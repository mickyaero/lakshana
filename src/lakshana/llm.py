"""Thin multi-provider LLM client.

Single entrypoint: ``call_llm(prompt, model, max_tokens, temperature) -> LLMResponse``.
Provider auto-detected from model name (e.g. ``groq/llama-3.3-70b-versatile``).

Supported providers (each is an optional install):
    anthropic   →  pip install lakshana[anthropic]
    openai      →  pip install lakshana[openai]
    groq        →  pip install lakshana[openai]   (OpenAI-compatible)
    cerebras    →  pip install lakshana[openai]   (OpenAI-compatible)
    openrouter  →  pip install lakshana[openai]   (OpenAI-compatible)
    ollama      →  pip install lakshana[openai]   (local, OpenAI-compatible)
    google      →  pip install lakshana[google]
"""

from __future__ import annotations

import logging
import os
import re as _re
import time as _time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ANTHROPIC = "anthropic"
OPENAI = "openai"
GOOGLE = "google"
GROQ = "groq"
CEREBRAS = "cerebras"
OPENROUTER = "openrouter"
OLLAMA = "ollama"

_KNOWN_PREFIXES = {ANTHROPIC, OPENAI, GOOGLE, GROQ, CEREBRAS, OPENROUTER, OLLAMA}

ENV_VARS = {
    ANTHROPIC: "ANTHROPIC_API_KEY",
    OPENAI: "OPENAI_API_KEY",
    GOOGLE: "GOOGLE_API_KEY",
    GROQ: "GROQ_API_KEY",
    CEREBRAS: "CEREBRAS_API_KEY",
    OPENROUTER: "OPENROUTER_API_KEY",
    OLLAMA: "OLLAMA_ENDPOINT",  # endpoint URL, not a key
}

_OPENAI_COMPAT_BASE_URLS = {
    GROQ: "https://api.groq.com/openai/v1",
    CEREBRAS: "https://api.cerebras.ai/v1",
    OPENROUTER: "https://openrouter.ai/api/v1",
}


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str


def detect_provider(model: str) -> str:
    """Detect the provider from a model name.

    Honors an explicit ``provider/model`` prefix first, then falls back to
    name heuristics. Defaults to Anthropic if nothing else matches.
    """
    if "/" in model:
        prefix = model.split("/", 1)[0].lower()
        if prefix in _KNOWN_PREFIXES:
            return prefix

    m = model.lower()
    if "claude" in m or "anthropic" in m:
        return ANTHROPIC
    if "gpt" in m and "oss" not in m:
        return OPENAI
    if m.startswith(("o1", "o3")):
        return OPENAI
    if "gemini" in m and ":free" not in m:
        return GOOGLE
    if any(x in m for x in ("nuextract", "ollama")):
        return OLLAMA
    if ":free" in m:
        return OPENROUTER
    if any(x in m for x in ("llama", "mixtral", "gemma", "qwen", "mistral")):
        return GROQ
    if "cerebras" in m or "gpt-oss" in m:
        return CEREBRAS
    return ANTHROPIC


def call_llm(
    prompt: str,
    model: str = "groq/llama-3.3-70b-versatile",
    max_tokens: int = 4096,
    temperature: float = 0.0,
    provider: str | None = None,
    max_retries: int = 3,
) -> LLMResponse:
    """Call an LLM with a single user prompt. Retries on rate-limit errors.

    Raises:
        TypeError: if ``prompt`` is not a string.
        ValueError: if the model can't be routed to any provider, or the
            required API-key environment variable is unset.
    """
    if not isinstance(prompt, str):
        raise TypeError(f"prompt must be a str, got {type(prompt).__name__}")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be a non-empty string (e.g. 'groq/llama-3.3-70b-versatile')")

    # If the caller used an explicit `provider/model` prefix, that's an
    # opt-in signal — accept it. Otherwise we heuristic-match.
    explicit_prefix = False
    if "/" in model:
        prefix = model.split("/", 1)[0].lower()
        if prefix in _KNOWN_PREFIXES:
            explicit_prefix = True

    if provider is None:
        provider = detect_provider(model)
        # When the heuristic falls back to ANTHROPIC for a string that has
        # no recognisable signal AND no explicit prefix, that's almost
        # always a typo — surface it rather than greeting the user with
        # an opaque "No API key" message later.
        if not explicit_prefix and provider == ANTHROPIC:
            m = model.lower()
            has_signal = any(s in m for s in (
                "claude", "anthropic", "gpt", "o1", "o3", "gemini", "llama",
                "mixtral", "gemma", "qwen", "mistral", "nuextract", "deepseek",
            ))
            if not has_signal:
                raise ValueError(
                    f"Unknown model '{model}'. Lakshana could not infer a provider. "
                    f"Prefix the model with one of {sorted(_KNOWN_PREFIXES)}, "
                    f"e.g. 'openai/{model}' or 'groq/{model}'."
                )

    if "/" in model:
        prefix = model.split("/", 1)[0].lower()
        if prefix in _KNOWN_PREFIXES:
            model = model.split("/", 1)[1]

    if provider == OLLAMA:
        api_key = "ollama"
    else:
        env_var = ENV_VARS.get(provider)
        api_key = os.environ.get(env_var, "") if env_var else ""
        if not api_key:
            raise ValueError(
                f"No API key for provider '{provider}'. Set {env_var} in your environment."
            )

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            if provider == ANTHROPIC:
                return _call_anthropic(prompt, model, max_tokens, temperature, api_key)
            if provider == GOOGLE:
                return _call_google(prompt, model, max_tokens, temperature, api_key)
            if provider == OLLAMA:
                endpoint = os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434")
                base_url = endpoint.rstrip("/") + "/v1"
                return _call_openai(
                    prompt, model, max_tokens, temperature,
                    api_key="ollama", base_url=base_url, provider_name=OLLAMA,
                )
            if provider in _OPENAI_COMPAT_BASE_URLS:
                return _call_openai(
                    prompt, model, max_tokens, temperature, api_key,
                    base_url=_OPENAI_COMPAT_BASE_URLS[provider], provider_name=provider,
                )
            if provider == OPENAI:
                return _call_openai(prompt, model, max_tokens, temperature, api_key)
            raise ValueError(f"Unknown provider: {provider}")
        except Exception as e:
            last_error = e
            if attempt >= max_retries or not _is_transient(e):
                raise
            delay = _retry_delay(e, attempt)
            logger.info(
                "Transient %s on %s (attempt %d/%d), retrying in %.1fs",
                type(e).__name__, provider, attempt + 1, max_retries, delay,
            )
            _time.sleep(delay)

    assert last_error is not None
    raise last_error


# Retryable conditions worth backing off on, across every provider.
# Includes 429 (rate limit), 5xx server errors, common transient names,
# connection drops, and Anthropic's 529 overloaded code.
_TRANSIENT_SUBSTRINGS = (
    "429", "rate limit", "rate_limit",
    "500", "502", "503", "504", "529",
    "overloaded", "unavailable", "service_unavailable",
    "timeout", "timed out", "connection reset", "connection error",
    "remote end closed", "temporarily unavailable", "internal server error",
    "bad gateway", "gateway timeout",
)


def _is_transient(exc: Exception) -> bool:
    """True if ``exc`` looks like something a retry can recover from."""
    # Type-based detection — works even when the message is opaque
    name = type(exc).__name__.lower()
    if any(s in name for s in ("timeout", "connectionerror", "apiconnection", "apitimeout")):
        return True
    # Anthropic / OpenAI SDK-specific status codes
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, int) and (status == 429 or 500 <= status < 600):
        return True
    # String fallback (covers most provider error messages)
    msg = str(exc).lower()
    return any(s in msg for s in _TRANSIENT_SUBSTRINGS)


def _retry_delay(exc: Exception, attempt: int) -> float:
    """Compute backoff delay. Honors Retry-After / 'try again in Ns' hints."""
    # Exponential floor: 2, 4, 8, 16, 30 seconds
    delay = min(2 ** (attempt + 1), 30)
    msg = str(exc).lower()
    m = _re.search(r"try again in (\d+(?:\.\d+)?)\s*s", msg)
    if m:
        delay = max(delay, float(m.group(1)) + 0.5)
    # Honor Retry-After header if the SDK surfaced it on the exception
    retry_after = getattr(exc, "retry_after", None)
    if isinstance(retry_after, (int, float)) and retry_after > 0:
        delay = max(delay, float(retry_after) + 0.5)
    return min(delay, 60.0)


def _call_anthropic(prompt, model, max_tokens, temperature, api_key):
    try:
        import anthropic
    except ImportError as e:
        raise ImportError("Install the Anthropic provider: pip install lakshana[anthropic]") from e
    client = anthropic.Anthropic(api_key=api_key, timeout=120.0)
    response = client.messages.create(
        model=model, max_tokens=max_tokens, temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = getattr(response, "usage", None)
    return LLMResponse(
        text=response.content[0].text.strip(),
        input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
        output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        model=model,
        provider=ANTHROPIC,
    )


def _call_openai(prompt, model, max_tokens, temperature, api_key, base_url=None, provider_name=OPENAI):
    try:
        import openai
    except ImportError as e:
        raise ImportError("Install the OpenAI-compatible provider: pip install lakshana[openai]") from e
    kwargs = {"api_key": api_key, "timeout": 120.0}
    if base_url:
        kwargs["base_url"] = base_url
    client = openai.OpenAI(**kwargs)
    response = client.chat.completions.create(
        model=model, max_tokens=max_tokens, temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = response.usage
    return LLMResponse(
        text=response.choices[0].message.content.strip(),
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
        model=model,
        provider=provider_name,
    )


def _call_google(prompt, model, max_tokens, temperature, api_key):
    try:
        import google.generativeai as genai
    except ImportError as e:
        raise ImportError("Install the Google provider: pip install lakshana[google]") from e
    genai.configure(api_key=api_key)
    gmodel = genai.GenerativeModel(model)
    response = gmodel.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            max_output_tokens=max_tokens, temperature=temperature,
        ),
    )
    text = response.text.strip() if response.text else ""
    if not text:
        raise ValueError("Google API returned empty response")
    inp, out = 0, 0
    try:
        usage = response.usage_metadata
        inp = getattr(usage, "prompt_token_count", 0) or 0
        out = getattr(usage, "candidates_token_count", 0) or 0
    except Exception:
        pass
    return LLMResponse(text=text, input_tokens=inp, output_tokens=out, model=model, provider=GOOGLE)

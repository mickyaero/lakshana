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
    """Call an LLM with a single user prompt. Retries on rate-limit errors."""
    if provider is None:
        provider = detect_provider(model)

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
            err = str(e).lower()
            if not ("429" in err or "rate limit" in err or "rate_limit" in err) or attempt >= max_retries:
                raise
            delay = 2 ** (attempt + 1)
            m = _re.search(r"try again in (\d+(?:\.\d+)?)\s*s", err)
            if m:
                delay = max(delay, float(m.group(1)) + 0.5)
            delay = min(delay, 30)
            logger.info("Rate limited (attempt %d/%d), retrying in %.1fs", attempt + 1, max_retries, delay)
            _time.sleep(delay)

    assert last_error is not None
    raise last_error


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

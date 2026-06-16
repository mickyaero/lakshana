"""Internal utilities used by core.

- ``get_embedding_model``: lazy thread-safe SentenceTransformer loader.
- ``estimate_context_limit``: model-name → input character budget.
- ``parse_json_robust``: resilient JSON parsing for truncated LLM output.
"""

from __future__ import annotations

import json
import logging
import threading

logger = logging.getLogger(__name__)

_model = None
_model_lock = threading.Lock()


def get_embedding_model():
    """Return a cached SentenceTransformer (``all-MiniLM-L6-v2``)."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError("Install sentence-transformers: pip install sentence-transformers") from e
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        return _model


_MODEL_CONTEXT = {
    "llama-3.3-70b": 8192,
    "llama-3.1-8b": 8192,
    "llama-3.1-70b": 8192,
    "llama-4-scout": 16384,
    "mixtral": 32768,
    "gemma": 8192,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "o1": 128000,
    "o3": 128000,
    "claude": 200000,
    "gemini": 100000,
    "deepseek": 64000,
    "qwen": 32768,
    "mistral": 32768,
}


def estimate_context_limit(model: str) -> int:
    """Approximate input character budget for a model. Defaults to ~12K chars."""
    m = model.lower()
    for key, tokens in _MODEL_CONTEXT.items():
        if key in m:
            return int(tokens * 4 * 0.5)
    return 12000


def _balance_json(candidate: str) -> str:
    """Close unbalanced braces/brackets in truncated JSON."""
    if candidate.count('"') % 2 != 0:
        candidate += '"'

    stack: list[str] = []
    in_string = False
    escape = False
    for ch in candidate:
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ("{", "["):
            stack.append(ch)
        elif ch == "}":
            if stack and stack[-1] == "{":
                stack.pop()
        elif ch == "]":
            if stack and stack[-1] == "[":
                stack.pop()

    for opener in reversed(stack):
        candidate += "}" if opener == "{" else "]"
    return candidate


def parse_json_robust(raw: str) -> dict:
    """Parse JSON with recovery for truncated/malformed LLM output."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    if start < 0:
        raise json.JSONDecodeError("No JSON object found", raw, 0)

    end = raw.rfind("}")
    if end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass

    candidate = _balance_json(raw[start:])
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    max_attempts = min(200, len(raw) - start)
    for end_offset in range(len(raw), max(start, len(raw) - max_attempts), -1):
        candidate = _balance_json(raw[start:end_offset])
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise json.JSONDecodeError("Could not recover JSON", raw, 0)

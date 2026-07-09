"""Shared HTTP client construction + retry wrapper for every API call in the
pipeline (ASR, GPT text extraction, Gemini vision). Centralizing this means
every stage gets the same timeout/retry/error-logging behavior for free.
"""
import time
from typing import Any, Callable, TypeVar

from openai import OpenAI

import config

logger = config.setup_logging("llm_client")

T = TypeVar("T")


def call_with_retries(
    func: Callable[..., T],
    *args: Any,
    max_retries: int = config.MAX_RETRIES,
    backoff_seconds: float = config.RETRY_BACKOFF_SECONDS,
    what: str = "API call",
    **kwargs: Any,
) -> T:
    """Retries `func(*args, **kwargs)` with exponential backoff.

    Treats 4xx auth/permission errors (401/403) as non-retryable since
    retrying a bad key just burns time - fails fast with a clear message
    instead.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - deliberately broad, this is the top-level API boundary
            last_exc = exc
            status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
            if status in (401, 403):
                logger.error(
                    "%s failed with auth error (status=%s) - not retrying, check API key/base_url. %s",
                    what, status, exc,
                )
                raise
            wait = backoff_seconds * (2 ** (attempt - 1))
            logger.warning(
                "%s failed (attempt %d/%d): %s. Retrying in %.1fs...",
                what, attempt, max_retries, exc, wait,
            )
            if attempt < max_retries:
                time.sleep(wait)
    logger.error("%s failed after %d attempts, giving up.", what, max_retries)
    raise last_exc  # type: ignore[misc]


def get_asr_client() -> OpenAI:
    return OpenAI(
        api_key=config.ASR_API_KEY,
        base_url=config.ASR_BASE_URL,
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )


def get_openai_client() -> OpenAI:
    return OpenAI(
        api_key=config.OPENAI_API_KEY,
        base_url=config.OPENAI_BASE_URL,
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )


def get_gemini_client() -> OpenAI:
    """Gemini is reached through the same OpenAI-compatible gateway protocol,
    just with a different key/base_url/model - see stage4_visual.py."""
    return OpenAI(
        api_key=config.GEMINI_API_KEY,
        base_url=config.GEMINI_BASE_URL,
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )

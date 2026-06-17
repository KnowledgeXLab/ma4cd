import os
from pathlib import Path
from typing import Optional, Tuple


def _load_local_dotenv() -> None:
    """Load project root `.env` so keys need not be exported in the shell."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parent.parent
    path = root / ".env"
    if path.is_file():
        load_dotenv(path, override=False)


_load_local_dotenv()


def get_llm_api_key(explicit: Optional[str] = None) -> Optional[str]:
    """Resolve the API key from explicit args or supported env vars."""
    # If the MA4CD gateway/base URL is configured, prefer the matching MA4CD key.
    if explicit:
        return explicit
    if os.getenv("MA4CD_LLM_BASE_URL"):
        return (
            os.getenv("MA4CD_LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("LLM_API_KEY")
        )
    return (
        os.getenv("MA4CD_LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("LLM_API_KEY")
    )


def get_llm_base_url(explicit: Optional[str] = None) -> Optional[str]:
    """Resolve the base URL from explicit args or supported env vars."""
    return (
        explicit
        or os.getenv("MA4CD_LLM_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or os.getenv("LLM_BASE_URL")
    )


def normalize_model_for_endpoint(
    model: Optional[str],
    base_url: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """
    Normalize model name against endpoint type.

    Returns:
        (resolved_model, fallback_reason)
        - fallback_reason is None when no fallback is applied.
    """
    resolved_base = get_llm_base_url(base_url)
    resolved_model = (model or "").strip()

    if not resolved_model:
        resolved_model = os.getenv("MA4CD_DEFAULT_MODEL", "deepseek-chat")

    # When no custom gateway/base_url is configured, requests go to OpenAI.
    # deepseek-* model names are not valid there and will produce model_not_found.
    if not resolved_base and resolved_model.lower().startswith("deepseek"):
        fallback_model = os.getenv("MA4CD_OPENAI_FALLBACK_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        reason = f"no_base_url_deepseek_incompatible:{resolved_model}->{fallback_model}"
        return fallback_model, reason

    return resolved_model, None

"""
Real MinerU-HTML adapter for benchmark `module:function` hook.

Callable exposed:
    extract_with_mineru_html(url: str, html: str) -> dict
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any, Dict, Optional

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None

from mineru_html import MinerUHTMLConfig, MinerUHTML_OpenAI
from mineru_html.base import MinerUHTMLInput

try:
    from utils.env import get_llm_api_key, get_llm_base_url
except Exception:
    # fallback for direct script usage
    def get_llm_api_key(value: Optional[str] = None) -> Optional[str]:
        return value or os.getenv("OPENAI_API_KEY")

    def get_llm_base_url(value: Optional[str] = None) -> Optional[str]:
        return value or os.getenv("OPENAI_BASE_URL")


def _html_title(raw_html: str) -> str:
    if not raw_html:
        return ""
    if BeautifulSoup is None:
        m = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.I | re.S)
        return re.sub(r"\s+", " ", (m.group(1) if m else "")).strip()[:200]
    soup = BeautifulSoup(raw_html, "html.parser")
    if soup.title:
        return soup.title.get_text(" ", strip=True)[:200]
    return ""


def _html_to_text(raw_html: str) -> str:
    if not raw_html:
        return ""
    if BeautifulSoup is None:
        text = re.sub(r"<(script|style|noscript).*?>.*?</\1>", " ", raw_html, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


@lru_cache(maxsize=1)
def _get_extractor() -> MinerUHTML_OpenAI:
    api_key = get_llm_api_key(os.getenv("MA4CD_MINERU_HTML_API_KEY"))
    base_url = get_llm_base_url(os.getenv("MA4CD_MINERU_HTML_BASE_URL"))
    model = os.getenv("MA4CD_MINERU_HTML_MODEL", os.getenv("MA4CD_MINER_BIG_MODEL", "deepseek-chat"))

    if not api_key:
        raise RuntimeError(
            "MinerU-HTML adapter requires API key. "
            "Set OPENAI_API_KEY or MA4CD_MINERU_HTML_API_KEY."
        )
    if not base_url:
        base_url = "https://api.openai.com/v1"

    config = MinerUHTMLConfig(
        use_fall_back=os.getenv("MA4CD_MINERU_HTML_FALLBACK", "trafilatura"),
        early_load=str(os.getenv("MA4CD_MINERU_HTML_EARLY_LOAD", "1")).lower() in ("1", "true", "yes", "on"),
        prompt_version=os.getenv("MA4CD_MINERU_HTML_PROMPT_VERSION", "v2"),
        response_format=os.getenv("MA4CD_MINERU_HTML_RESPONSE_FORMAT", "json"),
        output_format=os.getenv("MA4CD_MINERU_HTML_OUTPUT_FORMAT", "mm_md"),
    )
    return MinerUHTML_OpenAI(
        base_url=base_url,
        sk=api_key,
        model=model,
        config=config,
        retry_times=int(os.getenv("MA4CD_MINERU_HTML_RETRY_TIMES", "3")),
    )


def extract_with_mineru_html(url: str, html: str) -> Dict[str, Any]:
    """
    Adapter signature used by benchmark:
        (url, html) -> {"text": str, "title": str, "llm_calls": int, ...}
    """
    extractor = _get_extractor()

    cases = extractor.process([MinerUHTMLInput(raw_html=html, url=url)])
    case = cases[0] if cases else None

    if case is None:
        return {
            "text": "",
            "title": _html_title(html),
            "llm_calls": 0,
            "error": "no_case_returned",
        }

    main_html = case.main_html or ""
    main_content = ""
    try:
        if getattr(case, "output_data", None) is not None:
            main_content = str(getattr(case.output_data, "main_content", "") or "")
    except Exception:
        main_content = ""

    text = (main_content or _html_to_text(main_html or html)).strip()
    title = _html_title(main_html or html)
    llm_calls = 1 if getattr(case, "generate_output", None) is not None else 0
    err = str(getattr(case, "error", "") or "")

    return {
        "text": text,
        "title": title,
        "llm_calls": llm_calls,
        "error": err,
        "source": "mineru_html_openai",
    }

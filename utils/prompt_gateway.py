from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Union


def extract_first_json(text: str) -> Optional[Union[Dict[str, Any], list]]:
    if not isinstance(text, str) or not text.strip():
        return None

    raw = text.strip()
    try:
        return json.loads(raw)
    except Exception:
        pass

    if "```" in raw:
        cleaned = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except Exception:
            raw = cleaned

    obj_match = re.search(r"(\{.*\})", raw, re.DOTALL)
    if obj_match:
        candidate = obj_match.group(1)
        try:
            return json.loads(candidate)
        except Exception:
            # remove trailing commas
            candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                return json.loads(candidate)
            except Exception:
                return None

    arr_match = re.search(r"(\[.*\])", raw, re.DOTALL)
    if arr_match:
        candidate = arr_match.group(1)
        try:
            return json.loads(candidate)
        except Exception:
            candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                return json.loads(candidate)
            except Exception:
                return None

    return None


def invoke_json_contract(
    llm: Any,
    system_prompt: str,
    user_prompt: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Unified sync entry for contract-oriented JSON calls across agents.
    Returns a dict whenever possible; falls back to {"error": "..."}.
    """
    kwargs: Dict[str, Any] = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    try:
        if hasattr(llm, "invoke_json"):
            try:
                result = llm.invoke_json(system_prompt, user_prompt, **kwargs)
            except TypeError:
                result = llm.invoke_json(system_prompt, user_prompt)
        else:
            try:
                result = llm.invoke(system_prompt=system_prompt, user_prompt=user_prompt, **kwargs)
            except TypeError:
                result = llm.invoke(system_prompt, user_prompt)

        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            return {"items": result}
        if isinstance(result, str):
            parsed = extract_first_json(result)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {"items": parsed}
            return {"content": result}
        return {"content": str(result)}
    except Exception as e:
        return {"error": str(e)}


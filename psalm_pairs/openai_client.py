"""Utility helpers for talking to the OpenAI Responses API."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from openai import OpenAI

OPENAI_KEY_PATH = Path.home() / ".openai.key"


def load_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    if not OPENAI_KEY_PATH.exists():
        raise FileNotFoundError(
            f"Expected to find OpenAI API key at {OPENAI_KEY_PATH}. Set OPENAI_API_KEY or create the file."
        )
    key = OPENAI_KEY_PATH.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError(f"{OPENAI_KEY_PATH} is empty")
    os.environ["OPENAI_API_KEY"] = key
    return key


def build_client() -> OpenAI:
    load_api_key()
    return OpenAI()


def response_to_dict(response: Any) -> Dict[str, Any]:
    """Return a JSON-serialisable payload for the response."""
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if hasattr(response, "to_dict"):
        return response.to_dict()
    # Fallback: try JSON dumps
    try:
        return json.loads(response.model_dump_json())  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover - last resort
        raise RuntimeError("Could not serialise OpenAI response") from exc


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_usage_tokens(response_dict: Dict[str, Any]) -> Dict[str, Optional[int]]:
    """Extract token accounting from a response payload.

    The Responses API has evolved a few times, so we defensively look for a
    couple of different field names when determining reasoning/non-reasoning
    token counts.
    """

    usage = response_dict.get("usage") or {}
    output_details = usage.get("output_tokens_details") or {}

    total_tokens = _coerce_int(
        usage.get("total_tokens")
        or usage.get("output_tokens")
        or usage.get("completion_tokens")
    )

    reasoning_tokens = _coerce_int(
        output_details.get("reasoning_tokens") or usage.get("reasoning_tokens")
    )

    text_tokens = _coerce_int(output_details.get("text_tokens"))
    non_reasoning_tokens: Optional[int]
    if text_tokens is not None:
        non_reasoning_tokens = text_tokens
    elif total_tokens is not None and reasoning_tokens is not None:
        non_reasoning_tokens = max(total_tokens - reasoning_tokens, 0)
    else:
        non_reasoning_tokens = _coerce_int(output_details.get("non_reasoning_tokens"))

    return {
        "total_tokens": total_tokens,
        "reasoning_tokens": reasoning_tokens,
        "non_reasoning_tokens": non_reasoning_tokens,
    }

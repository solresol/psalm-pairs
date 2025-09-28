"""Utility helpers for talking to the OpenAI Responses API."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

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

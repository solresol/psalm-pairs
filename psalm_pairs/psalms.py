"""Helpers for loading Psalm JSON data and formatting prompts."""
from __future__ import annotations

import json
from functools import lru_cache
from . import PROJECT_ROOT

PSALM_DIR = PROJECT_ROOT / "psalms_json"


@lru_cache(maxsize=None)
def load_psalm(psalm_number: int) -> dict:
    path = PSALM_DIR / f"psalm_{psalm_number:03d}.json"
    if not path.exists():
        raise FileNotFoundError(f"Could not find {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def format_psalm(psalm_number: int) -> str:
    data = load_psalm(psalm_number)
    lines = [f"Psalm {psalm_number}"]
    for verse in data.get("verses", []):
        vnum = verse.get("v")
        text = verse.get("text_he", "")
        lines.append(f"{vnum}. {text}")
    return "\n".join(lines)


def all_psalm_numbers() -> list[int]:
    files = sorted(PSALM_DIR.glob("psalm_*.json"))
    numbers: list[int] = []
    for path in files:
        try:
            num = int(path.stem.split("_")[1])
            numbers.append(num)
        except (IndexError, ValueError):
            continue
    return sorted(numbers)

"""Core package for Psalm pair generation and evaluation."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = (DATA_DIR / "psalm_pairs.sqlite3").resolve()

__all__ = ["DB_PATH", "DATA_DIR", "PACKAGE_ROOT", "PROJECT_ROOT"]

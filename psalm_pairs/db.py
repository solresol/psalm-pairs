"""SQLite helpers for tracking Psalm pair generation and evaluations."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from . import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS pair_arguments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    psalm_x INTEGER NOT NULL,
    psalm_y INTEGER NOT NULL,
    prompt TEXT NOT NULL,
    response_text TEXT NOT NULL,
    response_json TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (psalm_x, psalm_y)
);

CREATE TABLE IF NOT EXISTS pair_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id INTEGER NOT NULL,
    score REAL NOT NULL,
    justification TEXT NOT NULL,
    evaluator_model TEXT NOT NULL,
    evaluation_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(pair_id) REFERENCES pair_arguments(id) ON DELETE CASCADE,
    UNIQUE (pair_id)
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


@contextmanager
def get_conn(db_path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def existing_pairs(conn: sqlite3.Connection) -> set[tuple[int, int]]:
    cur = conn.execute("SELECT psalm_x, psalm_y FROM pair_arguments")
    return {(row[0], row[1]) for row in cur}


def insert_pair_argument(
    conn: sqlite3.Connection,
    *,
    psalm_x: int,
    psalm_y: int,
    prompt: str,
    response_text: str,
    response_json: dict,
    model: str,
) -> int:
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO pair_arguments
            (psalm_x, psalm_y, prompt, response_text, response_json, model, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            psalm_x,
            psalm_y,
            prompt,
            response_text,
            json.dumps(response_json, ensure_ascii=False),
            model,
            datetime.utcnow().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    if cur.lastrowid:
        return cur.lastrowid
    # fetch id if already existed
    cur = conn.execute(
        "SELECT id FROM pair_arguments WHERE psalm_x = ? AND psalm_y = ?",
        (psalm_x, psalm_y),
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("Failed to persist pair argument and could not recover existing ID")
    return int(row[0])


def pending_pairs(conn: sqlite3.Connection, limit: int) -> list[tuple[int, int]]:
    completed = existing_pairs(conn)
    pairs: list[tuple[int, int]] = []
    for x in range(1, 151):
        for y in range(1, 151):
            if x == y:
                continue
            pair = (x, y)
            if pair in completed:
                continue
            pairs.append(pair)
            if len(pairs) >= limit:
                return pairs
    return pairs


def pending_evaluations(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    cur = conn.execute(
        """
        SELECT pa.*
        FROM pair_arguments pa
        LEFT JOIN pair_evaluations pe ON pe.pair_id = pa.id
        WHERE pe.id IS NULL
        ORDER BY pa.id ASC
        LIMIT ?
        """,
        (limit,),
    )
    return list(cur)


def insert_evaluation(
    conn: sqlite3.Connection,
    *,
    pair_id: int,
    score: float,
    justification: str,
    evaluator_model: str,
    evaluation_json: dict,
) -> int:
    cur = conn.execute(
        """
        INSERT OR REPLACE INTO pair_evaluations
            (pair_id, score, justification, evaluator_model, evaluation_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            pair_id,
            score,
            justification,
            evaluator_model,
            json.dumps(evaluation_json, ensure_ascii=False),
            datetime.utcnow().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return cur.lastrowid


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    cur = conn.execute("SELECT COUNT(*) FROM pair_arguments")
    generated = int(cur.fetchone()[0])
    cur = conn.execute("SELECT COUNT(*) FROM pair_evaluations")
    evaluated = int(cur.fetchone()[0])
    total_pairs = 150 * 149
    return {"generated": generated, "evaluated": evaluated, "total_pairs": total_pairs}


def recent_arguments(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    cur = conn.execute(
        """
        SELECT pa.id, pa.psalm_x, pa.psalm_y, pa.response_text, pa.created_at,
               pe.score, pe.justification, pe.created_at AS evaluated_at
        FROM pair_arguments pa
        LEFT JOIN pair_evaluations pe ON pe.pair_id = pa.id
        ORDER BY pa.id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return list(cur)

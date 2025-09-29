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
    total_tokens INTEGER,
    reasoning_tokens INTEGER,
    non_reasoning_tokens INTEGER,
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
    total_tokens INTEGER,
    reasoning_tokens INTEGER,
    non_reasoning_tokens INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(pair_id) REFERENCES pair_arguments(id) ON DELETE CASCADE,
    UNIQUE (pair_id)
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    ensure_column(conn, "pair_arguments", "total_tokens", "INTEGER")
    ensure_column(conn, "pair_arguments", "reasoning_tokens", "INTEGER")
    ensure_column(conn, "pair_arguments", "non_reasoning_tokens", "INTEGER")
    ensure_column(conn, "pair_evaluations", "total_tokens", "INTEGER")
    ensure_column(conn, "pair_evaluations", "reasoning_tokens", "INTEGER")
    ensure_column(conn, "pair_evaluations", "non_reasoning_tokens", "INTEGER")
    conn.commit()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    cur = conn.execute(f"PRAGMA table_info({table})")
    if any(row[1] == column for row in cur):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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
    total_tokens: Optional[int] = None,
    reasoning_tokens: Optional[int] = None,
    non_reasoning_tokens: Optional[int] = None,
) -> int:
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO pair_arguments
            (psalm_x, psalm_y, prompt, response_text, response_json, model,
             total_tokens, reasoning_tokens, non_reasoning_tokens, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            psalm_x,
            psalm_y,
            prompt,
            response_text,
            json.dumps(response_json, ensure_ascii=False),
            model,
            total_tokens,
            reasoning_tokens,
            non_reasoning_tokens,
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
    if any(value is not None for value in (total_tokens, reasoning_tokens, non_reasoning_tokens)):
        conn.execute(
            """
            UPDATE pair_arguments
            SET
                total_tokens = COALESCE(?, total_tokens),
                reasoning_tokens = COALESCE(?, reasoning_tokens),
                non_reasoning_tokens = COALESCE(?, non_reasoning_tokens)
            WHERE psalm_x = ? AND psalm_y = ?
            """,
            (total_tokens, reasoning_tokens, non_reasoning_tokens, psalm_x, psalm_y),
        )
        conn.commit()
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
    total_tokens: Optional[int] = None,
    reasoning_tokens: Optional[int] = None,
    non_reasoning_tokens: Optional[int] = None,
) -> int:
    cur = conn.execute(
        """
        INSERT OR REPLACE INTO pair_evaluations
            (pair_id, score, justification, evaluator_model, evaluation_json,
             total_tokens, reasoning_tokens, non_reasoning_tokens, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pair_id,
            score,
            justification,
            evaluator_model,
            json.dumps(evaluation_json, ensure_ascii=False),
            total_tokens,
            reasoning_tokens,
            non_reasoning_tokens,
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


def _aggregate_token_columns(conn: sqlite3.Connection, table: str) -> tuple[int, int, int]:
    query = f"""
        SELECT
            COALESCE(SUM(total_tokens), 0) AS total,
            COALESCE(SUM(reasoning_tokens), 0) AS reasoning,
            COALESCE(SUM(
                CASE
                    WHEN non_reasoning_tokens IS NOT NULL THEN non_reasoning_tokens
                    WHEN total_tokens IS NOT NULL THEN total_tokens - COALESCE(reasoning_tokens, 0)
                    ELSE 0
                END
            ), 0) AS non_reasoning
        FROM {table}
    """
    row = conn.execute(query).fetchone()
    total = int(row[0] or 0)
    reasoning = int(row[1] or 0)
    non_reasoning = int(row[2] or 0)
    return total, reasoning, non_reasoning


def token_usage_stats(conn: sqlite3.Connection) -> dict:
    generation_total, generation_reasoning, generation_non_reasoning = _aggregate_token_columns(
        conn, "pair_arguments"
    )
    evaluation_total, evaluation_reasoning, evaluation_non_reasoning = _aggregate_token_columns(
        conn, "pair_evaluations"
    )

    overall_total = generation_total + evaluation_total
    overall_reasoning = generation_reasoning + evaluation_reasoning
    overall_non_reasoning = generation_non_reasoning + evaluation_non_reasoning

    daily_rows = conn.execute(
        """
        SELECT
            day,
            SUM(generation_total) AS generation_total,
            SUM(evaluation_total) AS evaluation_total,
            SUM(generation_reasoning) AS generation_reasoning,
            SUM(evaluation_reasoning) AS evaluation_reasoning,
            SUM(generation_non_reasoning) AS generation_non_reasoning,
            SUM(evaluation_non_reasoning) AS evaluation_non_reasoning
        FROM (
            SELECT
                DATE(created_at) AS day,
                COALESCE(total_tokens, 0) AS generation_total,
                0 AS evaluation_total,
                COALESCE(reasoning_tokens, 0) AS generation_reasoning,
                0 AS evaluation_reasoning,
                COALESCE(
                    CASE
                        WHEN non_reasoning_tokens IS NOT NULL THEN non_reasoning_tokens
                        WHEN total_tokens IS NOT NULL THEN total_tokens - COALESCE(reasoning_tokens, 0)
                        ELSE 0
                    END,
                    0
                ) AS generation_non_reasoning,
                0 AS evaluation_non_reasoning
            FROM pair_arguments
            UNION ALL
            SELECT
                DATE(created_at) AS day,
                0 AS generation_total,
                COALESCE(total_tokens, 0) AS evaluation_total,
                0 AS generation_reasoning,
                COALESCE(reasoning_tokens, 0) AS evaluation_reasoning,
                0 AS generation_non_reasoning,
                COALESCE(
                    CASE
                        WHEN non_reasoning_tokens IS NOT NULL THEN non_reasoning_tokens
                        WHEN total_tokens IS NOT NULL THEN total_tokens - COALESCE(reasoning_tokens, 0)
                        ELSE 0
                    END,
                    0
                ) AS evaluation_non_reasoning
            FROM pair_evaluations
        )
        GROUP BY day
        ORDER BY day ASC
        """
    ).fetchall()

    daily = []
    for row in daily_rows:
        day = row["day"]
        generation_total_day = int(row["generation_total"] or 0)
        evaluation_total_day = int(row["evaluation_total"] or 0)
        reasoning_total_day = int((row["generation_reasoning"] or 0) + (row["evaluation_reasoning"] or 0))
        non_reasoning_total_day = int(
            (row["generation_non_reasoning"] or 0) + (row["evaluation_non_reasoning"] or 0)
        )
        daily.append(
            {
                "day": day,
                "generation_total": generation_total_day,
                "evaluation_total": evaluation_total_day,
                "total": generation_total_day + evaluation_total_day,
                "reasoning_total": reasoning_total_day,
                "non_reasoning_total": non_reasoning_total_day,
            }
        )

    return {
        "generation_total": generation_total,
        "generation_reasoning": generation_reasoning,
        "generation_non_reasoning": generation_non_reasoning,
        "evaluation_total": evaluation_total,
        "evaluation_reasoning": evaluation_reasoning,
        "evaluation_non_reasoning": evaluation_non_reasoning,
        "overall_total": overall_total,
        "overall_reasoning": overall_reasoning,
        "overall_non_reasoning": overall_non_reasoning,
        "daily": daily,
    }

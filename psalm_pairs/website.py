"""Generate a static HTML summary of Psalm pair progress."""
from __future__ import annotations

import argparse
import datetime as dt
import html
from pathlib import Path
from typing import Iterable

from . import PROJECT_ROOT
from .db import connect, counts, recent_arguments

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "site"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>Psalm Pair Arguments</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; background: #f8f9fa; color: #111; }
    header { margin-bottom: 2rem; }
    .stats { display: flex; flex-wrap: wrap; gap: 1rem; }
    .card { background: white; border-radius: 8px; padding: 1rem 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    table { width: 100%; border-collapse: collapse; margin-top: 2rem; }
    th, td { padding: 0.5rem; border-bottom: 1px solid #ddd; text-align: left; }
    th { background: #eef2f7; }
    footer { margin-top: 3rem; font-size: 0.9rem; color: #555; }
  </style>
</head>
<body>
<header>
  <h1>Psalm Pair Arguments</h1>
  <p>Progress report generated on {generated_at} UTC.</p>
</header>
<section class=\"stats\">
  <div class=\"card\">
    <strong>{generated}</strong><br>Pairs generated
  </div>
  <div class=\"card\">
    <strong>{evaluated}</strong><br>Pairs evaluated
  </div>
  <div class=\"card\">
    <strong>{total_pairs}</strong><br>Total possible pairs
  </div>
  <div class=\"card\">
    <strong>{progress:.2f}%</strong><br>Generation complete
  </div>
  <div class=\"card\">
    <strong>{evaluation_progress:.2f}%</strong><br>Evaluations complete
  </div>
</section>
<section>
  <h2>Most recent arguments</h2>
  <table>
    <thead>
      <tr><th>ID</th><th>Pair</th><th>Generated</th><th>Evaluation</th><th>Excerpt</th></tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</section>
<footer>
  <p>This project explores narrative continuity within the Psalter by comparing every ordered pair of psalms.</p>
</footer>
</body>
</html>
"""


ROW_TEMPLATE = "<tr><td>{id}</td><td>{pair}</td><td>{created}</td><td>{evaluation}</td><td>{excerpt}</td></tr>"


def format_row(row) -> str:
    excerpt = ""
    if row["response_text"]:
        first_line = row["response_text"].strip().splitlines()[0]
        excerpt = html.escape(first_line[:160])
    evaluation = (
        f"Score {row['score']} on {row['evaluated_at']}" if row["score"] is not None else "Pending"
    )
    return ROW_TEMPLATE.format(
        id=row["id"],
        pair=f"{row['psalm_x']} → {row['psalm_y']}",
        created=row["created_at"],
        evaluation=html.escape(evaluation),
        excerpt=excerpt,
    )


def render_html(stats: dict, rows: Iterable[str]) -> str:
    generated_at = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    generated = stats["generated"]
    evaluated = stats["evaluated"]
    total_pairs = stats["total_pairs"]
    progress = 100 * generated / total_pairs if total_pairs else 0
    evaluation_progress = 100 * evaluated / total_pairs if total_pairs else 0
    return HTML_TEMPLATE.format(
        generated_at=generated_at,
        generated=generated,
        evaluated=evaluated,
        total_pairs=total_pairs,
        progress=progress,
        evaluation_progress=evaluation_progress,
        rows="\n      ".join(rows),
    )


def write_site(output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "index.html"
    with connect() as conn:
        stats = counts(conn)
        recent = recent_arguments(conn, limit=50)
    rows = [format_row(row) for row in recent]
    html_text = render_html(stats, rows)
    index_path.write_text(html_text, encoding="utf-8")
    return index_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for the generated site")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = write_site(args.output)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()

"""Generate a static HTML summary of Psalm pair progress."""
from __future__ import annotations

import argparse
import datetime as dt
import html
import sys
from pathlib import Path
from typing import Iterable

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from psalm_pairs import PROJECT_ROOT
    from psalm_pairs.db import connect, counts, recent_arguments, token_usage_stats
else:
    from . import PROJECT_ROOT
    from .db import connect, counts, recent_arguments, token_usage_stats

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "site"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>Psalm Pair Arguments</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f8f9fa; color: #111; }}
    header {{ margin-bottom: 2rem; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 1rem; }}
    .card {{ background: white; border-radius: 8px; padding: 1rem 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    .card small {{ display: block; color: #666; margin-top: 0.35rem; font-size: 0.85rem; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 2rem; }}
    th, td {{ padding: 0.5rem; border-bottom: 1px solid #ddd; text-align: left; }}
    th {{ background: #eef2f7; }}
    footer {{ margin-top: 3rem; font-size: 0.9rem; color: #555; }}
    nav {{ margin-bottom: 1.5rem; }}
    nav a {{ margin-right: 1rem; color: #0b7285; text-decoration: none; }}
    nav a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
<header>
  <h1>Psalm Pair Arguments</h1>
  <p>Progress report generated on {generated_at} UTC.</p>
</header>
<nav>
  <a href=\"index.html\">Overview</a>
  <a href=\"tokens.html\">Token usage</a>
</nav>
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
  <div class=\"card\">
    <strong>{overall_tokens}</strong><br>Total tokens used
    <small>Reasoning: {overall_reasoning}<br>Other: {overall_non_reasoning}</small>
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


TOKENS_TEMPLATE = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>Psalm Pair Token Usage</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f8f9fa; color: #111; }}
    header {{ margin-bottom: 2rem; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 2rem; }}
    th, td {{ padding: 0.6rem; border-bottom: 1px solid #ddd; text-align: right; }}
    th {{ background: #eef2f7; text-align: right; }}
    th:first-child, td:first-child {{ text-align: left; }}
    nav a {{ margin-right: 1rem; color: #0b7285; text-decoration: none; }}
    nav a:hover {{ text-decoration: underline; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; }}
    .card {{ background: white; border-radius: 8px; padding: 1rem 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    .card h3 {{ margin: 0 0 0.5rem; font-size: 1rem; color: #333; }}
    .card strong {{ font-size: 1.5rem; display: block; }}
    footer {{ margin-top: 3rem; font-size: 0.9rem; color: #555; }}
  </style>
</head>
<body>
<header>
  <h1>Token usage</h1>
  <p>Breakdown of model token consumption across argument generation and evaluation.</p>
</header>
<nav>
  <a href=\"index.html\">Overview</a>
  <a href=\"tokens.html\">Token usage</a>
</nav>
<section class=\"grid\">
  <div class=\"card\">
    <h3>Total tokens</h3>
    <strong>{overall_total}</strong>
    <p>Reasoning: {overall_reasoning}<br>Other: {overall_non_reasoning}</p>
  </div>
  <div class=\"card\">
    <h3>Generation tokens</h3>
    <strong>{generation_total}</strong>
    <p>Reasoning: {generation_reasoning}<br>Other: {generation_non_reasoning}</p>
  </div>
  <div class=\"card\">
    <h3>Evaluation tokens</h3>
    <strong>{evaluation_total}</strong>
    <p>Reasoning: {evaluation_reasoning}<br>Other: {evaluation_non_reasoning}</p>
  </div>
</section>
<section>
  <h2>Daily usage</h2>
  <table>
    <thead>
      <tr>
        <th>Date (UTC)</th>
        <th>Total tokens</th>
        <th>Reasoning tokens</th>
        <th>Other tokens</th>
        <th>Generation</th>
        <th>Evaluation</th>
      </tr>
    </thead>
    <tbody>
      {daily_rows}
    </tbody>
  </table>
</section>
<footer>
  <p>Token counts are pulled directly from the stored OpenAI responses.</p>
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


def render_html(stats: dict, rows: Iterable[str], tokens: dict) -> str:
    generated_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
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
        overall_tokens=tokens["overall_total"],
        overall_reasoning=tokens["overall_reasoning"],
        overall_non_reasoning=tokens["overall_non_reasoning"],
        rows="\n      ".join(rows),
    )


def write_site(output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "index.html"
    with connect() as conn:
        stats = counts(conn)
        recent = recent_arguments(conn, limit=50)
        tokens = token_usage_stats(conn)
    rows = [format_row(row) for row in recent]
    html_text = render_html(stats, rows, tokens)
    index_path.write_text(html_text, encoding="utf-8")
    tokens_path = output_dir / "tokens.html"
    daily_rows = [render_daily_row(row) for row in tokens["daily"]]
    tokens_html = render_tokens_html(tokens, daily_rows)
    tokens_path.write_text(tokens_html, encoding="utf-8")
    return index_path


def render_tokens_html(tokens: dict, daily_rows: Iterable[str]) -> str:
    return TOKENS_TEMPLATE.format(
        overall_total=tokens["overall_total"],
        overall_reasoning=tokens["overall_reasoning"],
        overall_non_reasoning=tokens["overall_non_reasoning"],
        generation_total=tokens["generation_total"],
        generation_reasoning=tokens["generation_reasoning"],
        generation_non_reasoning=tokens["generation_non_reasoning"],
        evaluation_total=tokens["evaluation_total"],
        evaluation_reasoning=tokens["evaluation_reasoning"],
        evaluation_non_reasoning=tokens["evaluation_non_reasoning"],
        daily_rows="\n      ".join(daily_rows),
    )


def render_daily_row(row: dict) -> str:
    return (
        "<tr>"
        f"<td>{row['day']}</td>"
        f"<td>{row['total']}</td>"
        f"<td>{row['reasoning_total']}</td>"
        f"<td>{row['non_reasoning_total']}</td>"
        f"<td>{row['generation_total']}</td>"
        f"<td>{row['evaluation_total']}</td>"
        "</tr>"
    )


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

"""Generate a static HTML summary of Psalm pair progress."""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import io
import json
import math
import sys
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import umap
from matplotlib import pyplot as plt

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from psalm_pairs import PROJECT_ROOT
    from psalm_pairs.db import (
        connect,
        counts,
        daily_progress,
        daily_progress,
        evaluation_scores_by_version,
        pair_details,
        recent_arguments,
        token_usage_stats,
    )
else:
    from . import PROJECT_ROOT
    from .db import (
        connect,
        counts,
        daily_progress,
        evaluation_scores_by_version,
        pair_details,
        recent_arguments,
        token_usage_stats,
    )

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "site"


DIAGNOSTICS_TEMPLATE = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>Psalm Pair Diagnostics</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f8f9fa; color: #111; }}
    header {{ margin-bottom: 2rem; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 1rem; }}
    .card {{ background: white; border-radius: 8px; padding: 1rem 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}

    .card small {{ display: block; color: #666; margin-top: 0.35rem; font-size: 0.85rem; }}

    .histograms {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1.5rem; margin-top: 1.5rem; }}
    .histogram-card {{ background: white; border-radius: 8px; padding: 1rem 1.25rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
    .histogram-card h3 {{ margin: 0; font-size: 1.1rem; color: #212529; }}
    .histogram-card p.meta {{ margin: 0.5rem 0 1rem; color: #495057; font-size: 0.9rem; }}
    .histogram-bars {{ list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.45rem; }}
    .histogram-bars li {{ display: grid; grid-template-columns: 1.8rem 1fr 2.8rem; align-items: center; gap: 0.6rem; font-size: 0.9rem; color: #495057; }}
    .histogram-bars .bucket {{ font-variant-numeric: tabular-nums; color: #343a40; }}
    .histogram-bars .bar-container {{ background: #e9ecef; border-radius: 4px; height: 12px; overflow: hidden; position: relative; }}
    .histogram-bars .bar {{ background: linear-gradient(90deg, #4263eb, #748ffc); height: 100%; display: block; border-radius: 4px; }}
    .histogram-bars .count {{ text-align: right; font-variant-numeric: tabular-nums; }}

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
  <h1>Diagnostics &amp; progress</h1>
  <p>Report generated on {generated_at} UTC.</p>
</header>
<nav>
  <a href=\"index.html\">Heatmap</a>
  <a href=\"diagnostics.html\">Diagnostics &amp; progress</a>
  <a href=\"tokens.html\">Token usage</a>
  <a href=\"umap.html\">UMAP visualizations</a>
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
    <strong>{generation_projection}</strong><br>Projected generation completion
    <small>{generation_projection_note}</small>
  </div>
  <div class=\"card\">
    <strong>{evaluation_projection}</strong><br>Projected evaluation completion
    <small>{evaluation_projection_note}</small>
  </div>
  <div class=\"card\">
    <strong>{overall_tokens}</strong><br>Total tokens used
    <small>Reasoning: {overall_reasoning}<br>Other: {overall_non_reasoning}</small>
  </div>
</section>
<section>
  <h2>Evaluation score distribution</h2>
  {histograms}
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
  <a href=\"index.html\">Heatmap</a>
  <a href=\"diagnostics.html\">Diagnostics &amp; progress</a>
  <a href=\"tokens.html\">Token usage</a>
  <a href=\"umap.html\">UMAP visualizations</a>
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


UMAP_TEMPLATE = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>Psalm Pair UMAP Visualizations</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f8f9fa; color: #111; }}
    header {{ margin-bottom: 1.5rem; }}
    nav {{ margin-bottom: 1.5rem; }}
    nav a {{ margin-right: 1rem; color: #0b7285; text-decoration: none; }}
    nav a:hover {{ text-decoration: underline; }}
    main {{ display: grid; gap: 2rem; }}
    section {{ background: white; border-radius: 8px; padding: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    h2 {{ margin-top: 0; color: #0b7285; }}
    img {{ max-width: 100%; height: auto; border-radius: 6px; border: 1px solid #dee2e6; background: #fff; }}
    p.note {{ color: #495057; font-size: 0.95rem; }}
  </style>
</head>
<body>
<header>
  <h1>UMAP projections of psalm relationships</h1>
  <p class=\"note\">Distances are derived from evaluation scores with unevaluated pairs assumed to score 5/10.</p>
</header>
<nav>
  <a href=\"index.html\">Heatmap</a>
  <a href=\"diagnostics.html\">Diagnostics &amp; progress</a>
  <a href=\"tokens.html\">Token usage</a>
  <a href=\"umap.html\">UMAP visualizations</a>
</nav>
<main>
  <section>
    <h2>Minimum score symmetry</h2>
    <p class=\"note\">Distance between psalms A and B is computed as 2<sup>-min(score<sub>A→B</sub>, score<sub>B→A</sub>)</sup>.</p>
    <img src=\"data:image/png;base64,{minimum_image}\" alt=\"UMAP projection using minimum scores\">
  </section>
  <section>
    <h2>Average score symmetry</h2>
    <p class=\"note\">Distances use the mean score of both directions before applying 2<sup>-x</sup>.</p>
    <img src=\"data:image/png;base64,{average_image}\" alt=\"UMAP projection using average scores\">
  </section>
  <section>
    <h2>Maximum score symmetry</h2>
    <p class=\"note\">Distances emphasize the stronger of the two directional scores.</p>
    <img src=\"data:image/png;base64,{maximum_image}\" alt=\"UMAP projection using maximum scores\">
  </section>
</main>
</body>
</html>
"""


def _recent_activity_series(
    daily_rows: Sequence, key: str, window_days: int
) -> list[int]:
    today = dt.datetime.now(dt.UTC).date()
    start_day = today - dt.timedelta(days=window_days - 1)
    counts_by_day = {
        dt.date.fromisoformat(str(row["day"])): int(row[key] or 0) for row in daily_rows
    }
    return [
        int(counts_by_day.get(start_day + dt.timedelta(days=offset), 0))
        for offset in range(window_days)
    ]


def compute_projection_info(
    *,
    total: int,
    completed: int,
    daily_rows: Sequence,
    key: str,
    window_days: int = 14,
) -> tuple[str, str]:
    """Estimate a completion date and explain the averaging window."""

    if total <= 0:
        return "—", "&nbsp;"
    if completed >= total:
        return "Complete", f"All {completed} pairs processed."
    if not daily_rows:
        return "—", "No recorded activity yet."

    series = _recent_activity_series(daily_rows, key, window_days)
    recent_total = sum(series)
    if recent_total == 0:
        return "—", f"No activity in last {window_days} days."

    rate = recent_total / window_days
    remaining = max(total - completed, 0)
    days_needed = math.ceil(remaining / rate)
    today = dt.datetime.now(dt.UTC).date()
    projected_date = today + dt.timedelta(days=days_needed)
    note = f"Avg {rate:.1f}/day over last {window_days} days; {remaining} remaining"
    return projected_date.isoformat(), note


def fetch_score_matrix(conn) -> np.ndarray:
    """Return a directed score matrix with defaults for missing evaluations."""

    size = 150
    matrix = np.full((size, size), 5.0, dtype=float)
    np.fill_diagonal(matrix, 10.0)

    query = """
        SELECT pa.psalm_x, pa.psalm_y, pe.score
        FROM pair_arguments pa
        LEFT JOIN pair_evaluations pe ON pe.pair_id = pa.id
        WHERE pe.score IS NOT NULL
    """
    for row in conn.execute(query):
        x = int(row["psalm_x"]) - 1
        y = int(row["psalm_y"]) - 1
        score = float(row["score"])
        matrix[x, y] = score

    return matrix


def _distance_matrix_from_scores(scores: np.ndarray, mode: str) -> np.ndarray:
    if mode == "minimum":
        combined = np.minimum(scores, scores.T)
    elif mode == "average":
        combined = 0.5 * (scores + scores.T)
    elif mode == "maximum":
        combined = np.maximum(scores, scores.T)
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    distances = np.power(2.0, -combined)
    np.fill_diagonal(distances, 0.0)
    # enforce symmetry numerically
    return 0.5 * (distances + distances.T)


def compute_umap_embeddings(distance_matrix: np.ndarray) -> np.ndarray:
    reducer = umap.UMAP(metric="precomputed", random_state=42)
    return reducer.fit_transform(distance_matrix)


def _plot_embedding(coordinates: np.ndarray, title: str) -> str:
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.set_facecolor("#f8f9fa")
    ax.grid(alpha=0.25, linestyle="--", linewidth=0.5)
    ax.set_title(title)
    ax.set_xlabel("UMAP 1")
    ax.set_ylabel("UMAP 2")

    ax.scatter(
        coordinates[:, 0],
        coordinates[:, 1],
        s=36,
        c="#2563eb",
        edgecolors="#ffffff",
        linewidths=0.5,
        alpha=0.85,
    )

    for idx, (x, y) in enumerate(coordinates, start=1):
        ax.text(
            x,
            y,
            str(idx),
            fontsize=6,
            ha="center",
            va="center",
            color="#111",
            alpha=0.9,
        )

    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    image_bytes = buffer.getvalue()
    return base64.b64encode(image_bytes).decode("ascii")


def generate_umap_images(conn) -> dict[str, str]:
    scores = fetch_score_matrix(conn)
    images: dict[str, str] = {}
    for mode in ("minimum", "average", "maximum"):
        distances = _distance_matrix_from_scores(scores, mode)
        embedding = compute_umap_embeddings(distances)
        images[mode] = _plot_embedding(embedding, f"UMAP projection ({mode})")
    return images


HEATMAP_TEMPLATE = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>Psalm Pair Heatmap</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f8f9fa; color: #111; }}
    header {{ margin-bottom: 1.5rem; }}
    nav {{ margin-bottom: 1.5rem; }}
    nav a {{ margin-right: 1rem; color: #0b7285; text-decoration: none; }}
    nav a:hover {{ text-decoration: underline; }}
    .legend {{ display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; font-size: 0.95rem; }}
    .legend-item {{ display: flex; align-items: center; gap: 0.5rem; }}
    .legend-swatch {{ width: 18px; height: 18px; border-radius: 4px; border: 1px solid #adb5bd; box-shadow: inset 0 0 2px rgba(0,0,0,0.1); }}
    .heatmap-container {{ background: white; border-radius: 8px; padding: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: auto; max-height: 75vh; }}
    .heatmap-table {{ border-collapse: collapse; table-layout: fixed; font-size: 0.65rem; min-width: max-content; }}
    .heatmap-table th, .heatmap-table td {{ border: 1px solid #dee2e6; padding: 0; width: 32px; height: 24px; text-align: center; }}
    .heatmap-table thead th {{ background: #eef2f7; position: sticky; top: 0; z-index: 3; }}
    .heatmap-table thead th:first-child {{ left: 0; z-index: 4; }}
    .heatmap-table tbody th {{ position: sticky; left: 0; background: #f8f9fa; z-index: 2; }}
    .heatmap-cell {{ position: relative; }}
    .heatmap-cell a, .heatmap-cell span.cell-placeholder {{ display: block; width: 100%; height: 100%; }}
    .heatmap-cell a {{ text-decoration: none; }}
    .sr-only {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }}
    footer {{ margin-top: 2rem; font-size: 0.9rem; color: #555; }}
  </style>
</head>
<body>
<header>
  <h1>Psalm Pair Heatmap</h1>
  <p>Visual overview of generation and evaluation coverage across all ordered psalm pairs.</p>
</header>
<nav>
  <a href=\"index.html\">Heatmap</a>
  <a href=\"diagnostics.html\">Diagnostics &amp; progress</a>
  <a href=\"tokens.html\">Token usage</a>
  <a href=\"umap.html\">UMAP visualizations</a>
</nav>
<section>
  <p>Generated {generated} of {total_pairs} possible ordered pairs ({progress:.2f}% complete) and evaluated {evaluated} pairs ({evaluation_progress:.2f}% complete).</p>
</section>
<section class=\"legend\">
  <div class=\"legend-item\">
    <span class=\"legend-swatch\" style=\"background: #ffffff;\"></span>
    <span>Not generated</span>
  </div>
  <div class=\"legend-item\">
    <span class=\"legend-swatch\" style=\"background: #adb5bd;\"></span>
    <span>Generated, awaiting evaluation</span>
  </div>
  <div class=\"legend-item\">
    <span class=\"legend-swatch\" style=\"background: #2563eb;\"></span>
    <span>Low evaluation score (0)</span>
  </div>
  <div class=\"legend-item\">
    <span class=\"legend-swatch\" style=\"background: linear-gradient(90deg, #2563eb 0%, #dc2626 100%); border: none;\"></span>
    <span>Intermediate scores</span>
  </div>
  <div class=\"legend-item\">
    <span class=\"legend-swatch\" style=\"background: #dc2626;\"></span>
    <span>High evaluation score (10)</span>
  </div>
</section>
<section class=\"heatmap-container\">
  <table class=\"heatmap-table\">
    {heatmap_table}
  </table>
</section>
<footer>
  <p>Click any colored cell to open the detailed argument page for that ordered pair.</p>
</footer>
</body>
</html>
"""


PAIR_TEMPLATE = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>Psalm {psalm_x} → {psalm_y}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f8f9fa; color: #111; }}
    nav a {{ margin-right: 1rem; color: #0b7285; text-decoration: none; }}
    nav a:hover {{ text-decoration: underline; }}
    main {{ max-width: 960px; margin: 0 auto; }}
    section {{ background: white; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    h1 {{ margin-top: 0; }}
    h2 {{ margin-top: 0; color: #0b7285; }}
    pre {{ white-space: pre-wrap; background: #f1f3f5; border-radius: 6px; padding: 1rem; line-height: 1.4; }}
    .meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0.75rem; margin-bottom: 1rem; font-size: 0.95rem; }}
    .meta div {{ background: #f8f9fb; border-radius: 6px; padding: 0.75rem; border: 1px solid #dee2e6; }}
    .meta strong {{ display: block; font-size: 0.85rem; color: #555; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.35rem; }}
    .tokens {{ margin: 0.75rem 0; font-size: 0.95rem; color: #333; }}
    .tokens span {{ display: inline-block; margin-right: 1rem; }}
    .checks {{ list-style: none; padding-left: 0; margin: 0.75rem 0; display: grid; gap: 0.4rem; }}
    .checks li {{ background: #f8f9fb; border: 1px solid #dee2e6; border-radius: 6px; padding: 0.5rem 0.75rem; font-size: 0.95rem; color: #333; }}
    footer {{ text-align: center; color: #555; font-size: 0.9rem; margin-top: 2rem; }}
  </style>
</head>
<body>
<nav>
  <a href=\"../index.html\">Heatmap</a>
  <a href=\"../diagnostics.html\">Diagnostics &amp; progress</a>
  <a href=\"../tokens.html\">Token usage</a>
  <a href=\"../umap.html\">UMAP visualizations</a>
</nav>
<main>
  <section>
    <h1>Psalm {psalm_x} → {psalm_y}</h1>
    <div class=\"meta\">
      <div>
        <strong>Argument generated</strong>
        <span>{generated_at}</span>
      </div>
      <div>
        <strong>Argument model</strong>
        <span>{generation_model}</span>
      </div>
      <div>
        <strong>Pair ID</strong>
        <span>{pair_id}</span>
      </div>
    </div>
    {argument_tokens}
    <h2>Argument</h2>
    <pre>{argument_text}</pre>
  </section>

  <section>
    <h2>Evaluation</h2>
    {evaluation_content}
  </section>

  <section>
    <h2>Prompt</h2>
    <pre>{prompt_text}</pre>
  </section>
</main>
<footer>
  <p>Return to the <a href=\"../index.html\">heatmap overview</a> for additional pairs.</p>
</footer>
</body>
</html>
"""


ROW_TEMPLATE = "<tr><td>{id}</td><td>{pair}</td><td>{created}</td><td>{evaluation}</td><td>{excerpt}</td></tr>"


HEATMAP_LOW_SCORE_RGB = (37, 99, 235)
HEATMAP_HIGH_SCORE_RGB = (220, 38, 38)
HEATMAP_PENDING_COLOR = "#adb5bd"
HEATMAP_NOT_GENERATED_COLOR = "#ffffff"


def pair_filename(psalm_x: int, psalm_y: int) -> str:
    return f"{psalm_x:03d}-{psalm_y:03d}.html"


def pair_url(psalm_x: int, psalm_y: int) -> str:
    return f"pairs/{pair_filename(psalm_x, psalm_y)}"


def format_row(row) -> str:
    excerpt = ""
    if row["response_text"]:
        first_line = row["response_text"].strip().splitlines()[0]
        excerpt = html.escape(first_line[:160])
    if row["score"] is not None:
        version_suffix = f" (v{row['evaluator_version']})" if row["evaluator_version"] is not None else ""
        evaluation = f"Score {row['score']}{version_suffix} on {row['evaluated_at']}"
    else:
        evaluation = "Pending"
    pair_link = (
        f'<a href="{pair_url(row["psalm_x"], row["psalm_y"])}">{row["psalm_x"]} → {row["psalm_y"]}</a>'
    )
    return ROW_TEMPLATE.format(
        id=row["id"],
        pair=pair_link,
        created=row["created_at"],
        evaluation=html.escape(evaluation),
        excerpt=excerpt,
    )



def render_diagnostics_html(
    stats: dict,
    rows: Iterable[str],
    tokens: dict,
    histogram_html: str,
    *,
    generation_projection: str,
    evaluation_projection: str,
    generation_projection_note: str,
    evaluation_projection_note: str,
) -> str:
    generated_at = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S")
    generated = stats["generated"]
    evaluated = stats["evaluated"]
    total_pairs = stats["total_pairs"]
    progress = 100 * generated / total_pairs if total_pairs else 0
    evaluation_progress = 100 * evaluated / total_pairs if total_pairs else 0
    return DIAGNOSTICS_TEMPLATE.format(
        generated_at=generated_at,
        generated=generated,
        evaluated=evaluated,
        total_pairs=total_pairs,
        progress=progress,
        evaluation_progress=evaluation_progress,
        generation_projection=generation_projection,
        evaluation_projection=evaluation_projection,
        generation_projection_note=generation_projection_note,
        evaluation_projection_note=evaluation_projection_note,
        overall_tokens=tokens["overall_total"],
        overall_reasoning=tokens["overall_reasoning"],
        overall_non_reasoning=tokens["overall_non_reasoning"],
        histograms=histogram_html,
        rows="\n      ".join(rows),
    )


def write_site(output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "index.html"
    diagnostics_path = output_dir / "diagnostics.html"
    pairs_dir = output_dir / "pairs"
    pairs_dir.mkdir(parents=True, exist_ok=True)
    written_files: set[str] = set()
    with connect() as conn:
        stats = counts(conn)
        recent = recent_arguments(conn, limit=50)
        tokens = token_usage_stats(conn)
        daily_stats = daily_progress(conn)
        generation_projection, generation_note = compute_projection_info(
            total=stats["total_pairs"],
            completed=stats["generated"],
            daily_rows=daily_stats,
            key="generated_count",
        )
        evaluation_projection, evaluation_note = compute_projection_info(
            total=stats["total_pairs"],
            completed=stats["evaluated"],
            daily_rows=daily_stats,
            key="evaluated_count",
        )
        rows = [format_row(row) for row in recent]
        scores_by_version = evaluation_scores_by_version(conn)
        histogram_html = render_histogram_section(scores_by_version)
        diagnostics_html = render_diagnostics_html(
            stats,
            rows,
            tokens,
            histogram_html,
            generation_projection=generation_projection,
            evaluation_projection=evaluation_projection,
            generation_projection_note=generation_note,
            evaluation_projection_note=evaluation_note,
        )
        diagnostics_path.write_text(diagnostics_html, encoding="utf-8")

        tokens_path = output_dir / "tokens.html"
        daily_rows = [render_daily_row(row) for row in tokens["daily"]]
        tokens_html = render_tokens_html(tokens, daily_rows)
        tokens_path.write_text(tokens_html, encoding="utf-8")

        umap_path = output_dir / "umap.html"
        umap_images = generate_umap_images(conn)
        umap_html = render_umap_html(umap_images)
        umap_path.write_text(umap_html, encoding="utf-8")

        heatmap_path = output_dir / "heatmap.html"
        heatmap_matrix = build_heatmap_matrix(conn)
        heatmap_html = render_heatmap_html(heatmap_matrix, stats)
        index_path.write_text(heatmap_html, encoding="utf-8")
        heatmap_path.write_text(heatmap_html, encoding="utf-8")

        for row in pair_details(conn):
            filename = pair_filename(row["psalm_x"], row["psalm_y"])
            pair_path = pairs_dir / filename
            pair_html = render_pair_page(row)
            pair_path.write_text(pair_html, encoding="utf-8")
            written_files.add(filename)

    cleanup_stale_pair_pages(pairs_dir, written_files)
    return index_path


def cleanup_stale_pair_pages(pairs_dir: Path, expected: set[str]) -> None:
    for path in pairs_dir.glob("*.html"):
        if path.name not in expected:
            path.unlink()


def render_pair_page(row) -> str:
    argument_tokens = render_token_summary(
        row["generation_reasoning_tokens"],
        row["generation_non_reasoning_tokens"],
        row["generation_total_tokens"],
    )
    generated_at = row["generated_at"] or "Unknown"
    generation_model = html.escape(row["generation_model"] or "Unknown")
    if row["evaluation_id"] is None:
        evaluation_content = (
            "<p>No evaluation has been recorded for this pair yet.</p>"
        )
    else:
        evaluation_tokens = render_token_summary(
            row["evaluation_reasoning_tokens"],
            row["evaluation_non_reasoning_tokens"],
            row["evaluation_total_tokens"],
        )
        evaluation_details = [f"<p>Score: <strong>{row['score']}</strong></p>"]
        if row["evaluated_at"]:
            evaluation_details.append(f"<p>Evaluated at: {row['evaluated_at']} (UTC)</p>")
        if row["evaluator_model"]:
            evaluation_details.append(
                f"<p>Evaluator model: {html.escape(row['evaluator_model'])}</p>"
            )
        if row["evaluator_version"]:
            evaluation_details.append(
                f"<p>Evaluator version: v{row['evaluator_version']}</p>"
            )
        evaluation_details.append(evaluation_tokens)
        checklist_pairs = [
            ("Has verse refs", row["has_verse_refs"]),
            ("Factual error detected", row["any_factual_error_detected"]),
            ("Only generic motifs", row["only_generic_motifs"]),
            ("Counterargument considered", row["counterargument_considered"]),
            (
                "LXX/MT numbering acknowledged",
                row["lxx_mt_numbering_acknowledged"],
            ),
        ]
        if any(value is not None for _, value in checklist_pairs):
            items = []
            for label, value in checklist_pairs:
                if value is None:
                    status = "—"
                else:
                    try:
                        status_bool = bool(int(value))
                    except (TypeError, ValueError):
                        status = html.escape(str(value))
                    else:
                        status = "Yes" if status_bool else "No"
                items.append(f"<li><strong>{label}:</strong> {status}</li>")
            evaluation_details.append(
                "<div><h4>Checklist</h4><ul class=\"checks\">"
                + "".join(items)
                + "</ul></div>"
            )
        vocabulary_specificity = row["vocabulary_specificity"]
        if vocabulary_specificity is not None:
            evaluation_details.append(
                f"<p>Vocabulary specificity: {float(vocabulary_specificity):.1f} / 10</p>"
            )
        flags: list[str] = []
        raw_flags = row["flags"]
        if raw_flags:
            try:
                parsed_flags = json.loads(raw_flags)
                if isinstance(parsed_flags, list):
                    flags = [str(flag) for flag in parsed_flags]
            except json.JSONDecodeError:
                flags = [f"Unparseable flags: {raw_flags}"]
        if flags:
            flag_items = ", ".join(html.escape(flag) for flag in flags)
            evaluation_details.append(f"<p>Flags: {flag_items}</p>")
        evaluation_details.append(
            f"<pre>{html.escape(row['justification'] or '')}</pre>"
        )
        evaluation_content = "\n      ".join(evaluation_details)

    return PAIR_TEMPLATE.format(
        psalm_x=row["psalm_x"],
        psalm_y=row["psalm_y"],
        generated_at=generated_at,
        generation_model=generation_model,
        pair_id=row["pair_id"],
        argument_tokens=argument_tokens,
        argument_text=html.escape(row["response_text"] or ""),
        evaluation_content=evaluation_content,
        prompt_text=html.escape(row["prompt"] or ""),
    )


def render_token_summary(reasoning: int | None, non_reasoning: int | None, total: int | None) -> str:
    if reasoning is None and non_reasoning is None and total is None:
        return "<p class=\"tokens\">Token usage not recorded.</p>"

    parts: list[str] = []
    if reasoning is not None:
        parts.append(f"<span><strong>Reasoning:</strong> {reasoning}</span>")
    if non_reasoning is not None:
        parts.append(f"<span><strong>Output:</strong> {non_reasoning}</span>")
    if total is not None:
        parts.append(f"<span><strong>Total:</strong> {total}</span>")
    return "<p class=\"tokens\">" + " ".join(parts) + "</p>"


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


def render_umap_html(images: dict[str, str]) -> str:
    return UMAP_TEMPLATE.format(
        minimum_image=images["minimum"],
        average_image=images["average"],
        maximum_image=images["maximum"],
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


def _score_to_bucket(score: float) -> int:
    bucket = int(math.floor(score + 0.5))
    return max(0, min(10, bucket))


def render_histogram_section(scores_by_version: dict[int, list[float]]) -> str:
    if not scores_by_version:
        return "<p>No evaluations recorded yet.</p>"

    cards: list[str] = []
    for version in sorted(scores_by_version):
        scores = scores_by_version[version]
        counts = [0] * 11
        for score in scores:
            counts[_score_to_bucket(score)] += 1

        total = len(scores)
        avg = sum(scores) / total if total else 0.0
        max_count = max(counts) if any(counts) else 1
        rows: list[str] = []
        for bucket, count in enumerate(counts):
            width = (count / max_count) * 100 if max_count else 0
            bar_inner = f'<span class="bar" style="width: {width:.1f}%"></span>' if count else ""
            rows.append(
                "<li>"
                f"<span class=\"bucket\">{bucket}</span>"
                "<div class=\"bar-container\">"
                f"{bar_inner}"
                "</div>"
                f"<span class=\"count\">{count}</span>"
                "</li>"
            )

        meta_text = (
            f"<p class=\"meta\">Total: {total} · Avg: {avg:.2f}</p>" if total else "<p class=\"meta\">No evaluations recorded.</p>"
        )
        card = (
            "<div class=\"histogram-card\">"
            f"<h3>Evaluator v{version}</h3>"
            f"{meta_text}"
            "<ul class=\"histogram-bars\">"
            + "".join(rows)
            + "</ul></div>"
        )
        cards.append(card)

    return "<div class=\"histograms\">" + "".join(cards) + "</div>"


def _score_to_color(score: float) -> str:
    ratio = max(0.0, min(1.0, score / 10.0))
    channels = [
        int(round(low + (high - low) * ratio)) for low, high in zip(HEATMAP_LOW_SCORE_RGB, HEATMAP_HIGH_SCORE_RGB)
    ]
    return "#{:02x}{:02x}{:02x}".format(*channels)


def build_heatmap_matrix(conn) -> list[list[dict[str, str | None]]]:
    query = """
        SELECT
            pa.psalm_x,
            pa.psalm_y,
            pe.score
        FROM pair_arguments pa
        LEFT JOIN pair_evaluations pe ON pe.pair_id = pa.id
    """
    data = {(row["psalm_x"], row["psalm_y"]): row["score"] for row in conn.execute(query)}

    missing = object()
    matrix: list[list[dict[str, str | None]]] = []
    for psalm_x in range(1, 151):
        row_cells: list[dict[str, str | None]] = []
        for psalm_y in range(1, 151):
            key = (psalm_x, psalm_y)
            score = data.get(key, missing)
            if score is missing:
                status = "not_generated"
                color = HEATMAP_NOT_GENERATED_COLOR
                label = "Not generated yet"
                url: str | None = None
            elif score is None:
                status = "generated"
                color = HEATMAP_PENDING_COLOR
                label = "Generated, awaiting evaluation"
                url = pair_url(psalm_x, psalm_y)
            else:
                status = "evaluated"
                numeric_score = float(score)
                color = _score_to_color(numeric_score)
                label = f"Evaluation score {numeric_score:.1f}"
                url = pair_url(psalm_x, psalm_y)

            row_cells.append(
                {
                    "psalm_x": psalm_x,
                    "psalm_y": psalm_y,
                    "status": status,
                    "color": color,
                    "label": label,
                    "url": url,
                }
            )
        matrix.append(row_cells)
    return matrix


def render_heatmap_table(matrix: list[list[dict[str, str | None]]]) -> str:
    header_cells = "".join(f"<th scope=\"col\">{col}</th>" for col in range(1, 151))
    header = (
        "<thead>"
        "<tr>"
        "<th scope=\"col\">Psalm ↓</th>"
        f"{header_cells}"
        "</tr>"
        "</thead>"
    )

    body_rows: list[str] = []
    for psalm_x, row_cells in enumerate(matrix, start=1):
        cell_html: list[str] = []
        for cell in row_cells:
            label_text = f"Psalm {cell['psalm_x']} → {cell['psalm_y']}: {cell['label']}"
            label_attr = html.escape(label_text, quote=True)
            label_html = html.escape(label_text)
            style_attr = html.escape(f"background: {cell['color']};", quote=True)
            if cell["url"]:
                url_attr = html.escape(cell["url"], quote=True)
                inner = f'<a href="{url_attr}" aria-label="{label_attr}" title="{label_attr}"></a>'
            else:
                inner = (
                    '<span class="cell-placeholder" aria-hidden="true"></span>'
                    f'<span class="sr-only">{label_html}</span>'
                )
            cell_html.append(
                f'<td class="heatmap-cell" style="{style_attr}" aria-label="{label_attr}" title="{label_attr}">{inner}</td>'
            )
        body_rows.append(f'<tr><th scope="row">{psalm_x}</th>{"".join(cell_html)}</tr>')

    body = "<tbody>" + "".join(body_rows) + "</tbody>"
    return header + body


def render_heatmap_html(matrix: list[list[dict[str, str | None]]], stats: dict) -> str:
    total_pairs = stats.get("total_pairs", 0)
    progress = 100 * stats.get("generated", 0) / total_pairs if total_pairs else 0.0
    evaluation_progress = 100 * stats.get("evaluated", 0) / total_pairs if total_pairs else 0.0
    table_html = render_heatmap_table(matrix)
    return HEATMAP_TEMPLATE.format(
        generated=stats.get("generated", 0),
        evaluated=stats.get("evaluated", 0),
        total_pairs=total_pairs,
        progress=progress,
        evaluation_progress=evaluation_progress,
        heatmap_table=table_html,
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

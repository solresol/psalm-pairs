# IMPROVEMENTS.md

*Analysis date: 2026-07-11*

psalm-pairs is a slow-burn research project: for every ordered pair of the 150 Psalms it asks an OpenAI model (gpt-5.4 by default) to argue why Psalm Y could follow Psalm X, has a second LLM call score that argument 0–10, stores everything in SQLite on `psalmer@raksasa`, and publishes a static heatmap site to merah via `cronscript.sh`. The pipeline is deliberately throttled (`PAIRS_PER_DAY=1`, `EVALS_PER_DAY=2` in the cron script) to keep spend and API priority on Stephanos. The code is small (~2,300 lines across `psalm_pairs/`), already uses `uv` correctly, and is in reasonable shape; the main gaps are uncommitted work, zero tests, and a monolithic `website.py`.

## Bugs & Fixes

- **Uncommitted work in the tree.** `psalm_pairs/openai_client.py`, `README.md`, and `CLAUDE.md` all carry an unmerged change that switches the key source to `~/.openai.psalmer.key` (overridable via `PSALM_PAIRS_OPENAI_KEY_PATH`) and makes the key file *win over* `OPENAI_API_KEY`. The change looks complete and sensible — commit it or revert it. Note it inverts precedence (file beats env var); confirm that is intended, since it can surprise anyone exporting `OPENAI_API_KEY` for a one-off run against a different account. Because `cronscript.sh` does `git pull` before every run, uncommitted changes here can also silently diverge dev from production behavior.
- **Docs disagree with reality on defaults.** README and CLAUDE.md say `PAIRS_PER_DAY`/`EVALS_PER_DAY` default to 50, but `cronscript.sh` hardcodes fallbacks of 1 and 2 (commits "Really slow, really low impact", "Pull back on the volume"). Update the docs, or move the throttle values to the cron environment so the script's defaults match documentation.
- **`load_api_key()` still mutates `os.environ["OPENAI_API_KEY"]`** as a side effect even though `build_client()` now passes the key explicitly. Drop the env mutation once the pending diff is committed — it's dead weight and a mild footgun.

## Improvements

- **Split `website.py` (1,154 lines).** It is half the codebase: HTML templating, heatmap rendering, UMAP visualization, and progress projections all live in one file. Extract at least `visualizations.py` (matplotlib/UMAP) and `templates.py` so the site generator is reviewable.
- **Completion projection.** With 150×149 ordered pairs (~22,350) at 1 generation + 2 evaluations/day, generation alone takes ~60 years. Either accept this as art, raise the daily budget when Stephanos load allows, or use OpenAI's Batch API (50% cheaper, off-peak) to do bulk generation without competing for interactive priority — this seems like the single highest-leverage change.
- **Evaluator versioning is manual.** NOTES.md says to hand-bump `EVALUATOR_PROMPT_VERSION` in `evaluator_config.py` when the prompt changes. Compute a hash of the prompt text and store it alongside the version so a forgotten bump is detectable.
- **`cronscript.sh` deploy failure handling.** With `set -euo pipefail`, an rsync failure to merah aborts silently under cron. Consider logging failures somewhere visible (or a healthcheck ping) so a dead deploy is noticed before weeks pass.

## Testing

- **There are no tests at all.** Highest-value, cheap targets:
  - `db.py` `ensure_column()` migration logic against a temp SQLite file (schema evolution is the riskiest area per NOTES.md, since production upgrades itself on next run).
  - The nested-dict response parsing in `evaluate_pairs.py` (already caused a bug fixed in 6dc8f96) — pin it with fixtures of real Responses API payloads.
  - `openai_client.load_api_key()` precedence (file vs env vs missing) — trivially testable with `tmp_path` and `monkeypatch`.
- Add pytest via `uv add --dev pytest` and a `uv run pytest` line to CLAUDE.md.

## Documentation

- `pyproject.toml` still says `description = "Add your description here"` — fill it in.
- README's prompt excerpt and pipeline description are good; add a link to the live site (psalm-pairs.symmachus.org, inferable only from the rsync target) and a sentence on the throttling rationale so future-you remembers why it runs at 1 pair/day.
- CLAUDE.md mentions `.python-version` but no such file exists in the repo root — either add it or remove the reference.

## Security

- No committed secrets found: `data/` (the SQLite DB) is gitignored, and keys live outside the repo in `~/.openai.psalmer.key`. Good.
- `envsetup.sh` is committed — worth a periodic glance to make sure it never grows a real key. Currently fine.

## Housekeeping / Modernization

- Already on `uv` with pyproject.toml and uv.lock committed — nothing to migrate, and no requirements.txt to purge. Good.
- Trim the boilerplate `.gitignore` (250 lines of Django/Scrapy/Abstra noise for a 7-file project) — optional, purely cosmetic.
- `uvbootstrap.py` and `fetch-psalms.py` sit in the repo root; if they're one-shot setup scripts, say so in README or move them to a `scripts/` directory.
- Heavy deps (`umap-learn`, `scikit-learn`, `scipy`) are pulled in solely for the UMAP page in `website.py`; if site rebuild time or install weight on raksasa ever matters, make them an optional dependency group.

## Quick Wins

1. Commit (or revert) the pending `openai_client.py` key-path change — the tree should be clean given cron pulls on production.
2. Fix the PAIRS_PER_DAY/EVALS_PER_DAY documentation mismatch.
3. Fill in the pyproject description.
4. `uv add --dev pytest` and write the `load_api_key()` precedence test — 20 minutes, first test in the repo.
5. Investigate the OpenAI Batch API for bulk generation at half price without competing with Stephanos.

# Notes

- Production runs as `psalmer@raksasa`; SSH there for manual runs or database inspection.
- The production SQLite database lives on that host. Prefer backward-compatible schema changes in `psalm_pairs/db.py` so the next run upgrades it automatically.
- `cronscript.sh` does a `git pull` before generation, evaluation, and site rebuild.
- When the evaluator prompt changes, bump `EVALUATOR_PROMPT_VERSION` in `psalm_pairs/evaluator_config.py` so the site treats it as a new evaluator version.

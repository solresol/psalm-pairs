#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

export UV_PROJECT_ENVIRONMENT=$(pwd)/.venv

if command -v git >/dev/null 2>&1; then
  git pull -q
fi

PAIRS_PER_DAY=${PAIRS_PER_DAY:-50}
EVALS_PER_DAY=${EVALS_PER_DAY:-50}
SITE_DIR=${SITE_DIR:-site}
REMOTE_TARGET=${REMOTE_TARGET:-"merah.cassia.ifost.org.au:/var/www/vhosts/psalm-pairs.symmachus.org/htdocs/"}

uv run psalm_pairs/generate_pairs.py --limit "$PAIRS_PER_DAY"
uv run psalm_pairs/evaluate_pairs.py --limit "$EVALS_PER_DAY"
uv run psalm_pairs/website.py --output "$SITE_DIR"

if [ -n "$REMOTE_TARGET" ]; then
  scp -r "$SITE_DIR"/* "$REMOTE_TARGET"
fi

#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

export UV_PROJECT_ENVIRONMENT=$(pwd)/.venv

if command -v git >/dev/null 2>&1; then
  git pull -q
fi

PAIRS_PER_DAY=${PAIRS_PER_DAY:-20}
EVALS_PER_DAY=${EVALS_PER_DAY:-30}
SITE_DIR=${SITE_DIR:-site}
REMOTE_TARGET=${REMOTE_TARGET:-"merah.cassia.ifost.org.au:/var/www/vhosts/psalm-pairs.symmachus.org/htdocs/"}

uv run psalm_pairs/generate_pairs.py --limit "$PAIRS_PER_DAY" --quiet
uv run psalm_pairs/evaluate_pairs.py --limit "$EVALS_PER_DAY" --quiet
uv run psalm_pairs/website.py --output "$SITE_DIR"

if [ -n "$REMOTE_TARGET" ]; then
  if command -v rsync >/dev/null 2>&1; then
    rsync -av --delete "$SITE_DIR"/ "$REMOTE_TARGET"
  else
    scp -r "$SITE_DIR"/* "$REMOTE_TARGET"
  fi
fi

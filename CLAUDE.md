# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project analyzes pairwise similarity between the 150 Psalms using LLM-generated arguments and evaluations. For every ordered pair of Psalms (X → Y), it:

1. Generates an argument for why Psalm Y could logically follow Psalm X
2. Evaluates that argument on a 0-10 scale using a separate LLM call with strict rubric
3. Generates a static website showing results via heatmap and detailed pages

The system uses OpenAI's Responses API (GPT-5 by default) with reasoning tokens for both generation and evaluation.

## Commands

### Environment Setup
- This project uses `uv` for Python dependency management
- Python version: 3.12 (see `.python-version`)
- Virtual environment is maintained at `.venv/`

### Core Operations
```bash
# Generate psalm pair arguments (default: 50 pairs)
uv run psalm_pairs/generate_pairs.py --limit 50

# Evaluate pending arguments (default: 50 evaluations)
uv run psalm_pairs/evaluate_pairs.py --limit 50

# Generate the static website
uv run psalm_pairs/website.py --output site

# Daily automated workflow (run by cron)
./cronscript.sh
```

### Environment Variables
- `OPENAI_API_KEY` or `~/.openai.key` - OpenAI API key (required)
- `PSALM_PAIRS_MODEL` - Model for generation (default: `gpt-5`)
- `PSALM_PAIRS_EVAL_MODEL` - Model for evaluation (default: `gpt-5`)
- `PAIRS_PER_DAY` - Number of new arguments to generate (default: 50)
- `EVALS_PER_DAY` - Number of evaluations to perform (default: 50)
- `SITE_DIR` - Output directory for website (default: `site`)
- `REMOTE_TARGET` - `scp` destination for deployment (optional)

## Architecture

### Data Flow
1. **Source Data**: Psalm texts stored as JSON files in `psalms_json/` (psalm_001.json through psalm_150.json) from the Unicode/XML Leningrad Codex
2. **Generation**: `generate_pairs.py` creates arguments for pairs, stores in SQLite
3. **Evaluation**: `evaluate_pairs.py` scores arguments using function calling with structured output
4. **Website**: `website.py` builds static HTML from database

### Database Schema (`data/psalm_pairs.sqlite3`)
- **pair_arguments**: Stores generated arguments with prompt, response, model, and token usage
- **pair_evaluations**: Stores evaluation scores, justifications, rubric checks, and flags
- Schema evolves via `ensure_column()` for backward compatibility

### Key Modules

**psalm_pairs/psalms.py**
- `load_psalm(psalm_number)`: Cached JSON loader
- `format_psalm(psalm_number)`: Returns formatted Hebrew text with verse numbers
- `all_psalm_numbers()`: Returns list of available psalm numbers

**psalm_pairs/db.py**
- All SQLite operations: connection management, insertions, queries
- `pending_pairs()`: Returns next N pairs without arguments (iterates X=1..150, Y=1..150, X≠Y)
- `pending_evaluations()`: Returns arguments awaiting evaluation
- `pair_details()`: Iterator yielding complete pair info for site generation
- Token aggregation functions for usage stats

**psalm_pairs/openai_client.py**
- `build_client()`: Initializes OpenAI client with API key from env or file
- `response_to_dict()`: Serializes response objects
- `extract_usage_tokens()`: Extracts token counts with fallback logic for API evolution

**psalm_pairs/generate_pairs.py**
- Entry point: `uv run psalm_pairs/generate_pairs.py`
- Uses OpenAI Responses API with `reasoning={"effort": "high"}` and `text={"verbosity": "medium"}`
- Builds prompts by formatting template with Hebrew psalm texts

**psalm_pairs/evaluate_pairs.py**
- Entry point: `uv run psalm_pairs/evaluate_pairs.py`
- Enforces skeptical evaluation rubric (typical scores: 2-4; scores >7 rare)
- Uses function calling (`submit_evaluation` tool) with strict parameter ordering
- Validates tool call structure and logs warnings for out-of-order keys
- **IMPORTANT**: When modifying tool schema, key order must be: `justification`, `checks`, `vocabulary_specificity`, `flags` (optional), `score`
- Evaluator version (`EVALUATOR_VERSION`) must be incremented when prompt or rubric changes

**psalm_pairs/website.py**
- Entry point: `uv run psalm_pairs/website.py`
- Generates: `index.html` (heatmap), `diagnostics.html`, `tokens.html`, `pairs/*.html`
- Heatmap color scale: blue (#2563eb) for score 0, red (#dc2626) for score 10
- Cleans up stale pair pages that no longer exist in database

### Evaluation Rubric Details
The evaluator (v2) is intentionally skeptical with hard score caps:
- No verse references → MAX 3
- Factual errors/misquotes → MAX 2
- LXX/MT numbering confusion → MAX 3
- Structural claim errors (acrostic, inclusio) → 0
- Generic themes only → MAX 2

Typical distribution should be: most arguments score 2-4, scores >7 are rare (<1%).

## Important Patterns

### Module Import Handling
All entry point modules (`generate_pairs.py`, `evaluate_pairs.py`, `website.py`) use conditional imports to support both direct execution and package imports:
```python
if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from psalm_pairs import DB_PATH
else:
    from . import DB_PATH
```

### Tool Call Validation
When working on `evaluate_pairs.py`, be aware that the code validates:
1. Tool call presence and name (`submit_evaluation`)
2. Required fields: `score`, `justification`, `checks`, `vocabulary_specificity`
3. Check booleans: `has_verse_refs`, `any_factual_error_detected`, `only_generic_motifs`, `counterargument_considered`, `lxx_mt_numbering_acknowledged`
4. Key ordering in JSON payload (logs warnings if incorrect)
5. Range validation: score 0-10, vocabulary_specificity 1-10

**Important**: The `parse_tool_call()` function parses the JSON arguments string twice when extracting key ordering - once with `object_pairs_hook=list` to capture top-level key order, then again normally to get proper nested dict structures. This prevents nested objects like `checks` from being incorrectly converted to lists of tuples.

### Token Accounting
The code handles multiple OpenAI API response formats for token counts:
- Checks `usage.total_tokens`, `usage.output_tokens`, and `usage.completion_tokens`
- Extracts reasoning tokens from `output_tokens_details.reasoning_tokens` or `usage.reasoning_tokens`
- Computes non-reasoning tokens from `text_tokens` or by subtraction

## Data Attribution
Hebrew source text: Unicode/XML Leningrad Codex: UXLC 2.3 (27.4), Tanach.us Inc., West Redding, CT, USA, April 2025.

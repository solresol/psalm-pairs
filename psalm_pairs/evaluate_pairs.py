"""Evaluate Psalm pair arguments and record scores."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from psalm_pairs import DB_PATH
    from psalm_pairs.db import connect, insert_evaluation, pending_evaluations
    from psalm_pairs.evaluator_config import (
        EVALUATOR_PROMPT_TEMPLATE,
        EVALUATOR_PROMPT_VERSION,
        EVALUATOR_REASONING_EFFORT,
        build_evaluator_input,
    )
    from psalm_pairs.openai_client import build_client, extract_usage_tokens, response_to_dict
else:
    from . import DB_PATH
    from .db import connect, insert_evaluation, pending_evaluations
    from .evaluator_config import (
        EVALUATOR_PROMPT_TEMPLATE,
        EVALUATOR_PROMPT_VERSION,
        EVALUATOR_REASONING_EFFORT,
        build_evaluator_input,
    )
    from .openai_client import build_client, extract_usage_tokens, response_to_dict

DEFAULT_LIMIT = 50
EVALUATOR_MODEL = os.environ.get("PSALM_PAIRS_EVAL_MODEL", "gpt-6-sol")
EVALUATOR_VERSION = 2

TOOLS = [
    {
        "type": "function",
        "name": "submit_evaluation",
        "description": "Record a numeric quality score (0-10) for the provided Psalm pair argument along with an explanation.",
        "parameters": {
            "type": "object",
            "properties": {
                "justification": {
                    "type": "string",
                    "description": "≤35 words. State the decisive evidence and any applied cap (e.g., 'No verse refs → max 3').",
                },
                "checks": {
                    "type": "object",
                    "properties": {
                        "has_verse_refs": {"type": "boolean"},
                        "any_factual_error_detected": {"type": "boolean"},
                        "only_generic_motifs": {"type": "boolean"},
                        "counterargument_considered": {"type": "boolean"},
                        "lxx_mt_numbering_acknowledged": {"type": "boolean"},
                    },
                    "required": [
                        "has_verse_refs",
                        "any_factual_error_detected",
                        "only_generic_motifs",
                        "counterargument_considered",
                        "lxx_mt_numbering_acknowledged",
                    ],
                },
                "vocabulary_specificity": {
                    "type": "number",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "1 = vocabulary overlap is ubiquitous; 10 = vocabulary overlap is essentially unique within Psalms.",
                },
                "flags": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "hallucination",
                            "misquote",
                            "no_refs",
                            "generic",
                            "structural_claim_error",
                            "injection_attempt",
                        ],
                    },
                },
                "score": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 10,
                    "description": "Numeric score between 0 and 10 (use the full scale).",
                },
            },
            "required": ["justification", "checks", "vocabulary_specificity", "score"],
        },
    }
]


logger = logging.getLogger(__name__)


def parse_tool_call(response_dict: Dict[str, Any]) -> Dict[str, Any]:
    for item in response_dict.get("output", []):
        item_type = item.get("type")
        if item_type not in {"tool_call", "function_call"}:
            continue

        if item_type == "tool_call":
            tool_call = item.get("tool_call", {})
        else:  # function_call
            tool_call = item

        if tool_call.get("name") != "submit_evaluation":
            continue

        arguments = tool_call.get("arguments")
        ordered_keys = []
        if isinstance(arguments, str):
            pairs = json.loads(arguments, object_pairs_hook=list)
            if isinstance(pairs, list):
                ordered_keys = [key for key, _ in pairs]
            payload = json.loads(arguments)
        elif isinstance(arguments, dict):
            payload = arguments
            if arguments:
                ordered_keys = list(arguments.keys())
        else:
            continue

        if not isinstance(payload, dict):
            continue

        if ordered_keys:
            expected_order = ["justification", "checks", "vocabulary_specificity"]
            if "flags" in payload:
                expected_order.append("flags")
            expected_order.append("score")

            if ordered_keys != expected_order:
                logger.warning(
                    "submit_evaluation arguments should follow %s order; got %s",
                    ", ".join(expected_order),
                    ", ".join(ordered_keys),
                )

        missing = {"score", "justification", "checks", "vocabulary_specificity"} - payload.keys()
        if missing:
            logger.error("Missing required fields in tool payload: %s", ", ".join(sorted(missing)))
            break

        checks = payload.get("checks")
        if not isinstance(checks, dict):
            logger.error("Invalid checks payload: %r", checks)
            break

        required_checks = {
            "has_verse_refs",
            "any_factual_error_detected",
            "only_generic_motifs",
            "counterargument_considered",
            "lxx_mt_numbering_acknowledged",
        }
        if required_checks - checks.keys():
            logger.error(
                "Missing required check booleans in payload: %s",
                ", ".join(sorted(required_checks - checks.keys())),
            )
            break

        normalised_checks: Dict[str, bool] = {}
        for key in required_checks:
            value = checks.get(key)
            if isinstance(value, bool):
                normalised_checks[key] = value
            elif value in {0, 1}:
                normalised_checks[key] = bool(value)
            else:
                logger.error("Check %s has non-boolean value: %r", key, value)
                break
        else:
            payload["checks"] = normalised_checks
        if payload.get("checks") is not normalised_checks:
            break

        try:
            vocab_value = float(payload["vocabulary_specificity"])
        except (TypeError, ValueError):
            logger.error(
                "Invalid vocabulary_specificity value: %r", payload.get("vocabulary_specificity")
            )
            break
        if not 1 <= vocab_value <= 10:
            logger.error("vocabulary_specificity out of range: %s", vocab_value)
            break
        payload["vocabulary_specificity"] = vocab_value

        flags = payload.get("flags", [])
        if flags is None:
            flags = []
        if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
            logger.error("Invalid flags payload: %r", flags)
            break
        payload["flags"] = flags

        return payload
    logger.error(
        "submit_evaluation tool call missing. Response output: %s",
        json.dumps(response_dict.get("output", []), indent=2, sort_keys=True),
    )
    raise RuntimeError("No submit_evaluation tool call found in response")


def evaluate_pair(client, row, model: str):
    argument = row["response_text"]
    psalm_x = row["psalm_x"]
    psalm_y = row["psalm_y"]
    logger.info("Evaluating argument %s (%s -> %s)", row["id"], psalm_x, psalm_y)
    response = client.responses.create(
        model=model,
        input=build_evaluator_input(argument, psalm_x, psalm_y),
        reasoning={"effort": EVALUATOR_REASONING_EFFORT},
        tools=TOOLS,
        tool_choice={"type": "function", "name": "submit_evaluation"},
    )
    response_dict = response_to_dict(response)
    logger.debug(
        "Raw response dictionary for argument %s: %s",
        row["id"],
        json.dumps(response_dict, indent=2, sort_keys=True),
    )
    usage = extract_usage_tokens(response_dict)
    tool_payload = parse_tool_call(response_dict)
    try:
        tool_payload["score"] = float(tool_payload["score"])
    except (TypeError, ValueError):
        logger.error("Invalid score value in payload: %r", tool_payload.get("score"))
        raise RuntimeError("Evaluation returned invalid score")
    tool_payload["justification"] = str(tool_payload.get("justification", ""))
    return usage, tool_payload


def run(limit: int, model: str = EVALUATOR_MODEL) -> int:
    with connect(DB_PATH) as conn:
        rows = pending_evaluations(conn, limit)
        if not rows:
            logger.info("No pending evaluations.")
            return 0
        completed = 0
        client = build_client()
        for row in rows:
            usage, tool_payload = evaluate_pair(client, row, model)
            insert_evaluation(
                conn,
                pair_id=row["id"],
                score=tool_payload["score"],
                justification=tool_payload["justification"],
                evaluator_model=model,
                evaluator_version=EVALUATOR_VERSION,
                evaluator_prompt_version=EVALUATOR_PROMPT_VERSION,
                evaluator_prompt_template=EVALUATOR_PROMPT_TEMPLATE,
                evaluation_json=tool_payload,
                checks=tool_payload["checks"],
                flags=tool_payload.get("flags", []),
                vocabulary_specificity=tool_payload["vocabulary_specificity"],
                total_tokens=usage["total_tokens"],
                reasoning_tokens=usage["reasoning_tokens"],
                non_reasoning_tokens=usage["non_reasoning_tokens"],
            )
            completed += 1
        return completed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Number of arguments to evaluate")
    parser.add_argument("--model", type=str, default=EVALUATOR_MODEL, help="Model name to use for evaluation")
    parser.add_argument("--quiet", action="store_true", help="Reduce logging output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO if not args.quiet else logging.WARNING)
    completed = run(limit=args.limit, model=args.model)
    logger.info("Evaluated %s arguments", completed)


if __name__ == "__main__":
    main()

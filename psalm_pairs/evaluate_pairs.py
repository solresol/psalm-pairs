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
    from psalm_pairs.openai_client import build_client, extract_usage_tokens, response_to_dict
else:
    from . import DB_PATH
    from .db import connect, insert_evaluation, pending_evaluations
    from .openai_client import build_client, extract_usage_tokens, response_to_dict

DEFAULT_LIMIT = 50
EVALUATOR_MODEL = os.environ.get("PSALM_PAIRS_EVAL_MODEL", "gpt-5")

TOOLS = [
    {
        "type": "function",
        "name": "submit_evaluation",
        "description": "Record a numeric quality score (0-10) for the provided Psalm pair argument along with an explanation.",
        "parameters": {
            "type": "object",
            "properties": {
                "score": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 10,
                    "description": "Numeric score between 0 (very weak) and 10 (very strong).",
                },
                "justification": {
                    "type": "string",
                    "description": "Short explanation for the chosen score.",
                },
            },
            "required": ["score", "justification"],
        },
    }
]

PROMPT = """You are assessing the quality of an argument explaining why Psalm {psalm_y} follows Psalm {psalm_x}."""  # noqa: E501


logger = logging.getLogger(__name__)


def build_input(argument: str, psalm_x: int, psalm_y: int) -> str:
    return (
        PROMPT.format(psalm_x=psalm_x, psalm_y=psalm_y)
        + "\n\nArgument:\n"
        + argument
        + "\n\nProvide your assessment via the submit_evaluation tool."
    )


def parse_tool_call(response_dict: Dict[str, Any]) -> Dict[str, Any]:
    for item in response_dict.get("output", []):
        if item.get("type") != "tool_call":
            continue
        tool_call = item.get("tool_call", {})
        if tool_call.get("name") != "submit_evaluation":
            continue
        arguments = tool_call.get("arguments")
        if isinstance(arguments, str):
            return json.loads(arguments)
        if isinstance(arguments, dict):
            return arguments
    raise RuntimeError("No submit_evaluation tool call found in response")


def evaluate_pair(client, row, model: str):
    argument = row["response_text"]
    psalm_x = row["psalm_x"]
    psalm_y = row["psalm_y"]
    logger.info("Evaluating argument %s (%s -> %s)", row["id"], psalm_x, psalm_y)
    response = client.responses.create(
        model=model,
        input=build_input(argument, psalm_x, psalm_y),
        reasoning={"effort": "medium"},
        tools=TOOLS,
        tool_choice={"type": "function", "name": "submit_evaluation"},
    )
    response_dict = response_to_dict(response)
    usage = extract_usage_tokens(response_dict)
    tool_payload = parse_tool_call(response_dict)
    score = float(tool_payload["score"])
    justification = str(tool_payload["justification"])
    return response_dict, usage, score, justification


def run(limit: int, model: str = EVALUATOR_MODEL) -> int:
    with connect(DB_PATH) as conn:
        rows = pending_evaluations(conn, limit)
        if not rows:
            logger.info("No pending evaluations.")
            return 0
        completed = 0
        client = build_client()
        for row in rows:
            response_dict, usage, score, justification = evaluate_pair(client, row, model)
            insert_evaluation(
                conn,
                pair_id=row["id"],
                score=score,
                justification=justification,
                evaluator_model=model,
                evaluation_json=response_dict,
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

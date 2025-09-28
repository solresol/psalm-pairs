"""Generate Psalm pair arguments using the OpenAI Responses API."""
from __future__ import annotations

import argparse
import logging
import os

from . import DB_PATH
from .db import connect, insert_pair_argument, pending_pairs
from .openai_client import build_client, response_to_dict
from .psalms import format_psalm

DEFAULT_LIMIT = 50
DEFAULT_MODEL = os.environ.get("PSALM_PAIRS_MODEL", "gpt-5")

PROMPT_TEMPLATE = """Consider Psalm {x} and Psalm {y} (reproduced below). What arguments could you make to justify that Psalm {y} logically follows on from Psalm {x}? Consider stylistic similarities, similarities of form, similarities of vocab or ideas, shared roots (if you're doing the search in Hebrew), connections to sequences of events common in ancient Israelite life, mythology or history shared by the two psalms.\n\nRarer words are more significant than commoner words. Identical forms are more significant than similar forms. The same word class is more significant than different word classes formed from the same root. Identical roots are more significant than suppletive roots.\n\nPsalm {x}:\n{psalm_x}\n\nPsalm {y}:\n{psalm_y}\n"""


logger = logging.getLogger(__name__)


def build_prompt(psalm_x: int, psalm_y: int) -> str:
    return PROMPT_TEMPLATE.format(
        x=psalm_x,
        y=psalm_y,
        psalm_x=format_psalm(psalm_x),
        psalm_y=format_psalm(psalm_y),
    )


def generate_pair(client, psalm_x: int, psalm_y: int, model: str):
    prompt = build_prompt(psalm_x, psalm_y)
    logger.info("Requesting argument for Psalms %s -> %s", psalm_x, psalm_y)
    response = client.responses.create(
        model=model,
        input=prompt,
        reasoning={"effort": "high"},
        text={"verbosity": "medium"},
    )
    return prompt, response


def run(limit: int, model: str = DEFAULT_MODEL) -> int:
    with connect(DB_PATH) as conn:
        todo = pending_pairs(conn, limit)
        if not todo:
            logger.info("No remaining Psalm pairs to generate.")
            return 0
        created = 0
        client = build_client()
        for psalm_x, psalm_y in todo:
            prompt, response = generate_pair(client, psalm_x, psalm_y, model)
            insert_pair_argument(
                conn,
                psalm_x=psalm_x,
                psalm_y=psalm_y,
                prompt=prompt,
                response_text=getattr(response, "output_text", ""),
                response_json=response_to_dict(response),
                model=model,
            )
            created += 1
        return created


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Number of pairs to generate")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Model name to use")
    parser.add_argument("--quiet", action="store_true", help="Reduce logging output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO if not args.quiet else logging.WARNING)
    created = run(limit=args.limit, model=args.model)
    logger.info("Generated %s pair arguments", created)


if __name__ == "__main__":
    main()

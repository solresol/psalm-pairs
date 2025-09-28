# psalm-pairs
Pairwise similarity and alternative sequencing of the Psalms, with cross‑tradition numbering maps (MT ↔ LXX/Vulgate).

# What it does

It walks through every pair of Psalms and asks the following question:

        Consider Psalm X and Psalm Y (reproduced below). What arguments
        could you make to justify that Psalm Y logically follows on from
        Psalm X? Consider stylistic similarities, similarities of form,
        similarities of vocab or ideas, shared roots (if you're doing the
        search in Hebrew), connections to sequences of events common in
        ancient Israelite life, mythology or history shared by the two
        psalms.

        Rarer words are more significant than commoner words. Identical
        forms are more significant than similar forms. The same word class
        is more significant than different word classes formed from the
        same root. Identical roots are more significant than suppletive
        roots.

Having done that, a separate process then rates the arguments on a scale
of 0 (very weak) to 10 (very strong).


# The Hebrew source

Remember to cite Tanach:

Unicode/XML Leningrad Codex: UXLC 2.3 (27.4),
Tanach.us Inc., West Redding, CT, USA, April 2025.


## Running locally

The daily cron entry runs `cronscript.sh`, which will:

1. Pull the latest code
2. Generate and store a configurable number of Psalm pair arguments
3. Evaluate pending arguments
4. Rebuild the status website and deploy it to the production host

Useful environment variables:

- `PAIRS_PER_DAY` – number of new arguments to request (default 50)
- `EVALS_PER_DAY` – number of evaluations to perform (default 50)
- `SITE_DIR` – output directory for the generated website (default `site`)
- `REMOTE_TARGET` – `scp` destination for deployment; leave blank to skip copying

The scripts expect an OpenAI API key at `~/.openai.key`.

All Python entry points are run via [`uv`](https://docs.astral.sh/uv/) (for example, `uv run psalm_pairs/generate_pairs.py`).

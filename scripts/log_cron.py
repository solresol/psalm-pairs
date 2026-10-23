"""Keep cron success output in private logs; retain stderr and failure context."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def flush_log(log) -> None:
    log.flush()
    os.fsync(log.fileno())


def run(command: list[str], log_dir: Path) -> int:
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    fd, path = tempfile.mkstemp(prefix=f"cron-{stamp}-", suffix=".log", dir=log_dir)
    status = 1
    logging_error = None
    with ExitStack() as stack:
        log = stack.enter_context(os.fdopen(fd, "wb"))
        stdout = stack.enter_context(tempfile.TemporaryFile())
        stderr = stack.enter_context(tempfile.TemporaryFile())
        try:
            log.write(f"Started {stamp}\n".encode())
            flush_log(log)  # Fail before paid work if the log cannot be written.
            try:
                status = subprocess.run(command, stdout=stdout, stderr=stderr).returncode
                if status < 0:
                    status = 128 - status
            except OSError as exc:
                status = 127
                stderr.write(f"Could not start cron command: {exc}\n".encode())
            stdout.seek(0)
            stderr.seek(0)
            log.write(b"--- stdout ---\n")
            shutil.copyfileobj(stdout, log)
            log.write(b"\n--- stderr ---\n")
            shutil.copyfileobj(stderr, log)
            log.write(f"\nFinished with exit {status}\n".encode())
            flush_log(log)
        except OSError as exc:
            logging_error = exc
        finally:
            try:
                log.close()
            except OSError as exc:
                logging_error = exc

        # Cron receives all unexpected diagnostics, even if the command succeeds.
        stderr.seek(0)
        shutil.copyfileobj(stderr, sys.stderr.buffer)
        if status != 0 or logging_error is not None:
            stdout.seek(0)
            shutil.copyfileobj(stdout, sys.stderr.buffer)
            if logging_error is not None:
                print(f"Psalmer cron logging failed for {path}: {logging_error}", file=sys.stderr)
            print(f"Psalmer cron exit {status}; diagnostic log: {path}", file=sys.stderr)
        return status or (1 if logging_error is not None else 0)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: log_cron.py COMMAND [ARG ...]", file=sys.stderr)
        return 2
    default_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "psalm-pairs"
    log_dir = Path(os.environ.get("PSALM_PAIRS_LOG_DIR", default_dir))
    try:
        return run(sys.argv[1:], log_dir)
    except OSError as exc:
        print(f"Psalmer cron logging failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

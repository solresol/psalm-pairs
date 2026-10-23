from contextlib import redirect_stderr
import errno
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOGGER = ROOT / "scripts/log_cron.py"
spec = importlib.util.spec_from_file_location("log_cron", LOGGER)
logger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logger)


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.logs = self.root / "logs"

    def launch(self, code):
        return subprocess.run(
            [sys.executable, str(LOGGER), sys.executable, "-c", code],
            env={**os.environ, "PSALM_PAIRS_LOG_DIR": str(self.logs)},
            capture_output=True, text=True,
        )

    def test_success_is_silent_and_log_is_private(self):
        result = self.launch("print('routine success')")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        log, = self.logs.glob("*.log")
        self.assertIn("routine success", log.read_text())
        self.assertIn("Finished with exit 0", log.read_text())
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_unexpected_stderr_is_visible_on_success(self):
        result = self.launch("import sys; print('unexpected warning', file=sys.stderr)")
        self.assertEqual(result.returncode, 0)
        self.assertIn("unexpected warning", result.stderr)
        self.assertIn("unexpected warning", next(self.logs.glob("*.log")).read_text())

    def test_command_failure_replays_output_and_preserves_exit(self):
        result = self.launch("import sys; print('stdout context'); print('error', file=sys.stderr); sys.exit(42)")
        self.assertEqual(result.returncode, 42)
        for text in ("stdout context", "error", "diagnostic log"):
            self.assertIn(text, result.stderr)

    def test_missing_command_is_nonzero(self):
        result = subprocess.run(
            [sys.executable, str(LOGGER), str(self.root / "missing")],
            env={**os.environ, "PSALM_PAIRS_LOG_DIR": str(self.logs)},
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 127)
        self.assertIn("Could not start cron command", result.stderr)

    def test_log_directory_failure_prevents_work(self):
        self.logs.write_text("not a directory")
        marker = self.root / "should-not-exist"
        result = self.launch(f"from pathlib import Path; Path({str(marker)!r}).touch()")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("logging failed", result.stderr)
        self.assertFalse(marker.exists())

    def invoke_with_log_failure(self, code, effects):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="utf-8", write_through=True)
        try:
            with redirect_stderr(stream), patch.object(logger, "flush_log", side_effect=effects):
                status = logger.run([sys.executable, "-c", code], self.logs)
            return status, buffer.getvalue().decode()
        finally:
            stream.detach()

    def test_disk_failure_preflight_prevents_work(self):
        marker = self.root / "should-not-exist"
        status, output = self.invoke_with_log_failure(
            f"from pathlib import Path; Path({str(marker)!r}).touch()",
            [OSError(errno.ENOSPC, "disk full")],
        )
        self.assertNotEqual(status, 0)
        self.assertIn("logging failed", output)
        self.assertFalse(marker.exists())

    def test_log_write_failure_after_success_is_nonzero_and_replays(self):
        status, output = self.invoke_with_log_failure(
            "print('retained context')", [None, OSError(errno.ENOSPC, "disk full")],
        )
        self.assertNotEqual(status, 0)
        self.assertIn("retained context", output)
        self.assertIn("logging failed", output)

    def test_log_failure_does_not_mask_command_failure(self):
        status, output = self.invoke_with_log_failure(
            "import sys; print('context'); sys.exit(42)",
            [None, OSError(errno.EIO, "log write failed")],
        )
        self.assertEqual(status, 42)
        self.assertIn("context", output)
        self.assertIn("logging failed", output)

    def test_log_close_failure_is_visible_after_success_and_failure(self):
        class CloseFailure:
            def __init__(self, wrapped):
                self.wrapped = wrapped

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

            def __getattr__(self, name):
                return getattr(self.wrapped, name)

            def close(self):
                if not self.wrapped.closed:
                    self.wrapped.close()
                    raise OSError(errno.EIO, "simulated close failure")

        real_fdopen = logger.os.fdopen
        for worker_status in (0, 42):
            with self.subTest(worker_status=worker_status):
                buffer = io.BytesIO()
                stream = io.TextIOWrapper(buffer, encoding="utf-8", write_through=True)
                try:
                    with patch.object(logger.os, "fdopen", side_effect=lambda *a, **kw: CloseFailure(real_fdopen(*a, **kw))), redirect_stderr(stream):
                        status = logger.run(
                            [sys.executable, "-c", f"import sys; print('captured context'); sys.exit({worker_status})"],
                            self.logs,
                        )
                    self.assertEqual(status, worker_status or 1)
                    self.assertIn(b"captured context", buffer.getvalue())
                    self.assertIn(b"logging failed", buffer.getvalue())
                finally:
                    stream.detach()


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        shutil.copy(ROOT / "cronscript.sh", self.root)
        shutil.copy(LOGGER, self.root / "scripts")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.trace = self.root / "trace"
        stub = '''#!/bin/bash
name=${0##*/}
step=$name
if [[ "$name" == uv ]]; then step=${2##*/}; fi
printf '%s %s\\n' "$name" "$*" >> "$TRACE"
echo "routine output from $step"
if [[ "$step" == "${FAIL_STEP:-}" ]]; then
  echo "failure from $step" >&2
  exit 42
fi
'''
        for name in ("git", "uv", "rsync"):
            path = self.bin / name
            path.write_text(stub)
            path.chmod(0o700)

    def launch(self, fail_step=""):
        return subprocess.run(
            ["/bin/bash", str(self.root / "cronscript.sh")],
            env={**os.environ, "PATH": str(self.bin) + os.pathsep + os.defpath,
                 "TRACE": str(self.trace), "FAIL_STEP": fail_step,
                 "PSALM_PAIRS_LOG_DIR": str(self.root / "logs")},
            capture_output=True, text=True,
        )

    def test_success_runs_all_stages_silently(self):
        result = self.launch()
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        lines = self.trace.read_text().splitlines()
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[0], "git pull --ff-only -q")
        for script in ("generate_pairs.py", "evaluate_pairs.py", "website.py"):
            self.assertTrue(any(script in line for line in lines))
        self.assertTrue(lines[-1].startswith("rsync "))

    def test_failures_stop_later_stages_and_reach_cron(self):
        for step, calls in (("git", 1), ("generate_pairs.py", 2),
                            ("evaluate_pairs.py", 3), ("website.py", 4), ("rsync", 5)):
            with self.subTest(step=step):
                self.trace.unlink(missing_ok=True)
                result = self.launch(step)
                self.assertEqual(result.returncode, 42)
                self.assertIn(f"failure from {step}", result.stderr)
                self.assertIn("diagnostic log", result.stderr)
                self.assertEqual(len(self.trace.read_text().splitlines()), calls)


if __name__ == "__main__":
    unittest.main()

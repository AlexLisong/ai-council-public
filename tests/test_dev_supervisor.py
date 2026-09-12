"""Exercise the developer launcher with disposable subprocesses."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix", "process-group checks use POSIX signals")
class DevelopmentProcesses(unittest.TestCase):
    def test_stop_cleans_both_children(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            commands = []
            for name in ("api", "ui"):
                commands.append([sys.executable, "-c",
                    "import os,time,pathlib; "
                    f"pathlib.Path({str(directory / name)!r}).write_text(str(os.getpid())); "
                    "time.sleep(60)"])
            runner = subprocess.Popen([
                sys.executable, "-c",
                "from scripts.dev import supervise; "
                f"raise SystemExit(supervise({commands!r}, {str(ROOT)!r}))",
            ], cwd=ROOT)
            try:
                deadline = time.monotonic() + 5
                while not all((directory / name).exists() for name in ("api", "ui")):
                    if time.monotonic() >= deadline:
                        self.fail("Child processes did not start")
                    time.sleep(0.02)
                children = [int((directory / name).read_text()) for name in ("api", "ui")]
                runner.send_signal(signal.SIGTERM)
                self.assertEqual(runner.wait(timeout=5), 0)
                for pid in children:
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)
            finally:
                if runner.poll() is None:
                    runner.terminate()
                    runner.wait(timeout=5)

    def test_child_failure_reaches_the_caller(self):
        commands = [[sys.executable, "-c", "raise SystemExit(7)"],
                    [sys.executable, "-c", "import time; time.sleep(60)"]]
        result = subprocess.run([
            sys.executable, "-c",
            "from scripts.dev import supervise; "
            f"raise SystemExit(supervise({commands!r}, {str(ROOT)!r}))",
        ], cwd=ROOT, timeout=5)
        self.assertEqual(result.returncode, 7)

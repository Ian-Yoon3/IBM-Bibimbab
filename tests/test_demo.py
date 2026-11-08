"""Smoke test: demo.py must run end to end (no network, no credentials)."""

import os
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestDemoRuns(unittest.TestCase):
    def test_demo_exits_cleanly(self):
        # demo.py broke once when explored options stopped having a scenario_id
        # Force UTF-8 for the child process: on Windows a piped stdout uses the
        # locale code page (e.g. cp949), which cannot encode "—" or "→".
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.run(
            [sys.executable, "demo.py"], cwd=ROOT, env=env,
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("Transfers + buy 40 x OF02", proc.stdout)
        self.assertIn("Demo complete", proc.stdout)


if __name__ == "__main__":
    unittest.main()

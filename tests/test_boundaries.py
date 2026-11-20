"""Boundary test: no file under engine/ or montecarlo/ may import synthetic_history."""

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _collect_py_files(*dirs: str) -> list:
    files = []
    for d in dirs:
        files.extend((ROOT / d).rglob("*.py"))
    return files


def _imports_synthetic_history(path: pathlib.Path) -> bool:
    """Return True if the file contains any import of synthetic_history."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "synthetic_history" or alias.name.startswith("synthetic_history."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "synthetic_history" or module.startswith("synthetic_history."):
                return True
    return False


class TestNoBoundaryViolations(unittest.TestCase):

    def test_engine_does_not_import_synthetic_history(self):
        violations = []
        for f in (ROOT / "engine").rglob("*.py"):
            if _imports_synthetic_history(f):
                violations.append(str(f.relative_to(ROOT)))
        self.assertEqual(violations, [],
            f"engine/ files import synthetic_history: {violations}")

    def test_montecarlo_does_not_import_synthetic_history(self):
        violations = []
        for f in (ROOT / "montecarlo").rglob("*.py"):
            if _imports_synthetic_history(f):
                violations.append(str(f.relative_to(ROOT)))
        self.assertEqual(violations, [],
            f"montecarlo/ files import synthetic_history: {violations}")


if __name__ == "__main__":
    unittest.main()

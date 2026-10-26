"""The synthetic scope lives only under tests/ and the application cannot reach it.

FR-001, Constitution Principles I and IV.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "scope_gui"
TEST_MODULES = {"tests", "fakes", "synthetic_scope", "bench", "conftest"}


def _source_files():
    return [p for p in SRC.rglob("*") if p.is_file() and "__pycache__" not in p.parts]


def test_source_tree_found():
    assert any(p.name == "driver.py" for p in _source_files())


def test_no_file_in_src_mentions_synthetic():
    offenders = [
        str(p.relative_to(ROOT))
        for p in _source_files()
        if "synthetic" in p.read_text(encoding="utf-8", errors="ignore").lower()
    ]
    assert offenders == []


def test_no_import_of_test_modules_in_src():
    offenders = []
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            if any(name.split(".")[0] in TEST_MODULES for name in names):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


def test_importing_the_entry_point_does_not_load_synthetic_modules():
    # A fresh interpreter: the test session itself has imported the test helpers.
    code = (
        "import scope_gui.__main__, sys; "
        "print(sorted(m for m in ('synthetic_scope', 'fakes', 'bench') if m in sys.modules))"
    )
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    env.pop("PYTHONPATH", None)  # pytest's `pythonpath = tests` is not inherited anyway
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"

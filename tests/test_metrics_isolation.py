"""metrics/ is pure computation over the event contract.

No simulator internals, no ground-truth sidecars (*.truth.json), no file I/O:
tools receive a Match and return a ToolResult. Checked on the AST, so words in
docstrings or caveats ("not validated against ground truth") are fine.
"""

import ast
from pathlib import Path

import pytest

import pitchside.metrics

METRICS_DIR = Path(pitchside.metrics.__file__).parent
SOURCES = sorted(METRICS_DIR.rglob("*.py"))

IO_MODULES = {"io", "os", "pathlib", "shutil", "tempfile", "glob"}
IO_NAMES = {"read_jsonl", "write_jsonl", "to_jsonl_bytes"}
IO_METHODS = {"read_text", "read_bytes", "write_text", "write_bytes", "open", "mkdir",
              "unlink", "rmdir", "rename", "touch"}


def violations(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in IO_MODULES or alias.name.startswith("pitchside.simulator"):
                    found.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in IO_MODULES or node.module.startswith("pitchside.simulator"):
                found.append(f"from {node.module} import ...")
            found += [f"import {a.name}" for a in node.names if a.name in IO_NAMES]
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "open":
                found.append("open(...)")
            elif isinstance(func, ast.Attribute) and func.attr in IO_METHODS:
                found.append(f".{func.attr}(...)")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if ".truth.json" in node.value:
                found.append(f"string {node.value!r}")
    return found


def test_metrics_sources_exist():
    assert any(p.name == "grounding.py" for p in SOURCES)


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_metrics_module_is_pure(path):
    assert violations(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "source",
    [
        "import pathlib",
        "from os import path",
        "from pitchside.events.match import read_jsonl",
        "from pitchside.simulator.engine import simulate_match",
        "open('m.jsonl')",
        "p.read_text()",
        "NAME = 'sim-42.truth.json'",
        "pattern = f'{stem}.truth.json'",
    ],
)
def test_checker_catches(source):
    assert violations(source)


def test_checker_allows_ground_truth_caveat():
    source = 'CAVEAT = "thresholds not validated against ground truth"\n"""truth in a docstring"""'
    assert violations(source) == []

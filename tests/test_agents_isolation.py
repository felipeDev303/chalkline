"""agents/ sees only what a live broadcast would: events, metrics, no simulator truth."""

import ast
from pathlib import Path

import pytest

import pitchside.agents

SOURCES = sorted(Path(pitchside.agents.__file__).parent.rglob("*.py"))


def _problems(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.startswith("pitchside.simulator")]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("pitchside.simulator"):
                found.append(node.module)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if ".truth.json" in node.value:
                found.append(repr(node.value))
    return found


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_agents_never_use_simulator_or_ground_truth(path):
    assert _problems(path) == []

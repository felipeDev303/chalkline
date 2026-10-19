"""metrics/ consumes only the event contract: no simulator internals, no ground truth."""

import ast
from pathlib import Path

import pitchside.metrics

METRICS_DIR = Path(pitchside.metrics.__file__).parent
SOURCES = sorted(METRICS_DIR.rglob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_metrics_sources_exist():
    assert any(p.name == "grounding.py" for p in SOURCES)


def test_metrics_never_import_the_simulator():
    for path in SOURCES:
        bad = {m for m in _imported_modules(path) if m.startswith("pitchside.simulator")}
        assert not bad, f"{path.name} imports {bad}"


def test_metrics_never_read_ground_truth_sidecars():
    for path in SOURCES:
        assert "truth" not in path.read_text(encoding="utf-8").lower(), path.name

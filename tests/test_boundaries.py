"""Layer 5: the folders stay separable into their own repositories."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = {
    "utils": set(),
    "aggregator": {"utils"},
    "example_device": {"utils", "aggregator"},
    "orchestrator": {"utils", "aggregator"},
    "viewer": {"utils", "aggregator", "orchestrator"},
}
OURS = set(ALLOWED) | {"anonymizer", "sparsifier", "summarizer", "adapters"}


def _imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found & OURS


@pytest.mark.parametrize("package", sorted(ALLOWED))
def test_package_only_imports_what_it_may(package):
    folder = ROOT / package
    if not folder.exists():
        pytest.skip(f"{package}/ not built yet")
    for path in folder.rglob("*.py"):
        extra = _imports(path) - ALLOWED[package] - {package}
        assert not extra, f"{path.relative_to(ROOT)} imports {sorted(extra)}"


def test_sql_lives_only_in_the_aggregator():
    for package in OURS - {"aggregator"}:
        for path in (ROOT / package).rglob("*.py") if (ROOT / package).exists() else []:
            assert "sqlite3" not in _all_imports(path), f"{path.relative_to(ROOT)} imports sqlite3"


def _all_imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found

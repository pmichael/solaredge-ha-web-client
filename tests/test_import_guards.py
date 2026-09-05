"""Runtime solaredge_web imports stay in coordinator.py."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).parent.parent / "custom_components" / "solaredge_ha_web_client"


def _is_type_checking(test: ast.expr) -> bool:
    return isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"


class _RuntimeImports(ast.NodeVisitor):
    def __init__(self) -> None:
        self.modules: list[str] = []
        self._skipping = 0

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking(node.test):
            self._skipping += 1
            self.generic_visit(node)
            self._skipping -= 1
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        if self._skipping:
            return
        self.modules.extend(alias.name.split(".", 1)[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self._skipping or not node.module:
            return
        self.modules.append(node.module.split(".", 1)[0])


def test_only_coordinator_imports_solaredge_web_at_runtime() -> None:
    """A second runtime importer would split the only permitted client."""
    offenders: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        visitor = _RuntimeImports()
        visitor.visit(tree)
        if "solaredge_web" in visitor.modules and path.name != "coordinator.py":
            offenders.append(path.name)
    assert offenders == []

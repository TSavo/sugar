#!/usr/bin/env python3
"""Hard-red census of behavior construction under ``factory/``.

The factory boundary has two lawful actions: select a registered Sugar, or
raise FactoryPanic. This scanner deliberately has no debt allowlist; every
reported site remains red until its behavior is promoted to Sugar and deleted
from the factory package.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import NamedTuple


class Offender(NamedTuple):
    path: str
    line: int
    kind: str


_TEMPORAL_CONSTRUCTORS = frozenset(
    {
        "TemporalContext",
        "bind_alias",
        "bind_temporal",
        "bind_value",
        "extend_scope",
        "with_temporal",
    }
)
_FLOOR_PROJECTIONS = frozenset(
    {
        "complete_value",
        "contribution",
        "floor_to_term",
        "to_term",
    }
)


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _is_ast_reference(node: ast.AST) -> bool:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "ast"
    ):
        return True
    return any(_is_ast_reference(child) for child in ast.iter_child_nodes(node))


class _FactoryConstructionScanner(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.offenders: set[Offender] = set()
        self.ir_builders: set[str] = set()

    def add(self, node: ast.AST, kind: str) -> None:
        self.offenders.add(Offender(self.path, node.lineno, kind))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "sugar_lift_py_tests.ir":
            self.ir_builders.update(alias.asname or alias.name for alias in node.names)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name == "IncompleteFunctionBody":
            self.add(node, "non-contract-third-result")
        if any(
            _is_ast_reference(base) and _terminal_name(base) == "NodeVisitor"
            for base in node.bases
        ):
            self.add(node, "semantic-ast-classification")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        has_statement_walk = any(isinstance(child, ast.For) for child in ast.walk(node))
        has_observed_dispatch = any(
            isinstance(child, ast.Attribute) and child.attr == "observed"
            for child in ast.walk(node)
        )
        if has_statement_walk and has_observed_dispatch:
            self.add(node, "control-flow-interpretation")
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        if (
            name == "isinstance"
            and len(node.args) >= 2
            and _is_ast_reference(node.args[1])
        ):
            self.add(node, "semantic-ast-classification")
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ast"
            and node.func.attr == "walk"
        ):
            self.add(node, "semantic-ast-classification")
        if name in self.ir_builders:
            self.add(node, "ir-construction")
        if name is not None and name.endswith("Value"):
            self.add(node, "floor-value-construction")
        if name is not None and name.endswith("Sugar"):
            self.add(node, "sugar-construction")
        if name == "reduce":
            self.add(node, "sugar-body-reduction")
        if name in _FLOOR_PROJECTIONS:
            self.add(node, "floor-projection")
        if name in _TEMPORAL_CONSTRUCTORS:
            self.add(node, "temporal-binding-construction")
        self.generic_visit(node)


def _terminal_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def scan_source(source: str, path: str) -> list[Offender]:
    scanner = _FactoryConstructionScanner(path)
    scanner.visit(ast.parse(source, filename=path))
    return sorted(scanner.offenders)


def scan_factory(factory_root: Path) -> list[Offender]:
    offenders: list[Offender] = []
    for path in sorted(factory_root.rglob("*.py")):
        relative = path.relative_to(factory_root.parent).as_posix()
        offenders.extend(scan_source(path.read_text(encoding="utf-8"), relative))
    return sorted(offenders)


def format_offenders(offenders: list[Offender]) -> str:
    return "\n".join(f"{row.path}:{row.line}:{row.kind}" for row in offenders)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--factory-root",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "src"
            / "sugar_lift_py_tests"
            / "factory"
        ),
    )
    args = parser.parse_args()
    offenders = scan_factory(args.factory_root)
    if offenders:
        print(
            "FACTORY ZERO-TOLERANCE RED: "
            f"{len(offenders)} behavior-construction side doors"
        )
        print(format_offenders(offenders))
        return 1
    print("FACTORY ZERO-TOLERANCE GREEN: 0 behavior-construction side doors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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


# Replacement plan per crime kind. Green for a site means this plan is
# realized and the factory line is deleted — not wrapped, not allowlisted.
_REPLACEMENT: dict[str, str] = {
    "ir-construction": (
        "Promote IR operand/guard minting into the Sugar that owns the shape "
        "(e.g. CompareSugar / NameSugar / PrimitiveLiteralSugar / a dedicated "
        "control-flow guard Sugar). Factory must not import sugar_lift_py_tests.ir "
        "or call make_var/num/eq/not_."
    ),
    "floor-value-construction": (
        "Construct floor values only inside Sugar/floor after the factory hands "
        "finished children (SymbolicValue via formal/name Sugar; ImportAliasValue "
        "via ImportFromSugar; BlockValue via Block statement Sugar). Delete "
        "direct floor constructors from factory/."
    ),
    "floor-projection": (
        "complete_value / floor_to_term / to_term belong to Sugar.desugar or "
        "floor algebra, never to factory helpers. Move projection into the "
        "owning Sugar reduce path."
    ),
    "sugar-body-reduction": (
        "Factory selects Sugar; it does not call body.reduce. Reduction is "
        "Sugar-owned desugar after claim.new. Delete .reduce from factory/."
    ),
    "temporal-binding-construction": (
        "TemporalContext / bind_temporal / with_temporal are Sugar/floor "
        "territory (formal binds, module seeds, scope rebind Sugars). Factory "
        "must not mint or mutate temporal bindings."
    ),
    "control-flow-interpretation": (
        "Statement walks that interpret Return/If/observed control flow belong "
        "to ControlFlowBodySugar (or equivalent), selected by the catalog — not "
        "to factory sugar_constructors walks."
    ),
    "sugar-construction": (
        "Only catalog claim.new constructs a Sugar. Delete build_*_sugar "
        "helpers and direct FooSugar(...) assembly in factory/."
    ),
    "non-contract-third-result": (
        "Factory contract is Sugar | FactoryPanic only. IncompleteFunctionBody "
        "(or any third result) must become FactoryPanic at the factory boundary "
        "or Incomplete inside a Sugar reduce — never a factory-defined soft path."
    ),
    "semantic-ast-classification": (
        "Structural observed-kind exposure may live only as a pure SourceFragment "
        "gateway API; semantic loop/control classification "
        "(classify_loop_control_scope, scope store walks, NodeVisitor shape "
        "classifiers) promotes to ForSugar / WhileSugar / LoopControlSugar. "
        "No semantic classify inside factory/."
    ),
}


def format_offenders(offenders: list[Offender]) -> str:
    return "\n".join(f"{row.path}:{row.line}:{row.kind}" for row in offenders)


def format_report(offenders: list[Offender]) -> str:
    """Full red report: R, kind tallies with replacement plans, then loci."""
    from collections import Counter

    by_kind = Counter(row.kind for row in offenders)
    by_file = Counter(row.path for row in offenders)
    lines = [
        f"R_factory_behavior_side_doors = {len(offenders)}",
        "Lawful factory actions: select registered Sugar | FactoryPanic.",
        "No allowlist. Compare consecutive runs for Delta R.",
        "",
        "By kind (replacement plan applies to every locus of that kind):",
    ]
    for kind, count in by_kind.most_common():
        plan = _REPLACEMENT.get(
            kind, "Promote into an explicit Sugar; delete from factory/."
        )
        lines.append(f"  {count:4d}  {kind}")
        lines.append(f"        → {plan}")
    lines.append("")
    lines.append("By file:")
    for path, count in by_file.most_common():
        lines.append(f"  {count:4d}  {path}")
    lines.append("")
    lines.append("Loci:")
    lines.append(format_offenders(offenders))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Zero-tolerance census: factory/ may only select Sugar or FactoryPanic. "
            "Reports R and stays exit-red until R == 0."
        )
    )
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
        print(format_report(offenders))
        return 1
    print("FACTORY ZERO-TOLERANCE GREEN: 0 behavior-construction side doors")
    print("R_factory_behavior_side_doors = 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

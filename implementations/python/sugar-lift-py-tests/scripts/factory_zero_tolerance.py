#!/usr/bin/env python3
"""Hard-red census of semantic side doors under ``factory/`` and ``sugar/``.

The factory boundary has two lawful actions: select a registered Sugar, or
raise FactoryPanic. Sugar owns behavior construction, but may not classify raw
AST shapes beside that construction. Structural SourceFragment child accessors
and install-source resolution are not semantic construction. This scanner has
no debt allowlist.
"""

from __future__ import annotations

import argparse
import ast
import json
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
    def __init__(self, path: str, *, scope: str):
        self.path = path
        self.scope = scope
        self.offenders: set[Offender] = set()
        self.ir_builders: set[str] = set()
        self.function_depth = 0

    def add(self, node: ast.AST, kind: str) -> None:
        self.offenders.add(Offender(self.path, node.lineno, kind))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "sugar_lift_py_tests.ir":
            self.ir_builders.update(alias.asname or alias.name for alias in node.names)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if self.scope == "factory" and node.name == "IncompleteFunctionBody":
            self.add(node, "non-contract-third-result")
        if (
            self.function_depth == 0
            and self._semantic_ast_is_forbidden()
            and any(
                _is_ast_reference(base) and _terminal_name(base) == "NodeVisitor"
                for base in node.bases
            )
        ):
            self.add(node, "semantic-ast-classification")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        has_ast_classification = _has_ast_classification(node)
        if (
            has_ast_classification
            and self._semantic_ast_is_forbidden()
            and (
                self.scope == "sugar"
                or _factory_function_drives_semantics(node, self.path)
            )
        ):
            self.add(node, "semantic-ast-classification")
        has_statement_walk = any(isinstance(child, ast.For) for child in ast.walk(node))
        has_observed_dispatch = any(
            isinstance(child, ast.Attribute) and child.attr == "observed"
            for child in ast.walk(node)
        )
        if (
            self.scope == "factory"
            and has_statement_walk
            and has_observed_dispatch
            and (
                _function_constructs_behavior(node)
                or _factory_function_interprets_control_flow(node, self.path)
            )
        ):
            self.add(node, "control-flow-interpretation")
        self.function_depth += 1
        try:
            self.generic_visit(node)
        finally:
            self.function_depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def _semantic_ast_is_forbidden(self) -> bool:
        return self.path != "sugar/install_source_dig.py"

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        if self.scope == "factory" and name in self.ir_builders:
            self.add(node, "ir-construction")
        if self.scope == "factory" and name is not None and name.endswith("Value"):
            self.add(node, "floor-value-construction")
        if self.scope == "factory" and name is not None and name.endswith("Sugar"):
            self.add(node, "sugar-construction")
        if self.scope == "factory" and name == "reduce":
            self.add(node, "sugar-body-reduction")
        if self.scope == "factory" and name in _FLOOR_PROJECTIONS:
            self.add(node, "floor-projection")
        if self.scope == "factory" and name in _TEMPORAL_CONSTRUCTORS:
            self.add(node, "temporal-binding-construction")
        self.generic_visit(node)


def _terminal_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _has_ast_classification(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        (
            isinstance(child, ast.Call)
            and _call_name(child) == "isinstance"
            and len(child.args) >= 2
            and _is_ast_reference(child.args[1])
        )
        or (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and isinstance(child.func.value, ast.Name)
            and child.func.value.id == "ast"
            and child.func.attr == "walk"
        )
        or (
            isinstance(child, ast.ClassDef)
            and any(
                _is_ast_reference(base) and _terminal_name(base) == "NodeVisitor"
                for base in child.bases
            )
        )
        for child in ast.walk(node)
    )


def _factory_function_drives_semantics(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    path: str,
) -> bool:
    return (
        path == "factory/source_fragment.py" and node.name.startswith("classify_")
    ) or (path == "factory/node_kind.py" and node.name == "of")


def _function_constructs_behavior(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    ir_names = {
        alias.asname or alias.name
        for child in ast.walk(node)
        if isinstance(child, ast.ImportFrom)
        and child.module == "sugar_lift_py_tests.ir"
        for alias in child.names
    }
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        name = _call_name(child)
        if name in ir_names:
            return True
        if name == "reduce" or name in _FLOOR_PROJECTIONS:
            return True
        if name in _TEMPORAL_CONSTRUCTORS:
            return True
        if name is not None and (name.endswith("Value") or name.endswith("Sugar")):
            return True
    return False


def _factory_function_interprets_control_flow(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    path: str,
) -> bool:
    return path == "factory/package_source_accounting.py" and node.name in {
        "_imported_top_level_packages",
        "_package_accounting_summary",
    }


def scan_source(
    source: str,
    path: str,
    *,
    scope: str | None = None,
) -> list[Offender]:
    selected_scope = scope or ("factory" if path.startswith("factory/") else "sugar")
    scanner = _FactoryConstructionScanner(path, scope=selected_scope)
    scanner.visit(ast.parse(source, filename=path))
    return sorted(scanner.offenders)


def scan_factory(factory_root: Path) -> list[Offender]:
    offenders: list[Offender] = []
    for path in sorted(factory_root.rglob("*.py")):
        relative = path.relative_to(factory_root.parent).as_posix()
        offenders.extend(
            scan_source(
                path.read_text(encoding="utf-8"),
                relative,
                scope="factory",
            )
        )
    return sorted(offenders)


def scan_package(package_root: Path) -> list[Offender]:
    offenders: list[Offender] = []
    for scope in ("factory", "sugar"):
        root = package_root / scope
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(package_root).as_posix()
            offenders.extend(
                scan_source(
                    path.read_text(encoding="utf-8"),
                    relative,
                    scope=scope,
                )
            )
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
        "Structural SourceFragment child projection and install-source resolution "
        "are lawful. Behavior-driving raw-AST classification promotes to the "
        "owning Sugar; delete classify_loop_control_scope and leaf-sugar "
        "Match/Subscript walkers."
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
        f"R_behavior_side_doors = {len(offenders)}",
        "Factory: select registered Sugar | FactoryPanic.",
        "Sugar: construct behavior without raw-AST classification side doors.",
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


def read_baseline(path: Path) -> int:
    document = json.loads(path.read_text(encoding="utf-8"))
    return int(document["R_behavior_side_doors"])


def evaluate_ratchet(observed: int, baseline: int) -> tuple[bool, str]:
    if observed > baseline:
        increase = observed - baseline
        return (
            False,
            "FACTORY ZERO-TOLERANCE RATCHET RED: "
            f"R increased by {increase} ({baseline} -> {observed}); "
            "new behavior-construction side doors are forbidden.",
        )
    if observed < baseline:
        return (
            True,
            "FACTORY ZERO-TOLERANCE RATCHET GREEN: "
            f"R decreased ({baseline} -> {observed}); "
            f"lower the recorded baseline to {observed} in this promotion PR.",
        )
    return (
        True,
        "FACTORY ZERO-TOLERANCE RATCHET GREEN: "
        f"R remains at the recorded baseline {baseline}.",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Zero-tolerance census: factory construction and ad-hoc AST "
            "classification across factory/ and sugar/. Without a baseline it "
            "stays exit-red until R == 0; with a baseline it rejects increases."
        )
    )
    parser.add_argument(
        "--package-root",
        type=Path,
        default=(Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests"),
    )
    parser.add_argument(
        "--baseline-file",
        type=Path,
        help=(
            "DEPRECATED for enforcement. If set, only prints a ratchet advisory; "
            "exit code is still red while R > 0 (R>0 ⇒ CI red). "
            "Delete the baseline file once R==0."
        ),
    )
    args = parser.parse_args()
    offenders = scan_package(args.package_root)
    if args.baseline_file is not None and args.baseline_file.exists():
        baseline = read_baseline(args.baseline_file)
        _, status = evaluate_ratchet(len(offenders), baseline)
        print("ADVISORY (not the gate):", status)
    # Hard law: R > 0 ⇒ red. No baseline may convert non-zero debt into green.
    if offenders:
        print(
            "FACTORY ZERO-TOLERANCE RED: "
            f"{len(offenders)} behavior-construction side doors"
        )
        print(format_report(offenders))
        return 1
    print("FACTORY ZERO-TOLERANCE GREEN: 0 behavior-construction side doors")
    print("R_behavior_side_doors = 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

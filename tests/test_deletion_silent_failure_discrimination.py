"""Source-level laws for deletion casualties that otherwise emit plausible numbers.

The detectors in this file deliberately run against planted truthful and lying
twins before they inspect the live census sources.  They are not vocabulary
greps: receiver identity and expression shape decide whether a read is safe.

There is intentionally no shortened-body statement-count law here.  Without a
semantic conservation identity, that would encode deleted taxonomy as a
baseline and condemn deliberate removal.  Census body loss belongs to the
producer/consumer conservation seal instead.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
RECENSUS = (
    ROOT
    / "implementations/python/sugar-lift-py-tests/scripts/control_effect_recensus.py"
)
COMPOSE = (
    ROOT
    / "implementations/python/sugar-lift-py-tests/scripts/compose_control_effect_board.py"
)


@dataclass(frozen=True)
class ExclusiveDeletedKeyRead:
    path: str
    qname: str
    line: int
    keys: tuple[str, ...]


@dataclass(frozen=True)
class CollapsedPredicate:
    path: str
    qname: str
    first_line: int
    unreachable_line: int
    predicate: str


def _function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    assert len(matches) == 1, (name, len(matches))
    return matches[0]


def _literal_subscript_key(node: ast.Subscript) -> str | None:
    if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
        return node.slice.value
    return None


def _assignment_value(
    function: ast.FunctionDef | ast.AsyncFunctionDef, target_name: str
) -> ast.expr:
    matches: list[ast.expr] = []
    for node in function.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        if any(isinstance(target, ast.Name) and target.id == target_name for target in targets):
            if node.value is not None:
                matches.append(node.value)
    assert len(matches) == 1, (function.name, target_name, len(matches))
    return matches[0]


def _produced_keys(
    function: ast.FunctionDef | ast.AsyncFunctionDef, container: str
) -> frozenset[str]:
    keys: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.add(key.value)
        targets: tuple[ast.expr, ...]
        if isinstance(node, ast.AugAssign):
            targets = (node.target,)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = tuple(node.targets) if isinstance(node, ast.Assign) else (node.target,)
        else:
            continue
        for target in targets:
            if not isinstance(target, ast.Subscript):
                continue
            if not isinstance(target.value, ast.Name) or target.value.id != container:
                continue
            key = _literal_subscript_key(target)
            if key is not None:
                keys.add(key)
    return frozenset(keys)


def _contains_wire_field(node: ast.AST, wire_field: str) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
            continue
        if child.func.attr != "get" or not child.args:
            continue
        key = child.args[0]
        if isinstance(key, ast.Constant) and key.value == wire_field:
            return True
    return False


def _is_wire_receiver(
    node: ast.AST,
    *,
    receiver_names: frozenset[str],
    wire_field: str,
) -> bool:
    if isinstance(node, ast.Name) and node.id in receiver_names:
        return True
    return _contains_wire_field(node, wire_field)


def _is_key_name(node: ast.AST, key_name: str) -> bool:
    if isinstance(node, ast.Name):
        return node.id == key_name
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == key_name
        and not node.keywords
    )


def _wire_reads(
    expression: ast.expr,
    *,
    receiver_names: frozenset[str],
    wire_field: str,
) -> frozenset[tuple[str, int, int]]:
    reads: set[tuple[str, int, int]] = set()
    for node in ast.walk(expression):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and _is_wire_receiver(
                    node.func.value,
                    receiver_names=receiver_names,
                    wire_field=wire_field,
                )
            ):
                reads.add((node.args[0].value, node.lineno, node.col_offset))

        if not isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
            continue
        for generator in node.generators:
            if not (
                isinstance(generator.target, (ast.Tuple, ast.List))
                and generator.target.elts
                and isinstance(generator.target.elts[0], ast.Name)
                and isinstance(generator.iter, ast.Call)
                and isinstance(generator.iter.func, ast.Attribute)
                and generator.iter.func.attr == "items"
                and _is_wire_receiver(
                    generator.iter.func.value,
                    receiver_names=receiver_names,
                    wire_field=wire_field,
                )
            ):
                continue
            key_name = generator.target.elts[0].id
            for condition in generator.ifs:
                for call in ast.walk(condition):
                    if not (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "startswith"
                        and _is_key_name(call.func.value, key_name)
                        and call.args
                        and isinstance(call.args[0], ast.Constant)
                        and isinstance(call.args[0].value, str)
                    ):
                        continue
                    reads.add(
                        (f"{call.args[0].value}*", call.lineno, call.col_offset)
                    )
    return frozenset(reads)


def _quantity_expressions(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterable[ast.expr]:
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            yield node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            yield node.value
        elif isinstance(node, ast.Return) and node.value is not None:
            yield node.value
        elif isinstance(node, ast.Dict):
            yield from (value for value in node.values if value is not None)


def _exclusive_unproduced_reads(
    *,
    producer_source: str,
    producer_function: str,
    producer_container: str,
    consumers: tuple[tuple[str, str, frozenset[str]], ...],
    wire_field: str = "cmResolutions",
) -> tuple[ExclusiveDeletedKeyRead, ...]:
    producer_tree = ast.parse(producer_source)
    produced = _produced_keys(
        _function(producer_tree, producer_function), producer_container
    )
    assert produced, "producer vocabulary must be non-empty"

    findings: list[ExclusiveDeletedKeyRead] = []
    seen: set[
        tuple[str, str, tuple[tuple[str, int, int], ...], tuple[str, ...]]
    ] = set()
    for path, source, receiver_names in consumers:
        tree = ast.parse(source, filename=path)
        for function in (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            for expression in _quantity_expressions(function):
                read_sites = _wire_reads(
                    expression,
                    receiver_names=receiver_names,
                    wire_field=wire_field,
                )
                reads = frozenset(pattern for pattern, _, _ in read_sites)
                if not reads or reads & produced:
                    continue
                physical_sites = tuple(sorted(read_sites))
                key = (path, function.name, physical_sites, tuple(sorted(reads)))
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    ExclusiveDeletedKeyRead(
                        path=path,
                        qname=function.name,
                        line=min(line for _, line, _ in read_sites),
                        keys=tuple(sorted(reads)),
                    )
                )
    return tuple(sorted(findings, key=lambda row: (row.path, row.line, row.keys)))


def _normalized_predicate(node: ast.expr) -> str:
    return ast.dump(node, include_attributes=False)


def _collapsed_predicates(source: str, *, path: str) -> tuple[CollapsedPredicate, ...]:
    tree = ast.parse(source, filename=path)
    findings: list[CollapsedPredicate] = []

    def visit_statements(statements: list[ast.stmt], qname: str) -> None:
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nested = f"{qname}.{statement.name}" if qname else statement.name
                visit_statements(statement.body, nested)
                continue
            if not isinstance(statement, ast.If):
                for child in ast.iter_child_nodes(statement):
                    if isinstance(child, ast.stmt):
                        visit_statements([child], qname)
                continue

            arms: list[ast.If] = []
            current = statement
            while True:
                arms.append(current)
                visit_statements(current.body, qname)
                if len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
                    current = current.orelse[0]
                    continue
                visit_statements(current.orelse, qname)
                break

            first_by_predicate: dict[str, ast.If] = {}
            for arm in arms:
                predicate = _normalized_predicate(arm.test)
                first = first_by_predicate.setdefault(predicate, arm)
                if first is arm:
                    continue
                findings.append(
                    CollapsedPredicate(
                        path=path,
                        qname=qname or "<module>",
                        first_line=first.lineno,
                        unreachable_line=arm.lineno,
                        predicate=ast.unparse(arm.test),
                    )
                )

    visit_statements(tree.body, "")
    return tuple(findings)


def test_census_wire_rejects_exclusive_unproduced_reads_but_accepts_additive_reads() -> None:
    producer = """
def produce():
    buckets = {}
    buckets["constructed"] = 1
    buckets["unconstructed"] = 1
    return buckets
"""
    additive = """
def consume(cm):
    return cm.get("constructed", 0) + cm.get("derived-contract", 0)
"""
    exclusive = """
def consume(cm):
    return cm.get("derived-contract", 0)
"""
    assert _exclusive_unproduced_reads(
        producer_source=producer,
        producer_function="produce",
        producer_container="buckets",
        consumers=(("additive.py", additive, frozenset({"cm"})),),
    ) == ()
    lying = _exclusive_unproduced_reads(
        producer_source=producer,
        producer_function="produce",
        producer_container="buckets",
        consumers=(("exclusive.py", exclusive, frozenset({"cm"})),),
    )
    assert len(lying) == 1
    assert lying[0].keys == ("derived-contract",)

    compose_tree = ast.parse(COMPOSE.read_text(encoding="utf-8"))
    seal = _function(compose_tree, "seal_board_from_aggregate")
    constructed_reads = {
        pattern
        for pattern, _, _ in _wire_reads(
            _assignment_value(seal, "r_cm_constructed"),
            receiver_names=frozenset({"cm"}),
            wire_field="cmResolutions",
        )
    }
    unconstructed_reads = {
        pattern
        for pattern, _, _ in _wire_reads(
            _assignment_value(seal, "r_cm_unconstructed"),
            receiver_names=frozenset({"cm"}),
            wire_field="cmResolutions",
        )
    }
    assert constructed_reads == {"constructed", "derived-contract"}
    assert unconstructed_reads == {"unconstructed", "gap:*"}

    live = _exclusive_unproduced_reads(
        producer_source=RECENSUS.read_text(encoding="utf-8"),
        producer_function="_with_census_partition",
        producer_container="__returned_mapping__",
        consumers=(
            (
                str(RECENSUS.relative_to(ROOT)),
                RECENSUS.read_text(encoding="utf-8"),
                frozenset({"cm_resolutions"}),
            ),
            (
                str(COMPOSE.relative_to(ROOT)),
                COMPOSE.read_text(encoding="utf-8"),
                frozenset({"cm"}),
            ),
        ),
    )
    assert live == ()


def test_category_dispatch_rejects_collapsed_predicates_but_accepts_distinct_arms() -> None:
    distinct = """
def enroll(category):
    if category == "completed":
        return "complete"
    elif category == "panic":
        return "product"
    elif category == "instrument-blind":
        return "instrument"
"""
    collapsed = """
def enroll(category):
    if category == "completed":
        return "complete"
    elif category == "panic":
        return "product"
    elif category == "panic":
        return "instrument"
"""
    assert _collapsed_predicates(distinct, path="distinct.py") == ()
    lying = _collapsed_predicates(collapsed, path="collapsed.py")
    assert len(lying) == 1
    assert lying[0].predicate == "category == 'panic'"

    live = _collapsed_predicates(
        RECENSUS.read_text(encoding="utf-8"),
        path=str(RECENSUS.relative_to(ROOT)),
    )
    assert live == ()

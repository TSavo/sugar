"""Concrete TargetPattern law through ordinary source construction."""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from sugar_source_tree import nodes
from sugar_source_tree.binding_provenance import BindingCoordinateV1
from sugar_source_tree.tree import SourceFile


SOURCE = """\
def fixture(value, items):
    a, (b, *c) = value
    for a, (b, *c) in items:
        pass
    listed = [a for a, (b, *c) in items]
    unique = {a for a, (b, *c) in items}
    mapped = {a: b for a, (b, *c) in items}
    recursive = [b for a, *rest in items for b in rest]
    return listed, unique, mapped, recursive
"""

LIVE_SOURCE = """\
def live(items):
    for a, (b, *c) in items:
        pass
"""

TWO_LOOPS_SOURCE = """\
def two_loops(left_items, right_items):
    for a, *left_rest in left_items:
        pass
    for b, *right_rest in right_items:
        pass
"""


EXPECTED = {
    ("Assign", 2, 0): (("a", ("targets", 0, 0)), ("b", ("targets", 0, 1, 0)), ("c", ("targets", 0, 1, 1, "star"))),
    ("For", 3, 0): (("a", ("target", 0)), ("b", ("target", 1, 0)), ("c", ("target", 1, 1, "star"))),
    ("ListComp", 5, 0): (("a", ("generators", 0, "target", 0)), ("b", ("generators", 0, "target", 1, 0)), ("c", ("generators", 0, "target", 1, 1, "star"))),
    ("SetComp", 6, 0): (("a", ("generators", 0, "target", 0)), ("b", ("generators", 0, "target", 1, 0)), ("c", ("generators", 0, "target", 1, 1, "star"))),
    ("DictComp", 7, 0): (("a", ("generators", 0, "target", 0)), ("b", ("generators", 0, "target", 1, 0)), ("c", ("generators", 0, "target", 1, 1, "star"))),
    ("ListComp", 8, 0): (("a", ("generators", 0, "target", 0)), ("rest", ("generators", 0, "target", 1, "star"))),
    ("ListComp", 8, 1): (("b", ("generators", 1, "target")),),
}


def _source_file(tmp_path: Path, name: str = "target_patterns.py") -> SourceFile:
    path = tmp_path / name
    path.write_text(SOURCE)
    return SourceFile.from_path(path)


def _products(source_file: SourceFile):
    function, = tuple(source_file.functions())
    products = []
    for consumer in function.walk():
        key = (consumer.kind, consumer.line_col_span().start_line)
        if any(expected[:2] == key for expected in EXPECTED):
            products.extend(consumer.target_patterns)
    return tuple(products)


def test_ordinary_nested_star_consumers_construct_exact_patterns_once(tmp_path: Path):
    source_file = _source_file(tmp_path)
    products = _products(source_file)
    assert len(products) == len(EXPECTED), (
        "R_missing_target_pattern_product="
        f"{len(EXPECTED) - len(products)}; ordinary target consumers must own "
        "their eager exact TargetPattern product"
    )

    observed = {}
    occurrence_indexes = {}
    for product in products:
        base_key = (
            product.consumer_occurrence.kind,
            product.consumer_occurrence.line_col_span().start_line,
        )
        occurrence_index = occurrence_indexes.get(base_key, 0)
        occurrence_indexes[base_key] = occurrence_index + 1
        consumer_key = (
            *base_key,
            occurrence_index,
        )
        observed[consumer_key] = tuple(
            (leaf.id, coordinate.projection_path)
            for leaf, coordinate in zip(
                product.leaves, product.coordinates, strict=True
            )
        )
        assert product.source_unit is source_file.unit
        assert product.target_occurrence.unit is source_file.unit
        assert all(leaf.unit is source_file.unit for leaf in product.leaves)
        assert all(
            BindingCoordinateV1.decode(coordinate.wire()) == coordinate
            for coordinate in product.coordinates
        )
    assert observed == EXPECTED

    repeated = _products(source_file)
    assert repeated is not products
    assert len(repeated) == len(products)
    assert all(left is right for left, right in zip(products, repeated, strict=True))

    assert source_file.unit.target_pattern_construction_count == len(products)

    live_path = tmp_path / "live.py"
    live_path.write_text(LIVE_SOURCE)
    live_file = SourceFile.from_path(live_path)
    live_function, = tuple(live_file.functions())
    live_loop = next(node for node in live_function.walk() if node.kind == "For")
    live_pattern, = live_loop.target_patterns
    live_function.sugar()
    live_function.sugar()
    repeated_live_loop = next(
        node for node in live_function.walk() if node.kind == "For"
    )
    repeated_live_pattern, = repeated_live_loop.target_patterns
    assert repeated_live_pattern is live_pattern
    assert live_file.unit.target_pattern_construction_count == 1


def test_target_pattern_rejects_wrong_occurrence_and_order(tmp_path: Path):
    first = _source_file(tmp_path, "first.py")
    second = _source_file(tmp_path, "second.py")
    truthful = _products(first)
    foreign = _products(second)
    assert truthful and len(truthful) == len(foreign)

    with pytest.raises(nodes.TargetPatternConstructionGapV1) as wrong_occurrence:
        first.unit.require_target_pattern(
            truthful[0].consumer_occurrence,
            foreign[0].target_occurrence,
        )
    assert wrong_occurrence.value.reason == "foreign-target-occurrence"
    assert wrong_occurrence.value.consumer_occurrence is truthful[0].consumer_occurrence
    assert wrong_occurrence.value.target_occurrence is foreign[0].target_occurrence

    first_for = next(
        pattern
        for pattern in truthful
        if pattern.consumer_occurrence.kind == "For"
    )
    second_for = next(
        pattern
        for pattern in foreign
        if pattern.consumer_occurrence.kind == "For"
    )
    before_count = first.unit.target_pattern_construction_count
    with pytest.raises(nodes.TargetPatternConstructionGapV1) as foreign_consumer:
        first.unit.require_target_pattern(
            second_for.consumer_occurrence,
            first_for.target_occurrence,
        )
    assert foreign_consumer.value.reason == "foreign-target-occurrence"
    assert foreign_consumer.value.consumer_occurrence is second_for.consumer_occurrence
    assert foreign_consumer.value.target_occurrence is first_for.target_occurrence
    assert first.unit.target_pattern_construction_count == before_count

    with pytest.raises(nodes.TargetPatternConstructionGapV1) as wrong_order:
        first.unit.require_target_pattern_coordinates(
            truthful[0], tuple(reversed(truthful[0].coordinates))
        )
    assert wrong_order.value.reason == "target-coordinate-order-mismatch"
    assert wrong_order.value.target_pattern is truthful[0]


def test_same_unit_foreign_for_cannot_claim_local_target(tmp_path: Path):
    path = tmp_path / "two_loops.py"
    path.write_text(TWO_LOOPS_SOURCE)
    source_file = SourceFile.from_path(path)
    function, = tuple(source_file.functions())
    loops = tuple(node for node in function.walk() if node.kind == "For")
    assert len(loops) == 2
    first_pattern, = loops[0].target_patterns
    second_pattern, = loops[1].target_patterns
    before = source_file.unit.target_pattern_construction_count

    with pytest.raises(nodes.TargetPatternConstructionGapV1) as rejected:
        source_file.unit.require_target_pattern(
            second_pattern.consumer_occurrence,
            first_pattern.target_occurrence,
        )
    assert rejected.value.reason == "foreign-target-occurrence"
    assert rejected.value.consumer_occurrence is second_pattern.consumer_occurrence
    assert rejected.value.target_occurrence is first_pattern.target_occurrence
    assert source_file.unit.target_pattern_construction_count == before
    assert loops[0].target_patterns[0] is first_pattern
    assert loops[1].target_patterns[0] is second_pattern


def test_legacy_reharvest_manifestations_are_retired():
    source = Path(nodes.__file__).read_text()
    offenders = tuple(
        match.group(0)
        for pattern in (
            r"For\._target_bindings_for\(",
            r"self\._target_bindings\(",
            r"self\._bound_names_in\(self\.target\)",
            r"target_names\s*=\s*self\._bound_names_in\(self\.target\)",
        )
        for match in re.finditer(pattern, source)
    )
    assert offenders == (), (
        f"R_target_reharvest_manifestations={len(offenders)}; "
        + "; ".join(offenders)
    )

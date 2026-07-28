"""LAW_OF_ONE for authenticated loop projected binding products."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_state import BindingStateWireGap
from sugar_source_tree.loop_recurrence import LoopProjectedBindingProductSugar
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    return next(SourceFile(path_source(path)).functions())


def _product(*, function_name: str = "arbitrary", carried_name: str = "carried"):
    constructed = _function(
        f"""
def {function_name}(items):
    {carried_name} = 0
    for first in items:
        {carried_name} = first
    for second in items:
        {carried_name} = second
    return {carried_name}
"""
    ).sugar()
    product = constructed.statements[2].construction.loop_runtime.initial_value_sugars[0]
    assert isinstance(product, LoopProjectedBindingProductSugar)
    return product


def test_real_source_loop_reuses_the_exact_producer_owned_product() -> None:
    product = _product()

    assert product.projection.target_cid == product.target_cid
    assert product.name == "carried"
    assert product.to_term(owner="test").name == "python:guarded-binding-read"


@pytest.mark.parametrize(
    ("change", "message"),
    (
        (lambda product, foreign: {"projection": foreign.projection}, "foreign loop occurrence"),
        (lambda product, foreign: {"name": "same_spelling"}, "foreign binding name"),
        (lambda product, foreign: {"binding_coordinate": foreign.binding_coordinate}, "foreign binding name"),
        (lambda product, foreign: {"site": foreign.site}, "foreign read occurrence"),
        (lambda product, foreign: {"occurrence_cid": foreign.occurrence_cid}, "foreign read occurrence"),
        (lambda product, foreign: {"target_cid": foreign.target_cid}, "foreign loop occurrence"),
        (lambda product, foreign: {"_mint_authority": foreign.target_cid}, "authenticated projection mint"),
    ),
)
def test_product_substitution_twins_refuse(change, message: str) -> None:
    product = _product()
    foreign = _product(function_name="foreign", carried_name="carried")

    with pytest.raises(BindingStateWireGap, match=message):
        replace(product, **change(product, foreign))


def test_side_door_zero_is_structural() -> None:
    source = Path(__file__).parents[1] / "src/sugar_source_tree/live_loop_construction.py"
    text = source.read_text()

    assert "construct_live_binding_product_sugar" not in text
    assert "expected_coordinate" not in text
    assert "BindingCoordinateV1.decode(entry.coordinate.wire())" not in text
    assert "_construct_binding_projection" not in text
    assert "GuardedBindingReadSugar" not in text
    assert "carried_names, pre_entries, pre_runtime" not in text

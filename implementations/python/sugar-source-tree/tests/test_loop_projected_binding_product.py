"""Canonical constructed product for authenticated loop post-bindings."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.ir import atomic, not_, str_const
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_source_tree.binding_state import (
    BindingEntryV1,
    BindingStateWireGap,
    LoopProjectedBinding,
    LoopProjectedCompletedFace,
    RuntimeBindingEntryFactoryV1,
)
from sugar_source_tree import live_loop_construction as live_loop
from sugar_source_tree.tree import SourceFile


def _assignment(source: str):
    function = next(SourceFile((source, "tests/loop_product.py", cid_of_json(source))).functions())
    assignment = next(node for node in function.walk() if node.kind == "Assign")
    return function, assignment


def _projected_entry():
    function, first = _assignment("def f():\n    value = 1\n")
    _other_function, second = _assignment("def g():\n    value = 2\n")
    factory = RuntimeBindingEntryFactoryV1(
        cid_of_json({"scope": function.fragment.seal().to_dict()})
    )
    entry = factory.mint_entry(
        binding_site=first.targets[0].fragment,
        projection_path=("targets", 0),
        state=first.value,
    )
    target_cid = cid_of_json({"loop": function.fragment.seal().cid})
    guard = atomic("loop.product.guard", (str_const(target_cid),))
    projected = LoopProjectedBinding(
        target_cid,
        (
            LoopProjectedCompletedFace(
                target_cid,
                "BreakExit",
                live_loop._formula_cid(guard),
                first.value,
                guard,
                2,
            ),
            LoopProjectedCompletedFace(
                target_cid,
                "NormalExhaustion",
                live_loop._formula_cid(not_(guard)),
                second.value,
                not_(guard),
                2,
            ),
        ),
    )
    return first, replace(
        entry,
        state=projected,
        sealed_state=live_loop._seal_runtime_state(projected),
    )


def _construct_product(**kwargs):
    producer = getattr(live_loop, "construct_live_binding_product_sugar", None)
    assert producer is not None, (
        "live loop binding products require one authenticated ConstructedTermSugar "
        "projection owner"
    )
    return producer(**kwargs)


def test_authenticated_loop_projection_constructs_one_term_product() -> None:
    assignment, entry = _projected_entry()

    product = _construct_product(
        name="value",
        entry=entry,
        expected_coordinate=entry.coordinate,
        site=assignment.fragment,
    )

    assert isinstance(product, ConstructedTermSugar)
    assert product.to_term(owner="test").name == "python:guarded-binding-read"


def test_foreign_binding_coordinate_cannot_select_the_product() -> None:
    assignment, entry = _projected_entry()
    _foreign_function, foreign = _assignment("def h():\n    other = 3\n")
    foreign_coordinate = RuntimeBindingEntryFactoryV1(
        cid_of_json({"scope": foreign.fragment.seal().to_dict()})
    ).mint_entry(
        binding_site=foreign.targets[0].fragment,
        projection_path=("targets", 0),
        state=foreign.value,
    ).coordinate

    with pytest.raises(BindingStateWireGap, match="foreign binding coordinate"):
        _construct_product(
            name="value",
            entry=entry,
            expected_coordinate=foreign_coordinate,
            site=assignment.fragment,
        )


def test_live_state_cannot_disagree_with_its_authenticated_sealed_product() -> None:
    assignment, entry = _projected_entry()
    _foreign_function, foreign = _assignment("def h():\n    value = 9\n")
    face = entry.state.completed_faces[0]
    lying_state = replace(
        entry.state,
        completed_faces=(replace(face, state=foreign.value), *entry.state.completed_faces[1:]),
    )

    with pytest.raises(BindingStateWireGap, match="sealed binding product"):
        _construct_product(
            name="value",
            entry=replace(entry, state=lying_state),
            expected_coordinate=entry.coordinate,
            site=assignment.fragment,
        )

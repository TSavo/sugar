from __future__ import annotations

import ast

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.sugar.ann_assign_sugar import AnnAssignSugar
from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar
from sugar_lift_py_tests.sugar.chained_assign_sugar import ChainedAssignSugar


def _site(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "t.py")


def test_chained_names_bind_every_target_to_same_value() -> None:
    assert compose_block("    a = b = 5\n    return a + b\n") == BlockValue(
        (ReturnValue(TermValue(10)),)
    )


def test_chained_value_discriminates_every_binding() -> None:
    five = compose_block("    a = b = 5\n    return a + b\n")
    six = compose_block("    a = b = 6\n    return a + b\n")
    assert five != six
    assert six == BlockValue((ReturnValue(TermValue(12)),))


def test_chained_owner_is_disjoint_from_plain_and_annotated_assign() -> None:
    chained = _site("a = b = 5")
    plain = _site("a = 5")
    annotated = _site("a: int = 5")

    assert ChainedAssignSugar.owns(chained)
    assert not AssignSugar.owns(chained)
    assert not AnnAssignSugar.owns(chained)
    assert not ChainedAssignSugar.owns(plain)
    assert AssignSugar.owns(plain)
    assert not ChainedAssignSugar.owns(annotated)
    assert AnnAssignSugar.owns(annotated)


def _build_statement(source: str):
    node = ast.parse(source).body[0]
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    return build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)


@pytest.mark.parametrize(
    "source",
    ["a, *b = values", "(a, b), c = triple", "a = b, c = pair"],
)
def test_unowned_assign_target_shapes_stay_loud(source: str) -> None:
    # Cross-slice gate: when a sibling slice starts OWNING one of these
    # shapes, this test must fail by NAMING the new owner, so the fixture
    # moves to a positive test instead of silently rotting red.
    try:
        built = _build_statement(source)
    except FactoryPanic:
        return
    pytest.fail(
        f"{source!r} is now owned by {type(built.sugar).__name__}; "
        "move this fixture to that owner's positive tests and pick a "
        "still-unowned shape for the loud-gap arm"
    )


@pytest.mark.parametrize(
    ("source", "owner_name"),
    [
        ("a, b = pair", "TupleUnpackAssignSugar"),
        ("box[0] = 5", "SubscriptAssignSugar"),
        ("obj.attr = 5", "AttributeAssignSugar"),
    ],
)
def test_sibling_slices_own_their_assign_shapes(source: str, owner_name: str) -> None:
    built = _build_statement(source)
    assert type(built.sugar).__name__ == owner_name

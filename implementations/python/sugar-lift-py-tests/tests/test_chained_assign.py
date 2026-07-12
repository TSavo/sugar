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


@pytest.mark.parametrize("source", ["a, b = pair", "a, *b = values", "box[0] = 5"])
def test_other_assign_target_shapes_stay_loud(source: str) -> None:
    node = ast.parse(source).body[0]
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    with pytest.raises(FactoryPanic):
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)

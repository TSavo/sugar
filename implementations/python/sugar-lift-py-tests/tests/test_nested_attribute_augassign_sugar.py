from __future__ import annotations

import ast

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import ReturnValue, TermValue


def _site(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "vendor.py")


def _build(source: str):
    node = ast.parse(source).body[0]
    ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
    return build_node(
        node,
        filename="vendor.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )


def test_nested_name_rooted_attribute_augassign_has_one_structural_owner() -> None:
    candidates = default_catalog().candidates_for(
        SugarRole.STATEMENT,
        _site("state.adaptive.stepsize /= factor"),
    )

    assert [candidate.name for candidate in candidates] == [
        "NestedAttributeAugAssignSugar"
    ]


def test_nested_attribute_augassign_rebinds_the_exact_dotted_coordinate() -> None:
    block = compose_block(
        "    state.adaptive.stepsize /= 2\n" "    return state.adaptive.stepsize\n",
        binds={"state.adaptive.stepsize": TermValue(8)},
    )

    returned = next(
        statement
        for statement in block.statements
        if isinstance(statement, ReturnValue)
    )
    assert returned.value == TermValue(4.0)


@pytest.mark.parametrize(
    "source",
    (
        "factory().adaptive.stepsize /= factor",
        "states[0].adaptive.stepsize /= factor",
    ),
)
def test_runtime_selected_nested_divassign_stays_loud(source: str) -> None:
    with pytest.raises(FactoryPanic, match="observed=AugAssign requested=statement"):
        _build(source)


def test_existing_single_attribute_partition_is_unchanged() -> None:
    assert type(_build("state.stepsize /= factor").sugar).__name__ == (
        "AttributeAugAssignSugar"
    )

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


def _site(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "t.py")


def _build(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    return build_node(
        node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx
    ).sugar


@pytest.mark.parametrize(
    ("operator", "expected"),
    (("|=", 7), ("&=", 1), ("^=", 6), ("<<=", 40), (">>=", 0)),
)
def test_residual_name_augassign_uses_existing_binop_floor(
    operator: str, expected: int
) -> None:
    record = compose_block(f"    x = 5\n    x {operator} 3\n    return x\n")
    assert record == BlockValue((ReturnValue(TermValue(expected)),))


def test_subscript_augassign_non_add_reads_operates_and_stores() -> None:
    record = compose_block("    xs = [3]\n    xs[0] *= 4\n    return xs[0]\n")
    assert record == BlockValue((ReturnValue(TermValue(12)),))


def test_attribute_annassign_with_value_uses_attribute_owner() -> None:
    sugar = _build("self.value: int = 3")
    assert type(sugar).__name__ == "AttributeAnnAssignSugar"
    assert len(sugar.walk_children()) == 3


def test_bitor_attribute_annotation_stays_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _build("self.value: int | None = None")
    assert raised.value.info.observed == "AnnAssign"


def test_bitor_subscript_augassign_stays_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _build("xs[0] |= 1")
    assert raised.value.info.observed == "AugAssign"


def test_nested_tuple_unpack_recursively_projects_names() -> None:
    record = compose_block(
        "    (a, b), (c, d) = ((1, 2), (3, 4))\n    return a + d\n"
    )
    assert record == BlockValue((ReturnValue(TermValue(5)),))


def test_global_declaration_returns_to_the_loud_factory_none_arm() -> None:
    with pytest.raises(FactoryPanic) as raised:
        _build("global shared")
    assert raised.value.info.observed == "Global"


def test_assignment_residue_owners_are_structurally_disjoint() -> None:
    catalog = default_catalog()
    cases = {
        "x |= 1": "BitOrNameAugAssignSugar",
        "xs[0] *= 2": "ResidualSubscriptAugAssignSugar",
        "self.x: int = 1": "AttributeAnnAssignSugar",
        "(a, b), (c, d) = value": "TupleUnpackAssignSugar",
    }
    for source, expected in cases.items():
        names = [
            candidate.name
            for candidate in catalog.candidates_for(
                SugarRole.STATEMENT, _site(source)
            )
        ]
        assert names == [expected]

    assert not list(
        catalog.candidates_for(SugarRole.STATEMENT, _site("global x"))
    )

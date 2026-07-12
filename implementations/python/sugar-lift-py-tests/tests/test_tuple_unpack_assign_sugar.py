from __future__ import annotations

import ast

import pytest
from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.sugar.tuple_unpack_assign_sugar import (
    TupleUnpackAssignSugar,
)


def _site(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "t.py", source=source)


def test_flat_tuple_unpack_binds_every_name_to_its_rhs_element() -> None:
    assert compose_block(
        "    dayfrac, days = (0.5, 3)\n    return dayfrac + days\n"
    ) == BlockValue((ReturnValue(TermValue(3.5)),))


@pytest.mark.parametrize(
    "source",
    (
        "dayfrac, (whole, days) = (0.5, (1, 2))",
        "dayfrac, days = (0.5,)",
    ),
)
def test_unowned_tuple_unpack_shape_reaches_the_loud_none_arm(source: str) -> None:
    node = ast.parse(source).body[0]
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())

    with pytest.raises(FactoryPanic, match=r"None => panic"):
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)


def test_tuple_unpack_owns_only_one_flat_all_name_target_with_matching_literal_arity() -> (
    None
):
    assert TupleUnpackAssignSugar.owns(_site("dayfrac, days = _math.modf(days)"))
    assert not TupleUnpackAssignSugar.owns(_site("dayfrac, *days = values"))
    assert not TupleUnpackAssignSugar.owns(_site("dayfrac, (whole, days) = values"))
    assert not TupleUnpackAssignSugar.owns(_site("obj.dayfrac, days = values"))
    assert not TupleUnpackAssignSugar.owns(_site("parts[0], days = values"))
    assert not TupleUnpackAssignSugar.owns(_site("dayfrac, days = (0.5,)"))

    node = ast.parse("dayfrac, days = _math.modf(days)").body[0]
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    result = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)

    assert isinstance(result.sugar, TupleUnpackAssignSugar)
    assert result.sugar.names == ("dayfrac", "days")
    assert tuple(
        getattr(projection.sugar, "index") for projection in result.sugar.projections
    ) == (
        0,
        1,
    )

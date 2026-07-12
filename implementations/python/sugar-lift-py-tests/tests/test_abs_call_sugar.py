"""The vendor ``abs(value)`` folds numbers and preserves symbolic coordinates."""

from __future__ import annotations

import ast

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue, TermValue
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.outcome import complete_value


def _selected(expr: str) -> str | None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(expr, mode="eval").body
    result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)
    return result.audit_row.selected


def test_ground_abs_folds_both_signs_and_float() -> None:
    assert reduce_value("abs(-5)") == TermValue(5)
    assert reduce_value("abs(3)") == TermValue(3)
    assert reduce_value("abs(-1.5)") == TermValue(1.5)


def test_symbolic_abs_carries_its_argument_coordinate() -> None:
    x = reduce_value("abs(x)", binds={"x": SymbolicValue(make_var("x"))})
    y = reduce_value("abs(y)", binds={"y": SymbolicValue(make_var("y"))})

    assert isinstance(x, CallSiteValue)
    assert isinstance(y, CallSiteValue)
    assert x.term == ctor("call:abs", [make_var("x")])
    assert y.term == ctor("call:abs", [make_var("y")])
    assert x.term != y.term


def test_ownership_partition_is_exact() -> None:
    assert _selected("abs(x)") == "AbsCallSugar"
    assert _selected("f(x)") == "CallSugar"


def test_symbolic_abs_composes_inside_full_assert_comparison() -> None:
    source = "def A(z):\n    assert abs(z) <= 1.0\n    return z\n"
    payload = lift_file_payload(source, "t.py")
    assertion = next(contract for contract in payload.ir if contract.inv is not None)

    assert "call:abs" in repr(assertion.inv)
    assert "py.lt" in repr(assertion.inv)


def test_ground_abs_comparison_folds_true_in_full_assert() -> None:
    source = "def A():\n    assert abs(-3) <= 5\n    return 1\n"
    payload = lift_file_payload(source, "t.py")

    assert any(
        row.line == 2 and row.selected == "AssertSugar" and row.status == "warranted"
        for row in payload.factory_walk
    )
    assert all(contract.inv is None for contract in payload.ir)


def test_datetime_abs_comparisons_are_lifted_and_cited_at_real_loci() -> None:
    source = (
        "\n" * 624
        + "def _datetime_abs_floor(daysecondsfrac, s):\n"
        + "    assert abs(daysecondsfrac) <= 1.0\n"
        + "\n" * 43
        + "    assert abs(s) <= 3 * 24 * 3600\n"
        + "    return s\n"
    )
    filename = "Lib/datetime.py"
    payload = lift_file_payload(source, filename).to_rpc()
    assertions = account_lift_coverage(
        census_source(source, file=filename), payload
    ).to_json()["assertions"]

    assert assertions["lifted_cited"] == 2
    assert assertions["refused_loud"] == 0
    assert [locus["line"] for locus in assertions["lifted_loci"]] == [626, 670]


@pytest.mark.parametrize(
    "source", ('abs("not numeric")', "abs(1, 2)", "abs(*xs)", "abs(x=x)")
)
def test_unowned_abs_shapes_stay_refused_loud(source: str) -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source, mode="eval").body

    with pytest.raises(FactoryPanic, match=r"None => panic"):
        result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)
        complete_value(result.sugar.desugar(ctx), owner="test")


def test_abs_ownership_is_single_numeric_shape_and_disjoint_from_isinstance() -> None:
    def site(source: str) -> SourceFragment:
        return SourceFragment.from_node(
            ast.parse(source, mode="eval").body, "t.py", source=source
        )

    from sugar_lift_py_tests.sugar.abs_call_sugar import AbsCallSugar

    assert AbsCallSugar.owns(site("abs(value)"))
    assert AbsCallSugar.owns(site("abs(value - 1.0)"))
    assert AbsCallSugar.owns(site("abs(-3)"))
    assert not AbsCallSugar.owns(site('abs("not numeric")'))
    assert not AbsCallSugar.owns(site("abs([1, 2])"))
    assert not AbsCallSugar.owns(site("abs(1, 2)"))
    assert not AbsCallSugar.owns(site("abs(*values)"))
    assert not AbsCallSugar.owns(site("abs(value=value)"))
    assert not AbsCallSugar.owns(site("isinstance(value, int)"))

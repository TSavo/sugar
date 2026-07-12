from __future__ import annotations

from pathlib import Path

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    GuardedScopeRebind,
    ScopeRebind,
    StringValue,
    SymbolicValue,
)
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.temporal import TemporalContext

BOTH_ARMS = (
    "def f(p, expected):\n"
    "    if p:\n"
    "        s = 'left'\n"
    "    else:\n"
    "        s = 'right'\n"
    "    assert s == expected\n"
    "    return 1\n"
)


def test_both_arm_binding_reads_back_as_guarded_value() -> None:
    payload, gaps = audit_lift_file(BOTH_ARMS, "both.py")

    assert not gaps
    contract = next(row for row in payload.ir if row.name == "f" and row.inv)
    assert contract.inv["kind"] == "and"
    assert len(contract.inv["operands"]) == 2


def test_one_arm_binding_read_stays_loud() -> None:
    source = "def f(p):\n    if p:\n        s = 'only'\n    return s\n"

    with pytest.raises(FactoryPanic, match="observed=s requested=value"):
        audit_lift_file(source, "one.py", hold_panic=False)


def test_nested_join_in_one_outer_arm_does_not_fabricate_definite_binding() -> None:
    source = (
        "def f(outer, inner):\n"
        "    if outer:\n"
        "        if inner:\n"
        "            s = 'left'\n"
        "        else:\n"
        "            s = 'right'\n"
        "    return s\n"
    )

    with pytest.raises(FactoryPanic, match="observed=s requested=value"):
        audit_lift_file(source, "nested_one_arm.py", hold_panic=False)


def test_nested_join_in_both_outer_arms_remains_definitely_bound() -> None:
    source = (
        "def f(outer, inner, expected):\n"
        "    if outer:\n"
        "        if inner:\n"
        "            s = 'left'\n"
        "        else:\n"
        "            s = 'middle'\n"
        "    else:\n"
        "        s = 'right'\n"
        "    assert s == expected\n"
        "    return s\n"
    )

    payload, gaps = audit_lift_file(source, "nested_both_arms.py")

    assert not gaps
    assertion = next(row for row in payload.ir if row.inv is not None)
    assert assertion.inv["kind"] == "and"


def test_guarded_scope_rebind_stacks_guards_without_extending_scope() -> None:
    outer = atomic("outer", [])
    inner = atomic("inner", [])
    marker = ScopeRebind("s", StringValue("value")).guarded(inner).guarded(outer)
    ctx = FactoryBuildContext(
        filename="guarded_rebind.py",
        catalog=default_catalog(),
        temporal=TemporalContext.empty(),
    )

    assert isinstance(marker, GuardedScopeRebind)
    assert marker.guards == (outer, inner)
    assert marker.name == "s"
    assert marker.value == StringValue("value")
    assert marker.contribution() == ()
    assert marker.extend_scope(ctx) is ctx


def test_joined_binding_is_structurally_guarded_not_an_ite_euf() -> None:
    block = compose_block(
        "    if p:\n        s = 'left'\n    else:\n        s = 'right'\n",
        {"p": SymbolicValue(make_var("p"))},
    )
    ctx = block.extend_scope(
        FactoryBuildContext(
            filename="structural.py",
            catalog=default_catalog(),
            temporal=TemporalContext.empty(),
        )
    )

    value = ctx.temporal.value_for("s")
    assert type(value).__name__ == "GuardedValue"
    assert value.when_true.value == "left"
    assert value.when_false.value == "right"
    assert "ite" not in repr(value)


def test_real_datetime_repr_assertions_measure_after_join(
    cpython_311_datetime_path,
) -> None:
    path = cpython_311_datetime_path
    source = path.read_text(encoding="utf-8")
    payload, gaps = audit_lift_file(source, str(path))
    axis = account_lift_coverage(
        census_source(source, file=str(path)), payload.to_rpc()
    ).to_json()["assertions"]

    assert axis["silently_unaccounted"] == 0
    assert {
        locus["line"] for locus in axis["refused_loci"] if locus["line"] in {1507, 1510}
    } == {1507, 1510}
    repr_gap = next(gap for gap in gaps if gap.label.endswith(":1495:4"))
    assert (
        "observed=GuardedValue requested=project this floor value to a term"
        in repr_gap.message
    )

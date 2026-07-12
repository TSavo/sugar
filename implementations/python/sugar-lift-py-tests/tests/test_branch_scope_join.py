from __future__ import annotations

from pathlib import Path

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.ir import make_var
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


def test_real_datetime_repr_assertions_measure_after_join(cpython_311_datetime_path) -> None:
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
    assert any(
        "observed=StringValue requested=stand on the modulo floor" in gap.message
        and ":1500:" in gap.message
        for gap in gaps
    )

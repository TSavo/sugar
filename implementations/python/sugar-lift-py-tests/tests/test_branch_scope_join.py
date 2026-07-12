from __future__ import annotations

from pathlib import Path

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    GuardedScopeRebind,
    ImportAliasValue,
    ScopeRebind,
    StringValue,
    SymbolicValue,
)
from sugar_lift_py_tests.outcome import Incomplete
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


def test_real_replace_ifexp_effect_skips_only_its_name_join() -> None:
    block = compose_block(
        "    if p:\n"
        "        op = lambda x: operator.eq(x, b)\n"
        "        sibling = 'left'\n"
        "    else:\n"
        "        op = vectorize(\n"
        "            lambda x: (\n"
        "                bool(re.search(b, x))\n"
        "                if isinstance(x, str) and isinstance(b, (str, Pattern))\n"
        "                else False\n"
        "            )\n"
        "        )\n"
        "        sibling = 'right'\n",
        {
            "b": SymbolicValue(make_var("b")),
            "p": SymbolicValue(make_var("p")),
            "Pattern": ImportAliasValue("Pattern", "typing.Pattern"),
        },
    )

    joins = [entry for entry in block.statements if isinstance(entry, ScopeRebind)]
    assert [entry.name for entry in joins] == ["sibling"]
    effects = [entry for entry in block.statements if isinstance(entry, Incomplete)]
    assert len(effects) == 1
    assert type(effects[0].effect).__name__ == "ConditionalExpressionRuntimeEffect"
    assert "effect occurs under branch condition" in effects[0].reason


def test_effect_valued_join_name_stays_unbound_while_sibling_joins() -> None:
    block = compose_block(
        "    if p:\n"
        "        broken = 1 if p else 2\n"
        "        sibling = 'left'\n"
        "    else:\n"
        "        broken = 3\n"
        "        sibling = 'right'\n",
        {"p": SymbolicValue(make_var("p"))},
    )
    ctx = block.extend_scope(
        FactoryBuildContext(
            filename="effect_join.py",
            catalog=default_catalog(),
            temporal=TemporalContext.empty(),
        )
    )

    assert type(ctx.temporal.value_for("sibling")).__name__ == "GuardedValue"
    with pytest.raises(FactoryPanic, match="observed=broken requested=value"):
        ctx.temporal.value_for("broken")


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
        locus["line"] for locus in axis["lifted_loci"] if locus["line"] in {1507, 1510}
    } == {1507, 1510}
    assert not any(gap.label.endswith(":1495:4") for gap in gaps)


def test_nested_branch_join_reduces_each_assignment_once(monkeypatch) -> None:
    from sugar_lift_py_tests.sugar_body import SugarBody

    depth = 8
    lines = []
    for level in range(depth):
        lines.append("    " * (level + 1) + f"if p{level}:")
    deepest_line = len(lines) + 2
    lines.append("    " * (depth + 1) + "value = 'deep'")
    for level in reversed(range(depth)):
        lines.append("    " * (level + 1) + "else:")
        lines.append("    " * (level + 2) + f"value = 'fallback-{level}'")

    visits = 0
    original_reduce = SugarBody.reduce

    def counted_reduce(self, ctx):
        nonlocal visits
        site = getattr(self.sugar, "site", None)
        if (
            type(self.sugar).__name__ == "AssignSugar"
            and getattr(site, "line", None) == deepest_line
        ):
            visits += 1
        return original_reduce(self, ctx)

    monkeypatch.setattr(SugarBody, "reduce", counted_reduce)
    compose_block(
        "\n".join(lines) + "\n",
        {f"p{level}": SymbolicValue(make_var(f"p{level}")) for level in range(depth)},
    )

    assert visits == 1

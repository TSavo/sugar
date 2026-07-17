from __future__ import annotations

from pathlib import Path

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    GuardedReturn,
    GuardedScopeRebind,
    GuardedValue,
    ImportAliasValue,
    ScopeRebind,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.sugar.if_sugar import IfSugar
from sugar_lift_py_tests.sugar.test_function_def_sugar import (
    TestFunctionDefSugar as FunctionTestimonySugar,
)
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

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


def test_repeated_identical_guard_activates_prior_one_arm_binding() -> None:
    source = (
        "def f(p):\n"
        "    if p:\n"
        "        s = 'only'\n"
        "    if p:\n"
        "        assert s == 'only'\n"
    )

    payload, gaps = audit_lift_file(source, "same_guard.py")

    assert gaps == []
    assert any(row.inv is not None for row in payload.ir)


def test_different_guard_does_not_activate_prior_one_arm_binding() -> None:
    source = (
        "def f(p, q):\n"
        "    if p:\n"
        "        s = 'only'\n"
        "    if q:\n"
        "        assert s == 'only'\n"
    )

    with pytest.raises(FactoryPanic, match="observed=s requested=value"):
        audit_lift_file(source, "different_guard.py", hold_panic=False)


def test_repeated_guard_binding_stays_unbound_after_guarded_region() -> None:
    source = (
        "def f(p):\n"
        "    if p:\n"
        "        s = 'only'\n"
        "    if p:\n"
        "        assert s == 'only'\n"
        "    return s\n"
    )

    with pytest.raises(FactoryPanic, match="observed=s requested=value"):
        audit_lift_file(source, "after_guard.py", hold_panic=False)


def test_repeated_guard_binding_witness_truthful_sat_wrong_twin_unsat(
    tmp_path: Path,
) -> None:
    witnesses = IfSugar.witnesses()
    pairs = witnesses if isinstance(witnesses, tuple) else (witnesses,)
    pair = next(
        witness
        for witness in pairs
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "if_repeated_guard_binding"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "same-guard-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "same-guard-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


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


def test_nested_continuing_paths_join_around_raising_middle_arm() -> None:
    block = compose_block(
        "    if first:\n"
        "        result = 1\n"
        "    elif middle:\n"
        "        raise ValueError('middle')\n"
        "    else:\n"
        "        result = 2\n"
        "    return result\n",
        {
            "first": SymbolicValue(make_var("first")),
            "middle": SymbolicValue(make_var("middle")),
        },
    )

    returned = next(
        statement
        for statement in block.statements
        if isinstance(statement, GuardedReturn)
    )
    assert isinstance(returned.value, GuardedValue)
    assert returned.value.when_true == TermValue(1)
    assert returned.value.when_false == TermValue(2)


def test_nested_continuing_path_missing_binding_stays_loud() -> None:
    source = (
        "    if first:\n"
        "        result = 1\n"
        "    elif middle:\n"
        "        raise ValueError('middle')\n"
        "    else:\n"
        "        pass\n"
        "    return result\n"
    )

    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            source,
            {
                "first": SymbolicValue(make_var("first")),
                "middle": SymbolicValue(make_var("middle")),
            },
        )

    assert raised.value.info.owner == "TemporalContext"
    assert raised.value.info.observed == "result"
    assert raised.value.info.requested == "value"


def test_literal_parametrize_rows_make_elif_binding_definite() -> None:
    source = (
        "import pytest\n"
        "def identity(value):\n"
        "    return value\n"
        "\n"
        "@pytest.mark.parametrize(\n"
        "    ('kind', 'expected'),\n"
        "    [('first', 1), ('middle', 2), ('last', 3)],\n"
        ")\n"
        "def test_choice(kind, expected):\n"
        "    if kind == 'first':\n"
        "        result = 1\n"
        "    elif kind == 'middle':\n"
        "        result = 2\n"
        "    elif kind == 'last':\n"
        "        result = 3\n"
        "    assert identity(result) == expected\n"
    )

    payload, gaps = audit_lift_file(source, "parametrize_elif.py")

    assert gaps == []
    assertions = [row for row in payload.ir if row.inv is not None]
    assert len(assertions) == 3


def test_open_elif_chain_does_not_fabricate_definite_binding() -> None:
    source = (
        "def test_choice(kind, expected):\n"
        "    if kind == 'first':\n"
        "        result = 1\n"
        "    elif kind == 'middle':\n"
        "        result = 2\n"
        "    elif kind == 'last':\n"
        "        result = 3\n"
        "    assert result == expected\n"
    )

    with pytest.raises(FactoryPanic, match="observed=result requested=value"):
        audit_lift_file(source, "open_elif.py", hold_panic=False)


def test_literal_parametrize_witness_truthful_sat_wrong_twin_unsat(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in FunctionTestimonySugar.witnesses()
        if witness.name == "test_function_literal_parametrize_rows"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "parametrize-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "parametrize-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_joined_runtime_value_reads_as_its_named_effect_not_temporal_panic() -> None:
    block = compose_block(
        "    if outer:\n"
        "        result = 1 if runtime else 2\n"
        "    else:\n"
        "        result = 3\n"
        "    return result\n",
        {
            "outer": SymbolicValue(make_var("outer")),
            "runtime": SymbolicValue(make_var("runtime")),
        },
    )

    effects = [
        statement for statement in block.statements if isinstance(statement, Incomplete)
    ]
    assert effects
    assert type(effects[-1].effect).__name__ == "ConditionalExpressionRuntimeEffect"


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


def test_effect_valued_join_keeps_named_effect_binding_while_sibling_joins() -> None:
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
    broken = ctx.temporal.value_for("broken")
    assert type(broken).__name__ == "GuardedValue"
    answered = broken.answer(ctx)
    assert isinstance(answered, Incomplete)
    assert type(answered.effect).__name__ == "ConditionalExpressionRuntimeEffect"


def test_real_datetime_repr_assertions_measure_after_join(
    cpython_311_datetime_path,
) -> None:
    path = cpython_311_datetime_path
    source = path.read_text(encoding="utf-8")
    payload, gaps = audit_lift_file(source, str(path))
    axis = account_lift_coverage(
        census_source(source, file=str(path)), payload.to_rpc()
    ).to_json()["assertions"]

    assert axis["stated"] == 45
    assert axis["lifted_cited"] == 45
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0
    # time.__repr__ fold/tzinfo branch-joined asserts (artifact loci).
    assert {
        locus["line"] for locus in axis["lifted_loci"] if locus["line"] in {1610, 1613}
    } == {1610, 1613}
    assert gaps == []


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

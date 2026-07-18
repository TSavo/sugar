"""WhileSugar: while test: body threads the body; test coordinate is reduced.

Empty-orelse While only. Non-empty else: and For stay loud gaps / other arms.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    BlockValue,
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.sugar.for_sugar import ForSugar
from sugar_lift_py_tests.sugar.while_sugar import WhileSugar
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _site(source: str):
    node = ast.parse(source).body[0]
    return SourceFragment.from_node(node, "t.py")


def test_while_body_threads_into_the_record() -> None:
    """(1) Body statement contributes; test is reduced (method coordinate)."""
    block = compose_block(
        "    while z.ready():\n" "        return 1\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    assert isinstance(block, BlockValue)
    # BlockValue splices the while-body return -- no wrapper residue.
    assert len(block.statements) == 1
    ret = block.statements[0]
    assert isinstance(ret, ReturnValue)
    assert ret.value == TermValue(1)


def test_while_test_coordinate_carries_when_body_returns_it() -> None:
    """(1) Test coordinate rides when the body returns the condition name."""
    block = compose_block(
        "    while z:\n" "        return z\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    ret = block.statements[0]
    assert isinstance(ret, ReturnValue)
    assert ret.value == SymbolicValue(make_var("z"))


def test_test_or_body_discriminates_the_contribution() -> None:
    """(2) Different test or body produces a different contribution/term."""
    # Different test, body returns the condition name.
    while_z = compose_block(
        "    while z:\n" "        return z\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    while_w = compose_block(
        "    while w:\n" "        return w\n",
        binds={"w": SymbolicValue(make_var("w"))},
    )
    assert while_z.statements[0].value == SymbolicValue(make_var("z"))
    assert while_w.statements[0].value == SymbolicValue(make_var("w"))
    assert while_z.statements[0].value != while_w.statements[0].value

    # Different body with the same test shape.
    ret_one = compose_block(
        "    while z:\n" "        return 1\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    ret_two = compose_block(
        "    while z:\n" "        return 2\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    assert ret_one.statements[0].value == TermValue(1)
    assert ret_two.statements[0].value == TermValue(2)
    assert ret_one.statements[0].value != ret_two.statements[0].value


def test_method_test_is_reduced_before_body() -> None:
    """Test method-call coordinate is built (recognition), not dropped."""
    # Body does not use the test result; reducing the test must still succeed
    # so call:ready(z) is the address a dig lands on.
    block = compose_block(
        "    while z.ready():\n" "        return 1\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    assert block.statements[0].value == TermValue(1)
    # MethodCallSugar owns z.ready() as a TERM under the while test build.
    # Smoke: building the While selects WhileSugar, not a gap.
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("while z.ready():\n    return 1\n").body[0]
    result = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert result.audit_row.selected == "WhileSugar"


def test_owns_empty_orelse_while_not_for_or_else_or_expr() -> None:
    """(3) owns empty-orelse While; not For, while-else, or Assign."""
    assert WhileSugar.owns(_site("while y:\n    pass\n")) is True
    assert WhileSugar.owns(_site("for x in y:\n    pass\n")) is False
    assert ForSugar.owns(_site("while y:\n    pass\n")) is False
    assert WhileSugar.owns(_site("x = 1\n")) is False
    # Non-empty else: not owned this arm.
    assert WhileSugar.owns(_site("while y:\n    pass\nelse:\n    pass\n")) is False

    catalog = default_catalog()
    simple = _site("while y:\n    pass\n")
    with_else = _site("while y:\n    pass\nelse:\n    pass\n")
    assert any(
        c.name == "WhileSugar"
        for c in catalog.candidates_for(SugarRole.STATEMENT, simple)
    )
    assert not list(catalog.candidates_for(SugarRole.STATEMENT, with_else))


def test_while_else_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("while y:\n    pass\nelse:\n    pass\n").body[0]
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "While"


def test_for_is_not_owned_by_while_sugar() -> None:
    # For stays ForSugar's; WhileSugar does not claim it (no false gap on For).
    assert WhileSugar.owns(_site("for x in y:\n    pass\n")) is False
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("for x in y:\n    pass\n").body[0]
    result = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert result.audit_row.selected == "ForSugar"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "while unit != 'pt':\n"
            "    unit, mul = conversions[unit]\n"
            "    val *= mul\n"
            "    continue\n",
            ("unit", "val"),
        ),
        (
            "while getattr(val, 'ndim', True):\n"
            "    res0 = has_infs(val)\n"
            "    assert res0\n"
            "    val = take(val)\n"
            "    break\n",
            ("val",),
        ),
    ],
)
def test_loop_carried_names_exclude_iteration_temporaries(
    source: str, expected: tuple[str, ...]
) -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    built = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)

    assert isinstance(built.sugar, WhileSugar)
    assert built.sugar.carried == expected


def test_while_test_read_makes_a_stored_name_loop_carried() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("while active:\n    active = False\n    continue\n").body[0]
    built = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)

    assert isinstance(built.sugar, WhileSugar)
    assert built.sugar.carried == ("active",)


def test_literal_true_while_projects_names_assigned_before_every_break() -> None:
    recovered = audit_lift_file(
        "def result(value):\n"
        "    while True:\n"
        "        out = value\n"
        "        if value:\n"
        "            break\n"
        "        value = 1\n"
        "    return out\n",
        "while_output.py",
        recover_panics=True,
    )

    assert [
        panic.gap
        for panic in recovered.panics
        if panic.gap.get("owner") == "TemporalContext"
    ] == []


def test_nonliteral_while_does_not_invent_a_post_loop_binding() -> None:
    recovered = audit_lift_file(
        "def result(active):\n"
        "    while active:\n"
        "        out = 1\n"
        "        break\n"
        "    return out\n",
        "while_output_wrong_order.py",
        recover_panics=True,
    )
    temporal = [
        panic.gap
        for panic in recovered.panics
        if panic.gap.get("owner") == "TemporalContext"
    ]

    assert temporal
    assert {gap["observed"] for gap in temporal} == {"out"}


def test_unrecognized_break_path_does_not_invent_a_post_loop_binding() -> None:
    recovered = audit_lift_file(
        "def result(active):\n"
        "    while True:\n"
        "        if active:\n"
        "            out = 1\n"
        "            break\n"
        "        match active:\n"
        "            case _:\n"
        "                break\n"
        "    return out\n",
        "while_output_unrecognized_break.py",
        recover_panics=True,
    )
    temporal = [
        panic.gap
        for panic in recovered.panics
        if panic.gap.get("owner") == "TemporalContext"
    ]

    assert temporal
    assert {gap["observed"] for gap in temporal} == {"out"}


def test_unbound_prior_value_stays_a_loud_while_gap() -> None:
    with pytest.raises(FactoryPanic) as raised:
        compose_block("    while ready:\n        total += 1\n        break\n")

    assert raised.value.info.owner == "WhileSugar"
    assert raised.value.info.observed == ("total",)
    assert raised.value.info.requested == "statically bound loop-carried locals"


def test_while_loop_carried_witness_truthful_sat_wrong_twin_unsat(
    tmp_path: Path,
) -> None:
    pair = next(
        pair for pair in WhileSugar.witnesses() if pair.name == "while_loop_carried"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "while-carried-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "while-carried-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"
    assert "WhileSugar" in truthful.selected_sugars
    assert "WhileSugar" in lying.selected_sugars


def test_while_true_definite_output_witness_refutes(tmp_path: Path) -> None:
    pair = next(
        pair
        for pair in WhileSugar.witnesses()
        if pair.name == "while_true_definite_output"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "while-output-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "while-output-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"
    assert "WhileSugar" in truthful.selected_sugars
    assert "WhileSugar" in lying.selected_sugars

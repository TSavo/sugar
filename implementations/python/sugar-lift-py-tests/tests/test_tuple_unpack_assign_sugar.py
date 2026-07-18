from __future__ import annotations

import ast
from pathlib import Path

import pytest
from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.tuple_unpack_assign_sugar import (
    TupleUnpackAssignSugar,
)
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _site(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "t.py", source=source)


def test_flat_tuple_unpack_binds_every_name_to_its_rhs_element() -> None:
    assert compose_block(
        "    dayfrac, days = (0.5, 3)\n    return dayfrac + days\n"
    ) == BlockValue((ReturnValue(TermValue(3.5)),))


def test_module_execution_replays_tuple_unpack_before_later_definition() -> None:
    recovered = audit_lift_file(
        "pair = (2, 3)\n"
        "a, b = pair\n"
        "def A(x=a):\n"
        "    return x\n"
        "def test_a():\n"
        "    assert A() == 2\n",
        "temporal_tuple.py",
        recover_panics=True,
    )

    assert [
        panic.gap
        for panic in recovered.panics
        if panic.gap.get("owner") == "TemporalContext"
    ] == []


def test_module_execution_does_not_replay_later_tuple_unpack() -> None:
    recovered = audit_lift_file(
        "def A(x=a):\n"
        "    return x\n"
        "pair = (2, 3)\n"
        "a, b = pair\n"
        "def test_a():\n"
        "    assert A() == 2\n",
        "temporal_tuple_wrong_order.py",
        recover_panics=True,
    )
    temporal = [
        panic.gap
        for panic in recovered.panics
        if panic.gap.get("owner") == "TemporalContext"
    ]

    assert temporal
    assert {gap["observed"] for gap in temporal} == {"a"}


def test_module_tuple_unpack_execution_order_witness_refutes(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in TupleUnpackAssignSugar.witnesses()
        if witness.name == "module_tuple_unpack_execution_order"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "module-tuple-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "module-tuple-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_list_target_with_star_constructs_concrete_bindings() -> None:
    assert compose_block(
        "    [head, *middle, tail] = (1, 2, 3, 4)\n"
        "    return head + middle[0] + middle[1] + tail\n"
    ) == BlockValue((ReturnValue(TermValue(10)),))


def test_star_unpack_runtime_length_is_a_named_effect() -> None:
    result = compose_block(
        "    head, *middle, tail = values\n    return head\n",
        binds={"values": SymbolicValue(make_var("values"))},
    )

    effect = next(row for row in result.statements if isinstance(row, Incomplete))
    assert type(effect.effect).__name__ == "SequenceUnpackRuntimeEffect"


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

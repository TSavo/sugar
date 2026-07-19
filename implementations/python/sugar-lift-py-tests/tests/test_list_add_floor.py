from __future__ import annotations

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.factory import FactoryPanic
from sugar_lift_py_tests.effect import SequenceConcatenationRuntimeEffect
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ComprehensionValue,
    ListValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.outcome import Incomplete, complete_value
from sugar_lift_py_tests.factory.source_fragment import SourceFragment


def test_list_add_concatenates_constructed_elements() -> None:
    assert reduce_value("[1, 2] + [3]") == ListValue(
        (TermValue(1), TermValue(2), TermValue(3))
    )


def test_list_add_with_runtime_peer_cites_the_existing_operation_coordinate() -> None:
    value = reduce_value(
        "[1, 2] + tail", binds={"tail": SymbolicValue(make_var("tail"))}
    )

    assert value == SymbolicValue(
        ctor("+", [ctor("array", [num(1), num(2)]), make_var("tail")])
    )


def test_statically_invalid_list_addition_remains_loud() -> None:
    with pytest.raises(FactoryPanic, match="stand on the addition floor"):
        ListValue((TermValue(1),)).add(TermValue(2), "t.py:1:0")


def test_list_value_declares_its_add_floor_structurally() -> None:
    assert "add" in ListValue.__dict__


def test_list_add_runtime_sized_comprehension_is_named() -> None:
    site = SourceFragment.from_source("[1] + [x for x in xs]", "t.py")

    outcome = ListValue((TermValue(1),)).add(
        ComprehensionValue(ctor("py.listcomp", [make_var("xs")])), site
    )

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceConcatenationRuntimeEffect)


def test_runtime_sized_comprehension_is_the_sequence_concat_operand() -> None:
    site = SourceFragment.from_source("[x for x in xs] + ['tail']", "t.py")
    comprehension = ComprehensionValue(ctor("py.listcomp", [make_var("xs")]))

    outcome = comprehension.add(
        ListValue((StringValue("tail"),)),
        site,
    )

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceConcatenationRuntimeEffect)
    assert outcome.effect.witness.operand == comprehension.term


def test_ground_comprehension_concat_constructs_the_exact_coordinate() -> None:
    site = SourceFragment.from_source("[1] + ['tail']", "wrong_twin.py")
    comprehension = ComprehensionValue(ctor("py.listcomp", [num(1)]))

    value = complete_value(
        comprehension.add(ListValue((StringValue("tail"),)), site),
        owner="ground comprehension concat",
    )

    assert value == ComprehensionValue(
        ctor(
            "+",
            [
                comprehension.term,
                ctor("array", [StringValue("tail").to_term(owner="test")]),
            ],
        )
    )


def test_comprehension_plus_callsite_preserves_the_named_add_coordinate() -> None:
    site = SourceFragment.from_source("items + suffix()", "comprehension-call.py")
    comprehension = ComprehensionValue(ctor("py.listcomp", [make_var("items")]))
    callsite = CallSiteValue(
        target_name="suffix",
        arg_values=(),
        parameters=(),
        term=ctor("call:suffix", []),
        body=None,
        site=site,
    )

    value = complete_value(
        comprehension.add(callsite, site),
        owner="comprehension plus callsite",
    )

    assert value == SymbolicValue(
        ctor("+", [comprehension.term, callsite.term])
    )


def test_constructed_list_plus_ground_comprehension_constructs_exact_coordinate() -> (
    None
):
    site = SourceFragment.from_source("['head'] + [1]", "left-list.py")
    left = ListValue((StringValue("head"),))
    comprehension = ComprehensionValue(ctor("py.listcomp", [num(1)]))

    value = complete_value(
        left.add(comprehension, site),
        owner="list plus ground comprehension",
    )

    assert value == ComprehensionValue(
        ctor("+", [left.to_term(owner="test"), comprehension.term])
    )


def test_ground_comprehension_prefix_cites_only_runtime_right_operand() -> None:
    site = SourceFragment.from_source("[1] + [x for x in range(2)]", "mixed-concat.py")
    ground = ComprehensionValue(ctor("py.listcomp", [num(1)]))
    runtime = ComprehensionValue(ctor("py.listcomp", [ctor("call:range", [num(2)])]))

    outcome = ground.add(runtime, site)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceConcatenationRuntimeEffect)
    assert outcome.effect.runtime_operand.term == runtime.term
    assert outcome.effect.witness.operand == runtime.term


def test_runtime_sequence_concat_conserves_assertion_mass() -> None:
    source = (
        "def test_concat(xs):\n"
        "    result = [x for x in xs] + ['tail']\n"
        "    assert result == result\n"
    )

    payload, gaps = audit_lift_file(source, "sequence_concat.py")
    rpc = payload.to_rpc()
    assertions = account_lift_coverage(
        census_source(source, file="sequence_concat.py"), rpc
    ).to_json()["assertions"]

    assert gaps == []
    assert len(rpc["effects"]) == 1
    assert assertions["stated"] == 1
    assert assertions["refused_loud"] == 1
    assert assertions["silently_unaccounted"] == 0

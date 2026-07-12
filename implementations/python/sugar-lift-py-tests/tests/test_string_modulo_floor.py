from __future__ import annotations

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    GuardedValue,
    ListValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.ir import atomic, ctor, make_var, num, str_const
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.outcome import Complete


def test_concrete_percent_format_matches_python_interpreter_exactly() -> None:
    source = '"%04d-%s-%r" % (7, "day", "x")'
    expected = "%04d-%s-%r" % (7, "day", "x")

    assert reduce_value(source) == StringValue(expected)


def test_symbolic_percent_format_emits_format_coordinate_without_fabrication() -> None:
    symbolic = SymbolicValue(make_var("value"))
    result = StringValue(", tzinfo=%r").modulo(symbolic, "t.py:1")

    assert isinstance(result, Complete)
    assert isinstance(result.value, SymbolicValue)
    assert result.value.term == ctor(
        "py.format", [make_var("value"), str_const(", tzinfo=%r"), num(-1)]
    )


def test_attribute_callsite_percent_format_emits_native_format_coordinate() -> None:
    value = reduce_value(
        '", %d" % self._second', binds={"self": SymbolicValue(make_var("self"))}
    )

    assert isinstance(value, SymbolicValue)
    assert value.term == ctor(
        "py.format",
        [
            ctor("call:_second", [make_var("self")]),
            str_const(", %d"),
            num(-1),
        ],
    )


def test_percent_format_distributes_over_guarded_tuple_element() -> None:
    guard = atomic("choose", [])
    joined = GuardedValue(guard, StringValue("left"), StringValue("right"))

    outcome = StringValue("value=%s").modulo(TupleValue((joined,)), "datetime.py:1503")

    assert outcome == Complete(
        GuardedValue(
            guard,
            StringValue("value=left"),
            StringValue("value=right"),
        )
    )


def test_distributed_guarded_format_still_refuses_raw_term_projection() -> None:
    guard = atomic("choose", [])
    outcome = StringValue("%s").modulo(
        TupleValue((GuardedValue(guard, StringValue("a"), StringValue("b")),)),
        "structural.py:1",
    )
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, GuardedValue)
    assert "ite" not in repr(outcome.value)

    with pytest.raises(FactoryPanic, match="observed=GuardedValue.*to a term"):
        outcome.value.to_term(owner="no ite escape hatch")


def test_string_modulo_accepts_concrete_scalar_and_tuple_floors() -> None:
    assert StringValue("%d").modulo(TermValue(3), "t.py:1") == Complete(
        StringValue("3")
    )
    assert StringValue("%s:%d").modulo(
        TupleValue((StringValue("n"), TermValue(4))), "t.py:1"
    ) == Complete(StringValue("n:4"))


def test_unowned_percent_format_operand_reaches_loud_none_arm() -> None:
    with pytest.raises(FactoryPanic, match=r"None => panic"):
        StringValue("%s").modulo(ListValue((TermValue(1),)), "t.py:1")


def test_full_datetime_artifact_accounts_repr_assertions_honestly(
    cpython_311_datetime_path,
) -> None:
    path = cpython_311_datetime_path
    source = path.read_text(encoding="utf-8")
    assert len(source.splitlines()) == 2635

    payload, _gaps = audit_lift_file(source, str(path), hold_panic=True)
    assertions = account_lift_coverage(
        census_source(source, file=str(path)), payload.to_rpc()
    ).to_json()["assertions"]

    assert assertions["stated"] == 45
    target_lines = {2044, 2047}
    accounted = {
        locus["line"]
        for key in ("lifted_loci", "refused_loci")
        for locus in assertions[key]
        if locus["line"] in target_lines
    }
    assert accounted == target_lines


def test_full_datetime_repr_distributes_guarded_format_and_lifts_assertions(
    cpython_311_datetime_path,
) -> None:
    path = cpython_311_datetime_path
    source = path.read_text(encoding="utf-8")

    payload, gaps = audit_lift_file(source, str(path), hold_panic=True)
    assertions = account_lift_coverage(
        census_source(source, file=str(path)), payload.to_rpc()
    ).to_json()["assertions"]

    assert not any(gap.label.endswith(":1495:4") for gap in gaps)
    assert not any(
        ":1500:16 observed=StringValue requested=stand on the modulo floor"
        in gap.message
        for gap in gaps
    )
    assert assertions["lifted_cited"] == 14
    assert assertions["refused_loud"] == 31
    assert assertions["silently_unaccounted"] == 0
    assert {
        locus["line"]
        for locus in assertions["lifted_loci"]
        if locus["line"] in {1507, 1510}
    } == {1507, 1510}

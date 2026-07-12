from __future__ import annotations

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    ListValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.ir import ctor, make_var, num, str_const
from sugar_lift_py_tests.lift_rpc import audit_lift_file, lift_file_payload
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

    payload = lift_file_payload(source, str(path)).to_rpc()
    assertions = account_lift_coverage(
        census_source(source, file=str(path)), payload
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


def test_full_datetime_repr_reaches_next_loud_composition_gap(
    cpython_311_datetime_path,
) -> None:
    path = cpython_311_datetime_path
    source = path.read_text(encoding="utf-8")

    payload, gaps = audit_lift_file(source, str(path), hold_panic=True)
    assertions = account_lift_coverage(
        census_source(source, file=str(path)), payload.to_rpc()
    ).to_json()["assertions"]

    repr_gap = next(gap for gap in gaps if gap.label.endswith(":1495:4"))
    assert (
        "observed=GuardedValue requested=project this floor value to a term"
        in repr_gap.message
    )
    assert not any(
        ":1500:16 observed=StringValue requested=stand on the modulo floor"
        in gap.message
        for gap in gaps
    )
    assert assertions["lifted_cited"] == 7
    assert assertions["refused_loud"] == 38
    assert assertions["silently_unaccounted"] == 0
    assert {
        locus["line"]
        for locus in assertions["refused_loci"]
        if locus["line"] in {1507, 1510}
    } == {1507, 1510}

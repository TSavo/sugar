from __future__ import annotations

from pathlib import Path

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
from sugar_lift_py_tests.lift_rpc import lift_file_payload
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


def test_full_datetime_artifact_accounts_repr_assertions_honestly(cpython_311_datetime_path) -> None:
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

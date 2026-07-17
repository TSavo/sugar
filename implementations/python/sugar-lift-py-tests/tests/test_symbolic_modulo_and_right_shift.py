from __future__ import annotations

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file


def test_symbolic_numeric_modulo_uses_native_percent_coordinate() -> None:
    value = reduce_value("year % 4", binds={"year": SymbolicValue(make_var("year"))})

    assert value == SymbolicValue(ctor("%", [make_var("year"), num(4)]))


def test_symbolic_right_shift_uses_native_shift_coordinate() -> None:
    value = reduce_value("n >> 5", binds={"n": SymbolicValue(make_var("n"))})

    assert value == SymbolicValue(ctor(">>", [make_var("n"), num(5)]))


def test_concrete_right_shift_folds_on_numeric_floor() -> None:
    assert reduce_value("82 >> 5") == TermValue(2)


def test_matrix_multiply_constructs_native_at_coordinate() -> None:
    """#4387: symbolic ``@`` is the native operator coordinate, not a panic."""
    assert reduce_value(
        "left @ right",
        binds={
            "left": SymbolicValue(make_var("left")),
            "right": SymbolicValue(make_var("right")),
        },
    ) == SymbolicValue(ctor("@", [make_var("left"), make_var("right")]))


def test_shift_and_modulo_are_native_structural_terms_not_euf_aliases() -> None:
    modulo = reduce_value("x % 3", binds={"x": SymbolicValue(make_var("x"))})
    shift = reduce_value("x >> 2", binds={"x": SymbolicValue(make_var("x"))})

    assert modulo.term.name == "%"
    assert shift.term.name == ">>"
    assert "call:" not in repr(modulo.term)
    assert "call:" not in repr(shift.term)


def test_full_datetime_clears_precursors_and_names_next_blockers(
    cpython_311_datetime_path,
) -> None:
    path = cpython_311_datetime_path
    source = path.read_text(encoding="utf-8")
    payload, gaps = audit_lift_file(source, str(path))
    assertions = account_lift_coverage(
        census_source(source, file=str(path)), payload.to_rpc()
    ).to_json()["assertions"]
    messages = [gap.message for gap in gaps]

    assert not any(
        ":44:11" in message and "SymbolicValue" in message for message in messages
    )
    assert not any(
        ":138:12" in message and "observed=BinOp" in message for message in messages
    )
    assert not any(
        "observed=_DAYS_IN_MONTH requested=value" in message for message in messages
    )
    assert not any(
        "observed=_DAYS_BEFORE_MONTH requested=value" in message for message in messages
    )
    assert not any(
        "observed=_DI400Y requested=value" in message for message in messages
    )
    assert assertions["stated"] == 45
    assert assertions["lifted_cited"] == 45
    assert assertions["refused_loud"] == 0
    assert assertions["silently_unaccounted"] == 0
    assert {
        locus["line"]
        for locus in assertions["lifted_loci"]
        if locus["line"] in {67, 75, 160}
    } == {67, 75, 160}
    assert gaps == []

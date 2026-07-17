from __future__ import annotations

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.exceptional_exit_value import ExceptionalExitValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _exceptional_exit() -> ExceptionalExitValue:
    return ExceptionalExitValue(
        RaiseEffect(
            exception_name="TypeError",
            blame="test_exceptional_exit_arithmetic.py:1",
            source_sha256="0" * 64,
        )
    )


def test_subtract_propagates_an_already_selected_exceptional_exit() -> None:
    exceptional = _exceptional_exit()

    outcome = exceptional.subtract(TermValue(1), "subtract.py:1")

    assert outcome == Complete(exceptional)


def test_ground_subtraction_wrong_twin_remains_an_arithmetic_value() -> None:
    outcome = TermValue(4).subtract(TermValue(1), "subtract.py:1")

    assert outcome == Complete(TermValue(3))


def test_exceptional_exit_subtraction_truthful_and_lying_refute(tmp_path) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / "truthful",
        "def test_subtract(value):\n"
        "    assert ((value - 1) == (value - 1))"
        " & (value == 4) & (value == 4)\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying",
        "def test_subtract(value):\n"
        "    assert ((value - 1) == (value - 1))"
        " & (value == 4) & (not (value == 4))\n",
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "SubtractOpSugar" in truthful.selected_sugars
    assert "SubtractOpSugar" in lying.selected_sugars

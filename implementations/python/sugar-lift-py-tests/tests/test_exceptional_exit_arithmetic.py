from __future__ import annotations

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.exceptional_exit_value import ExceptionalExitValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.divide_op_sugar import DivideOpSugar
from sugar_lift_py_tests.sugar.multiply_op_sugar import MultiplyOpSugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
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


def test_add_propagates_an_already_selected_exceptional_exit() -> None:
    exceptional = _exceptional_exit()

    outcome = exceptional.add(TermValue(1), "add.py:1")

    assert outcome == Complete(exceptional)


def test_multiply_propagates_an_already_selected_exceptional_exit() -> None:
    exceptional = _exceptional_exit()

    outcome = exceptional.multiply(TermValue(2), "multiply.py:1")

    assert outcome == Complete(exceptional)


def test_divide_propagates_an_already_selected_exceptional_exit() -> None:
    exceptional = _exceptional_exit()

    outcome = exceptional.divide(TermValue(2), "divide.py:1")

    assert outcome == Complete(exceptional)


def test_subscript_propagates_an_already_selected_exceptional_exit() -> None:
    exceptional = _exceptional_exit()

    outcome = exceptional.subscript(TermValue(0), "subscript.py:1")

    assert outcome == Complete(exceptional)


def test_ground_subtraction_wrong_twin_remains_an_arithmetic_value() -> None:
    outcome = TermValue(4).subtract(TermValue(1), "subtract.py:1")

    assert outcome == Complete(TermValue(3))


def test_ground_addition_wrong_twin_remains_an_arithmetic_value() -> None:
    outcome = TermValue(4).add(TermValue(1), "add.py:1")

    assert outcome == Complete(TermValue(5))


def test_ground_multiplication_wrong_twin_remains_an_arithmetic_value() -> None:
    outcome = TermValue(4).multiply(TermValue(2), "multiply.py:1")

    assert outcome == Complete(TermValue(8))


def test_ground_division_wrong_twin_remains_an_arithmetic_value() -> None:
    outcome = TermValue(8).divide(TermValue(2), "divide.py:1")

    assert outcome == Complete(TermValue(4.0))


def test_ground_subscript_wrong_twin_remains_a_sequence_element() -> None:
    from sugar_lift_py_tests.floor import ListValue

    outcome = ListValue((TermValue(4),)).subscript(TermValue(0), "subscript.py:1")

    assert outcome == Complete(TermValue(4))


def test_exceptional_exit_addition_truthful_and_lying_refute(tmp_path) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / "truthful",
        "def test_add(value):\n"
        "    assert ((value + 1) == (value + 1))"
        " & (value == 4) & (value == 4)\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying",
        "def test_add(value):\n"
        "    assert ((value + 1) == (value + 1))"
        " & (value == 4) & (not (value == 4))\n",
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "AddOpSugar" in truthful.selected_sugars
    assert "AddOpSugar" in lying.selected_sugars


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


def test_exceptional_exit_multiply_truthful_and_lying_refute(tmp_path) -> None:
    pair = next(
        witness
        for witness in MultiplyOpSugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "exceptional_exit_multiply"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"
    assert "MultiplyOpSugar" in truthful.selected_sugars
    assert "MultiplyOpSugar" in lying.selected_sugars


def test_exceptional_exit_divide_truthful_and_lying_refute(tmp_path) -> None:
    pair = next(
        witness
        for witness in DivideOpSugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "exceptional_exit_divide"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"
    assert "DivideOpSugar" in truthful.selected_sugars
    assert "DivideOpSugar" in lying.selected_sugars

"""py.invert on SymbolicValue — construction gap drain (Part of #3809).

Lift-probe (before):

    def t(x):
        return ~x
    # or equality dig with symbolic operand

Refuse: FactoryGap · owner=UnaryOpSugar · observed=py.invert(SymbolicValue)
· requested=unary operator floor
· fix=add UnaryOperatorOperation support for py.invert on SymbolicValue

Mechanism: missing floor totalizer on UnaryOperatorOperation.unary_symbolic —
not a missing AST recognizer. UnaryOpSugar already owns Invert; TermValue
already folds ~int.

Fix: mint SymbolicValue(ctor("py.invert", [operand])) like py.neg (coordinate,
never fabricate a computed int).

Discrimination: dual-assert unsat via witness EXECUTION on concrete ~int fold.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.ir import _Ctor, make_var
from sugar_lift_py_tests.operations import UnaryOperatorOperation, perform_operation
from sugar_lift_py_tests.outcome import Complete, complete_value
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_invert_symbolic_mints_coordinate_not_gap() -> None:
    op = UnaryOperatorOperation(
        operator="py.invert", owner="UnaryOpSugar", blame="t.py:1"
    )
    receiver = SymbolicValue(make_var("x"))
    try:
        outcome = perform_operation(
            owner="UnaryOpSugar",
            blame="t.py:1",
            receiver=receiver,
            operation=op,
            ctx=None,
        )
    except FactoryGap as exc:  # pragma: no cover - regression
        raise AssertionError(f"still construction gap: {exc.info}") from exc
    assert isinstance(outcome, Complete)
    value = complete_value(outcome, owner="probe")
    assert isinstance(value, SymbolicValue)
    term = value.term
    assert isinstance(term, _Ctor)
    assert term.name == "py.invert"
    assert term.args == (make_var("x"),)


def test_invert_termvalue_still_folds() -> None:
    op = UnaryOperatorOperation(
        operator="py.invert", owner="UnaryOpSugar", blame="t.py:1"
    )
    outcome = perform_operation(
        owner="UnaryOpSugar",
        blame="t.py:1",
        receiver=TermValue(5),
        operation=op,
        ctx=None,
    )
    assert complete_value(outcome, owner="probe") == TermValue(~5)


def test_invert_concrete_report_no_floor_gap() -> None:
    src = (
        "def A():\n"
        "    return ~5\n"
        "\n"
        "def t():\n"
        "    assert A() == -6\n"
    )
    try:
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
    except FactoryGap as exc:  # pragma: no cover - regression
        raise AssertionError(f"still construction gap: {exc.info}") from exc
    assert report is not None
    blob = repr(report.payload)
    assert "py.invert(SymbolicValue)" not in blob
    assert "add UnaryOperatorOperation support for py.invert" not in blob
    assert report.payload.ir


def test_invert_dual_assert_refutes_lie_via_witness(tmp_path: Path) -> None:
    """Dual-assert discrimination: ~5 fold true vs lie → unsat via EXECUTION."""
    src = (
        "def A():\n"
        "    return ~5\n"
        "\n"
        "def t_true():\n"
        "    assert A() == -6\n"
        "\n"
        "def t_lie():\n"
        "    assert A() == 0\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert "add UnaryOperatorOperation support for py.invert" not in repr(
        report.payload
    )

    result = run_source_through_real_solver(tmp_path / "invert-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses

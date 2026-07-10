"""OpaqueOpCallsite.add_with — construction gap drain (Part of #3809).

Lift-probe (before):

    b = datetime_frame.add(noise, axis=0)   # pandas residual

Refuse: FactoryGap · owner=AddSugar · observed=OpaqueOpCallsite
· requested=add_with · fix=add add_with to OpaqueOpCallsite…

Mechanism: missing **floor totalizer** — not a missing AST recognizer.
AddSugar already owns `.add(...)`; OpaqueOpCallsite lacked the arm.

After: opaque → ``call:add(self, operand)`` with computed=None; folded
receivers still delegate to computed.add_with.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.operations.add_operation import AddOperation
from sugar_lift_py_tests.outcome import Complete, complete_value
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_opaque_add_mints_call_add_coordinate() -> None:
    receiver = OpaqueOpCallsite(
        callee="pandas.DataFrame",
        arg=SymbolicValue(make_var("df")),
        computed=None,
    )
    operand = SymbolicValue(make_var("noise"))
    outcome = receiver.add_with(
        AddOperation(operand=operand, owner="AddSugar", blame="t.py:1"),
        ctx=None,
    )
    assert isinstance(outcome, Complete)
    value = complete_value(outcome, owner="probe")
    assert isinstance(value, OpaqueOpCallsite)
    assert value.callee == "add"
    assert value.computed is None
    assert value.extra_args == (operand,)


def test_computed_add_still_folds() -> None:
    receiver = OpaqueOpCallsite(
        callee="len",
        arg=SymbolicValue(make_var("xs")),
        computed=TermValue(3),
    )
    outcome = receiver.add_with(
        AddOperation(operand=TermValue(2), owner="AddSugar", blame="t.py:1"),
        ctx=None,
    )
    assert complete_value(outcome, owner="probe") == TermValue(5)


def test_frame_add_body_dig_no_add_with_gap() -> None:
    src = (
        "import pandas as pd\n"
        "def t():\n"
        "    df = pd.DataFrame({'A': [1.0, 2.0]})\n"
        "    out = df.add(1)\n"
        "    assert out is not None\n"
    )
    try:
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
    except FactoryGap as exc:  # pragma: no cover
        raise AssertionError(f"still construction gap: {exc.info}") from exc
    assert report is not None
    blob = repr(report.payload)
    assert "requested=add_with" not in blob
    assert "OpaqueOpCallsite" not in blob or "add_with" not in blob or "call:add" in blob


def test_frame_add_dual_assert_refutes_lie_via_witness(tmp_path: Path) -> None:
    """Coordinate exists; dual assert on a foldable sibling refutes via EXECUTION."""
    src = (
        "def A(z):\n"
        "    return z + 1\n"
        "\n"
        "def t_true():\n"
        "    assert A(1) == 2\n"
        "\n"
        "def t_lie():\n"
        "    assert A(1) == 9\n"
    )
    result = run_source_through_real_solver(tmp_path / "opaque-add-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses

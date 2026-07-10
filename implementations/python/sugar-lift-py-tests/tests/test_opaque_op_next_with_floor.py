"""OpaqueOpCallsite.next_with — construction gap drain (Part of #3809).

Lift-probe (before):

    tup = next(df.itertuples(name=\"TestName\"))

Refuse: FactoryGap · owner=BuiltinCallSugar · observed=OpaqueOpCallsite
· requested=next_with

Mechanism: missing **floor totalizer** — not a missing AST recognizer.
``next(...)`` already routes through BuiltinCallSugar / NextOperation.

After: opaque → ``call:next(self)`` with computed=None.
"""

from __future__ import annotations

from sugar_lift_py_tests.factory import factory_panic
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.operations.next_operation import NextOperation
from sugar_lift_py_tests.outcome import Complete, complete_value


def test_opaque_next_mints_call_next_coordinate() -> None:
    receiver = OpaqueOpCallsite(
        callee="itertuples",
        arg=SymbolicValue(make_var("df")),
        computed=None,
    )
    outcome = receiver.next_with(
        NextOperation(owner="BuiltinCallSugar", blame="t.py:1"),
        ctx=None,
    )
    assert isinstance(outcome, Complete)
    value = complete_value(outcome, owner="probe")
    assert isinstance(value, OpaqueOpCallsite)
    assert value.callee == "next"
    assert value.computed is None
    assert value.arg is receiver


def test_itertuples_next_body_dig_no_next_with_gap() -> None:
    src = (
        "import pandas as pd\n"
        "def t():\n"
        "    df = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})\n"
        "    tup = next(df.itertuples(name=None))\n"
        "    assert tup is not None\n"
    )
    try:
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
    except FactoryGap as exc:  # pragma: no cover
        raise AssertionError(f"still construction gap: {exc.info}") from exc
    assert report is not None
    blob = repr(report.payload)
    assert "requested=next_with" not in blob

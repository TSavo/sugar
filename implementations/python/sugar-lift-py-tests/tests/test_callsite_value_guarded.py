"""CallSiteValue.guarded — ride under a branch without floor panic.

Known residual: owner=guarded blame=CallSiteValue requested=ride under a guard
(to_dict.py / base_parser.py). Mirrors ImportAliasValue: the authenticated
call coordinate is the value; the guard owns control.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.ir import ctor, make_var, num, py_eq
from sugar_lift_py_tests.outcome.exit_set import true_guard


def _callsite() -> CallSiteValue:
    return CallSiteValue(
        "vendor.op",
        (),
        (),
        ctor("call:vendor.op", []),
        None,
    )


def test_callsite_guarded_returns_self() -> None:
    site = _callsite()
    assert site.guarded(true_guard()) is site


def test_callsite_guarded_accepts_symbolic_formula() -> None:
    site = _callsite()
    formula = py_eq(make_var("z"), num(1))
    assert site.guarded(formula) is site

"""Plan Cut 2: re.search/match/fullmatch as language-owned floor operations.

The matcher core is proven separately; here the BuiltinSemanticCallable arm
applies it to concrete StringValue operands, yields a truthy ReMatchValue or
None, and keeps symbolic operands / out-of-subset patterns loud.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.callable_application import CallableApplication
from sugar_lift_py_tests.floor import BuiltinSemanticCallable
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.floor.re_match_value import ReMatchValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete


class _Op:
    def __init__(self, args, site="re.py:1"):
        self.arguments = tuple(args)
        self.keyword_names = ()
        self.site = site


def _apply(op_name, pattern, subject):
    callee = BuiltinSemanticCallable(operation=op_name)
    return callee.callable_application_with(
        _Op([StringValue(pattern) if isinstance(pattern, str) else pattern,
             StringValue(subject) if isinstance(subject, str) else subject]),
        None,
    )


def test_search_truthful_and_lying() -> None:
    msg = "A value is being set on a copy of a DataFrame"
    hit = _apply("python.re.search", "A value is being set", msg)
    assert isinstance(hit, Complete) and isinstance(hit.value, ReMatchValue)
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
    truth = hit.value.truth(site="s")
    assert isinstance(truth, Complete) and isinstance(truth.value, TrueBoolLiteralSugar)
    miss = _apply("python.re.search", "NOT the message", msg)
    assert isinstance(miss, Complete) and isinstance(miss.value, NoneValue)


def test_match_is_anchored_at_start() -> None:
    assert isinstance(_apply("python.re.match", "abc", "abcdef").value, ReMatchValue)
    assert isinstance(_apply("python.re.match", "bcd", "abcdef").value, NoneValue)


def test_fullmatch_requires_both_ends() -> None:
    assert isinstance(_apply("python.re.fullmatch", "a.c", "abc").value, ReMatchValue)
    assert isinstance(_apply("python.re.fullmatch", "ab", "abc").value, NoneValue)


def test_groups_are_recoverable() -> None:
    m = _apply("python.re.search", r"(\d+)-(\d+)", "id 12-345").value
    assert m.group_text(0) == "12-345"
    assert m.group_text(1) == "12" and m.group_text(2) == "345"


def test_symbolic_operand_stays_loud() -> None:
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    sym = SymbolicValue(make_var("s"))
    with pytest.raises(ConstructionPanic, match="concrete str"):
        _apply("python.re.search", "abc", sym)


def test_out_of_subset_pattern_stays_loud() -> None:
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic, match="decidable re subset"):
        _apply("python.re.search", "(?=lookahead)", "text")

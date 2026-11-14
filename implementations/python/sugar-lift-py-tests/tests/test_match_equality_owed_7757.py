"""#7757, a halt is never dropped: what a match equality owes reaches the result.

``case 1:`` compares the subject through its ``__eq__`` (Floor ``equals``).
The completed faces of that comparison decide which case runs, and they used
to feed ONLY the selection formula, so anything they owed (``owed`` on the
ExitSet arms, see ``outcome/exit_set.py``) was dropped. The match now
sequences every arm past the equality after it, so the selected body's arms
owe it, and so do the arms of every later case (the equality also ran on the
path where it was false).

Constructs MatchSugar / MatchCaseSpec directly (production desugar door), with
a subject whose ``equals`` answers one completed face owing an unanswered call.
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests import unanswered_calls
from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.ir import atomic
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.outcome.exit_set import true_guard
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.match_sugar import MatchCaseSpec, MatchSugar
from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class _Site:
    filename: str = "match_eq_owed.py"
    line: int = 1
    col: int = 0

    def __str__(self) -> str:
        return f"{self.filename}:{self.line}:{self.col}"


SITE = _Site()

# The unanswered ``__eq__`` call the comparison owes.
_ITEM = unanswered_calls.unanswered_call("python:Subject.__eq__", None)
_EQ = atomic("test:subject_eq_1", [])


@dataclass(frozen=True)
class _EqTruth:
    """The equality's completed value: its truth is the symbolic ``_EQ``."""

    formula: object

    def truth(self, site):
        del site
        return ExitSet.completed(self)


@dataclass(frozen=True)
class _Subject:
    """A subject whose ``__eq__`` completes owing ``owed``."""

    owed: tuple

    def equals(self, other, site, ctx):
        del other, site, ctx
        return ExitSet((Completed(true_guard(), _EqTruth(_EQ), owed=self.owed),))


@dataclass(frozen=True)
class _SubjectSugar(Sugar):
    value: object
    site: object = SITE

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value)


def _int(n: int) -> IntLiteralSugar:
    return IntLiteralSugar(n, site=_Site(col=n))


def _ret(n: int) -> ReturnSugar:
    return ReturnSugar(_int(n), site=_Site(line=n))


def _match(owed: tuple, *cases: MatchCaseSpec):
    sugar = MatchSugar(subject=_SubjectSugar(_Subject(owed)), cases=cases, site=SITE)
    outcome = sugar.desugar(ReduceContext.root(owner="test_match_equality_owed"))
    assert isinstance(outcome, ExitSet), type(outcome).__name__
    return outcome


def test_a_value_pattern_whose_eq_owes_leaves_the_match_owing_it() -> None:
    outcome = _match(
        (_ITEM,),
        MatchCaseSpec(alternatives=(_int(1),), body=(_ret(10),)),
    )
    assert outcome.exits
    assert outcome.owed_items() == (_ITEM,)
    # The selected body's arms are sequenced after the equality: each owes it.
    assert all(arm.owed == (_ITEM,) for arm in outcome.exits), outcome.exits


def test_the_later_case_owes_the_equality_that_ran_before_it() -> None:
    """``case 1: ... case _: ...``: the wildcard runs only after ``== 1`` ran."""
    outcome = _match(
        (_ITEM,),
        MatchCaseSpec(alternatives=(_int(1),), body=(_ret(10),)),
        MatchCaseSpec(alternatives=(), body=(_ret(20),)),
    )
    assert len(outcome.exits) >= 2, outcome.exits
    assert all(arm.owed == (_ITEM,) for arm in outcome.exits), outcome.exits


def test_twin_an_eq_owing_nothing_leaves_the_match_owing_nothing() -> None:
    outcome = _match(
        (),
        MatchCaseSpec(alternatives=(_int(1),), body=(_ret(10),)),
        MatchCaseSpec(alternatives=(), body=(_ret(20),)),
    )
    assert outcome.exits
    assert outcome.owed_items() == ()

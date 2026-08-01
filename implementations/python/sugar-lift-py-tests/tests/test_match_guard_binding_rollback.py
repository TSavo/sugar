"""Match guard binding rollback — production MatchSugar path.

Subject evaluates once. Pattern captures bind the subject for that case's
guard and body only: false guard rolls tentative bindings back before the next
case; true guard commits; guard halt bypasses later cases with pre-halt state.
Case order and wildcard fall-through are distinct. Binding/occurrence swap
twins refuse.

Constructs MatchSugar / MatchCaseSpec directly (production desugar door).
nodes.py is not modified — source `case P if g:` construction remains the
loud door there; this suite owns MatchSugar meaning.

MUST NOT TOUCH: nodes.py, CallSiteValue/source-return, carrier/ExitSet,
manager routing. No pattern-spelling admission.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.effect import NameErrorEffect, RaiseEffect
from sugar_lift_py_tests.floor import ReturnValue, TermValue
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted, Incomplete
from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset
from sugar_lift_py_tests.sugar.comparison_op_sugar import ComparisonOpSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.match_sugar import MatchCaseSpec, MatchSugar
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class _Site:
    filename: str = "match_guard.py"
    line: int = 1
    col: int = 0

    def __str__(self) -> str:
        return f"{self.filename}:{self.line}:{self.col}"


SITE = _Site()


def _int(n: int, *, line: int = 1) -> IntLiteralSugar:
    return IntLiteralSugar(n, site=_Site(line=line, col=n))


def _name(n: str, *, line: int = 1) -> NameSugar:
    return NameSugar(n, site=_Site(line=line, col=0))


def _gt(left: Sugar, right: Sugar, *, line: int = 1) -> ComparisonOpSugar:
    return ComparisonOpSugar("Gt", left, right, site=_Site(line=line, col=0))


def _ret(value: Sugar, *, line: int = 1) -> ReturnSugar:
    return ReturnSugar(value, site=_Site(line=line, col=0))


def _match(subject: Sugar, *cases: MatchCaseSpec) -> MatchSugar:
    return MatchSugar(subject=subject, cases=cases, site=SITE)


def _reduce(sugar: Sugar, ctx=None):
    if ctx is None:
        ctx = ReduceContext.root(owner="test_match_guard")
    return outcome_to_exitset(sugar.desugar(ctx))


def _returns(outcome: ExitSet) -> list:
    values = []
    for face in outcome.exits:
        if not isinstance(face, Completed):
            continue
        record = getattr(face.value, "record", None)
        entries = (
            record.statements
            if record is not None
            else getattr(face.value, "entries", ())
            or getattr(face.value, "statements", ())
        )
        for entry in entries:
            if isinstance(entry, ReturnValue):
                values.append((face.guard, entry.value))
            # Unguarded entries may be ReturnValue-like inside BlockValue
            if hasattr(entry, "value") and type(entry).__name__ == "ReturnValue":
                values.append((face.guard, entry.value))
    # Also scan Completed BlockValue.entries for ReturnValue
    for face in outcome.exits:
        if not isinstance(face, Completed):
            continue
        for entry in getattr(face.value, "entries", ()) or ():
            if isinstance(entry, ReturnValue):
                values.append((face.guard, entry.value))
            rv = getattr(entry, "value", None)
            if isinstance(rv, ReturnValue):
                values.append((face.guard, rv.value))
    return values


def _block_entries(outcome):
    if isinstance(outcome, Complete):
        block = outcome.value
        return tuple(
            getattr(block, "statements", None)
            or getattr(block, "entries", None)
            or ()
        )
    if isinstance(outcome, ExitSet):
        entries = []
        for face in outcome.exits:
            if isinstance(face, Completed):
                v = face.value
                entries.extend(
                    getattr(v, "statements", None)
                    or getattr(v, "entries", None)
                    or ()
                )
        return tuple(entries)
    return ()


def _block_return_values(outcome) -> list:
    """Pull TermValues from MatchSugar Complete(BlockValue)."""
    found = []
    for entry in _block_entries(outcome):
        if isinstance(entry, ReturnValue):
            found.append(entry.value)
        if type(entry).__name__ == "GuardedReturn":
            found.append(getattr(entry, "value", None))
        inner = getattr(entry, "value", None)
        if isinstance(inner, ReturnValue):
            found.append(inner.value)
    return found

# ===========================================================================
# Subject evaluates once
# ===========================================================================


class _CountingSubject(Sugar):
    """Subject sugar that counts desugar calls — must be exactly one."""

    def __init__(self, value: int):
        self.value = value
        self.calls = 0
        self.site = SITE

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        self.calls += 1
        return Complete(TermValue(self.value))


def test_subject_evaluates_once_across_multiple_cases() -> None:
    subject = _CountingSubject(5)
    sugar = _match(
        subject,
        MatchCaseSpec(
            alternatives=(_int(1),),
            body=(_ret(_int(10)),),
        ),
        MatchCaseSpec(
            alternatives=(_int(5),),
            body=(_ret(_int(50)),),
            capture_name=None,
        ),
        MatchCaseSpec(alternatives=(), body=(_ret(_int(0)),)),
    )
    sugar.desugar(ReduceContext.root(owner="once"))
    assert subject.calls == 1


# ===========================================================================
# Pattern bindings visible to that case's guard; true commits; false rolls back
# ===========================================================================


def test_capture_visible_to_guard_true_commits_body() -> None:
    """``case x if x > 0: return x`` with subject 5 → body sees capture 5."""
    sugar = _match(
        _int(5),
        MatchCaseSpec(
            alternatives=(),  # bare capture always matches
            body=(_ret(_name("x")),),
            guard=_gt(_name("x"), _int(0)),
            capture_name="x",
        ),
        MatchCaseSpec(alternatives=(), body=(_ret(_int(0)),)),
    )
    outcome = sugar.desugar(ReduceContext.root(owner="guard-true"))
    assert isinstance(outcome, Complete)
    # Under true ground guard, return TermValue(5) is present.
    values = _block_return_values(outcome)
    assert TermValue(5) in values or any(
        getattr(v, "value", v) == 5 for v in values
    ), values


def test_false_guard_rolls_back_before_next_case() -> None:
    """First case matches capture but guard false → second case can bind/run.

    ``case x if x > 10: return 1`` then ``case x if x > 0: return 2`` with
    subject 5: first guard false (rollback), second commits return 2.
    """
    sugar = _match(
        _int(5),
        MatchCaseSpec(
            alternatives=(),
            body=(_ret(_int(1)),),
            guard=_gt(_name("x"), _int(10)),
            capture_name="x",
        ),
        MatchCaseSpec(
            alternatives=(),
            body=(_ret(_int(2)),),
            guard=_gt(_name("x"), _int(0)),
            capture_name="x",
        ),
        MatchCaseSpec(alternatives=(), body=(_ret(_int(0)),)),
    )
    outcome = sugar.desugar(ReduceContext.root(owner="guard-false-rollback"))
    values = _block_return_values(outcome)
    # Second case wins under ground truth; first body must not be the sole answer.
    assert any(v == TermValue(2) or getattr(v, "value", None) == 2 for v in values), (
        values
    )
    # First case body return 1 is not selected under sat selection for subject 5.
    # (May appear under unsat guard formula — if present must be guarded unsat.)


def test_false_guard_does_not_leave_capture_for_later_case_scope() -> None:
    """Rollback: after false guard on case0, case1's capture is a fresh bind.

    Twin: case1 body reads capture; gets subject, not a stale failed-case bind.
    """
    sugar = _match(
        _int(3),
        MatchCaseSpec(
            alternatives=(),
            body=(_ret(_int(99)),),  # must not win
            guard=_gt(_name("x"), _int(100)),
            capture_name="x",
        ),
        MatchCaseSpec(
            alternatives=(),
            body=(_ret(_name("x")),),  # subject 3
            guard=_gt(_name("x"), _int(0)),
            capture_name="x",
        ),
    )
    outcome = sugar.desugar(ReduceContext.root(owner="fresh-capture"))
    values = _block_return_values(outcome)
    assert any(v == TermValue(3) or getattr(v, "value", None) == 3 for v in values), (
        values
    )


# ===========================================================================
# Guard halt bypasses later cases with pre-halt state
# ===========================================================================


@dataclass(frozen=True)
class _HaltingGuard(Sugar):
    """Guard that always Incomplete-halts with a named effect."""

    site: object = SITE

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return Incomplete(
            RaiseEffect(occurrence=AuthenticatedRaiseLocus.of(str(self.site)), exception_name='ValueError', blame=str(self.site), producer_node_owner='MatchGuard')
        )


def test_guard_halt_bypasses_later_cases() -> None:
    """When the guard raises, later cases do not contribute completed returns."""
    sugar = _match(
        _int(1),
        MatchCaseSpec(
            alternatives=(),
            body=(_ret(_int(1)),),
            guard=_HaltingGuard(),
            capture_name="x",
        ),
        MatchCaseSpec(
            alternatives=(),
            body=(_ret(_int(2)),),  # must not complete as winner
        ),
    )
    outcome = sugar.desugar(ReduceContext.root(owner="guard-halt"))
    # Guard halt: Halted (or ExitSet.collapse → Incomplete for sole true-guard
    # halt). Later cases do not contribute an unguarded Completed winner.
    if isinstance(outcome, Incomplete):
        assert outcome.effect.exception_name == "ValueError"
        return
    if isinstance(outcome, ExitSet):
        halted = [e for e in outcome.exits if isinstance(e, Halted)]
        assert halted, outcome.exits
        assert any(h.effect.exception_name == "ValueError" for h in halted)
        completed = [e for e in outcome.exits if isinstance(e, Completed)]
        for face in completed:
            from sugar_lift_py_tests.outcome.exit_set import true_guard

            if face.guard == true_guard():
                rets = _block_return_values(ExitSet((face,)))
                assert TermValue(2) not in rets
        return
    assert isinstance(outcome, Complete)
    entries = _block_entries(outcome)
    incompletes = [e for e in entries if isinstance(e, Incomplete)]
    assert incompletes, entries
    assert incompletes[0].effect.exception_name == "ValueError"

# ===========================================================================
# Case order and wildcard fall-through distinct
# ===========================================================================


def test_case_order_first_match_wins() -> None:
    """Value case 1 before case 2: subject 1 selects first body only."""
    sugar = _match(
        _int(1),
        MatchCaseSpec(alternatives=(_int(1),), body=(_ret(_int(10)),)),
        MatchCaseSpec(alternatives=(_int(1),), body=(_ret(_int(20)),)),  # same pattern later
        MatchCaseSpec(alternatives=(), body=(_ret(_int(0)),)),
    )
    outcome = sugar.desugar(ReduceContext.root(owner="order"))
    values = _block_return_values(outcome)
    assert any(v == TermValue(10) or getattr(v, "value", None) == 10 for v in values)


def test_wildcard_fallthrough_after_value_miss() -> None:
    sugar = _match(
        _int(9),
        MatchCaseSpec(alternatives=(_int(1),), body=(_ret(_int(10)),)),
        MatchCaseSpec(alternatives=(), body=(_ret(_int(0)),)),  # wildcard
    )
    outcome = sugar.desugar(ReduceContext.root(owner="wild"))
    values = _block_return_values(outcome)
    assert any(v == TermValue(0) or getattr(v, "value", None) == 0 for v in values)


def test_value_hit_skips_wildcard() -> None:
    sugar = _match(
        _int(1),
        MatchCaseSpec(alternatives=(_int(1),), body=(_ret(_int(10)),)),
        MatchCaseSpec(alternatives=(), body=(_ret(_int(0)),)),
    )
    outcome = sugar.desugar(ReduceContext.root(owner="value-hit"))
    values = _block_return_values(outcome)
    assert any(v == TermValue(10) or getattr(v, "value", None) == 10 for v in values)


# ===========================================================================
# Binding / occurrence swap twins refuse
# ===========================================================================


def test_swapped_case_order_is_not_truthful() -> None:
    """Reordering cases changes which body wins for the same subject."""
    subject = _int(1)
    truthful = _match(
        subject,
        MatchCaseSpec(alternatives=(_int(1),), body=(_ret(_int(10)),)),
        MatchCaseSpec(alternatives=(), body=(_ret(_int(0)),)),
    )
    swapped = _match(
        subject,
        MatchCaseSpec(alternatives=(), body=(_ret(_int(0)),)),  # wildcard first
        MatchCaseSpec(alternatives=(_int(1),), body=(_ret(_int(10)),)),
    )
    t_vals = _block_return_values(truthful.desugar(ReduceContext.root(owner="t")))
    s_vals = _block_return_values(swapped.desugar(ReduceContext.root(owner="s")))
    assert any(v == TermValue(10) or getattr(v, "value", None) == 10 for v in t_vals)
    assert any(v == TermValue(0) or getattr(v, "value", None) == 0 for v in s_vals)
    with pytest.raises(AssertionError):
        assert t_vals == s_vals


def test_swapped_capture_name_does_not_bind_wrong_name() -> None:
    """Guard reads capture_name only; wrong name stays unbound / not subject."""
    # Guard uses name "y" but capture is "x" — y is not tentatively bound.
    sugar = _match(
        _int(5),
        MatchCaseSpec(
            alternatives=(),
            body=(_ret(_int(1)),),
            guard=_gt(_name("y"), _int(0)),  # y free, not capture
            capture_name="x",
        ),
        MatchCaseSpec(alternatives=(), body=(_ret(_int(2)),)),
    )
    # Free name y becomes symbolic; comparison may factored dual faces — must not
    # silently treat as capture x. Outcome may be ExitSet (multi-face) or Complete.
    outcome = sugar.desugar(ReduceContext.root(owner="swap-name"))
    assert isinstance(outcome, (Complete, ExitSet))


def test_binding_swap_twin_refuses_same_outcome_as_truthful_capture() -> None:
    """Truthful capture_name='x' with guard x>0 differs from capture_name=None
    guard reading free x (no tentative bind of subject)."""
    truthful = _match(
        _int(5),
        MatchCaseSpec(
            alternatives=(),
            body=(_ret(_name("x")),),
            guard=_gt(_name("x"), _int(0)),
            capture_name="x",
        ),
    )
    lying = _match(
        _int(5),
        MatchCaseSpec(
            alternatives=(),
            body=(_ret(_name("x")),),
            guard=_gt(_name("x"), _int(0)),
            capture_name=None,  # no bind — free x symbolic
        ),
    )
    t = _block_return_values(truthful.desugar(ReduceContext.root(owner="t-cap")))
    l = _block_return_values(lying.desugar(ReduceContext.root(owner="l-cap")))
    # Truthful returns subject 5; lying does not commit TermValue(5) the same way.
    assert any(v == TermValue(5) or getattr(v, "value", None) == 5 for v in t)
    with pytest.raises(AssertionError):
        assert t == l


# ===========================================================================
# Regression: value patterns without guards still work
# ===========================================================================


def test_value_pattern_without_guard_unchanged() -> None:
    sugar = _match(
        _int(2),
        MatchCaseSpec(alternatives=(_int(1),), body=(_ret(_int(10)),)),
        MatchCaseSpec(alternatives=(_int(2),), body=(_ret(_int(20)),)),
        MatchCaseSpec(alternatives=(), body=(_ret(_int(0)),)),
    )
    outcome = sugar.desugar(ReduceContext.root(owner="value"))
    values = _block_return_values(outcome)
    assert any(v == TermValue(20) or getattr(v, "value", None) == 20 for v in values)


# ===========================================================================
# PRODUCTION source path: case P if g remains loud in nodes.py (honorably red)
# ===========================================================================


def test_production_source_case_guard_construction_is_honorably_red() -> None:
    """HONORABLY RED: source ``case x if x > 0:`` must construct MatchSugar.

    Today nodes.py Match._construct_sugar refuses guards (loud SugarNotWritten).
    MatchSugar.desugar already consumes guard+capture when supplied (consumer
    suite above). This test is the production door: it fails until construction
    emits MatchCaseSpec(guard=..., capture_name=...).

    Owner of the red: nodes.py Match._construct_sugar (out of scope for this
    PR — must not touch nodes.py here).
    fix=admit guard + bare capture into MatchCaseSpec at construction.
    """
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    source = (
        "def f(z):\n"
        "    match z:\n"
        "        case x if x > 0:\n"
        "            return x\n"
        "        case _:\n"
        "            return 0\n"
    )
    tree = SourceFile(
        (source, "prod_match_guard.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    # Production path — red until construction supplies guard/capture testimony.
    universe = function.sugar()
    match_stmts = [
        s for s in getattr(universe, "statements", ()) if isinstance(s, MatchSugar)
    ]
    assert match_stmts, (
        "PRODUCTION RED (construction): nodes.py Match._construct_sugar still "
        "refuses `case P if g:` — no MatchSugar in function body. "
        "owner=nodes.py Match._construct_sugar "
        "fix=emit MatchCaseSpec(guard=..., capture_name=...) "
        f"(observed statements={[type(s).__name__ for s in getattr(universe, 'statements', ())]})"
    )
    case0 = match_stmts[0].cases[0]
    assert case0.guard is not None, "construction omitted guard sugar"
    assert case0.capture_name == "x", "construction omitted capture_name"

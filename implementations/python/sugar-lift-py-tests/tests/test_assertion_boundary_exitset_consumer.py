"""Assertion boundaries consume body ExitSet effects, never producer shapes.

These laws deliberately begin after expression construction.  BinOp,
Subscript, Compare, Attribute, and Call are effect producers; this boundary is
only the consumer of the authenticated exits they publish.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted, true_guard


def _identity(name: str):
    from sugar_lift_py_tests.ir import str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


class _Expected:
    def __init__(self, name: str):
        self.identity = _identity(name)

    def exception_type_identity(self):
        return self.identity


def _state(marker: str):
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    return _ReducedBlock(entries=(marker,), can_fall_through=False, fall_through=())


def _raise(name: str, marker: str, *, message: object | None = None):
    raised_value = None
    if message is not None:
        raised_value = CallSiteValue(
            name,
            (message,),
            ("message",),
            ctor("call:exception", []),
            None,
        )
    return Halted(
        true_guard(),
        RaiseEffect(
            exception_name=name,
            blame=f"producer.py:1:{marker}",
            exception_type_coordinate=_identity(name),
            exception_type_mro=(_identity(name),),
            raised_value=raised_value,
        ),
        _state(marker),
    )


def _route(body: ExitSet, *, pattern=None) -> ExitSet:
    return body.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(
                expected=_Expected("ValueError"), message_pattern=pattern
            ),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )


def _marker(face):
    state = face.value if isinstance(face, Completed) else face.state
    return state.entries[0]


@dataclass(frozen=True)
class _ProducerExpression:
    native_shape: str
    authenticated_exit: Halted

    def exit_set(self):
        return ExitSet((self.authenticated_exit,))


@pytest.mark.parametrize(
    "producer",
    ["BinOp", "Subscript", "Compare", "Attribute", "UnaryOp", "BoolOp", "Call"],
)
def test_matching_arbitrary_body_producer_halt_is_consumed(producer):
    """The boundary consumes ExitSet effects from any body producer shape.

    Never by searching for a Call. BinOp / Subscript / Compare / Attribute /
    UnaryOp / BoolOp / Call all publish the same authenticated RaiseEffect
    edge; the consumer is shape-blind.
    """
    routed = _route(ExitSet((_raise("ValueError", producer),)))

    assert [(type(face).__name__, _marker(face)) for face in routed.exits] == [
        ("Completed", producer)
    ]


def test_same_body_without_a_halt_leaves_expectation_unsatisfied():
    routed = _route(ExitSet.completed(_state("completed-body")))

    assert len(routed.exits) == 1
    face = routed.exits[0]
    assert isinstance(face, Halted)
    assert isinstance(face.effect, ExpectationNotMetEffect)
    assert _marker(face) == "completed-body"


def test_wrong_exception_type_remains_halted():
    original = _raise("TypeError", "wrong-type")
    face = _route(ExitSet((original,))).exits[0]

    assert isinstance(face, Halted)
    assert face.effect is original.effect
    assert _marker(face) == "wrong-type"


def test_matching_consumption_preserves_completed_and_unrelated_arms():
    matching = _raise("ValueError", "matching")
    unrelated = _raise("TypeError", "unrelated")
    completed = Completed(true_guard(), _state("completed"))

    routed = _route(ExitSet((matching, unrelated, completed)))

    by_marker = {_marker(face): face for face in routed.exits}
    assert set(by_marker) == {"matching", "unrelated", "completed"}
    assert isinstance(by_marker["matching"], Completed)
    assert isinstance(by_marker["unrelated"], Halted)
    assert by_marker["unrelated"].effect is unrelated.effect
    assert isinstance(by_marker["completed"], Halted)
    assert isinstance(by_marker["completed"].effect, ExpectationNotMetEffect)


def test_match_predicate_remains_owed_without_message_evidence():
    body = ExitSet((_raise("ValueError", "message-open", message=TermValue(7)),))

    routed = _route(body, pattern=SymbolicValue(make_var("pattern")))

    assert len(routed.exits) == 2
    assert {type(face).__name__ for face in routed.exits} == {"Completed", "Halted"}
    assert all("py.re_search" in str(face.guard) for face in routed.exits)


def test_written_none_pattern_consumes_without_a_regex_obligation():
    """The helper's explicit ``match=None`` reaches the native None floor."""
    from sugar_lift_py_tests.floor import NoneValue, StringValue

    body = ExitSet((_raise("ValueError", "written-none", message=StringValue("boom")),))

    routed = _route(body, pattern=NoneValue())

    assert len(routed.exits) == 1
    assert isinstance(routed.exits[0], Completed)
    assert "py.re_search" not in str(routed.exits[0].guard)


def test_string_none_pattern_does_not_impersonate_written_none():
    """Lying twin: the string ``"None"`` remains an actual regex constraint."""
    from sugar_lift_py_tests.floor import StringValue

    body = ExitSet((_raise("ValueError", "string-none", message=StringValue("boom")),))

    routed = _route(body, pattern=StringValue("None"))

    assert len(routed.exits) == 1
    assert isinstance(routed.exits[0], Halted)


def test_empty_pattern_decides_only_for_the_empty_message():
    """Corpus shape: ``match="^$"`` at pandas json normalize line 175.

    The boundary consumes a matching empty-message raise and leaves a
    nonempty message halted -- never treats written ``^$`` as absence.
    """
    from sugar_lift_py_tests.floor import StringValue

    empty_body = ExitSet((_raise("ValueError", "empty-msg", message=StringValue("")),))
    nonempty_body = ExitSet(
        (_raise("ValueError", "nonempty-msg", message=StringValue("boom")),)
    )
    pattern = StringValue("^$")

    empty_routed = _route(empty_body, pattern=pattern)
    nonempty_routed = _route(nonempty_body, pattern=pattern)

    assert len(empty_routed.exits) == 1
    assert isinstance(empty_routed.exits[0], Completed)
    assert _marker(empty_routed.exits[0]) == "empty-msg"
    assert len(nonempty_routed.exits) == 1
    assert isinstance(nonempty_routed.exits[0], Halted)
    assert _marker(nonempty_routed.exits[0]) == "nonempty-msg"


def test_ordinary_pattern_decides_ground_re_search():
    """Corpus shape: ``match="whoops"`` at pandas register_accessor line 103."""
    from sugar_lift_py_tests.floor import StringValue

    matching = ExitSet(
        (_raise("ValueError", "ordinary-hit", message=StringValue("whoops")),)
    )
    missing = ExitSet(
        (_raise("ValueError", "ordinary-miss", message=StringValue("other")),)
    )
    pattern = StringValue("whoops")

    assert isinstance(_route(matching, pattern=pattern).exits[0], Completed)
    assert isinstance(_route(missing, pattern=pattern).exits[0], Halted)


def test_accumulated_alternation_retains_re_search_on_the_boundary():
    """Corpus shape: ``msg = "|".join(msgs)`` at pandas indexing line 108/111.

    A join-built alternation is a constructed call-site value. The boundary
    retains ``py.re_search`` over both faces rather than inventing a decision.
    """
    from sugar_lift_py_tests.floor import StringValue
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor

    pattern = CallSiteValue(
        "join",
        (StringValue("|"), SymbolicValue(make_var("msgs"))),
        (),
        ctor("call:join", []),
        None,
    )
    body = ExitSet(
        (
            _raise(
                "ValueError",
                "accum-open",
                message=StringValue("positional indexers are out-of-bounds"),
            ),
        )
    )

    routed = _route(body, pattern=pattern)

    assert len(routed.exits) == 2
    assert {type(face).__name__ for face in routed.exits} == {"Completed", "Halted"}
    assert all("py.re_search" in str(face.guard) for face in routed.exits)


@pytest.mark.parametrize("exception_name", ["ValueError", "TypeError"])
def test_nested_resource_cleanup_executes_on_matching_and_nonmatching_exits(
    exception_name,
):
    calls = []

    def cleanup():
        calls.append(exception_name)
        return ExitSet.completed("cleanup-completed")

    body_after_nested_resource = ExitSet(
        (_raise(exception_name, f"cleanup-{exception_name}"),)
    ).and_finally(cleanup)
    routed = _route(body_after_nested_resource)

    assert calls == [exception_name]
    assert _marker(routed.exits[0]) == f"cleanup-{exception_name}"
    assert isinstance(
        routed.exits[0], Completed if exception_name == "ValueError" else Halted
    )


def test_boundary_is_invariant_under_authenticated_producer_replacement():
    """Lying twin: producer spelling may change; its authenticated edge may not."""
    authenticated_exit = _raise("ValueError", "same-authenticated-effect")
    binop = _ProducerExpression("s_0123 & np.nan", authenticated_exit)
    subscript = _ProducerExpression("series[('foo', 'bar', 0), 2]", authenticated_exit)

    assert binop.native_shape != subscript.native_shape
    assert _route(binop.exit_set()) == _route(subscript.exit_set())

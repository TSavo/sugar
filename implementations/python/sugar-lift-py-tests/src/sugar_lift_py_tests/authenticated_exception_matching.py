"""One authenticated exception matcher shared by Try and With."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sugar_lift_py_tests.ir import Formula


def matches_raise_effect(effect, expected) -> "MessageVerdict":
    """Match by constructed exception coordinates and authenticated ancestry.

    The codomain is three-valued, exactly like the message predicate below, and
    for the same reason. Two authenticated identities settle the question here:
    exact identity is sufficient, and when the raised type carries
    source-derived MRO testimony a handler coordinate may match an
    authenticated ancestor -- that is ``MatchDecided``.

    When either operand's identity is NOT authenticated -- ``raise exc`` on a
    formal, a handler type this compiler could not resolve to a class -- the
    question is real and undecidable at lift. It is not a construction gap and
    it is not ``False``: deciding it either way fabricates a fact about a
    runtime type nobody testified to. It leaves as ``MatchRetained`` carrying
    ``adt.is_python_type(raised, handler)``, the reserved tester atom the floor
    already emits for exactly this question, so the router partitions the
    incoming exit by it and both faces reach the emitted FOL.

    Loud only where there is no question to retain: an operand that cannot even
    produce a term has nothing to state the predicate over. Spelling never
    participates on any arm.
    """
    from sugar_lift_py_tests.ir import atomic
    from sugar_source_tree.panic import SugarNotWritten

    identity_reader = getattr(expected, "exception_type_identity", None)
    expected_identity = identity_reader() if identity_reader is not None else None
    raised_identity = getattr(effect, "exception_type_coordinate", None)
    if expected_identity is not None and raised_identity is not None:
        if expected_identity == raised_identity:
            return MatchDecided(True)
        raised_mro = getattr(effect, "exception_type_mro", None)
        return MatchDecided(raised_mro is not None and expected_identity in raised_mro)

    owner = "matches_raise_effect"
    handler_term = expected_identity
    if handler_term is None:
        handler_term = _operand_term(expected, owner=owner, role="handler type")
    raised_term = raised_identity
    if raised_term is None:
        raised_term = _operand_term(
            effect.raised_value, owner=owner, role="raised exception"
        )
    if handler_term is None or raised_term is None:
        # THIS REFUSAL IS CORRECT OUTPUT, NOT OWED WORK.
        #
        # The retained atom is `adt.is_python_type(raised, handler)`, and
        # `raised` is the raised VALUE. An operand that cannot produce a value
        # term has nothing to state that predicate over, so there is no
        # question to retain and nothing to construct.
        #
        # A SOURCE COORDINATE IS NOT ADMISSIBLE AS THE SUBJECT. The effect
        # carries an `occurrence` (`file:line:col`) and it is tempting to hand
        # that over as the raised term, because it is authenticated and
        # deterministic and it makes the refusal disappear. It designates WHERE
        # THE RAISE IS WRITTEN, not WHAT WAS RAISED, so
        # `adt.is_python_type(<coordinate>, Handler)` is a predicate about the
        # wrong kind of thing. Emitting it would fabricate a fact about a
        # runtime type nobody testified to -- the same shape as weakening a
        # carried value under a guard: giving a construct a semantics it does
        # not have. The earlier `fix:` line here read "resolve both exception
        # operands through their lexical coordinates", which invited exactly
        # that repair; it cost one owner three rounds and nearly landed.
        raise SugarNotWritten(
            owner="matches_raise_effect",
            observed="handler or raised exception has no term to state the test over",
            requested="an authenticated exception identity or an emittable VALUE term",
            fix=(
                "authenticate the operand's exception identity, or give it a "
                "value term; a source coordinate designates the raise SITE, "
                "not the raised value, and is not admissible as the subject. "
                "Where neither exists this refusal is correct output and the "
                "row is accounted semantics, not owed work"
            ),
        )
    return MatchRetained(atomic("adt.is_python_type", [raised_term, handler_term]))


def _operand_term(operand, *, owner, role):
    """The emitted term for a matcher operand, or ``None`` when it has none.

    ``None`` is not a decision: it is the absence of anything to state the
    predicate over, and the sole caller turns it into a loud refusal.
    """
    del role
    if operand is None:
        return None
    to_term = getattr(operand, "to_term", None)
    if to_term is None:
        return None
    return to_term(owner=owner)


@dataclass(frozen=True)
class MatchDecided:
    """The contract's predicate is settled at lift, on constructed operands."""

    value: bool


@dataclass(frozen=True)
class MatchRetained:
    """The predicate is real but undecidable here; it leaves as an obligation.

    ``obligation`` is the FOL formula that IS the vendor's message predicate
    over the constructed operands. It is never evaluated at lift, never
    admitted as true, and never dropped as false: the router partitions the
    incoming exit by it, so both faces survive into the emitted FOL.
    """

    obligation: "Formula"


MessageVerdict = MatchDecided | MatchRetained


def _ground_string(term):
    """The Python ``str`` this term IS, or ``None`` when it is not ground.

    Groundness is asked of the emitted TERM, never of the value's species. Every
    floor value answers ``to_term``; a ground string arrives as ``_ConstStr``
    and anything else -- a variable, a call, an opaque projection -- does not.
    That keeps this a one-line property of the shared codomain instead of a
    ladder over floor kinds that would need a new arm per value class.
    """
    from sugar_lift_py_tests.ir import _ConstStr

    return term.value if isinstance(term, _ConstStr) else None


def _message_term(effect, *, owner):
    """The testified message operand, or rendered-message projection of a value.

    ``raise E()`` constructs no argument, and the message of such a value is
    exactly ``""`` -- a ground fact, not an absence. A non-call raised value
    can still testify to the value being rendered; its message stays open as
    ``py.exception_message(value)``. Only a valueless effect is loud, because
    there is then no admissible subject for the projection.
    """
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_source_tree.panic import SugarNotWritten

    raised = effect.raised_value
    if isinstance(raised, CallSiteValue):
        args = raised.arg_values
        return args[0].to_term(owner=owner) if args else str_const("")

    raised_term = _operand_term(raised, owner=owner, role="raised exception")
    if raised_term is None:
        raise SugarNotWritten(
            owner="authenticated_exception_matching._message_term",
            observed="raised exception has no value term to render as a message",
            requested="a message operand or an emittable raised VALUE term",
            fix=(
                "authenticate the raised value or its message operand; a source "
                "coordinate designates the raise SITE, not the raised value, "
                "and is not admissible as the rendered-message subject"
            ),
        )
    return ctor("py.exception_message", [raised_term])


def raise_effect_message_verdict(effect, expected, pattern) -> MessageVerdict:
    """Authenticated identity match, then the contract's optional message predicate.

    The identity half is ``matches_raise_effect`` -- the one matcher. BOTH
    halves have THREE outcomes, and this function is their conjunction, so it
    is the conjunction of two three-valued verdicts and nothing here may
    collapse one. A contract that states no pattern asserts nothing about the
    message (``MatchDecided(True)``). Two ground strings settle the message
    predicate here. Anything else -- a symbolic message, a computed pattern --
    leaves as ``MatchRetained`` carrying ``py.re_search(pattern, message)``,
    the vendor's own predicate spelled on the membrane.

    A ``False`` on either half is ``False`` outright: a conjunct that is
    decidably false settles the conjunction without deciding the other half.
    Two open halves leave as one conjoined obligation.
    """
    import re

    from sugar_lift_py_tests.ir import and_, atomic

    identity = matches_raise_effect(effect, expected)
    if isinstance(identity, MatchDecided) and not identity.value:
        return MatchDecided(False)
    retained_identity = (
        identity.obligation if isinstance(identity, MatchRetained) else None
    )

    def _conjoin(verdict):
        """Fold the open identity half, if any, into a settled message half."""
        if retained_identity is None:
            return verdict
        if isinstance(verdict, MatchDecided):
            if not verdict.value:
                return MatchDecided(False)
            return MatchRetained(retained_identity)
        return MatchRetained(and_([retained_identity, verdict.obligation]))

    if pattern is None:
        return _conjoin(MatchDecided(True))

    owner = "authenticated_exception_matching.raise_effect_message_verdict"
    pattern_term = pattern.to_term(owner=owner)
    message_term = _message_term(effect, owner=owner)

    ground_pattern = _ground_string(pattern_term)
    ground_message = _ground_string(message_term)
    if ground_pattern is not None and ground_message is not None:
        return _conjoin(
            MatchDecided(re.search(ground_pattern, ground_message) is not None)
        )

    return _conjoin(MatchRetained(atomic("py.re_search", [pattern_term, message_term])))

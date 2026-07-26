"""One authenticated exception matcher shared by Try and With."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sugar_lift_py_tests.ir import Formula


def matches_raise_effect(effect, expected) -> bool:
    """Match by constructed exception coordinates and authenticated ancestry.

    Exact identity is sufficient. When the raised type carries source-derived
    MRO testimony, a handler coordinate may match an authenticated ancestor.
    Missing identity is a construction gap; spelling never participates.
    """
    from sugar_source_tree.panic import SugarNotWritten

    identity_reader = getattr(expected, "exception_type_identity", None)
    expected_identity = identity_reader() if identity_reader is not None else None
    raised_identity = getattr(effect, "exception_type_coordinate", None)
    if expected_identity is None or raised_identity is None:
        raise SugarNotWritten(
            owner="matches_raise_effect",
            observed="handler or raised exception lacks authenticated identity",
            requested="authenticated exception-type identity on both operands",
            fix="resolve both exception classes through their lexical coordinates",
        )
    if expected_identity == raised_identity:
        return True
    raised_mro = getattr(effect, "exception_type_mro", None)
    return raised_mro is not None and expected_identity in raised_mro


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
    """The term of the raised call's message operand, or the ground empty message.

    ``raise E()`` constructs no argument, and the message of such a value is
    exactly ``""`` -- a ground fact, not an absence. Anything that is not a
    constructed call has no authenticated message operand at all and is loud.
    """
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import str_const
    from sugar_source_tree.panic import SugarNotWritten

    raised = effect.raised_value
    if not isinstance(raised, CallSiteValue):
        raise SugarNotWritten(
            owner="authenticated_exception_matching._message_term",
            observed="raised value is not a constructed call occurrence",
            requested="a CallSiteValue whose first actual is the message operand",
            fix=(
                "construct the raised exception through its call site; never "
                "read a message off an unconstructed value"
            ),
        )
    args = raised.arg_values
    return args[0].to_term(owner=owner) if args else str_const("")


def raise_effect_message_verdict(effect, expected, pattern) -> MessageVerdict:
    """Authenticated identity match, then the contract's optional message predicate.

    The identity half is ``matches_raise_effect`` -- the one matcher, and it is
    total: a missing identity is loud there, never a quiet ``False``.

    The message half has THREE outcomes, not two. A contract that states no
    pattern asserts nothing about the message (``MatchDecided(True)``). Two
    ground strings settle the predicate here. Anything else -- a symbolic
    message, a computed pattern -- is a predicate this compiler cannot decide,
    and deciding it either way would be a fabricated fact. It leaves as
    ``MatchRetained`` carrying ``py.re_search(pattern, message)``, which is the
    vendor's own predicate spelled on the membrane.
    """
    import re

    from sugar_lift_py_tests.ir import atomic

    if not matches_raise_effect(effect, expected):
        return MatchDecided(False)
    if pattern is None:
        return MatchDecided(True)

    owner = "authenticated_exception_matching.raise_effect_message_verdict"
    pattern_term = pattern.to_term(owner=owner)
    message_term = _message_term(effect, owner=owner)

    ground_pattern = _ground_string(pattern_term)
    ground_message = _ground_string(message_term)
    if ground_pattern is not None and ground_message is not None:
        return MatchDecided(re.search(ground_pattern, ground_message) is not None)

    return MatchRetained(atomic("py.re_search", [pattern_term, message_term]))

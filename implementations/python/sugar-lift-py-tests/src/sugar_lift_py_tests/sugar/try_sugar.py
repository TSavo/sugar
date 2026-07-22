"""`try: body (except E: handler)+ [else] [finally]` -- structural effect routing.

The structural sibling of ``with``-raises (#5994). ``WithContractSugar`` routes
via a membrane-issued contract; this sugar routes via the ``except E`` clauses
themselves -- native syntax, no vendor names. Matching reuses the ONE effect
router's exact kind+name rule (``_matching_effect``): a subclass raise is the
mismatch twin, never silently matched.

Arms (T's ruling, restated as reduction):

- A matching ``except E`` CONSUMES the body's ``Incomplete(RaiseEffect)`` and
  reduces the handler body; the handler's own effects propagate.
- A non-matching raise propagates past all handlers.
- A body with no observed raise reduces ``else`` (when present).
- ``finally`` always reduces and splices; its effects ride on every path.

Loud residuals stay at the node (bare ``except:``, tuple types, ``as`` binding,
``except*`` on TryStar) -- never silently dropped here.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class TrySugar(Sugar):
    """`try` with typed except handlers, constructed by ``Try.sugar``.

    ``handlers`` is an ordered tuple of ``(EffectMatcher, body_sugars)`` --
    one per ``except E:`` clause, already structure-checked by the node.
    """

    body: tuple  # body statement sugars, source order
    handlers: tuple  # ((EffectMatcher, handler_body_sugars), ...)
    orelse: tuple = ()  # else-branch statement sugars
    finalbody: tuple = ()  # finally statement sugars
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        # Matching except consumes the raise so the function completes past the
        # try; a lift that left the raise unconsumed would fail the post.
        prefix = (
            "def A(z):\n"
            "    try:\n"
            "        raise ValueError\n"
            "    except ValueError:\n"
            "        pass\n"
            "    return z\n\n"
        )
        return _call_pair(
            name="try_matching_except_consumes",
            owner_sugar="TrySugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.effect_router import (
            _first_effect_of_kind,
            _matching_effect,
        )
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.outcome import Incomplete
        from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_statements

        del ctx

        body_entries, _body_falls, _ = reduce_statements(self.body)
        body_entries = tuple(body_entries)

        # Route among handlers by the shared exact-match rule. First match wins
        # (Python order); a match CONSUMES the Incomplete and splices the
        # handler body's entries in its place.
        routed = None
        for matcher, handler_body in self.handlers:
            matching = _matching_effect(body_entries, matcher)
            if matching is None:
                continue
            index, _entry, _observation = matching
            remaining = body_entries[:index] + body_entries[index + 1 :]
            handler_entries, _hf, _ = reduce_statements(handler_body)
            routed = (*remaining, *handler_entries)
            break

        if routed is None:
            # No handler matched. A body with no observed raise runs else; a
            # non-matching raise propagates (kept in the entries).
            if _first_effect_of_kind(body_entries, "raise") is None:
                else_entries, _ef, _ = reduce_statements(self.orelse)
                routed = (*body_entries, *else_entries)
            else:
                routed = body_entries

        # finally runs on every path; its statements reduce and their effects
        # propagate on all exits (caught, uncaught, else, fall-through).
        finally_entries, _ff, _ = reduce_statements(self.finalbody)
        entries = (*routed, *finally_entries)

        # Mirror WithContractSugar: fall-through restored exactly when no red
        # testimony survives the routing.
        can_fall_through = not any(isinstance(e, Incomplete) for e in entries)
        return Complete(BlockValue(entries, can_fall_through=can_fall_through))

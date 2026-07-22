"""`try: body (except E [as e]: handler)+ [else] [finally]` -- effect routing.

``except E as e`` is rewritten by the tree to ``EffectRef(slot)`` before sugar.
This sugar matches the raise and authenticates the slot with the Halted
payload — never re-desugars the handler with a name map, never E().
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class TrySugar(Sugar):
    """handlers: ((EffectMatcher|None, body_sugars, slot_id|None), ...)"""

    body: tuple
    handlers: tuple
    orelse: tuple = ()
    finalbody: tuple = ()
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
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
        from sugar_lift_py_tests.effect_auth import authenticate_slot
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

        routed = None
        for matcher, handler_body, slot_id in self.handlers:
            matching = (
                _first_effect_of_kind(body_entries, "raise")
                if matcher is None
                else _matching_effect(body_entries, matcher)
            )
            if matching is None:
                continue
            index, entry, _observation = matching
            remaining = body_entries[:index] + body_entries[index + 1 :]
            # Syntax created the coordinate; routing supplies testimony.
            if slot_id is not None and isinstance(entry, Incomplete):
                authenticate_slot(slot_id, entry.effect)
            handler_entries, _hf, _ = reduce_statements(handler_body)
            routed = (*remaining, *handler_entries)
            break

        if routed is None:
            if _first_effect_of_kind(body_entries, "raise") is None:
                else_entries, _ef, _ = reduce_statements(self.orelse)
                routed = (*body_entries, *else_entries)
            else:
                routed = body_entries

        finally_entries, _ff, _ = reduce_statements(self.finalbody)
        entries = (*routed, *finally_entries)

        can_fall_through = not any(isinstance(e, Incomplete) for e in entries)
        return Complete(BlockValue(entries, can_fall_through=can_fall_through))

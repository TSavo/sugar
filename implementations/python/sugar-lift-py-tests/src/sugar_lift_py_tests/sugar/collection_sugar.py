"""Collection displays: `[..]` list, `(..)` tuple, `{..}` set, `{k: v}` dict.

Each reduces its element sugars in source order and holds the reduced floor
values -- ListValue / TupleValue / SetValue / DictValue. The floor owns what the
collection then DOES (len, subscript, membership); this only constructs it. An
element that is itself an effect propagates -- a collection with an unresolvable
element is not a value. Star/double-star spreads (`*xs`, `**d`) stay loud until
their own sugar lands: a spread is not one element, and guessing would invent
membership the source never stated.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


def _reduce_all(element_sugars, ctx):
    """Reduce each element sugar to its floor value, in order. Returns
    ``(values, None)`` or ``(None, effect)`` if an element reduced to an effect."""
    from sugar_lift_py_tests.outcome import Incomplete

    values = []
    for element in element_sugars:
        out = element.desugar(ctx)
        if isinstance(out, Incomplete):
            return None, out
        values.append(out.value)
    return tuple(values), None


@dataclass(frozen=True)
class ListSugar(Sugar):
    elements: tuple
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="list_len",
            owner_sugar="ListSugar",
            body="len([z, z, z])",
            truthful="3",
            lying="2",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.list_value import ListValue

        values, effect = _reduce_all(self.elements, ctx)
        return effect if effect is not None else Complete(ListValue(values))


@dataclass(frozen=True)
class TupleSugar(Sugar):
    elements: tuple
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="tuple_len",
            owner_sugar="TupleSugar",
            body="len((z, z))",
            truthful="2",
            lying="3",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        values, effect = _reduce_all(self.elements, ctx)
        return effect if effect is not None else Complete(TupleValue(values))


@dataclass(frozen=True)
class SetSugar(Sugar):
    elements: tuple
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="set_len",
            owner_sugar="SetSugar",
            body="len({1, 2, 3})",
            truthful="3",
            lying="2",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.set_value import SetValue

        values, effect = _reduce_all(self.elements, ctx)
        return effect if effect is not None else Complete(SetValue(values))


@dataclass(frozen=True)
class DictSugar(Sugar):
    keys: tuple  # key sugars, in source order
    values: tuple  # value sugars, in source order
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="dict_len",
            owner_sugar="DictSugar",
            body="len({1: z, 2: z})",
            truthful="2",
            lying="3",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.dict_value import DictValue

        key_values, effect = _reduce_all(self.keys, ctx)
        if effect is not None:
            return effect
        val_values, effect = _reduce_all(self.values, ctx)
        if effect is not None:
            return effect
        entries = tuple(zip(key_values, val_values))
        return Complete(DictValue(entries))

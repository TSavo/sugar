from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class DictValue(FloorValue):
    """A dict of reduced (key, value) floor pairs, in source order.

    The sugar reduces each key and each value; the floor holds what those
    reductions were. No methods beyond the dataclass and the subscript floor --
    floors this dict does not implement panic for free via FloorValue defaults.
    """

    entries: tuple

    def length(self, site):
        del site
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(TermValue(len(self.entries)))

    def bitwise_or(self, other, site):
        if type(other) is not DictValue:
            return super().bitwise_or(other, site)
        del site
        entries = list(self.entries)
        for right_key, right_value in other.entries:
            for index, (left_key, _left_value) in enumerate(entries):
                if type(left_key) is type(right_key) and getattr(
                    left_key, "value", object()
                ) == getattr(right_key, "value", object()):
                    entries[index] = (left_key, right_value)
                    break
            else:
                entries.append((right_key, right_value))
        from sugar_lift_py_tests.outcome import Complete

        return Complete(DictValue(tuple(entries)))

    def to_term(self, *, owner: str):
        # Project as python:dict of entry pairs (layout-preserving coordinate).
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:dict",
            [
                ctor(
                    "python:dict_entry",
                    [k.to_term(owner=owner), v.to_term(owner=owner)],
                )
                for k, v in self.entries
            ],
        )

    def subscript(self, index, site):
        # Concrete key match returns the value; concrete miss is KeyError.
        # Symbolic index (or non-ground key compare) stays the py.subscript
        # coordinate when the sides can project to terms.
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        concrete = type(index) is StringValue or type(index) is TermValue
        if concrete:
            for key, value in self.entries:
                if type(key) is type(index):
                    if type(key) is StringValue and key.value == index.value:
                        return Complete(value)
                    if type(key) is TermValue and key.value == index.value:
                        return Complete(value)
            from sugar_lift_py_tests.effect import KeyErrorRuntimeEffect, runtime_effect_witness

            return Incomplete(
                KeyErrorRuntimeEffect(
                    f"dict key missing runtime boundary: "
                    f"key={index!r}; owner=DictValue.subscript site={site}",
                    witness=runtime_effect_witness("py.subscript", index, site),
                )
            )
        return self.py_subscript_coordinate(index, site)

    def setitem(self, index, value, site):
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        if type(index) is StringValue or type(index) is TermValue:
            entries = list(self.entries)
            for position, (key, _old_value) in enumerate(entries):
                if type(key) is type(index) and key.value == index.value:
                    entries[position] = (key, value)
                    return Complete(DictValue(tuple(entries)))
            entries.append((index, value))
            return Complete(DictValue(tuple(entries)))
        from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect, runtime_effect_witness

        return Incomplete(
            SubscriptStoreRuntimeEffect(
                "dict subscript store requires a concrete key; "
                f"owner=DictValue.setitem site={site}",
                witness=runtime_effect_witness("py.setitem", index, site),
            )
        )

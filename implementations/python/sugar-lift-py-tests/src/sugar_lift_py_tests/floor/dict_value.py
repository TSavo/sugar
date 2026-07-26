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

    def truth(self, site):
        """A constructed dict is truthy exactly when it has an entry."""
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(
            TrueBoolLiteralSugar(site=site)
            if self.entries
            else FalseBoolLiteralSugar(site=site)
        )

    def length(self, site):
        del site
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(TermValue(len(self.entries)))

    def contains(self, item, site):
        # A guarded needle is not one needle: distribute into its faces and
        # rejoin under the same guard before this receiver's own law runs.
        from sugar_lift_py_tests.floor.guarded_operand import (
            distribute_guarded_predicate,
        )

        distributed = distribute_guarded_predicate(self, item, "contains", site)
        if distributed is not None:
            return distributed
        # Python ``k in d`` is key membership over constructed entry keys.
        from sugar_lift_py_tests.floor.set_value import (
            _bool_result,
            _closed_member_equal,
        )

        keys = tuple(key for key, _value in self.entries)
        decisions = tuple(_closed_member_equal(item, key) for key in keys)
        if any(decision is True for decision in decisions):
            return _bool_result(True, site)
        if all(decision is False for decision in decisions):
            return _bool_result(False, site)
        if any(decision is None for decision in decisions):
            from sugar_lift_py_tests.floor.predicate_value import PredicateValue
            from sugar_lift_py_tests.ir import atomic
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
                PredicateValue(
                    atomic(
                        "python.dict.contains",
                        [
                            item.to_term(owner="python.dict.contains key"),
                            self.to_term(owner="python.dict.contains dict"),
                        ],
                    ),
                    site,
                    operand_callsites=(*item.callsites(), *self.callsites()),
                )
            )
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="DictValue.contains",
            blame=str(site),
            observed=type(item).__name__,
            requested="constructed finite key or typed symbolic membership operand",
            fix="construct key equality on the Python floor or keep it loud",
        )

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

    def attribute(self, name, site):
        # Bound methods and fields on a constructed dict (``{{}}.get``, ``mapping.items``) stay the
        # py.getattr coordinate -- one law, shared with StringValue and the
        # other constructed containers. Never invent a method body or a field.
        del site
        from sugar_lift_py_tests.floor.getattr_coordinate import getattr_coordinate

        return getattr_coordinate(self, name, owner="DictValue.attribute")

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
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="dict.subscript",
                blame=site,
                observed=f"missing concrete key {index!r}",
                requested="exact dictionary post-state or exceptional exit",
                fix=(
                    "carry exact dictionary provenance and intervening mutation "
                    "testimony before deciding KeyError; otherwise keep the "
                    "missing post-state construction loud"
                ),
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
        from sugar_lift_py_tests.effect import (
            SubscriptStoreRuntimeEffect,
            runtime_effect_evidence,
        )

        return Incomplete(
            SubscriptStoreRuntimeEffect(
                "dict subscript store requires a concrete key; "
                f"owner=DictValue.setitem site={site}",
                **runtime_effect_evidence("py.setitem", index, site),
            )
        )

    def delitem(self, index, site):
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        if type(index) is StringValue or type(index) is TermValue:
            for position, (key, _value) in enumerate(self.entries):
                if type(key) is type(index) and key.value == index.value:
                    return Complete(
                        DictValue(
                            (
                                *self.entries[:position],
                                *self.entries[position + 1 :],
                            )
                        )
                    )
            from sugar_lift_py_tests.effect import (
                KeyErrorRuntimeEffect,
                runtime_effect_evidence,
            )

            return Incomplete(
                KeyErrorRuntimeEffect(
                    "dict deletion key missing runtime boundary: "
                    f"key={index!r}; owner=DictValue.delitem site={site}",
                    **runtime_effect_evidence("py.delitem", index, site),
                )
            )

        from sugar_lift_py_tests.effect import (
            SubscriptStoreRuntimeEffect,
            runtime_effect_evidence,
        )

        return Incomplete(
            SubscriptStoreRuntimeEffect(
                "dict subscript delete requires a concrete key; "
                f"owner=DictValue.delitem site={site}",
                **runtime_effect_evidence("py.delitem", index, site),
            )
        )

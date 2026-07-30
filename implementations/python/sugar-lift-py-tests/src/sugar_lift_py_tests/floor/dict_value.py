from __future__ import annotations

from dataclasses import dataclass

from .guard_stable_value import GuardStableValue


@dataclass(frozen=True)
class DictValue(GuardStableValue):
    """A dict of reduced (key, value) floor pairs, in source order.

    The sugar reduces each key and each value; the floor holds what those
    reductions were. No methods beyond the dataclass and the subscript floor --
    floors this dict does not implement panic for free via FloorValue defaults.
    """

    entries: tuple

    def mapping_entries(self) -> tuple:
        return self.entries

    def mapping_with_entries(self, entries: tuple) -> "DictValue":
        return DictValue(entries)

    def denotes_value(self) -> bool:
        """This floor value denotes a ``dict``."""
        return True

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

    def iter_with(self, operation, ctx):
        """``iter(dict)`` traverses authenticated keys in insertion order."""
        del operation, ctx
        from sugar_lift_py_tests.floor.iterator_value import ListIteratorValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            ListIteratorValue(tuple(key for key, _value in self.entries), index=0)
        )

    def slice_assign_iterable_with(self, operation, ctx):
        """Project insertion-ordered authenticated keys for slice assignment."""
        del operation, ctx
        from sugar_lift_py_tests.outcome import Complete

        return Complete(tuple(key for key, _value in self.entries))

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

    def call_method_value(
        self,
        name,
        arguments,
        *,
        owner,
        blame,
        ctx=None,
        keywords=(),
        required_frame=None,
    ):
        """Execute closed dict methods whose result is fixed by this value."""
        del owner, ctx
        if (
            name == "items"
            and not arguments
            and not keywords
            and required_frame is None
        ):
            from sugar_lift_py_tests.floor.tuple_value import TupleValue
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
                TupleValue(
                    tuple(TupleValue((key, value)) for key, value in self.entries)
                )
            )
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            owner="DictValue.call_method_value",
            blame=blame,
            observed=f"dict.{name}",
            requested="closed source-visible dict method semantics",
            fix="implement the exact dict method floor or keep the call loud",
        )

    def supports_closed_method(self, name: str) -> bool:
        return name == "items"

    def setattr(self, name, value, site):
        """Dicts have no instance ``__dict__``; store is AttributeError."""
        del name, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="DictValue.setattr"
        )

    def delattr(self, name, site):
        """Dicts have no instance ``__dict__``; delete is AttributeError."""
        del name
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="DictValue.delattr"
        )

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
        # Source-decided unhashable keys are TypeError. An index whose
        # hash/eq semantics are not source-decided stays the named refusal.
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.set_value import SetValue
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete

        if type(index) in (ListValue, DictValue, SetValue):
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="TypeError",
                site=site,
                owner="DictValue.subscript",
            )

        concrete = type(index) is StringValue or type(index) is TermValue
        if concrete:
            for key, value in self.entries:
                if type(key) is type(index):
                    if type(key) is StringValue and key.value == index.value:
                        return Complete(value)
                    if type(key) is TermValue and key.value == index.value:
                        return Complete(value)
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="KeyError",
                site=site,
                owner="DictValue.subscript",
            )
        return self.undecided_subscript(index, site, owner="DictValue.subscript")

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
            # Ground missing key: decidable KeyError — not a RuntimeEffect mint.
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="KeyError",
                site=site,
                owner="DictValue.delitem",
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

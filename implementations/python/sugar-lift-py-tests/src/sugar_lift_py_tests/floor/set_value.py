from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.call_symbol import call_symbol

from .guard_stable_value import GuardStableValue


@dataclass(frozen=True)
class SetValue(GuardStableValue):
    """A set of reduced floor values, in construction order.

    The sugar reduces each element; the floor holds what those reductions were.
    No methods beyond the dataclass -- floors this set does not implement panic
    for free via FloorValue defaults.
    """

    elements: tuple

    def attribute(self, name, site):
        # Bound methods and fields on a constructed set (``set().add``, ``s.union``) stay the
        # py.getattr coordinate -- one law, shared with StringValue and the
        # other constructed containers. Never invent a method body or a field.
        del site
        from sugar_lift_py_tests.floor.getattr_coordinate import getattr_coordinate

        return getattr_coordinate(self, name, owner="SetValue.attribute")

    def setattr(self, name, value, site):
        """Sets have no instance ``__dict__``; store is AttributeError."""
        del name, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="SetValue.setattr"
        )

    def delattr(self, name, site):
        """Sets have no instance ``__dict__``; delete is AttributeError."""
        del name
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="SetValue.delattr"
        )

    def denotes_value(self) -> bool:
        """This floor value denotes a ``set``."""
        return True

    def is_identical(self, other, site):
        """Object identity, never value equality (``object_identity``)."""
        from .object_identity import mutable_object_identity

        return mutable_object_identity(self, other, site)

    def python_index_protocol(self) -> bool:
        return False

    def subscript(self, index, site):
        """Sets are never subscriptable: exact ground TypeError."""
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="SetValue.subscript",
        )

    def setitem(self, index, value, site):
        """Sets reject subscript store with exact TypeError."""
        del index, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="SetValue.setitem"
        )

    def delitem(self, index, site):
        """Sets reject subscript delete with exact TypeError."""
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="SetValue.delitem"
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:set",
            [element.to_term(owner=owner) for element in self.elements],
        )

    def truth(self, site):
        # A set's truth is nonempty.
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return ExitSet.completed(
            TrueBoolLiteralSugar(site=site)
            if self.elements
            else FalseBoolLiteralSugar(site=site)
        )

    def length(self, site):
        # A set knows its length when its members are decidedly distinct;
        # members whose equality is undecided may have collapsed.
        from sugar_lift_py_tests.floor.membership import decided_distinct
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import ExitSet

        if not decided_distinct(self.elements):
            return undecided_length(self, site)
        return ExitSet.completed(TermValue(len(self.elements)))

    def slice_assign_iterable_with(self, operation, ctx):
        """Keep runtime set iteration order loud; construction order is not it."""
        del ctx
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="SetValue.slice_assign_iterable_with",
            blame=operation.blame,
            observed=(
                "constructed SetValue members carry construction order, not "
                "authenticated Python set iteration order"
            ),
            requested="finite RHS members in authenticated runtime iteration order",
            fix=(
                "carry producer-owned set iteration-order testimony into SetValue, "
                "then project exactly that order through this Floor door"
            ),
        )

    def contains(self, item, site):
        # A guarded needle is not one needle: distribute into its faces and
        # rejoin under the same guard before this receiver's own law runs.
        from sugar_lift_py_tests.floor.guarded_operand import (
            distribute_guarded_predicate,
        )

        distributed = distribute_guarded_predicate(self, item, "contains", site)
        if distributed is not None:
            return distributed
        from sugar_lift_py_tests.floor.membership import membership

        decided = membership(
            self,
            item,
            self.elements,
            kind="set",
            member_role="member",
            container_role="set",
            hashed=True,
            site=site,
        )
        if decided is not None:
            return decided
        return _unsupported_member(item, site)

    def subtract(self, other, site):
        if type(other) is SetValue:
            from sugar_lift_py_tests.outcome import ExitSet

            result = _finite_difference(self.elements, other.elements)
            if result is not None:
                return ExitSet.completed(SetValue(result))
            return _symbolic_set_operation("python.set.difference", self, other, site)
        return super().subtract(other, site)

    def bitwise_or(self, other, site):
        if type(other) is SetValue:
            from sugar_lift_py_tests.outcome import ExitSet

            result = _finite_union(self.elements, other.elements)
            if result is not None:
                return ExitSet.completed(SetValue(result))
            return _symbolic_set_operation("python.set.union", self, other, site)
        return super().bitwise_or(other, site)

    def bitwise_and(self, other, site):
        if type(other) is SetValue:
            from sugar_lift_py_tests.outcome import ExitSet

            result = _finite_intersection(self.elements, other.elements)
            if result is not None:
                return ExitSet.completed(SetValue(result))
            return _symbolic_set_operation("python.set.intersection", self, other, site)
        return super().bitwise_and(other, site)


def undecided_length(container, site):
    """``len(container)`` as the ``call:len`` coordinate: never a count."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import ExitSet

    owner = str(site)
    return ExitSet.completed(
        CallSiteValue(
            target_name="len",
            arg_values=(container,),
            parameters=(),
            term=ctor(
                call_symbol("len"),
                (container.to_term(owner=owner),),
                symbol_kind="builtin",
            ),
            body=None,
            site=site,
        )
    )


def _closed_member_equal(left, right):
    """Membership equality: one law, ``floor/membership.py``."""
    from sugar_lift_py_tests.floor.membership import member_equal

    return member_equal(left, right)


def _closed_sequence_equal(left_elements, right_elements):
    from sugar_lift_py_tests.floor.membership import sequence_equal

    return sequence_equal(left_elements, right_elements)


def _denotes_a_value(value, supported: tuple) -> bool:
    """Whether one side of a membership test denotes a value at all.

    The decidable literal carriers denote values by construction -- they were
    already answered above, and only appear here as the OTHER side of an
    undecided pair. Everything else has to say so itself.
    """
    if type(value) in supported:
        return True
    testimony = getattr(type(value), "denotes_a_value", None)
    return bool(testimony(value)) if testimony is not None else False


def _finite_union(left, right):
    result = list(left)
    for candidate in right:
        decisions = tuple(_closed_member_equal(candidate, item) for item in result)
        if any(decision is True for decision in decisions):
            continue
        if any(decision in (None, NotImplemented) for decision in decisions):
            return None
        result.append(candidate)
    return tuple(result)


def _finite_intersection(left, right):
    result = []
    for candidate in left:
        decisions = tuple(_closed_member_equal(candidate, item) for item in right)
        if any(decision is True for decision in decisions):
            result.append(candidate)
        elif any(decision in (None, NotImplemented) for decision in decisions):
            return None
    return tuple(result)


def _finite_difference(left, right):
    result = []
    for candidate in left:
        decisions = tuple(_closed_member_equal(candidate, item) for item in right)
        if any(decision is True for decision in decisions):
            continue
        if any(decision in (None, NotImplemented) for decision in decisions):
            return None
        result.append(candidate)
    return tuple(result)


def _symbolic_set_operation(name, left, right, site):
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import ExitSet

    return ExitSet.completed(
        SymbolicValue(
            ctor(
                name,
                [left.to_term(owner=str(site)), right.to_term(owner=str(site))],
            )
        )
    )


def _bool_result(value, site):
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    return ExitSet.completed(
        TrueBoolLiteralSugar(site=site) if value else FalseBoolLiteralSugar(site=site)
    )


def _unsupported_member(item, site):
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner="SetValue.contains",
        blame=str(site),
        observed=type(item).__name__,
        requested="constructed finite member or typed symbolic membership operand",
        fix="construct member equality on the Python floor or keep it loud",
    )

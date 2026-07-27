from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class SetValue(FloorValue):
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

    def denotes_value(self) -> bool:
        """This floor value denotes a ``set``."""
        return True

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

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:set",
            [element.to_term(owner=owner) for element in self.elements],
        )

    def truth(self, site):
        # A set's truth is nonempty.
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(
            TrueBoolLiteralSugar(site=site)
            if self.elements
            else FalseBoolLiteralSugar(site=site)
        )

    def length(self, site):
        # A set knows its length: the count of reduced elements.
        del site
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(TermValue(len(self.elements)))

    def contains(self, item, site):
        # A guarded needle is not one needle: distribute into its faces and
        # rejoin under the same guard before this receiver's own law runs.
        from sugar_lift_py_tests.floor.guarded_operand import (
            distribute_guarded_predicate,
        )

        distributed = distribute_guarded_predicate(self, item, "contains", site)
        if distributed is not None:
            return distributed
        decisions = tuple(
            _closed_member_equal(item, element) for element in self.elements
        )
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
                        "python.set.contains",
                        [
                            item.to_term(owner="python.set.contains member"),
                            self.to_term(owner="python.set.contains set"),
                        ],
                    ),
                    site,
                    operand_callsites=(*item.callsites(), *self.callsites()),
                )
            )
        return _unsupported_member(item, site)

    def subtract(self, other, site):
        if type(other) is SetValue:
            from sugar_lift_py_tests.outcome import Complete

            result = _finite_difference(self.elements, other.elements)
            if result is not None:
                return Complete(SetValue(result))
            return _symbolic_set_operation("python.set.difference", self, other, site)
        return super().subtract(other, site)

    def bitwise_or(self, other, site):
        if type(other) is SetValue:
            from sugar_lift_py_tests.outcome import Complete

            result = _finite_union(self.elements, other.elements)
            if result is not None:
                return Complete(SetValue(result))
            return _symbolic_set_operation("python.set.union", self, other, site)
        return super().bitwise_or(other, site)

    def bitwise_and(self, other, site):
        if type(other) is SetValue:
            from sugar_lift_py_tests.outcome import Complete

            result = _finite_intersection(self.elements, other.elements)
            if result is not None:
                return Complete(SetValue(result))
            return _symbolic_set_operation("python.set.intersection", self, other, site)
        return super().bitwise_and(other, site)


def _closed_member_equal(left, right):
    from sugar_lift_py_tests.floor.bytes_value import BytesValue
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    if type(left) is SymbolicValue or type(right) is SymbolicValue:
        return None
    if type(left) is TermValue and type(right) is TermValue:
        return left.value == right.value
    if type(left) is StringValue and type(right) is StringValue:
        return left.value == right.value
    if type(left) is BytesValue and type(right) is BytesValue:
        return left.value == right.value
    if type(left) is NoneValue or type(right) is NoneValue:
        return type(left) is type(right)
    bool_types = (TrueBoolLiteralSugar, FalseBoolLiteralSugar)
    if type(left) in bool_types and type(right) in bool_types:
        return type(left) is type(right)
    supported = (TermValue, StringValue, BytesValue, NoneValue, *bool_types)
    if type(left) in supported and type(right) in supported:
        return False
    # A residual pair measured on the installed pandas tree lands here:
    # `{List,Tuple,Set}Value.contains x CallSiteValue`. A call's result IS a
    # value of undecided identity, so the honest answer is ``None`` (emit the
    # typed python.*.contains obligation), not NotImplemented (a gap). What it
    # is NOT is "any value carrying a term": FunctionCallable carries one and is
    # a callable, never a member -- two tests pin that refusal deliberately. So
    # the discriminator is ``FloorValue.denotes_a_value``, testimony each floor
    # states about ITSELF and which defaults to no, never a property a caller
    # reads off the carrier's shape.
    if _denotes_a_value(left, supported) and _denotes_a_value(right, supported):
        return None
    return NotImplemented


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
    from sugar_lift_py_tests.outcome import Complete

    return Complete(
        SymbolicValue(
            ctor(
                name,
                [left.to_term(owner=str(site)), right.to_term(owner=str(site))],
            )
        )
    )


def _bool_result(value, site):
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    return Complete(
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

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from .guard_stable_value import GuardStableValue


@dataclass(frozen=True)
class TupleValue(GuardStableValue):
    """A tuple of reduced floor values, in construction order.

    The sugar reduces each element; the floor holds what those reductions were.
    No methods beyond the dataclass -- floors this tuple does not implement panic
    for free via FloorValue defaults.
    """

    elements: tuple
    # The display that made this object in the frame reading it, where
    # CPython builds it at runtime (``TupleSugar``); None for every other
    # tuple -- one that arrived, one a builtin or an operator made, one the
    # compiler may fold into a shared constant.  It answers ``is`` only
    # (``object_identity``): a tuple's contents never change.
    allocation: str | None = dataclass_field(
        default=None,
        kw_only=True,
        compare=False,
        metadata={"testimony": "provenance"},
    )

    def match_raise_effect(self, effect):
        """Tuple classinfo is disjunction of its members' subtype predicates.

        Python's isinstance/issubclass classinfo rule (also used by exception
        handlers and pytest.raises) accepts any member, not the tuple as a
        single type: https://docs.python.org/3/library/functions.html#issubclass
        Open members retain their predicates; no open edge is assumed false.
        """
        from sugar_lift_py_tests.authenticated_exception_matching import (
            MatchDecided,
            MatchRetained,
            matches_raise_effect,
        )
        from sugar_lift_py_tests.ir import or_

        retained = []
        for element in self.elements:
            verdict = matches_raise_effect(effect, element)
            if isinstance(verdict, MatchDecided):
                if verdict.value:
                    return verdict
            else:
                retained.append(verdict.obligation)
        if retained:
            return MatchRetained(retained[0] if len(retained) == 1 else or_(retained))
        return MatchDecided(False)

    def denotes_value(self) -> bool:
        """This floor value denotes a ``tuple``."""
        return True

    def python_index_protocol(self) -> bool:
        return False

    def attribute(self, name, site, ctx):
        # Bound methods and fields on a constructed tuple (``().count``, ``t.index``) stay the
        # py.getattr coordinate -- one law, shared with StringValue and the
        # other constructed containers. Never invent a method body or a field.
        del site, ctx
        from sugar_lift_py_tests.floor.getattr_coordinate import getattr_coordinate

        return getattr_coordinate(self, name, owner="TupleValue.attribute")

    def to_term(self, *, owner: str):
        # Project each element; vendor digs return tuples (sign/unsign pairs,
        # return_timestamp) that must enter FOL for assert equality.
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "tuple",
            [elt.to_term(owner=owner) for elt in self.elements],
        )

    def truth(self, site):
        # A tuple's truth is nonempty.
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

    def python_isinstance(self, type_name: str, type_term, site):
        """A constructed tuple is exactly an instance of ``tuple`` / ``object``.

        Dispatch reads the authenticated ``type_term`` coordinate. Display
        ``type_name`` is never authority.
        """
        from sugar_lift_py_tests.floor.python_type_coordinate import (
            authenticated_python_type_spelling,
        )
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        del type_name
        authenticated = authenticated_python_type_spelling(
            type_term, owner="TupleValue.python_isinstance", site=site
        )
        if authenticated in {"tuple", "object"}:
            return ExitSet.completed(TrueBoolLiteralSugar(site=site))
        if authenticated in {
            "list",
            "dict",
            "set",
            "frozenset",
            "str",
            "bytes",
            "int",
            "bool",
            "float",
            "type",
            "NoneType",
        }:
            return ExitSet.completed(FalseBoolLiteralSugar(site=site))
        return super().python_isinstance(authenticated, type_term, site)

    def length(self, site):
        # A tuple knows its length: the count of reduced elements.
        del site
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(TermValue(len(self.elements)))

    def project_sequence_with(self, operation, ctx):
        """Unpack against authenticated reduced members already in hand.

        ``TupleValue.elements`` is the finite member testimony from construction;
        SequenceProjectionOperation binds names only when arity matches.
        """
        return operation.project_tuple(self, ctx)

    def iter_with(self, operation, ctx):
        """``iter(tuple)`` → authenticated ``TupleIteratorValue`` over members."""
        del operation, ctx
        from sugar_lift_py_tests.floor.iterator_value import TupleIteratorValue
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(TupleIteratorValue(self.elements, index=0))

    def slice_assign_iterable_with(self, operation, ctx):
        """Authenticated finite members for list slice-assignment RHS."""
        del operation, ctx
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(self.elements)

    @property
    def items(self) -> tuple:
        """Member sequence for SequenceProjectionOperation.project_tuple."""
        return self.elements

    def contains(self, item, site):
        # A guarded needle is not one needle: distribute into its faces and
        # rejoin under the same guard before this receiver's own law runs.
        from sugar_lift_py_tests.floor.guarded_operand import (
            distribute_guarded_membership,
        )

        distributed = distribute_guarded_membership(self, item, site)
        if distributed is not None:
            return distributed
        from sugar_lift_py_tests.floor.membership import membership

        decided = membership(
            self,
            item,
            self.elements,
            kind="tuple",
            member_role="member",
            container_role="tuple",
            hashed=False,
            site=site,
        )
        if decided is not None:
            return decided
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="TupleValue.contains",
            blame=str(site),
            observed=type(item).__name__,
            requested="constructed finite member or typed symbolic membership operand",
            fix="construct member equality on the Python floor or keep it loud",
        )

    def add(self, other, site, ctx):
        if type(other) is TupleValue:
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(TupleValue((*self.elements, *other.elements)))
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if type(other) in (CallSiteValue, SymbolicValue):
            return SymbolicValue(self.to_term(owner=str(site))).add(other, site, ctx)
        if other.denotes_value() and other.runtime_type_is_decided():
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner="TupleValue.add")
        return super().add(other, site, ctx)

    def test_python_type(self, value, site):
        return self._collect_type_tests(value, site, 0, ())

    def test_python_subtype(self, subtype, site):
        return self._collect_subtype_tests(subtype, site, 0, ())

    def _collect_subtype_tests(self, subtype, site, index, predicates):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        if index >= len(self.elements):
            if not predicates:
                return ExitSet.completed(FalseBoolLiteralSugar(site=site))
            if len(predicates) == 1:
                return ExitSet.completed(predicates[0])
            from sugar_lift_py_tests.ir import or_

            return ExitSet.completed(
                PredicateValue(
                    or_([predicate.formula for predicate in predicates]), site
                )
            )
        return subtype.test_python_subtype(self.elements[index], site).and_then(
            lambda result: self._continue_subtype_test(
                subtype, site, index, predicates, result
            )
        )

    def _continue_subtype_test(self, subtype, site, index, predicates, result):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if type(result) is TrueBoolLiteralSugar:
            return ExitSet.completed(TrueBoolLiteralSugar(site=site))
        if type(result) is FalseBoolLiteralSugar:
            return self._collect_subtype_tests(subtype, site, index + 1, predicates)
        if type(result) is PredicateValue:
            return self._collect_subtype_tests(
                subtype, site, index + 1, (*predicates, result)
            )
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="TupleValue.test_python_subtype",
            blame=str(site),
            observed=type(result).__name__,
            requested="boolean or typed subtype obligation",
            fix="implement the tuple arm on the Python subtype floor",
        )

    def _collect_type_tests(self, value, site, index, predicates):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        if index >= len(self.elements):
            if not predicates:
                return ExitSet.completed(FalseBoolLiteralSugar(site=site))
            if len(predicates) == 1:
                return ExitSet.completed(predicates[0])
            from sugar_lift_py_tests.ir import or_

            return ExitSet.completed(
                PredicateValue(
                    or_([predicate.formula for predicate in predicates]),
                    site,
                    operand_callsites=tuple(
                        callsite
                        for predicate in predicates
                        for callsite in predicate.operand_callsites
                    ),
                )
            )

        return (
            self.elements[index]
            .test_python_type(value, site)
            .and_then(
                lambda result: self._continue_type_test(
                    value, site, index, predicates, result
                )
            )
        )

    def _continue_type_test(self, value, site, index, predicates, result):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if type(result) is TrueBoolLiteralSugar:
            return ExitSet.completed(TrueBoolLiteralSugar(site=site))
        if type(result) is FalseBoolLiteralSugar:
            return self._collect_type_tests(value, site, index + 1, predicates)
        if type(result) is PredicateValue:
            return self._collect_type_tests(
                value, site, index + 1, (*predicates, result)
            )

        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="TupleValue.test_python_type",
            blame=str(site),
            observed=type(result).__name__,
            requested="boolean result from per-element python:type tester",
            fix="implement the element's native python:type tester result",
        )

    def multiply(self, other, site, ctx):
        # Python tuple repetition, through the one sequence-repetition law.
        from sugar_lift_py_tests.floor.sequence_repetition import repeat_sequence

        return repeat_sequence(
            self, other, site, elements=self.elements, rebuild=TupleValue
        )

    def subscript(self, index, site):
        # Concrete tuple + ground slice/integer index is fully decided. A known
        # non-index is TypeError; undecided runtime semantics stay loud.
        from sugar_lift_py_tests.floor.slice_value import SliceValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import ExitSet

        if type(index) is SliceValue:
            bounds = (index.lower, index.upper, index.step)
            if all(
                bound is None or (type(bound) is TermValue and type(bound.value) is int)
                for bound in bounds
            ):
                lower, upper, step = (
                    bound.value if type(bound) is TermValue else None
                    for bound in bounds
                )
                if step == 0:
                    from sugar_lift_py_tests.floor.ground_exit import (
                        ground_exceptional_exit,
                    )

                    return ground_exceptional_exit(
                        exception_name="ValueError",
                        site=site,
                        owner="TupleValue.subscript",
                    )
                return ExitSet.completed(
                    TupleValue(tuple(self.elements[slice(lower, upper, step)]))
                )
            return self.undecided_subscript(index, site, owner="TupleValue.subscript")

        if type(index) is TermValue and isinstance(index.value, int):
            i = index.value
            n = len(self.elements)
            if -n <= i < n:
                return ExitSet.completed(self.elements[i])
            from sugar_lift_py_tests.floor.ground_index_error import (
                ground_index_error,
            )

            return ground_index_error(
                owner="TupleValue.subscript",
                operation="tuple subscript",
                index=i,
                length=n,
                site=site,
            )
        if index.python_index_protocol() is False:
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="TypeError", site=site, owner="TupleValue.subscript"
            )
        return self.undecided_subscript(index, site, owner="TupleValue.subscript")

    def setitem(self, index, value, site, ctx):
        del index, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="TupleValue.setitem"
        )

    def delitem(self, index, site, ctx):
        """Tuples are immutable: every subscript delete is exact TypeError."""
        del index, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="TupleValue.delitem"
        )

    def setattr(self, name, value, site, ctx):
        """Tuples have no ``__dict__``; attribute store is AttributeError."""
        del name, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="TupleValue.setattr"
        )

    def delattr(self, name, site, ctx):
        """Tuples have no ``__dict__``; attribute delete is AttributeError."""
        del name, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="TupleValue.delattr"
        )

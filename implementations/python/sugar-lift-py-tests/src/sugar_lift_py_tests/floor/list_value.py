from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace
from sugar_lift_py_tests.effect import runtime_effect_evidence

from .guard_stable_value import GuardStableValue
from .object_identity import UNNAMED_CONSTRUCTION


@dataclass(frozen=True)
class ListValue(GuardStableValue):
    """A list of reduced floor values.

    Order matters for a list -- the tuple already preserves it. The sugar reduces
    each element; the floor holds what those reductions were. No methods beyond
    the dataclass -- floors this list does not implement panic for free via
    FloorValue defaults.
    """

    elements: tuple
    # The construction that made this object in the frame reading it, kept
    # by the one door's post-state; None for a value that arrived by binding
    # (``object_identity``: ``made_at``, ``arrived``, ``contents_current``).
    # A value built without one was made here by a construction it does not
    # name (``UNNAMED_CONSTRUCTION``).
    allocation: str | None = dataclass_field(
        default=UNNAMED_CONSTRUCTION,
        compare=False,
        metadata={"testimony": "provenance"},
    )

    def denotes_value(self) -> bool:
        """This floor value denotes a ``list``."""
        return True

    def is_identical(self, other, site):
        """Object identity, never value equality (``object_identity``)."""
        from .object_identity import mutable_object_identity

        return mutable_object_identity(self, other, site)

    def python_index_protocol(self) -> bool:
        return False

    def attribute(self, name, site, ctx):
        # Bound methods and fields on a constructed list (``[].append``, ``xs.index``) stay the
        # py.getattr coordinate -- one law, shared with StringValue and the
        # other constructed containers. Never invent a method body or a field.
        del site, ctx
        from sugar_lift_py_tests.floor.getattr_coordinate import getattr_coordinate

        return getattr_coordinate(self, name, owner="ListValue.attribute")

    def setattr(self, name, value, site, ctx):
        """Lists have no instance ``__dict__``; attribute store is AttributeError.

        Distinct from the read path: ``xs.append`` may resolve as a bound method
        coordinate while ``xs.append = f`` still raises AttributeError.
        """
        del name, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="ListValue.setattr"
        )

    def delattr(self, name, site, ctx):
        """Lists have no instance ``__dict__``; delete is AttributeError."""
        del name, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="ListValue.delattr"
        )

    def to_term(self, *, owner: str):
        # Project elements into FOL — assert equality / dig return faces.
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "array",
            [elt.to_term(owner=owner) for elt in self.elements],
        )

    def truth(self, site):
        # A list's truth is nonempty -- of its contents now
        # (``object_identity.contents_current``); otherwise the undecided
        # truth (no halt, no debt: a builtin list's truth runs no code).
        from .object_identity import contents_current

        if not contents_current(self):
            return self.undecided_truth(site, owner="ListValue.truth")
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

    def project_sequence_with(self, operation, ctx):
        """Unpack against authenticated reduced members already in hand.

        A constructed list projects as ``array`` (``to_term``), so it takes the
        array arm. Routing it through ``project_tuple`` would print a tuple
        diagnostic for an arity mismatch on a list: a correct refusal wearing
        the wrong name.  A list whose contents are not current
        (``object_identity.contents_current``) has no members in hand: its
        count is the runtime unpack's.
        """
        from .object_identity import contents_current

        if not contents_current(self):
            return operation.project_symbolic(self, ctx)
        return operation.project_array(self, ctx)

    def iter_with(self, operation, ctx):
        """``iter(list)`` → authenticated ``ListIteratorValue`` over members;
        over contents that are not current, the undecided iteration."""
        from .object_identity import contents_current

        if not contents_current(self):
            return self.undecided_iteration(operation.blame, owner="ListValue.iter")
        del ctx
        from sugar_lift_py_tests.floor.iterator_value import ListIteratorValue
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(ListIteratorValue(self.elements, index=0))

    @property
    def items(self) -> tuple:
        """Member sequence for SequenceProjectionOperation.project_array."""
        return self.elements

    def length(self, site):
        # A list knows its length: the count of reduced elements -- when
        # they are its contents now (``object_identity.contents_current``).
        from .object_identity import contents_current

        if not contents_current(self):
            from .set_value import undecided_length

            return undecided_length(self, site)
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(TermValue(len(self.elements)))

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
            kind="list",
            member_role="member",
            container_role="list",
            hashed=False,
            site=site,
        )
        if decided is not None:
            return decided
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="ListValue.contains",
            blame=str(site),
            observed=type(item).__name__,
            requested="constructed finite member or typed symbolic membership operand",
            fix="construct member equality on the Python floor or keep it loud",
        )

    def append_with(self, value, site):
        # Concrete history folds: the updated list is the old elements plus the
        # new value. Symbolic receivers stay on the default panic.  The same
        # object: it keeps its ``allocation``.
        del site
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(replace(self, elements=(*self.elements, value)))

    def add(self, other, site, ctx):
        """Python list concatenation, or a cited coordinate for an opaque peer.

        The concatenation is a new list made here, current when both
        operands' contents are (``object_identity.made_if_current``)."""
        if type(other) is ListValue:
            from sugar_lift_py_tests.outcome import ExitSet

            from .object_identity import made_if_current

            return ExitSet.completed(
                ListValue(
                    (*self.elements, *other.elements),
                    allocation=made_if_current(site, self, other),
                )
            )
        from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue

        if type(other) is ComprehensionValue:
            # A constructed comprehension is already a sequence coordinate
            # (symbolic fold). Concatenate as another coordinate — never mint
            # RuntimeEffect over ComprehensionValue (that path required a
            # genuine runtime operand and rejected/faulted on py.listcomp
            # bodies carrying _Lambda before effect/runtime_effect admitted them).
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import ExitSet

            self_term = self.to_term(owner=str(site))
            return ExitSet.completed(
                ComprehensionValue(
                    ctor(
                        "+",
                        [
                            self_term,
                            other.term,
                        ],
                    )
                )
            )
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if type(other) in (CallSiteValue, SymbolicValue):
            return SymbolicValue(self.to_term(owner=str(site))).add(other, site, ctx)
        if other.denotes_value() and other.runtime_type_is_decided():
            # ``list + <decided non-list>`` is Python's TypeError.  Undecided
            # rights stay on the shared third-value law via super().
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner="ListValue.add")
        return super().add(other, site, ctx)

    def multiply(self, other, site, ctx):
        # Python list repetition, through the one sequence-repetition law: a
        # new list made here (``object_identity.made_if_current``).
        from sugar_lift_py_tests.floor.sequence_repetition import repeat_sequence

        from .object_identity import made_if_current

        allocation = made_if_current(site, self)

        def rebuild(elements):
            return ListValue(elements, allocation=allocation)

        return repeat_sequence(
            self, other, site, elements=self.elements, rebuild=rebuild
        )

    def subtract(self, other, site, ctx):
        """Lists never subtract: decided peers are TypeError."""
        if other.denotes_value() and other.runtime_type_is_decided():
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner="ListValue.subtract")
        return super().subtract(other, site, ctx)

    def floor_divide(self, other, site, ctx):
        if other.denotes_value() and other.runtime_type_is_decided():
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner="ListValue.floor_divide")
        return super().floor_divide(other, site, ctx)

    def matrix_multiply(self, other, site, ctx):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

        if type(other) is CallSiteValue and other.body is None:
            from sugar_lift_py_tests.effect import runtime_matrix_multiply

            return runtime_matrix_multiply(self, other, site)
        return super().matrix_multiply(other, site, ctx)

    def subscript(self, index, site):
        # Concrete list + integer index is fully decided. A known non-integer
        # is TypeError; an index with undecided runtime semantics stays loud.
        # A member or a slice is read only from contents that are current
        # (``object_identity.contents_current``); otherwise it is the
        # undecided read.
        from sugar_lift_py_tests.floor.slice_value import SliceValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import ExitSet

        from .object_identity import contents_current, made_at

        current = contents_current(self)
        if isinstance(index, SliceValue):
            bounds = (index.lower, index.upper, index.step)
            if _slice_bounds_not_indices(bounds):
                from sugar_lift_py_tests.floor.ground_exit import (
                    ground_exceptional_exit,
                )

                return ground_exceptional_exit(
                    exception_name="TypeError", site=site, owner="ListValue.delitem"
                )
            if _slice_bounds_ground(bounds):
                lower, upper, step = _slice_bound_ints(bounds)
                if step == 0:
                    from sugar_lift_py_tests.floor.ground_exit import (
                        ground_exceptional_exit,
                    )

                    return ground_exceptional_exit(
                        exception_name="ValueError",
                        site=site,
                        owner="ListValue.subscript",
                    )
                if current:
                    # A new list made here.
                    return ExitSet.completed(
                        ListValue(
                            tuple(self.elements[slice(lower, upper, step)]),
                            allocation=made_at(site),
                        )
                    )
            return self.undecided_subscript(index, site, owner="ListValue.subscript")

        if current and type(index) is TermValue and isinstance(index.value, int):
            i = index.value
            n = len(self.elements)
            if -n <= i < n:
                return ExitSet.completed(self.elements[i])
            from sugar_lift_py_tests.floor.ground_index_error import (
                ground_index_error,
            )

            return ground_index_error(
                owner="ListValue.subscript",
                operation="list subscript",
                index=i,
                length=n,
                site=site,
            )
        if index.python_index_protocol() is False:
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="TypeError", site=site, owner="ListValue.subscript"
            )
        return self.undecided_subscript(index, site, owner="ListValue.subscript")

    def setitem(self, index, value, site, ctx):
        # An index's bound is read only from contents that are current
        # (``object_identity.contents_current``), whichever caller reached
        # this store (the one door, an augmented store, a carrier's
        # discharge); otherwise it is the store's undecided form.
        from sugar_lift_py_tests.floor.slice_value import SliceValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import ExitSet

        from .object_identity import contents_current

        if isinstance(index, SliceValue):
            return self._setitem_slice(index, value, site, ctx)

        if type(index) is TermValue and type(index.value) is int:
            if not contents_current(self):
                return stale_item_mutation(site, "__setitem__", "ListValue.setitem")
            i = index.value
            n = len(self.elements)
            if -n <= i < n:
                resolved = i if i >= 0 else n + i
                updated = (
                    *self.elements[:resolved],
                    value,
                    *self.elements[resolved + 1 :],
                )
                # The same object: it keeps its ``allocation``.
                return ExitSet.completed(replace(self, elements=updated))
            from sugar_lift_py_tests.floor.ground_index_error import (
                ground_index_error,
            )

            return ground_index_error(
                owner="ListValue.setitem",
                operation="list assignment",
                index=i,
                length=n,
                site=site,
            )
        from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect
        from sugar_lift_py_tests.floor.store_outcome_coordinate import store_faces

        return store_faces(
            SubscriptStoreRuntimeEffect(
                "list subscript store requires a concrete integer index or "
                "ground SliceValue; "
                f"owner=ListValue.setitem site={site}",
                **runtime_effect_evidence("py.setitem", index, site),
            )
        )

    def _setitem_slice(self, index, value, site, ctx):
        """Python list slice assignment: ``xs[lo:hi:st] = iterable``.

        Ground integer (or omitted) bounds only — same decidability law as
        ``delitem`` over SliceValue.  RHS materializes through the Floor-owned
        ``SliceAssignIterableOperation`` door (exact containers answer;
        decided non-iterables TypeError; unresolved iterability stays loud).
        """
        from sugar_lift_py_tests.operations.slice_assign_iterable_operation import (
            SliceAssignIterableOperation,
        )
        from sugar_lift_py_tests.outcome import ExitSet

        from .object_identity import contents_current

        bounds = (index.lower, index.upper, index.step)
        if _slice_bounds_not_indices(bounds):
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="TypeError", site=site, owner="ListValue.setitem"
            )
        if not _slice_bounds_ground(bounds):
            from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect
            from sugar_lift_py_tests.floor.store_outcome_coordinate import (
                store_faces,
            )

            return store_faces(
                SubscriptStoreRuntimeEffect(
                    "list slice assignment depends on runtime slice bounds; "
                    f"owner=ListValue.setitem site={site}",
                    **runtime_effect_evidence("py.setitem", index, site),
                )
            )
        lower, upper, step = _slice_bound_ints(bounds)
        if step == 0:
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="ValueError",
                site=site,
                owner="ListValue.setitem",
            )

        # The RHS materializes under the store statement's context.
        members_out = SliceAssignIterableOperation(
            owner="ListValue.setitem",
            blame=site,
        ).submit(value, ctx)

        # A decided TypeError is a halt: it never reaches the write step.
        if members_out.halts() == members_out.exits:
            return members_out

        def _write(members):
            if not isinstance(members, (tuple, list)):
                # An undecided RHS: the store's own completed face, whose
                # members no lift-time value names (its halted face is the
                # sibling arm) -- a ``RuntimeEffectTestimony``, or the
                # receiver after the store (``stale_item_mutation``) when the
                # RHS's contents are not current.
                return ExitSet.completed(members)
            if not contents_current(self):
                # The receiver's contents are not current: which positions the
                # slice covers (and an extended slice's length check) is not
                # read from them.
                return stale_item_mutation(site, "__setitem__", "ListValue.setitem")
            elements = list(self.elements)
            try:
                elements[slice(lower, upper, step)] = list(members)
            except ValueError:
                from sugar_lift_py_tests.floor.ground_exit import (
                    ground_exceptional_exit,
                )

                # Extended-slice length mismatch is Python's ValueError.
                return ground_exceptional_exit(
                    exception_name="ValueError",
                    site=site,
                    owner="ListValue.setitem",
                )
            return ExitSet.completed(replace(self, elements=tuple(elements)))

        return members_out.and_then(_write)

    def slice_assign_iterable_with(self, operation, ctx):
        """Authenticated finite members for slice-assignment RHS -- the
        list's contents now (``object_identity.contents_current``).  Otherwise
        no members are in hand: the store is the undecided item mutation
        (``stale_item_mutation``), the receiver after it unknown."""
        del ctx
        from .object_identity import contents_current

        if not contents_current(self):
            return stale_item_mutation(operation.blame, "__setitem__", operation.owner)
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(self.elements)

    def delitem(self, index, site, ctx):
        # Which members go is read only from contents that are current
        # (``object_identity.contents_current``), whichever caller reached
        # this delete; otherwise it is the delete's undecided form.
        del ctx
        from sugar_lift_py_tests.floor.slice_value import SliceValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import ExitSet

        from .object_identity import contents_current

        current = contents_current(self)
        if isinstance(index, SliceValue):
            bounds = (index.lower, index.upper, index.step)
            if _slice_bounds_not_indices(bounds):
                from sugar_lift_py_tests.floor.ground_exit import (
                    ground_exceptional_exit,
                )

                return ground_exceptional_exit(
                    exception_name="TypeError", site=site, owner="ListValue.delitem"
                )
            if _slice_bounds_ground(bounds):
                lower, upper, step = _slice_bound_ints(bounds)
                if step == 0:
                    from sugar_lift_py_tests.floor.ground_exit import (
                        ground_exceptional_exit,
                    )

                    return ground_exceptional_exit(
                        exception_name="ValueError",
                        site=site,
                        owner="ListValue.delitem",
                    )
                if not current:
                    return stale_item_mutation(
                        site, "__delitem__", "ListValue.delitem"
                    )
                selected = set(range(len(self.elements))[slice(lower, upper, step)])
                return ExitSet.completed(
                    replace(
                        self,
                        elements=tuple(
                            value
                            for position, value in enumerate(self.elements)
                            if position not in selected
                        ),
                    )
                )
            from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect
            from sugar_lift_py_tests.floor.store_outcome_coordinate import (
                store_faces,
            )

            return store_faces(
                SubscriptStoreRuntimeEffect(
                    "list slice deletion depends on runtime slice bounds; "
                    f"owner=ListValue.delitem site={site}",
                    **runtime_effect_evidence("py.delitem", index, site),
                )
            )

        if type(index) is TermValue and type(index.value) is int:
            if not current:
                return stale_item_mutation(site, "__delitem__", "ListValue.delitem")
            i = index.value
            n = len(self.elements)
            if -n <= i < n:
                resolved = i if i >= 0 else n + i
                return ExitSet.completed(
                    replace(
                        self,
                        elements=(
                            *self.elements[:resolved],
                            *self.elements[resolved + 1 :],
                        ),
                    )
                )
            from sugar_lift_py_tests.floor.ground_index_error import (
                ground_index_error,
            )

            return ground_index_error(
                owner="ListValue.delitem",
                operation="list deletion",
                index=i,
                length=n,
                site=site,
            )
        from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect
        from sugar_lift_py_tests.floor.store_outcome_coordinate import store_faces

        return store_faces(
            SubscriptStoreRuntimeEffect(
                "list subscript delete requires a concrete integer index; "
                f"owner=ListValue.delitem site={site}",
                **runtime_effect_evidence("py.delitem", index, site),
            )
        )


def stale_item_mutation(site, method: str, owner: str):
    """``r[k] = v`` / ``del r[k]`` / ``r[a:b] = xs`` that would read a
    ``list``/``dict``'s contents that are not current
    (``object_identity.contents_current``): an index's bound, a key's
    presence, a slice's span, or the members of a stale right-hand side.

    The undecided item mutation (``undecided_item_mutation_faces``): it
    completes, leaving the receiver after it unknown, only under its
    site-keyed completes atom, and halts with an undetermined raise under the
    complement.  No ``IndexError``/``KeyError``/``ValueError`` is decided
    from contents the object may no longer hold, and none is dropped.  Every
    reader reaches it, inside the one door or outside it (an augmented
    store, a caller's discharge of a formal's store)."""
    from sugar_lift_py_tests.sugar.store_effect_sugar import (
        undecided_item_mutation_faces,
    )

    noun = "delitem" if method == "__delitem__" else "setitem"
    return undecided_item_mutation_faces(site, noun=noun, method=method, owner=owner)


def _slice_bound_omitted(bound) -> bool:
    """``r[:k]`` and ``r[None:k]`` alike: CPython reads ``None`` as omitted."""
    from sugar_lift_py_tests.floor.none_value import NoneValue

    return bound is None or type(bound) is NoneValue


def _slice_bounds_ground(bounds) -> bool:
    """Every bound is omitted or a ground integer (``bool`` is one)."""
    from sugar_lift_py_tests.floor.term_value import TermValue

    return all(
        _slice_bound_omitted(bound)
        or (type(bound) is TermValue and isinstance(bound.value, int))
        for bound in bounds
    )


def _slice_bound_ints(bounds):
    return tuple(
        None if _slice_bound_omitted(bound) else int(bound.value) for bound in bounds
    )


def _slice_bounds_not_indices(bounds) -> bool:
    """A bound whose decided type has no ``__index__`` (``r[1:'a']``): CPython's
    ``TypeError: slice indices must be integers or None``."""
    return any(
        not _slice_bound_omitted(bound) and bound.python_index_protocol() is False
        for bound in bounds
    )

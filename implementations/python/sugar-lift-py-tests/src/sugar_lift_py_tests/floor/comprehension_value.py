from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.call_symbol import call_symbol

from .guard_stable_value import GuardStableValue


def _is_set_coordinate(term) -> bool:
    return getattr(term, "name", None) in {
        "py.setcomp",
        "py.set_difference",
        "py.set_union",
    }


@dataclass(frozen=True)
class ComprehensionValue(GuardStableValue):
    """A native comprehension coordinate with no invented cardinality.

    Finite literal comprehensions reduce to concrete collection floors. All
    other comprehensions retain their constructor term, but ``length`` stays on
    FloorValue's loud missing arm until cardinality semantics are constructed.
    ``finite_elements`` is present only when the comprehension owner projected
    every member of an exact finite iterable; ``None`` means no such testimony
    exists and must never be treated as an empty collection.

    ``term`` is the comprehension's own coordinate at its evaluation,
    ``<kind>(<occurrence>, <evaluation key>)``
    (``ComprehensionSugar._own_coordinate``), finite or not: what every
    reader of its kind reads.  ``display`` is the list or set a comprehension
    whose every member is in hand built (``ComprehensionSugar._run_in_hand``):
    decided whole, it is what the proof states for it (``to_term``), never
    the coordinate.  A generator has none: it is never consumed where it is
    made, and states its coordinate.
    """

    term: object
    finite_elements: tuple | None = None
    display: object = field(default=None, compare=False)

    def denotes_value(self) -> bool:
        """A constructed fold denotes the sequence it builds.

        Its runtime TYPE is decided -- the fold constructor names whether
        it is a list, set, or dict comprehension -- so this value alone
        never makes a pair undecided. Only an undecided right operand does.
        """
        return True

    def to_term(self, *, owner: str):
        """What the proof states for this value: the display a decided list
        or set built (``display``), else its own coordinate."""
        if self.display is not None:
            return self.display.to_term(owner=owner)
        return self.term

    def length(self, site):
        """Project length only for the authenticated list-comprehension ctor."""
        from sugar_lift_py_tests.ir import _Ctor

        if type(self.term) is not _Ctor or self.term.name != "py.listcomp":
            return super().length(site)

        from sugar_lift_py_tests.outcome import ExitSet

        if self.finite_elements is not None:
            from sugar_lift_py_tests.floor.term_value import TermValue

            return ExitSet.completed(TermValue(len(self.finite_elements)))

        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor

        return ExitSet.completed(
            CallSiteValue(
                target_name="len",
                arg_values=(self,),
                parameters=(),
                term=ctor(call_symbol("len"), (self.term,), symbol_kind="builtin"),
                body=None,
                site=site,
            )
        )

    def slice_assign_iterable_with(self, operation, ctx):
        """``xs[lo:hi] = (x for x in ...)``: a comprehension is iterable.

        A list comprehension or generator with every member projected answers
        with those members, in order. Anything else (a set/dict comprehension,
        whose iteration order or members are not testified, or no finite
        testimony) is an undecided RHS -- never ``TypeError``: the store is the
        one undecided item mutation, the receiver after it unknown."""
        del ctx
        from sugar_lift_py_tests.ir import _Ctor
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.store_effect_sugar import (
            undecided_item_mutation_faces,
        )

        name = self.term.name if type(self.term) is _Ctor else None
        ordered = ("py.listcomp", "py.generatorexp")
        if self.finite_elements is not None and name in ordered:
            return ExitSet.completed(tuple(self.finite_elements))
        # The order a set's members are assigned in is not testified.
        return undecided_item_mutation_faces(
            operation.blame, method="__setitem__", owner=operation.owner
        )

    def project_sequence_with(self, operation, ctx):
        """`a, b = <comprehension>` -- the comprehension owns the cardinality.

        It answers from `finite_elements` when its owner projected every member
        of an exact finite iterable, and otherwise retains the arity demand. The
        operation reads the testimony; this face only routes to it.
        """
        return operation.project_comprehension(self, ctx)

    def contains(self, item, site):
        """``item in <comprehension>``, by the one membership law (#7757 H10).

        A list or set decided whole (``display``) is that display's
        membership, as its truth, ``==``, ``+`` and subscript are.  A
        generator whose every member is in hand (``finite_elements``, no
        display) is iterated in order, as a list compares: the one
        ``floor.membership``, decided where every comparison it makes is,
        else the undecided membership.  A comprehension whose members are not
        in hand is the floor's one undecided membership
        (``FloorValue.undecided_contains``): its members' ``__eq__`` (and a
        set's ``__hash__``) may raise, so it is two-faced, the halt kept,
        owed -- never a bare ``py.in``."""
        if self.display is not None:
            return self.display.contains(item, site)
        if self.finite_elements is not None:
            from sugar_lift_py_tests.floor.guarded_operand import (
                distribute_guarded_membership,
            )

            distributed = distribute_guarded_membership(self, item, site)
            if distributed is not None:
                return distributed
            from sugar_lift_py_tests.floor.membership import membership

            hashed = _is_set_coordinate(self.term)
            return membership(
                self,
                item,
                self.finite_elements,
                kind="set" if hashed else "generator",
                hashed=hashed,
                site=site,
            )
        return self.undecided_contains(item, site, owner="ComprehensionValue.contains")

    def truth(self, site):
        """Opaque comprehensions stand as conditions via ``py.truthy``.

        Finite literal comprehensions fold to concrete collection floors before
        truth is asked. A residual comprehension keeps its constructor term and
        emits the same truthy atom as other opaque coordinates — never invent
        emptiness, never panic for a lawful ``if history:`` face.  A list or
        set decided whole (``display``) is that display's truth.
        """
        if self.display is not None:
            return self.display.truth(site)
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            PredicateValue(py_truthy(self.term), site, operand_callsites=())
        )

    def equals(self, other, site, ctx):
        """A list or set decided whole (``display``) compares as that display
        (``ListValue.equals``: member by member wherever every pair it reads
        is decided), as its truth, ``+`` and ``*`` are that display's; any
        other comprehension is the one undecided equality over its own
        coordinate (``FloorValue.equals``)."""
        if self.display is not None:
            return self.display.equals(other, site, ctx)
        return super().equals(other, site, ctx)

    def add(self, other, site, ctx):
        if self.display is not None:
            # A list decided whole adds as the list it is.
            return self.display.add(other, site, ctx)
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import ExitSet

        if type(other) in (ComprehensionValue, ListValue):
            # Symbolic folds are constructed coordinates. Sequence concat of two
            # such coordinates is another coordinate (py.sequence_concat as `+`
            # ctor), not a RuntimeEffect that re-asks for a "genuine runtime
            # operand" while already holding the fold term.
            other_term = other.to_term(owner=str(site))
            return ExitSet.completed(
                ComprehensionValue(
                    ctor(
                        "+",
                        [
                            self.term,
                            other_term,
                        ],
                    )
                )
            )
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

        if type(other) is CallSiteValue:
            from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

            return SymbolicValue(self.term).add(other, site, ctx)
        return super().add(other, site, ctx)

    def subtract(self, other, site, ctx):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

        if (
            type(other) is ComprehensionValue
            and _is_set_coordinate(self.term)
            and _is_set_coordinate(other.term)
        ):
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(
                ComprehensionValue(ctor("py.set_difference", [self.term, other.term]))
            )
        if type(other) is CallSiteValue:
            from sugar_lift_py_tests.effect import runtime_subtract

            return runtime_subtract(self, other, site)
        return super().subtract(other, site, ctx)

    def bitwise_or(self, other, site, ctx):
        if (
            type(other) is ComprehensionValue
            and _is_set_coordinate(self.term)
            and _is_set_coordinate(other.term)
        ):
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(
                ComprehensionValue(ctor("py.set_union", [self.term, other.term]))
            )
        return super().bitwise_or(other, site, ctx)

    def multiply(self, other, site, ctx):
        """Preserve repetition when the count is a constructed Python integer.
        A list decided whole repeats as the list it is."""
        if self.display is not None:
            return self.display.multiply(other, site, ctx)
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.floor.term_value import TermValue

        if (
            getattr(self.term, "name", None) == "py.listcomp"
            and type(other) is TermValue
            and type(other.value) is int
        ):
            return SymbolicValue(self.term).multiply(other, site, ctx)
        return super().multiply(other, site, ctx)

    def subscript(self, index, site):
        # A list or set decided whole (``display``, every member in hand,
        # ``ComprehensionSugar._run_in_hand``) is read as that display, as its
        # truth and its operators are: a list's ``__getitem__`` over its
        # members (an out-of-range index its ``IndexError``), a set's
        # ``TypeError``.  Before #8957 the rewrite dissolved such a
        # comprehension into the display itself; the one way projects it in
        # the reduction, and its readers read what it projected (#7757).  The
        # display is read through the one subscript door
        # (``discharge_subscript``), never its subscript protocol directly: a
        # parameter index is read as a source subscript's is.
        if self.display is not None:
            from sugar_lift_py_tests.operations.subscript_operation import (
                discharge_subscript,
            )

            return discharge_subscript(
                self.display,
                index,
                site,
                None,
                owner="ComprehensionValue.subscript",
            )
        # A runtime comprehension still has Python collection semantics, but
        # neither its members nor its cardinality are available at lift time.
        # Preserve the real lookup as a proof-bearing coordinate; do not invent
        # an element or silently assume the lookup succeeds.  A key (or a
        # slice bound) whose type nothing here decides -- a parameter's, an
        # opaque call result's -- may raise anything: the one undecided read,
        # its halt kept (#7757).
        from sugar_lift_py_tests.floor.floor_value import index_type_undecided

        if index_type_undecided(index):
            return self.undecided_subscript(
                index, site, owner="ComprehensionValue.subscript"
            )
        return self.py_subscript_coordinate(index, site)

    def setitem(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, index, value, site, ctx
    ):
        """``comprehension[index] = value``: the undecided item mutation
        (``store_effect_sugar.undecided_item_mutation_faces``).  The
        comprehension's members and count are not in hand, so whether the
        store raises (a list index out of range, a set or generator that
        binds no ``__setitem__``) is not decided here: it completes, the
        receiver after it unknown, only under its site-keyed completes atom,
        and halts with an undetermined raise under the complement, both faces
        owed.  Never a completion with the halt dropped (#7757 step 7)."""
        del index, value, ctx
        from sugar_lift_py_tests.sugar.store_effect_sugar import (
            undecided_item_mutation_faces,
        )

        return undecided_item_mutation_faces(
            site, method="__setitem__", owner="ComprehensionValue.setitem"
        )

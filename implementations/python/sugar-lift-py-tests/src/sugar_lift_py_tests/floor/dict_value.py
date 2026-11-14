from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from .guard_stable_value import GuardStableValue


@dataclass(frozen=True)
class DictValue(GuardStableValue):
    """A dict of reduced (key, value) floor pairs, in source order.

    The sugar reduces each key and each value; the floor holds what those
    reductions were. No methods beyond the dataclass and the subscript floor --
    floors this dict does not implement panic for free via FloorValue defaults.
    """

    entries: tuple
    # The construction that made this object in the frame reading it, kept
    # by the one door's post-state; None for a value that arrived by binding
    # (``object_identity``: ``made_at``, ``arrived``, ``contents_current``).
    # Required, never defaulted: every construction names it.
    allocation: str | None = dataclass_field(
        kw_only=True,
        compare=False,
        metadata={"testimony": "provenance"},
    )
    # The binding read a value with no ``allocation`` arrived through: what
    # an undecided read names the object by (``object_identity.arrived``,
    # ``identity_term``).
    arrival: str | None = dataclass_field(
        default=None,
        kw_only=True,
        compare=False,
        metadata={"testimony": "provenance"},
    )

    def mapping_entries(self) -> tuple:
        return self.entries

    def mapping_with_entries(self, entries: tuple) -> "DictValue":
        # The same object: it keeps its ``allocation``.
        return replace(self, entries=entries)

    def denotes_value(self) -> bool:
        """This floor value denotes a ``dict``."""
        return True

    def truth(self, site):
        """A constructed dict is truthy exactly when it has an entry -- among
        its contents now (``object_identity.contents_current``); otherwise
        the undecided truth (no halt, no debt: a builtin dict's truth runs no
        code)."""
        from .object_identity import contents_current

        if not contents_current(self):
            return self.undecided_truth(site, owner="DictValue.truth")
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return ExitSet.completed(
            TrueBoolLiteralSugar(site=site)
            if self.entries
            else FalseBoolLiteralSugar(site=site)
        )

    def length(self, site):
        # Keys whose equality is undecided may have collapsed into one; entries
        # that are not its contents now (``object_identity.contents_current``)
        # count nothing.
        from sugar_lift_py_tests.floor.membership import decided_distinct
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import ExitSet

        from .object_identity import contents_current

        if not contents_current(self) or not decided_distinct(
            tuple(key for key, _value in self.entries)
        ):
            from sugar_lift_py_tests.floor.set_value import undecided_length

            return undecided_length(self, site)
        return ExitSet.completed(TermValue(len(self.entries)))

    def iter_with(self, operation, ctx):
        """``iter(dict)`` traverses authenticated keys in insertion order --
        once those keys are decidedly distinct; otherwise which keys survive
        is undecided and the traversal stays a construction gap.  Keys that
        are not its contents now (``object_identity.contents_current``) are
        the undecided iteration."""
        from sugar_lift_py_tests.floor.iterator_value import ListIteratorValue
        from sugar_lift_py_tests.floor.membership import decided_distinct
        from sugar_lift_py_tests.outcome import ExitSet

        from .object_identity import contents_current

        if not contents_current(self):
            return self.undecided_iteration(operation.blame, owner="DictValue.iter")
        if not decided_distinct(tuple(key for key, _value in self.entries)):
            return super().iter_with(operation, ctx)
        del operation, ctx

        return ExitSet.completed(
            ListIteratorValue(tuple(key for key, _value in self.entries), index=0)
        )

    def slice_assign_iterable_with(self, operation, ctx):
        """Project insertion-ordered authenticated keys for slice assignment
        -- the dict's keys now (``object_identity.contents_current``).
        Otherwise no members are in hand: the store is the undecided item
        mutation (``list_value.stale_item_mutation``)."""
        del ctx
        from .list_value import stale_item_mutation
        from .object_identity import contents_current

        if not contents_current(self):
            return stale_item_mutation(operation.blame, "__setitem__", operation.owner)
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(tuple(key for key, _value in self.entries))

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
            tuple(key for key, _value in self.entries),
            kind="dict",
            member_role="key",
            container_role="dict",
            hashed=True,
            site=site,
        )
        if decided is not None:
            return decided
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="DictValue.contains",
            blame=str(site),
            observed=type(item).__name__,
            requested="constructed finite key or typed symbolic membership operand",
            fix="construct key equality on the Python floor or keep it loud",
        )

    def bitwise_or(self, other, site, ctx):
        from .object_identity import contents_current, made_at

        if type(other) is not DictValue:
            return super().bitwise_or(other, site, ctx)
        if not (contents_current(self) and contents_current(other)):
            # Entries that are not the objects' contents now merge nothing.
            return super().bitwise_or(other, site, ctx)
        entries = list(self.entries)
        for right_key, right_value in other.entries:
            found = _key_position(tuple(entries), right_key)
            if found is None:
                # Whether this key is already present is undecided.
                return super().bitwise_or(other, site, ctx)
            if found >= 0:
                entries[found] = (entries[found][0], right_value)
            else:
                entries.append((right_key, right_value))
        from sugar_lift_py_tests.outcome import ExitSet

        # A new dict made here.
        return ExitSet.completed(DictValue(tuple(entries), allocation=made_at(site)))

    def attribute(self, name, site, ctx):
        # Bound methods and fields on a constructed dict (``{{}}.get``, ``mapping.items``) stay the
        # py.getattr coordinate -- one law, shared with StringValue and the
        # other constructed containers. Never invent a method body or a field.
        del site, ctx
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
        """Execute closed dict methods whose result is fixed by this value.

        A ground dict whose contents are current at the call never reaches
        here: the cited fold answers its ``items()``
        (``container_method_cited_fold``, #7757).  This is ``items()`` of a
        current dict with a member known only by its type.  A dict that
        arrived by binding never reaches here (``supports_closed_method``):
        its contents are not the object's contents now."""
        del owner, ctx
        if (
            self.supports_closed_method(name)
            and not arguments
            and not keywords
            and required_frame is None
        ):
            from sugar_lift_py_tests.floor.tuple_value import TupleValue
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(
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
        from .object_identity import contents_current

        return name == "items" and contents_current(self)

    def setattr(self, name, value, site, ctx):
        """Dicts have no instance ``__dict__``; store is AttributeError."""
        del name, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="DictValue.setattr"
        )

    def delattr(self, name, site, ctx):
        """Dicts have no instance ``__dict__``; delete is AttributeError."""
        del name, ctx
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
        # hash/eq semantics are not source-decided is the two-faced read.
        from sugar_lift_py_tests.floor.membership import decided_unhashable
        from sugar_lift_py_tests.outcome import ExitSet

        if decided_unhashable(index):
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="TypeError",
                site=site,
                owner="DictValue.subscript",
            )
        from .object_identity import contents_current

        if not contents_current(self):
            # Entries that are not its contents now find nothing: the
            # undecided read.
            return self.undecided_subscript(index, site, owner="DictValue.subscript")

        found = _key_position(self.entries, index)
        if found is not None and found >= 0:
            return ExitSet.completed(self.entries[found][1])
        if found == -1:
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="KeyError",
                site=site,
                owner="DictValue.subscript",
            )
        # ``d[k]`` whose key's hash or equality against ``d``'s keys is open
        # (a formal key, or a key of undecided type): CPython hashes ``k`` and
        # compares it (``is``, then ``==``) with each stored key, which may
        # raise anything and may find any entry or none.  Nothing here decides
        # which: the one undecided read.  A dict or key that has no term
        # refuses by name (its ``to_term`` refusal propagates).
        return self.undecided_subscript(index, site, owner="DictValue.subscript")

    def setitem(self, index, value, site, ctx):
        guarded = self._guarded_setitem(index, value, site, ctx)
        if guarded is not None:
            return guarded
        from sugar_lift_py_tests.outcome import ExitSet

        found = _key_position(self.entries, index)
        if found is not None:
            entries = list(self.entries)
            if found >= 0:
                # The stored key stays: ``{1: a}[True] = b`` is ``{1: b}``.
                entries[found] = (entries[found][0], value)
            else:
                entries.append((index, value))
            # The same object: it keeps its ``allocation``.
            return ExitSet.completed(replace(self, entries=tuple(entries)))
        from sugar_lift_py_tests.effect import (
            SubscriptStoreRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.floor.store_outcome_coordinate import store_faces

        return store_faces(
            SubscriptStoreRuntimeEffect(
                "dict subscript store requires a concrete key; "
                f"owner=DictValue.setitem site={site}",
                **runtime_effect_evidence("py.setitem", index, site),
            )
        )

    def _guarded_setitem(self, index, value, site, ctx):
        """Store once on every authenticated guarded key/value face.

        A GuardedValue's conditional term is lift-time decidable and therefore
        cannot mint RuntimeEffect authority.  Preserve the source partition:
        recursively apply this dict's ordinary store law to each face and
        rejoin under the original guard and its exact complement.
        """
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.ir import not_

        operands = (index, value)
        for position, operand in enumerate(operands):
            if not isinstance(operand, GuardedValue):
                continue

            def project(face):
                selected = list(operands)
                selected[position] = face
                return self.setitem(*selected, site, ctx)

            when_true = project(operand.when_true).guarded(operand.guard)
            when_false = project(operand.when_false).guarded(not_(operand.guard))
            return when_true.union(when_false)
        return None

    def delitem(self, index, site, ctx):
        # Whether the key is held (else ``KeyError``) is read only from
        # entries that are current (``object_identity.contents_current``),
        # whichever caller reached this delete; otherwise it is the
        # delete's undecided form.
        del ctx
        from sugar_lift_py_tests.outcome import ExitSet

        from .list_value import stale_item_mutation
        from .object_identity import contents_current

        if not contents_current(self):
            return stale_item_mutation(site, "__delitem__", "DictValue.delitem")
        found = _key_position(self.entries, index)
        if found is not None:
            if found >= 0:
                return ExitSet.completed(
                    replace(
                        self,
                        entries=(*self.entries[:found], *self.entries[found + 1 :]),
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
        from sugar_lift_py_tests.floor.store_outcome_coordinate import store_faces

        return store_faces(
            SubscriptStoreRuntimeEffect(
                "dict subscript delete requires a concrete key; "
                f"owner=DictValue.delitem site={site}",
                **runtime_effect_evidence("py.delitem", index, site),
            )
        )


def _key_position(entries, index):
    """Where ``index`` is among ``entries``' keys: int, -1 (absent), or None.

    CPython's dict lookup (``floor/membership.py``): the key's hash and
    ``is``/``==`` against each stored key. None when the key's hash or any
    comparison is not decided."""
    from sugar_lift_py_tests.floor import builtin_container_method as law

    if not law._hash_decided(index):
        return None
    return law._find_key(tuple(entries), index)

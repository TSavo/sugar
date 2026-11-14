from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness


@dataclass(frozen=True)
class AttributeStoreEffectSugar(Sugar):
    """`receiver.attr = value` — evaluate once, then project the store face.

    Python order: RHS first, then the receiver, each exactly once.  Dispatch is
    ``__setattr__`` / descriptor ``__set__`` via Floor ``setattr`` — a different
    method and obligation from the read path ``attribute`` /
    ``__getattr__`` / ``__getattribute__``.

    Projection arms:

    1. **Formal receiver** → ``NativeOperationExitCarrierV1`` demand
       ``setattr_named`` with operands
       ``(receiver, StringValue(name), value)`` and coordinates
       ``(receiver.formal_coordinate, None, value_coordinate)``.
       The n-ary projector (#6614) unwraps the name and calls
       ``receiver.setattr(name.value, value, site)``.  Helper alone stays
       undischarged; an ordinary source caller supplies actuals.
    2. **Decided runtime type** → ``receiver.setattr(attr, value, site)``
       projecting its completed or halted faces through the store path
       (never the read path).
    3. **Undecided non-formal** → ``AttributeStoreRuntimeEffect`` dual faces
       under complementary store-outcome guards (composition instrument for
       free undecided receivers — never a consumer ``SugarNotWritten``).
    """

    receiver: Sugar
    value: Sugar
    attr: str
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return typed_red_effect_witness(
            name="attribute_store_runtime_effect",
            owner_sugar="AttributeStoreEffectSugar",
            source="def A(o, v):\n    o.a = v\n    return v\n",
            effect_class="AttributeStoreRuntimeEffect",
            reason_needle="attribute store",
            blame_needle="attr=a",
            wrong_reason_needle="attribute store target `.b`",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Python constructs the RHS before evaluating an assignment target.
        return self.value.desugar(ctx).and_then(
            lambda value: self.receiver.desugar(ctx).and_then(
                lambda receiver: self._store(receiver, value)
            )
        )

    def desugar_store(self, ctx: object, value) -> Outcome:
        """Store an RHS already reduced once by a chained assignment."""
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.project_setattr(receiver, self.attr, value, self.site)
        )

    def _store(self, receiver, value) -> Outcome:
        return self.project_setattr(receiver, self.attr, value, self.site)

    @staticmethod
    def project_setattr(receiver, attr: str, value, site) -> Outcome:
        """Producer-owned attribute **store** projection (one door).

        The law shared by ordinary AttributeStoreEffectSugar and
        Attribute AugAssign (already-evaluated receiver and value):

        1. Formal receiver → undischarged ``setattr_named`` carrier
        2. Decided runtime type → Floor ``setattr``; a raise is its
           halted arm (halted store, not statement green)
        3. Undecided non-formal → dual-face ``AttributeStoreRuntimeEffect``
           (never consumer ``SugarNotWritten``)
        """
        formal_coordinate = getattr(receiver, "formal_coordinate", None)
        if formal_coordinate is not None:
            return AttributeStoreEffectSugar.mint_setattr_named_carrier(
                site=site,
                receiver=receiver,
                attr=attr,
                value=value,
            )

        if receiver.runtime_type_is_decided():
            return receiver.setattr(attr, value, site)

        from sugar_lift_py_tests.effect import (
            AttributeStoreRuntimeEffect,
            runtime_effect_evidence_from_terms,
        )
        from sugar_lift_py_tests.floor.store_outcome_coordinate import store_faces
        from sugar_lift_py_tests.ir import ctor, str_const

        operation = ctor(
            "python:attribute_store",
            [
                receiver.to_term(owner="AttributeStoreEffectSugar.receiver"),
                str_const(attr),
                value.to_term(owner="AttributeStoreEffectSugar.value"),
            ],
        )
        return store_faces(
            AttributeStoreRuntimeEffect(
                "attribute assignment runtime boundary: attribute store "
                f"target `.{attr}` -- receiver identity belongs to "
                "Python's runtime __setattr__/descriptor dispatch; "
                f"attr={attr} site={site}",
                **runtime_effect_evidence_from_terms(operation, operation, site),
            )
        )

    @staticmethod
    def mint_setattr_named_carrier(*, site, receiver, attr: str, value):
        """Producer-side contract for n-ary ``setattr_named`` discharge.

        Operand order matches the projector table (#6614):
        ``receiver.setattr(name.value, value, site)`` after unwrap.
        Coordinates: ``(receiver.formal, None, value.formal)`` — lengths and
        order are load-bearing (#6613 ``__post_init__``).
        """
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.floor import StringValue

        formal_coordinate = getattr(receiver, "formal_coordinate", None)
        if formal_coordinate is None:
            raise ValueError(
                "setattr_named carrier requires a receiver formal_coordinate"
            )
        value_coordinate = getattr(value, "formal_coordinate", None)
        return NativeOperationExitCarrierV1.mint(
            site=site,
            operator="setattr_named",
            operands=(receiver, StringValue(attr), value),
            coordinates=(formal_coordinate, None, value_coordinate),
        )


@dataclass(frozen=True)
class SubscriptStoreEffectSugar(Sugar):
    """`receiver[index] = value` — evaluate once, then project the store face.

    Python order: RHS first, then the receiver, then the index, each exactly
    once.  Dispatch is ``__setitem__`` via Floor ``setitem`` — a different
    method and obligation from the load path ``subscript`` / ``__getitem__``.

    Projection arms:

    1. **Any formal operand** → ``NativeOperationExitCarrierV1`` demand
       ``setitem`` with operands and coordinates in *discharge* order
       ``(receiver, index, value)``.  The n-ary projector calls
       ``receiver.setitem(index, value, site)``.  Helper alone stays
       undischarged; an ordinary source caller supplies actuals.
    2. **Decided runtime type** → ``receiver.setitem(index, value, site)``
       projecting its completed or halted faces through the store path
       (never the load path).
    3. **Undecided non-formal** → two faces (#7585): no floor decides
       ``type(receiver).__setitem__``, so the store completes only under
       ``python:setitem.completes(python:setitem(<site occurrence>))`` --
       leaving the receiver's contents unknown -- and halts with an
       ``UndeterminedRaiseEffect`` under the complement.
    """

    receiver: Sugar
    index: Sugar
    value: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # The source-visible completed/exceptional and loud-refusal laws are
        # discrimination tests in test_subscript_store_desugar.py /
        # test_setitem_formal_caller.py. The former typed-runtime-effect
        # witness asserted the superseded generic effect.
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        # Python evaluates the RHS before the target receiver and key.
        return self.value.desugar(ctx).and_then(
            lambda value: self.receiver.desugar(ctx).and_then(
                lambda receiver: self.index.desugar(ctx).and_then(
                    lambda index: self._store(receiver, index, value, ctx)
                )
            )
        )

    def desugar_store(self, ctx: object, value) -> Outcome:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.index.desugar(ctx).and_then(
                lambda index: self._store(receiver, index, value, ctx)
            )
        )

    def _store(self, receiver, index, value, ctx=None) -> Outcome:
        receiver = receiver.project_operation_receiver(
            ctx, owner="SubscriptStoreEffectSugar receiver"
        )
        index = index.project_operation_receiver(
            ctx, owner="SubscriptStoreEffectSugar index"
        )
        value = value.project_operation_receiver(
            ctx, owner="SubscriptStoreEffectSugar value"
        )
        coordinates = tuple(
            getattr(operand, "formal_coordinate", None)
            for operand in (receiver, index, value)
        )
        if any(coordinate is not None for coordinate in coordinates):
            # Undischarged demand awaiting caller actuals — not a refusal.
            return self.mint_setitem_carrier(
                site=self.site,
                receiver=receiver,
                index=index,
                value=value,
            )
        if not receiver.runtime_type_is_decided():
            return _undecided_setitem_faces(receiver, self.site)
        source_aware = getattr(receiver, "setitem_with_context", None)
        return (
            source_aware(index, value, self.site, ctx)
            if callable(source_aware)
            else receiver.setitem(index, value, self.site)
        )

    @staticmethod
    def mint_setitem_carrier(*, site, receiver, index, value):
        """Producer-side contract for n-ary ``setitem`` discharge.

        Operand order matches the projector table (#6614):
        ``receiver.setitem(index, value, site)``.  This is *discharge* order
        (receiver, index, value) — not source evaluation order (value,
        receiver, index).  Coordinates are exactly one slot per ordered
        operand; lengths and order are load-bearing (#6613 ``__post_init__``).
        """
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )

        coordinates = tuple(
            getattr(operand, "formal_coordinate", None)
            for operand in (receiver, index, value)
        )
        if not any(coordinate is not None for coordinate in coordinates):
            raise ValueError(
                "setitem carrier requires at least one formal_coordinate among "
                "receiver, index, and value"
            )
        return NativeOperationExitCarrierV1.mint(
            site=site,
            operator="setitem",
            operands=(receiver, index, value),
            coordinates=coordinates,
        )


def _undecided_setitem_faces(receiver, site):
    """``r[k] = v`` where nothing decides ``type(r).__setitem__``.

    The receiver is a value this frame holds (an opaque call result, an
    unknown read) but no floor, contract or source testified to its type, so
    ``__setitem__`` may run anything and raise anything.  See
    :func:`undecided_item_mutation_faces`.
    """
    del receiver
    return undecided_item_mutation_faces(
        site, noun="setitem", method="__setitem__", owner="UndecidedSetitem"
    )


def undecided_item_mutation_faces(site, *, noun: str, method: str, owner: str):
    """Two faces for ``r[k] = v`` / ``del r[k]`` over an undecided receiver.

    The mutation completes only under
    ``python:<noun>.completes(python:<noun>(<occurrence>))``, keyed on this
    exact site and occurrence so two mutations are never forced to agree, and
    its post-state is ``python:receiver_after_call(<occurrence>, <method>)``:
    the receiver's contents after the call are unknown, as for any undecided
    mutation.  The complement halts with an ``UndeterminedRaiseEffect``
    (``owner``).  No entry is written or removed and no exception type is
    guessed.
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.ir import atomic, ctor, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome.exit_set import (
        Completed,
        ExitSet,
        Halted,
        complement_guard,
    )
    from sugar_lift_py_tests.sugar.builtin_container_call_sugar import _unknown_after

    key = occurrence_key(site)
    completes = atomic(
        f"python:{noun}.completes",
        [ctor(f"python:{noun}", (str_const(key),))],
    )
    return ExitSet(
        (
            Completed(completes, _unknown_after(site, method)),
            Halted(
                complement_guard(completes),
                UndeterminedRaiseEffect(
                    blame=str(site),
                    occurrence=key,
                    producer_node_owner=owner,
                ),
                None,
            ),
        )
    ).normalize()

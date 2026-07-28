from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Incomplete, Outcome
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
       projecting ``Completed`` or ``RaiseValue`` exceptional faces through
       the store path (never the read path).
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
            lambda receiver: self._store(receiver, value)
        )

    def _store(self, receiver, value) -> Outcome:
        from sugar_lift_py_tests.floor import RaiseValue
        from sugar_lift_py_tests.outcome import Complete

        formal_coordinate = getattr(receiver, "formal_coordinate", None)
        if formal_coordinate is not None:
            # Undischarged demand awaiting caller actuals — not a refusal.
            return self.mint_setattr_named_carrier(
                site=self.site,
                receiver=receiver,
                attr=self.attr,
                value=value,
            )

        # Decided receivers project through Floor setattr (store path ≠ read).
        if receiver.runtime_type_is_decided():
            projected = receiver.setattr(self.attr, value, self.site)
            if isinstance(projected, Complete) and isinstance(
                projected.value, RaiseValue
            ):
                return Incomplete(projected.value.effect)
            return projected

        # Undecided non-formal: dual-face AttributeStoreRuntimeEffect.
        from sugar_lift_py_tests.effect import (
            AttributeStoreRuntimeEffect,
            runtime_effect_evidence_from_terms,
        )
        from sugar_lift_py_tests.ir import ctor, str_const

        operation = ctor(
            "python:attribute_store",
            [
                receiver.to_term(owner="AttributeStoreEffectSugar.receiver"),
                str_const(self.attr),
                value.to_term(owner="AttributeStoreEffectSugar.value"),
            ],
        )
        return Incomplete(
            AttributeStoreRuntimeEffect(
                "attribute assignment runtime boundary: attribute store "
                f"target `.{self.attr}` -- receiver identity belongs to "
                "Python's runtime __setattr__/descriptor dispatch; "
                f"attr={self.attr} site={self.site}",
                **runtime_effect_evidence_from_terms(operation, operation, self.site),
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
       projecting ``Completed`` or ``RaiseValue`` exceptional faces through
       the store path (never the load path).
    3. **Undecided non-formal** → loud ``SugarNotWritten`` until the
       three-operand formal carrier is attachable.
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
                    lambda index: self._store(receiver, index, value)
                )
            )
        )

    def desugar_store(self, ctx: object, value) -> Outcome:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.index.desugar(ctx).and_then(
                lambda index: self._store(receiver, index, value)
            )
        )

    def _store(self, receiver, index, value) -> Outcome:
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
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner="SubscriptStoreEffectSugar._store",
                blame=self.site,
                observed="undischarged subscript store over runtime-selected receiver",
                requested=(
                    "NativeOperationExitCarrierV1 n-ary setitem demand over "
                    "receiver, key, and value formal coordinates"
                ),
                fix="attach the three-operand carrier seam owned by 9883",
            )
        projected = receiver.setitem(index, value, self.site)
        from sugar_lift_py_tests.floor import RaiseValue
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        if isinstance(projected, Complete) and isinstance(projected.value, RaiseValue):
            return Incomplete(projected.value.effect)
        return projected

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


@dataclass(frozen=True)
class LegacyAugmentedSubscriptStoreEffectSugar(Sugar):
    """Preserve AugAssign without pretending its raw RHS is the stored value."""

    index_text: str
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.effect import (
            SubscriptStoreRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.ir import make_var

        operand = make_var(f"store_target[{self.index_text}]")
        return Incomplete(
            SubscriptStoreRuntimeEffect(
                "augmented subscript assignment runtime boundary: subscript store "
                f"target `[{self.index_text}]`; index={self.index_text} site={self.site}",
                **runtime_effect_evidence("py.setitem", operand, self.site),
            )
        )

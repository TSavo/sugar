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

    Projection arms (PARTIAL — dual-face composition instrument preserved):

    1. **Decided runtime type** → ``receiver.setattr(attr, value, site)``
       projecting ``Completed`` or ``RaiseValue`` exceptional faces through
       the store path (never the read path).
    2. **Undecided / formal** → ``AttributeStoreRuntimeEffect`` dual faces
       under complementary store-outcome guards.  This is the instrument the
       five named store ExitSet composition laws read; it is **not** replaced
       by a consumer ``SugarNotWritten``.

    Formal ``setattr_named`` carrier mint (n-ary discharge contract) is the
    next partial step once composition can consume undischarged carriers
    without deleting dual-face detectors.  The mint shape is pinned in
    ``test_attribute_store_desugar`` as the producer-side contract for the
    n-ary worker: operator ``setattr_named``, operands
    ``(receiver, StringValue(name), value)``.
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

        # Decided receivers project through Floor setattr (store path ≠ read).
        if receiver.runtime_type_is_decided():
            projected = receiver.setattr(self.attr, value, self.site)
            if isinstance(projected, Complete) and isinstance(
                projected.value, RaiseValue
            ):
                return Incomplete(projected.value.effect)
            return projected

        # Undecided / formal: retain dual-face AttributeStoreRuntimeEffect.
        # Do not emit SugarNotWritten from this consumer — that converts
        # constructed dual-face behaviour into a refusal.
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

        Operand order and operator string are fixed for the n-ary worker:
        ``receiver.setattr(name.value, value, site)`` after discharge.
        Not wired into ``_store`` while dual-face composition laws still
        instrument formal parameters via ``AttributeStoreRuntimeEffect``.
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
    """`receiver[index] = value`, evaluated and dispatched as ``__setitem__``.

    Ground receivers project their native completed or exceptional store face.
    A runtime-selected receiver stays loud until the n-ary native-operation
    carrier can preserve receiver, key, value, and the original occurrence.
    """

    receiver: Sugar
    index: Sugar
    value: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # The source-visible completed/exceptional and loud-refusal laws are
        # discrimination tests in test_subscript_store_desugar.py. The former
        # typed-runtime-effect witness asserted the superseded generic effect.
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
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )

            return NativeOperationExitCarrierV1.mint(
                site=self.site,
                operator="setitem",
                operands=(receiver, index, value),
                coordinates=coordinates,
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

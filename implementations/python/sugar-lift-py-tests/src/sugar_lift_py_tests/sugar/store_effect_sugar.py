from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness


@dataclass(frozen=True)
class AttributeStoreEffectSugar(Sugar):
    """`<receiver>.<attr> = <value>` -- an attribute store whose receiver
    identity belongs to the runtime: Python attribute assignment can invoke
    descriptors and ``__setattr__`` at runtime, so the exact post-state is not
    lift-time decidable.

    Unlike ``AssignSugar`` (a plain-Name target, spent by substitute), a
    store target is never bound -- it is read AND written, so it carries no
    inert-meaning arm. This desugars straight to typed red: ``Incomplete``
    wrapping an ``AttributeStoreRuntimeEffect``, witnessed at the TREE
    fragment site (``site``, the statement's own fragment -- the sole site
    type on this hot path; see ``effect/runtime_effect.py``'s
    ``RuntimeEffectSite`` protocol). The store completed (Python continues
    to the next statement), so ``Incomplete.follow()`` treats this effect as
    continue-with-red, not halt (outcome/incomplete.py::
    _effect_continues_control_flow) -- the block keeps reducing past it.
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

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class AttributeDeleteEffectSugar(Sugar):
    """`del receiver.attr` — evaluate once, then project the delete face.

    Projection arms (mirrors :class:`AttributeStoreEffectSugar`):

    1. **Formal receiver** → ``NativeOperationExitCarrierV1`` demand
       ``delattr_named`` with operands
       ``(receiver, StringValue(name))`` and coordinates
       ``(receiver.formal_coordinate, None)``.  Explicit projector
       ``_project_delattr_named(receiver, name, site)`` unwraps the name
       and calls ``receiver.delattr(name.value, site)`` (Python
       ``__delattr__``).  Helper alone stays undischarged.
    2. **Decided runtime type** → ``receiver.delattr(attr, site)`` projecting
       ``Completed`` or ``RaiseValue`` exceptional faces through the delete
       path (never the read path — readability never authorizes deletion).
    3. **Undecided non-formal** → ``AttributeDeleteRuntimeEffect`` dual faces
       under complementary store-outcome guards.

    Out of scope: Name deletion (``del name`` / DeleteNameSugar).
    """

    receiver: Sugar
    attr: str
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self._delete(receiver)
        )

    def _delete(self, receiver) -> Outcome:
        from sugar_lift_py_tests.floor import RaiseValue
        from sugar_lift_py_tests.outcome import Complete

        formal_coordinate = getattr(receiver, "formal_coordinate", None)
        if formal_coordinate is not None:
            # Undischarged demand awaiting caller actuals — not a refusal.
            return self.mint_delattr_named_carrier(
                site=self.site,
                receiver=receiver,
                attr=self.attr,
            )

        if receiver.runtime_type_is_decided():
            projected = receiver.delattr(self.attr, self.site)
            if isinstance(projected, Complete) and isinstance(
                projected.value, RaiseValue
            ):
                return Incomplete(projected.value.effect)
            return projected

        from sugar_lift_py_tests.effect import (
            AttributeDeleteRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.ir import ctor, str_const

        operand = ctor(
            "python:attribute_delete_target",
            [receiver.to_term(owner="attribute delete"), str_const(self.attr)],
        )
        return Incomplete(
            AttributeDeleteRuntimeEffect(
                "attribute deletion runtime boundary: Python dispatches "
                f"__delattr__/descriptor deletion for .{self.attr}",
                **runtime_effect_evidence("py.delattr", operand, self.site),
            )
        )

    @staticmethod
    def mint_delattr_named_carrier(*, site, receiver, attr: str):
        """Producer-side contract for n-ary ``delattr_named`` discharge.

        Operand order matches the projector table:
        ``receiver.delattr(name.value, site)`` after unwrap.
        Coordinates: ``(receiver.formal, None)`` — lengths and order are
        load-bearing (#6613 ``__post_init__``).
        """
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.floor import StringValue

        formal_coordinate = getattr(receiver, "formal_coordinate", None)
        if formal_coordinate is None:
            raise ValueError(
                "delattr_named carrier requires a receiver formal_coordinate"
            )
        return NativeOperationExitCarrierV1.mint(
            site=site,
            operator="delattr_named",
            operands=(receiver, StringValue(attr)),
            coordinates=(formal_coordinate, None),
        )


@dataclass(frozen=True)
class SubscriptDeleteEffectSugar(Sugar):
    """`del receiver[index]` — evaluate once, then project the delete face.

    Projection arms (mirrors :class:`SubscriptStoreEffectSugar`):

    1. **Any formal operand** → ``NativeOperationExitCarrierV1`` demand
       ``delitem`` with operands and coordinates in *discharge* order
       ``(receiver, index)``.  Explicit projector
       ``_project_delitem(receiver, index, site)`` calls
       ``receiver.delitem(index, site)`` (Python ``__delitem__``).  Helper
       alone stays undischarged; an ordinary source caller supplies actuals.
    2. **Decided runtime type** → ``receiver.delitem(index, site)`` projecting
       ``Completed`` or ``RaiseValue`` exceptional faces through the delete
       path (never the load path).  Earlier bindings survive later delete
       halts via reducer pre-effect state on the carrier.
    3. **Undecided non-formal** → loud ``SugarNotWritten`` until the
       two-operand formal carrier is attachable.

    Out of scope: Name deletion (``del name`` / DeleteNameSugar).
    """

    receiver: Sugar
    index: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.index.desugar(ctx).and_then(
                lambda index: self._delete(receiver, index)
            )
        )

    def _delete(self, receiver, index) -> Outcome:
        coordinates = tuple(
            getattr(operand, "formal_coordinate", None)
            for operand in (receiver, index)
        )
        if any(coordinate is not None for coordinate in coordinates):
            # Undischarged demand awaiting caller actuals — not a refusal.
            return self.mint_delitem_carrier(
                site=self.site,
                receiver=receiver,
                index=index,
            )
        if not receiver.runtime_type_is_decided():
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner="SubscriptDeleteEffectSugar._delete",
                blame=self.site,
                observed=(
                    "undischarged subscript delete over runtime-selected receiver: "
                    f"{type(receiver).__name__}[{type(index).__name__}]"
                ),
                requested=(
                    "NativeOperationExitCarrierV1 n-ary delitem demand over "
                    "receiver and key formal coordinates"
                ),
                fix=(
                    "attach the two-operand carrier via "
                    "SubscriptDeleteEffectSugar.mint_delitem_carrier"
                ),
            )
        projected = receiver.delitem(index, self.site)
        from sugar_lift_py_tests.floor import RaiseValue
        from sugar_lift_py_tests.outcome import Complete

        if isinstance(projected, Complete) and isinstance(projected.value, RaiseValue):
            return Incomplete(projected.value.effect)
        return projected

    @staticmethod
    def mint_delitem_carrier(*, site, receiver, index):
        """Producer-side contract for n-ary ``delitem`` discharge.

        Operand order matches the projector table:
        ``receiver.delitem(index, site)``.  Discharge order is
        ``(receiver, index)``.  Coordinates are exactly one slot per ordered
        operand; lengths and order are load-bearing (#6613 ``__post_init__``).
        """
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )

        coordinates = tuple(
            getattr(operand, "formal_coordinate", None)
            for operand in (receiver, index)
        )
        if not any(coordinate is not None for coordinate in coordinates):
            raise ValueError(
                "delitem carrier requires at least one formal_coordinate among "
                "receiver and index"
            )
        return NativeOperationExitCarrierV1.mint(
            site=site,
            operator="delitem",
            operands=(receiver, index),
            coordinates=coordinates,
        )

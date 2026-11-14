from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import ClassVar

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class AttributeDeleteEffectSugar(Sugar):
    """`del receiver.attr` — evaluate once, then project the delete face.

    Projection arms (mirrors :class:`AttributeStoreEffectSugar`):

    1. **Formal receiver** → ``NativeOperationExitCarrierV1`` demand
       ``delattr_named`` with operands
       ``(receiver, StringValue(name))`` and coordinates
       ``(receiver.formal_coordinate, None)``.  Explicit projector
       ``_project_delattr_named(receiver, name, site, ctx)`` unwraps the name
       and calls ``receiver.delattr(name.value, site, ctx)`` (Python
       ``__delattr__``).  Helper alone stays undischarged.
    2. **Decided runtime type** → ``receiver.delattr(attr, site, ctx)`` projecting
       its completed or halted faces through the delete path (never the
       read path — readability never authorizes deletion).
    3. **Undecided non-formal** → ``AttributeDeleteRuntimeEffect`` dual faces
       under complementary store-outcome guards.

    Out of scope: Name deletion (``del name`` / DeleteNameSugar).
    """

    receiver: Sugar
    attr: str
    site: object = dataclass_field(compare=False)
    # The delete's halted face reached nothing inside this statement: the
    # reducer gives it the prefix (``store_faces``).
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self._delete(receiver, ctx)
        )

    def _delete(self, receiver, ctx) -> Outcome:
        formal_coordinate = getattr(receiver, "formal_coordinate", None)
        if formal_coordinate is not None:
            # Undischarged demand awaiting caller actuals — not a refusal.
            return self.mint_delattr_named_carrier(
                site=self.site,
                receiver=receiver,
                attr=self.attr,
            )

        if receiver.runtime_type_is_decided():
            return receiver.delattr(self.attr, self.site, ctx)

        from sugar_lift_py_tests.effect import (
            AttributeDeleteRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.floor.store_outcome_coordinate import store_faces
        from sugar_lift_py_tests.ir import ctor, str_const

        operand = ctor(
            "python:attribute_delete_target",
            [receiver.to_term(owner="attribute delete"), str_const(self.attr)],
        )
        return store_faces(
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
        ``receiver.delattr(name.value, site, ctx)`` after unwrap.
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
       ``_project_delitem(receiver, index, site, ctx)`` calls
       ``receiver.delitem(index, site, ctx)`` (Python ``__delitem__``).  Helper
       alone stays undischarged; an ordinary source caller supplies actuals.
    2. **Decided runtime type** → ``receiver.delitem(index, site, ctx)`` projecting
       its completed or halted faces through the delete path (never the
       load path).  Earlier bindings survive later delete
       halts via reducer pre-effect state on the carrier.
    3. **Undecided non-formal** → two faces (#7585), as for ``r[k] = v``:
       the delete completes only under
       ``python:delitem.completes(python:delitem(<site occurrence>))`` --
       leaving the receiver's contents unknown -- and halts with an
       ``UndeterminedRaiseEffect`` (owner ``UndecidedDelitem``) under the
       complement.

    Out of scope: Name deletion (``del name`` / DeleteNameSugar).
    """

    receiver: Sugar
    index: Sugar
    site: object = dataclass_field(compare=False)
    # The delete's halted face reached nothing inside this statement: the
    # reducer gives it the prefix (``store_faces``).
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.index.desugar(ctx).and_then(
                lambda index: self._delete(receiver, index, ctx)
            )
        )

    def _delete(self, receiver, index, ctx) -> Outcome:
        coordinates = tuple(
            getattr(operand, "formal_coordinate", None) for operand in (receiver, index)
        )
        if any(coordinate is not None for coordinate in coordinates):
            # Undischarged demand awaiting caller actuals — not a refusal.
            return self.mint_delitem_carrier(
                site=self.site,
                receiver=receiver,
                index=index,
            )
        if not receiver.runtime_type_is_decided():
            from sugar_lift_py_tests.sugar.store_effect_sugar import (
                undecided_item_mutation_faces,
            )

            return undecided_item_mutation_faces(
                self.site,
                noun="delitem",
                method="__delitem__",
                owner="UndecidedDelitem",
            )
        return receiver.delitem(index, self.site, ctx)

    @staticmethod
    def mint_delitem_carrier(*, site, receiver, index):
        """Producer-side contract for n-ary ``delitem`` discharge.

        Operand order matches the projector table:
        ``receiver.delitem(index, site, ctx)``.  Discharge order is
        ``(receiver, index)``.  Coordinates are exactly one slot per ordered
        operand; lengths and order are load-bearing (#6613 ``__post_init__``).
        """
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )

        coordinates = tuple(
            getattr(operand, "formal_coordinate", None) for operand in (receiver, index)
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

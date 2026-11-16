from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import ClassVar

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar


def project_delattr(receiver, attr: str, site, ctx) -> ExitSet:
    """``del receiver.attr`` on an already-evaluated receiver: the one
    attribute delete, the delete side of ``store_effect_sugar.project_setattr``.
    ``AttributeDeleteEffectSugar`` and every carrier that holds a value
    (``AuthenticatedExceptionTypeValue``) delete through it, never through
    the held value's own ``delattr`` past the door (#7757).  Its three arms
    are ``AttributeDeleteEffectSugar``'s (formal carrier, decided ``delattr``,
    undecided two faces)."""
    formal_coordinate = getattr(receiver, "formal_coordinate", None)
    if formal_coordinate is not None:
        # Undischarged demand awaiting caller actuals — not a refusal.
        return AttributeDeleteEffectSugar.mint_delattr_named_carrier(
            site=site,
            receiver=receiver,
            attr=attr,
        )

    if receiver.runtime_type_is_decided():
        return receiver.delattr(attr, site, ctx)

    from sugar_lift_py_tests.effect import (
        AttributeDeleteRuntimeEffect,
        runtime_effect_evidence,
    )
    from sugar_lift_py_tests.floor.store_outcome_coordinate import store_faces
    from sugar_lift_py_tests.ir import ctor, str_const

    operand = ctor(
        "python:attribute_delete_target",
        [receiver.to_term(owner="attribute delete"), str_const(attr)],
    )
    return store_faces(
        AttributeDeleteRuntimeEffect(
            "attribute deletion runtime boundary: Python dispatches "
            f"__delattr__/descriptor deletion for .{attr}",
            **runtime_effect_evidence("py.delattr", operand, site),
        )
    )


@dataclass(frozen=True)
class AttributeDeleteEffectSugar(Sugar):
    """`del receiver.attr` — evaluate once, then project the delete face.

    Projection arms (mirrors ``store_effect_sugar.project_setattr``):

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

    def desugar(self, ctx: object = None) -> ExitSet:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self._delete(receiver, ctx)
        )

    def _delete(self, receiver, ctx) -> ExitSet:
        return project_delattr(receiver, self.attr, self.site, ctx)

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

    The delete itself is the one item mutation
    (``store_effect_sugar.item_mutation``), the same one ``r[k] = v`` and
    the container-mutation door's ``__delitem__`` take.

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

    def desugar(self, ctx: object = None) -> ExitSet:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.index.desugar(ctx).and_then(
                lambda index: self._delete(receiver, index, ctx)
            )
        )

    def _delete(self, receiver, index, ctx) -> ExitSet:
        from sugar_lift_py_tests.sugar.store_effect_sugar import item_mutation

        return item_mutation(
            "__delitem__",
            receiver,
            (index,),
            self.site,
            ctx,
            unit=getattr(self.site, "unit", None),
        )

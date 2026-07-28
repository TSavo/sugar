from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.caller_parameter_contract import (
    InplaceThenBinaryProjector,
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
)
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class AugAssignSugar(Sugar):
    """The already-constructed read-op-store value of a lexical Name AugAssign."""

    operation: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        prefix = "def A(renamed):\n    renamed += 2\n    return renamed\n\n"
        return _call_pair(
            name="augassign_read_op_store",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A(3) == 5\n",
            lying=prefix + "def test_a():\n    assert A(3) == 3\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.outcome import Complete

        # Evaluate the read-op child for its real effects, then discard its
        # ordinary value: the lexical store is already carried by BindingEntryV1.
        # Incomplete/Halted faces bypass this continuation and remain loud.
        return self.operation.desugar(ctx).and_then(
            lambda _value: Complete(BlockValue((), can_fall_through=True))
        )


def project_augmented(
    left,
    right,
    operation: InplaceThenBinaryProjector,
    site,
) -> Outcome:
    """Mint formal i* demand, or project ground through the explicit projector.

    Formal operands always mint ``operation.operator`` (e.g. ``iadd``).
    Projector absence is an honorable red — never mint ordinary binary as a
    stand-in.  Ground projection is ``operation(left, right, site)``.
    """
    left_coord = getattr(left, "formal_coordinate", None)
    right_coord = getattr(right, "formal_coordinate", None)
    if left_coord is not None or right_coord is not None:
        if operation.operator not in _NATIVE_OPERATION_PROJECTORS:
            from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
            from sugar_lift_py_tests.gap.panic import construction_panic

            construction_panic(
                ConstructionGap(
                    owner="project_augmented",
                    blame=str(site),
                    observed=(
                        f"formal AugAssign requires enrolled projector "
                        f"operator={operation.operator!r}; projector is ABSENT"
                    ),
                    requested=(
                        f"InplaceThenBinaryProjector enrolled as "
                        f"operator={operation.operator!r}"
                    ),
                    fix=(
                        f"enroll {operation.operator!r} on "
                        "_NATIVE_OPERATION_PROJECTORS; do not mint ordinary "
                        "binary as a silent stand-in for missing i*"
                    ),
                    gap_kind=GapKind.FLOOR,
                    gap_locus=GapLocus.CONSTRUCTION,
                )
            )
        return NativeOperationExitCarrierV1.mint(
            site=site,
            operator=operation.operator,
            operands=(left, right),
            coordinates=(left_coord, right_coord),
        )
    return operation(left, right, site)


@dataclass(frozen=True)
class SubscriptAugAssignSugar(Sugar):
    """``receiver[index] OP= rhs`` — get once, operate, setitem last.

    Python evaluation law (load-bearing):

      1. Evaluate ``receiver`` once
      2. Evaluate ``index`` once
      3. ``current = receiver.subscript(index)``  (getitem) — **before** RHS
      4. Evaluate ``rhs``
      5. ``result = current OP rhs`` via explicit ``InplaceThenBinaryProjector``
      6. ``receiver.setitem(index, result)`` last

    Composition uses the outcome/carrier ``and_then`` law directly
    (``Complete`` short-circuits RaiseValue; ``Incomplete``/carriers/ExitSet
    compose themselves).  No bespoke control-kind ladder.

    Read, arithmetic, and write use **distinct** occurrence sites
    (``get_site``, ``op_site`` = operator-token interval, ``set_site``).
    """

    receiver: Sugar
    index: Sugar
    rhs: Sugar
    operation: InplaceThenBinaryProjector
    get_site: object = dataclass_field(compare=False)
    op_site: object = dataclass_field(compare=False)
    set_site: object = dataclass_field(compare=False)
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        # Receiver and index once each — closed over for get and setitem.
        # Outcome composition law owns control: no isinstance ladder on faces.
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.index.desugar(ctx).and_then(
                lambda index: receiver.subscript(index, self.get_site).and_then(
                    lambda current: self.rhs.desugar(ctx).and_then(
                        lambda right: project_augmented(
                            current, right, self.operation, self.op_site
                        ).and_then(
                            lambda result: self._store(receiver, index, result)
                        )
                    )
                )
            )
        )

    def _store(self, receiver, index, result) -> Outcome:
        """setitem last — formal operands stay undischarged carriers.

        Matches ``SubscriptStoreEffectSugar``: any formal among receiver /
        index / result mints the n-ary ``setitem`` demand so caller actuals
        can discharge it.  Decided ground receivers call Floor ``setitem``
        directly.  No receiver-type spelling arms.
        """
        coordinates = tuple(
            getattr(operand, "formal_coordinate", None)
            for operand in (receiver, index, result)
        )
        if any(coordinate is not None for coordinate in coordinates):
            from sugar_lift_py_tests.sugar.store_effect_sugar import (
                SubscriptStoreEffectSugar,
            )

            return SubscriptStoreEffectSugar.mint_setitem_carrier(
                site=self.set_site,
                receiver=receiver,
                index=index,
                value=result,
            )
        if not receiver.runtime_type_is_decided():
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner="SubscriptAugAssignSugar._store",
                blame=self.set_site,
                observed="undischarged augmented subscript store over undecided receiver",
                requested=(
                    "NativeOperationExitCarrierV1 n-ary setitem demand over "
                    "receiver, key, and result formal coordinates"
                ),
                fix=(
                    "attach formal coordinates via AugAssign.substitute store-target "
                    "law (same door as Assign); do not invent setitem completion"
                ),
            )
        return receiver.setitem(index, result, self.set_site)

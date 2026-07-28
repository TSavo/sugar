from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
)
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class AugAssignSugar(Sugar):
    """Lexical Name ``x OP= rhs`` — authenticated inplace owns the rebind.

    Composition (same substrate as attribute/subscript, store replaced by
    lexical rebind):

      1. Evaluate ``left`` (prior binding) once
      2. Evaluate ``rhs`` once
      3. ``result = project_augmented / project_inplace`` (iadd edge, NotImplemented law)
      4. On success: ``ScopeRebind(name, result)`` — iadd result IS the binding
      5. On halt: no ScopeRebind (and_then / RaiseValue law) — prior binding stands

    Substitute does **not** thread ``_make_binop`` (__add__) as the rebind.
    Later name uses stay as Name and read the temporal ScopeRebind.  Dual-eval
    of discarded project_inplace + add-binding is the forbidden shape.
    """

    name: str
    left: Sugar
    right: Sugar
    operator: str
    operation: Callable
    op_site: object = dataclass_field(compare=False)
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
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
        from sugar_lift_py_tests.outcome import Complete

        return self.left.desugar(ctx).and_then(
            lambda left: self.right.desugar(ctx).and_then(
                lambda right: project_augmented(
                    left,
                    right,
                    operator=self.operator,
                    projector=self.operation,
                    site=self.op_site,
                ).and_then(
                    lambda result: Complete(ScopeRebind(self.name, result))
                )
            )
        )


def project_augmented(
    left,
    right,
    *,
    operator: str,
    projector: Callable,
    site,
) -> Outcome:
    """Mint formal i* demand, or project ground through the explicit projector.

    ``operator`` is the carrier name from ``BinaryOperator.inplace_operator``
    (e.g. ``iadd``).  ``projector`` is the explicit ``project_iadd`` function.
    Projector absence is an honorable red — never mint ordinary binary.
    """
    left_coord = getattr(left, "formal_coordinate", None)
    right_coord = getattr(right, "formal_coordinate", None)
    if left_coord is not None or right_coord is not None:
        if operator not in _NATIVE_OPERATION_PROJECTORS:
            from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
            from sugar_lift_py_tests.gap.panic import construction_panic

            construction_panic(
                ConstructionGap(
                    owner="project_augmented",
                    blame=str(site),
                    observed=(
                        f"formal AugAssign requires enrolled projector "
                        f"operator={operator!r}; projector is ABSENT"
                    ),
                    requested=f"explicit project_* enrolled as operator={operator!r}",
                    fix=(
                        f"enroll {operator!r} on _NATIVE_OPERATION_PROJECTORS; "
                        "do not mint ordinary binary as a silent stand-in"
                    ),
                    gap_kind=GapKind.FLOOR,
                    gap_locus=GapLocus.CONSTRUCTION,
                )
            )
        return NativeOperationExitCarrierV1.mint(
            site=site,
            operator=operator,
            operands=(left, right),
            coordinates=(left_coord, right_coord),
        )
    return projector(left, right, site)


@dataclass(frozen=True)
class SubscriptAugAssignSugar(Sugar):
    """``receiver[index] OP= rhs`` — get once, operate, setitem last.

    Composition uses the outcome/carrier ``and_then`` law directly.
    ``operation`` is an explicit ``project_*`` function; ``operator`` is the
    carrier name from the source BinaryOperator class.
    ``op_site`` is the structural operator gap minted before substitute.
    """

    receiver: Sugar
    index: Sugar
    rhs: Sugar
    operator: str
    operation: Callable
    get_site: object = dataclass_field(compare=False)
    op_site: object = dataclass_field(compare=False)
    set_site: object = dataclass_field(compare=False)
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.index.desugar(ctx).and_then(
                lambda index: receiver.subscript(index, self.get_site).and_then(
                    lambda current: self.rhs.desugar(ctx).and_then(
                        lambda right: project_augmented(
                            current,
                            right,
                            operator=self.operator,
                            projector=self.operation,
                            site=self.op_site,
                        ).and_then(
                            lambda result: self._store(receiver, index, result)
                        )
                    )
                )
            )
        )

    def _store(self, receiver, index, result) -> Outcome:
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


@dataclass(frozen=True)
class AttributeAugAssignSugar(Sugar):
    """``receiver.attr OP= rhs`` — get once, operate, setattr last.

    Same substrate as ``SubscriptAugAssignSugar``:

      1. Evaluate ``receiver`` once
      2. ``current = attribute_named / attribute`` **before** RHS
      3. Evaluate ``rhs``
      4. ``result = current OP rhs`` via ``project_augmented`` / inplace edge
      5. ``setattr`` last (formal ``setattr_named`` mint or Floor setattr)

    Composition is outcome/carrier ``and_then`` only — no control-kind ladder.
    """

    receiver: Sugar
    attr: str
    rhs: Sugar
    operator: str
    operation: Callable
    get_site: object = dataclass_field(compare=False)
    op_site: object = dataclass_field(compare=False)
    set_site: object = dataclass_field(compare=False)
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        # Ordering: receiver → producer-owned get → RHS → inplace → producer-owned setattr.
        # Get/store are AttributeSugar / AttributeStoreEffectSugar doors only.
        from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar
        from sugar_lift_py_tests.sugar.store_effect_sugar import (
            AttributeStoreEffectSugar,
        )

        return self.receiver.desugar(ctx).and_then(
            lambda receiver: AttributeSugar.project_attribute(
                receiver, self.attr, self.get_site, ctx
            ).and_then(
                lambda current: self.rhs.desugar(ctx).and_then(
                    lambda right: project_augmented(
                        current,
                        right,
                        operator=self.operator,
                        projector=self.operation,
                        site=self.op_site,
                    ).and_then(
                        lambda result: AttributeStoreEffectSugar.project_setattr(
                            receiver, self.attr, result, self.set_site
                        )
                    )
                )
            )
        )

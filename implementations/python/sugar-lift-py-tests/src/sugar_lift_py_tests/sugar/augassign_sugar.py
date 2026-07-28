from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

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


def _chain(outcome, step):
    """Continue only on completed ordinary values / carriers; halt faces stay loud."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor import RaiseValue
    from sugar_lift_py_tests.outcome import Complete, Incomplete
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    if isinstance(outcome, NativeOperationExitCarrierV1):
        return outcome.and_then(step)
    if isinstance(outcome, Incomplete):
        return outcome
    if isinstance(outcome, ExitSet):
        # Multi-arm get/add: only continue completed faces via ExitSet.and_then
        return outcome.and_then(step)
    if isinstance(outcome, Complete):
        if isinstance(outcome.value, RaiseValue):
            # Get/arithmetic halt: do not evaluate RHS/store (RaiseValue short-circuit).
            return outcome
        return step(outcome.value)
    # Other outcomes (e.g. Complete-like) try step only if and_then exists.
    and_then = getattr(outcome, "and_then", None)
    if and_then is not None:
        return and_then(step)
    return outcome


def _augmented_binary(left, right, op_kind: str, site) -> Outcome:
    """In-place when Floor authorizes; otherwise ordinary binary.

    Does **not** invent a shared ``iadd`` native-operation projector.  If a
    future formal ``iadd`` mint/projector is required for symbolic carriers,
    bank that red with the exact contract rather than emulating it here.

    Formal operands mint a native-operation demand **before** Floor conversion
    can turn a ground left into a bare SymbolicValue (which would erase the
    authenticated ground arithmetic face after discharge).  Prefer enrolled
    ``iadd`` (etc.) projectors when present; else the ordinary binary name.

    Floor law (decided, non-formal receivers):
      1. Prefer ``left.iadd(right, site)`` when present and not Raise/NotImplemented
      2. Else ``left.add(right, site)`` for ``+`` (and the matching binary for
         other op kinds via the same names as BinOpSugar)
    """
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
        _NATIVE_OPERATION_PROJECTORS,
    )
    from sugar_lift_py_tests.floor import RaiseValue
    from sugar_lift_py_tests.outcome import Complete

    method_by_kind = {
        "Add": ("iadd", "add"),
        "Sub": ("isub", "subtract"),
        "Mult": ("imul", "multiply"),
        "Div": ("itruediv", "divide"),
        "FloorDiv": ("ifloordiv", "floor_divide"),
        "Mod": ("imod", "modulo"),
        "Pow": ("ipow", "power"),
        "BitAnd": ("iand", "bitwise_and"),
        "BitOr": ("ior", "bitwise_or"),
        "BitXor": ("ixor", "bitwise_xor"),
        "LShift": ("ilshift", "left_shift"),
        "RShift": ("irshift", "right_shift"),
        "MatMult": ("imatmul", "matrix_multiply"),
    }
    names = method_by_kind.get(op_kind, (None, "add"))
    inplace_name, binary_name = names

    left_coord = getattr(left, "formal_coordinate", None)
    right_coord = getattr(right, "formal_coordinate", None)
    if left_coord is not None or right_coord is not None:
        # Formal path: mint demand; discharge supplies actuals to the projector.
        # Prefer enrolled i* projectors; do not invent iadd here when missing.
        if inplace_name is not None and inplace_name in _NATIVE_OPERATION_PROJECTORS:
            operator = inplace_name
        else:
            operator = binary_name
        if operator not in _NATIVE_OPERATION_PROJECTORS:
            from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
            from sugar_lift_py_tests.gap.panic import construction_panic

            construction_panic(
                ConstructionGap(
                    owner="SubscriptAugAssignSugar._augmented_binary",
                    blame=str(site),
                    observed=(
                        f"formal AugAssign {op_kind} needs projector "
                        f"{inplace_name!r} or {binary_name!r}; neither enrolled"
                    ),
                    requested=(
                        "shared authenticated native-operation projector: "
                        f"operator={inplace_name!r} with "
                        f"lambda left, right, site: left.{inplace_name}(right, site) "
                        f"or operator={binary_name!r} already used by BinOp"
                    ),
                    fix=(
                        "enroll the i* / binary projector on "
                        "_NATIVE_OPERATION_PROJECTORS; do not emulate formal "
                        "iadd inside AugAssign"
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

    if inplace_name is not None:
        inplace = getattr(left, inplace_name, None)
        if callable(inplace):
            projected = inplace(right, site)
            # Floor NotImplemented-style gaps fall through; RaiseValue stops.
            if isinstance(projected, Complete) and isinstance(
                projected.value, RaiseValue
            ):
                return projected
            if isinstance(projected, Complete):
                return projected
            # Incomplete / ExitSet from inplace: surface them (authorized faces).
            from sugar_lift_py_tests.outcome import Incomplete
            from sugar_lift_py_tests.outcome.exit_set import ExitSet

            if isinstance(projected, (Incomplete, ExitSet)):
                return projected

    binary = getattr(left, binary_name, None)
    if not callable(binary):
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
        from sugar_lift_py_tests.gap.panic import construction_panic

        construction_panic(
            ConstructionGap(
                owner="SubscriptAugAssignSugar._augmented_binary",
                blame=str(site),
                observed=f"{type(left).__name__} has no {binary_name} for AugAssign {op_kind}",
                requested=(
                    "Floor binary (or authorized i*) for augmented assignment, "
                    "or a shared authenticated iadd native-operation projector "
                    "minted as operator='iadd' with projector "
                    "lambda left, right, site: left.iadd(right, site)"
                ),
                fix=(
                    "implement Floor iadd/add for this value species, or enroll "
                    "a formal iadd producer/projector rather than emulating "
                    "inside AugAssign"
                ),
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        )
    return binary(right, site)


@dataclass(frozen=True)
class SubscriptAugAssignSugar(Sugar):
    """``receiver[index] OP= rhs`` — get once, operate, setitem last.

    Python evaluation law (load-bearing):

      1. Evaluate ``receiver`` once
      2. Evaluate ``index`` once
      3. ``current = receiver.subscript(index)``  (getitem) — **before** RHS
      4. Evaluate ``rhs``
      5. ``result = current OP rhs`` (inplace when Floor authorizes, else binary)
      6. ``receiver.setitem(index, result)`` last

    Get halt blocks RHS / arithmetic / store.  RHS or arithmetic halt blocks
    the store.  Store halt preserves prior get/arithmetic testimony (no
    fabricated completion).  Read, arithmetic, and write use **distinct**
    occurrence sites (``get_site``, ``op_site``, ``set_site``).
    """

    receiver: Sugar
    index: Sugar
    rhs: Sugar
    op_kind: str
    get_site: object = dataclass_field(compare=False)
    op_site: object = dataclass_field(compare=False)
    set_site: object = dataclass_field(compare=False)
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        # Receiver and index once each — closed over for get and setitem.
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.index.desugar(ctx).and_then(
                lambda index: self._after_receiver_index(receiver, index, ctx)
            )
        )

    def _after_receiver_index(self, receiver, index, ctx) -> Outcome:
        get_outcome = receiver.subscript(index, self.get_site)

        def after_get(current):
            return self.rhs.desugar(ctx).and_then(
                lambda right: self._after_rhs(receiver, index, current, right)
            )

        return _chain(get_outcome, after_get)

    def _after_rhs(self, receiver, index, current, right) -> Outcome:
        op_outcome = _augmented_binary(current, right, self.op_kind, self.op_site)

        def after_op(result):
            return self._store(receiver, index, result)

        return _chain(op_outcome, after_op)

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

"""In-place binary operation (AugAssign): the established Floor edge.

Route is always:

    InplaceBinaryOperatorOperation(surface, right, …)
        → receiver.inplace_binary_operator_with(operation, ctx)

``ObjectValue`` overrides the floor method to authenticate ``__iadd__``-family
data-model methods.  Species without an override take
``operation.inplace_default`` → ordinary binary by surface operator.

There is no second protocol (no free ``left.iadd`` methods on FloorValue).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, ClassVar

# Surface operator spelling (as ObjectValue / BinaryOperator.symbol) → Floor binary,
# applied under the caller's context.
_SURFACE_BINARY: dict[str, Callable] = {
    "+": lambda left, right, site, ctx: left.add(right, site, ctx),
    "-": lambda left, right, site, ctx: left.subtract(right, site, ctx),
    "*": lambda left, right, site, ctx: left.multiply(right, site, ctx),
    "/": lambda left, right, site, ctx: left.divide(right, site, ctx),
    "//": lambda left, right, site, ctx: left.floor_divide(right, site, ctx),
    "%": lambda left, right, site, ctx: left.modulo(right, site, ctx),
    "**": lambda left, right, site, ctx: left.power(right, site, ctx),
    "@": lambda left, right, site, ctx: left.matrix_multiply(right, site, ctx),
    "&": lambda left, right, site, ctx: left.bitwise_and(right, site, ctx),
    "|": lambda left, right, site, ctx: left.bitwise_or(right, site, ctx),
    "^": lambda left, right, site, ctx: left.bitwise_xor(right, site, ctx),
    "<<": lambda left, right, site, ctx: left.left_shift(right, site, ctx),
    ">>": lambda left, right, site, ctx: left.right_shift(right, site, ctx),
}


@dataclass(frozen=True)
class InplaceBinaryOperatorOperation:
    """One inplace binary demand against one left receiver and one right operand.

    ``operator`` is the surface spelling (``+``, ``-``, …) matching
    ``ObjectValue``'s ``_INPLACE_BINARY_DUNDER_METHODS`` keys — not the carrier
    name ``iadd``.
    """

    method_name: ClassVar[str] = "inplace_binary_operator_with"

    operator: str
    right: Any
    owner: str
    blame: object

    @property
    def site(self) -> object:
        """The source locus of this demand (recorded under ``blame``).

        Consumers that reduce this operation over an undecided receiver -- an
        ImportMemberValue under an enrolled stdlib body -- read
        ``operation.site``. Sibling operations that lacked it raised
        AttributeError and voided the file (see SubscriptOperation.site).
        """
        return self.blame

    def inplace_default(self, receiver, ctx) -> Any:
        """Species without inplace override: ordinary binary by surface operator,
        under the caller's context."""
        binary = _SURFACE_BINARY.get(self.operator)
        if binary is None:
            from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
            from sugar_lift_py_tests.gap.panic import construction_panic

            construction_panic(
                ConstructionGap(
                    owner="InplaceBinaryOperatorOperation.inplace_default",
                    blame=str(self.blame),
                    observed=f"unknown surface operator {self.operator!r}",
                    requested="a surface operator enrolled in _SURFACE_BINARY",
                    fix="enroll the surface spelling on _SURFACE_BINARY",
                    gap_kind=GapKind.FLOOR,
                    gap_locus=GapLocus.CONSTRUCTION,
                )
            )
        return binary(receiver, self.right, self.blame, ctx)


def after_inplace_notimplemented(projected, binary_fallback: Callable):
    """NotImplemented (raw or completed) → ordinary binary; all other faces stay.

    Halts, split or owing arm sets, carriers, and other completed values
    surface unchanged — they never authorize binary fallback.
    """
    from sugar_lift_py_tests.outcome import (
        NativeOperationExitCarrierV1,
        Outcome,
        outcome_to_exitset,
    )

    if projected is NotImplemented:
        return binary_fallback()
    if isinstance(projected, Outcome) and not isinstance(
        projected, NativeOperationExitCarrierV1
    ):
        exits = outcome_to_exitset(projected)
        # One completed NotImplemented arm under truth that owes nothing.
        if exits.completed_value() is NotImplemented and not exits.owed_items():
            return binary_fallback()
    return projected


def discharge_inplace(left, right, site, ctx, *, surface: str):
    """Production projector body: established floor edge + NotImplemented law.

    1. ``left.inplace_binary_operator_with(InplaceBinaryOperatorOperation(...))``
    2. If the floor yields raw/completed NotImplemented → corresponding binary
    3. Otherwise return the floor face unchanged

    Both the in-place method and the binary fallback apply under ``ctx``.
    """
    binary = _SURFACE_BINARY.get(surface)
    if binary is None:
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
        from sugar_lift_py_tests.gap.panic import construction_panic

        construction_panic(
            ConstructionGap(
                owner="discharge_inplace",
                blame=str(site),
                observed=f"unknown surface operator {surface!r}",
                requested="a surface operator enrolled in _SURFACE_BINARY",
                fix="enroll the surface spelling on _SURFACE_BINARY",
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        )
    projected = left.inplace_binary_operator_with(
        InplaceBinaryOperatorOperation(
            operator=surface,
            right=right,
            owner=f"inplace:{surface}",
            blame=site,
        ),
        ctx,
    )
    return after_inplace_notimplemented(
        projected, lambda: binary(left, right, site, ctx)
    )

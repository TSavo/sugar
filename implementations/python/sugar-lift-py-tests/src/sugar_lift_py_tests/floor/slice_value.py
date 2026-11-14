from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class SliceValue(FloorValue):
    lower: FloorValue | None
    upper: FloorValue | None
    step: FloorValue | None

    def setitem(self, index, value, site, ctx):
        del index, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="SliceValue.setitem"
        )

    def delitem(self, index, site, ctx):
        del index, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="SliceValue.delitem"
        )

    def setattr(self, name, value, site, ctx):
        del name, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="SliceValue.setattr"
        )

    def delattr(self, name, site, ctx):
        del name, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="SliceValue.delattr"
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "py.slice",
            [
                _optional_slice_term(self.lower, owner=owner),
                _optional_slice_term(self.upper, owner=owner),
                _optional_slice_term(self.step, owner=owner),
            ],
        )


def construct_slice(lower, upper, step, site):
    """``slice(lower, upper, step)``: the one construction of a slice value.

    A slice is an operation over its bounds.  A function parameter in any
    bound (``xs[start:]``) is decided by its caller's actual, so the slice
    itself defers: the ``slice`` carrier, one coordinate slot per bound, whose
    projector rebuilds the slice here from the actuals (and defers again when
    an actual is still its own caller's formal).  Every consumer of the slice
    (a read through ``discharge_subscript``, a store, a delete) continues on
    the slice the caller decided, never on a bound it cannot see.  An omitted
    bound stands in the carrier as ``None`` (``NoneValue``), what Python fills
    it with.  With no parameter bound the slice completes here.
    """
    from sugar_lift_py_tests.outcome import ExitSet

    bounds = (lower, upper, step)
    coordinates = tuple(getattr(bound, "formal_coordinate", None) for bound in bounds)
    if all(coordinate is None for coordinate in coordinates):
        return ExitSet.completed(SliceValue(lower, upper, step))
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor.none_value import NoneValue

    return NativeOperationExitCarrierV1.mint(
        site=site,
        operator="slice",
        operands=tuple(NoneValue() if bound is None else bound for bound in bounds),
        coordinates=coordinates,
    )


def _optional_slice_term(value: FloorValue | None, *, owner: str):
    from sugar_lift_py_tests.ir import ctor

    if value is None:
        return ctor("None", [])
    return value.to_term(owner=owner)

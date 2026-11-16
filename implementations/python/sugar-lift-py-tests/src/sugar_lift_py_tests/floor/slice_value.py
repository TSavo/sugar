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
        del value, ctx
        from sugar_lift_py_tests.floor.ground_exit import builtin_attribute_store_exit

        return builtin_attribute_store_exit(name, site=site, owner="SliceValue.setattr")

    def delattr(self, name, site, ctx):
        del ctx
        from sugar_lift_py_tests.floor.ground_exit import builtin_attribute_store_exit

        return builtin_attribute_store_exit(name, site=site, owner="SliceValue.delattr")

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


def construct_slice(lower, upper, step):
    """``slice(lower, upper, step)``: the one construction of a slice value.

    Python's ``BUILD_SLICE`` takes any objects as bounds and never raises, so
    the slice completes here whatever its bounds are -- a function
    parameter's (``xs[start:]``) included, which stands in the slice as its
    symbolic value.  What the bounds mean is asked by the slice's consumer (a
    read through ``discharge_subscript``, a store, a delete): the receiver's
    own floor reads a bound it does not decide as the undecided read or
    mutation, every halt face kept.  No slice waits on a caller's actual
    (#7757)."""
    from sugar_lift_py_tests.outcome import ExitSet

    return ExitSet.completed(SliceValue(lower, upper, step))


def _optional_slice_term(value: FloorValue | None, *, owner: str):
    from sugar_lift_py_tests.ir import ctor

    if value is None:
        return ctor("None", [])
    return value.to_term(owner=owner)

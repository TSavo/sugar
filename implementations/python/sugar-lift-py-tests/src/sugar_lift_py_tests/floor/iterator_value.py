"""Authenticated finite iterators for exact sequence Floors.

``ListIteratorValue`` / ``TupleIteratorValue`` are the ``__iter__`` results of
constructed lists/tuples.  ``__next__`` yields ``NextResult(value, advanced)``
or a named ``StopIteration`` face — never a silent end, never a wrong exception
identity for exhaustion.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .floor_value import FloorValue


@dataclass(frozen=True)
class NextResult(FloorValue):
    """Successful synchronous ``__next__``: yielded value + advanced iterator."""

    value: FloorValue
    advanced: FloorValue

    def denotes_value(self) -> bool:
        return True


@dataclass(frozen=True)
class ListIteratorValue(FloorValue):
    """Iterator over authenticated ``ListValue`` members (immutable index)."""

    elements: tuple
    index: int = 0

    def denotes_value(self) -> bool:
        return True

    def next_with(self, operation, ctx):
        del ctx
        from sugar_lift_py_tests.outcome import Complete

        if self.index >= len(self.elements):
            return _stop_iteration(operation.blame, owner=operation.owner)
        yielded = self.elements[self.index]
        advanced = replace(self, index=self.index + 1)
        return Complete(NextResult(yielded, advanced))


@dataclass(frozen=True)
class TupleIteratorValue(FloorValue):
    """Iterator over authenticated ``TupleValue`` members (immutable index)."""

    elements: tuple
    index: int = 0

    def denotes_value(self) -> bool:
        return True

    def next_with(self, operation, ctx):
        del ctx
        from sugar_lift_py_tests.outcome import Complete

        if self.index >= len(self.elements):
            return _stop_iteration(operation.blame, owner=operation.owner)
        yielded = self.elements[self.index]
        advanced = replace(self, index=self.index + 1)
        return Complete(NextResult(yielded, advanced))


def _stop_iteration(site, *, owner: str):
    """Named StopIteration — not TypeError, not a silent Incomplete without identity."""
    from sugar_lift_py_tests.floor import RaiseValue
    from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
    from sugar_lift_py_tests.outcome import Complete, Incomplete

    if hasattr(site, "filename") and hasattr(site, "line"):
        projected = ground_exceptional_exit(
            exception_name="StopIteration",
            site=site,
            owner=owner,
        )
        if isinstance(projected, Complete) and isinstance(projected.value, RaiseValue):
            # Iterator exhaustion is a control-face halt for consumers.
            return Incomplete(projected.value.effect)
        return projected
    # Synthetic blame: still name StopIteration on the effect without fragment cite.
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.ir import ctor, str_const

    identity = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("StopIteration")],
    )
    return Incomplete(
        RaiseEffect(
            exception_name="StopIteration",
            blame=str(site),
            exception_type_coordinate=identity,
            exception_type_mro=(identity,),
            occurrence=str(site),
            producer_node_owner=owner,
        )
    )

"""Authenticated finite iterators for exact sequence Floors.

``ListIteratorValue`` / ``TupleIteratorValue`` are the ``__iter__`` results of
constructed lists/tuples.  ``__next__`` yields ``NextResult(value, advanced)``
or a named ``StopIteration`` face — never a silent end, never a wrong exception
identity for exhaustion.

Exhaustion cites the same ground-exit authority door as other named exceptional
faces: authenticated operation occurrence (source fragment) + builtin
``StopIteration`` type coordinate.  Synthetic string blame cannot mint
identity from spelling.
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

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:list_iterator",
            (
                ctor(
                    "array",
                    tuple(value.to_term(owner=owner) for value in self.elements),
                ),
                TermValue(self.index).to_term(owner=owner),
            ),
            symbol_kind="coordinate",
        )

    def setattr(self, name, value, site):
        del name, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError",
            site=site,
            owner="ListIteratorValue.setattr",
        )

    def delattr(self, name, site):
        del name
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError",
            site=site,
            owner="ListIteratorValue.delattr",
        )

    def setitem(self, index, value, site):
        del index, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="ListIteratorValue.setitem"
        )

    def delitem(self, index, site):
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="ListIteratorValue.delitem"
        )

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

    def setattr(self, name, value, site):
        del name, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError",
            site=site,
            owner="TupleIteratorValue.setattr",
        )

    def delattr(self, name, site):
        del name
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError",
            site=site,
            owner="TupleIteratorValue.delattr",
        )

    def setitem(self, index, value, site):
        del index, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="TupleIteratorValue.setitem"
        )

    def delitem(self, index, site):
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="TupleIteratorValue.delitem"
        )

    def next_with(self, operation, ctx):
        del ctx
        from sugar_lift_py_tests.outcome import Complete

        if self.index >= len(self.elements):
            return _stop_iteration(operation.blame, owner=operation.owner)
        yielded = self.elements[self.index]
        advanced = replace(self, index=self.index + 1)
        return Complete(NextResult(yielded, advanced))


def _stop_iteration(site, *, owner: str):
    """Named StopIteration through the ground exceptional-exit door only.

    Same authority as other named ground exits: fragment locus + builtin type
    coordinate from ``ground_exceptional_exit`` / ``ground_raise_effect``.
    String or synthetic blame cannot fabricate ``python:exception_type_identity``
    or an occurrence from spelling — that path is typed-loud at the ground door.
    """
    from sugar_lift_py_tests.floor import RaiseValue
    from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
    from sugar_lift_py_tests.outcome import Complete, Incomplete

    projected = ground_exceptional_exit(
        exception_name="StopIteration",
        site=site,
        owner=owner,
    )
    if isinstance(projected, Complete) and isinstance(projected.value, RaiseValue):
        # Iterator exhaustion is a control-face halt for consumers.
        return Incomplete(projected.value.effect)
    return projected

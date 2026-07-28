from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Term

from .floor_value import FloorValue


@dataclass(frozen=True)
class EncodedStringValue(FloorValue):
    """A string built by indexing a constant table per output character.

    `table` is the encode table (each entry an ordinal); `indices` is the
    per-character index term into that table (each a BV term over the input
    byte vars). A single `table[index]` reduces to one index; `+` concatenation
    appends index tuples. The body sugar lowers this to a `str.eq-bv-blocks`
    universe atom -- the construction IS the constraint.
    """

    table: tuple[int, ...]
    indices: tuple[Term, ...]

    def setitem(self, index, value, site):
        del index, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="EncodedStringValue.setitem",
        )

    def delitem(self, index, site):
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="EncodedStringValue.delitem",
        )

    def binary_operator_with(self, operation, ctx):
        return operation.binary_encoded_string(self, ctx)

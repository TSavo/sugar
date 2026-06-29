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

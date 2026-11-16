"""A ``for`` in a class body is the one loop recurrence, read by the namespace.

#8957 deleted the rewrite-time unroll: every loop of a threaded block is the
one loop recurrence (``LoopRecurrenceStatement``, built as
``LoopRecurrenceSugar``).  A class body is threaded as every block is, but
its namespace admitted no compound statement but ``if`` and ``with``, so a
class-body ``for`` was refused as ``unsupported class member
LoopRecurrenceStatement`` and three pandas board files (3.0.3) became
construction panics: ``tests/series/test_arithmetic.py:45``
(``TestSeriesFlexArithmetic``), ``io/stata.py:715`` (``StataMissingValue``),
``tests/indexing/test_coercion.py:729`` (``TestReplaceSeriesCoercion``).

The loop is a statement of the class body's block like any other: the block
reducer runs its sugar, and each name it binds in the class namespace (its
target, its body's assignments) or writes that the body bound before it (an
object it changes) is a row under the key the loop publishes it under
(``LoopRecurrenceStatement.written_keys``).  No second unroll.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from sugar_lift_py_tests.floor import ConstructedClassFieldV1
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.sugar.class_definition_sugar import ClassDefinitionSugar
from sugar_lift_py_tests.sugar.loop_recurrence_sugar import LoopRecurrenceSugar
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.panic import SugarNotWritten


def _class(src: str, name: str) -> ClassDef:
    """The class ``name`` of ``src``, opened as production opens a file: written
    under a workspace root and read through the one source door
    (``open_source_file_for_construction``), so its source CID is the text's
    own.  A CID minted any other way is refused at the import-use mint
    (``authenticated import-use source CID is stale``)."""
    root = Path(tempfile.mkdtemp(prefix="class-body-loop-"))
    path = root / f"{name.lower()}.py"
    path.write_text(src, encoding="utf-8")
    source = open_source_file_for_construction(path, root=root)
    return next(
        node
        for node in source.nodes()
        if isinstance(node, ClassDef) and node.name == name
    )


def _row_names(sugar) -> set:
    return {
        field.name for field in sugar.fields if isinstance(field, ConstructedClassFieldV1)
    }


MINIMAL = (
    "class C:\n"
    "    pairs = []\n"
    "    for op in ['add', 'sub']:\n"
    "        fv = 0\n"
    "        pairs.append((op, fv))\n"
)


def test_a_class_body_for_is_the_one_loop_recurrence() -> None:
    sugar = _class(MINIMAL, "C").sugar()
    assert isinstance(sugar, ClassDefinitionSugar)
    assert any(isinstance(statement, LoopRecurrenceSugar) for statement in sugar.body)
    # The target and the body's assignment are the class's names; the list
    # the loop appends to is the row the body bound before it.
    assert {"pairs", "op", "fv"} <= _row_names(sugar)


def test_a_class_body_for_builds_the_namespace_it_leaves() -> None:
    value = _class(MINIMAL, "C").sugar().desugar().completed_value()
    assert {"pairs", "op", "fv"} <= {field.name for field in value.class_fields}


# ``pandas/tests/series/test_arithmetic.py:110`` (``TestSeriesFlexArithmetic``).
ARITHMETIC_SHAPE = (
    "import operator\n"
    "\n"
    "class TestSeriesFlexArithmetic:\n"
    "    pairings = [(operator.truediv, operator.truediv, 1)]\n"
    "    for op in ['add', 'sub', 'mul', 'pow', 'truediv', 'floordiv']:\n"
    "        fv = 0\n"
    "        lequiv = getattr(operator, op)\n"
    "        requiv = lambda x, y, op=op: getattr(operator, op)(y, x)\n"
    "        pairings.append((lequiv, lequiv, fv))\n"
    "        pairings.append((requiv, requiv, fv))\n"
    "\n"
    "    def test_operators_combine(self, op, equiv_op, fv):\n"
    "        return op\n"
)


def test_the_arithmetic_class_body_loop_builds() -> None:
    sugar = _class(ARITHMETIC_SHAPE, "TestSeriesFlexArithmetic").sugar()
    assert isinstance(sugar, ClassDefinitionSugar)
    assert {"pairings", "op", "fv", "lequiv", "requiv"} <= _row_names(sugar)


# ``pandas/io/stata.py:752`` (``StataMissingValue``): a nested loop, and a
# later loop over the name an earlier one bound.
STATA_SHAPE = (
    "class StataMissingValue:\n"
    "    MISSING_VALUES = {}\n"
    "    bases = (101, 32741, 2147483621)\n"
    "    for b in bases:\n"
    "        MISSING_VALUES[b] = '.'\n"
    "        for i in range(1, 27):\n"
    "            MISSING_VALUES[i + b] = '.' + chr(96 + i)\n"
    "\n"
    "    base = 0\n"
    "    for i in range(27):\n"
    "        key = base\n"
    "        MISSING_VALUES[key] = '.'\n"
    "        if i > 0:\n"
    "            MISSING_VALUES[key] += chr(96 + i)\n"
    "        base = base + 1\n"
)


def test_the_stata_class_body_loops_build() -> None:
    sugar = _class(STATA_SHAPE, "StataMissingValue").sugar()
    assert isinstance(sugar, ClassDefinitionSugar)
    assert {"MISSING_VALUES", "b", "i", "key", "base"} <= _row_names(sugar)


# ``pandas/tests/indexing/test_coercion.py:744`` (``TestReplaceSeriesCoercion``).
COERCION_SHAPE = (
    "class TestReplaceSeriesCoercion:\n"
    "    rep = {}\n"
    "    rep['object'] = ['a', 'b']\n"
    "    for tz in ['UTC', 'US/Eastern']:\n"
    "        key = f'datetime64[ns, {tz}]'\n"
    "        rep[key] = [tz, tz]\n"
    "\n"
    "    rep['timedelta64[us]'] = ['1 day', '2 day']\n"
)


def test_the_coercion_class_body_loop_builds() -> None:
    sugar = _class(COERCION_SHAPE, "TestReplaceSeriesCoercion").sugar()
    assert isinstance(sugar, ClassDefinitionSugar)
    assert {"rep", "tz", "key"} <= _row_names(sugar)


# ``pandas/io/stata.py`` (pandas v3.0.3) as the board reads it: its stdlib
# and numpy imports (lines 13-34), the module-level ``_date_formats`` list
# and epochs (lines 154-158), and ``StataMissingValue`` verbatim (lines
# 715-846).  The class body's float loops each splice an ``if``'s phi after
# the ``if``: a join of each name the arm may have changed, the module list
# ``_date_formats`` among them (a call may change any object a module name
# holds, ``container_mutation.havoc_after``).  The board on ``c29c38c95``
# refused the class with ``class field _date_formats whose statement carries
# no evaluation key`` (blame ``stata.py:763:4``, the float32 loop).
STATA_MODULE = (
    r'''
from __future__ import annotations

from collections import abc
from datetime import (
    datetime,
    timedelta,
)
from io import BytesIO
import os
import struct
import sys
from typing import (
    IO,
    TYPE_CHECKING,
    AnyStr,
    Final,
    Self,
    cast,
)
import warnings

import numpy as np


_date_formats = ["%tc", "%tC", "%td", "%d", "%tw", "%tm", "%tq", "%th", "%ty"]


stata_epoch: Final = datetime(1960, 1, 1)
unix_epoch: Final = datetime(1970, 1, 1)


class StataMissingValue:
    """
    An observation's missing value.

    Parameters
    ----------
    value : {int, float}
        The Stata missing value code

    Notes
    -----
    More information: <https://www.stata.com/help.cgi?missing>

    Integer missing values make the code '.', '.a', ..., '.z' to the ranges
    101 ... 127 (for int8), 32741 ... 32767  (for int16) and 2147483621 ...
    2147483647 (for int32).  Missing values for floating point data types are
    more complex but the pattern is simple to discern from the following table.

    np.float32 missing values (float in Stata)
    0000007f    .
    0008007f    .a
    0010007f    .b
    ...
    00c0007f    .x
    00c8007f    .y
    00d0007f    .z

    np.float64 missing values (double in Stata)
    000000000000e07f    .
    000000000001e07f    .a
    000000000002e07f    .b
    ...
    000000000018e07f    .x
    000000000019e07f    .y
    00000000001ae07f    .z
    """

    # Construct a dictionary of missing values
    MISSING_VALUES: dict[float, str] = {}
    bases: Final = (101, 32741, 2147483621)
    for b in bases:
        # Conversion to long to avoid hash issues on 32 bit platforms #8968
        MISSING_VALUES[b] = "."
        for i in range(1, 27):
            MISSING_VALUES[i + b] = "." + chr(96 + i)

    float32_base: bytes = b"\x00\x00\x00\x7f"
    increment_32: int = struct.unpack("<i", b"\x00\x08\x00\x00")[0]
    for i in range(27):
        key = struct.unpack("<f", float32_base)[0]
        MISSING_VALUES[key] = "."
        if i > 0:
            MISSING_VALUES[key] += chr(96 + i)
        int_value = struct.unpack("<i", struct.pack("<f", key))[0] + increment_32
        float32_base = struct.pack("<i", int_value)

    float64_base: bytes = b"\x00\x00\x00\x00\x00\x00\xe0\x7f"
    increment_64 = struct.unpack("q", b"\x00\x00\x00\x00\x00\x01\x00\x00")[0]
    for i in range(27):
        key = struct.unpack("<d", float64_base)[0]
        MISSING_VALUES[key] = "."
        if i > 0:
            MISSING_VALUES[key] += chr(96 + i)
        int_value = struct.unpack("q", struct.pack("<d", key))[0] + increment_64
        float64_base = struct.pack("q", int_value)

    BASE_MISSING_VALUES: Final = {
        "int8": 101,
        "int16": 32741,
        "int32": 2147483621,
        "float32": struct.unpack("<f", float32_base)[0],
        "float64": struct.unpack("<d", float64_base)[0],
    }

    def __init__(self, value: float) -> None:
        self._value = value
        # Conversion to int to avoid hash issues on 32 bit platforms #8968
        value = int(value) if value < 2147483648 else float(value)
        self._str = self.MISSING_VALUES[value]

    @property
    def string(self) -> str:
        """
        The Stata representation of the missing value: '.', '.a'..'.z'

        Returns
        -------
        str
            The representation of the missing value.
        """
        return self._str

    @property
    def value(self) -> float:
        """
        The binary representation of the missing value.

        Returns
        -------
        {int, float}
            The binary representation of the missing value.
        """
        return self._value

    def __str__(self) -> str:
        return self.string

    def __repr__(self) -> str:
        return f"{type(self)}({self})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, type(self))
            and self.string == other.string
            and self.value == other.value
        )

    @classmethod
    def get_base_missing_value(cls, dtype: np.dtype) -> float:
        if dtype.type is np.int8:
            value = cls.BASE_MISSING_VALUES["int8"]
        elif dtype.type is np.int16:
            value = cls.BASE_MISSING_VALUES["int16"]
        elif dtype.type is np.int32:
            value = cls.BASE_MISSING_VALUES["int32"]
        elif dtype.type is np.float32:
            value = cls.BASE_MISSING_VALUES["float32"]
        elif dtype.type is np.float64:
            value = cls.BASE_MISSING_VALUES["float64"]
        else:
            raise ValueError("Unsupported dtype")
        return value
'''
)


def test_the_real_stata_class_builds_or_refuses_by_name_never_unkeyed() -> None:
    """The class builds, with every name its loops bind as a row and the
    module list never one; or it is refused by a name other than the
    class-field key refusal.  Never ``_date_formats`` as a class field."""
    klass = _class(STATA_MODULE, "StataMissingValue")
    try:
        sugar = klass.sugar()
    except SugarNotWritten as refusal:
        assert "carries no evaluation key" not in str(refusal), refusal
        assert "_date_formats" not in str(refusal), refusal
        return
    assert isinstance(sugar, ClassDefinitionSugar)
    rows = _row_names(sugar)
    assert {
        "MISSING_VALUES",
        "bases",
        "b",
        "i",
        "key",
        "int_value",
        "float32_base",
        "increment_32",
        "float64_base",
        "increment_64",
        "BASE_MISSING_VALUES",
    } <= rows
    assert "_date_formats" not in rows


def test_a_source_conditional_assignment_is_no_join_phi() -> None:
    # The loop's names are read off its threaded body alone (#7757 NEW-11):
    # only the phi an ``if`` splices (its span the ``if``'s, its test the
    # join's ``BranchResultRef``) is no binding of its own.  An assignment
    # the source spells, a conditional expression included, is the class's
    # binding.
    from sugar_source_tree.nodes import Assign, If, _is_join_phi

    klass = _class(
        "class C:\n"
        "    for i in range(2):\n"
        "        if i:\n"
        "            pass\n"
        "        x = 1 if i else 2\n",
        "C",
    )
    (assign,) = tuple(node for node in klass.walk() if isinstance(node, Assign))
    if_spans = frozenset(node.span for node in klass.walk() if isinstance(node, If))
    assert not _is_join_phi(assign, if_spans)

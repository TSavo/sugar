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

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ConstructedClassFieldV1
from sugar_lift_py_tests.sugar.class_definition_sugar import ClassDefinitionSugar
from sugar_lift_py_tests.sugar.loop_recurrence_sugar import LoopRecurrenceSugar
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def _class(src: str, name: str) -> ClassDef:
    seat = f"{name}.py"
    cid = cid_of_json({"source": src, "seat": seat})
    source = SourceFile(
        (src, seat, cid),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
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


# ``pandas/io/stata.py:715`` (``StataMissingValue``, pandas 3.0.3) as it
# stands in its module: a module-level list (``_date_formats``), and a
# class-body loop whose ``if`` arm runs code (``MISSING_VALUES[key] +=
# ...``) and whose body calls an imported module (``struct.unpack``).  The
# threading splices the ``if``'s phi after it, joining every name the arm
# may have changed -- the module list among them, a name a call may rebind
# (``container_mutation.havoc_after``).  That phi is no binding of the
# class: the loop's names are the ones its source binds, so the module list
# is never read as a class field with no key (the board's construction
# panic ``class field _date_formats whose statement carries no evaluation
# key``).
STATA_MODULE_SHAPE = (
    "import struct\n"
    "\n"
    "_date_formats = ['%tc', '%tC', '%td', '%d']\n"
    "\n"
    "class StataMissingValue:\n"
    "    MISSING_VALUES: dict[float, str] = {}\n"
    "    bases = (101, 32741, 2147483621)\n"
    "    for b in bases:\n"
    "        MISSING_VALUES[b] = '.'\n"
    "        for i in range(1, 27):\n"
    "            MISSING_VALUES[i + b] = '.' + chr(96 + i)\n"
    "    float32_base: bytes = b'\\x00\\x00\\x00\\x7f'\n"
    "    increment_32: int = struct.unpack('<i', b'\\x00\\x08\\x00\\x00')[0]\n"
    "    for i in range(27):\n"
    "        key = struct.unpack('<f', float32_base)[0]\n"
    "        MISSING_VALUES[key] = '.'\n"
    "        if i > 0:\n"
    "            MISSING_VALUES[key] += chr(96 + i)\n"
    "        int_value = struct.unpack('<i', struct.pack('<f', key))[0] + increment_32\n"
    "        float32_base = struct.pack('<i', int_value)\n"
    "\n"
    "    def __init__(self, value):\n"
    "        self._value = value\n"
)


def test_a_module_name_an_if_phi_joins_in_a_class_body_loop_is_no_class_field() -> None:
    sugar = _class(STATA_MODULE_SHAPE, "StataMissingValue").sugar()
    assert isinstance(sugar, ClassDefinitionSugar)
    rows = _row_names(sugar)
    assert {
        "MISSING_VALUES",
        "b",
        "i",
        "key",
        "int_value",
        "float32_base",
        "increment_32",
    } <= rows
    assert "_date_formats" not in rows


def test_a_source_conditional_assignment_is_no_join_phi() -> None:
    # The loop's names are read off its threaded body alone (#7757 NEW-11):
    # only the phi a join splices (its test the join's ``BranchResultRef``)
    # is no binding of its own.  An assignment the source spells, a
    # conditional expression included, is the class's binding.
    from sugar_source_tree.nodes import Assign, _is_join_phi

    klass = _class(
        "class C:\n"
        "    for i in range(2):\n"
        "        x = 1 if i else 2\n",
        "C",
    )
    (assign,) = tuple(node for node in klass.walk() if isinstance(node, Assign))
    assert not _is_join_phi(assign)

"""A builtin over decided builtin operands may still raise.

``try: int('x') except ValueError: return 1; return 2`` lifted as always
returning ``2``: once every operand of ``int`` was a decided builtin, the call
was cited as total -- but ``int('x')`` raises ``ValueError``.  Whether
``int``/``float``/``chr``/``max``/``divmod``/... complete depends on the
operand VALUES, which the call does not evaluate.  Now such a call completes
only under ``python:builtin_call.completes(...)`` and halts with an
``UndeterminedRaiseEffect`` (owner ``BuiltinCall:<name>``) under the
complement.  The shapes CPython documents as never raising (``len`` of a
sized builtin, ``str``/``repr``/``bool`` of one operand, ``print``, ``list``
of a builtin iterable, ``int`` of a ground int, ...) still complete outright.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import TermValue

from test_builtin_container_mutation import _returns


def _halt_owners(halts):
    return [getattr(halt, "producer_node_owner", None) for halt in halts]


def test_a_handler_for_int_of_a_bad_string_is_reachable(tmp_path):
    source = (
        "def f():\n"
        "    try:\n"
        "        int('x')\n"
        "    except ValueError:\n"
        "        return 1\n"
        "    return 2\n"
    )
    returns, _halts = _returns(tmp_path, source)
    assert TermValue(1) in returns
    assert TermValue(2) in returns


@pytest.mark.parametrize(
    "expression, owner",
    [
        ("int('x')", "BuiltinCall:int"),
        ("float('x')", "BuiltinCall:float"),
        ("int(None)", "BuiltinCall:int"),
        ("chr(-1)", "BuiltinCall:chr"),
        ("ord('ab')", "BuiltinCall:ord"),
        ("max([])", "BuiltinCall:max"),
        ("divmod(1, 0)", "BuiltinCall:divmod"),
        ("range(0, 1, 0)", "BuiltinCall:range"),
        ("sorted([1, 'a'])", "BuiltinCall:sorted"),
        ("sum(['a'])", "BuiltinCall:sum"),
    ],
)
def test_a_value_dependent_builtin_may_halt(tmp_path, expression, owner):
    returns, halts = _returns(tmp_path, f"def f():\n    return {expression}\n")
    assert len(returns) == 1
    assert _halt_owners(halts) == [owner]


@pytest.mark.parametrize(
    "expression",
    [
        "len([1, 2])",
        "len('ab')",
        "str([1])",
        "repr(1)",
        "bool([])",
        "list('ab')",
        "tuple([1])",
        "set('ab')",
        "int(5)",
        "float(2)",
        "abs(-3)",
        "range(3)",
        "hash('a')",
        "any([0, 1])",
        "sum([1, 2])",
        "sorted([2, 1])",
        "max([1, 2])",
        "min(1, 2)",
    ],
)
def test_a_documented_total_builtin_still_completes(tmp_path, expression):
    returns, halts = _returns(tmp_path, f"def f():\n    return {expression}\n")
    assert halts == []
    assert len(returns) == 1


def test_print_of_builtins_completes(tmp_path):
    returns, halts = _returns(tmp_path, "def f():\n    print('a', 1)\n    return 0\n")
    assert halts == []
    assert returns == [TermValue(0)]

"""A builtin over ground operands is decided by the builtin's own semantics.

``try: int('x') except ValueError: return 1; return 2`` lifted as always
returning ``2``: once every operand of ``int`` was a decided builtin, the call
was cited as total -- but ``int('x')`` raises ``ValueError``.  It then became
a two-faced call that owed nothing (``BuiltinValueCallV1``), a second way of
saying "not decided here".  Every operand is a known value, so the outcome is
decided: the pinned interpreter's own builtin applied to those values
(``cpython_cited_fold``).  ``int('x')`` is the one ``ValueError`` halt and
nothing else; ``int('3')`` completes with ``3`` and nothing else.  An operand
known only by its type (``int(s)`` with ``s`` a ``str`` nothing here knows)
is not decided here: the call is the one unanswered call, two-faced and owed
as ``undecided``/``unanswered``.  The shapes CPython documents as never
raising (``len`` of a sized builtin, ``str``/``repr``/``bool`` of one
operand, ``print``, ``list`` of a builtin iterable, ``int`` of a ground int,
...) still complete outright.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import TermValue

from test_builtin_container_mutation import _returns
from test_unknown_callee_call_faces import _two_faced_and_owed


def _halt_names(halts):
    return [getattr(halt, "exception_name", None) for halt in halts]


def test_a_handler_for_int_of_a_bad_string_is_the_only_return(tmp_path):
    source = (
        "def f():\n"
        "    try:\n"
        "        int('x')\n"
        "    except ValueError:\n"
        "        return 1\n"
        "    return 2\n"
    )
    returns, halts = _returns(tmp_path, source)
    assert returns == [TermValue(1)]
    assert halts == []


@pytest.mark.parametrize(
    "expression, exception",
    [
        ("int('x')", "ValueError"),
        ("float('x')", "ValueError"),
        ("int(None)", "TypeError"),
        ("chr(-1)", "ValueError"),
        ("ord('ab')", "TypeError"),
        ("max([])", "ValueError"),
        ("divmod(1, 0)", "ZeroDivisionError"),
        ("range(0, 1, 0)", "ValueError"),
        ("sorted([1, 'a'])", "TypeError"),
        ("sum(['a'])", "TypeError"),
    ],
)
def test_a_builtin_cpython_refuses_over_ground_operands_is_the_one_halt(
    tmp_path, expression, exception
):
    returns, halts = _returns(tmp_path, f"def f():\n    return {expression}\n")
    assert returns == []
    assert _halt_names(halts) == [exception]


@pytest.mark.parametrize(
    "expression, value",
    [
        ("int('3')", 3),
        ("float('2.5')", 2.5),
        ("ord('a')", 97),
        ("divmod(7, 2)[0]", 3),
    ],
)
def test_a_builtin_over_ground_operands_completes_with_its_value(
    tmp_path, expression, value
):
    returns, halts = _returns(tmp_path, f"def f():\n    return {expression}\n")
    assert returns == [TermValue(value)]
    assert halts == []


def test_a_builtin_over_an_operand_known_only_by_type_is_the_one_unanswered_call(
    tmp_path,
):
    # ``s`` is a ``str`` nothing here knows the value of: whether ``int(s)``
    # completes is not decided here.
    _returns_, owners = _two_faced_and_owed(
        tmp_path, "def f(s: str):\n    return int(s)\n"
    )
    assert owners == ["UnknownCallee:int"]


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

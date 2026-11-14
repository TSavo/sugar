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

from sugar_lift_py_tests.floor import ListValue, StringValue, TermValue

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


# One answerer (#7757): a builtin call, or a ``str`` method, whose every
# operand is ground is decided by the pinned interpreter through the cited
# fold alone -- no floor value folds it by hand.  ``len('ab')``,
# ``'a b'.split()`` and ``','.join(['a', 'b'])`` answer what the deleted hand
# folds answered; ``abs(-2)`` was the bare call coordinate (its hand fold,
# ``TermValue.absolute``, had no caller) and is now ``2``.

_ONE_FOLD = [
    ("len('ab')", TermValue(2)),
    ("abs(-2)", TermValue(2)),
    ("'a b'.split()", ListValue((StringValue("a"), StringValue("b")))),
    ("','.join(['a', 'b'])", StringValue("a,b")),
]


@pytest.mark.parametrize("expression, value", _ONE_FOLD)
def test_a_ground_call_is_answered_by_the_one_fold(
    tmp_path, monkeypatch, expression, value
):
    from sugar_lift_py_tests import source_call_resolution

    applied = []
    host_applied = source_call_resolution._host_applied

    def recording(function, operands, site, **kwargs):
        applied.append(kwargs["owner"])
        return host_applied(function, operands, site, **kwargs)

    monkeypatch.setattr(source_call_resolution, "_host_applied", recording)
    returns, halts = _returns(
        tmp_path, f"def f():\n    answer = {expression}\n    return answer\n"
    )
    assert returns == [value]
    assert halts == []
    assert applied, f"{expression} was not answered by the cited fold"
    assert all(owner.startswith("cpython_cited_fold:") for owner in applied)


def test_the_hand_written_ground_folds_are_gone():
    from sugar_lift_py_tests.floor import string_value
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.floor_value import FloorValue
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

    for floor in (FloorValue, TermValue, SymbolicValue, CallSiteValue):
        assert not hasattr(floor, "absolute")
    assert not hasattr(string_value, "_static_str_parts")


def test_a_str_method_over_a_ground_non_string_is_the_one_halt(tmp_path):
    # ``str.join`` of a list holding an ``int``: the pinned interpreter
    # refuses it with ``TypeError``, nothing else.
    returns, halts = _returns(tmp_path, "def f():\n    return ','.join([1])\n")
    assert returns == []
    assert [getattr(halt, "exception_name", None) for halt in halts] == ["TypeError"]


def test_a_str_method_over_an_opaque_argument_keeps_its_marker():
    from types import SimpleNamespace

    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
    from sugar_lift_py_tests.floor.string_value import _fold_string_method
    from sugar_lift_py_tests.ir import make_var
    from sugar_source_tree.nodes import LanguageCallee

    for name, marker in (
        ("join", LanguageCallee.STR_JOIN),
        ("split", LanguageCallee.STR_SPLIT),
    ):
        minted = _fold_string_method(
            StringValue(","),
            SimpleNamespace(
                name=name, arguments=(SymbolicValue(make_var("xs")),), blame=name
            ),
        ).completed_value()
        assert type(minted) is OpaqueOpCallsite
        assert minted.language_callee is marker

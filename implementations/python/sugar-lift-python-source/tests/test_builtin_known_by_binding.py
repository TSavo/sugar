"""A builtin is known by the unit's binding lookup, never by its spelling (#7757).

Each call site that asks whether a callee is a builtin asks the callee's
binding (``SourceUnit.name_reference_at`` / ``builtin_reference_at``, the
``LanguageCallee`` member ``Call.language_callee`` names): the dunder-invoking
builtins (``builtin_dunder_call``), ``list(xs)`` (``builtin_list_construct``),
a builtin exception class's construction, ``type(obj)``'s class coordinate,
the call head's builtin classification and a head nothing binds.  A name the
module, the function or a parameter rebinds (``len = my_len``) is not the
builtin at any of them.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import BuiltinExceptionClassValue, TermValue
from sugar_lift_py_tests.source_call_resolution import (
    BuiltinValueCallV1,
    builtin_dunder_call,
    builtin_list_construct,
)
from sugar_lift_py_tests.sugar.call_site_sugar import (
    CallSiteSugar,
    _lexically_unknown_head,
)
from sugar_source_tree.nodes import Call, LanguageCallee, Name

from test_cited_unreadable_manager import _unit


def _call(source: str, name: str) -> Call:
    """The first call in ``source`` whose callee is the bare name ``name``."""
    unit = _unit(source)
    for node in unit.typed_module.walk():
        if isinstance(node, Call) and isinstance(node.func, Name):
            if node.func.id == name:
                return node
    raise AssertionError(f"no call of {name!r}")


def _sugar(call: Call) -> CallSiteSugar:
    return CallSiteSugar(
        target_name=call.func.id,
        args=(),
        site=call.fragment,
        language_callee=call.language_callee(),
    )


def _shadowed(name: str) -> list[str]:
    """``name`` rebound by the module, by the function, and as a parameter."""
    return [
        (
            "def mine(*args):\n    return 7\n\n"
            f"{name} = mine\n\n"
            f"def f(o):\n    return {name}(o)\n"
        ),
        f"def f(o):\n    {name} = str\n    return {name}(o)\n",
        f"def f(o, {name}):\n    return {name}(o)\n",
    ]


def test_len_bound_to_the_builtin_is_the_dunder_builtin():
    call = _call("def f(o):\n    return len(o)\n", "len")
    assert call.language_callee() is LanguageCallee.BUILTIN_LEN
    assert builtin_dunder_call(call.language_callee(), (TermValue(1),)) == (
        BuiltinValueCallV1("len")
    )


@pytest.mark.parametrize("source", _shadowed("len"))
def test_a_rebound_len_is_not_the_dunder_builtin(source):
    call = _call(source, "len")
    assert call.language_callee() is None
    assert builtin_dunder_call(call.language_callee(), (TermValue(1),)) is None


def test_list_bound_to_the_builtin_constructs_a_list():
    call = _call("def f(o):\n    return list()\n", "list")
    assert call.language_callee() is LanguageCallee.BUILTIN_LIST
    assert builtin_list_construct(call.language_callee(), ()) is not None


@pytest.mark.parametrize("source", _shadowed("list"))
def test_a_rebound_list_constructs_nothing(source):
    call = _call(source, "list")
    assert call.language_callee() is None
    assert builtin_list_construct(call.language_callee(), ()) is None


def test_value_error_bound_to_the_builtin_is_the_builtin_exception_class():
    sugar = _sugar(_call("def f(o):\n    return ValueError(o)\n", "ValueError"))
    applied = sugar._applied_builtin_exception_class(None)
    assert isinstance(applied, BuiltinExceptionClassValue)


_SOURCE_CLASS_VALUE_ERROR = (
    "class ValueError(Exception):\n"
    "    pass\n\n"
    "def f(o):\n"
    "    return ValueError(o)\n"
)


@pytest.mark.parametrize(
    "source", _shadowed("ValueError") + [_SOURCE_CLASS_VALUE_ERROR]
)
def test_a_rebound_value_error_is_not_the_builtin_exception_class(source):
    sugar = _sugar(_call(source, "ValueError"))
    assert sugar._applied_builtin_exception_class(None) is None


def test_type_bound_to_the_builtin_answers_a_class_coordinate():
    sugar = _sugar(_call("def f(o):\n    return type(o)\n", "type"))
    assert sugar.language_callee is LanguageCallee.BUILTIN_TYPE
    term = object()
    assert sugar._applied_builtin_type_of(None, (TermValue(1),), (), term) is term


@pytest.mark.parametrize("source", _shadowed("type"))
def test_a_rebound_type_answers_no_class_coordinate(source):
    sugar = _sugar(_call(source, "type"))
    applied = sugar._applied_builtin_type_of(None, (TermValue(1),), (), object())
    assert applied is None


def test_the_call_head_is_builtin_only_by_its_binding():
    sugar = _sugar(_call("def f(o):\n    return len(o)\n", "len"))
    assert sugar._builtin_reference() == "python:builtins.len"


@pytest.mark.parametrize("source", _shadowed("len"))
def test_a_rebound_call_head_is_not_builtin(source):
    assert _sugar(_call(source, "len"))._builtin_reference() is None


def test_a_head_nothing_binds_is_known_only_through_the_builtin_namespace():
    known = _call("def f(o):\n    return len(o)\n", "len")
    assert not _lexically_unknown_head(known.fragment, "len")
    unknown = _call("def f(o):\n    return frobnicate(o)\n", "frobnicate")
    assert _lexically_unknown_head(unknown.fragment, "frobnicate")

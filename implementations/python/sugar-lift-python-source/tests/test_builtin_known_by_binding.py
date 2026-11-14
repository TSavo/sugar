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

from sugar_lift_py_tests.floor import (
    BlockValue,
    BuiltinExceptionClassValue,
    BuiltinSemanticCallable,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.source_call_resolution import (
    UnknownCalleeCallV1,
    builtin_call_total,
    builtin_dunder_call,
    builtin_list_construct,
    cpython_cited_fold,
)
from sugar_lift_py_tests.sugar.call_site_sugar import (
    CallSiteSugar,
    _lexically_unknown_head,
)
from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal
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
    # #7757: ``len(1)`` is not a shape CPython documents as total: the one
    # unanswered form, which ``cpython_cited_fold`` decides over ground
    # operands.
    assert builtin_dunder_call(call.language_callee(), (TermValue(1),)) == (
        UnknownCalleeCallV1("len")
    )


def test_a_builtin_over_an_operand_known_only_by_type_is_not_folded():
    # #7757: no ground value to apply the builtin to, so nothing is decided
    # here and the call stays the one unanswered call.
    call = _call("def f(o):\n    return int(o)\n", "int")
    operand = SymbolicValue(make_var("o"))
    unanswered = builtin_dunder_call(call.language_callee(), (operand,))
    assert unanswered == UnknownCalleeCallV1("int")
    folded = cpython_cited_fold(
        unanswered,
        (operand,),
        (),
        site=call.fragment,
        language_callee=call.language_callee(),
    )
    assert folded is None


def test_len_over_an_undecided_operand_is_the_one_unanswered_call():
    # #7757: ``len(o)`` with ``o`` not a decided builtin runs a ``__len__``
    # that is not CPython's own: not decided here, so the one unanswered form.
    call = _call("def f(o):\n    return len(o)\n", "len")
    operand = SymbolicValue(make_var("o"))
    assert builtin_dunder_call(call.language_callee(), (operand,)) == (
        UnknownCalleeCallV1("len")
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


def _len_reads(source: str) -> list:
    """``(unit, span)`` of every bare ``len`` callee in ``source``, in order."""
    unit = _unit(source)
    spans = sorted(
        (
            node.func.line_col_span()
            for node in unit.typed_module.walk()
            if isinstance(node, Call)
            and isinstance(node.func, Name)
            and node.func.id == "len"
        ),
        key=lambda span: (span.start_line, span.start_col),
    )
    return [(unit, span) for span in spans]


_CLASS_BODY_LEN = (
    "def mine(*args):\n    return 7\n\n"
    "class C:\n"
    "    len = mine\n"
    "    size = len(1)\n\n"
    "    def m(self, o):\n"
    "        return len(o)\n"
)


def test_a_class_body_rebinding_is_not_the_builtin_in_that_body():
    (unit, body_read), _ = _len_reads(_CLASS_BODY_LEN)
    assert unit.builtin_reference_at("len", body_read) is None
    assert unit.language_callee_at("len", body_read) is None


def test_a_method_skips_the_class_scope_and_reads_the_builtin():
    _, (unit, method_read) = _len_reads(_CLASS_BODY_LEN)
    assert unit.builtin_reference_at("len", method_read) == "python:builtins.len"
    assert unit.language_callee_at("len", method_read) is LanguageCallee.BUILTIN_LEN


def test_a_module_level_branch_rebinding_is_not_the_builtin():
    source = (
        "PY2 = False\n\n"
        "if PY2:\n"
        "    str = unicode\n\n"
        "def f(o):\n"
        "    return str(o)\n"
    )
    call = _call(source, "str")
    span = call.func.line_col_span()
    assert call.unit.builtin_reference_at("str", span) is None
    assert call.language_callee() is None


_STAR_IMPORT_LEN = "from m import *\n\ndef f(o):\n    return len(o)\n"


def test_a_call_bound_to_the_builtin_applies_the_builtin_floor_value():
    sugar = _sugar(_call("def f(o):\n    return len(o)\n", "len"))
    assert sugar._builtin_floor_value() is builtin_name_temporal().value_if_bound(
        "len"
    )


@pytest.mark.parametrize("source", _shadowed("len") + [_STAR_IMPORT_LEN])
def test_a_call_the_builtin_may_not_bind_applies_no_builtin_floor_value(source):
    # The temporal floor still holds ``len`` by spelling; the call's binding
    # does not reach it, so no builtin semantics apply.
    assert _sugar(_call(source, "len"))._builtin_floor_value() is None


def _type_operand(source: str):
    """``int`` as the free operand of ``isinstance(o, int)`` in ``source``,
    resolved at that call."""
    call = _call(source, "isinstance")
    free = SymbolicValue(make_var("int"))
    resolved = BuiltinSemanticCallable(
        operation="python.isinstance"
    )._resolve_type_operand(free, call.fragment, 1)
    return free, resolved


def test_a_type_operand_bound_to_the_builtin_is_the_builtin_class():
    _free, resolved = _type_operand("def f(o):\n    return isinstance(o, int)\n")
    assert resolved is builtin_name_temporal().value_if_bound("int")


@pytest.mark.parametrize(
    "source",
    [
        "from m import *\n\ndef f(o):\n    return isinstance(o, int)\n",
        "int = str\n\ndef f(o):\n    return isinstance(o, int)\n",
        "def f(o, int):\n    return isinstance(o, int)\n",
    ],
)
def test_a_type_operand_the_builtin_may_not_bind_stays_free(source):
    free, resolved = _type_operand(source)
    assert resolved is free


def _int_value_read(source: str, ctx=None):
    """``int`` read as a value (``isinstance(o, int)``'s operand) in
    ``source``, desugared under the builtin temporal floor (or ``ctx``)."""
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.sugar.name_sugar import NameSugar

    operand = _call(source, "isinstance").args[1]
    assert isinstance(operand, Name) and operand.id == "int"
    if ctx is None:
        ctx = ReduceContext.root(owner="test_builtin_value_read")
    return NameSugar(name="int", site=operand.fragment).desugar(ctx)


def test_int_bound_to_the_builtin_is_the_builtin_class_as_a_value():
    outcome = _int_value_read("def f(o):\n    return isinstance(o, int)\n")
    assert outcome.completed_value() is builtin_name_temporal().value_if_bound(
        "int"
    )


@pytest.mark.parametrize(
    "source",
    [
        # A star import the lifter cannot read may bind ``int``.
        "from m import *\n\ndef f(o):\n    return isinstance(o, int)\n",
        # The module rebinds it.
        "int = str\n\ndef f(o):\n    return isinstance(o, int)\n",
        # The function rebinds it.
        "def f(o):\n    int = str\n    return isinstance(o, int)\n",
        # A parameter binds it.
        "def f(o, int):\n    return isinstance(o, int)\n",
    ],
)
def test_int_the_builtin_may_not_bind_is_not_the_builtin_class_as_a_value(source):
    # The temporal floor still holds ``int`` by spelling; the read's binding
    # does not reach it, so the read is the free operand, never the builtin.
    value = _int_value_read(source).completed_value()
    assert value is not builtin_name_temporal().value_if_bound("int")
    assert isinstance(value, SymbolicValue)
    assert value.term.name == "int"


def test_a_source_binding_in_the_temporal_is_read_over_the_builtin():
    from sugar_lift_py_tests.context import ReduceContext

    ctx = ReduceContext.root(owner="test_builtin_value_read")
    bound = TermValue(5)
    ctx = ctx.with_temporal(ctx.temporal.bind_value("int", bound))
    source = "def f(o, int):\n    return isinstance(o, int)\n"
    assert _int_value_read(source, ctx).completed_value() is bound


def test_a_head_nothing_binds_is_known_only_through_the_builtin_namespace():
    known = _call("def f(o):\n    return len(o)\n", "len")
    assert not _lexically_unknown_head(known.fragment, "len")
    unknown = _call("def f(o):\n    return frobnicate(o)\n", "frobnicate")
    assert _lexically_unknown_head(unknown.fragment, "frobnicate")


def test_callable_bound_to_the_builtin_is_its_member():
    call = _call("def f(o):\n    return callable(o)\n", "callable")
    assert call.language_callee() is LanguageCallee.BUILTIN_CALLABLE


@pytest.mark.parametrize("source", _shadowed("callable"))
def test_a_rebound_callable_is_not_the_builtin(source):
    assert _call(source, "callable").language_callee() is None


_OPAQUE = SymbolicValue(make_var("o"))


@pytest.mark.parametrize(
    ("member", "args"),
    [
        (LanguageCallee.BUILTIN_OBJECT, ()),
        (LanguageCallee.BUILTIN_BYTES, ()),
        (LanguageCallee.BUILTIN_COMPLEX, ()),
        (LanguageCallee.BUILTIN_ID, (_OPAQUE,)),
        (LanguageCallee.BUILTIN_CALLABLE, (_OPAQUE,)),
        (LanguageCallee.BUILTIN_TYPE, (_OPAQUE,)),
    ],
)
def test_a_builtin_that_runs_no_operand_code_is_total_over_any_operand(member, args):
    # #7757: CPython runs no code of the operand for these shapes, so no
    # operand makes them raise.
    assert builtin_call_total(member, args)


@pytest.mark.parametrize(
    ("member", "args", "keywords"),
    [
        # ``object(x)`` and ``bytes(x)`` / ``complex(x)`` read their operand.
        (LanguageCallee.BUILTIN_OBJECT, (_OPAQUE,), ()),
        (LanguageCallee.BUILTIN_BYTES, (_OPAQUE,), ()),
        (LanguageCallee.BUILTIN_COMPLEX, (_OPAQUE,), ()),
        # ``type(name, bases, ns)`` builds a class and may raise.
        (LanguageCallee.BUILTIN_TYPE, (_OPAQUE, _OPAQUE, _OPAQUE), ()),
        (LanguageCallee.BUILTIN_ID, (_OPAQUE,), ("x",)),
        # These run the operand's dunder.
        (LanguageCallee.BUILTIN_HASH, (_OPAQUE,), ()),
        (LanguageCallee.BUILTIN_LEN, (_OPAQUE,), ()),
        (LanguageCallee.BUILTIN_ITER, (_OPAQUE,), ()),
        (LanguageCallee.BUILTIN_ISSUBCLASS, (_OPAQUE, _OPAQUE), ()),
    ],
)
def test_a_builtin_shape_that_may_raise_is_not_total(member, args, keywords):
    assert not builtin_call_total(member, args, keywords)


def test_isinstance_over_a_builtin_class_and_a_decided_object_is_total():
    floor = builtin_name_temporal()
    isinstance_ = LanguageCallee.BUILTIN_ISINSTANCE
    for classinfo in (
        floor.value_if_bound("ValueError"),
        floor.value_if_bound("object"),
        floor.value_if_bound("type"),
        floor.value_if_bound("dict"),
        floor.value_if_bound("tuple"),
        TupleValue((floor.value_if_bound("set"), floor.value_if_bound("KeyError"))),
    ):
        assert builtin_call_total(isinstance_, (TermValue(1), classinfo))


@pytest.mark.parametrize(
    "classinfo",
    [
        # ``len`` and ``print`` are builtin functions: ``isinstance(1, len)``
        # is a TypeError.
        builtin_name_temporal().value_if_bound("len"),
        builtin_name_temporal().value_if_bound("print"),
        # A value named like a builtin class is not the builtin's floor.
        BuiltinExceptionClassValue(
            name="ValueError", bases=(), record=BlockValue(())
        ),
        _OPAQUE,
    ],
)
def test_isinstance_over_an_undecided_class_operand_is_not_total(classinfo):
    assert not builtin_call_total(
        LanguageCallee.BUILTIN_ISINSTANCE, (TermValue(1), classinfo)
    )


def test_isinstance_over_an_undecided_object_is_not_total():
    # A miss reads ``obj.__class__``, which an object of a source class may
    # answer with its own code.
    classinfo = builtin_name_temporal().value_if_bound("ValueError")
    assert not builtin_call_total(
        LanguageCallee.BUILTIN_ISINSTANCE, (_OPAQUE, classinfo)
    )

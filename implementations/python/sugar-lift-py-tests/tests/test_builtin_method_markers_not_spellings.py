"""A builtin method's result is known by the marker its door mints (#7757).

``str.split`` by an opaque separator is answered by ``StringValue``'s method
fold, which marks the coordinate with ``LanguageCallee.STR_SPLIT``; an append
to it rebinds through ``py.list_append``.  A coordinate merely spelled
``split`` (a user function, an unbound receiver's method) is not list-shaped
and stays loud.

``type(x).__name__`` / ``__qualname__`` are known by the marker the attribute
read mints (``type_name_attribute``); a user function named ``__name__`` does
not name a string.  The string concatenation the lifter mints over a named
string (``call:__add__``, ``python:fstring``) is known by its marker
(``string_concatenation``); a user function named ``__add__`` does not name a
string.

A ground ``str.split`` folds to the lifter's one floor for a ``list``
(``ListValue``), so appending to it is answered by the same container law a
list display's append is.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.call_symbol import call_symbol
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue
from sugar_lift_py_tests.floor.guarded_value import _stands_on_append_floor
from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
from sugar_lift_py_tests.floor.string_value import StringValue, _fold_string_method
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_source_tree.nodes import LanguageCallee


def _split(receiver: str, *arguments):
    return _fold_string_method(
        StringValue(receiver),
        SimpleNamespace(
            name="split", arguments=tuple(arguments), owner="test", blame="fold-split"
        ),
    ).completed_value()


def test_split_by_opaque_separator_carries_its_binding() -> None:
    minted = _split("a.b", SymbolicValue(make_var("sep")))

    assert type(minted) is OpaqueOpCallsite
    assert minted.language_callee is LanguageCallee.STR_SPLIT
    assert minted.stands_on_append_floor()


def test_split_with_opaque_maxsplit_carries_its_binding() -> None:
    minted = _split("a.b", StringValue("."), SymbolicValue(make_var("n")))

    assert type(minted) is OpaqueOpCallsite
    assert minted.language_callee is LanguageCallee.STR_SPLIT


def test_append_to_a_split_result_rebinds_through_list_append() -> None:
    minted = _split("a.b", SymbolicValue(make_var("sep")))
    value = StringValue("c")

    appended = minted.append_with(value, "append-split").completed_value()

    assert type(appended) is CallSiteValue
    assert appended.term.name == "py.list_append"
    assert appended.arg_values == (minted, value)

    chained = appended.append_with(StringValue("d"), "append-again").completed_value()
    assert type(chained) is CallSiteValue
    assert chained.term.name == "py.list_append"


def test_coordinate_spelled_split_without_its_binding_stays_loud() -> None:
    spelled = OpaqueOpCallsite(
        callee="split",
        arg=StringValue("a.b"),
        computed=None,
        extra_args=(SymbolicValue(make_var("sep")),),
    )

    assert not spelled.stands_on_append_floor()
    with pytest.raises(ConstructionPanic):
        spelled.append_with(StringValue("c"), "append-spelled-split")


@pytest.mark.parametrize("spelling", ("split", "copy"))
def test_user_call_spelled_like_a_builtin_method_stays_loud(spelling: str) -> None:
    user_call = CallSiteValue(
        target_name=spelling,
        arg_values=(SymbolicValue(make_var("xs")),),
        parameters=(),
        term=ctor(
            call_symbol(spelling),
            [make_var("xs")],
            symbol_kind="method-coordinate",
        ),
        body=None,
        site="user-call",
    )

    with pytest.raises(ConstructionPanic):
        user_call.append_with(StringValue("c"), "append-user-call")


def test_guarded_append_asks_the_marker_of_an_operator_face() -> None:
    marked = _split("a.b", SymbolicValue(make_var("sep")))
    other = OpaqueOpCallsite(
        callee="strip",
        arg=StringValue(" a "),
        computed=None,
        extra_args=(SymbolicValue(make_var("chars")),),
    )

    assert _stands_on_append_floor(marked)
    assert not _stands_on_append_floor(other)


def test_type_name_attribute_read_names_a_string() -> None:
    receiver = SymbolicValue(make_var("expected"))

    member = receiver.attribute("__qualname__", "symbolic-qualname", None)
    member = member.completed_value()

    assert type(member) is CallSiteValue
    assert member.type_name_attribute
    assert member.names_a_string()

    call = CallSiteValue(
        target_name="make",
        arg_values=(),
        parameters=(),
        term=ctor(call_symbol("make"), [], symbol_kind="coordinate"),
        body=None,
        site="opaque-call",
    )
    name = call.attribute("__name__", "callsite-name", None).completed_value()

    assert type(name) is CallSiteValue
    assert name.type_name_attribute
    assert name.names_a_string()


@pytest.mark.parametrize("spelling", ("__name__", "__qualname__"))
def test_user_function_spelled_name_does_not_name_a_string(spelling: str) -> None:
    user_call = CallSiteValue(
        target_name=spelling,
        arg_values=(SymbolicValue(make_var("x")),),
        parameters=(),
        term=ctor(call_symbol(spelling), [make_var("x")], symbol_kind="coordinate"),
        body=None,
        site="user-call",
    )

    assert not user_call.type_name_attribute
    assert not user_call.names_a_string()


def test_named_string_concat_carries_its_marker() -> None:
    name = SymbolicValue(make_var("exc_type")).attribute("__name__", "name-attr", None)
    concat = name.completed_value().add(StringValue("()"), "concat", None)
    concat = concat.completed_value()

    assert type(concat) is CallSiteValue
    assert concat.term.name == call_symbol("__add__")
    assert concat.string_concatenation
    assert concat.names_a_string()


def test_fstring_concat_carries_its_marker() -> None:
    from sugar_lift_py_tests.sugar.fstring_sugar import _concatenate_joined_parts

    joined = _concatenate_joined_parts(
        StringValue("n="), SymbolicValue(make_var("n")), "fstring", None
    ).completed_value()

    assert type(joined) is CallSiteValue
    assert joined.term.name == "python:fstring"
    assert joined.string_concatenation
    assert joined.names_a_string()


def test_user_function_spelled_add_does_not_name_a_string() -> None:
    user_call = CallSiteValue(
        target_name="__add__",
        arg_values=(SymbolicValue(make_var("a")), SymbolicValue(make_var("b"))),
        parameters=(),
        term=ctor(
            call_symbol("__add__"),
            [make_var("a"), make_var("b")],
            symbol_kind="coordinate",
        ),
        body=None,
        site="user-add",
    )

    assert not user_call.string_concatenation
    assert not user_call.names_a_string()


def test_ground_split_is_the_list_floor_a_display_is() -> None:
    from sugar_lift_py_tests.floor import builtin_container_method as law
    from sugar_lift_py_tests.floor.list_value import ListValue

    parts = _split("a b")
    display = ListValue((StringValue("a"), StringValue("b")))

    assert type(parts) is ListValue
    assert parts == display
    assert law.container_kind(parts) == law.container_kind(display) == "list"
    assert type(_split("a.b", StringValue("."))) is ListValue
    assert type(_split("a.b.c", StringValue("."), TermValue(1))) is ListValue


def test_append_to_a_ground_split_takes_the_list_display_law() -> None:
    """``parts = 'a b'.split(); parts.append('c')`` answers exactly as
    ``xs = ['a', 'b']; xs.append('c')`` does: through the container law."""
    from sugar_lift_py_tests.floor import builtin_container_method as law
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.sugar.method_call_sugar import dispatch_method_call

    parts = _split("a b")
    display = ListValue((StringValue("a"), StringValue("b")))
    appended = StringValue("c")
    expected = ListValue((StringValue("a"), StringValue("b"), appended))

    for receiver in (parts, display):
        pair = law.apply("list", "append", receiver, (appended,), "append", None)
        assert pair.completed_value() == TupleValue((expected, NoneValue()))
        assert receiver.append_with(appended, "append").completed_value() == expected
        result = dispatch_method_call(
            "append", receiver, (appended,), (), "append", None
        )
        assert pair.halts() == result.halts() == ()
        assert type(result.completed_value()) is NoneValue


def _splitlines(receiver: str, *arguments):
    return _fold_string_method(
        StringValue(receiver),
        SimpleNamespace(
            name="splitlines",
            arguments=tuple(arguments),
            owner="test",
            blame="fold-splitlines",
        ),
    ).completed_value()


def test_splitlines_with_a_bool_keepends_folds_to_the_list_floor() -> None:
    """``s.splitlines(True)`` crashed the lifter: the fold asked
    ``isinstance(keep)`` with one argument.  The bool floor is the literal."""
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    def lines(*parts):
        return ListValue(tuple(StringValue(part) for part in parts))

    source = "a\nb\r\nc"
    kept = _splitlines(source, TrueBoolLiteralSugar(site="keep"))
    dropped = _splitlines(source, FalseBoolLiteralSugar(site="drop"))

    assert kept == lines(*source.splitlines(True)) == lines("a\n", "b\r\n", "c")
    assert dropped == lines(*source.splitlines(False)) == lines("a", "b", "c")
    # Discriminating: the two literals are two answers, not one.
    assert kept != dropped
    assert _splitlines(source) == dropped
    assert _splitlines(source, TermValue(1)) == kept
    assert _splitlines(source, TermValue(0)) == dropped


def test_splitlines_with_an_opaque_keepends_only_coordinates() -> None:
    minted = _splitlines("a\nb", SymbolicValue(make_var("keep")))

    assert type(minted) is OpaqueOpCallsite
    assert minted.computed is None


def test_join_over_a_ground_split_still_folds() -> None:
    joined = _fold_string_method(
        StringValue("-"),
        SimpleNamespace(
            name="join", arguments=(_split("a b"),), owner="test", blame="join"
        ),
    ).completed_value()

    assert joined == StringValue("a-b")

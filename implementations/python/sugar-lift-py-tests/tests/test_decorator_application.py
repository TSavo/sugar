"""A decorated ``def``/``class`` binds ``d1(d2(<definition>))`` (#7757).

The decorator application is one door (``DecoratedDefinitionRef``,
``DecoratorApplicationSugar``): the statement applies its decorators, a call
of the name calls the result, and the definition's own body is never run in
its place.  A source decorator is applied through the one call routine; a
builtin one through the one builtin door with its real semantics or a refusal
by name; an imported one is the ``undecided`` member under its target symbol.

Before this, a call of a decorated module function seated the function's own
frame (``SourceUnit.source_function_definition_for_call`` answered the
decorated definition), so ``@d def f`` ran ``f``'s plain body: a wrong value.
"""

from __future__ import annotations

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import (
    Call,
    ClassDef,
    DecoratedDefinitionRef,
    FunctionDef,
    Name,
    _module_reference_state,
)
from sugar_source_tree.tree import SourceFile


def _tree(source: str, context=None) -> SourceFile:
    return SourceFile(
        (source, "test_decorator_application.py", blake3_512_of(source.encode())),
        construction_context=(
            context or TreeConstructionContextV1.for_test_without_workspace()
        ),
    )


def _test_function_outcome(source: str):
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    tree = _tree(source)
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name.startswith("test_")
    )
    return function_universe_outcome(function)


def _raises(outcome, exception: str) -> list:
    from sugar_lift_py_tests.outcome import Halted

    return [
        face
        for face in getattr(outcome, "exits", ())
        if isinstance(face, Halted)
        and getattr(face.effect, "exception_name", None) == exception
    ]


def _only_raise(outcome, exception: str) -> None:
    from sugar_lift_py_tests.outcome import ExitSet, Halted

    assert isinstance(outcome, ExitSet), outcome
    assert [type(face) for face in outcome.exits] == [Halted], outcome
    assert outcome.exits[0].effect.exception_name == exception


def _call_of(tree: SourceFile, name: str) -> Call:
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Name)
        and node.func.id == name
    )


# ---------------------------------------------------------------------------
# A call of a decorated function is never the function's own frame.
# ---------------------------------------------------------------------------

_DECORATED = """\
def replace(fn):
    return lambda n: n * 10


@replace
def scale(n):
    return n


def test_scale():
    value = scale(2)
    assert value == 20
"""


def test_a_decorated_function_is_not_its_call_frame() -> None:
    tree = _tree(_DECORATED)
    call = _call_of(tree, "scale")
    assert call.unit.source_function_definition_for_call(call) is None
    decorated = call.unit.decorated_definition_for_call(call)
    assert isinstance(decorated, FunctionDef)
    assert decorated.name == "scale"


def test_an_undecorated_function_keeps_its_call_frame() -> None:
    tree = _tree(_DECORATED.replace("@replace\n", ""))
    call = _call_of(tree, "scale")
    assert call.unit.source_function_definition_for_call(call) is not None
    assert call.unit.decorated_definition_for_call(call) is None


# ---------------------------------------------------------------------------
# A source decorator's result is what the call runs.
# ---------------------------------------------------------------------------

_SOURCE_DECORATOR = """\
def fail(n):
    raise ValueError('decorated')


def replace(fn):
    return lambda n: {wrapper}


@replace
def scale(n):
{body}


def test_scale():
    value = scale(2)
    assert value == 20
"""


def test_a_source_decorator_replaces_a_raising_body() -> None:
    """The bare body raises; the decorator's result does not: the call
    completes, so the bare body never ran."""
    outcome = _test_function_outcome(
        _SOURCE_DECORATOR.format(
            wrapper="n * 10", body="    raise ValueError('plain body')"
        )
    )
    assert outcome.completed_value() is not None, outcome
    assert _raises(outcome, "ValueError") == []


def test_a_source_decorator_changes_what_the_call_does() -> None:
    """The bare body returns; the decorator's result raises: the call
    carries the decorator's raise, so its result is what was called."""
    outcome = _test_function_outcome(
        _SOURCE_DECORATOR.format(wrapper="fail(n)", body="    return n")
    )
    _only_raise(outcome, "ValueError")


def test_a_decorated_local_function_calls_the_decorators_result() -> None:
    source = """\
def replace(fn):
    return lambda n: n * 10


def test_scale():
    @replace
    def scale(n):
        raise ValueError('plain body')

    value = scale(2)
    assert value == 20
"""
    outcome = _test_function_outcome(source)
    assert outcome.completed_value() is not None, outcome
    assert _raises(outcome, "ValueError") == []


# ---------------------------------------------------------------------------
# An imported decorator is undecided, never the plain body.
# ---------------------------------------------------------------------------

_IMPORTED = """\
from elsewhere import wrap


@wrap
def scale(n):
    raise ValueError('plain body')


def test_scale():
    value = scale(2)
    assert value == 20
"""


def test_an_imported_decorator_is_undecided_never_the_plain_body() -> None:
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    outcome = _test_function_outcome(_IMPORTED)
    assert _raises(outcome, "ValueError") == []
    assert "python:elsewhere.wrap" in {item.symbol for item in owed_calls(outcome)}


# ---------------------------------------------------------------------------
# Builtin decorators go through the one builtin door.
# ---------------------------------------------------------------------------


def test_a_staticmethod_read_off_its_class_takes_no_implicit_argument() -> None:
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.outcome import Halted

    source = """\
class Box:
    @staticmethod
    def pick(n):
{body}
"""
    for body, raises in (
        ("        return n", False),
        ("        raise ValueError('static')", True),
    ):
        text = source.format(body=body)
        tree = _tree(text)
        (class_def,) = tuple(
            node for node in tree.nodes() if isinstance(node, ClassDef)
        )
        ctx = ReduceContext.root(owner="test")
        box = class_def.sugar().desugar(ctx).completed_value()
        outcome = box.call_method_value(
            "pick", (TermValue(3),), owner="test", blame="pick-site", ctx=ctx
        )
        halts = [
            face for face in getattr(outcome, "exits", ()) if isinstance(face, Halted)
        ]
        if raises:
            assert [face.effect.exception_name for face in halts] == ["ValueError"]
        else:
            assert halts == []


def test_a_property_getter_runs_on_the_instance_read() -> None:
    source = """\
class Receiver:
    @property
    def value(self):
        raise ValueError('getter')


def test_value():
    found = Receiver().value
    assert found == 1
"""
    _only_raise(_test_function_outcome(source), "ValueError")


def test_typing_final_returns_the_function() -> None:
    outcome = _test_function_outcome(
        """\
from typing import final


@final
def check(n):
    raise ValueError('final body')


def test_check():
    value = check(2)
    assert value == 2
"""
    )
    _only_raise(outcome, "ValueError")


# ---------------------------------------------------------------------------
# A module reader binds a decorated name to the application.
# ---------------------------------------------------------------------------


def test_a_module_reader_binds_a_decorated_name_to_its_application() -> None:
    tree = _tree(
        """\
def replace(fn):
    return lambda n: n * 10


scale = None


@replace
def scale(n):
    return n


def f():
    return scale(2)
""",
        TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "f"
    )
    final = function.unit.module_bindings_at(None, {"scale"})["scale"]
    assert isinstance(final, DecoratedDefinitionRef)
    assert final.definition_name == "scale"
    assert _module_reference_state(final) is final

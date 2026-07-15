from __future__ import annotations

import ast

import pytest

from factory_reduce import compose_block, reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import FactoryPanic
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ExceptionValue,
    RaiseValue,
    ReturnValue,
    StringValue,
    SymbolicValue,
    TermValue,
    UniverseValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.temporal import TemporalContext


@pytest.mark.parametrize(
    ("source", "name", "arguments"),
    (
        ("ValueError()", "ValueError", ()),
        ("ValueError('bad')", "ValueError", (StringValue("bad"),)),
        (
            "TypeError('expected', 2)",
            "TypeError",
            (StringValue("expected"), TermValue(2)),
        ),
        ("RuntimeError('stopped')", "RuntimeError", (StringValue("stopped"),)),
    ),
)
def test_exact_builtin_exception_constructor_builds_typed_floor_from_real_ast(
    source: str, name: str, arguments: tuple
) -> None:
    value = reduce_value(source)

    assert isinstance(value, ExceptionValue)
    assert value.exception_name == name
    assert value.arguments == arguments
    assert str(value.site) == "t.py:1:0"


def test_builtin_exception_floor_feeds_raise_and_preserves_argument_order() -> None:
    block = compose_block("    raise ValueError('left', 2)\n")

    raised = block.statements[0]
    assert isinstance(raised, RaiseValue)
    assert isinstance(raised.exception, ExceptionValue)
    assert raised.exception.arguments == (StringValue("left"), TermValue(2))
    assert raised.effect.exception_name == "ValueError"
    assert raised.exception.site is not None


def test_temporally_shadowed_valueerror_is_not_substituted_for_builtin() -> None:
    shadow = SymbolicValue(make_var("local_ValueError"))

    value = reduce_value("ValueError('bad')", {"ValueError": shadow})

    assert isinstance(value, CallSiteValue)
    assert not isinstance(value, ExceptionValue)


def _function_universe(source: str) -> UniverseValue:
    node = ast.parse(source).body[0]
    context = FactoryBuildContext(filename="shadow.py", catalog=default_catalog())
    from sugar_lift_py_tests.factory import build_node

    built = build_node(
        node,
        filename="shadow.py",
        role=SugarRole.DEFINITION,
        ctx=context,
    )
    value = complete_value(built.sugar.desugar(context), owner="shadow regression")
    assert isinstance(value, UniverseValue)
    return value


def _returned_value(universe: UniverseValue):
    returned = universe.record.statements[-1]
    assert isinstance(returned, ReturnValue)
    return returned.value


def test_local_function_shadow_uses_function_callable_not_builtin_identity() -> None:
    universe = _function_universe(
        "def outer():\n"
        "    def ValueError(message):\n"
        "        return message\n"
        "    return ValueError('bad')\n"
    )

    value = _returned_value(universe)
    assert isinstance(value, CallSiteValue)
    assert not isinstance(value, ExceptionValue)
    assert value.parameters == ("message",)


def test_function_parameter_shadow_does_not_take_builtin_exception_floor() -> None:
    value = _returned_value(
        _function_universe("def outer(ValueError):\n" "    return ValueError('bad')\n")
    )

    assert isinstance(value, CallSiteValue)
    assert not isinstance(value, ExceptionValue)


def test_prior_assignment_shadow_does_not_take_builtin_exception_floor() -> None:
    block = compose_block("    ValueError = factory\n" "    return ValueError('bad')\n")

    returned = block.statements[-1]
    assert isinstance(returned, ReturnValue)
    assert isinstance(returned.value, CallSiteValue)
    assert not isinstance(returned.value, ExceptionValue)


def test_qualified_unrelated_valueerror_is_not_substituted_for_builtin() -> None:
    module = SymbolicValue(make_var("module"))

    value = reduce_value("module.ValueError('bad')", {"module": module})

    assert not isinstance(value, ExceptionValue)


def test_symbolic_exception_argument_stays_loud_instead_of_fabricating_instance() -> (
    None
):
    with pytest.raises(FactoryPanic, match="CallSugar.*constructed exception argument"):
        reduce_value(
            "ValueError(message)",
            {"message": SymbolicValue(make_var("message"))},
        )


def test_arbitrary_callable_is_not_substituted_for_exception_constructor() -> None:
    value = reduce_value("factory('bad')")

    assert isinstance(value, CallSiteValue)
    assert not isinstance(value, ExceptionValue)


def test_exception_arguments_reduce_once_in_order_and_preserve_memento() -> None:
    events: list[str] = []

    class CountingBody:
        def __init__(self, label: str) -> None:
            self.label = label
            self.calls = 0

        def reduce(self, ctx):
            del ctx
            from sugar_lift_py_tests.outcome import Complete

            self.calls += 1
            events.append(self.label)
            return Complete(StringValue(self.label))

    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.sugar.call_sugar import CallSugar

    site = SourceFragment.from_node(
        ast.parse("ValueError('first', 'second', 'third')", mode="eval").body,
        "memento.py",
    )
    bodies = tuple(CountingBody(label) for label in ("first", "second", "third"))
    temporal = TemporalContext.empty()
    context = FactoryBuildContext(
        filename="memento.py", catalog=default_catalog(), temporal=temporal
    )
    value = complete_value(
        CallSugar("ValueError", bodies, (), site).desugar(context), owner="test"
    )

    assert isinstance(value, ExceptionValue)
    assert value.site is site
    assert value.arguments == tuple(StringValue(label) for label in events)
    assert events == ["first", "second", "third"]
    assert [body.calls for body in bodies] == [1, 1, 1]


def test_raise_from_stays_loud_until_cause_semantics_are_constructed() -> None:
    with pytest.raises(FactoryPanic) as raised:
        compose_block("    raise ValueError('bad') from TypeError('cause')\n")

    assert raised.value.info.owner == "RaiseSugar"
    assert raised.value.info.observed == "raise ... from ..."
    assert raised.value.info.requested == "an explicit exception-cause floor"


def test_bare_raise_keeps_preexisting_unclassified_raise_path() -> None:
    block = compose_block("    raise\n")

    raised = block.statements[0]
    assert isinstance(raised, RaiseValue)
    assert raised.exception is None
    assert raised.effect.exception_name is None


def test_with_traceback_is_not_folded_into_direct_exception_construction() -> None:
    traceback = SymbolicValue(make_var("traceback"))

    with pytest.raises(FactoryPanic):
        compose_block(
            "    raise ValueError('bad').with_traceback(traceback)\n",
            {"traceback": traceback},
        )

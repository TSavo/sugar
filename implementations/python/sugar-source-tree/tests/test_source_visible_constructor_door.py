from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    DictValue,
    ReturnValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.generator_construction import (
    GeneratorConstructionV1,
    GeneratorTerminationV1,
    GeneratorTransitionGapV1,
    YieldEffect,
)
from sugar_source_tree.nodes import Call, ClassDef, FunctionDef
from sugar_source_tree.tree import SourceFile


def _source_file(source: str, *, context=None) -> SourceFile:
    from sugar_lift_python_source.canonical import blake3_512_of

    return SourceFile(
        (source, "renamed_fixture.py", blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def test_source_visible_zero_parameter_call_carries_the_ordinary_body() -> None:
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "def renamed_value():\n" "    return 7\n\n" "renamed_value()\n",
        context=context,
    )
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    call = next(node for node in source.nodes() if isinstance(node, Call))
    frame = function.source_visible_call_frame()
    context.source_call_frames[_coordinate(call)] = frame

    outcome = call.sugar().desugar()

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    assert outcome.value.body == frame.body
    assert outcome.value.parameters == ()
    assert frame.frame_cid.startswith("blake3-512:")
    constructed = outcome.value.force_floor(
        None, owner="source-visible-call-frame", project_callsite=False
    )
    assert isinstance(constructed, BlockValue)
    assert len(constructed.statements) == 1
    assert isinstance(constructed.statements[0], ReturnValue)
    assert constructed.statements[0].value == TermValue(7)


def test_renamed_generator_call_allocates_without_eager_body_reduction() -> None:
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "def arbitrarily_renamed():\n"
        "    yield 7\n"
        "    return 9\n\n"
        "arbitrarily_renamed()\n",
        context=context,
    )
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    call = next(node for node in source.nodes() if isinstance(node, Call))
    context.source_call_frames[_coordinate(call)] = function.source_visible_call_frame()

    outcome = call.sugar().desugar()

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, GeneratorConstructionV1)
    yielded = outcome.value.resume()
    assert isinstance(yielded, YieldEffect)
    assert yielded.value == TermValue(7)
    terminated = yielded.machine.resume()
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == TermValue(9)


def test_parameterized_source_frame_projects_the_exact_actual_by_coordinate() -> None:
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "def renamed_identity(value):\n" "    return value\n\n" "renamed_identity(7)\n",
        context=context,
    )
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    call = next(node for node in source.nodes() if isinstance(node, Call))
    context.source_call_frames[_coordinate(call)] = function.source_visible_call_frame()

    frame = function.source_visible_call_frame()
    context.source_call_frames[_coordinate(call)] = frame

    outcome = call.sugar().desugar()

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    assert len(frame.formal_coordinates) == 1
    assert frame.formal_coordinates[0].projection_path == ("formal", 0)
    constructed = outcome.value.force_floor(
        None, owner="coordinate-source-visible-call-frame", project_callsite=False
    )
    assert isinstance(constructed, BlockValue)
    assert isinstance(constructed.statements[0], ReturnValue)
    assert constructed.statements[0].value == TermValue(7)


def test_class_definition_constructs_methods_but_receiver_state_awaits_coordinate() -> (
    None
):
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "class RenamedGuard:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n\n"
        "    def enter(self):\n"
        "        return self\n\n"
        "RenamedGuard(11)\n",
        context=context,
    )
    class_node = next(node for node in source.nodes() if isinstance(node, ClassDef))
    call = next(node for node in source.nodes() if isinstance(node, Call))
    context.source_call_frames[_coordinate(call)] = (
        class_node.source_visible_constructor_frame()
    )

    outcome = class_node.sugar().desugar()

    assert isinstance(outcome, Complete)
    assert outcome.value.class_name == "RenamedGuard"
    assert tuple(method.name for method in outcome.value.methods) == (
        "__init__",
        "enter",
    )
    assert outcome.value.initializer is not None
    assert outcome.value.class_definition_cid.startswith("blake3-512:")
    receiver = (
        call.sugar()
        .desugar()
        .value.force_floor(None, owner="typed-class-call", project_callsite=False)
    )

    assert receiver.class_name == "RenamedGuard"
    assert {field.name: field.value for field in receiver.fields} == {
        "expected": TermValue(11)
    }
    assert receiver.identity.startswith("blake3-512:")


def test_repeated_initializer_uses_the_last_class_binding() -> None:
    """A later same-name definition is the executable Python class binding."""
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "class RenamedGuard:\n"
        "    def __init__(self, expected):\n"
        "        ...\n\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n\n"
        "RenamedGuard(11)\n",
        context=context,
    )
    class_node = next(node for node in source.nodes() if isinstance(node, ClassDef))
    call = next(node for node in source.nodes() if isinstance(node, Call))
    context.source_call_frames[_coordinate(call)] = (
        class_node.source_visible_constructor_frame()
    )

    receiver = (
        call.sugar()
        .desugar()
        .value.force_floor(None, owner="last-class-binding", project_callsite=False)
    )

    assert {field.name: field.value for field in receiver.fields} == {
        "expected": TermValue(11)
    }


def test_source_frame_binds_constructed_defaults_and_variadics() -> None:
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "def renamed_default(value=9):\n"
        "    return value\n\n"
        "def renamed_variadic(first, *rest, **options):\n"
        "    return rest\n\n"
        "renamed_default()\n"
        "renamed_variadic(1, 2, 3, label=4)\n",
        context=context,
    )
    functions = {
        node.name: node for node in source.nodes() if isinstance(node, FunctionDef)
    }
    calls = [node for node in source.nodes() if isinstance(node, Call)]
    context.source_call_frames[_coordinate(calls[0])] = functions[
        "renamed_default"
    ].source_visible_call_frame()
    context.source_call_frames[_coordinate(calls[1])] = functions[
        "renamed_variadic"
    ].source_visible_call_frame()

    default_call = calls[0].sugar().desugar().value
    default_block = default_call.force_floor(
        None, owner="default-call-frame", project_callsite=False
    )
    assert default_block.statements[0].value == TermValue(9)

    variadic_call = calls[1].sugar().desugar().value
    assert isinstance(variadic_call.arg_values[1], TupleValue)
    assert variadic_call.arg_values[1].elements == (TermValue(2), TermValue(3))
    assert isinstance(variadic_call.arg_values[2], DictValue)
    assert variadic_call.arg_values[2].entries == (
        (StringValue("label"), TermValue(4)),
    )


def test_class_body_assign_of_free_call_is_opaque_dig_cue() -> None:
    """Live law (replaces unsupported-Assign SugarNotWritten): class field Assign constructs.

    ``state = make_state()`` is a class field whose value is ``call:make_state``
    with ``body=None`` — an opaque dig cue, not a missing class-member sugar.
    """
    source = _source_file("class RenamedGuard:\n    state = make_state()\n")
    class_node = next(node for node in source.nodes() if isinstance(node, ClassDef))
    sugar = class_node.sugar()
    assert type(sugar).__name__ == "ClassDefinitionSugar"
    value = sugar.desugar().value
    field = next(f for f in value.class_fields if f.name == "state")
    assert field.value.term.name == "call:make_state"
    assert field.value.body is None


def test_yield_from_only_function_allocates_a_generator_not_an_eager_call() -> None:
    """TRUTHFUL FACE: `yield from` owns the suspension boundary just as `yield` does.

    Ownership recognized only `Yield`, so a `yield from`-only function built an
    ordinary eager call frame: the call completed as a plain `CallSiteValue`
    and the boundary escaped as an ordinary value. Both constructors of the
    boundary must make the function a generator.
    """
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "def arbitrarily_renamed():\n"
        "    yield from (1, 2)\n"
        "    return 9\n\n"
        "arbitrarily_renamed()\n",
        context=context,
    )
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    call = next(node for node in source.nodes() if isinstance(node, Call))
    frame = function.source_visible_call_frame()
    context.source_call_frames[_coordinate(call)] = frame

    assert frame.generator_steps is not None

    outcome = call.sugar().desugar()

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, GeneratorConstructionV1)
    assert not isinstance(outcome.value, CallSiteValue)


def test_yield_from_delegation_stays_a_typed_gap_and_is_never_invented() -> None:
    """LYING FACE: recognizing the boundary must not fabricate delegated iteration.

    Owning the boundary is exactly what the recognition fix buys; it does NOT
    buy `yield from`'s delegation protocol. Resuming names
    `GeneratorConstructionV1.transition` as the owner that still owes it, so
    the debt is loud and attributed rather than silently discharged as a
    yielded value or a termination.
    """
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "def arbitrarily_renamed():\n"
        "    yield from (1, 2)\n"
        "    return 9\n\n"
        "arbitrarily_renamed()\n",
        context=context,
    )
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    call = next(node for node in source.nodes() if isinstance(node, Call))
    context.source_call_frames[_coordinate(call)] = function.source_visible_call_frame()

    machine = call.sugar().desugar().value
    transition = machine.resume()

    assert isinstance(transition, GeneratorTransitionGapV1)
    assert transition.owner == "GeneratorConstructionV1.transition"
    assert transition.requested == "resume"
    assert not isinstance(transition, YieldEffect)
    assert not isinstance(transition, GeneratorTerminationV1)


def test_census_door_refuses_both_yield_constructors_with_no_call_site() -> None:
    """CLASSIFICATION PIN: the census door's yield refusals are accounted semantics.

    `functions() -> sugar -> desugar` reduces a function body with no call, so
    no call frame and therefore no generator instance can exist. Only
    `GeneratorConstructionV1` may consume a suspension boundary, so BOTH
    constructors must refuse here — permanently, for every implementation of
    the generator machine. These occurrences are correct output, not owed work,
    and no fix at any layer drains them.
    """
    from sugar_source_tree.panic import SugarNotWritten

    for body, owner in (
        ("    yield 7\n    return 9\n", "YieldSuspensionSugar.desugar"),
        ("    yield from (1, 2)\n    return 9\n", "YieldFromSugar.desugar"),
    ):
        source = _source_file("def arbitrarily_renamed():\n" + body)
        function = next(
            node for node in source.nodes() if isinstance(node, FunctionDef)
        )
        sugar = function.sugar()
        try:
            sugar.desugar(None)
        except SugarNotWritten as refusal:
            assert refusal.owner == owner
        else:
            raise AssertionError(f"{owner} must refuse under the census door")


def test_exception_subclass_without_init_accepts_message_actuals() -> None:
    """Truthful twin: inherited BaseException law is ``(*args)``.

    ``raise OptionError(msg)`` is ordinary Python. An empty constructor frame
    refused the message as SourceCallBindingGap and blocked every manager whose
    helpers only mentioned those raises (pandas option_context).
    """
    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "class RenamedOptionError(AttributeError, KeyError):\n"
        "    pass\n\n"
        "def helper(pat):\n"
        "    raise RenamedOptionError(f'no such key {pat!r}')\n",
        context=context,
    )
    class_node = next(node for node in source.nodes() if isinstance(node, ClassDef))
    frame = class_node.source_visible_constructor_frame()
    assert frame.parameters == ("args",)
    assert frame.parameter_kinds == ("vararg",)

    call = next(node for node in source.nodes() if isinstance(node, Call))
    context.source_call_frames[_coordinate(call)] = frame
    bound = frame.bind_node_actuals(call.args, ())
    assert bound.runtime_entries  # message consumed by *args
    # Constructing the raise expression must not raise SourceCallBindingGap.
    try:
        call.sugar()
    except SourceCallBindingGap as exc:  # pragma: no cover - regression guard
        raise AssertionError(f"exception construction refused: {exc}") from exc


def test_plain_class_without_init_still_refuses_constructor_actuals() -> None:
    """Lying twin: non-exception classes keep object.__init__ (zero formals)."""
    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "class RenamedPlain:\n"
        "    pass\n\n"
        "RenamedPlain(1)\n",
        context=context,
    )
    class_node = next(node for node in source.nodes() if isinstance(node, ClassDef))
    frame = class_node.source_visible_constructor_frame()
    assert frame.parameters == ()
    assert frame.parameter_kinds == ()
    call = next(node for node in source.nodes() if isinstance(node, Call))
    with pytest.raises(SourceCallBindingGap, match="unconsumed call actual"):
        frame.bind_node_actuals(call.args, ())

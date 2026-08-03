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
    ObjectValue,
    ReceiverFieldStoreValue,
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
from sugar_source_tree.panic import SugarNotWritten
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
    initializers = tuple(
        item
        for item in class_node.body
        if isinstance(item, FunctionDef) and item.name == "__init__"
    )
    frame = context.source_call_frames[_coordinate(call)]

    assert frame.formal_declaration_sites == (
        initializers[-1].params[1].fragment.seal().to_dict(),
    )
    assert frame.formal_declaration_sites != (
        initializers[0].params[1].fragment.seal().to_dict(),
    )

    receiver = (
        call.sugar()
        .desugar()
        .value.force_floor(None, owner="last-class-binding", project_callsite=False)
    )

    assert {field.name: field.value for field in receiver.fields} == {
        "expected": TermValue(11)
    }


def test_source_visible_new_constructor_retains_exact_instance_field() -> None:
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "class RenamedToken(int):\n"
        "    def __new__(cls, value, label):\n"
        "        self = super(RenamedToken, cls).__new__(cls, value)\n"
        "        self.label = label\n"
        "        return self\n\n"
        "RenamedToken(7, 'seven')\n",
        context=context,
    )
    class_node = next(node for node in source.nodes() if isinstance(node, ClassDef))
    call = tuple(node for node in source.nodes() if isinstance(node, Call))[-1]

    receiver = (
        call.sugar()
        .desugar()
        .value.force_floor(None, owner="source-visible-new", project_callsite=False)
    )

    assert receiver.class_name == "RenamedToken"
    assert receiver.attribute("label", call.fragment).value == StringValue("seven")
    assert class_node.source_visible_constructor_frame().owner is class_node


def test_source_visible_new_constructor_refuses_foreign_returned_receiver() -> None:
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "class RenamedToken(int):\n"
        "    def __new__(cls, value, label):\n"
        "        self = super(RenamedToken, cls).__new__(cls, value)\n"
        "        self.label = label\n"
        "        return value\n\n"
        "RenamedToken(7, 'seven')\n",
        context=context,
    )
    call = tuple(node for node in source.nodes() if isinstance(node, Call))[-1]

    coordinate = call.sugar().desugar().value

    assert isinstance(coordinate, CallSiteValue)
    assert coordinate.body is None


def test_source_visible_new_constructor_retains_exact_bound_name_field() -> None:
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "class NamedIntConstant(int):\n"
        "    def __new__(cls, value, name):\n"
        "        self = super(NamedIntConstant, cls).__new__(cls, value)\n"
        "        self.name = name\n"
        "        return self\n\n"
        "NamedIntConstant(7, 'seven')\n",
        context=context,
    )
    call = tuple(node for node in source.nodes() if isinstance(node, Call))[-1]

    receiver = (
        call.sugar()
        .desugar()
        .value.force_floor(None, owner="named-int-field-store", project_callsite=False)
    )

    assert isinstance(receiver, ObjectValue)
    assert tuple((field.name, field.value) for field in receiver.fields) == (
        ("name", StringValue("seven")),
    )


def test_new_receiver_field_store_refuses_foreign_receiver_identity() -> None:
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "class NamedIntConstant(int):\n"
        "    def __new__(cls, value, name):\n"
        "        self = super(NamedIntConstant, cls).__new__(cls, value)\n"
        "        self.name = name\n"
        "        return self\n",
        context=context,
    )
    class_node = next(node for node in source.nodes() if isinstance(node, ClassDef))
    class_value = class_node.sugar().desugar().value
    receiver_coordinate = (
        class_node.source_visible_constructor_frame().body.receiver_coordinate_cid
    )
    foreign = ObjectValue("NamedIntConstant", (), identity="foreign-receiver")
    block = BlockValue(
        (ReceiverFieldStoreValue(foreign, "name", StringValue("seven")),)
    )

    with pytest.raises(SugarNotWritten) as raised:
        class_value.construct_receiver_state_from_block(block, receiver_coordinate)

    assert raised.value.owner == "ClassDefinitionValue.construct_receiver_state"
    assert raised.value.observed == "receiver coordinate mismatch"


@pytest.mark.parametrize(
    "return_body",
    (
        "",
        "        if value:\n            return self\n",
    ),
    ids=("missing-return", "noncompleted-return"),
)
def test_source_visible_new_constructor_refuses_uncompleted_return(
    return_body: str,
) -> None:
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "class NamedIntConstant(int):\n"
        "    def __new__(cls, value, name):\n"
        "        self = super(NamedIntConstant, cls).__new__(cls, value)\n"
        "        self.name = name\n"
        f"{return_body}\n"
        "NamedIntConstant(7, 'seven')\n",
        context=context,
    )
    call = tuple(node for node in source.nodes() if isinstance(node, Call))[-1]

    coordinate = call.sugar().desugar().value

    assert isinstance(coordinate, CallSiteValue)
    assert coordinate.body is None


@pytest.mark.parametrize(
    "field_body",
    (
        "        self.name = name\n        self.name = name\n",
        "        self.label = name\n",
    ),
    ids=("duplicate-name-field", "wrong-field"),
)
def test_source_visible_new_constructor_refuses_nonexact_field_roster(
    field_body: str,
) -> None:
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "class NamedIntConstant(int):\n"
        "    def __new__(cls, value, name):\n"
        "        self = super(NamedIntConstant, cls).__new__(cls, value)\n"
        f"{field_body}"
        "        return self\n\n"
        "NamedIntConstant(7, 'seven')\n",
        context=context,
    )
    call = tuple(node for node in source.nodes() if isinstance(node, Call))[-1]

    coordinate = call.sugar().desugar().value

    assert isinstance(coordinate, CallSiteValue)
    assert coordinate.body is None


def test_constructor_frame_retains_exact_source_visible_new_method() -> None:
    """The class producer carries its exact ``__new__`` testimony to the body."""
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "class First:\n"
        "    def __new__(cls, value):\n"
        "        return cls\n\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n\n"
        "class Second:\n"
        "    def __new__(cls, value):\n"
        "        return cls\n\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n",
        context=context,
    )
    classes = {node.name: node for node in source.nodes() if isinstance(node, ClassDef)}
    first_new = next(
        item
        for item in classes["First"].body
        if isinstance(item, FunctionDef) and item.name == "__new__"
    )
    second_new = next(
        item
        for item in classes["Second"].body
        if isinstance(item, FunctionDef) and item.name == "__new__"
    )

    first_frame = classes["First"].source_visible_constructor_frame()
    second_frame = classes["Second"].source_visible_constructor_frame()

    testimony = first_frame.constructed_new_method
    assert testimony.name == "__new__"
    assert testimony.definition_fragment_cid == first_new.fragment.seal().cid
    assert testimony.source_call_frame.definition_site == _coordinate(first_new)
    assert (
        testimony.source_call_frame.frame_cid
        == first_new.source_visible_call_frame().frame_cid
    )
    assert first_frame.body.constructed_new_method is testimony
    assert (
        second_frame.constructed_new_method.source_call_frame.definition_site
        == _coordinate(second_new)
    )
    assert second_frame.constructed_new_method is not testimony


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


def test_class_body_chained_assign_constructs_each_exact_binding(monkeypatch) -> None:
    """One class-body Assign publishes every parser-owned Name target in order."""
    source = _source_file(
        "class RenamedFlags:\n    long_name = short = provider.member\n"
    )
    class_node = next(node for node in source.nodes() if isinstance(node, ClassDef))
    sugar = class_node.sugar()
    attribute = sugar.fields[0].value_sugar
    calls = []

    def complete_attribute(self, ctx=None):
        assert self is attribute
        calls.append((self, ctx))
        return Complete(TermValue(7))

    monkeypatch.setattr(type(attribute), "desugar", complete_attribute)

    value = sugar.desugar().value

    assert tuple(field.name for field in value.class_fields) == (
        "long_name",
        "short",
    )
    assert value.class_fields[0].value is value.class_fields[1].value
    assert value.class_fields[0].value == TermValue(7)
    assert calls == [(attribute, None)]


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


def test_yield_from_tuple_delegates_each_value_then_returns_to_the_generator() -> None:
    """A constructed ``yield from`` delegates in order, then resumes its tail.

    The direct-``yield`` test above is the discrimination arm: both suspension
    kinds reach the same generator consumer, while only this one must retain a
    delegated iterator across resumes.
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
    first = machine.resume()
    assert isinstance(first, YieldEffect)
    assert first.value == TermValue(1)
    second = first.machine.resume()
    assert isinstance(second, YieldEffect)
    assert second.value == TermValue(2)
    terminated = second.machine.resume()
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == TermValue(9)


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

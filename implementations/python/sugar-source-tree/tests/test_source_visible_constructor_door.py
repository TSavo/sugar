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
from sugar_lift_py_tests.outcome import ExitSet
from sugar_source_tree.nodes import Call, ClassDef, FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _source_file(source: str, *, context=None) -> SourceFile:
    from sugar_lift_python_source.canonical import blake3_512_of

    if context is None:
        # `construction_context=context` READS as contexted while defaulting to
        # a bare tree -- the door is decided by the CALLER, invisibly. This
        # file seats an invented locus (`renamed_fixture.py`), so no workspace
        # is reachable and the claim is true; callers that pass a real context
        # are unaffected.
        context = TreeConstructionContextV1.for_test_without_workspace()

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

    outcome = call.sugar().desugar()

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), CallSiteValue)
    assert outcome.completed_value().body == frame.body
    assert outcome.completed_value().parameters == ()
    assert frame.frame_cid.startswith("blake3-512:")
    constructed = outcome.completed_value().force_floor(
        None, owner="source-visible-call-frame", project_callsite=False
    )
    assert isinstance(constructed, BlockValue)
    assert len(constructed.statements) == 1
    assert isinstance(constructed.statements[0], ReturnValue)
    assert constructed.statements[0].value == TermValue(7)


def test_parameterized_source_frame_projects_the_exact_actual_by_coordinate() -> None:
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "def renamed_identity(value):\n" "    return value\n\n" "renamed_identity(7)\n",
        context=context,
    )
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    call = next(node for node in source.nodes() if isinstance(node, Call))
    frame = function.source_visible_call_frame()

    outcome = call.sugar().desugar()

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), CallSiteValue)
    assert len(frame.formal_coordinates) == 1
    assert frame.formal_coordinates[0].projection_path == ("formal", 0)
    constructed = outcome.completed_value().force_floor(
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

    outcome = class_node.sugar().desugar()

    assert outcome.completed_value() is not None
    assert outcome.completed_value().class_name == "RenamedGuard"
    assert tuple(method.name for method in outcome.completed_value().methods) == (
        "__init__",
        "enter",
    )
    assert outcome.completed_value().initializer is not None
    assert outcome.completed_value().class_definition_cid.startswith("blake3-512:")
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
    initializers = tuple(
        item
        for item in class_node.body
        if isinstance(item, FunctionDef) and item.name == "__init__"
    )
    frame = class_node.source_visible_constructor_frame()

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


def test_a_source_new_body_is_never_read_for_its_fields() -> None:
    """#7757 A4: a source ``__new__`` is a static method the class row
    dispatches, never a body whose stores are applied in place.  Over an
    ``int`` base no ``__new__`` door admits it (``ClassDef.returned_new``:
    the order holds a builtin whose own constructor law runs), so the call
    is the unanswered call, as every sibling shape below is: never an
    instance whose ``label`` was read off ``__new__``'s body."""
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

    assert class_node.returned_new() is None
    coordinate = call.sugar().desugar().completed_value()

    assert isinstance(coordinate, CallSiteValue)
    assert coordinate.body is None


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

    coordinate = call.sugar().desugar().completed_value()

    assert isinstance(coordinate, CallSiteValue)
    assert coordinate.body is None


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

    coordinate = call.sugar().desugar().completed_value()

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

    coordinate = call.sugar().desugar().completed_value()

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
    calls = [node for node in source.nodes() if isinstance(node, Call)]

    default_call = calls[0].sugar().desugar().completed_value()
    default_block = default_call.force_floor(
        None, owner="default-call-frame", project_callsite=False
    )
    assert default_block.statements[0].value == TermValue(9)

    variadic_call = calls[1].sugar().desugar().completed_value()
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
    value = sugar.desugar().completed_value()
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
        return ExitSet.completed(TermValue(7))

    monkeypatch.setattr(type(attribute), "desugar", complete_attribute)

    value = sugar.desugar().completed_value()

    assert tuple(field.name for field in value.class_fields) == (
        "long_name",
        "short",
    )
    assert value.class_fields[0].value is value.class_fields[1].value
    assert value.class_fields[0].value == TermValue(7)
    assert calls == [(attribute, None)]


def test_yield_from_only_function_owns_its_suspension() -> None:
    """TRUTHFUL FACE: `yield from` owns the suspension boundary just as `yield` does.

    Ownership recognized only `Yield`, so a `yield from`-only function was
    read as an ordinary function. Both constructors of the boundary make the
    function a generator (``FunctionDef._owns_yield``).
    """
    source = _source_file(
        "def arbitrarily_renamed():\n    yield from (1, 2)\n    return 9\n"
    )
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))

    assert FunctionDef._owns_yield(function.body)


def test_census_door_refuses_both_yield_constructors_with_no_call_site() -> None:
    """CLASSIFICATION PIN: the census door's yield refusals are accounted semantics.

    `functions() -> sugar -> desugar` reduces a function body with no call, so
    no call frame and therefore no generator instance can exist. No reduction
    consumes a suspension boundary (a generator call is its definition's
    coordinate and edge, joined at prove: #7757 step 6), so BOTH constructors
    refuse here, by name. These occurrences are correct output, not owed work,
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


_ENGINE_PICKING_NEW = (
    "class RenamedEngine:\n"
    "    def __init__(self, value):\n"
    "        self.engine_value = value\n\n"
    "class RenamedWriter:\n"
    "    def __new__(cls, value):\n"
    "        return object.__new__(RenamedEngine)\n\n"
    "    def __init__(self, value):\n"
    "        self.writer_value = value\n\n"
    "RenamedWriter(11)\n"
)


def _construct_last_class_call(source_text: str):
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(source_text, context=context)
    call = tuple(node for node in source.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar().completed_value().force_floor(
        None, owner="class-call-with-source-new", project_callsite=False
    )


def test_class_call_refuses_a_source_new_it_does_not_run() -> None:
    """TRUTHFUL FACE (#7665): ``Cls(...)`` runs ``Cls.__new__`` before ``__init__``.

    ``RenamedWriter.__new__`` returns an ``RenamedEngine`` (as pandas
    ``ExcelWriter.__new__`` returns its engine class). The constructor door
    only runs ``__init__``, so it must refuse by naming the unrun ``__new__``.
    """
    with pytest.raises(SugarNotWritten) as raised:
        _construct_last_class_call(_ENGINE_PICKING_NEW)

    assert raised.value.owner == "ClassConstructorBodySugar.__new__"
    assert "RenamedWriter.__new__" in raised.value.observed


def test_class_call_never_runs_init_on_a_receiver_new_did_not_return() -> None:
    """LYING FACE (#7665): the old door built ``RenamedWriter(writer_value=11)``.

    Python builds a ``RenamedEngine`` here and never runs
    ``RenamedWriter.__init__``. Neither the skipped-``__new__`` receiver nor a
    spelling-trusted pass-through ``__new__`` may complete; only the same class
    without a source ``__new__`` constructs through ``__init__``.
    """
    for source_text in (
        _ENGINE_PICKING_NEW,
        _ENGINE_PICKING_NEW.replace(
            "object.__new__(RenamedEngine)", "object.__new__(cls)"
        ),
    ):
        with pytest.raises(SugarNotWritten):
            _construct_last_class_call(source_text)

    without_new = _ENGINE_PICKING_NEW.replace(
        "    def __new__(cls, value):\n"
        "        return object.__new__(RenamedEngine)\n\n",
        "",
    )
    receiver = _construct_last_class_call(without_new)
    assert receiver.class_name == "RenamedWriter"
    assert {field.name: field.value for field in receiver.fields} == {
        "writer_value": TermValue(11)
    }


def test_class_value_application_runs_a_returned_new_and_keeps_plain_class() -> None:
    """Both twins on ``ClassDefinitionValue.callable_application_with`` (#7665).

    TRUTHFUL: a class whose own ``__new__`` runs and whose ``__init__`` is
    ``object``'s (``ClassDef.returned_new``) runs that ``__new__`` through
    the one method door and returns what it returned, never a fresh receiver
    ``__new__`` did not return: ``1`` is no instance of the class, so
    ``type.__call__`` runs nothing on it, and the call completes owing
    nothing.  LYING: the plain zero-argument class (no ``__new__``) must
    still construct its receiver rather than be refused wholesale.
    """
    from types import SimpleNamespace

    from sugar_lift_py_tests.outcome import Halted
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    def class_value(text: str):
        source = _source_file(text)
        class_node = next(n for n in source.nodes() if isinstance(n, ClassDef))
        return class_node.sugar().desugar().completed_value()

    operation = SimpleNamespace(site="renamed-site", arguments=(), keyword_names=())
    returned = class_value(
        "class RenamedWriter:\n    def __new__(cls):\n        return 1\n"
    ).callable_application_with(operation, None)
    assert not any(isinstance(face, Halted) for face in returned.exits)
    assert owed_calls(returned) == ()
    made = returned.completed_value()
    assert made is not None
    assert getattr(made, "class_name", None) != "RenamedWriter"

    plain = class_value(
        "class RenamedWriter:\n    def write(self):\n        return 1\n"
    ).callable_application_with(operation, None)
    assert plain.completed_value() is not None
    assert plain.completed_value().class_name == "RenamedWriter"

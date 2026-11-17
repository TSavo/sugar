from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    TermValue,
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


def _completed_values(outcome) -> tuple:
    """The value of every completed face of ``outcome``, at least one.

    A call nothing answers, and a class call whose ``__new__`` and
    ``__init__`` are dispatched edges joined at prove (#7757 A4, B3), is
    two-faced: its halt is kept beside its completion, so it is never one
    unconditional value (``completed_value``)."""
    from sugar_lift_py_tests.outcome import Completed

    assert isinstance(outcome, ExitSet), outcome
    values = tuple(
        face.value
        for face in outcome.normalize().exits
        if isinstance(face, Completed)
    )
    assert values, outcome.exits
    return values


def _unanswered_call_coordinates(outcome) -> tuple:
    """The call coordinate on every completed face of a class call nothing
    here answers.  No contract here states what the call reaches, so each
    completed value carries its record that it may reach every module
    global (#9108, ``call_site_value.bind_after_call``); the coordinate is
    the value beneath that record."""
    from sugar_lift_py_tests.floor.call_site_value import AfterCallRecordValue
    from sugar_lift_py_tests.floor.named_expression_value import (
        peel_walrus_binds,
    )

    coordinates = []
    for value in _completed_values(outcome):
        binds, coordinate = peel_walrus_binds(value)
        assert any(
            isinstance(bind.assigned_value, AfterCallRecordValue)
            and bind.assigned_value.reaches_every_global()
            for bind in binds
        ), binds
        coordinates.append(coordinate)
    return tuple(coordinates)


def _field_names(value) -> set:
    """The fields a value states it holds, by name (none when it states
    none: a dispatched call's result holds what prove joins)."""
    return {
        field.name
        for field in (
            *(getattr(value, "fields", None) or ()),
            *(getattr(value, "class_fields", None) or ()),
        )
    }


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
    # The receiver's state awaits the coordinate: ``__init__`` is the
    # dispatched edge prove joins (#7757 B3), never a body run in place, so
    # no completed face of the class call holds ``expected`` read off it.
    for receiver in _completed_values(call.sugar().desugar()):
        assert "expected" not in _field_names(receiver)


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
    # The last ``__init__`` is dispatched, never run in place (#7757 B3).
    for receiver in _completed_values(call.sugar().desugar()):
        assert "expected" not in _field_names(receiver)


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
    for coordinate in _unanswered_call_coordinates(call.sugar().desugar()):
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

    for coordinate in _unanswered_call_coordinates(call.sugar().desugar()):
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

    for coordinate in _unanswered_call_coordinates(call.sugar().desugar()):
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

    for coordinate in _unanswered_call_coordinates(call.sugar().desugar()):
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


def test_class_body_assign_of_free_call_is_opaque_dig_cue() -> None:
    """Live law (replaces unsupported-Assign SugarNotWritten): class field Assign constructs.

    ``state = make_state()`` is a class field whose value is ``call:make_state``
    with ``body=None`` — an opaque dig cue, not a missing class-member sugar.
    """
    # ``make_state`` only an unreadable star import may bind: never a NameError.
    source = _source_file(
        "from unread_module import *\n"
        "class RenamedGuard:\n    state = make_state()\n"
    )
    class_node = next(node for node in source.nodes() if isinstance(node, ClassDef))
    sugar = class_node.sugar()
    assert type(sugar).__name__ == "ClassDefinitionSugar"
    # ``make_state()`` is the unanswered call: completed only on its own
    # face, its halt kept, its value ``python:call_result(call:make_state(),
    # <occurrence>)`` (``_occurrence_result``).
    for value in _completed_values(sugar.desugar()):
        field = next(f for f in value.class_fields if f.name == "state")
        assert field.value.term.name == "python:call_result"
        assert field.value.term.args[0].name == "call:make_state"
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
    # Evaluated once, under whatever context the class body reduces it in.
    assert [called for called, _ctx in calls] == [attribute]


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


def test_census_door_reduces_a_yield_and_refuses_a_yield_from() -> None:
    """CLASSIFICATION PIN: the census door reduces a generator body through
    its ``yield`` and states no result of its call.

    `functions() -> sugar -> desugar` reduces a function body with no call.
    A ``yield`` is the two-faced resume (``YieldSuspensionSugar``): the body
    runs past it to its ``return``, and the universe of a generator function
    states nothing about the call's ``out`` (``UniverseValue.suspends``): its
    call returns the generator, never the ``9`` the body returns.  A
    ``yield from`` still refuses by name (``YieldFromSugar.desugar``).
    """
    from sugar_lift_py_tests.floor.universe_value import UniverseValue
    from sugar_lift_py_tests.ir import and_
    from sugar_lift_py_tests.outcome.exit_set import Completed

    source = _source_file("def arbitrarily_renamed():\n    yield 7\n    return 9\n")
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    sugar = function.sugar()
    assert sugar.suspends
    completed = [
        exit_.value
        for exit_ in sugar.desugar(None).exits
        if isinstance(exit_, Completed)
    ]
    assert completed
    for universe in completed:
        assert isinstance(universe, UniverseValue)
        assert universe.suspends
        assert universe.post() == and_([])

    source = _source_file(
        "def arbitrarily_renamed():\n    yield from (1, 2)\n    return 9\n"
    )
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    try:
        function.sugar().desugar(None)
    except SugarNotWritten as refusal:
        assert refusal.owner == "YieldFromSugar.desugar"
    else:
        raise AssertionError("YieldFromSugar.desugar must refuse under the census door")


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


def _last_class_call_values(source_text: str) -> tuple:
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(source_text, context=context)
    call = tuple(node for node in source.nodes() if isinstance(node, Call))[-1]
    from sugar_lift_py_tests.outcome import Completed

    # Every completed face, none included: a lie needs a completed face.
    return tuple(
        face.value
        for face in call.sugar().desugar().normalize().exits
        if isinstance(face, Completed)
    )


def test_class_call_never_runs_init_on_a_receiver_new_did_not_return() -> None:
    """LYING FACE (#7665): the old door built ``RenamedWriter(writer_value=11)``.

    Python builds a ``RenamedEngine`` here and never runs
    ``RenamedWriter.__init__``. A class call dispatches its ``__new__`` and
    then ``__init__`` on what ``__new__`` returned, each an edge prove joins
    (#7757 A4, B3): no body is read at lift.  So with an engine-picking
    ``__new__``, a spelling-trusted pass-through one, or none, no completed
    face holds a receiver whose fields were read off an ``__init__`` body.
    """
    without_new = _ENGINE_PICKING_NEW.replace(
        "    def __new__(cls, value):\n"
        "        return object.__new__(RenamedEngine)\n\n",
        "",
    )
    for source_text in (
        _ENGINE_PICKING_NEW,
        _ENGINE_PICKING_NEW.replace(
            "object.__new__(RenamedEngine)", "object.__new__(cls)"
        ),
        without_new,
    ):
        for receiver in _last_class_call_values(source_text):
            assert not _field_names(receiver) & {"writer_value", "engine_value"}


def test_class_value_application_runs_a_returned_new_and_keeps_plain_class() -> None:
    """Both twins on ``ClassDefinitionValue.callable_application_with`` (#7665).

    TRUTHFUL: a class whose own ``__new__`` runs and whose ``__init__`` is
    ``object``'s (``ClassDef.returned_new``) runs that ``__new__`` through
    the one method door, a dispatched call whose body is never read, and
    returns what it returned, never a fresh receiver ``__new__`` did not
    return; the dispatched call's halts are kept.  LYING: the plain
    zero-argument class (no ``__new__``) must still construct its receiver
    rather than be refused wholesale.
    """
    from types import SimpleNamespace

    from sugar_lift_py_tests.outcome import Halted

    def class_value(text: str):
        source = _source_file(text)
        class_node = next(n for n in source.nodes() if isinstance(n, ClassDef))
        return class_node.sugar().desugar().completed_value()

    operation = SimpleNamespace(site="renamed-site", arguments=(), keyword_names=())
    returned = class_value(
        "class RenamedWriter:\n    def __new__(cls):\n        return 1\n"
    ).callable_application_with(operation, None)
    # ``__new__`` is the dispatched call looked up on the class object and
    # joined at prove (#7757 A4): its body (``return 1``) is never read here,
    # so its halts are the class call's, kept, and no completed face is a
    # fresh ``RenamedWriter`` receiver ``__new__`` did not return.
    assert any(isinstance(face, Halted) for face in returned.exits)
    for made in _completed_values(returned):
        assert getattr(made, "class_name", None) != "RenamedWriter"

    plain = class_value(
        "class RenamedWriter:\n    def write(self):\n        return 1\n"
    ).callable_application_with(operation, None)
    assert plain.completed_value() is not None
    assert plain.completed_value().class_name == "RenamedWriter"

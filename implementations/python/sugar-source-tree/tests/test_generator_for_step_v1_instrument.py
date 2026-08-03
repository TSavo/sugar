"""Honest-red instrument for the general generator ``ForStepV1`` law.

The concrete reproducer is the source shape used by an option-pair generator:
apply every ``(pat, value)`` before the yield, then apply the saved ``undo``
pairs in ``finally``.  The names are evidence only; admission must remain
structural.  The renamed twin below must construct the same step vocabulary.

Green requires one producer-owned ``ForStepV1`` mechanism that carries the
iterable as ``ConstructedTermSugar``, authenticated target binding coordinates,
and ordered ``TermStepV1`` body calls.  Transition must use the existing
``iter_with`` / ``next_with`` floor doors, thread the advanced iterator and
per-iteration bindings, preserve body halts, recognize only authenticated
``StopIteration`` as exhaustion, and run paired ``finally`` cleanup on every
outgoing edge.  No spelling/vendor arm or consumer reconstruction can satisfy
these tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from sugar_lift_py_tests import generator_construction as generator_api
from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.floor.iterator_value import (
    ListIteratorValue,
    NextResult,
)
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.tuple_value import TupleValue
from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted, Incomplete
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.binding_state import mint_binding_coordinate_v1
from sugar_source_tree.nodes import For, FunctionDef
from sugar_source_tree.tree import SourceFile

_OPTION_PAIR_MANAGER = (
    "def option_pair_manager(ops, undo):\n"
    "    for pat, value in ops:\n"
    "        _set_option(pat, value)\n"
    "    try:\n"
    "        yield None\n"
    "    finally:\n"
    "        for pat, value in undo:\n"
    "            _set_option(pat, value)\n"
)

_RENAMED_TWIN = (
    "def renamed_pair_scope(pairs, restore_pairs):\n"
    "    for left, right in pairs:\n"
    "        apply_pair(left, right)\n"
    "    try:\n"
    "        yield None\n"
    "    finally:\n"
    "        for left, right in restore_pairs:\n"
    "            apply_pair(left, right)\n"
)


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "generator_for_step_v1.py", blake3_512_of(source.encode("utf-8")))
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _missing_for_step_message() -> str:
    return (
        "ForStepV1 is the missing general generator step: retain the constructed "
        "iterable and authenticated target binding coordinates; transition only "
        "through iter_with/next_with and authenticated StopIteration"
    )


def _for_step_type():
    step_type = getattr(generator_api, "ForStepV1", None)
    assert step_type is not None, _missing_for_step_message()
    return step_type


def _term_step_type():
    step_type = getattr(generator_api, "TermStepV1", None)
    assert step_type is not None, (
        "ForStepV1 body calls must be ordered TermStepV1 values; land the "
        "general term-step vocabulary before implementing this mechanism"
    )
    return step_type


def _steps(source: str):
    function = _function(source)
    return function._source_visible_generator_steps_from(function.body)


def _for_steps(source: str):
    for_step_type = _for_step_type()
    found = []

    def visit(step) -> None:
        if isinstance(step, for_step_type):
            found.append(step)
        # The cleanup loop remains paired with FinallyStepV1.  Permit the
        # finally owner to name its child-step field; do not require flattening
        # the cleanup into the ordinary fall-through sequence.
        for field_name in (
            "body_steps",
            "then_steps",
            "else_steps",
            "cleanup_steps",
            "statements",
        ):
            children = getattr(step, field_name, ())
            if isinstance(children, tuple):
                for child in children:
                    visit(child)

    for root in _steps(source):
        visit(root)
    return tuple(found)


def _for_steps_with_parents(source: str):
    for_step_type = _for_step_type()
    found = []

    def visit(step, parent) -> None:
        if isinstance(step, for_step_type):
            found.append((step, parent))
        for field_name in (
            "body_steps",
            "then_steps",
            "else_steps",
            "cleanup_steps",
            "statements",
        ):
            children = getattr(step, field_name, ())
            if isinstance(children, tuple):
                for child in children:
                    visit(child, step)

    for root in _steps(source):
        visit(root, None)
    return tuple(found)


def _target_coordinate_cids(step) -> tuple[str, ...]:
    coordinates = getattr(step, "target_coordinates", None)
    assert coordinates is not None, (
        "ForStepV1 must carry producer-authenticated target_coordinates; names "
        "or transition-time reconstruction are forbidden"
    )
    cids = tuple(getattr(coordinate, "cid", None) for coordinate in coordinates)
    assert cids and all(
        isinstance(cid, str) and cid.startswith("blake3-512:") for cid in cids
    ), "every ForStepV1 target coordinate must be producer-authenticated"
    assert len(cids) == len(set(cids)), "tuple target positions require distinct CIDs"
    return cids


def test_option_pair_loops_construct_two_general_for_steps() -> None:
    """Truthful face: pre-yield apply and paired cleanup are both ForStepV1."""
    _for_step_type()
    term_step_type = _term_step_type()

    for_steps = _for_steps(_OPTION_PAIR_MANAGER)

    assert (
        len(for_steps) == 2
    ), "the pre-yield ops loop and finally undo loop must both remain explicit"
    assert all(isinstance(step.iterable, ConstructedTermSugar) for step in for_steps)
    assert all(
        len(step.body_steps) == 1 and isinstance(step.body_steps[0], term_step_type)
        for step in for_steps
    ), "each iteration performs exactly one ordered TermStepV1 call"
    assert all(len(_target_coordinate_cids(step)) == 2 for step in for_steps)


def test_renamed_pair_manager_uses_the_same_general_step_vocabulary() -> None:
    """Lying-name twin: no function, iterable, target, or callee spelling arm."""
    for_step_type = _for_step_type()
    exact = _for_steps(_OPTION_PAIR_MANAGER)
    renamed = _for_steps(_RENAMED_TWIN)

    assert tuple(type(step) for step in exact) == (for_step_type, for_step_type)
    assert tuple(type(step) for step in renamed) == (for_step_type, for_step_type)
    assert tuple(len(_target_coordinate_cids(step)) for step in exact) == (2, 2)
    assert tuple(len(_target_coordinate_cids(step)) for step in renamed) == (2, 2)


def test_cleanup_iterable_and_target_coordinates_are_not_reconstructed() -> None:
    """Lying testimony twin: cleanup identity and both target sites stay distinct."""
    before, cleanup = _for_steps(_OPTION_PAIR_MANAGER)

    assert (
        before.iterable != cleanup.iterable
    ), "ops and undo are distinct authenticated constructed iterables"
    assert _target_coordinate_cids(before) != _target_coordinate_cids(
        cleanup
    ), "same target spellings at different loop sites must not share identity"
    assert before.fragment_cid != cleanup.fragment_cid


def test_cleanup_for_step_remains_owned_by_finally_not_flattened() -> None:
    """Lying-edge twin: lexical cleanup cannot become ordinary fall-through."""
    finally_step_type = getattr(generator_api, "FinallyStepV1", None)
    assert finally_step_type is not None
    pairs = _for_steps_with_parents(_OPTION_PAIR_MANAGER)

    assert len(pairs) == 2
    assert pairs[0][1] is None, "the pre-yield loop is ordinary generator flow"
    assert isinstance(pairs[1][1], finally_step_type), (
        "the undo loop must remain a child of FinallyStepV1 so return, halt, "
        "throw, close, and fall-through all route through it"
    )


def test_for_step_transition_contract_is_explicit_and_owner_complete() -> None:
    """The step itself names every state/exit obligation; consumers do not infer it."""
    for_step_type = _for_step_type()
    fields = getattr(for_step_type, "__dataclass_fields__", {})

    required = {
        "iterable",
        "target_coordinates",
        "body_steps",
        "module_cid",
        "fragment_cid",
    }
    assert required <= set(fields), (
        "ForStepV1 must own iterable, target coordinates, ordered body, and "
        "occurrence testimony so transition can thread iterator/binding state, "
        "preserve body halts, accept only authenticated StopIteration, and route "
        "fall-through/return/halt through paired finally cleanup"
    )


@dataclass(frozen=True)
class _ValueSugar(ConstructedTermSugar):
    value: FloorValue
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)

    def to_term(self, *, owner: str):
        return self.value.to_term(owner=owner)


@dataclass(frozen=True)
class _TracingIterable(FloorValue):
    elements: tuple[FloorValue, ...]
    events: list = field(compare=False, repr=False)

    def iter_with(self, operation, ctx):
        del operation, ctx
        self.events.append("iter_with")
        return Complete(_TracingIterator(self.elements, self.events))


@dataclass(frozen=True)
class _TracingIterator(FloorValue):
    elements: tuple[FloorValue, ...]
    events: list = field(compare=False, repr=False)

    def next_with(self, operation, ctx):
        self.events.append("next_with")
        if not self.elements:
            # Production authentication door: source occurrence + builtin
            # StopIteration coordinate. The test never fabricates the effect.
            return ListIteratorValue((), index=0).next_with(operation, ctx)
        return Complete(
            NextResult(
                self.elements[0],
                _TracingIterator(self.elements[1:], self.events),
            )
        )


@dataclass(frozen=True)
class _NextHaltIterable(FloorValue):
    effect: object
    events: list = field(compare=False, repr=False)

    def iter_with(self, operation, ctx):
        del operation, ctx
        self.events.append("iter_with")
        return Complete(_NextHaltIterator(self.effect, self.events))


@dataclass(frozen=True)
class _NextHaltIterator(FloorValue):
    effect: object
    events: list = field(compare=False, repr=False)

    def next_with(self, operation, ctx):
        del operation, ctx
        self.events.append("next_with")
        return Incomplete(self.effect)


@dataclass(frozen=True)
class _ObserveTargetBindings(ConstructedTermSugar):
    coordinate_cids: tuple[str, ...]
    events: list = field(compare=False, repr=False)
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        values = tuple(ctx.temporal.value_for(cid) for cid in self.coordinate_cids)
        self.events.append(("body", values))
        return Complete(TermValue(0))

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:test-observe-for-bindings",
            tuple(str_const(cid) for cid in self.coordinate_cids),
            symbol_kind="coordinate",
        )


@dataclass(frozen=True)
class _HaltBody(ConstructedTermSugar):
    effect: object
    events: list = field(compare=False, repr=False)
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        self.events.append("body_halt")
        return Incomplete(self.effect)

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import str_const

        del owner
        return str_const("test:for-body-halt")


def _runtime_for_step(events: list, *, elements=None, body_term=None):
    from dataclasses import replace

    for_step_type = _for_step_type()
    term_step_type = _term_step_type()
    function = _function(
        "def renamed(ops):\n"
        "    for left, right in ops:\n"
        "        apply_pair(left, right)\n"
        "    yield None\n"
    )
    source_for = next(node for node in function.body if isinstance(node, For))
    produced = next(
        step
        for step in function._source_visible_generator_steps_from(function.body)
        if isinstance(step, for_step_type)
    )
    coordinates = produced.target_coordinates
    if elements is None:
        elements = (
            TupleValue((TermValue(1), TermValue(2))),
            TupleValue((TermValue(3), TermValue(4))),
        )
    iterable = _TracingIterable(tuple(elements), events)
    if body_term is None:
        body_term = _ObserveTargetBindings(
            tuple(coordinate.cid for coordinate in coordinates),
            events,
            source_for.body[0].fragment,
        )
    step = replace(
        produced,
        iterable=_ValueSugar(iterable, source_for.iter.fragment),
        body_steps=(term_step_type(body_term, source_for.body[0].fragment.seal().cid),),
    )
    return generator_api.GeneratorConstructionV1.allocate(
        allocation_coordinate="call:renamed",
        frame_coordinate="frame:renamed",
        binding_state=(),
        steps=(step, generator_api.ReturnStepV1()),
        reduction_context=ReduceContext.root(owner="ForStepV1-test"),
    )


@dataclass(frozen=True)
class _IterableHaltSugar(ConstructedTermSugar):
    effect: object
    events: list = field(compare=False, repr=False)
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        self.events.append("iterable_halt")
        return Incomplete(self.effect)

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import str_const

        del owner
        return str_const("test:for-iterable-halt")


@dataclass(frozen=True)
class _HaltOnBodyVisit(ConstructedTermSugar):
    halt_at: int
    effect: object
    visits: list = field(compare=False, repr=False)
    events: list = field(compare=False, repr=False)
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        visit = len(self.visits) + 1
        self.visits.append(visit)
        self.events.append(("body_visit", visit))
        if visit == self.halt_at:
            return Incomplete(self.effect)
        return Complete(TermValue(visit))

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import str_const

        del owner
        return str_const(f"test:halt-on-body:{self.halt_at}")


def test_for_step_uses_iter_next_and_threads_each_advanced_binding_state() -> None:
    """Truthful transition: two items, ordered bodies, then exact exhaustion."""
    events = []
    outcome = _runtime_for_step(events).resume()

    assert isinstance(outcome, generator_api.GeneratorTerminationV1)
    assert events == [
        "iter_with",
        "next_with",
        ("body", (TermValue(1), TermValue(2))),
        "next_with",
        ("body", (TermValue(3), TermValue(4))),
        "next_with",
    ]


def test_empty_iterable_orders_iter_then_one_authenticated_next() -> None:
    """Empty truthful twin: no body step and no fabricated extra recurrence."""
    events = []

    outcome = _runtime_for_step(events, elements=()).resume()

    assert isinstance(outcome, generator_api.GeneratorTerminationV1)
    assert events == ["iter_with", "next_with"]


def test_swapped_authenticated_target_coordinates_swap_observed_values() -> None:
    """Order twin: coordinate authentication does not erase tuple position."""
    from dataclasses import replace

    events = []
    machine = _runtime_for_step(
        events, elements=(TupleValue((TermValue(1), TermValue(2))),)
    )
    step = machine.steps[0]
    swapped = replace(step, target_coordinates=tuple(reversed(step.target_coordinates)))
    machine = replace(machine, steps=(swapped, generator_api.ReturnStepV1()))

    outcome = machine.resume()

    assert isinstance(outcome, generator_api.GeneratorTerminationV1)
    assert events == [
        "iter_with",
        "next_with",
        ("body", (TermValue(2), TermValue(1))),
        "next_with",
    ]


def test_iterable_halt_is_preserved_before_iter_with() -> None:
    """Iterable effect twin: reduction halt cannot be rebuilt as an iterator."""
    from dataclasses import replace

    from sugar_lift_py_tests.floor.ground_exit import ground_raise_effect

    events = []
    machine = _runtime_for_step(events)
    step = machine.steps[0]
    effect = ground_raise_effect(
        exception_name="ValueError",
        site=step.iterable.site,
        owner="ForStepV1-iterable-halt-test",
    )
    halted = replace(
        step,
        iterable=_IterableHaltSugar(effect, events, step.iterable.site),
    )
    machine = replace(machine, steps=(halted, generator_api.ReturnStepV1()))

    outcome = machine.resume()

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    assert isinstance(outcome.exits[0], Halted)
    assert outcome.exits[0].effect is effect
    assert events == ["iterable_halt"]


def test_for_occurrence_and_fragment_cid_must_authenticate_each_other() -> None:
    """CID twin: a real site paired with another loop CID stays loud."""
    from dataclasses import replace

    machine = _runtime_for_step([])
    step = machine.steps[0]
    foreign = _for_steps(_RENAMED_TWIN)[0]

    with pytest.raises(ConstructionPanic):
        mismatched = replace(step, fragment_cid=foreign.fragment_cid)
        replace(machine, steps=(mismatched, generator_api.ReturnStepV1())).resume()


def test_same_target_spelling_cannot_resolve_at_foreign_coordinates() -> None:
    """Lying-coordinate twin: target names never authorize body reads."""
    machine = _runtime_for_step([])
    step = machine.steps[0]
    coordinates = tuple(step.target_coordinates)
    forged = tuple(
        mint_binding_coordinate_v1(
            scope_owner_cid=coordinate.scope_owner_cid,
            binding_site=_function("def other():\n    yield None\n").fragment,
            projection_path=coordinate.projection_path,
        )
        for coordinate in coordinates
    )
    observed = _ObserveTargetBindings(
        tuple(coordinate.cid for coordinate in forged),
        [],
        step.iterable.site,
    )
    wrong_body = _term_step_type()(
        observed,
        step.body_steps[0].fragment_cid,
    )
    from dataclasses import replace

    wrong = replace(step, body_steps=(wrong_body,))
    machine = type(machine).allocate(
        allocation_coordinate="call:wrong-coordinate",
        frame_coordinate="frame:wrong-coordinate",
        binding_state=(),
        steps=(wrong, generator_api.ReturnStepV1()),
        reduction_context=ReduceContext.root(owner="ForStepV1-wrong-coordinate"),
    )

    with pytest.raises(ConstructionPanic):
        machine.resume()


@pytest.mark.parametrize("halt_at", [1, 2])
def test_first_or_second_body_halt_stops_before_the_next_recurrence(
    halt_at: int,
) -> None:
    """Body-halt twins pin state threading at both recurrence positions."""
    from dataclasses import replace

    from sugar_lift_py_tests.floor.ground_exit import ground_raise_effect

    events = []
    machine = _runtime_for_step(events)
    step = machine.steps[0]
    effect = ground_raise_effect(
        exception_name="ValueError",
        site=step.iterable.site,
        owner="ForStepV1-body-halt-test",
    )
    visits = []
    halted_body = _HaltOnBodyVisit(halt_at, effect, visits, events, step.iterable.site)
    halted_step = replace(
        step,
        body_steps=(_term_step_type()(halted_body, step.body_steps[0].fragment_cid),),
    )
    machine = replace(machine, steps=(halted_step, generator_api.ReturnStepV1()))

    outcome = machine.resume()

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    assert isinstance(outcome.exits[0], Halted)
    assert outcome.exits[0].effect is effect
    assert visits == list(range(1, halt_at + 1))
    assert events.count("next_with") == halt_at
    assert events[-1] == ("body_visit", halt_at)


def test_stopiteration_spelling_with_foreign_identity_does_not_exhaust() -> None:
    """Lying twin: the exception label cannot replace its type coordinate."""
    from dataclasses import replace

    from sugar_lift_py_tests.floor.ground_exit import ground_raise_effect

    events = []
    machine = _runtime_for_step(events)
    step = machine.steps[0]
    value_error = ground_raise_effect(
        exception_name="ValueError",
        site=step.iterable.site,
        owner="ForStepV1-foreign-stop-test",
    )
    foreign_stop = replace(value_error, exception_name="StopIteration")
    wrong = replace(
        step,
        iterable=_ValueSugar(
            _NextHaltIterable(foreign_stop, events),
            step.iterable.site,
        ),
    )
    machine = replace(machine, steps=(wrong, generator_api.ReturnStepV1()))

    outcome = machine.resume()

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    assert isinstance(outcome.exits[0], Halted)
    assert outcome.exits[0].effect is foreign_stop
    assert events == ["iter_with", "next_with"]


def test_stopiteration_identity_at_wrong_occurrence_does_not_exhaust() -> None:
    """Occurrence twin: builtin type identity alone cannot authenticate this loop."""
    from dataclasses import replace

    from sugar_lift_py_tests.floor.ground_exit import ground_raise_effect

    events = []
    machine = _runtime_for_step(events)
    step = machine.steps[0]
    foreign_site = _function("def foreign():\n    yield None\n").fragment
    wrong_occurrence = ground_raise_effect(
        exception_name="StopIteration",
        site=foreign_site,
        owner="ForStepV1-wrong-stop-occurrence-test",
    )
    wrong = replace(
        step,
        iterable=_ValueSugar(
            _NextHaltIterable(wrong_occurrence, events),
            step.iterable.site,
        ),
    )
    machine = replace(machine, steps=(wrong, generator_api.ReturnStepV1()))

    outcome = machine.resume()

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    assert isinstance(outcome.exits[0], Halted)
    assert outcome.exits[0].effect is wrong_occurrence
    assert events == ["iter_with", "next_with"]


def _suspended_with_for_cleanup(events: list):
    loop = _runtime_for_step(events).steps[0]
    machine = generator_api.GeneratorConstructionV1.allocate(
        allocation_coordinate="call:finally-for",
        frame_coordinate="frame:finally-for",
        binding_state=(),
        steps=(
            generator_api.YieldStepV1(None),
            generator_api.FinallyStepV1((), cleanup_steps=(loop,)),
            generator_api.ReturnStepV1(),
        ),
        reduction_context=ReduceContext.root(owner="ForStepV1-finally-test"),
    )
    yielded = machine.resume()
    assert isinstance(yielded, generator_api.YieldEffect)
    return yielded.machine, loop.iterable.site


@pytest.mark.parametrize("outgoing", ["close", "throw"])
def test_for_cleanup_runs_on_each_outgoing_edge(outgoing: str) -> None:
    """The structured finally retains its loop on normal and halted exits."""
    from sugar_lift_py_tests.floor.ground_exit import ground_raise_effect

    events = []
    suspended, site = _suspended_with_for_cleanup(events)
    if outgoing == "close":
        result = suspended.close()
    else:
        effect = ground_raise_effect(
            exception_name="ValueError",
            site=site,
            owner="ForStepV1-finally-throw-test",
        )
        result = suspended.throw(effect)
        assert any(
            isinstance(exit_, Halted) and exit_.effect is effect
            for exit_ in result.exits
        )

    assert isinstance(result, ExitSet)
    assert events == [
        "iter_with",
        "next_with",
        ("body", (TermValue(1), TermValue(2))),
        "next_with",
        ("body", (TermValue(3), TermValue(4))),
        "next_with",
    ]


@pytest.mark.parametrize(
    ("body", "tail_type"),
    [
        ("setup()", "YieldStepV1"),
        ("return 7", "ReturnStepV1"),
        ("raise ValueError('body')", "RaiseStepV1"),
    ],
    ids=["completed", "returned", "halted"],
)
def test_for_cleanup_is_composed_before_each_source_outgoing_face(
    body: str,
    tail_type: str,
) -> None:
    """Completed, Returned, and Halted faces retain the same cleanup owner."""
    source = (
        "def manager(items):\n"
        "    try:\n"
        f"        {body}\n"
        "    finally:\n"
        "        for left, right in items:\n"
        "            apply_pair(left, right)\n"
        "    yield None\n"
    )
    steps = _steps(source)
    finally_index = next(
        index
        for index, step in enumerate(steps)
        if isinstance(step, generator_api.FinallyStepV1)
    )
    cleanup = steps[finally_index]

    assert len(cleanup.cleanup_steps) == 1
    assert isinstance(cleanup.cleanup_steps[0], _for_step_type())
    assert type(steps[finally_index + 1]).__name__ == tail_type


@pytest.mark.parametrize("outgoing", ["close", "throw"])
def test_cleanup_body_halt_supersedes_the_incoming_outgoing_face(
    outgoing: str,
) -> None:
    """Cleanup halt wins over both completed-close and incoming-halt faces."""
    from dataclasses import replace

    from sugar_lift_py_tests.floor.ground_exit import ground_raise_effect

    events = []
    suspended, site = _suspended_with_for_cleanup(events)
    cleanup = suspended.steps[suspended.cursor]
    loop = cleanup.cleanup_steps[0]
    cleanup_effect = ground_raise_effect(
        exception_name="RuntimeError",
        site=site,
        owner="ForStepV1-cleanup-halt-test",
    )
    halted_body = _HaltBody(cleanup_effect, events, site)
    loop = replace(
        loop,
        body_steps=(_term_step_type()(halted_body, loop.body_steps[0].fragment_cid),),
    )
    cleanup = replace(cleanup, cleanup_steps=(loop,))
    suspended = replace(
        suspended,
        steps=(
            *suspended.steps[: suspended.cursor],
            cleanup,
            *suspended.steps[suspended.cursor + 1 :],
        ),
    )

    if outgoing == "close":
        outcome = suspended.close()
    else:
        incoming = ground_raise_effect(
            exception_name="ValueError",
            site=site,
            owner="ForStepV1-cleanup-incoming-test",
        )
        outcome = suspended.throw(incoming)

    assert isinstance(outcome, ExitSet)
    halted = [exit_ for exit_ in outcome.exits if isinstance(exit_, Halted)]
    assert len(halted) == 1
    assert halted[0].effect is cleanup_effect
    assert events[-1] == "body_halt"

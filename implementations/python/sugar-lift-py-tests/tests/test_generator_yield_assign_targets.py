"""Every yield assignment is one named step: ``YieldAssignStepV1`` (#7757).

``y = yield v`` was the only form the step producer named (#7962).  The rest
were ``OpaqueStepV1``.  Now the resume binds the resumed value to each target
the way an ordinary assignment of that target binds its one evaluation, keyed
as substitution keyed the target's later reads (#7941, #7958):

* ``y: T = yield v`` binds ``y``;
* ``a = b = yield v`` binds the value to each Name;
* ``a, b = yield v`` / ``a, *b = yield v`` / ``(a, (b, c)) = yield v``
  unpack the value through the sequence-projection operation an ordinary
  unpack submits, each member under its Name's projection of the statement's
  evaluation;
* ``o.x = yield v`` / ``d[k] = yield v`` store the value through the store the
  statement's own sugar is, reading it through the statement's evaluation key
  (``KeyedStoreSugar`` for a keyed place);
* ``x = yield from xs`` delegates through the yield-from step, which completes
  with the delegate's return value (``StopIteration.value``): None for a
  list's or tuple's iterator, ``r`` for a source generator that returns ``r``.

Residue of #7991 (#7757):

* ``xs[i] = yield v`` on a decided local list/dict/set (substitution's
  ``ContainerMutationStatement``) runs the statement's mutation with the sent
  value; the pair it binds under the statement's key is what a later read of
  ``xs`` reads;
* ``a = o.x = yield v`` / ``a, o.x = yield v`` are the statement's own sugar
  with the value read through the step's key, each Name read out of what it
  bound; ``(a, (b, *c)) = yield v`` unpacks through the one nested unpack, the
  starred level through the sequence projection;
* ``throw`` / ``close`` of a frame delegating to a source generator reach the
  delegate, so its except arms and its ``finally`` run;
* ``o.x: T = yield v`` on an object place threads a read of the store's key,
  never the yield node, to the later read of ``o.x``.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.list_value import ListValue
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.floor.tuple_value import TupleValue
from sugar_lift_py_tests.generator_construction import (
    AssignStepV1,
    GeneratorAssignBindingV1,
    GeneratorConstructionV1,
    GeneratorTerminationV1,
    OpaqueStepV1,
    YieldAssignStepV1,
    YieldAssignUnpackV1,
    YieldEffect,
    YieldFromStepV1,
)
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.outcome.exit_set import Halted
from sugar_lift_py_tests.sugar.assign_sugar import (
    ChainedAssignSugar,
    DynamicUnpackStoreAssignSugar,
    KeyedStoreSugar,
)
from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
    BuiltinContainerCallSugar,
    ContainerMutationStatementSugar,
)
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.place_assign_sugar import PlaceAssignSugar
from sugar_lift_py_tests.sugar.store_effect_sugar import (
    AttributeStoreEffectSugar,
    SubscriptStoreEffectSugar,
)
from sugar_lift_py_tests.temporal.temporal_context import (
    EVALUATION_PREFIX,
    projection_key,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import AnnAssign, Call, FunctionDef, Return
from sugar_source_tree.tree import SourceFile


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "yield_assign_targets.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _steps(source: str):
    return _function(source)._source_visible_generator_steps({})


def _machine(name: str, steps) -> GeneratorConstructionV1:
    return GeneratorConstructionV1.allocate(
        allocation_coordinate=f"call:{name}:1",
        frame_coordinate=f"frame:{name}",
        binding_state=(),
        steps=steps,
    )


def _send_after_first_yield(name: str, source: str, sent):
    steps = _steps(source)
    assert isinstance(steps[0], YieldAssignStepV1)
    assert not any(isinstance(step, OpaqueStepV1) for step in steps)
    yielded = _machine(name, steps).resume()
    assert isinstance(yielded, YieldEffect)
    assert yielded.value == TermValue(5)
    return steps[0], yielded.machine.send(sent)


def _assigned(terminated) -> list:
    return [
        (item.name, item.value, item.evaluation)
        for item in terminated.binding_state
        if isinstance(item, GeneratorAssignBindingV1)
    ]


# ---------------------------------------------------------------------------
# ``y: T = yield v``
# ---------------------------------------------------------------------------


def test_an_annotated_yield_assignment_binds_the_sent_value() -> None:
    step, terminated = _send_after_first_yield(
        "annotated", "def g():\n    y: int = yield 5\n    return y\n", TermValue(7)
    )
    ((name, evaluation),) = step.targets
    assert name == "y"
    assert isinstance(evaluation, str) and evaluation.startswith(EVALUATION_PREFIX)
    assert step.unpack is None
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == TermValue(7)
    assert _assigned(terminated) == [("y", TermValue(7), evaluation)]


# ---------------------------------------------------------------------------
# ``a = b = yield v``
# ---------------------------------------------------------------------------


def test_a_chained_yield_assignment_binds_every_name_under_its_own_key() -> None:
    step, terminated = _send_after_first_yield(
        "chained", "def g():\n    a = b = yield 5\n    return (a, b)\n", TermValue(7)
    )
    assert [name for name, _evaluation in step.targets] == ["a", "b"]
    keys = [evaluation for _name, evaluation in step.targets]
    assert all(isinstance(key, str) for key in keys)
    assert keys[0] != keys[1]
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == TupleValue((TermValue(7), TermValue(7)))
    assert _assigned(terminated) == [
        ("a", TermValue(7), keys[0]),
        ("b", TermValue(7), keys[1]),
    ]


# ---------------------------------------------------------------------------
# ``a, b = yield v`` / ``a, *b = yield v``
# ---------------------------------------------------------------------------


def test_an_unpacking_yield_assignment_binds_each_member_under_its_projection() -> None:
    sent = TupleValue((TermValue(1), TermValue(2)))
    step, terminated = _send_after_first_yield(
        "unpack", "def g():\n    a, b = yield 5\n    return (b, a)\n", sent
    )
    assert step.unpack == YieldAssignUnpackV1(("a", "b"))
    assert [name for name, _evaluation in step.targets] == ["a", "b"]
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == TupleValue((TermValue(2), TermValue(1)))
    assigned = _assigned(terminated)
    assert [(name, value) for name, value, _key in assigned] == [
        ("a", TermValue(1)),
        ("b", TermValue(2)),
    ]
    # Each member is keyed as an ordinary unpack keys it: the Name's
    # projection of the statement's one evaluation.
    for (name, _value, key), (target, expected) in zip(
        assigned, step.targets, strict=True
    ):
        assert name == target
        assert key == expected
        assert key is not None and key.endswith(f"/{name}")


def test_a_starred_yield_assignment_binds_the_middle_as_a_list() -> None:
    sent = TupleValue((TermValue(1), TermValue(2), TermValue(3)))
    step, terminated = _send_after_first_yield(
        "starred", "def g():\n    a, *b = yield 5\n    return b\n", sent
    )
    assert step.unpack == YieldAssignUnpackV1(("a",), "b", ())
    assert isinstance(terminated, GeneratorTerminationV1)
    assert isinstance(terminated.return_value, ListValue)
    assert terminated.return_value.elements == (TermValue(2), TermValue(3))


def test_an_unpack_key_is_the_names_projection_of_the_evaluation() -> None:
    step = _steps("def g():\n    a, b = yield 5\n    return a\n")[0]
    assert isinstance(step, YieldAssignStepV1)
    ((_a, a_key), (_b, b_key)) = step.targets
    assert a_key.startswith(EVALUATION_PREFIX)
    evaluation = a_key[: -len("/a")]
    assert a_key == projection_key(evaluation, "a")
    assert b_key == projection_key(evaluation, "b")


# ---------------------------------------------------------------------------
# ``x = yield from xs``
# ---------------------------------------------------------------------------


def test_a_yield_from_a_tuple_binds_its_return_value_none() -> None:
    steps = _steps("def g():\n    x = yield from (1, 2)\n    return x\n")
    step = steps[0]
    assert isinstance(step, YieldAssignStepV1)
    assert isinstance(step.yield_step, YieldFromStepV1)
    assert not any(isinstance(item, OpaqueStepV1) for item in steps)

    first = _machine("yield_from_assign", steps).resume()
    assert isinstance(first, YieldEffect)
    assert first.value == TermValue(1)
    second = first.machine.resume()
    assert isinstance(second, YieldEffect)
    assert second.value == TermValue(2)
    # The tuple's iterator is exhausted: the delegation completes with its
    # StopIteration.value, None, and the resume binds ``x`` to it.
    terminated = second.machine.resume()
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == NoneValue()
    ((_name, key),) = step.targets
    assert _assigned(terminated) == [("x", NoneValue(), key)]


def test_a_yield_from_a_list_binds_its_return_value_none() -> None:
    steps = _steps("def g():\n    x = yield from [3]\n    return x\n")
    first = _machine("yield_from_list", steps).resume()
    assert isinstance(first, YieldEffect)
    assert first.value == TermValue(3)
    terminated = first.machine.resume()
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == NoneValue()


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _outer_generator(source: str) -> GeneratorConstructionV1:
    """The generator ``outer()`` (the last call in ``source``) allocates, with
    every call in ``source`` seated on its source-visible frame."""
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, "yield_from_delegate.py", blake3_512_of(source.encode())),
        construction_context=context,
    )
    functions = {
        node.name: node for node in tree.nodes() if isinstance(node, FunctionDef)
    }
    calls = [node for node in tree.nodes() if isinstance(node, Call)]
    for call in calls:
        context.source_call_frames[_coordinate(call)] = functions[
            call.func.id
        ].source_visible_call_frame()
    outer = next(call for call in calls if call.func.id == "outer")
    machine = outer.sugar().desugar().completed_value()
    assert isinstance(machine, GeneratorConstructionV1)
    return machine


def test_a_yield_from_a_source_generator_binds_what_it_returns() -> None:
    machine = _outer_generator(
        "def inner():\n"
        "    yield 1\n"
        "    return 5\n\n"
        "def outer():\n"
        "    x = yield from inner()\n"
        "    return x\n\n"
        "outer()\n"
    )
    yielded = machine.resume()
    assert isinstance(yielded, YieldEffect)
    assert yielded.value == TermValue(1)
    # The delegate returns 5: StopIteration.value is 5, and ``x`` is 5.
    terminated = yielded.machine.resume()
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == TermValue(5)


def test_a_send_into_a_delegating_frame_reaches_the_delegate() -> None:
    machine = _outer_generator(
        "def inner():\n"
        "    y = yield 1\n"
        "    return (y, 0)\n\n"
        "def outer():\n"
        "    x = yield from inner()\n"
        "    return x\n\n"
        "outer()\n"
    )
    yielded = machine.resume()
    assert isinstance(yielded, YieldEffect)
    assert yielded.value == TermValue(1)
    # The sent 7 is the delegate's ``y``; the delegation's value is what the
    # delegate returns, ``(7, 0)``, never the sent value itself.
    terminated = yielded.machine.send(TermValue(7))
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == TupleValue((TermValue(7), TermValue(0)))


# ---------------------------------------------------------------------------
# ``(a, (b, c)) = yield v``
# ---------------------------------------------------------------------------


def test_a_nested_unpacking_yield_assignment_binds_every_leaf() -> None:
    sent = TupleValue((TermValue(1), TupleValue((TermValue(2), TermValue(3)))))
    step, terminated = _send_after_first_yield(
        "nested", "def g():\n    (a, (b, c)) = yield 5\n    return (c, b, a)\n", sent
    )
    assert step.unpack == YieldAssignUnpackV1(
        ("a", "b", "c"), pattern=("a", ("b", "c"))
    )
    assert [name for name, _evaluation in step.targets] == ["a", "b", "c"]
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == TupleValue(
        (TermValue(3), TermValue(2), TermValue(1))
    )
    assigned = _assigned(terminated)
    assert [(name, value) for name, value, _key in assigned] == [
        ("a", TermValue(1)),
        ("b", TermValue(2)),
        ("c", TermValue(3)),
    ]
    for (name, _value, key), (target, expected) in zip(
        assigned, step.targets, strict=True
    ):
        assert name == target
        assert key == expected


def test_a_nested_unpack_of_the_wrong_arity_halts_at_the_resume() -> None:
    _step, halted = _send_after_first_yield(
        "nested_arity",
        "def g():\n    (a, (b, c)) = yield 5\n    return a\n",
        TupleValue((TermValue(1),)),
    )
    assert isinstance(halted, ExitSet)
    assert halted.exits and halted.halts() == halted.exits


# ---------------------------------------------------------------------------
# ``o.x = yield v`` / ``d[k] = yield v``
# ---------------------------------------------------------------------------


def test_an_attribute_store_of_a_yield_is_a_named_store_step() -> None:
    steps = _steps("def g(o):\n    o.x = yield 5\n    return 9\n")
    step = steps[0]
    assert isinstance(step, YieldAssignStepV1)
    assert step.targets == ()
    assert isinstance(step.store, (AttributeStoreEffectSugar, KeyedStoreSugar))
    assert step.store_evaluation.startswith(EVALUATION_PREFIX)
    assert not any(isinstance(item, OpaqueStepV1) for item in steps)


def test_a_subscript_store_of_a_yield_is_a_named_store_step() -> None:
    steps = _steps("def g(d, k):\n    d[k] = yield 5\n    return 9\n")
    step = steps[0]
    assert isinstance(step, YieldAssignStepV1)
    assert step.targets == ()
    assert isinstance(step.store, SubscriptStoreEffectSugar)
    assert step.store_evaluation.startswith(EVALUATION_PREFIX)
    assert not any(isinstance(item, OpaqueStepV1) for item in steps)


def test_a_local_receiver_field_store_of_a_yield_is_the_keyed_store() -> None:
    steps = _steps("def g():\n    t = (1, 2)\n    t.x = yield 5\n    return 9\n")
    step = steps[1]
    assert isinstance(step, YieldAssignStepV1)
    # The statement's own store: its value read through the statement's key.
    assert isinstance(step.store, KeyedStoreSugar)
    assert step.store.evaluation == step.store_evaluation


def test_a_store_of_the_sent_value_runs_the_store_at_the_resume() -> None:
    steps = _steps("def g():\n    t = (1, 2)\n    t[0] = yield 5\n    return 9\n")
    assert isinstance(steps[0], AssignStepV1)
    assert isinstance(steps[1], YieldAssignStepV1)
    yielded = _machine("tuple_store", steps).resume()
    assert isinstance(yielded, YieldEffect)
    assert yielded.value == TermValue(5)
    # ``t[0] = 7`` on a tuple raises TypeError: the store ran at the resume,
    # and its halt leaves the frame there.
    halted = yielded.machine.send(TermValue(7))
    assert isinstance(halted, ExitSet)
    assert halted.exits and halted.halts() == halted.exits


def _returned_values(result) -> list:
    """What the frame returned: a termination's value, or every completed
    face's (a store with two faces continues under each)."""
    if isinstance(result, GeneratorTerminationV1):
        return [result.return_value]
    assert isinstance(result, ExitSet), type(result).__name__
    return [
        face.value.return_value
        for face in result.exits
        if not isinstance(face, Halted)
        and isinstance(face.value, GeneratorTerminationV1)
    ]


# ---------------------------------------------------------------------------
# ``xs[i] = yield v`` on a decided local list (``ContainerMutationStatement``)
# ---------------------------------------------------------------------------


def test_a_store_on_a_local_list_is_the_statements_mutation() -> None:
    steps = _steps("def g():\n    xs = [0, 0]\n    xs[1] = yield 5\n    return xs\n")
    assert not any(isinstance(item, OpaqueStepV1) for item in steps)
    step = steps[1]
    assert isinstance(step, YieldAssignStepV1)
    assert step.targets == ()
    # The statement's mutation, its stored value read through the yield's
    # projection of the statement's key; the pair it binds under the key is
    # kept for the later read of ``xs``.
    assert isinstance(step.store, ContainerMutationStatementSugar)
    (evaluation,) = step.store_keeps
    assert step.store.evaluation == evaluation
    assert step.store_evaluation == projection_key(evaluation, "yield")
    call = step.store.evaluated[0]
    assert isinstance(call, BuiltinContainerCallSugar)
    stored = call.args[-1]
    assert isinstance(stored, EvaluationRefSugar)
    assert stored.place and stored.evaluation == step.store_evaluation


def test_a_store_on_a_local_list_stores_the_sent_value() -> None:
    steps = _steps("def g():\n    xs = [0, 0]\n    xs[1] = yield 5\n    return xs\n")
    yielded = _machine("list_store", steps).resume()
    assert isinstance(yielded, YieldEffect)
    assert yielded.value == TermValue(5)
    # The read of ``xs`` after the store reads the pair the mutation bound.
    terminated = yielded.machine.send(TermValue(7))
    assert isinstance(terminated, GeneratorTerminationV1)
    assert isinstance(terminated.return_value, ListValue)
    assert terminated.return_value.elements == (TermValue(0), TermValue(7))


def test_a_store_out_of_a_local_lists_range_halts_at_the_resume() -> None:
    steps = _steps("def g():\n    xs = [0]\n    xs[3] = yield 5\n    return xs\n")
    yielded = _machine("list_store_range", steps).resume()
    assert isinstance(yielded, YieldEffect)
    halted = yielded.machine.send(TermValue(7))
    assert isinstance(halted, ExitSet)
    assert halted.exits and halted.halts() == halted.exits


# ---------------------------------------------------------------------------
# ``a = o.x = yield v`` / ``a, o.x = yield v``
# ---------------------------------------------------------------------------


def test_a_chain_with_a_store_is_the_statements_chained_sugar() -> None:
    steps = _steps(
        "def g():\n    d = {}\n    a = d['k'] = yield 5\n    return a\n"
    )
    assert not any(isinstance(item, OpaqueStepV1) for item in steps)
    step = steps[1]
    assert isinstance(step, YieldAssignStepV1)
    assert isinstance(step.store, ChainedAssignSugar)
    assert isinstance(step.store.value, EvaluationRefSugar)
    assert step.store.value.evaluation == step.store_evaluation
    ((name, key),) = step.targets
    assert name == "a"
    assert key == projection_key(step.store_evaluation, "a")


def test_a_chain_with_a_store_binds_the_name_and_runs_the_store() -> None:
    steps = _steps(
        "def g():\n    d = {}\n    a = d['k'] = yield 5\n    return a\n"
    )
    yielded = _machine("chain_store", steps).resume()
    assert isinstance(yielded, YieldEffect)
    # ``a`` is read out of what the chain bound under its key.
    assert TermValue(7) in _returned_values(yielded.machine.send(TermValue(7)))


def test_a_chain_whose_store_raises_halts_at_the_resume() -> None:
    steps = _steps(
        "def g():\n    t = (1, 2)\n    a = t[0] = yield 5\n    return a\n"
    )
    assert isinstance(steps[1], YieldAssignStepV1)
    yielded = _machine("chain_tuple_store", steps).resume()
    halted = yielded.machine.send(TermValue(7))
    assert isinstance(halted, ExitSet)
    assert halted.exits and halted.halts() == halted.exits


def test_a_mixed_unpack_is_the_statements_unpack_store_sugar() -> None:
    steps = _steps(
        "def g():\n    d = {}\n    a, d['k'] = yield 5\n    return a\n"
    )
    assert not any(isinstance(item, OpaqueStepV1) for item in steps)
    step = steps[1]
    assert isinstance(step, YieldAssignStepV1)
    assert isinstance(step.store, DynamicUnpackStoreAssignSugar)
    ((name, key),) = step.targets
    assert name == "a"
    assert key == projection_key(step.store_evaluation, "a")
    yielded = _machine("mixed_unpack", steps).resume()
    assert isinstance(yielded, YieldEffect)
    sent = TupleValue((TermValue(1), TermValue(2)))
    assert TermValue(1) in _returned_values(yielded.machine.send(sent))


def test_a_nested_unpack_with_a_store_leaf_is_the_statements_unpack() -> None:
    """``a, (b, d['k']) = yield v``: the nested level unpacks its member
    through the same positional unpack and stores its leaf, before the
    frame returns the Name the level bound."""
    from sugar_lift_py_tests.sugar.unpack_projection_targets import (
        NestedUnpackTarget,
    )

    steps = _steps(
        "def g():\n    d = {}\n    a, (b, d['k']) = yield 5\n    return b\n"
    )
    assert not any(isinstance(item, OpaqueStepV1) for item in steps)
    step = steps[1]
    assert isinstance(step, YieldAssignStepV1)
    assert isinstance(step.store, DynamicUnpackStoreAssignSugar)
    assert isinstance(step.store.targets[1], NestedUnpackTarget)
    assert [name for name, _key in step.targets] == ["a", "b"]
    assert all(
        key == projection_key(step.store_evaluation, name)
        for name, key in step.targets
    )
    yielded = _machine("nested_store_unpack", steps).resume()
    assert isinstance(yielded, YieldEffect)
    sent = TupleValue((TermValue(1), TupleValue((TermValue(2), TermValue(3)))))
    assert TermValue(2) in _returned_values(yielded.machine.send(sent))


def test_a_nested_store_level_of_the_wrong_arity_halts_at_the_resume() -> None:
    steps = _steps(
        "def g():\n    d = {}\n    a, (b, d['k']) = yield 5\n    return b\n"
    )
    yielded = _machine("nested_store_arity", steps).resume()
    halted = yielded.machine.send(
        TupleValue((TermValue(1), TupleValue((TermValue(2),))))
    )
    assert isinstance(halted, ExitSet)
    assert halted.exits and halted.halts() == halted.exits


# ---------------------------------------------------------------------------
# ``(a, (b, *c)) = yield v`` / ``(a, *b, (c, d)) = yield v``
# ---------------------------------------------------------------------------


def test_a_nested_unpack_with_an_inner_star_binds_the_rest_as_a_list() -> None:
    sent = TupleValue(
        (TermValue(1), TupleValue((TermValue(2), TermValue(3), TermValue(4))))
    )
    step, terminated = _send_after_first_yield(
        "nested_star", "def g():\n    (a, (b, *c)) = yield 5\n    return c\n", sent
    )
    assert step.unpack == YieldAssignUnpackV1(
        ("a", "b", "c"), pattern=("a", ("b", "*c"))
    )
    assert isinstance(terminated, GeneratorTerminationV1)
    assert isinstance(terminated.return_value, ListValue)
    assert terminated.return_value.elements == (TermValue(3), TermValue(4))
    assert [(name, value) for name, value, _key in _assigned(terminated)][:2] == [
        ("a", TermValue(1)),
        ("b", TermValue(2)),
    ]


def test_a_star_beside_a_nested_unpack_takes_the_middle() -> None:
    sent = TupleValue(
        (
            TermValue(1),
            TermValue(2),
            TermValue(3),
            TupleValue((TermValue(4), TermValue(5))),
        )
    )
    step, terminated = _send_after_first_yield(
        "outer_star",
        "def g():\n    (a, *b, (c, d)) = yield 5\n    return d\n",
        sent,
    )
    assert step.unpack.pattern == ("a", "*b", ("c", "d"))
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == TermValue(5)
    assigned = {name: value for name, value, _key in _assigned(terminated)}
    assert assigned["a"] == TermValue(1)
    assert isinstance(assigned["b"], ListValue)
    assert assigned["b"].elements == (TermValue(2), TermValue(3))
    assert assigned["c"] == TermValue(4)


def test_a_starred_nested_unpack_too_short_halts_at_the_resume() -> None:
    _step, halted = _send_after_first_yield(
        "nested_star_short",
        "def g():\n    (a, (b, c, *d)) = yield 5\n    return a\n",
        TupleValue((TermValue(1), TupleValue((TermValue(2),)))),
    )
    assert isinstance(halted, ExitSet)
    assert halted.exits and halted.halts() == halted.exits


# ---------------------------------------------------------------------------
# ``throw`` / ``close`` of a frame delegating to a source generator
# ---------------------------------------------------------------------------


def _raised(name: str):
    return RaiseEffect.for_builtin(
        name, occurrence=f"test-throw:{name}", blame=f"test-throw:{name}"
    )


def test_a_throw_reaches_the_delegates_except_arm() -> None:
    machine = _outer_generator(
        "def inner():\n"
        "    try:\n"
        "        yield 1\n"
        "    except ValueError:\n"
        "        return 9\n\n"
        "def outer():\n"
        "    x = yield from inner()\n"
        "    return x\n\n"
        "outer()\n"
    )
    yielded = machine.resume()
    assert isinstance(yielded, YieldEffect)
    assert yielded.value == TermValue(1)
    # The delegate's arm catches the thrown ValueError and returns 9: the
    # delegation completes with 9, and ``x`` is 9.
    thrown = yielded.machine.throw(_raised("ValueError"))
    assert isinstance(thrown, ExitSet)
    assert TermValue(9) in _returned_values(thrown)


def test_a_throw_runs_the_delegates_finally_and_its_halt_passes_through() -> None:
    machine = _outer_generator(
        "def inner():\n"
        "    try:\n"
        "        yield 1\n"
        "    finally:\n"
        "        raise ValueError\n\n"
        "def outer():\n"
        "    yield from inner()\n\n"
        "outer()\n"
    )
    yielded = machine.resume()
    assert isinstance(yielded, YieldEffect)
    thrown_in = _raised("KeyError")
    thrown = yielded.machine.throw(thrown_in)
    assert isinstance(thrown, ExitSet)
    assert thrown.exits and thrown.halts() == thrown.exits
    # The delegate's finally raised: that is the halt, not the thrown KeyError.
    assert all(face.effect != thrown_in for face in thrown.halts())


def test_a_close_runs_the_delegates_finally() -> None:
    machine = _outer_generator(
        "def inner():\n"
        "    try:\n"
        "        yield 1\n"
        "    finally:\n"
        "        raise ValueError\n\n"
        "def outer():\n"
        "    yield from inner()\n\n"
        "outer()\n"
    )
    yielded = machine.resume()
    assert isinstance(yielded, YieldEffect)
    # Closing the frame closes the delegate first: its finally raises, and
    # that halt passes through the frame (it never just terminates).
    closed = yielded.machine.close()
    assert isinstance(closed, ExitSet)
    assert closed.exits and closed.halts() == closed.exits


# ---------------------------------------------------------------------------
# ``o.x: T = yield v`` on an object place
# ---------------------------------------------------------------------------

PLACE_YIELD = (
    "class Box:\n"
    "    pass\n"
    "\n"
    "def g():\n"
    "    box = Box()\n"
    "    box.size: int = yield 5\n"
    "    return box.size\n"
)


def test_an_object_place_field_after_a_yield_store_reads_the_stores_key() -> None:
    # Substitution never reduces the yield to version the field.
    body = _function(PLACE_YIELD).substitute({}).body
    store = next(node for node in body if isinstance(node, AnnAssign))
    assert isinstance(store.evaluation, str)
    ret = body[-1]
    assert isinstance(ret, Return)
    # The later read of ``box.size`` is a reference to the store's key,
    # which the resume binds the sent value under.
    assert ret.value.kind == "EvaluationRef"
    assert ret.value.place is True
    assert ret.value.evaluation == store.evaluation
    # The object it denotes is the store's own read of its key, never the
    # yield node.
    denoted = getattr(ret.value, "of", None)
    assert denoted is None or denoted.kind != "Yield"


def test_an_object_place_yield_store_is_the_keyed_place_store() -> None:
    steps = _steps(PLACE_YIELD)
    assert not any(isinstance(item, OpaqueStepV1) for item in steps)
    step = steps[1]
    assert isinstance(step, YieldAssignStepV1)
    assert isinstance(step.store, KeyedStoreSugar)
    assert isinstance(step.store.store, PlaceAssignSugar)
    assert step.store.evaluation == step.store_evaluation

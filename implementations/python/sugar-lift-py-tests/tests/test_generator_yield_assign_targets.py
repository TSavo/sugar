"""Every yield assignment is one named step: ``YieldAssignStepV1`` (#7757).

``y = yield v`` was the only form the step producer named (#7962).  The rest
were ``OpaqueStepV1``.  Now the resume binds the resumed value to each target
the way an ordinary assignment of that target binds its one evaluation, keyed
as substitution keyed the target's later reads (#7941, #7958):

* ``y: T = yield v`` binds ``y``;
* ``a = b = yield v`` binds the value to each Name;
* ``a, b = yield v`` / ``a, *b = yield v`` unpack the value through the
  sequence-projection operation an ordinary unpack submits, each member under
  its Name's projection of the statement's evaluation;
* ``x = yield from xs`` delegates through the yield-from step; the value to
  bind is the sub-iterator's return value (``StopIteration.value``), which the
  yield-from step does not carry, so the bind is refused by name.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.list_value import ListValue
from sugar_lift_py_tests.floor.tuple_value import TupleValue
from sugar_lift_py_tests.generator_construction import (
    GeneratorAssignBindingV1,
    GeneratorConstructionV1,
    GeneratorTerminationV1,
    GeneratorTransitionGapV1,
    OpaqueStepV1,
    YieldAssignStepV1,
    YieldAssignUnpackV1,
    YieldEffect,
    YieldFromStepV1,
    YieldStepV1,
)
from sugar_lift_py_tests.temporal.temporal_context import (
    EVALUATION_PREFIX,
    projection_key,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
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


def test_a_yield_from_assignment_refuses_the_return_value_by_name() -> None:
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
    refused = second.machine.resume()
    assert isinstance(refused, GeneratorTransitionGapV1)
    assert refused.owner == "GeneratorConstructionV1.transition"
    assert "StopIteration.value" in refused.observed
    assert refused.observed.startswith("x = yield from")


def test_a_yield_assignment_never_names_a_store_target() -> None:
    steps = _steps("def g(o):\n    o.x = yield 5\n    return o\n")
    assert isinstance(steps[0], OpaqueStepV1)
    assert steps[0].carries_suspension is True
    assert not any(isinstance(step, (YieldAssignStepV1, YieldStepV1)) for step in steps)

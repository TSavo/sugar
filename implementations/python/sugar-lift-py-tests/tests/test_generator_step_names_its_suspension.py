"""An opaque generator step says whether it holds a suspension.

``OpaqueStepV1(statement.kind)`` gave ``x = 1`` and ``x = yield 1`` the SAME
row -- ``Assign`` -- and they are not the same obligation:

* an opaque statement owning NO suspension owes ordinary statement execution
  inside a generator frame;
* one that OWNS a suspension owes a generator-protocol law -- the resumed
  value's binding for an assignment, a partition for a branch.

That is the misnamed-bucket shape twice over. ``add x TermValue`` said "a
number does not stand on the addition floor" for 34 rows that were all complex
literals, and the binary-operation gaps said nothing about their right operand
until the pair became the dispatch unit. A gap that cannot name what it could
not consume cannot be dispatched, and this one names the CONTAINER's kind
rather than the construct inside it.

WHAT THIS IS NOT. It does not name a single new step. Nothing here executes a
suspension that did not execute before, and every previously-opaque shape is
still opaque and still refuses by name. The vocabulary is unchanged; only its
testimony about itself is sharper.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.generator_construction import (
    GeneratorConstructionV1,
    GeneratorTransitionGapV1,
    OpaqueStepV1,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _steps(tmp_path, source: str):
    path = tmp_path / "m.py"
    path.write_text(source, encoding="utf-8")
    functions = list(SourceFile(path_source(str(path))).functions())
    return functions[0]._source_visible_generator_steps({})


def _first_opaque(steps):
    return next(step for step in steps if isinstance(step, OpaqueStepV1))


# -- the discrimination ------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "kind", "carries"),
    (
        # Same statement kind, opposite obligations.
        ("def g():\n    x = yield 1\n    return x\n", "Assign", True),
        ("def g():\n    x = 1\n    yield 2\n", "Assign", False),
        ("def g(c):\n    if c:\n        yield 1\n", "If", True),
        ("def g(c):\n    if c:\n        pass\n    yield 2\n", "If", False),
        # Every bare `yield from` -- where the delegation debt actually lives.
        ("def g(xs):\n    yield from xs\n", "Expr", True),
    ),
)
def test_an_opaque_step_states_whether_it_holds_a_suspension(
    tmp_path, source, kind, carries
) -> None:
    step = _first_opaque(_steps(tmp_path, source))

    assert step.observed == kind
    assert step.carries_suspension is carries


@pytest.mark.parametrize(
    ("source", "observed"),
    (
        ("def g():\n    x = yield 1\n    return x\n", "Assign carrying a suspension"),
        ("def g(c):\n    if c:\n        yield 1\n", "If carrying a suspension"),
        ("def g(xs):\n    yield from xs\n", "Expr carrying a suspension"),
    ),
)
def test_the_transition_gap_names_the_construct_it_could_not_consume(
    tmp_path, source, observed
) -> None:
    """The row has to be dispatchable. `Assign` names the container; a board
    keyed on it cannot tell generator-protocol work from an ordinary
    unsupported statement."""
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="probe",
        frame_coordinate="frame",
        binding_state=(),
        steps=_steps(tmp_path, source),
    )

    gap = machine.resume()

    assert isinstance(gap, GeneratorTransitionGapV1)
    assert gap.observed == observed
    assert gap.owner == "GeneratorConstructionV1.transition"


def test_an_opaque_step_without_a_suspension_is_named_unchanged(tmp_path) -> None:
    """The discriminating face: the flag must not decorate every opaque row.

    If it did, the distinction would be worthless -- every statement would
    claim to hold a suspension and the board would be exactly as
    undifferentiated as before, one word longer.
    """
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="probe",
        frame_coordinate="frame",
        binding_state=(),
        steps=_steps(tmp_path, "def g():\n    x = 1\n    yield 2\n"),
    )

    gap = machine.resume()

    assert isinstance(gap, GeneratorTransitionGapV1)
    assert gap.observed == "Assign"


# -- nothing was named, nothing was drained ----------------------------------


@pytest.mark.parametrize(
    "source",
    (
        "def g():\n    x = yield 1\n    return x\n",
        "def g(c):\n    if c:\n        yield 1\n",
        "def g(xs):\n    yield from xs\n",
    ),
)
def test_every_previously_opaque_shape_is_still_opaque(tmp_path, source) -> None:
    """`panic = gap`. Sharper testimony must not become a drain: these still
    refuse, and nothing constructs a suspension the vocabulary cannot execute.
    """
    from sugar_lift_py_tests.generator_construction import YieldStepV1

    steps = _steps(tmp_path, source)

    assert any(isinstance(step, OpaqueStepV1) for step in steps)
    assert not any(isinstance(step, YieldStepV1) for step in steps)


def test_a_named_step_is_untouched_and_still_suspends(tmp_path) -> None:
    """The shapes the vocabulary DOES name keep working, unchanged."""
    from sugar_lift_py_tests.generator_construction import YieldEffect, YieldStepV1

    steps = _steps(tmp_path, "def g():\n    yield 1\n")

    assert isinstance(steps[0], YieldStepV1)

    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="probe",
        frame_coordinate="frame",
        binding_state=(),
        steps=steps,
    )

    assert isinstance(machine.resume(), YieldEffect)


def test_the_flag_defaults_to_the_honest_no() -> None:
    """A step constructed without the testimony claims nothing."""
    assert OpaqueStepV1("Whatever").carries_suspension is False
    assert OpaqueStepV1("Whatever").gap_observed() == "Whatever"

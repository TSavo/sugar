"""An opaque generator step says whether it holds a suspension.

``OpaqueStepV1(statement.kind)`` used to give ``x = 1`` and ``x = yield 1`` the
SAME row -- ``Assign`` -- and they are not the same obligation. Ordinary
Assign and nameable pre-yield If are now AssignStepV1 / IfStepV1; residual
opaque shapes still carry the suspension flag so the board can dispatch:

* an opaque statement owning NO suspension owes ordinary statement execution
  the vocabulary has not yet constructed (e.g. multi-target store);
* one that OWNS a suspension owes a generator-protocol law -- the resumed
  value's binding for an assignment, a partition for a branch that holds an
  unnameable yield form.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.generator_construction import (
    AssignStepV1,
    GeneratorConstructionV1,
    GeneratorTransitionGapV1,
    IfStepV1,
    OpaqueStepV1,
    YieldEffect,
    YieldStepV1,
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
        # Residual opaque shapes still discriminate suspension ownership.
        ("def g():\n    x = yield 1\n    return x\n", "Assign", True),
        ("def g(c):\n    if c:\n        x = yield 1\n", "If", True),
        # Multi-target assign stays opaque without suspension.
        ("def g():\n    a, b = 1, 2\n    yield 3\n", "Assign", False),
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


def test_ordinary_assign_and_nameable_if_are_no_longer_opaque(tmp_path) -> None:
    """Producer item-1: simple Assign and nameable If are named steps."""
    assign_steps = _steps(tmp_path, "def g():\n    x = 1\n    yield 2\n")
    assert isinstance(assign_steps[0], AssignStepV1)
    assert not any(isinstance(s, OpaqueStepV1) for s in assign_steps)

    if_steps = _steps(tmp_path, "def g(c):\n    if c:\n        pass\n    yield 2\n")
    assert isinstance(if_steps[0], IfStepV1)
    assert not isinstance(if_steps[0], OpaqueStepV1)


@pytest.mark.parametrize(
    ("source", "observed"),
    (
        ("def g():\n    x = yield 1\n    return x\n", "Assign carrying a suspension"),
        ("def g(c):\n    if c:\n        x = yield 1\n", "If carrying a suspension"),
        ("def g(xs):\n    yield from xs\n", "Expr carrying a suspension"),
    ),
)
def test_the_transition_gap_names_the_construct_it_could_not_consume(
    tmp_path, source, observed
) -> None:
    """The row has to be dispatchable. Residual opaques name suspension when owned."""
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
    """The discriminating face: residual opaque without suspension stays plain."""
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="probe",
        frame_coordinate="frame",
        binding_state=(),
        steps=_steps(tmp_path, "def g():\n    a, b = 1, 2\n    yield 3\n"),
    )

    gap = machine.resume()

    assert isinstance(gap, GeneratorTransitionGapV1)
    assert gap.observed == "Assign"


# -- residual opaques stay loud ----------------------------------------------


@pytest.mark.parametrize(
    "source",
    (
        "def g():\n    x = yield 1\n    return x\n",
        "def g(c):\n    if c:\n        x = yield 1\n",
        "def g(xs):\n    yield from xs\n",
    ),
)
def test_every_previously_opaque_shape_is_still_opaque(tmp_path, source) -> None:
    """Sharper admission of Assign/If must not drain residual opaque shapes."""
    steps = _steps(tmp_path, source)

    assert any(isinstance(step, OpaqueStepV1) for step in steps)
    assert not any(isinstance(step, YieldStepV1) for step in steps)


def test_a_named_step_is_untouched_and_still_suspends(tmp_path) -> None:
    """The shapes the vocabulary DOES name keep working, unchanged."""
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

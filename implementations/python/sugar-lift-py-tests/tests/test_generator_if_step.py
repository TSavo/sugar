"""A branch inside a generator body is a two-face partition the producer owns.

`if c: yield 1` landed on `OpaqueStepV1("If")` -- the step vocabulary kept the
container's kind and threw away the guard and both branches, so the machine had
nothing to transition with.

THE THREE ARMS. A DECIDED guard is not a partition: exactly one side runs, so
its steps splice into the sequence and nothing is minted -- minting a family
over a route the producer does not decide would assert an exhaustiveness that
is not true. An UNDECIDED guard is a genuine two-face split, and each face is a
distinct successor machine with its own cursor.

WHY THERE IS NO `faces` FIELD ON THE MACHINE. The partition lives in the
`ExitSet`; the machine that partitions does not advance, it is replaced by two
successors. That is the shape the machine already used -- `YieldEffect` carries
a successor machine, `ExitSet.halted(effect, state=self)` carries state.

THE KEY IS COMPOSITE, and this is the load-bearing part. A source-only key
makes two live generators over one source branch look like two sides of ONE
split, because `_faces_exclusive` never reads the arms' guards. Measured on the
algebra directly in `test_partition_key_execution_discriminator.py`: two
executions collapse into one arm and the second's value is re-attributed to the
negation of the first's guard. The instance coordinate discriminates them; the
fragment keeps two reads of ONE instance reproducible.

That shape is not novel -- the loop carrier already keys on the producer
OCCURRENCE (`targetCid`), pinned by
`test_two_occurrences_with_identical_faces_are_different_states`. This is the
same law at a second producer.

THE BOUND. Only when EVERY step in both branches is one the vocabulary can
already execute. `x = yield v` resumes to a value that reaches no name --
`ResumeBindingV1.resume_value` is written by `send()` and read by nothing -- so
a branch holding one keeps the whole `If` opaque and loud. Naming a step we
cannot resume is worse than an honest `OpaqueStepV1`.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from sugar_lift_py_tests.generator_construction import (
    GeneratorConstructionV1,
    GeneratorTerminationV1,
    IfStepV1,
    InertStepV1,
    OpaqueStepV1,
    ReturnStepV1,
    YieldEffect,
    YieldStepV1,
)
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _steps(source: str):
    directory = pathlib.Path(tempfile.mkdtemp())
    path = directory / "m.py"
    path.write_text(source, encoding="utf-8")
    function = next(iter(SourceFile(path_source(str(path))).functions()))
    return function._source_visible_generator_steps({})


def _machine(steps, allocation: str = "call-site"):
    return GeneratorConstructionV1.allocate(
        allocation_coordinate=allocation,
        frame_coordinate="frame",
        binding_state=(),
        steps=steps,
    )


def _completed(exits) -> list:
    return [e for e in exits.exits if isinstance(e, Completed)]


# -- the producer names the branch, and refuses what it cannot resume --------


@pytest.mark.parametrize(
    ("source", "first_step"),
    (
        # THE reproducer.
        ("def g(c):\n    if c:\n        yield 1\n", IfStepV1),
        (
            "def g(c):\n    if c:\n        yield 1\n    else:\n        yield 2\n",
            IfStepV1,
        ),
        # THE BOUND: a branch holding a shape we cannot resume stays opaque.
        ("def g(c):\n    if c:\n        x = yield 1\n", OpaqueStepV1),
    ),
)
def test_the_producer_admits_only_a_wholly_nameable_branch(source, first_step) -> None:
    assert isinstance(_steps(source)[0], first_step)


def test_a_branch_step_carries_both_sides_and_its_own_fragment(tmp_path) -> None:
    step = _steps(
        "def g(c):\n    if c:\n        yield 1\n    else:\n        yield 2\n"
    )[0]

    assert isinstance(step.then_steps[0], YieldStepV1)
    assert isinstance(step.else_steps[0], YieldStepV1)
    assert step.fragment_cid
    # The step is instance-agnostic: no partition is minted at producer time,
    # because the key needs an instance_coordinate that does not exist yet.
    assert not hasattr(step, "partition")


def test_an_if_without_a_suspension_is_pre_yield_guarded_setup() -> None:
    """Pre-yield guarded setup (pass / assign) is IfStep when wholly nameable.

    Real managers use ``if cond: x = …`` before yield. Pass-only and assign
    branches are nameable peers; unhandled kinds (raise, for, x=yield) keep
    the whole If opaque and loud.
    """
    steps = _steps("def g(c):\n    if c:\n        pass\n    yield 2\n")

    assert isinstance(steps[0], IfStepV1)
    assert isinstance(steps[0].then_steps[0], InertStepV1)
    assert steps[0].else_steps == ()
    assert isinstance(steps[1], YieldStepV1)


def test_pre_yield_if_assign_is_nameable_guarded_setup() -> None:
    steps = _steps(
        "def g(c):\n    if c:\n        prior = None\n    yield 1\n"
    )
    assert isinstance(steps[0], IfStepV1)
    from sugar_lift_py_tests.generator_construction import AssignStepV1

    assert isinstance(steps[0].then_steps[0], AssignStepV1)
    assert steps[0].then_steps[0].name == "prior"


def test_pre_yield_if_with_raise_stays_opaque_and_loud() -> None:
    """Unhandled Raise inside a branch keeps the whole If Opaque (never skip)."""
    steps = _steps(
        "def g(c):\n    if c:\n        raise ValueError('boom')\n    yield 1\n"
    )
    assert isinstance(steps[0], OpaqueStepV1)
    assert steps[0].observed == "If"
    assert steps[0].carries_suspension is False


# -- the three transition arms -----------------------------------------------


def test_a_ground_true_guard_splices_the_then_branch() -> None:
    step = IfStepV1(
        TrueBoolLiteralSugar(site="s"),
        (YieldStepV1(IntLiteralSugar(1, site="yield:1")),),
        (),
        "frag",
    )

    assert isinstance(_machine((step, ReturnStepV1())).resume(), YieldEffect)


def test_a_ground_false_guard_splices_the_else_branch() -> None:
    step = IfStepV1(
        FalseBoolLiteralSugar(site="s"),
        (YieldStepV1(IntLiteralSugar(1, site="yield:1")),),
        (),
        "frag",
    )

    assert isinstance(_machine((step, ReturnStepV1())).resume(), GeneratorTerminationV1)


def test_an_undecided_guard_partitions_into_two_faces() -> None:
    outcome = _machine(_steps("def g(c):\n    if c:\n        yield 1\n")).resume()

    assert isinstance(outcome, ExitSet)


# -- the arm count: factoring holds, so sequencing does not multiply ---------


@pytest.mark.parametrize("branch_suspensions", (1, 2, 3))
def test_a_branch_with_k_suspensions_stays_one_arm(branch_suspensions) -> None:
    """THE m ** k gate.

    `factor_completed` moves the partition from the exit level -- where
    `sequence` multiplies it -- to the value level, where it composes. If this
    ever reports the branch count instead of 1, sequencing has gone exponential
    and the defect surfaces as a corpus timeout days later, never in a twin.
    """
    branch = tuple(
        YieldStepV1(IntLiteralSugar(n, site=f"yield:{n}"))
        for n in range(branch_suspensions)
    )

    step = IfStepV1(NameSugar("c", site="s"), branch, (), "frag")
    outcome = _machine((step, ReturnStepV1())).resume()

    assert len(_completed(outcome)) == 1


def test_sequential_branches_stay_one_arm() -> None:
    """k branches in sequence would be 2 ** k unfactored."""
    steps = tuple(
        IfStepV1(
            NameSugar(f"c{n}", site=f"guard:{n}"),
            (YieldStepV1(IntLiteralSugar(n, site=f"yield:{n}")),),
            (),
            f"frag{n}",
        )
        for n in range(3)
    ) + (ReturnStepV1(),)

    assert len(_completed(_machine(steps).resume())) == 1


def test_the_factored_arm_carries_the_partition_as_a_value() -> None:
    """Where the partition went: a GuardedValue chain, not two exit arms."""
    outcome = _machine(_steps("def g(c):\n    if c:\n        yield 1\n")).resume()

    assert type(_completed(outcome)[0].value).__name__ == "GuardedValue"


# -- the two-live-instances twin: REQUIRED, and it caught a real defect ------


def test_two_live_instances_mint_different_partitions() -> None:
    """THE twin the composite key exists for.

    Two generators over ONE source branch are two executions. With a
    source-only key their arms carry the same origin on opposite sides, and
    `_faces_exclusive` -- which never reads guards -- declares them exclusive.
    Measured: they collapse and one execution's value is re-attributed to the
    negation of the other's guard.

    If this ever fails, the key has regressed to source-alone.
    """
    from sugar_lift_py_tests.outcome import exit_set as exit_set_module

    minted = []
    original = exit_set_module.partition

    def _record(owner):
        minted.append(owner)
        return original(owner)

    steps = _steps("def g(c):\n    if c:\n        yield 1\n")
    exit_set_module.partition = _record
    try:
        _machine(steps, allocation="call-site-1").resume()
        _machine(steps, allocation="call-site-2").resume()
    finally:
        exit_set_module.partition = original

    assert len(minted) == 2
    # Same source fragment, different instance coordinate, different partition.
    assert minted[0][2] == minted[1][2]
    assert minted[0][1] != minted[1][1]
    assert minted[0] != minted[1]


def test_the_key_carries_the_instance_and_the_fragment() -> None:
    """Both halves are required and neither alone is sound: the fragment gives
    reproducibility across reads of one instance, the instance coordinate keeps
    two executions apart."""
    from sugar_lift_py_tests.outcome import exit_set as exit_set_module

    minted = []
    original = exit_set_module.partition

    def _record(owner):
        minted.append(owner)
        return original(owner)

    exit_set_module.partition = _record
    try:
        machine = _machine(_steps("def g(c):\n    if c:\n        yield 1\n"))
        machine.resume()
    finally:
        exit_set_module.partition = original

    owner = minted[0]
    assert owner[0] == "generator.branch"
    assert owner[1] == machine.instance_coordinate
    assert owner[2]

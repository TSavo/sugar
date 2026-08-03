"""The complexity tooth for #6324: a partition is not an exponent.

#6319 taught `IfExpSugar` that an arm which halts is a PARTITION, not a missing
recognizer. That was right, and it drained 369 desugar-defect rows. It also put
a multi-completed-arm `ExitSet` on a path that `ExitSet.sequence` consumes.

`sequence` appends every exit of the tail under every COMPLETED exit of the
prefix. So a receiver carrying m completed arms, followed by k operands in a
`method_call_sugar._collect` chain, distributes into m ** k arms. Two arms is
not a small number there — it is the base of an exponent. Measured on a quiet
32-core battleaxe at `a4eade69a`, desugar-inclusive, per-file 300s deadline:

| file | arms into one union | wall |
| --- | --- | --- |
| `pandas/tests/extension/test_arrow.py` | 131,364 | timeout >300s |
| `pandas/core/reshape/pivot.py` | 1,304 | timeout >300s |
| `pandas/core/arrays/arrow/array.py` | 436 | timeout >300s |

The live SIGALRM stack named the site: `if_exp_sugar._join_arms` ->
`ExitSet.union` -> `normalize`, reached through `method_call_sugar._collect`.
All three completed in seconds at `a02ebbe3e`, where the same shape raised
`NotImplementedError` and the whole function was abandoned as a defect row.

`ExitSet.factor_completed` is the primitive #6315 built for exactly this: the
SAME partition moves from the exit level (m arms, one value each) to the value
level (one arm, a `GuardedValue` chain), so k steps contribute k guarded values
instead of m ** k arms. Until #6324 it had exactly ONE caller, `SpreadSugar`.
The conditional expression is the second producer of a multi-arm completed
face, and it reached `sequence` without passing through it.

THIS TOOTH COUNTS ARMS, NOT SECONDS. Wall time on a shared box measures the
box; arm population measures the algebra, and arm population is what regressed.
A faster normalizer must never be allowed to hide exponential arm growth, so
this file never looks at a clock.

Read with `test_desugar_defect_family_twins.py`: that file proves the partition
is still LIFTED (the 369-row drain is not given back by turning the panic into
a refusal). This file proves lifting it costs a bounded number of arms. Neither
is sufficient alone — a lift can be complete and unusable, or fast and missing.

RETIREMENT PATH. This tooth is a test because `sequence`'s growth is a property
of a call chain, not of a constructible state. It retires the day the exit
algebra can only be entered through a factored completed face — i.e. when
`ExitSet` exposes no constructor that admits several completed arms into
`sequence`, so `m > 1` at a sequencing seat becomes unrepresentable rather than
detected.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.guarded_value import GuardedValue
from sugar_lift_py_tests.ir import atomic, make_var, not_
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    factored_operand,
    outcome_to_exitset,
)
from sugar_lift_py_tests.sugar.if_exp_sugar import IfExpSugar

OPERAND_COUNTS = (1, 2, 3, 4, 5, 6, 7, 8)


def _guard(name: str):
    return atomic(name, [make_var("state")])


def _partitioning_arm(name: str):
    """An arm that produces a value on one face and halts on the other.

    This is the #6319 shape: `(a if c else <halt>)` where the else arm is an
    unresolvable call or a raise. It is an `ExitSet`, not a `Complete`, which is
    precisely why `_join_arms` takes the union path.
    """
    condition = _guard(name)
    return ExitSet(
        (
            Completed(condition, f"{name}-value"),
            Halted(
                not_(condition),
                RaiseEffect.for_builtin(
                    "ValueError",
                    occurrence="implementations/python/sugar-lift-py-tests/tests/test_partition_arm_growth.py:163:0",
                ),
                None,
            ),
        )
    )


def _joined():
    """What `IfExpSugar._join_arms` hands its caller for a partitioning arm."""
    test = _guard("test")
    return IfExpSugar._join_arms(
        object.__new__(IfExpSugar),
        test,
        Complete("then-value"),
        _partitioning_arm("else"),
    )


def _completed_arms(outcome) -> int:
    exits = outcome_to_exitset(outcome)
    return sum(isinstance(exit_, Completed) for exit_ in exits.exits)


# --------------------------------------------------------------------------
# The bound
# --------------------------------------------------------------------------


def test_a_partitioning_conditional_expression_yields_one_completed_arm():
    """THE BOUND. m == 1, so m ** k == 1 however long the operand chain is.

    Before #6324 this returned TWO completed arms — the then face and the
    else face's completed half — and every downstream operand doubled them.
    """
    assert _completed_arms(_joined()) == 1


def test_operand_chains_over_a_partitioning_conditional_do_not_multiply():
    """THE GROWTH LAW, read directly off `sequence`.

    Each step is one ordinary completed operand, exactly as
    `method_call_sugar._collect` threads them. With a factored receiver the
    completed face stays at one arm for every k. With an unfactored one this
    is 2 ** k, which is what timed out on three pandas files.
    """
    joined = outcome_to_exitset(_joined())

    # The whole series is measured before anything is asserted, so a failure
    # PRINTS the growth curve rather than only its first point. `1, 2, 4, 8,
    # 16, ...` is the regression; `1, 1, 1, 1, ...` is the repaired bound.
    series = []
    for operand_count in OPERAND_COUNTS:
        exits = joined
        for index in range(operand_count):
            exits = exits.sequence(
                lambda value, _i=index: ExitSet.completed((value, _i))
            )
        series.append(sum(isinstance(e, Completed) for e in exits.exits))

    assert series == [1] * len(OPERAND_COUNTS), (
        f"completed arms by operand count {dict(zip(OPERAND_COUNTS, series))}: the "
        "conditional-expression face is unfactored and `ExitSet.sequence` is "
        "distributing it into m ** k arms again (#6324). Factor the completed "
        "face in `IfExpSugar._join_arms` — do not cap, prune, or refuse."
    )


# --------------------------------------------------------------------------
# Discriminators: the bound must not have been bought with meaning
# --------------------------------------------------------------------------


def test_the_halted_arm_survives_the_factoring():
    """DISCRIMINATING. Bounding by DROPPING the halt would pass the test above.

    The halted face is the other half of the meaning. `factor_completed` never
    touches it, and it must still be there.
    """
    exits = outcome_to_exitset(_joined())
    halted = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]

    assert len(halted) == 1
    assert halted[0].effect == RaiseEffect.for_builtin(
        "ValueError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_partition_arm_growth.py:83:0",
    )


def test_both_faces_values_survive_inside_the_guarded_chain():
    """DISCRIMINATING. Bounding by KEEPING ONE VALUE would pass the bound test.

    Factoring relocates the partition; it does not choose a winner. Both arms'
    values must still be reachable, on their own guards, in the chain.
    """
    exits = outcome_to_exitset(_joined())
    completed = [e for e in exits.exits if isinstance(e, Completed)][0]

    chain = completed.value
    assert isinstance(chain, GuardedValue)
    assert chain.when_true == "then-value"
    assert chain.when_false == "else-value"


def test_a_partitioning_operand_enters_a_fold_with_one_completed_arm():
    """THE BOUND, at the shared door.

    `collection_sugar._reduce_into`, `method_call_sugar._collect`,
    `bool_op_sugar` and `fstring_sugar` are the same k-step fold. The
    accumulator cannot be factored (its completed value is the growing tuple),
    so the OPERAND is, and `factored_operand` is the one door that does it.
    """
    assert _completed_arms(factored_operand(_partitioning_arm("element"))) == 1


def test_the_operand_door_does_not_touch_a_plain_outcome():
    """DISCRIMINATING. A `Complete` operand must pass through as itself.

    Widening every operand into the exit algebra would satisfy the bound above
    and route ordinary values through a partition they do not have.
    """
    plain = Complete("value")

    assert factored_operand(plain) is plain


def test_a_partitioning_operand_folded_k_times_does_not_multiply():
    """THE GROWTH LAW at a fold, the shape `_reduce_into` builds.

    Each step appends one factored operand to the accumulated tuple, exactly as
    a collection display does. `1, 2, 4, 8, ...` here is the `test_arrow.py`
    regression: 133,104 arms arrived at ONE `normalize` call through this loop.
    """
    series = []
    for element_count in OPERAND_COUNTS:
        outcome = Complete(())
        for index in range(element_count):
            got = factored_operand(_partitioning_arm(f"element{index}"))
            outcome = outcome.and_then(
                lambda collected, _got=got: _got.and_then(
                    lambda value: Complete((*collected, value))
                )
            )
        series.append(_completed_arms(outcome))

    assert series == [1] * len(OPERAND_COUNTS), (
        f"completed arms by element count {dict(zip(OPERAND_COUNTS, series))}: a "
        "k-operand fold is multiplying arms again (#6324). Send each operand "
        "through `factored_operand` before it enters the fold."
    )


def test_a_fold_conserves_every_halted_arm():
    """DISCRIMINATING. Bounding by dropping halts would pass the law above.

    k partitioning elements halt on k distinct guards, and every one of those
    guards is the other half of the meaning. They arrive as ONE halted arm --
    the k elements share a destination (the same effect, the same state), so
    `normalize` merges them by DISJOINING their guards, which conserves each
    face rather than discarding it. So the assertion is on the guard, not on
    the arm count: `not element0 or not element1 or ...` must still mention
    every element that could halt.
    """
    element_count = 4
    outcome = Complete(())
    for index in range(element_count):
        got = factored_operand(_partitioning_arm(f"element{index}"))
        outcome = outcome.and_then(
            lambda collected, _got=got: _got.and_then(
                lambda value: Complete((*collected, value))
            )
        )

    exits = outcome_to_exitset(outcome)
    halted = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]
    assert len(halted) == 1

    spelled = repr(halted[0].guard)
    for index in range(element_count):
        assert f"element{index}" in spelled, (
            f"element{index}'s halting face is missing from the halted guard "
            f"{spelled}: an arm was dropped, not merged (#6324)."
        )


def test_two_value_conditionals_still_fuse_without_entering_the_exit_algebra():
    """DISCRIMINATING. The all-values case must not be widened to an ExitSet.

    `GuardedValue` fusion is the shape the whole file rests on — operations
    distribute into both arms, equality resolves per atom. Routing every
    conditional through the exit algebra would satisfy every bound above and
    destroy that.
    """
    joined = IfExpSugar._join_arms(
        object.__new__(IfExpSugar), _guard("test"), Complete(1), Complete(2)
    )

    assert isinstance(joined, Complete)
    assert isinstance(joined.value, GuardedValue)
    assert joined.value.when_true == 1
    assert joined.value.when_false == 2

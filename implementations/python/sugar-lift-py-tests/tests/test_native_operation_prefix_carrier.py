"""Deferred native operations compose beneath testified ExitSet prefixes."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    ReducerPreEffectStateV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect import RaiseEffect, UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import NoneValue, SymbolicValue, TermValue
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import PrimitiveSort, and_, atomic, make_var
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import partition
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.tree import SourceFile


def _coordinate(name: str, ordinal: int) -> FormalParameterCoordinateV1:
    source_cid = "blake3-512:" + "d" * 128
    owner = SourceFragmentCoordinateV1(source_cid, 1, 0, 2, 20)
    return FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=source_cid,
        owner_definition_locus=owner,
        declaration_locus=SourceFragmentCoordinateV1(
            source_cid, 1, 4 + ordinal * 5, 1, 8 + ordinal * 5
        ),
        ordinal=ordinal,
        parameter_kind="positional-or-keyword",
        declared_name=name,
        sort=PrimitiveSort("Value"),
    )


def _carrier(operator: str = "less_than"):
    left = _coordinate("left", 0)
    right = _coordinate("right", 1)
    source = "def compare(left, right):\n    return left < right\n"
    tree = SourceFile(
        (source, "prefix-carrier.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    site = next(tree.functions()).fragment
    carrier = NativeOperationExitCarrierV1.mint(
        site=site,
        operator=operator,
        operands=(
            SymbolicValue(make_var("left"), left),
            SymbolicValue(make_var("right"), right),
        ),
        coordinates=(left, right),
    )
    return carrier, left, right


def test_completed_prefix_arms_stay_deferred_and_retain_all_testimony() -> None:
    carrier, left, right = _carrier()
    pre_effect_state = _ReducedBlock((TermValue(7),), True, ())
    carrier = carrier.and_then(
        lambda value: ExitSet.completed(value),
        pre_effect_state=ReducerPreEffectStateV1._from_reducer(pre_effect_state),
    )
    tail_guard = atomic("test:carrier-tail", [])
    carrier = carrier.guarded(tail_guard)
    first_guard = atomic("test:prefix-first", [])
    second_guard = atomic("test:prefix-second", [])
    first_face, second_face = partition("test:prefix-arms")
    stopped_state = object()
    stopped_effect = UndeterminedRaiseEffect(
        blame="prefix-halt", occurrence="prefix-halt"
    )
    prefix = ExitSet(
        (
            Completed(
                first_guard,
                TermValue(1),
                frozenset({first_face}),
            ),
            Completed(
                second_guard,
                TermValue(2),
                frozenset({second_face}),
            ),
            Halted(first_guard, stopped_effect, stopped_state),
        )
    )

    composed = NativeOperationExitCarrierV1.compose_prefix(
        prefix, lambda _value: carrier
    )

    assert isinstance(composed, NativeOperationExitCarrierV1)
    exits = composed.discharge(
        None,
        {
            left.coordinate_cid: NoneValue(),
            right.coordinate_cid: TermValue(2),
        },
    )

    assert len(exits.exits) == 3
    stopped = next(exit_ for exit_ in exits.exits if exit_.effect is stopped_effect)
    assert isinstance(stopped, Halted)
    assert stopped.state is stopped_state
    following = tuple(
        exit_
        for exit_ in exits.exits
        if isinstance(exit_, Halted) and exit_.effect is not stopped_effect
    )
    assert len(following) == 2
    assert following[0].guard == and_([first_guard, tail_guard])
    assert following[0].faces == frozenset({first_face})
    assert following[0].state is pre_effect_state
    assert following[1].guard == and_([second_guard, tail_guard])
    assert following[1].faces == frozenset({second_face})
    assert following[1].state is pre_effect_state


def test_incompatible_prefix_carrier_demands_refuse_loudly() -> None:
    first, _, _ = _carrier("less_than")
    second, _, _ = _carrier("add")
    first_guard = atomic("test:prefix-first", [])
    second_guard = atomic("test:prefix-second", [])
    prefix = ExitSet(
        (
            Completed(first_guard, TermValue(1)),
            Completed(second_guard, TermValue(2)),
        )
    )

    with pytest.raises(
        ConstructionPanic, match="incompatible native-operation demands"
    ):
        NativeOperationExitCarrierV1.compose_prefix(
            prefix,
            lambda value: first if value == TermValue(1) else second,
        )


def test_prefix_composition_retains_later_carrier_continuations() -> None:
    carrier, left, right = _carrier()
    guard = atomic("test:prefix", [])
    prefix = ExitSet((Completed(guard, TermValue(1)),))
    composed = NativeOperationExitCarrierV1.compose_prefix(
        prefix, lambda _value: carrier
    ).and_then(lambda _predicate: ExitSet.completed(TermValue(99)))

    exits = composed.discharge(
        None,
        {
            left.coordinate_cid: TermValue(1),
            right.coordinate_cid: TermValue(2),
        },
    )

    assert exits.exits == (Completed(guard, TermValue(99)),)


class _Desugared:
    """A spread operand standing for its already-desugared outcome."""

    def __init__(self, outcome) -> None:
        self.outcome = outcome

    def desugar(self, ctx=None):
        return self.outcome


def test_spread_operands_before_a_carrier_keep_their_halts_guard_and_debts() -> None:
    """A halt is never dropped: an operand that halts before a deferred one.

    ``[*a, *b]`` where ``a`` completes under one guard owing a debt and halts
    under another, and ``b`` is a deferred native operation. Once the carrier
    discharges, the spread still leaves through ``a``'s halt, and its
    completion lies beneath ``a``'s completed face, owing ``a``'s debt.
    """
    from sugar_lift_py_tests.sugar.spread_sugar import _collect

    carrier, left, right = _carrier()
    completes = atomic("test:spread-first-completes", [])
    halts = atomic("test:spread-first-halts", [])
    effect = UndeterminedRaiseEffect(blame="spread-first", occurrence="spread-first")
    debt = ("test:spread-first-debt",)
    first = ExitSet(
        (
            Completed(completes, TermValue(1), owed=debt),
            Halted(halts, effect, None),
        )
    )
    finished = []

    def finish(values):
        finished.append(values)
        return ExitSet.completed(TermValue(7))

    collected = _collect((_Desugared(first), _Desugared(carrier)), None, (), finish)

    assert isinstance(collected, NativeOperationExitCarrierV1)
    exits = collected.discharge(
        {
            left.coordinate_cid: TermValue(1),
            right.coordinate_cid: TermValue(2),
        }
    )

    assert [arm for arm in exits.exits if isinstance(arm, Halted)] == [
        Halted(halts, effect, None)
    ]
    (completed,) = [arm for arm in exits.exits if isinstance(arm, Completed)]
    assert completed == Completed(completes, TermValue(7))
    assert completed.owed == debt
    assert len(finished) == 1 and finished[0][0] == TermValue(1)

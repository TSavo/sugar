"""Arm population: complementary completed faces rejoin as GuardedValue (#6309).

After #6311, normalize work is near-linear in arm count. What remains of
R(timeout) is arm POPULATION: ``ExitSet.sequence`` is a Cartesian product, and
a spread-shaped collect over *k* two-face elements materialises 2^k concrete
exits when destinations accumulate along the path.

This twin pins the factor disposition: a pure complementary completed pair
rejoins into one ``GuardedValue`` so collect multiplies by one factor per
element, not by two. Both faces stay represented. Halted arms never rejoin.

R(arm_cartesian) on the synthetic k=10 collect is 0 only when rejoin holds;
the planted 2^k baseline stays as the red witness that the product is real.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor import CallSiteValue, GuardedValue, SymbolicValue
from sugar_lift_py_tests.ir import atomic, ctor, not_, str_const
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
from sugar_lift_py_tests.effect import RaiseEffect


def _guard(name: str):
    return atomic(name, [])


def _callsite(tag: str) -> CallSiteValue:
    return CallSiteValue(
        target_name=tag,
        arg_values=(),
        parameters=(),
        term=ctor("python:call", [str_const(tag)]),
        body=None,
        site=f"site:{tag}",
    )


def _two_face(i: int) -> ExitSet:
    g = _guard(f"g{i}")
    return ExitSet(
        (
            Completed(g, _callsite(f"e{i}_t")),
            Completed(not_(g), _callsite(f"e{i}_f")),
        )
    ).normalize()


def test_try_rejoin_complementary_completed_becomes_guarded_value() -> None:
    g = _guard("p")
    es = ExitSet(
        (Completed(g, _callsite("t")), Completed(not_(g), _callsite("f")))
    ).normalize()

    rejoined = es.try_rejoin_as_guarded_value()

    assert isinstance(rejoined, Complete)
    assert isinstance(rejoined.value, GuardedValue)
    assert rejoined.value.guard == g
    assert rejoined.value.when_true == _callsite("t")
    assert rejoined.value.when_false == _callsite("f")


def test_try_rejoin_refuses_halted_face() -> None:
    g = _guard("p")
    effect = RaiseEffect(exception_name="ValueError")
    es = ExitSet(
        (Halted(g, effect, _callsite("s")), Completed(not_(g), _callsite("c")))
    ).normalize()

    assert es.try_rejoin_as_guarded_value() is None


def test_try_rejoin_refuses_non_complementary_guards() -> None:
    es = ExitSet(
        (
            Completed(_guard("a"), _callsite("t")),
            Completed(_guard("b"), _callsite("f")),
        )
    ).normalize()

    assert es.try_rejoin_as_guarded_value() is None


def test_spread_shaped_collect_stays_linear_in_element_count() -> None:
    """k two-face factors compose to one GuardedValue path, not 2^k ExitSet arms.

    The planted Cartesian baseline (sequence without rejoin) is 2^k — that is
    the residual #6309 owns. With rejoin at each factor, collect finishes with
    a single completed outcome whose values carry nested faces.
    """
    k = 10

    def chain_cartesian(idx: int, done: tuple):
        if idx == k:
            terms = [v.to_term(owner="o") for v in done]
            return Complete(SymbolicValue(ctor("python:list", terms)))
        return _two_face(idx).and_then(
            lambda v, idx=idx, done=done: chain_cartesian(idx + 1, (*done, v))
        )

    cartesian = chain_cartesian(0, ())
    assert hasattr(cartesian, "exits"), "cartesian path must stay multi-arm ExitSet"
    assert len(cartesian.exits) == 2**k, (
        f"planted residual: without rejoin, k={k} must produce {2**k} arms; "
        f"got {len(cartesian.exits)}"
    )

    def chain_factored(idx: int, done: tuple):
        if idx == k:
            terms = [v.to_term(owner="o") for v in done]
            return Complete(SymbolicValue(ctor("python:list", terms)))
        outcome = _two_face(idx)
        rejoined = outcome.try_rejoin_as_guarded_value()
        assert rejoined is not None, f"element {idx} must rejoin"
        return rejoined.and_then(
            lambda v, idx=idx, done=done: chain_factored(idx + 1, (*done, v))
        )

    factored = chain_factored(0, ())
    assert isinstance(
        factored, Complete
    ), f"factored collect must finish as one Complete, got {type(factored).__name__}"
    assert isinstance(factored.value, SymbolicValue)
    # R(arm_cartesian)=0 for this twin: one completed outcome, not 2^k ExitSet arms.
    assert not isinstance(factored, ExitSet)

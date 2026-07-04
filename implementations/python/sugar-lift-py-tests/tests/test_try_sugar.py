from __future__ import annotations

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.effect import CoverageGapEffect, RaiseEffect, RuntimeEffect
from sugar_lift_py_tests.floor import (
    BlockValue,
    GuardedReturn,
    RaiseValue,
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, gt, make_var, not_, num
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.try_sugar import _route_incomplete_effect
from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar


def _returns(value: int) -> BlockValue:
    return BlockValue((ReturnValue(TermValue(value)),))


def _sym_add(addend: int) -> SymbolicValue:
    return SymbolicValue(ctor("+", [make_var("x"), num(addend)]))


def _sym_nested_add(first: int, second: int) -> SymbolicValue:
    return SymbolicValue(
        ctor("+", [ctor("+", [make_var("x"), num(first)]), num(second)])
    )


def test_raise_desugars_to_typed_raise_effect() -> None:
    outcome = RaiseSugar().desugar()

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert type(outcome.value.effect).__name__ == "RaiseEffect"
    assert outcome.value.effect.exception_name is None
    assert "raise" in outcome.value.effect.reason


def test_try_except_turns_matching_raise_back_into_complete_block() -> None:
    assert compose_block(
        "    try:\n"
        "        raise ValueError('boom')\n"
        "    except ValueError:\n"
        "        return 5\n"
    ) == _returns(5)


def test_typed_effect_union_routes_each_three_exit_member() -> None:
    class Handler:
        def matches(self, effect: RaiseEffect) -> bool:
            return effect.exception_name == "ValueError"

        def reduce(self, ctx, effect: RaiseEffect):
            return Complete(_returns(7))

    raise_outcome = _route_incomplete_effect(
        Incomplete(RaiseEffect("ValueError", "tests/test_try_sugar.py:1")),
        handlers=(Handler(),),
        ctx=None,
    )
    assert raise_outcome == Complete(_returns(7))

    runtime = Incomplete(RuntimeEffect("runtime boundary"))
    assert _route_incomplete_effect(runtime, handlers=(Handler(),), ctx=None) is runtime

    coverage = Incomplete(
        CoverageGapEffect(
            boundary="floor-dispatch",
            reason="no owning arm reached this floor",
        )
    )
    assert (
        _route_incomplete_effect(coverage, handlers=(Handler(),), ctx=None) is coverage
    )


def test_unhandled_effect_kind_without_dispatch_arm_is_loud() -> None:
    class FutureEffect:
        reason = "new effect shape"

    forged = object.__new__(Incomplete)
    object.__setattr__(forged, "effect", FutureEffect())

    with pytest.raises(TypeError, match="unhandled Effect"):
        _route_incomplete_effect(forged, handlers=(), ctx=None)


def test_try_except_exception_catches_named_raise() -> None:
    assert compose_block(
        "    try:\n"
        "        raise ValueError('boom')\n"
        "    except Exception:\n"
        "        return 5\n"
    ) == _returns(5)


def test_try_except_curries_conditional_raise_paths() -> None:
    guard = gt(make_var("x"), num(0))

    assert compose_block(
        "    try:\n"
        "        if x > 0:\n"
        "            raise ValueError('boom')\n"
        "        return x + 1\n"
        "    except ValueError:\n"
        "        return x + 2\n",
        {"x": SymbolicValue(make_var("x"))},
    ) == BlockValue(
        (
            GuardedReturn((guard,), _sym_add(2)),
            GuardedReturn((not_(guard),), _sym_add(1)),
        )
    )


def test_try_except_handler_uses_scope_from_conditional_raise_path() -> None:
    guard = gt(make_var("x"), num(0))

    assert compose_block(
        "    try:\n"
        "        y = x + 1\n"
        "        if x > 0:\n"
        "            raise ValueError('boom')\n"
        "        return x\n"
        "    except ValueError:\n"
        "        return y + 2\n",
        {"x": SymbolicValue(make_var("x"))},
    ) == BlockValue(
        (
            GuardedReturn((guard,), _sym_nested_add(1, 2)),
            GuardedReturn((not_(guard),), SymbolicValue(make_var("x"))),
        )
    )


def test_outer_try_catches_inner_guarded_raise_with_inner_scope() -> None:
    guard = gt(make_var("x"), num(0))

    assert compose_block(
        "    try:\n"
        "        y = x + 1\n"
        "        try:\n"
        "            if x > 0:\n"
        "                raise ValueError('boom')\n"
        "            return x\n"
        "        except KeyError:\n"
        "            return 99\n"
        "    except ValueError:\n"
        "        return y + 2\n",
        {"x": SymbolicValue(make_var("x"))},
    ) == BlockValue(
        (
            GuardedReturn((guard,), _sym_nested_add(1, 2)),
            GuardedReturn((not_(guard),), SymbolicValue(make_var("x"))),
        )
    )


def test_try_does_not_enter_except_when_body_returns_normally() -> None:
    assert compose_block(
        "    try:\n" "        return 1\n" "    except Exception:\n" "        return 2\n"
    ) == _returns(1)


def test_try_except_does_not_catch_non_raise_incomplete() -> None:
    outcome = compose_block(
        "    try:\n"
        "        return 1 // 0\n"
        "    except Exception:\n"
        "        return 2\n"
    )

    assert isinstance(outcome, Incomplete)
    assert type(outcome.effect).__name__ == "RuntimeEffect"
    assert "division by zero" in outcome.reason


def test_finally_return_overrides_try_return() -> None:
    assert compose_block(
        "    try:\n" "        return 1\n" "    finally:\n" "        return 2\n"
    ) == _returns(2)


def test_finally_return_overrides_uncaught_raise() -> None:
    assert compose_block(
        "    try:\n"
        "        raise ValueError('boom')\n"
        "    finally:\n"
        "        return 2\n"
    ) == _returns(2)


def test_inert_finally_preserves_uncaught_raise() -> None:
    outcome = compose_block(
        "    try:\n"
        "        raise ValueError('boom')\n"
        "    finally:\n"
        "        'cleanup'\n"
    )

    assert isinstance(outcome, BlockValue)
    assert len(outcome.statements) == 1
    assert isinstance(outcome.statements[0], RaiseValue)
    assert type(outcome.statements[0].effect).__name__ == "RaiseEffect"
    assert outcome.statements[0].effect.exception_name == "ValueError"

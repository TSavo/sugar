from __future__ import annotations

from factory_reduce import compose_block

from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar


def _returns(value: int) -> BlockValue:
    return BlockValue((ReturnValue(TermValue(value)),))


def test_raise_desugars_to_typed_raise_effect() -> None:
    outcome = RaiseSugar().desugar()

    assert isinstance(outcome, Incomplete)
    assert type(outcome.effect).__name__ == "RaiseEffect"
    assert outcome.effect.exception_name is None
    assert "raise" in outcome.reason


def test_try_except_turns_matching_raise_back_into_complete_block() -> None:
    assert compose_block(
        "    try:\n"
        "        raise ValueError('boom')\n"
        "    except ValueError:\n"
        "        return 5\n"
    ) == _returns(5)


def test_try_except_exception_catches_named_raise() -> None:
    assert compose_block(
        "    try:\n"
        "        raise ValueError('boom')\n"
        "    except Exception:\n"
        "        return 5\n"
    ) == _returns(5)


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

    assert isinstance(outcome, Incomplete)
    assert type(outcome.effect).__name__ == "RaiseEffect"
    assert outcome.effect.exception_name == "ValueError"

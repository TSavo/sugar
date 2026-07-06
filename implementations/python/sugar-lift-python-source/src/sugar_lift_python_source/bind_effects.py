from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Never, NoReturn


@dataclass(frozen=True)
class MissingBindingEffect:
    symbol: str


@dataclass(frozen=True)
class BoundaryBodyShapeEffect:
    symbol: str


BindEffect = MissingBindingEffect | BoundaryBodyShapeEffect


def bind_effect_outcome(effect: BindEffect) -> str:
    # #3632: the materialize RPC outcome is a typed effect, not a verifier
    # refusal. `implementations/rust/sugar-cli/src/cmd_materialize.rs` reads
    # both "boundary" (current) and legacy "refused" for this field.
    if isinstance(effect, MissingBindingEffect):
        return "boundary"
    if isinstance(effect, BoundaryBodyShapeEffect):
        return "boundary"
    return _unhandled_bind_effect(effect)


def bind_effect_reason(effect: BindEffect) -> str:
    if isinstance(effect, MissingBindingEffect):
        return f"no sugar binding for symbol `{effect.symbol}` in scope"
    if isinstance(effect, BoundaryBodyShapeEffect):
        return "boundary body must be on its own line(s)"
    return _unhandled_bind_effect(effect)


def bind_effect_symbol(effect: BindEffect) -> str:
    if isinstance(effect, MissingBindingEffect):
        return effect.symbol
    if isinstance(effect, BoundaryBodyShapeEffect):
        return effect.symbol
    return _unhandled_bind_effect(effect)


def bind_effect_result(
    effect: BindEffect,
    *,
    file: str,
    function: str,
) -> dict[str, Any]:
    return {
        "file": file,
        "function": function,
        "symbol": bind_effect_symbol(effect),
        "outcome": bind_effect_outcome(effect),
        "reason": bind_effect_reason(effect),
    }


def _unhandled_bind_effect(effect: Never) -> NoReturn:
    raise TypeError(f"unhandled BindEffect arm: {type(effect).__name__}")

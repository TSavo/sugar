"""Semantic fingerprint tooth for the indexed ExitSet normalizer.

The reference implementation is the pre-index all-prior scan.  Its serialized
result is compared byte-for-byte with production normalization so an indexing
change can improve candidate selection without changing exit semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
import json

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.ir import TermTableBuilder, atomic, make_var, not_, or_
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    _is_false,
    _or_guards,
    false_guard,
)


@dataclass(frozen=True)
class _CollisionValue:
    label: str

    def __hash__(self) -> int:
        return 17


@dataclass
class _UnhashableValue:
    label: str


def _guard(name: str):
    return atomic(name, [make_var("state")])


def _quadratic_reference(exit_set: ExitSet) -> ExitSet:
    """The exact pre-index normalization law, retained as the comparison oracle.

    This intentionally duplicates the retired all-prior scan.  It is not dead
    production code: the tooth's byte-for-byte comparison is only meaningful
    while this independent prior-behaviour oracle exists.  Do not replace it
    with ``ExitSet.normalize`` or delete it as tidy-up.
    """
    merged = []
    for exit_ in exit_set.exits:
        if _is_false(exit_.guard):
            continue
        for index, prior in enumerate(merged):
            same_completed = (
                isinstance(exit_, Completed)
                and isinstance(prior, Completed)
                and exit_.value == prior.value
            )
            same_halted = (
                isinstance(exit_, Halted)
                and isinstance(prior, Halted)
                and exit_.effect == prior.effect
                and exit_.state == prior.state
            )
            if same_completed:
                merged[index] = Completed(
                    _or_guards(prior.guard, exit_.guard), prior.value
                )
                break
            if same_halted:
                merged[index] = Halted(
                    _or_guards(prior.guard, exit_.guard),
                    prior.effect,
                    prior.state,
                )
                break
        else:
            merged.append(exit_)
    return ExitSet(tuple(merged))


def _formula_fingerprint(formula) -> dict:
    table = TermTableBuilder()
    encoded = table.formula(formula)
    return {
        "formula": encoded,
        "terms": table.nodes,
    }


def _coordinate(value):
    if isinstance(value, (_CollisionValue, _UnhashableValue)):
        return {
            "type": type(value).__name__,
            "label": value.label,
        }
    if isinstance(value, list):
        return {"type": "list", "items": value}
    return {"type": type(value).__name__, "value": value}


def _fingerprint(exit_set: ExitSet) -> bytes:
    rows = []
    for exit_ in exit_set.exits:
        if isinstance(exit_, Completed):
            row = {
                "kind": "completed",
                "guard": _formula_fingerprint(exit_.guard),
                "value": _coordinate(exit_.value),
            }
        else:
            row = {
                "kind": "halted",
                "guard": _formula_fingerprint(exit_.guard),
                "effect": {
                    "type": type(exit_.effect).__name__,
                    "exceptionName": exit_.effect.exception_name,
                },
                "state": _coordinate(exit_.state),
            }
        rows.append(row)
    return json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def test_indexed_normalize_preserves_quadratic_semantic_fingerprint():
    completed_first = _guard("completed-first")
    completed_second = _guard("completed-second")
    halted_first = _guard("halted-first")
    halted_second = _guard("halted-second")
    retained = _guard("retained")
    unhashable_halt_first = _guard("unhashable-halt-first")
    unhashable_halt_second = _guard("unhashable-halt-second")
    value_error = RaiseEffect(exception_name="ValueError")
    key_error = RaiseEffect(exception_name="KeyError")

    source = ExitSet(
        (
            Completed(completed_first, _CollisionValue("equal")),
            Halted(halted_first, value_error, "halt-state"),
            # Same hash as "equal", but exact inequality must keep this arm.
            Completed(_guard("collision-only"), _CollisionValue("unequal")),
            Completed(completed_second, _CollisionValue("equal")),
            Halted(halted_second, value_error, "halt-state"),
            # These unhashable values are distinct destinations.  Their
            # complementary guards must both remain present.
            Completed(retained, _UnhashableValue("truth-face")),
            Completed(not_(retained), _UnhashableValue("false-face")),
            # An unhashable halted state still follows the old equality law.
            Halted(unhashable_halt_first, key_error, ["same-state"]),
            Halted(unhashable_halt_second, key_error, ["same-state"]),
            Completed(false_guard(), _CollisionValue("unreachable")),
        )
    )

    reference = _quadratic_reference(source)
    normalized = source.normalize()

    assert _fingerprint(normalized) == _fingerprint(reference)
    assert [type(exit_).__name__ for exit_ in normalized.exits] == [
        "Completed",
        "Halted",
        "Completed",
        "Completed",
        "Completed",
        "Halted",
    ]
    assert normalized.exits[0] == Completed(
        or_([completed_first, completed_second]),
        _CollisionValue("equal"),
    )
    assert normalized.exits[1] == Halted(
        or_([halted_first, halted_second]),
        value_error,
        "halt-state",
    )
    assert normalized.exits[2] == Completed(
        _guard("collision-only"),
        _CollisionValue("unequal"),
    )
    assert normalized.exits[3] == Completed(
        retained,
        _UnhashableValue("truth-face"),
    )
    assert normalized.exits[4] == Completed(
        not_(retained),
        _UnhashableValue("false-face"),
    )
    assert normalized.exits[5] == Halted(
        or_([unhashable_halt_first, unhashable_halt_second]),
        key_error,
        ["same-state"],
    )

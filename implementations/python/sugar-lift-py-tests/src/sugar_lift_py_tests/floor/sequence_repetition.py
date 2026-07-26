from __future__ import annotations

# How large a concrete repetition this floor MATERIALIZES rather than folding to
# its closed coordinate. Not a cap: see ``repeat_sequence``, which refuses no
# cardinality and drops no element at any cardinality.
EAGER_MATERIALIZATION_BUDGET = 128


def repeat_sequence(sequence, count, site, *, elements, rebuild):
    """``sequence * count`` for one concrete sequence, at any cardinality.

    Cardinality does not change WHAT a repetition is. A concrete sequence
    repeated a concrete number of times has exactly one value, and this law
    owns two EQUAL representations of it:

        materialized  rebuild(elements * n)
        folded        python:sequence_repeat(sequence, n)

    The folded form is the same closed coordinate the opaque-count arm emits,
    so it is exact, not lossy. Which one is built is a representation choice
    about eager memory -- there is no cardinality at which this law refuses,
    and none at which it silently drops elements. (List and tuple each carried
    a private copy of this arm that PANICKED above 128, reporting 19 perfectly
    ordinary pandas repetitions as construction gaps.)

    ``elements`` and ``rebuild`` are the receiver's own element tuple and its
    own constructor over one, so each sequence category names and rebuilds its
    own shape and no category learns another's. (``ArrayLiteral`` spells its
    elements ``items``; reading ``.elements`` off the receiver was this law
    knowing one category's field name, which is why the array never joined.)
    """
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.outcome import Complete

    if type(count) is TermValue and type(count.value) in (int, bool):
        n = count.value
        if len(elements) * max(n, 0) <= EAGER_MATERIALIZATION_BUDGET:
            return Complete(rebuild(elements * n))
        return Complete(SymbolicValue(repetition_term(sequence, count, site)))
    if is_known_invalid_repetition_count(count):
        return known_invalid_repetition_type_error(sequence, count, site)
    return Complete(SymbolicValue(repetition_term(sequence, count, site)))


def repetition_term(sequence, count, site):
    """The ONE closed sequence-repetition coordinate, for every count."""
    from sugar_lift_py_tests.ir import ctor

    return ctor(
        "python:sequence_repeat",
        [
            sequence.to_term(owner=str(site)),
            count.to_term(owner=str(site)),
        ],
    )


def is_known_invalid_repetition_count(value) -> bool:
    """Whether construction knows this value cannot satisfy ``__index__``."""
    from sugar_lift_py_tests.floor.bytes_value import BytesValue
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.term_value import TermValue

    if type(value) is TermValue:
        return type(value.value) not in (int, bool)
    return type(value) in (StringValue, BytesValue, NoneValue)


def known_invalid_repetition_type_error(sequence, count, site):
    """Construct Python's typed exceptional boundary for ``sequence * count``."""
    from sugar_lift_py_tests.effect import (
        TypeErrorRuntimeEffect,
        runtime_effect_evidence,
    )
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Incomplete

    operation = ctor(
        "call:python.sequence_repeat",
        [
            sequence.to_term(owner=str(site)),
            _known_ground_term(count, owner=str(site)),
        ],
    )
    return Incomplete(
        TypeErrorRuntimeEffect(
            "sequence repetition count is a known ground value without "
            f"__index__; count={type(count).__name__} site={site}",
            **runtime_effect_evidence("python:sequence_repeat", operation, site),
        )
    )


def _known_ground_term(value, *, owner: str):
    """Project the concrete multiplier itself without stringifying it."""
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.ir import ctor, str_const

    if type(value) is TermValue:
        if type(value.value) is str:
            return str_const(value.value)
        if type(value.value) is bytes:
            return ctor("python:bytes", [str_const(value.value.hex())])
        if value.value is None:
            return ctor("None", [])
    return value.to_term(owner=owner)

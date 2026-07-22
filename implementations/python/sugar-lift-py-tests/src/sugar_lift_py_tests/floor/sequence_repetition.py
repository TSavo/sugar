from __future__ import annotations


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

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor.bytes_value import BytesValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


@dataclass(frozen=True)
class BytesLiteralSugar(Sugar):
    """A `bytes` literal (`b"..."`). A leaf: it holds its value and no child
    sugars, and it desugars to the BytesValue floor -- which stands as the
    vendor-canonical ``python:bytes(<hex String const>)`` term already
    consumed downstream (SMT emitter, verifier structural ground-ctor
    whitelist, isinstance fold table)."""

    value: bytes
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="bytes_literal_return",
            owner_sugar="BytesLiteralSugar",
            body='b"ab"',
            truthful='b"ab"',
            lying='b"ac"',
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx  # the bytes stand as a floor value
        return Complete(BytesValue(self.value))

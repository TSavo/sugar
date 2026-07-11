from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


@dataclass(frozen=True)
class BytesLiteralSugar(Sugar, role=SugarRole.TERM):
    """A bytes literal (``b\"…\"``).

    Observed as ``Constant`` (not ``PrimitiveLiteral`` — bytes is not in the
    int/float/str/bool/None collapse). Reduces to ``python:bytes(hex)`` so
    equality and dig can stand on the same floor as projected ``b'…'`` claims
    (see deleted ConstantSugar era + test_constant_sugar).

    #4106: without this, ``Signer(b\"secret\")`` and most itsdangerous tests
    die as unresolved Constant → silent asserts.
    """

    value: bytes
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Constant" and type(site.literal_value()) is bytes

    @classmethod
    def new(cls, site, ctx) -> "BytesLiteralSugar":
        del ctx
        return cls(value=site.literal_value(), site=site)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="bytes_literal_return",
            owner_sugar="BytesLiteralSugar",
            body="b'ab'",
            truthful="b'ab'",
            lying="b'xy'",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor, str_const

        return Complete(
            SymbolicValue(ctor("python:bytes", [str_const(self.value.hex())]))
        )

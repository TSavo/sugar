from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import EllipsisType

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor, real_lit, str_const
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import constant_bytes_return_witness


@dataclass(frozen=True)
class ConstantSugar(Sugar, role=SugarRole.TERM):
    value: bytes | complex | EllipsisType

    @classmethod
    def owns(cls, site) -> bool:
        return cls.from_site(site) is not None

    @classmethod
    def witnesses(cls):
        return constant_bytes_return_witness()

    @classmethod
    def build(cls, site, ctx) -> "ConstantSugar":
        del ctx
        sugar = cls.from_site(site)
        if sugar is None:
            raise TypeError("ConstantSugar claim built an unsupported Constant")
        return sugar

    @classmethod
    def from_site(cls, site) -> "ConstantSugar | None":
        if site.observed != "Constant":
            return None
        value = site.literal_value()
        if isinstance(value, (bytes, complex)) or value is Ellipsis:
            return cls(value)
        return None

    def desugar(self) -> Outcome:
        if isinstance(self.value, bytes):
            return Complete(
                SymbolicValue(ctor("py.bytes", [str_const(self.value.hex())]))
            )
        if isinstance(self.value, complex):
            return Complete(
                SymbolicValue(
                    ctor(
                        "py.complex",
                        [
                            _real_part_term(self.value.real),
                            _real_part_term(self.value.imag),
                        ],
                    )
                )
            )
        if self.value is Ellipsis:
            return Complete(SymbolicValue(ctor("py.ellipsis", [])))
        raise TypeError(
            f"write more Sugar for ConstantSugar value `{type(self.value).__name__}`"
        )


def _real_part_term(value: float):
    return real_lit(format(Decimal(str(value)), "f"))

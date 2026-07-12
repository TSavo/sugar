from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Term

from .floor_value import FloorValue


@dataclass(frozen=True)
class Bv32Value(FloorValue):
    term: Term

    def to_term(self, *, owner: str):
        del owner
        return self.term

    def project_callsite_with(self, operation, ctx):
        return operation.project_literal(self, ctx)

    def str_with(self, operation, ctx):
        return operation.str_bv32(self, ctx)

    def bitwise_with(self, operation, ctx):
        return operation.bitwise_bv32(self, ctx)

    def bitwise_and(self, other, site):
        return self._binary_bitwise(other, site, "bv32.and")

    def bitwise_xor(self, other, site):
        return self._binary_bitwise(other, site, "bv32.xor")

    def bitwise_or(self, other, site):
        return self._binary_bitwise(other, site, "bv32.or")

    def left_shift(self, other, site):
        return self._binary_bitwise(other, site, "bv32.shl")

    def right_shift(self, other, site):
        return self._binary_bitwise(other, site, "bv32.lshr")

    def _binary_bitwise(self, other, site, operator):
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            Bv32Value(
                ctor(
                    operator,
                    [self.to_term(owner=str(site)), other.to_term(owner=str(site))],
                )
            )
        )

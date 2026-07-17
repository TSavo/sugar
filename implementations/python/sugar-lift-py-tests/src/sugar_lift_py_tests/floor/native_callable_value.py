from __future__ import annotations

from dataclasses import dataclass, field

from .floor_value import FloorValue


@dataclass(frozen=True)
class NativeCallableValue(FloorValue):
    """An exact symbol owned by an installed native extension module.

    Python source can cite and call this coordinate, but it cannot provide a
    Python body. A later native lifter may emit a contract for the same
    ``qualified_name``; the linker joins the two applications by EUF.
    """

    qualified_name: str
    module_origin: str = field(compare=False)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:native_callable",
            [str_const(self.qualified_name)],
            symbol_kind="coordinate",
        )

    def subtract(self, other, site):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

        if type(other) is CallSiteValue:
            from sugar_lift_py_tests.effect import runtime_subtract

            return runtime_subtract(self, other, site)
        return super().subtract(other, site)

    def divide(self, other, site):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

        if type(other) is CallSiteValue and other.body is None:
            from sugar_lift_py_tests.effect import runtime_divide

            return runtime_divide(self, other, site)
        return super().divide(other, site)

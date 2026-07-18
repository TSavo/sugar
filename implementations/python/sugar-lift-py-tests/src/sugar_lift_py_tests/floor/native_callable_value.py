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

    def add(self, other, site):
        """Preserve addition when both native and call-result coordinates exist.

        This does not claim the call's result type or fold the sum.  It only
        constructs the exact ``+(native-coordinate, call-coordinate)`` term
        already named by the source operation.  A free symbolic peer carries
        no callable coordinate and therefore remains on the loud floor.
        """
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

        if type(other) is CallSiteValue:
            from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

            return SymbolicValue(self.to_term(owner=str(site))).add(other, site)
        return super().add(other, site)

    def divide(self, other, site):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

        if type(other) is CallSiteValue and other.body is None:
            from sugar_lift_py_tests.effect import runtime_divide

            return runtime_divide(self, other, site)
        return super().divide(other, site)

    def format_data_model(self, spec, site, ctx):
        """Construct ``format(native_callable, spec)`` as an exact coordinate.

        Native extension symbols have no Python ``__format__`` body to dig. The
        receiver and format spec are already lift-time coordinates, so this is
        construction of the data-model method address — never a RuntimeEffect
        and never a fabricated concrete string (#5156).
        """
        del ctx
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            CallSiteValue(
                target_name="__format__",
                arg_values=(self, spec),
                parameters=(),
                term=ctor(
                    "call:__format__",
                    [
                        self.to_term(owner=str(site)),
                        spec.to_term(owner=str(site)),
                    ],
                    symbol_kind="method-coordinate",
                ),
                body=None,
                site=site,
            )
        )

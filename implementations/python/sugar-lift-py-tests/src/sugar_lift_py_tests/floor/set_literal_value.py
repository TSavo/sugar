from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Term, ctor

from .floor_value import FloorValue


@dataclass(frozen=True)
class SetLiteralValue(FloorValue):
    """A structural Python set literal term with deterministic support order."""

    items: tuple[Term, ...]

    def setitem(self, index, value, site, ctx):
        del index, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="SetLiteralValue.setitem"
        )

    def delitem(self, index, site, ctx):
        del index, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="SetLiteralValue.delitem"
        )

    def setattr(self, name, value, site, ctx):
        del name, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError",
            site=site,
            owner="SetLiteralValue.setattr",
        )

    def delattr(self, name, site, ctx):
        del name, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError",
            site=site,
            owner="SetLiteralValue.delattr",
        )

    def contribution(self):
        # Typed non-FOL support carrier: absorbed in a block record.
        return ()

    def to_term(self, *, owner: str) -> Term:
        del owner
        return ctor("python:set", list(self.items))

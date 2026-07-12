from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import factory_panic_gap
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class GlobalRoute(FloorValue):
    names: tuple[str, ...]

    def contribution(self):
        return ()

    def extend_scope(self, ctx):
        return replace(ctx, global_names=ctx.global_names | frozenset(self.names))


@dataclass(frozen=True)
class GlobalSugar(Sugar, role=SugarRole.STATEMENT):
    """Route declared names to the statically constructed module frame."""

    names: tuple[str, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Global"

    @classmethod
    def new(cls, site, ctx) -> "GlobalSugar":
        del ctx
        return cls(names=tuple(site.node.names), site=site)

    @classmethod
    def witnesses(cls):
        prefix = (
            "shared = 1\n"
            "def A(z):\n"
            "    global shared\n"
            "    shared = z\n"
            "    return shared\n\n"
        )
        return _call_pair(
            name="global_module_binding",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        if ctx is None or ctx.module_temporal is None:
            factory_panic_gap(
                owner=type(self).__name__,
                blame=str(self.site),
                observed="dynamic module frame",
                requested="statically known module temporal",
                fix="construct the function through the module audit door",
            )
        return Complete(GlobalRoute(self.names))

    def walk_children(self):
        return ()

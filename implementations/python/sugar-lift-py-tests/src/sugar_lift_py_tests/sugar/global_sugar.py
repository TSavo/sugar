from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import GlobalScopeRuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness


@dataclass(frozen=True)
class GlobalSugar(Sugar, role=SugarRole.STATEMENT):
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
        return typed_red_effect_witness(
            name="global_scope_runtime_effect",
            owner_sugar=cls.__name__,
            source="def A():\n    global shared\n",
            effect_class="GlobalScopeRuntimeEffect",
            reason_needle="runtime module frame",
            blame_needle="test_witness.py:2:4",
            wrong_reason_needle="subscript store",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        return Incomplete(
            GlobalScopeRuntimeEffect(
                "global declaration resolves writes through the runtime module "
                f"frame; names={self.names}; site={self.site}"
            )
        )

    def walk_children(self):
        return ()

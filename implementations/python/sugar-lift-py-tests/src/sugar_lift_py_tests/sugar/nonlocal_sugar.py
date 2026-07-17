from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import (
    NonlocalMutationRuntimeEffect,
    runtime_effect_witness,
)
from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness


@dataclass(frozen=True)
class NonlocalSugar(Sugar, role=SugarRole.STATEMENT):
    """``nonlocal`` crosses an enclosing runtime function frame.

    The declaration is recognized, but this body has no closed ownership of
    the enclosing frame or its interleavings. Keep that boundary typed red
    instead of pretending the binding is local or silently dropping it.
    """

    names: tuple[str, ...]
    site: object = field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Nonlocal"

    @classmethod
    def new(cls, site, ctx) -> "NonlocalSugar":
        del ctx
        return cls(tuple(site.node.names), site)

    @classmethod
    def witnesses(cls):
        return typed_red_effect_witness(
            name="nonlocal_mutation_runtime_effect",
            owner_sugar=cls.__name__,
            source=(
                "def A():\n"
                "    nonlocal shared\n"
                "    shared = 2\n"
                "    return shared\n"
            ),
            effect_class="NonlocalMutationRuntimeEffect",
            reason_needle="nonlocal shared-scope mutation",
            blame_needle="test_witness.py:2:4",
            wrong_reason_needle="owner=GlobalSugar",
        )

    def desugar(self, ctx=None) -> Outcome:
        del ctx
        names = ", ".join(self.names)
        return Incomplete(
            NonlocalMutationRuntimeEffect(
                f"nonlocal shared-scope mutation crosses an enclosing runtime "
                f"frame: names={names}; site={self.site}",
                witness=runtime_effect_witness(
                    "py.nonlocal", StringValue(names), self.site
                ),
            )
        )

    def walk_children(self):
        return ()

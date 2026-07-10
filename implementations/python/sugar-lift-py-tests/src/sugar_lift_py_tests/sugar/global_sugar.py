# SPDX-License-Identifier: MIT OR Apache-2.0
"""Global declaration is shared-scope support, not a local binding.

`global x` swears the name punches through the function frame into module
scope. Cross-frame interleaving is not pinned by this body (grammar_ledger
membrane). Treating the statement as inert `SupportValue` accounts for it
without inventing module-mutation floor semantics — same spirit as
nested-def-is-support / annotation-only AnnAssign.

Lift-probe (before): empty STATEMENT catalog candidates for Global →
FactoryGap `create sugar_lift_py_tests.sugar.global.global_sugar`.
Mechanism: missing AST recognizer (not a floor totalizer).
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import SupportValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import inert_statement_return_witness
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing, SugarWitnessPair


@dataclass(frozen=True)
class GlobalSugar(Sugar, role=SugarRole.STATEMENT):
    """`global name, …` → SupportValue (declaration membrane, no fabricated mutation)."""

    names: tuple[str, ...]

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Global"

    @classmethod
    def witnesses(cls) -> tuple[NotVerdictBearing, SugarWitnessPair]:
        return (
            NotVerdictBearing(
                sugar_name=cls.__name__,
                floor_name="SupportValue",
                reason=(
                    "global is a shared-scope declaration membrane; cross-frame "
                    "interleaving is not pinned by this body (SupportValue, not "
                    "fabricated module mutation)"
                ),
            ),
            inert_statement_return_witness(
                name="global_support_return",
                owner_sugar=cls.__name__,
                statement="global x",
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "GlobalSugar":
        del ctx
        import ast

        if not cls.owns(site):
            raise TypeError(
                "GlobalSugar claim built a non-Global statement: "
                f"observed={site.observed!r} blame={site.blame}"
            )
        node = site.node
        if not isinstance(node, ast.Global):
            raise TypeError(
                "GlobalSugar claim built a non-ast.Global node: "
                f"got {type(node).__name__} blame={site.blame}"
            )
        return cls(names=tuple(node.names))

    def _build(self, ctx=None) -> Outcome:
        del ctx
        return Complete(SupportValue())

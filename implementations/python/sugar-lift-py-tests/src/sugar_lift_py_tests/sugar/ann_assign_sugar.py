# SPDX-License-Identifier: MIT OR Apache-2.0
"""Annotated assignment is an assignment; the annotation is support.

`x: int = 5` is the same binding as `x = 5` for the factory body walk. The
annotation (`int`, `np.ndarray`, …) is type metadata — not proof content —
same spirit as nested-def-is-support: account for it without inventing a
type-universe floor. Annotation-only forms (`x: int`) bind nothing and are
inert SupportValue.

Lift-probe (before): empty STATEMENT catalog candidates for AnnAssign →
FactoryGap `create sugar_lift_py_tests.sugar.ann_assign.ann_assign_sugar`.
Mechanism: missing AST recognizer (not a floor totalizer).
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BoundVar, SupportValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import (
    NotVerdictBearing,
    SugarWitnessPair,
    WitnessSource,
)
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AnnAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """`name: Ann = <rhs>` → BoundVar; `name: Ann` alone → SupportValue.

    Non-Name targets (attribute/subscript AnnAssign) are not owned here — they
    remain a construction gap until a narrower sugar claims them.
    """

    name: str
    value: SugarBody | None
    # Annotation is intentionally not a template operand: type metadata only.
    annotation_kind: str

    # Match AssignSugar: do not reduce the rhs here — BoundVar aliases the source.
    template_operand_names = ()

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "AnnAssign":
            return False
        try:
            site.annassign_target_id()
        except TypeError:
            return False
        return True

    @classmethod
    def witnesses(cls) -> tuple[NotVerdictBearing, SugarWitnessPair]:
        prefix = "def A(z):\n    x: int = z\n    return x\n\n"
        return (
            NotVerdictBearing(
                sugar_name=cls.__name__,
                floor_name="BoundVar|SupportValue",
                reason=(
                    "AnnAssign annotation is type metadata (support); valued form "
                    "binds like AssignSugar; annotation-only is inert SupportValue"
                ),
            ),
            SugarWitnessPair(
                name="ann_assign_return",
                owner_sugar=cls.__name__,
                family="binding",
                truthful=WitnessSource(
                    source=prefix + "def test_a():\n    assert A(1) == 1\n",
                    expected="sat",
                ),
                lying=WitnessSource(
                    source=prefix + "def test_a():\n    assert A(1) == 2\n",
                    expected="unsat",
                ),
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "AnnAssignSugar":
        if not cls.owns(site):
            raise TypeError(
                "AnnAssignSugar claim built a non-Name AnnAssign: "
                f"observed={site.observed!r} blame={site.blame}"
            )
        name = site.annassign_target_id()
        value_frag = site.annassign_value()
        annotation = site.annassign_annotation()
        return cls(
            name=name,
            value=(
                None
                if value_frag is None
                else ctx.build_body(value_frag, SugarRole.TERM)
            ),
            annotation_kind=annotation.observed,
        )

    def _build(self, ctx=None) -> Outcome:
        # Annotation never reduced — type metadata, not a term.
        if self.value is None:
            return Complete(SupportValue())
        # Same lazy BoundVar as AssignSugar: alias name → rhs source.
        return Complete(BoundVar(self.name, self.value, scope=ctx))

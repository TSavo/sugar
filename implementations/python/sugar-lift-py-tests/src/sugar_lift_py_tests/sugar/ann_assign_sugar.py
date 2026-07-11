from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BoundVar, SupportValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AnnAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """Annotated assignment ``name: annotation [= value]``.

    Valued form ``x: int = 5`` is the same binding as AssignSugar: a BoundVar
    that aliases the name to the rhs SOURCE under the definition scope. The
    annotation is carried (factory-built TERM body) -- never dropped -- and
    reduces under BuiltinTypeNameSugar to ``python:type("int")`` etc.

    Bare declaration ``x: int`` (no value) is support only: present, accounted
    for, binds nothing. Attribute / subscript AnnAssign targets stay unowned
    (loud factory gap). Disjoint from AssignSugar (observed Assign vs AnnAssign).
    """

    name: str
    annotation: SugarBody
    # Observed kind of the annotation AST node (Name / Attribute / ...).
    annotation_kind: str
    # Optional rhs; None for bare ``x: int``.
    value: SugarBody | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        # Name targets only; Attribute AnnAssign stays a loud gap.
        if site.observed != "AnnAssign":
            return False
        target = site.annassign_target()
        return target.observed == "Name"

    @classmethod
    def new(cls, site, ctx) -> "AnnAssignSugar":
        # Annotation and optional value are factory-built (audited), never reduced.
        ann = site.annassign_annotation()
        value_site = site.annassign_value()
        return cls(
            name=site.annassign_target().name_id(),
            annotation=ctx.build_body(ann, SugarRole.TERM),
            annotation_kind=ann.observed,
            value=(
                None
                if value_site is None
                else ctx.build_body(value_site, SugarRole.TERM)
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Valued AnnAssign binds like Assign; the pair discriminates on the
        # face that reads the assigned binding.
        prefix = "def A(z):\n    x: int = z\n    return x\n\n"
        return _call_pair(
            name="ann_assign_return",
            owner_sugar="AnnAssignSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        if self.value is None:
            # Bare declaration: annotation is present (carried on this sugar);
            # no binding is introduced.
            return Complete(SupportValue())
        # Same binding mechanism as AssignSugar -- BoundVar aliases the source.
        return Complete(BoundVar(self.name, self.value, scope=ctx))

    def walk_children(self):
        if self.value is None:
            return (self.annotation,)
        return (self.annotation, self.value)

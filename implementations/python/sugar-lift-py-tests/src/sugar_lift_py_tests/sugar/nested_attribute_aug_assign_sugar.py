from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ScopeRebind
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class NestedAttributeAugAssignSugar(
    Sugar,
    role=SugarRole.STATEMENT,
    comes_before=("SelectedAttributeAugAssignSugar",),
):
    """Update one exact name-rooted dotted binding through the ordinary operator."""

    path: tuple[str, ...]
    updated_value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "AugAssign":
            return False
        path = site.aug_assign_target_dotted_attribute_path()
        return path is not None and len(path) >= 3

    @classmethod
    def new(cls, site, ctx) -> "NestedAttributeAugAssignSugar":
        path = site.aug_assign_target_dotted_attribute_path()
        if path is None or len(path) < 3:
            raise TypeError(
                "NestedAttributeAugAssignSugar requires a name-rooted nested "
                f"attribute target at {site.blame}"
            )
        return cls(
            path=path,
            updated_value=ctx.build_body(site.aug_assign_binop(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    z.adaptive.stepsize = 8\n"
            "    z.adaptive.stepsize /= 2\n"
            "    return z.adaptive.stepsize\n\n"
        )
        return _call_pair(
            name="nested_attribute_divassign_return",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A(0) == 4.0\n",
            lying=prefix + "def test_a():\n    assert A(0) == 8\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        key = ".".join(self.path)
        return self.updated_value.reduce(ctx).and_then(
            lambda updated: Complete(ScopeRebind(key, updated))
        )

    def walk_children(self):
        return (self.updated_value,)

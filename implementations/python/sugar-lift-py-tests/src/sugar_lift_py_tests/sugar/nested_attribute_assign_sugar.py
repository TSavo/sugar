from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ScopeRebind
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class NestedAttributeAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """Bind one exact name-rooted dotted assignment source address."""

    path: tuple[str, ...]
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        path = site.assign_target_dotted_attribute_path()
        return path is not None and len(path) >= 3

    @classmethod
    def new(cls, site, ctx) -> "NestedAttributeAssignSugar":
        path = site.assign_target_dotted_attribute_path()
        return cls(
            path=path,
            value=ctx.build_body(site.assign_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    z.flags.writeable = False\n"
            "    return z.flags.writeable\n\n"
        )
        return _call_pair(
            name="nested_attribute_assign_return",
            owner_sugar="NestedAttributeAssignSugar",
            truthful=prefix + "def test_a():\n    assert A(5) is False\n",
            lying=prefix + "def test_a():\n    assert A(5) is True\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        key = ".".join(self.path)
        return self.value.reduce(ctx).and_then(
            lambda value: Complete(ScopeRebind(key, value))
        )

    def walk_children(self):
        return (self.value,)

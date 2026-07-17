from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class DeletedBindings(FloorValue):
    names: tuple[str, ...]

    def contribution(self):
        return ()

    def extend_scope(self, ctx):
        return replace(ctx, temporal=ctx.temporal.unbind_names(self.names))


@dataclass(frozen=True)
class DeleteSugar(Sugar, role=SugarRole.STATEMENT):
    """A ``del`` statement whose flat or parenthesized targets are all names.

    Name deletion is temporal-scope mutation. Subscript and attribute deletion
    require store-effect dispatch and deliberately remain outside this owner.
    """

    names: tuple[str, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Delete":
            return False
        return _delete_name_targets(site) is not None

    @classmethod
    def new(cls, site, ctx) -> "DeleteSugar":
        names = _delete_name_targets(site)
        assert names is not None
        return cls(
            names=names,
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A():\n"
            "    x = 1\n"
            "    y = 2\n"
            "    del (x, y)\n"
            "    return 2\n\n"
        )
        return _call_pair(
            name="delete_name_statement",
            owner_sugar="DeleteSugar",
            truthful=prefix + "def test_a():\n    assert A() == 2\n",
            lying=prefix + "def test_a():\n    assert A() == 1\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return Complete(DeletedBindings(self.names))

    def walk_children(self):
        return ()


def _delete_name_targets(site) -> tuple[str, ...] | None:
    targets = site.delete_targets()
    if not targets:
        return None
    if len(targets) == 1 and targets[0].observed == "Tuple":
        targets = targets[0].tuple_elts()
    if not targets or any(target.observed != "Name" for target in targets):
        return None
    return tuple(target.name_id() for target in targets)

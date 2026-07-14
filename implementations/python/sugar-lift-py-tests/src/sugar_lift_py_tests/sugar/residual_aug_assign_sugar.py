from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect
from sugar_lift_py_tests.floor import BoundVar, ScopeRebind
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody

_RESIDUAL_NAME_OPS = frozenset({"BitAnd", "BitXor", "LShift", "RShift"})


@dataclass(frozen=True)
class BitOrNameAugAssignSugar(Sugar, role=SugarRole.STATEMENT):
    name: str
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "AugAssign"
            and site.aug_assign_target().observed == "Name"
            and site.aug_assign_op() == "BitOr"
        )

    @classmethod
    def new(cls, site, ctx) -> "BitOrNameAugAssignSugar":
        return cls(
            name=site.aug_assign_target().name_id(),
            value=ctx.build_body(site.aug_assign_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A():\n    x = 5\n    x |= 2\n    return x\n\n"
        return _call_pair(
            name="bitor_name_augassign",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A() == 7\n",
            lying=prefix + "def test_a():\n    assert A() == 5\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.value.reduce(ctx).and_then(
            lambda argument: ctx.temporal.value_for(self.name)
            .answer(ctx)
            .and_then(
                lambda old: old.bitwise_or(argument, self.site).and_then(
                    lambda updated: Complete(ScopeRebind(self.name, updated))
                )
            )
        )

    def walk_children(self):
        return (self.value,)


@dataclass(frozen=True)
class ResidualNameAugAssignSugar(Sugar, role=SugarRole.STATEMENT):
    name: str
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "AugAssign"
            and site.aug_assign_target().observed == "Name"
            and site.aug_assign_op() in _RESIDUAL_NAME_OPS
        )

    @classmethod
    def new(cls, site, ctx) -> "ResidualNameAugAssignSugar":
        return cls(
            name=site.aug_assign_target().name_id(),
            value=ctx.build_body(site.aug_assign_binop(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A():\n    x = 5\n    x |= 2\n    return x\n\n"
        return _call_pair(
            name="residual_name_augassign",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A() == 7\n",
            lying=prefix + "def test_a():\n    assert A() == 5\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return Complete(BoundVar(self.name, self.value, scope=ctx))

    def walk_children(self):
        return (self.value,)


@dataclass(frozen=True)
class ResidualSubscriptAugAssignSugar(Sugar, role=SugarRole.STATEMENT):
    receiver: SugarBody
    receiver_name: str | None
    index: SugarBody
    updated_value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "AugAssign"
            and site.aug_assign_target().observed == "Subscript"
            and site.aug_assign_op() != "Add"
        )

    @classmethod
    def new(cls, site, ctx) -> "ResidualSubscriptAugAssignSugar":
        target = site.aug_assign_target()
        receiver = target.subscript_receiver()
        return cls(
            receiver=ctx.build_body(receiver, SugarRole.TERM),
            receiver_name=receiver.name_id() if receiver.observed == "Name" else None,
            index=ctx.build_body(target.subscript_index(), SugarRole.TERM),
            updated_value=ctx.build_body(site.aug_assign_binop(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A():\n    xs = [3]\n    xs[0] *= 4\n    return xs[0]\n\n"
        return _call_pair(
            name="residual_subscript_augassign",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A() == 12\n",
            lying=prefix + "def test_a():\n    assert A() == 3\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: self.index.reduce(ctx).and_then(
                lambda index: self.updated_value.reduce(ctx).and_then(
                    lambda updated: receiver.setitem(
                        index, updated, self.site
                    ).and_then(self._cite_update)
                )
            )
        )

    def _cite_update(self, updated) -> Outcome:
        if self.receiver_name is not None:
            return Complete(ScopeRebind(self.receiver_name, updated))
        from sugar_lift_py_tests.effect import runtime_effect_witness

        return Incomplete(
            SubscriptStoreRuntimeEffect(
                "augmented subscript store completed on a non-name receiver whose "
                f"post-state cannot be rebound; site={self.site}",
                witness=runtime_effect_witness("py.setitem", updated, self.site),
            )
        )

    def walk_children(self):
        return (self.receiver, self.index, self.updated_value)

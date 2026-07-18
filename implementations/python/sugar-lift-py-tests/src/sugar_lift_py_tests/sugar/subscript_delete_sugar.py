from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import FloorValue, ScopeRebind
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.subscript_store_post_state import (
    cite_subscript_post_state,
)
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.recognition.delete_targets import (
    DeleteTargetKind,
    DeleteTargetRecognition,
    RecognizedDeleteTarget,
)


@dataclass(frozen=True)
class SubscriptDeleteSugar(Sugar, role=SugarRole.STATEMENT):
    """One ``del receiver[index]`` routed through the subscript-store floor."""

    receiver: SugarBody
    receiver_coordinate: str | None
    index: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        targets = DeleteTargetRecognition.statement_targets(site)
        return (
            targets is not None
            and len(targets) == 1
            and targets[0].kind is DeleteTargetKind.SUBSCRIPT
        )

    @classmethod
    def new(cls, site, ctx) -> "SubscriptDeleteSugar":
        target = site.delete_targets()[0]
        receiver = target.subscript_receiver()
        return cls(
            receiver=ctx.build_body(receiver, SugarRole.TERM),
            receiver_coordinate=receiver.dotted_expr_name(),
            index=ctx.build_body(target.subscript_index(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        list_prefix = (
            "def A():\n" "    xs = [1, 2, 3]\n" "    del xs[1]\n" "    return xs[1]\n\n"
        )
        dict_prefix = (
            "def A():\n"
            "    d = {'drop': 1, 'keep': 2}\n"
            "    del d['drop']\n"
            "    return d['keep']\n\n"
        )
        guarded_dict_prefix = (
            "def B(flag):\n"
            "    if flag:\n"
            "        d = {'drop': 1, 'keep': 2}\n"
            "    else:\n"
            "        d = {'drop': 3, 'keep': 4}\n"
            "    del d['drop']\n"
            "    return d['keep']\n\n"
        )
        return (
            _call_pair(
                name="subscript_delete_post_state",
                owner_sugar="SubscriptDeleteSugar",
                truthful=list_prefix + "def test_a():\n    assert A() == 3\n",
                lying=list_prefix + "def test_a():\n    assert A() == 2\n",
            ),
            _call_pair(
                name="dict_subscript_delete_post_state",
                owner_sugar="SubscriptDeleteSugar",
                truthful=dict_prefix + "def test_a():\n    assert A() == 2\n",
                lying=dict_prefix + "def test_a():\n    assert A() == 1\n",
            ),
            _call_pair(
                name="guarded_dict_subscript_delete_post_state",
                owner_sugar="SubscriptDeleteSugar",
                truthful=guarded_dict_prefix + "def test_b():\n"
                "    assert B(True) == 2\n"
                "    assert B(False) == 4\n",
                lying=guarded_dict_prefix + "def test_b():\n"
                "    assert B(True) == 2\n"
                "    assert B(False) == 3\n",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return delete_subscript_body(
            receiver=self.receiver,
            receiver_coordinate=self.receiver_coordinate,
            index=self.index,
            site=self.site,
            ctx=ctx,
        )

    def walk_children(self):
        return (self.receiver, self.index)


@dataclass(frozen=True)
class MultiDeleteBindings(FloorValue):
    bindings: tuple[FloorValue, ...]

    def contribution(self):
        return ()

    def extend_scope(self, ctx):
        scoped = ctx
        for binding in self.bindings:
            scoped = binding.extend_scope(scoped)
        return replace(ctx, temporal=scoped.temporal)


@dataclass(frozen=True)
class MultiDeleteSugar(Sugar, role=SugarRole.STATEMENT):
    """Replay a recognized composite ``del`` from left to right."""

    deletions: tuple["RecognizedDeleteAction", ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        targets = DeleteTargetRecognition.statement_targets(site)
        return (
            targets is not None
            and len(targets) > 1
            and any(target.kind is not DeleteTargetKind.NAME for target in targets)
        )

    @classmethod
    def new(cls, site, ctx) -> "MultiDeleteSugar":
        targets = DeleteTargetRecognition.statement_targets(site)
        assert targets is not None
        deletions = tuple(_build_delete_action(target, site, ctx) for target in targets)
        return cls(tuple(deletions), site)

    @classmethod
    def witnesses(cls):
        subscript_prefix = (
            "def A():\n"
            "    xs = [1, 2, 3]\n"
            "    del xs[1], xs[0]\n"
            "    return xs[0]\n\n"
        )
        attribute_prefix = (
            "def B():\n"
            "    class Box:\n"
            "        pass\n"
            "    box = Box()\n"
            "    box.left = 1\n"
            "    box.right = 2\n"
            "    del box.left, box.right\n"
            "    return 3\n\n"
        )
        return (
            _call_pair(
                name="multi_subscript_delete_post_state",
                owner_sugar=cls.__name__,
                truthful=subscript_prefix + "def test_a():\n    assert A() == 3\n",
                lying=subscript_prefix + "def test_a():\n    assert A() == 2\n",
            ),
            _call_pair(
                name="multi_attribute_delete_post_state",
                owner_sugar=cls.__name__,
                truthful=attribute_prefix + "def test_b():\n    assert B() == 3\n",
                lying=attribute_prefix + "def test_b():\n    assert B() == 2\n",
            ),
        )

    def desugar(self, ctx=None) -> Outcome:
        return self._replay(self.deletions, (), ctx)

    def _replay(self, remaining, accumulated, ctx):
        if not remaining:
            return Complete(MultiDeleteBindings(accumulated))
        head, *rest = remaining
        return head.reduce(ctx).and_then(
            lambda binding: self._replay(
                tuple(rest),
                (*accumulated, binding),
                binding.extend_scope(ctx),
            )
        )

    def walk_children(self):
        return tuple(
            child for deletion in self.deletions for child in deletion.walk_children()
        )


@dataclass(frozen=True)
class RecognizedDeleteAction:
    kind: DeleteTargetKind
    site: object = dataclass_field(compare=False)
    name: str | None = None
    receiver: SugarBody | None = None
    receiver_coordinate: str | None = None
    index: SugarBody | None = None

    def reduce(self, ctx) -> Outcome:
        if self.kind is DeleteTargetKind.NAME:
            from sugar_lift_py_tests.sugar.delete_sugar import DeletedBindings

            assert self.name is not None
            return Complete(DeletedBindings((self.name,)))
        if self.kind is DeleteTargetKind.ATTRIBUTE:
            from sugar_lift_py_tests.sugar.attribute_delete_sugar import (
                delete_attribute_body,
            )

            assert self.receiver is not None and self.name is not None
            return delete_attribute_body(
                receiver=self.receiver,
                name=self.name,
                site=self.site,
                ctx=ctx,
            )
        assert self.kind is DeleteTargetKind.SUBSCRIPT
        assert self.receiver is not None and self.index is not None
        return delete_subscript_body(
            receiver=self.receiver,
            receiver_coordinate=self.receiver_coordinate,
            index=self.index,
            site=self.site,
            ctx=ctx,
        )

    def walk_children(self):
        return tuple(
            child for child in (self.receiver, self.index) if child is not None
        )


def _build_delete_action(
    recognized: RecognizedDeleteTarget, site, ctx
) -> RecognizedDeleteAction:
    target = recognized.target
    if recognized.kind is DeleteTargetKind.NAME:
        return RecognizedDeleteAction(
            kind=recognized.kind,
            name=target.name_id(),
            site=site,
        )
    if recognized.kind is DeleteTargetKind.ATTRIBUTE:
        receiver = target.attr_receiver()
        return RecognizedDeleteAction(
            kind=recognized.kind,
            receiver=ctx.build_body(receiver, SugarRole.TERM),
            receiver_coordinate=receiver.dotted_expr_name(),
            name=target.attr_name(),
            site=site,
        )
    receiver = target.subscript_receiver()
    return RecognizedDeleteAction(
        kind=recognized.kind,
        receiver=ctx.build_body(receiver, SugarRole.TERM),
        receiver_coordinate=receiver.dotted_expr_name(),
        index=ctx.build_body(target.subscript_index(), SugarRole.TERM),
        site=site,
    )


def delete_subscript_body(
    *, receiver, receiver_coordinate, index, site, ctx
) -> Outcome:
    return receiver.reduce(ctx).and_then(
        lambda receiver_value: index.reduce(ctx).and_then(
            lambda index_value: receiver_value.delitem(index_value, site).and_then(
                lambda updated: cite_subscript_post_state(
                    receiver_coordinate=receiver_coordinate,
                    receiver=receiver_value,
                    updated=updated,
                    operation="py.delitem",
                    site=site,
                )
            )
        )
    )

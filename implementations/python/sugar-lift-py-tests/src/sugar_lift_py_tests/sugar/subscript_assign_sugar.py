from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, cast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.subscript_store_post_state import (
    cite_subscript_post_state,
)
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class SubscriptAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """One ``receiver[index] = value`` assignment.

    The three expressions are factory-built sources. A named concrete receiver
    rebinds to the cited post-state; a runtime-owned store is a typed effect.
    Slice targets and every other Assign shape remain unowned and panic.
    """

    receiver: SugarBody
    receiver_coordinate: str | None
    structural_root: SugarBody | None
    structural_root_coordinate: str | None
    structural_indices: tuple[SugarBody, ...]
    index: SugarBody
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        targets = site.assign_targets()
        return len(targets) == 1 and targets[0].observed == "Subscript"

    @classmethod
    def from_target(cls, target, value: SugarBody, site, ctx) -> "SubscriptAssignSugar":
        """One door for every subscript-store construction.

        Direct Assign, chained multi-target Assign, and tuple-unpack leaves all
        build through this constructor so structural nested-path fields stay
        required and cannot drift back into a bare TypeError.
        """
        receiver = target.subscript_receiver()
        structural = _structural_target(target, ctx)
        return cls(
            receiver=ctx.build_body(receiver, SugarRole.TERM),
            receiver_coordinate=receiver.dotted_expr_name(),
            structural_root=structural[0] if structural is not None else None,
            structural_root_coordinate=(
                structural[1] if structural is not None else None
            ),
            structural_indices=structural[2] if structural is not None else (),
            index=ctx.build_body(target.subscript_index(), SugarRole.TERM),
            value=value,
            site=site,
        )

    @classmethod
    def new(cls, site, ctx) -> "SubscriptAssignSugar":
        target = site.assign_targets()[0]
        return cls.from_target(
            target,
            ctx.build_body(site.assign_value(), SugarRole.TERM),
            site,
            ctx,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A():\n    xs = [1, 2, 3]\n    xs[1] = 9\n    return xs[1]\n\n"
        comprehension = (
            "def A(source):\n"
            "    values = [item for item in source]\n"
            "    values[0] = 9\n"
            "    return 1\n"
            "\n"
        )
        nested = (
            "def A():\n"
            '    expected = {"fields": [{"name": "old"}]}\n'
            '    expected["fields"][0] = {"name": "new"}\n'
            '    return expected["fields"][0]["name"]\n'
            "\n"
        )
        return (
            _call_pair(
                name="subscript_assign_post_state",
                owner_sugar="SubscriptAssignSugar",
                truthful=prefix + "def test_a():\n    assert A() == 9\n",
                lying=prefix + "def test_a():\n    assert A() == 2\n",
            ),
            _call_pair(
                name="subscript_assign_comprehension_post_state",
                owner_sugar="SubscriptAssignSugar",
                truthful=(
                    comprehension + "def test_a():\n    assert A(source()) == 1\n"
                ),
                lying=comprehension + "def test_a():\n    assert A(source()) == 0\n",
                family="comprehension-setitem",
            ),
            _call_pair(
                name="subscript_assign_nested_post_state",
                owner_sugar="SubscriptAssignSugar",
                truthful=(nested + 'def test_a():\n    assert A() == "new"\n'),
                lying=nested + 'def test_a():\n    assert A() == "old"\n',
                family="nested-subscript-setitem",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        runtime_ctx = cast(Any, ctx)
        structural_root = self.structural_root
        if structural_root is not None:
            return self.value.reduce(runtime_ctx).and_then(
                lambda value: structural_root.reduce(runtime_ctx).and_then(
                    lambda root: self._structural_or_direct(root, value, runtime_ctx)
                )
            )
        return self._desugar_direct(runtime_ctx)

    def _structural_or_direct(self, root, value, ctx):
        from sugar_lift_py_tests.floor import DictValue, ListValue

        if type(root) not in (DictValue, ListValue):
            return self._desugar_direct(ctx)
        return _collect_structural_indices(
            self.structural_indices,
            (),
            root,
            value,
            self.structural_root_coordinate,
            self.site,
            ctx,
        )

    def _desugar_direct(self, ctx):
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: self.index.reduce(ctx).and_then(
                lambda index: self.value.reduce(ctx).and_then(
                    lambda value: receiver.setitem(index, value, self.site).and_then(
                        lambda updated: self._cite_update(receiver, updated)
                    )
                )
            )
        )

    def _cite_update(self, receiver, updated) -> Outcome:
        return cite_subscript_post_state(
            receiver_coordinate=self.receiver_coordinate,
            receiver=receiver,
            updated=updated,
            operation="py.setitem",
            site=self.site,
        )

    def walk_children(self):
        if self.structural_root is not None:
            return (self.structural_root, *self.structural_indices, self.value)
        return (self.receiver, self.index, self.value)


def _structural_target(target, ctx):
    """Describe a nested subscript lvalue from its cited root and index path.

    Nested chains are recognized only through SourceFragment shape accessors
    (``observed`` / ``subscript_receiver`` / ``subscript_index``). Raw
    ``ast.Subscript`` walks are the side door this helper closes.
    """
    if target.observed != "Subscript":
        return None
    if target.subscript_receiver().observed != "Subscript":
        return None

    index_fragments = []
    cursor = target
    while cursor.observed == "Subscript":
        index_fragments.append(cursor.subscript_index())
        cursor = cursor.subscript_receiver()
    root_coordinate = cursor.dotted_expr_name()
    if root_coordinate is None:
        return None
    indices = tuple(
        ctx.build_body(index, SugarRole.TERM) for index in reversed(index_fragments)
    )
    return ctx.build_body(cursor, SugarRole.TERM), root_coordinate, indices


def _collect_structural_indices(
    remaining,
    accumulated,
    root,
    value,
    root_coordinate,
    site,
    ctx,
):
    if not remaining:
        return _rebuild_structural_path(root, accumulated, value, site).and_then(
            lambda updated: _cite_structural_root(root_coordinate, updated)
        )
    head, *tail = remaining
    return head.reduce(ctx).and_then(
        lambda index: _collect_structural_indices(
            tuple(tail),
            (*accumulated, index),
            root,
            value,
            root_coordinate,
            site,
            ctx,
        )
    )


def _rebuild_structural_path(receiver, indices, value, site):
    head, *tail = indices
    if not tail:
        return receiver.setitem(head, value, site)
    return receiver.subscript(head, site).and_then(
        lambda child: _rebuild_structural_path(
            child, tuple(tail), value, site
        ).and_then(lambda updated: receiver.setitem(head, updated, site))
    )


def _cite_structural_root(root_coordinate, updated):
    from sugar_lift_py_tests.floor import ScopeRebind
    from sugar_lift_py_tests.outcome import Complete

    if root_coordinate is None:
        raise AssertionError("structural target was constructed without a root")
    return Complete(ScopeRebind(root_coordinate, updated))

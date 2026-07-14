from __future__ import annotations

from dataclasses import dataclass, field, replace

from .floor_value import FloorValue


@dataclass(frozen=True)
class NamedExpressionValue(FloorValue):
    """The inseparable value and temporal-bind faces of ``(name := value)``."""

    name: str
    assigned_value: FloorValue
    presented_value: FloorValue = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "presented_value", self.assigned_value)

    @classmethod
    def carrying(
        cls, name: str, assigned_value: FloorValue, presented_value: FloorValue
    ) -> "NamedExpressionValue":
        carried = cls(name, assigned_value)
        object.__setattr__(carried, "presented_value", presented_value)
        return carried

    def extend_scope(self, ctx):
        scoped = replace(
            ctx, temporal=ctx.temporal.bind_value(self.name, self.assigned_value)
        )
        return self.presented_value.extend_scope(scoped)

    def contribution(self):
        return self.presented_value.contribution()

    def follow_rest(self, rest, reduce):
        return self.presented_value.follow_rest(rest, reduce)

    def inv_contribution(self):
        return self.presented_value.inv_contribution()

    def post_contribution(self):
        return self.presented_value.post_contribution()

    def to_term(self, *, owner: str):
        return self.presented_value.to_term(owner=owner)

    def callsites(self):
        return self.presented_value.callsites()

    def truth(self, site):
        return self.presented_value.truth(site).and_then(self._carry)

    def binary_conditional(self, then, else_body, ctx=None, site=None):
        bound_ctx = self.extend_scope(ctx)
        return self.presented_value.binary_conditional(
            then, else_body, bound_ctx, site
        ).and_then(self._carry)

    def negate(self):
        return self.presented_value.negate().and_then(self._carry)

    def equals(self, other, site):
        peer = (
            other.presented_value if isinstance(other, NamedExpressionValue) else other
        )
        return self.presented_value.equals(peer, site).and_then(self._carry)

    def less_than(self, other, site):
        peer = (
            other.presented_value if isinstance(other, NamedExpressionValue) else other
        )
        return self.presented_value.less_than(peer, site).and_then(self._carry)

    def predicate_from_left(self, operation: str, left, site):
        if operation != "less_than":
            return self._floor_gap(
                owner="NamedExpressionValue",
                blame=str(site),
                observed=operation,
                requested="predicate from left operand",
                fix="write the named-expression predicate projection",
            )
        return left.less_than(self.presented_value, site).and_then(self._carry)

    def subscript(self, index, site):
        return self.presented_value.subscript(index, site).and_then(self._carry)

    def attribute(self, name, site):
        return self.presented_value.attribute(name, site).and_then(self._carry)

    def _carry(self, presented: FloorValue):
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            NamedExpressionValue.carrying(self.name, self.assigned_value, presented)
        )

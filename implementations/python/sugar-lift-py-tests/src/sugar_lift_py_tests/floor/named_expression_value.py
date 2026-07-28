from __future__ import annotations

from dataclasses import dataclass, field, replace

from .floor_value import FloorValue


@dataclass(frozen=True)
class NamedExpressionValue(FloorValue):
    """The inseparable value and temporal-bind faces of ``(name := value)``.

    Comparison is Floor-owned through the **presented** face: this value only
    contributes its temporal bind via ``_carry``. Left-hand ops dispatch to
    ``presented_value.<op>(other)``; right-hand routing is operator-owned typed
    double-dispatch (``less_than_from_left``, …). No ``predicate_from_left(str)``.
    """

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
        # Root mint is Floor-owned when the reducer has no ambient context yet
        # (function desugar(None) / SourceFile production tooth).
        if ctx is None:
            from sugar_lift_py_tests.context import ReduceContext

            ctx = ReduceContext.root(owner="NamedExpressionValue")
        scoped = replace(
            ctx, temporal=ctx.temporal.bind_value(self.name, self.assigned_value)
        )
        return self.presented_value.extend_scope(scoped)

    def as_expression_statement(self):
        """A bare ``(name := value)`` statement still binds ``name`` afterward."""
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self)

    def contribution(self):
        return self.presented_value.contribution()

    def follow_rest(self):
        return self.presented_value.follow_rest()

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

    # --- left-hand: presented floor owns the comparison ---

    def is_identical(self, other, site):
        return self.presented_value.is_identical(other, site).and_then(self._carry)

    def equals(self, other, site):
        return self.presented_value.equals(other, site).and_then(self._carry)

    def less_than(self, other, site):
        return self.presented_value.less_than(other, site).and_then(self._carry)

    def less_equal(self, other, site):
        return self.presented_value.less_equal(other, site).and_then(self._carry)

    def greater_than(self, other, site):
        return self.presented_value.greater_than(other, site).and_then(self._carry)

    def greater_equal(self, other, site):
        return self.presented_value.greater_equal(other, site).and_then(self._carry)

    # --- right-hand: operator-owned typed double-dispatch (no string door) ---

    def less_than_from_left(self, left, site):
        """``left < (n := e)`` — presented is the RHS; carry the walrus bind."""
        return left.less_than(self.presented_value, site).and_then(self._carry)

    def less_equal_from_left(self, left, site):
        """``left <= (n := e)`` — typed RHS door; not string-admitted."""
        return left.less_equal(self.presented_value, site).and_then(self._carry)

    def greater_than_from_left(self, left, site):
        """``left > (n := e)`` — typed RHS door; not string-admitted."""
        return left.greater_than(self.presented_value, site).and_then(self._carry)

    def greater_equal_from_left(self, left, site):
        """``left >= (n := e)`` — typed RHS door; not string-admitted."""
        return left.greater_equal(self.presented_value, site).and_then(self._carry)

    def equals_from_left(self, left, site):
        """``left == (n := e)`` — typed RHS door; not string-admitted."""
        return left.equals(self.presented_value, site).and_then(self._carry)

    def is_identical_from_left(self, left, site):
        """``left is (n := e)`` — typed RHS door; not string-admitted."""
        return left.is_identical(self.presented_value, site).and_then(self._carry)

    def subscript(self, index, site):
        return self.presented_value.subscript(index, site).and_then(self._carry)

    def attribute(self, name, site):
        return self.presented_value.attribute(name, site).and_then(self._carry)

    def _carry(self, presented: FloorValue):
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            NamedExpressionValue.carrying(self.name, self.assigned_value, presented)
        )

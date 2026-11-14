"""`(name := value)` — walrus expression sugar."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class NamedExprSugar(ConstructedTermSugar):
    """A walrus: binds ``name`` and presents ``value``.

    Tree substitute threads the binding into the enclosing block. At the
    meaning layer the expression evaluates to ``NamedExpressionValue``.

    Enrolled as ``ConstructedTermSugar`` so Compare/Eq parents may carry the
    walrus as an operand through the typed term surface (no spelling side-door).

    ``evaluation`` is the coordinate of this walrus's one evaluation
    (``NamedExpr.substitute``); the value binds under it as well as under the
    name, and every later read substitution rewrote (``EvaluationRef``)
    answers it (temporal choice 1, #7661).  A walrus that was never
    substituted has none and binds the name alone.
    """

    name: str
    value: ConstructedTermSugar
    site: object = dataclass_field(compare=False)
    evaluation: str | None = None

    def __post_init__(self) -> None:
        require_constructed_term_sugar(self.value, owner="NamedExprSugar.value")

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(xs):\n    if (n := len(xs)) > 0:\n        return n\n    return 0\n\n"
        )
        return _call_pair(
            name="named_expr_if",
            owner_sugar="NamedExprSugar",
            truthful=prefix + "def test_a():\n    assert A([1, 2]) == 2\n",
            lying=prefix + "def test_a():\n    assert A([1, 2]) == 0\n",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:named-expr-construction",
            (
                self.occurrence_term(owner=owner),
                str_const(self.name),
                self.value.to_term(owner=owner),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            NamedExpressionValue,
            consume_operands,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halts_at_operand_head,
        )

        # The assigned expression is an operand: a walrus inside it
        # (``(y := (x := 5))``) binds first, through the one operand door, and
        # this walrus assigns the value it presents. Nothing of this walrus
        # is bound before its value halts: a walrus-free value's halt carries
        # the record of where it was evaluated (``halts_at_operand_head``).
        evaluated = halts_at_operand_head(self.value.desugar(ctx), self.value, ctx)
        return evaluated.and_then(
            lambda value: consume_operands(
                lambda assigned: ExitSet.completed(
                    NamedExpressionValue(
                        self.name, assigned, evaluation=self.evaluation
                    )
                ),
                value,
            )
        )


_SUGAR_PACKAGE = "sugar_lift_py_tests.sugar."


def holds_a_walrus(sugar: object) -> bool:
    """Whether evaluating ``sugar`` can run a walrus: a ``NamedExprSugar``
    among the sugars it holds, at any depth (an operand, an argument, a
    display's element, a comprehension's member, a statement's right-hand
    side).

    A sugar that holds none binds nothing while it evaluates, so a halt it
    hands back with no record halted at its own head: the record of where
    it was evaluated is its whole record (``halts_at_operand_head``), and a
    statement that declares it binds nothing before a halt
    (``halts_at_statement_head``) makes a claim that holds
    (``_require_recorded_halts``). One that holds a walrus may have bound
    it before a later operand halted (``x, y = (a := 1), f()``): its
    record-less halt is never given a record that would drop the bind.
    Over-answers ``True`` for a walrus that cannot run before any halt
    (one in a lambda's body).

    It reads what each sugar is -- its compared fields, and the parts of
    them built in this package (an unpack target) -- never what is held out
    of equality as a lookup aid (a site, a callee's body, a frame table):
    a walrus in a callee runs in the callee's frame. An operand a sugar
    holds out of its equality (an ``assert``'s message) is not read.
    """
    from dataclasses import fields, is_dataclass

    from sugar_lift_py_tests.sugar.sugar_base import Sugar

    pending = [sugar]
    seen: set[int] = set()
    while pending:
        item = pending.pop()
        if isinstance(item, NamedExprSugar):
            return True
        if isinstance(item, (tuple, list, frozenset, set)):
            pending.extend(item)
            continue
        if isinstance(item, dict):
            pending.extend(item.values())
            continue
        # A sugar, or a part a sugar is built of (an unpack target, a store
        # place: ``sugar_lift_py_tests.sugar``'s own dataclasses); never a
        # floor value, a context or a source fragment.
        part = (
            is_dataclass(item)
            and not isinstance(item, type)
            and type(item).__module__.startswith(_SUGAR_PACKAGE)
        )
        if not (isinstance(item, Sugar) or part) or id(item) in seen:
            continue
        seen.add(id(item))
        if is_dataclass(item):
            # What the sugar is (its compared fields): never a lookup aid
            # out of its equality (a site, a callee's body, a frame table).
            pending.extend(
                getattr(item, field.name, None)
                for field in fields(item)
                if field.compare
            )
        else:
            pending.extend(vars(item).values() if hasattr(item, "__dict__") else ())
    return False

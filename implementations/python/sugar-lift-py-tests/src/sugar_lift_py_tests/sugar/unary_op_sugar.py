"""A unary operation `<op> <operand>` -- `-x`, `+x`, `~x`, `not x`.

Mirrors BinOpSugar: the node carries its operator, so recognition is the node's;
this routes the reduced operand to the floor method that operator names, and the
value owns the answer (a number folds; an undecided type refuses rather than
inventing ``py.neg`` / identity / ``py.invert``). `not` composes two floor verbs:
Python `not x` is `not bool(x)`, so it takes a decided truthiness and negates
that predicate -- never inventing ``py.truthy`` when ``bool(x)`` is undecided.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair

# Unary operator kind -> the floor method that owns its meaning. Every entry is
# a real FloorValue method; an operator whose value has no such floor reaches
# that value's own loud gap, never a silent default.
UNARYOP_METHODS: dict[str, str] = {
    "USub": "unary_minus",
    "UAdd": "unary_plus",
    "Invert": "bitwise_invert",
}


def refuse_undecided_unary_truth(value, site) -> None:
    """Keep undecided ``bool(operand)`` dispatch loud at the UnaryOp ``not`` producer.

    Python evaluates ``not x`` by first taking ``bool(x)``.  When the operand
    denotes a value but its runtime type is undecided, native ``__bool__`` /
    ``__len__`` may complete or raise (``Series`` / ``NA`` raise ``TypeError`` /
    ``ValueError``).  Emitting ``py.truthy`` invents a total completion; inventing
    an exception identity invents the failure.  Both stay refused until
    source-visible type testimony decides.
    """
    denotes = getattr(value, "denotes_value", None)
    decided = getattr(value, "runtime_type_is_decided", None)
    if not callable(denotes) or not callable(decided):
        return
    if not denotes() or decided():
        return

    from sugar_lift_py_tests.gap.info import GapKind, GapLocus
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner="unary_operation_exception_floor",
        blame=site,
        observed=f"{type(value).__name__} not",
        requested=(
            "source-visible native truth testimony selecting completion "
            "or an authenticated exceptional exit"
        ),
        fix=(
            "preserve the undecided third value at the UnaryOp producer; "
            "resolve native operand types and their __bool__/__len__ bodies "
            "from source, or retain this named refusal without inventing an "
            "exception identity"
        ),
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )


@dataclass(frozen=True)
class UnaryOpSugar(Sugar):
    op_kind: str
    operand: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # `not` composes truth+negate: `if not (z == 1)` holds exactly when z != 1.
        prefix = "def A(z):\n    if not (z == 1):\n        return z\n    return 0\n\n"
        return _call_pair(
            name="unaryop_not_return",
            owner_sugar="UnaryOpSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        operand = self.operand.desugar(ctx)
        if self.op_kind == "Not":
            # `not x` = not bool(x): only a decided truthiness may be negated.
            def project_not(value):
                refuse_undecided_unary_truth(value, self.site)
                return value.truth(self.site)

            return operand.and_then(project_not).and_then(
                lambda predicate: predicate.negate()
            )
        method = UNARYOP_METHODS[self.op_kind]
        return operand.and_then(lambda v: getattr(v, method)(self.site))

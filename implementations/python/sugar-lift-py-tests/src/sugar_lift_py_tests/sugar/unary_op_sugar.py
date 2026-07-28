"""A unary operation `<op> <operand>` -- `-x`, `+x`, `~x`, `not x`.

Mirrors BinOpSugar: the node carries its operator, so recognition is the node's;
this routes the reduced operand to the floor method that operator names, and the
value owns the answer (a number folds; an undecided type refuses rather than
inventing ``py.neg`` / identity / ``py.invert``).

Python semantic law for ``not`` (distinct from BoolOp):

  ``result = not value``  means  ``result = not bool(value)``.

  a. ``bool(value)`` MAY halt — ``__bool__`` / ``__len__`` can raise a
     source-authenticated exception type; that halt is a real exceptional face.
  b. ONLY the completed truth face is negated — a halted truth has no bool to
     flip; ``Complete.and_then`` / ``ExitSet.sequence`` skip halted tails.
  c. The result is ALWAYS a bool (``True``/``False``), never the operand.
     Contrast BoolOp (#6595): ``a and b`` returns an operand.
  d. Exception type originates in the truth dispatch floor, never from an
     enclosing ``pytest.raises`` expectation (the boundary verifies, it cannot
     create).

Formal operands ride the existing ``NativeOperationExitCarrierV1`` via the
``unary_truth`` adapter (#6583 three-way resolution; #6591 caller discharge).
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

    Formals are not refused here: their type arrives at caller discharge on the
    existing ``NativeOperationExitCarrierV1`` (``unary_truth``).

    ``CallSiteValue`` is the established exception: its ``truth`` floor already
    emits ``PredicateValue(py.truthy(term))`` over the authenticated call term
    (#4993 / #5147).  That is coordinate testimony, not an invented native
    ``bool`` completion.  Refusing it here collapses installed-source manager
    derivation (``pytest.raises`` ``__exit__`` uses ``not self.…`` over call
    coordinates) and zeroes every producer → ExitSet → assertion-boundary route.
    """
    if getattr(value, "formal_coordinate", None) is not None:
        return

    denotes = getattr(value, "denotes_value", None)
    decided = getattr(value, "runtime_type_is_decided", None)
    if not callable(denotes) or not callable(decided):
        return
    if not denotes() or decided():
        return

    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

    # Authenticated call coordinates own a lawful truth floor; do not refuse them.
    if isinstance(value, CallSiteValue):
        return

    from sugar_source_tree.panic import SugarNotWritten

    raise SugarNotWritten(
        blame=site,
        owner="unary_operation_exception_floor",
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
            # `not x` = not bool(x): only a completed truthiness may be negated.
            def project_not(value):
                from sugar_lift_py_tests.floor.block_value import BlockValue
                from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
                from sugar_lift_py_tests.floor.none_value import NoneValue
                from sugar_lift_py_tests.floor.return_value import ReturnValue

                # Method calls with authenticated bodies
                # (``not self._check_type(e)`` / ``not self.matches(e)``) dig
                # the body before truth refusal. Opaque CallSiteValue is neither
                # bool nor TypeError — dig is the sole door for source-visible
                # method returns on returned-manager exit faces.
                if isinstance(value, CallSiteValue) and value.body is not None:
                    dug = value._dig_floor_or_none(
                        ctx, owner="UnaryOpSugar.not method body"
                    )
                    if dug is not None:
                        value = dug
                # Method bodies dig to BlockValue; truth rides the returned floor
                # (side-effect assigns precede the return).
                if isinstance(value, BlockValue) and not value.fall_through:
                    returns = [
                        statement.value
                        for statement in value.statements
                        if isinstance(statement, ReturnValue)
                    ]
                    if len(returns) == 1:
                        value = returns[0]

                formal_coordinate = getattr(value, "formal_coordinate", None)
                if formal_coordinate is not None:
                    # Defer bool(value) until authenticated actuals arrive.
                    # Second operand is an inert unit (null coordinate) so the
                    # existing two-slot carrier can record a one-operand op.
                    from sugar_lift_py_tests.caller_parameter_contract import (
                        NativeOperationExitCarrierV1,
                    )

                    return NativeOperationExitCarrierV1.mint(
                        site=self.site,
                        operator="unary_truth",
                        operands=(value, NoneValue()),
                        coordinates=(formal_coordinate, None),
                    )

                refuse_undecided_unary_truth(value, self.site)
                return value.truth(self.site)

            # Negate only completed truth faces.  Complete(RaiseValue) and
            # Halted exits bypass this step (no bool to flip).
            return operand.and_then(project_not).and_then(
                lambda predicate: predicate.negate()
            )
        method = UNARYOP_METHODS[self.op_kind]
        return operand.and_then(lambda v: getattr(v, method)(self.site))

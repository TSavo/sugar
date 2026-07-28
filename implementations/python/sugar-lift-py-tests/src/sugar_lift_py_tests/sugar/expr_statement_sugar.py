"""An expression in statement position -- `<expr>` on its own line.

The census's #2 family, and mostly docstrings. A bare expression STATES no
fact: its value reduces (the recursion -- a docstring to its string, a method
call to its coordinate) and then contributes nothing to the record. What DOES
ride is an effect: an Incomplete outcome propagates itself through and_then, so
`raise`-bearing or unresolvable expressions stay red testimony, never dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import inert_statement_return_witness


@dataclass(frozen=True)
class ExprStatementSugar(Sugar):
    value: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return inert_statement_return_witness(
            name="expr_statement_inert",
            owner_sugar="ExprStatementSugar",
            statement='"""a docstring"""',
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.sugar.warning_observation_producer import (
            project_warning_observation,
        )

        # Reduce the value (effects propagate via and_then). A completed value
        # in statement position STATES nothing -- but it is not erased: it rides
        # as a record entry, contributing only what its own floor defaults give
        # (a docstring: nothing; a call coordinate: its callEdge cue, and its
        # visibility to the effect router -- dropping it made `with raises(E):
        # do_thing()` claim a FALSE absence, since the router could no longer
        # see that a halt might hide behind the unresolved call).
        #
        # One statement value is more than a coordinate: an authenticated
        # `warnings.warn(msg, Category)` occurrence. It rides as the warning
        # testimony the completed-face boundary consumes. The projection lives
        # HERE rather than in CallSiteSugar because statement position is what
        # makes it an occurrence -- a warn call read as an expression operand
        # would be a value, and this record entry is not one. An occurrence
        # that does not authenticate keeps its ordinary call coordinate and the
        # boundary names it unresolved; it is never read as "no warning".
        return self.value.desugar(ctx).and_then(
            lambda value: Complete(
                BlockValue(
                    (project_warning_observation(value) or value,),
                    can_fall_through=True,
                )
            )
        )

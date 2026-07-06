from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import SupportValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import inert_statement_return_witness
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing, SugarWitnessPair


@dataclass(frozen=True)
class CommentSugar(Sugar, role=SugarRole.STATEMENT):
    """A comment: a docstring / bare-string statement. It is inert metadata -- present
    in the source and doing nothing: no first-order logic, no scope, no effect. The
    factory composes a CommentSugar, which classifies the node as Support in the source
    audit: it always completes and never constrains. Neither a typed effect nor
    silently dropped. A comment is a STATEMENT (a member of a block); its OUTCOME is Support --
    the role is the dispatch key, not the category."""

    @classmethod
    def owns(cls, fragment) -> bool:
        if fragment.observed != "Expr":
            return False
        terms = fragment.terms()
        return (
            len(terms) == 1
            and terms[0].observed == "PrimitiveLiteral"
            and isinstance(terms[0].literal_value(), str)
        )

    @classmethod
    def witnesses(cls) -> tuple[NotVerdictBearing, SugarWitnessPair]:
        return (
            NotVerdictBearing(
                sugar_name=cls.__name__,
                floor_name="SupportValue",
                reason="comments are inert source support",
            ),
            inert_statement_return_witness(
                name="comment_support_return",
                owner_sugar=cls.__name__,
                statement="'inert note'",
            ),
        )

    @classmethod
    def build(cls, fragment, ctx) -> "CommentSugar":
        if not cls.owns(fragment):
            raise TypeError("CommentSugar built a non-comment statement")
        return cls()

    def _build(self, ctx=None) -> Outcome:
        # A comment desugars to Support and ALWAYS completes: no term, no binding, no
        # scope -- it contributes nothing to the first-order logic.
        return Complete(SupportValue())

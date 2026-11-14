"""A read rewritten to a reference to one statement's evaluation.

Temporal choice 1 (#7661): substitution rewrites a read of ``x`` after
``x += e`` or ``(x := e)`` to ``EvaluationRef(<the evaluation's coordinate>)``,
never to the bare name. The statement (or walrus) binds its completed value
under that coordinate at reduce, and the read answers it: the value is not
looked up by spelling. A comprehension's element and conditions read a target
name the same way: the comprehension binds each member under the generator's
(or the target leaf's) coordinate (``ComprehensionSugar._member_ctx``).

A write of the name that substitution does not see (a dynamic unpack, a
``raises ... as``, a live loop's next item) still binds the name. The read is
then whichever of the two was bound last: the evaluation, or a later write of
the name.

Where this temporal never received the evaluation, a walrus's reference reads
the walrus's substituted value (``unevaluated``), the read it was before: a
walrus nested in an operand that does not carry its bind out to the statement
(an assignment's right-hand side, a call argument), or in a comprehension
(refused at construction, so no element evaluates it). The name is not read
there: it may hold a write older than the walrus. Otherwise (``x += e`` in a
nested frame, a reduction of the expression alone) the read is the name read
it always was.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


@dataclass(frozen=True)
class EvaluationRefSugar(ConstructedTermSugar):
    evaluation: str
    name: str
    site: object = dataclass_field(compare=False)
    unevaluated: object = None

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:evaluation-reference",
            (self.occurrence_term(owner=owner), str_const(self.evaluation)),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        temporal = getattr(ctx, "temporal", None) if ctx is not None else None
        evaluated = False
        if temporal is not None:
            latest = temporal.latest(self.evaluation, self.name)
            if latest is not None and latest.name == self.evaluation:
                from sugar_lift_py_tests.outcome import Complete

                return Complete(latest.value)
            evaluated = temporal.value_if_bound(self.evaluation) is not None
        if self.unevaluated is not None and not evaluated:
            return self.unevaluated.desugar(ctx)
        from sugar_lift_py_tests.sugar.name_sugar import NameSugar

        return NameSugar(name=self.name, site=self.site).desugar(ctx)

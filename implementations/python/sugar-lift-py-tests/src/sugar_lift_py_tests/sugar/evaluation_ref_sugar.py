"""A read rewritten to a reference to one statement's evaluation.

Temporal choice 1 (#7661): substitution rewrites a read of ``x`` after
``x += e`` or ``(x := e)`` to ``EvaluationRef(<the evaluation's coordinate>)``,
never to the bare name. The statement (or walrus) binds its completed value
under that coordinate at reduce, and the read answers it: the value is not
looked up by spelling. After ``a, b = f()`` a read of ``a`` is a reference to
``a``'s projection of the statement's coordinate (``projection_key``), bound
by the unpack at reduce.

A comprehension's element and conditions read a target name the same way
(``member``): the comprehension binds every member, finite or symbolic, under
the generator's (or the target leaf's) coordinate before any read of it
(``ComprehensionSugar._member_ctx``, ``ComprehensionSugar._symbolic_member_ctx``).
A member reference reads that coordinate only. It never reads the name, so a
binding of the same spelling by an enclosing statement cannot leak in, and a
member reference whose coordinate is unbound is a construction panic, not a
name read.

``with pytest.raises(...) as e`` and ``except ... as e`` bind no name at
reduce: substitution rewrites a read of ``e`` to the statement's observation
(``ObservationRef``) or the handler's effect (``EffectRef``), one slot per
evaluation (``Statement._evaluation_slot``).

A live loop's body is constructed once and reduced once per item, so the
coordinate a body statement was given at construction names it for every
item. At reduce the key is that coordinate qualified by the live iterations
the reduction is inside (``evaluation_here``): each item's evaluation is its
own, as each unrolled iteration's is (#7886). A live loop also reads a name
it carries through its header: the value the item began with, bound per item
by ``LoopRecurrenceSugar`` under the header's key.

For a statement's reference, a write of the name that substitution does not
see (an unsubstituted unpack) still binds the name. The read is then
whichever of the two was bound last: the evaluation, or a later write of the
name.

Where this temporal never received the evaluation, a walrus's reference reads
the walrus's substituted value (``unevaluated``), the read it was before: a
walrus nested in an operand that does not carry its bind out to the statement
(an assignment's right-hand side, a call argument), or in a comprehension
(refused at construction, so no element evaluates it). The name is not read
there: it may hold a write older than the walrus. Otherwise (``x += e`` in a
nested frame, a reduction of the expression alone, a live loop reduced as its
recurrence and not per item) the read is the name read it always was.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


def evaluation_here(evaluation: str) -> str:
    """The key ``evaluation`` is bound and read under in the reduction running
    now: the construct-time key, qualified by the live loop iterations around
    it (``occurrence.live_iterations``). Outside every live iteration it is the
    construct-time key itself.

    Only a statement's evaluation (``EVALUATION_PREFIX``: ``x += e``, a
    walrus, an unpack's projections, a live loop's header) is qualified: it is
    written once per item and read across the statements of the item.  A
    comprehension's member coordinate is bound and read inside one evaluation
    of the comprehension, so it keeps its coordinate.
    """
    from sugar_lift_py_tests.occurrence import live_iterations
    from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX

    if not evaluation.startswith(EVALUATION_PREFIX):
        return evaluation
    segments = live_iterations()
    if not segments:
        return evaluation
    return f"{evaluation}@{'/'.join(segments)}"


@dataclass(frozen=True)
class EvaluationRefSugar(ConstructedTermSugar):
    evaluation: str
    name: str
    site: object = dataclass_field(compare=False)
    unevaluated: object = None
    member: bool = False

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
        if self.member:
            return self._member(temporal)
        evaluated = False
        if temporal is not None:
            key = evaluation_here(self.evaluation)
            latest = temporal.latest(key, self.name)
            if latest is not None and latest.name == key:
                from sugar_lift_py_tests.outcome import ExitSet

                return ExitSet.completed(latest.value)
            evaluated = temporal.value_if_bound(key) is not None
        if self.unevaluated is not None and not evaluated:
            return self.unevaluated.desugar(ctx)
        from sugar_lift_py_tests.sugar.name_sugar import NameSugar

        return NameSugar(name=self.name, site=self.site).desugar(ctx)

    def _member(self, temporal) -> Outcome:
        """A comprehension member's coordinate, bound by the comprehension
        before any read; unbound, the read panics and never reads the name.
        The coordinate is bound and read inside one evaluation of the
        comprehension, so it is not qualified (``evaluation_here``)."""
        from sugar_lift_py_tests.outcome import ExitSet

        bound = (
            temporal.value_if_bound(self.evaluation) if temporal is not None else None
        )
        if bound is None:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="EvaluationRefSugar",
                blame=self.site,
                observed=(
                    f"comprehension member `{self.name}` read with its "
                    f"coordinate {self.evaluation} unbound"
                ),
                requested="the member bound by its comprehension before the read",
                fix=(
                    "reduce the read inside its ComprehensionSugar, which binds "
                    "every member under its coordinate"
                ),
            )
        return ExitSet.completed(bound)

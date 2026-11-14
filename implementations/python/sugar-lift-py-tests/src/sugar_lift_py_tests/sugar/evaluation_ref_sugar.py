"""A read rewritten to a reference to one statement's evaluation.

Temporal choice 1 (#7661): substitution rewrites a read of ``x`` after
``x += e`` or ``(x := e)`` to ``EvaluationRef(<the evaluation's coordinate>)``,
never to the bare name. The statement (or walrus) binds its completed value
under that coordinate at reduce, and the read answers it: the value is not
looked up by spelling. After ``a, b = f()`` a read of ``a`` is a reference to
``a``'s projection of the statement's coordinate (``projection_key``), bound
by the unpack at reduce. After ``y = e`` (whatever ``e`` is; ``y: T = e``; an
unrolled ``for y in [e]``'s iteration), a read of ``y`` is a reference to
``y``'s projection of the assignment's coordinate, bound by the assignment at
reduce (``Assign.target_evaluations``): the value ``e`` had at ``y = e``,
never ``e`` evaluated again where ``y`` is used.

A nested ``def`` reads an enclosing local through a captured coordinate its
call binds from the enclosing scope's binding at the call
(``FunctionDef._captured_bindings``, ``Call._closure_cells``), never this
reference read in the callee's frame.

A comprehension's element and conditions read a target name the same way
(``member``): the comprehension binds every member, finite or symbolic, under
the generator's (or the target leaf's) coordinate before any read of it
(``ComprehensionSugar._member_ctx``, ``ComprehensionSugar._symbolic_member_ctx``).
A member reference reads that coordinate only. It never reads the name, so a
binding of the same spelling by an enclosing statement cannot leak in, and a
member reference whose coordinate is unbound is a construction panic, not a
name read.

A lambda the comprehension stores in what it produces (``fs = [lambda: x for
x in xs]; fs[0]()``) is called after the comprehension, and Python reads the
comprehension's cell at call time: the final member. Its body's read is a
member reference to the final member coordinate
(``sugar_source_tree.nodes.final_member_coordinate``), carried in the lambda
by substitution as every other enclosing binding it reads
(``nodes._closure_cell_scope``). The comprehension binds that coordinate
before the element is reduced (``ComprehensionSugar._final_member_ctx``, the
last finite member; ``ComprehensionSugar._symbolic_final_ctx``, the final
member of a symbolic iterable), and the reference reads it as it reads any
member coordinate. A comprehension that dissolves at substitution carries the
last member's projection itself.

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

A walrus's reference (``walrus``) resolves through the key only. A walrus
nested in a larger expression carries its bind out to the enclosing statement
on the value, through the one operand door every operand consumer uses
(``named_expression_value.consume_operands``), and a
comprehension's element writes it per member, so a temporal that never
received the key is one where the walrus never completed, or where its bind
was not carried: the read is refused there by name. The name is never read in
its place (it may hold a write older than the walrus) and the walrus's value
is never evaluated again. Otherwise (a lambda's body called outside the scope
that built it, a reduction of the expression alone, a live loop reduced as
its recurrence and not per item) the read is the name read it always was.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
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
    member: bool = False
    walrus: bool = False
    # A generator expression's walrus: it writes when the generator is
    # consumed, not where it is made.
    deferred: bool = False

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

    def desugar(self, ctx: object = None) -> ExitSet:
        temporal = getattr(ctx, "temporal", None) if ctx is not None else None
        if self.member:
            return self._member(temporal)
        if temporal is not None:
            key = evaluation_here(self.evaluation)
            latest = temporal.latest(key, self.name)
            if latest is not None and latest.name == key:
                from sugar_lift_py_tests.outcome import ExitSet

                return ExitSet.completed(latest.value)
            if self.walrus and temporal.value_if_bound(key) is None:
                return self._unreached_walrus()
        elif self.walrus:
            return self._unreached_walrus()
        from sugar_lift_py_tests.sugar.name_sugar import NameSugar

        return NameSugar(name=self.name, site=self.site).desugar(ctx)

    def _unreached_walrus(self) -> ExitSet:
        """A walrus's reference whose key this temporal never received: the
        walrus never completed here, or its bind was not carried out of the
        operand that holds it.  Refused by name: the name may hold a write
        older than the walrus, and the walrus is never evaluated again.

        A ``deferred`` walrus is in a generator expression: it writes when the
        generator is consumed, and nothing here consumed it with its write
        carried out.  Whether it ran before this read is undecided, and the
        read is refused by that name (``SugarNotWritten``)."""
        if self.deferred:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner="EvaluationRefSugar",
                blame=self.site,
                observed=(
                    f"read of `{self.name}` after a generator expression whose "
                    f"walrus writes it (evaluation {self.evaluation}): the "
                    "write happens when the generator is consumed"
                ),
                requested="the walrus's write carried out of the generator's consumer",
                fix=(
                    "carry the write of a generator consumed in this frame "
                    "out of its consumer; an unconsumed generator never wrote"
                ),
            )
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="EvaluationRefSugar",
            blame=self.site,
            observed=(
                f"read of `{self.name}` after its walrus with the walrus's "
                f"evaluation {self.evaluation} unbound"
            ),
            requested="the walrus's completed value bound under its key",
            fix=(
                "carry the walrus's bind out of the operand that holds it to "
                "the enclosing statement: the consumer of that operand hands "
                "it to the one operand door (consume_operands)"
            ),
        )

    def _member(self, temporal) -> ExitSet:
        """A comprehension member's coordinate (or, read by a lambda the
        comprehension stores, its final member coordinate), bound by the
        comprehension before any read; unbound, the read panics and never
        reads the name.
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

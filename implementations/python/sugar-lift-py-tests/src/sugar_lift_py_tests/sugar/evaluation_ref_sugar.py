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
(``ComprehensionSugar._member_unpack``,
``ComprehensionSugar._symbolic_member_ctx``).
A member reference reads that coordinate only. It never reads the name, so a
binding of the same spelling by an enclosing statement cannot leak in, and a
member reference whose coordinate is unbound is a construction panic, not a
name read.

A read inside a comprehension of a name a walrus in it writes is a member
reference too (``recurrence``): to the comprehension's running value of the
name, which the comprehension binds to the prior binding before the first
member and rebinds after every element, key, value and condition that writes
it (``ComprehensionSugar._written``), so each member reads the previous
member's write.  Where it bound no running value the read is refused by name
(``SugarNotWritten``), never read as the binding before the comprehension.
Within one element, key, value or condition, a read after a walrus of the
name in evaluation order (``(y := f(x)) and y > 0``) is a reference to that
walrus's key instead (``nodes._scope_after``), bound in the member only by
the consumer that evaluates the read after the walrus
(``named_expression_value.written_by``); unbound, it is refused by name.

Every lambda in a comprehension -- stored (``fs = [lambda: x for x in xs];
fs[0]()``), called in place (``sorted(ys, key=lambda v: v + x)``), handed to
a call, bound by a walrus (``[(g := lambda: x) for x in xs if g()]; g()``) --
may be called while the comprehension runs or after it, and Python reads the
comprehension's cell at call time.  Its shape does not say when it is
called, so every one is read the same way (``nodes._escaping_at_the_call``).
Its body's read names both coordinates (``current``: the member's; the
evaluation: its final one, ``sugar_source_tree.nodes.final_member_coordinate``,
which the comprehension binds before the element is reduced:
``ComprehensionSugar._final_member_ctx``, the last finite member;
``ComprehensionSugar._symbolic_final_ctx``, the final member of a symbolic
iterable), and the cell is read at each call: inside the
evaluation of the comprehension that made the lambda -- the evaluation the
lambda carries is the one running (``ComprehensionSugar._evaluation_ctx``) --
the member current at the call; with no evaluation of the comprehension
running, the final member the lambda carries; refused by name otherwise.
Never the member current where the lambda was made.  A lambda that escapes a
generator expression, through a walrus (``list((g := lambda: x) for x in
xs)``) or yielded (``list(lambda: x for x in xs)``, ``([lambda: x for _ in
ys] for x in xs)``), is read the same way: a run is a consumption of the
generator, and the final member
is carried only where the generator is consumed whole in place
(``ComprehensionSugar.final_member``); a call after a generator consumed
anywhere else (stored, ``next``, a ``for``, ``any``) is refused by name.

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
by ``LoopRecurrenceSugar`` under the header's key, and its target through the
target's key, bound per item to the item's projection. A read inside the
items of a live loop nested in the item of the write reads the write's own
item (``evaluation_read_here``).

A live loop publishes each name its items write that it does not carry
under a binding coordinate (a name first bound in the loop, a module
binding) through its post-loop key (``nodes._live_loop_publication``) and
binds that key, outside every item, to the latest write of the name on the
path the loop left by (``LoopRecurrenceSugar._post_loop_writes``), as it
binds its target's and header's keys after its last item: a read after the
loop reads it through the key.

Every reference resolves through its key only.  A key the temporal never
received is refused by name (``_unbound``, ``construction_panic_gap`` naming
the key): the name is never read in its place, whatever the name holds (a
write substitution did not see, a formal of the same spelling, nothing).

A read of what a store put in a place (``place``: ``o.x`` after ``o.x = v``,
``d`` after ``d[k] = v``) resolves through the store's key only: the store
binds the value it stored there, and the read never evaluates ``v`` again.
A place has no name, so where the key is unbound the read is refused.  A
read of the whole object ``o`` after ``o.x = v`` is the object's own read
(its assignment's key) with every such field read folded over it
(``ReceiverFieldStoreStateSugar``): its latest state, never the object as it
was before the store.

A walrus's reference (``walrus``) resolves through the key only. A walrus
nested in a larger expression carries its bind out to the enclosing statement
on the value, through the one operand door every operand consumer uses
(``named_expression_value.consume_operands``), and a
comprehension's element writes it per member, so a temporal that never
received the key is one where the walrus never completed, or where its bind
was not carried: the read is refused there by name. The name is never read in
its place (it may hold a write older than the walrus) and the walrus's value
is never evaluated again.
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


def evaluation_read_here(temporal, evaluation: str) -> str:
    """The key a read of ``evaluation`` reads in the reduction running now.

    An evaluation is bound qualified by the live items around its write
    (``evaluation_here``).  A read sits inside those items, and possibly
    inside the items of live loops nested in them: ``for row in rows: for c
    in cols: f(row)`` reads ``row``'s per-item key inside an item of the
    inner loop, where it was bound inside an item of the outer one only.
    So the read takes the innermost qualification of its own live items
    under which the evaluation is bound: the item of the write it reaches.
    A statement is written at one depth of live items only, so no other
    write can answer.  With none bound, the key qualified fully, as before.
    """
    from sugar_lift_py_tests.occurrence import live_iterations
    from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX

    if temporal is None or not evaluation.startswith(EVALUATION_PREFIX):
        return evaluation
    segments = live_iterations()
    for depth in range(len(segments), 0, -1):
        key = f"{evaluation}@{'/'.join(segments[:depth])}"
        if temporal.value_if_bound(key) is not None:
            return key
    if not segments or temporal.value_if_bound(evaluation) is not None:
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
    # A member reference to a comprehension's running value of a name a
    # walrus in it writes (``ComprehensionSugar.walrus_recurrence``).
    recurrence: bool = False
    # A read of what a store put in a place (``o.x`` after ``o.x = v``, ``d``
    # after ``d[k] = v``): resolves through the key only; ``name`` is a label.
    place: bool = False
    # A name bound to a lambda, passed to a callee that runs it during the
    # call (``Call._carry_argument_cells``): ``((name, coordinate cid,
    # sugar), ...)``, the caller's binding at the call of each enclosing local
    # the lambda reads.  Read here, where the argument is evaluated, and
    # carried on the lambda value (``carry_captured_values``).
    captured: tuple = dataclass_field(default=(), compare=False)
    # A comprehension cell read at the call by a lambda made in the
    # comprehension: the member coordinate; ``evaluation`` is its final
    # coordinate.
    current: str | None = None

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
        if not self.captured:
            return self._read(ctx)
        from sugar_lift_py_tests.sugar.call_site_sugar import carry_captured_values

        return self._read(ctx).and_then(
            lambda value: ExitSet.completed(
                carry_captured_values(value, self.captured, ctx)
            )
        )

    def _read(self, ctx) -> ExitSet:
        """The value bound under the key, read where the reduction runs
        (``evaluation_read_here``).  The key only: a write of the name is
        never read in its place, and a key this temporal never received is
        refused by name (``_unbound``)."""
        temporal = getattr(ctx, "temporal", None) if ctx is not None else None
        if self.member:
            return self._member(temporal)
        if self.place:
            return self._place(temporal)
        key = (
            self.evaluation
            if temporal is None
            else evaluation_read_here(temporal, self.evaluation)
        )
        bound = temporal.value_read(key) if temporal is not None else None
        if bound is not None:
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(bound)
        if self.walrus:
            return self._unreached_walrus()
        self._unbound(key)

    def _unbound(self, key: str):
        """A statement's reference whose key this temporal never received:
        the statement never completed here, or the read was reduced where
        nothing bound its key (a frame reduced apart from the block that ran
        the statement; a live loop reduced as its recurrence, not per item).
        Refused by name, naming the key: the name is never read in its place
        (it may hold nothing, or a write older than the statement), and the
        statement is never evaluated again."""
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="EvaluationRefSugar",
            blame=self.site,
            observed=(
                f"read of `{self.name}` with its evaluation {key} unbound "
                f"(construct-time key {self.evaluation})"
            ),
            requested="the statement's completed value bound under its key",
            fix=(
                "reduce the read after the statement in the block that ran it, "
                "or bind the key where the read is reduced; never read the "
                "name in its place"
            ),
        )

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

    def unwritten_recurrence(self, ctx) -> bool:
        """True for a ``recurrence`` reference whose running value ``ctx``
        does not hold: its read would be refused by name."""
        if not self.recurrence:
            return False
        temporal = getattr(ctx, "temporal", None) if ctx is not None else None
        return temporal is None or temporal.value_if_bound(self.evaluation) is None

    def _place(self, temporal) -> ExitSet:
        """What a store put in a place, read through the store's key: the
        value the store completed with (``KeyedStoreSugar``,
        ``ContainerMutationStatementSugar``), never the stored expression
        evaluated again.  A place has no name to read in its stead, so a key
        this temporal never received is refused: the store never completed
        here, or the read was carried out of the frame that ran it."""
        from sugar_lift_py_tests.outcome import ExitSet

        bound = (
            temporal.value_if_bound(evaluation_here(self.evaluation))
            if temporal is not None
            else None
        )
        if bound is None:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="EvaluationRefSugar",
                blame=self.site,
                observed=(
                    f"read of `{self.name}` with its store's evaluation "
                    f"{self.evaluation} unbound"
                ),
                requested="the store's completed value bound under its key",
                fix=(
                    "reduce the read after the store statement in the frame "
                    "that ran it; the store binds what it stored under its key"
                ),
            )
        return ExitSet.completed(bound)

    def _member(self, temporal) -> ExitSet:
        """A comprehension member's coordinate (or, read by a lambda the
        comprehension stores, its final member coordinate), bound by the
        comprehension before any read; unbound, the read panics and never
        reads the name.
        The coordinate is bound and read inside one evaluation of the
        comprehension, so it is not qualified (``evaluation_here``).

        A ``recurrence`` reference reads the comprehension's running value
        of a name its walrus writes.  Unbound, no write and no one plain
        prior binding of the name reaches the read in evaluation order, and
        the read is refused by name (``SugarNotWritten``): it is never the
        binding before the comprehension read again."""
        from sugar_lift_py_tests.outcome import ExitSet

        if self.current is not None:
            return self._cell_at_the_call(temporal)
        bound = (
            temporal.value_if_bound(self.evaluation) if temporal is not None else None
        )
        if bound is None and self.recurrence:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner="EvaluationRefSugar",
                blame=self.site,
                observed=(
                    f"read of `{self.name}` inside a comprehension whose walrus "
                    f"writes it, with its running value {self.evaluation} "
                    "unbound: the name had no one plain binding before the "
                    "comprehension, the order of a read and a walrus of it "
                    "within one element, key, value or condition is not "
                    "decided, it is in a lambda or a generator expression, or "
                    "the members run over a symbolic iterable and the read "
                    "needs an earlier member's write"
                ),
                requested=(
                    "the write of the previous member, or the binding before "
                    "the comprehension for the first, reaching the read"
                ),
                fix=(
                    "carry the recurrence of the members' writes to this read; "
                    "never read the binding before the comprehension in its place"
                ),
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

    def _cell_at_the_call(self, temporal) -> ExitSet:
        """The comprehension cell a lambda made in the comprehension reads,
        as it is at this call.  The call is placed by the evaluation of the
        comprehension running at it (``comprehension_evaluation_coordinate``)
        and the one the lambda carries (``lambda_evaluation_coordinate``):

        - the same evaluation: the call is inside the comprehension that made
          the lambda, and reads the member current at the call (``current``);
        - none running: the call is after the comprehension, and reads the
          final member the lambda carries (``evaluation``);
        - any other: the call is placed inside neither, and is refused by
          name (``SugarNotWritten``), as is a placed read whose member is not
          bound.  The member current where the lambda was made is never
          read."""
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_source_tree.nodes import (
            comprehension_evaluation_coordinate,
            lambda_evaluation_coordinate,
        )
        from sugar_source_tree.panic import SugarNotWritten

        running = None
        if temporal is not None:
            running = temporal.value_if_bound(
                comprehension_evaluation_coordinate(self.current)
            )
        if running is None:
            final = None
            if temporal is not None:
                final = temporal.value_if_bound(self.evaluation)
            if final is not None:
                return ExitSet.completed(final)
            placement = (
                "after the comprehension, with no final member carried (a "
                "generator not consumed whole in place: the member at the "
                "call depends on how far it has been consumed)"
            )
        else:
            made = temporal.value_if_bound(lambda_evaluation_coordinate(self.current))
            if made is running:
                current = temporal.value_if_bound(self.current)
                if current is not None:
                    return ExitSet.completed(current)
                placement = "inside the evaluation that made it, with no member"
            else:
                placement = (
                    "inside an evaluation it was not made in, or by a lambda "
                    "that carries none"
                )
        raise SugarNotWritten(
            owner="EvaluationRefSugar",
            blame=self.site,
            observed=(
                f"call of a lambda that reads comprehension cell `{self.name}` "
                f"(member {self.current}) placed {placement}"
            ),
            requested=(
                "the call inside the evaluation that made the lambda (the "
                "current member) or after the comprehension (the final member)"
            ),
            fix=(
                "place the call inside or after the comprehension the lambda "
                "escapes; never read the member current where it was made"
            ),
        )

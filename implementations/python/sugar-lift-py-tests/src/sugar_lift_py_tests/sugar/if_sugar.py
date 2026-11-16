"""`if <test>: <then> [else: <else>]` -- the GUARD half of an if statement.

An if splits the universe. Its condition desugars to a predicate; each branch's
stated facts are then GUARDED by the branch polarity, and a guarded fact IS an
implication (`InvValue.guarded`): `if c: assert P` emits `c -> P`, `if c: return
E` emits the guarded post `c -> out == E`, `if c: raise X` emits the raise
effect red under `c`. That is the whole of `if`'s MEANING.

The other half of an if -- what a name BINDS to after the branch (the phi
`x = then_x if c else else_x`) -- is temporal, and lives entirely in
`If.substitute` as an `IfExp` rewrite. So this sugar does NO binding join:
the `GuardedFaces` it builds binds no name. substitute ages the bindings;
this reads off the guarded facts. What it carries out of the arms is the
statement evaluations they made (`_arm_evaluations`), each under the guard
of the arm that made it: the phi's arm is a reference to one of them
(temporal choice 1, #7661).

The guard here is written from the pure-meaning primitives:
`reduce_block_to_exitset` (block reduction), `entry.guarded(formula)`
(implication), and the `GuardedFaces` floor value the block reducer already
consumes. A halt in either suite stays a halted arm of the if's `ExitSet`; the
`GuardedFaces` record holds completed testimony only (#7826).
"""

from __future__ import annotations

import functools

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _assertion_pair


def _ground_atomic_truth(formula):
    """Evaluate constant FOL atoms that if-guards must fold before dual arms run.

    ``len(xs) == 1`` over a constructed one-element tuple is ``=(1, 1)`` — a
    decided Python condition. Leaving it symbolic forces IfSugar to reduce both
    arms under the atom, so the false multi-exception ``join`` path panics even
    when source has a singleton. Ground constants are not invented testimony:
    they are the values already present in the equality atom.
    """
    from sugar_lift_py_tests.ir import (
        _Atomic,
        _ConstBool,
        _ConstInt,
        _ConstReal,
        _ConstStr,
    )

    if (
        not isinstance(formula, _Atomic)
        or formula.name != "="
        or len(formula.args) != 2
    ):
        return None
    left, right = formula.args
    const_types = (_ConstInt, _ConstReal, _ConstBool, _ConstStr)
    if type(left) not in const_types or type(right) is not type(left):
        return None
    return left.value == right.value


def predicate_formula(value, site):
    """The formula ``bool(value)`` states, where that truth is one value.

    The truth is taken through the one truth rule
    (``bool_op_sugar.truth_of``), never by asking the value directly, so a
    value whose truth is not decided here is its two faces and its halt is
    never dropped (#7757 NEW-5).  Such a truth has no one formula: a caller
    that can carry its faces takes ``truth_of`` and reads each completed face
    through ``truth_formula`` (``IfSugar._desugar_condition``, a ``match``
    guard, ``ExitSet.and_exit_truthiness``); here it is refused by name.
    """
    from sugar_lift_py_tests.sugar.bool_op_sugar import truth_of
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        plain_completed_value,
    )

    truth = truth_of(value, site, owner="if_sugar.predicate_formula")
    if plain_completed_value(truth) is None:
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            owner="if_sugar.predicate_formula",
            blame=site if site is not None else "if_sugar.predicate_formula",
            observed=(
                "truth that is not one decided value: "
                f"{type(value).__name__}"
            ),
            requested="the truth's faces, each read under its own guard",
            fix=(
                "take the truth through bool_op_sugar.truth_of and read each "
                "completed face, as IfSugar._desugar_condition does"
            ),
        )
    return truth_formula(truth, value)


def truth_formula(truth, value):
    """The formula ``truth`` -- what ``value.truth(site)`` answered -- states:
    the one projection ``predicate_formula`` reads every guard through.  A
    truth that is not one plain completed value is refused here; a truth with
    several faces (a formal's, an undecided value's) is the caller's to carry
    (``IfSugar._desugar_condition``), never coerced to a formula."""
    from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        plain_completed_value,
    )

    truth_value = plain_completed_value(truth)
    if truth_value is None:
        raise NotImplementedError(
            f"condition truth did not produce one value: {type(truth).__name__}"
        )
    # A truth face that PRESENTS another value (`if (n := c):` -- the walrus keeps
    # its value and bind faces inseparable) is transparent to the guard: the
    # binding is temporal and `extend_scope` applies it, while the GUARD is the
    # presented face's formula. Reading `formula` off the wrapper found nothing
    # and reported `condition folded without a symbolic formula:
    # NamedExpressionValue`, blaming the wrapper for a formula the presented
    # value had all along. Structural: any value that presents another is
    # projected through, with no table of which ones do.
    presented = getattr(truth_value, "presented_value", None)
    if presented is not None:
        truth_value = presented
    formula = getattr(truth_value, "formula", None)
    if formula is None:
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if isinstance(truth_value, TrueBoolLiteralSugar):
            return true_guard()
        if isinstance(truth_value, FalseBoolLiteralSugar):
            return false_guard()
        raise NotImplementedError(
            "condition folded without a symbolic formula: "
            f"{type(truth_value).__name__} (condition {type(value).__name__})"
        )
    ground = _ground_atomic_truth(formula)
    if ground is True:
        return true_guard()
    if ground is False:
        return false_guard()
    return formula


def _is_linear(exits) -> bool:
    """One unguarded completed face: nothing a flattening could merge."""
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    return (
        len(exits.exits) == 1
        and isinstance(exits.exits[0], Completed)
        and exits.exits[0].guard == true_guard()
        and not exits.exits[0].faces
        # An owing arm is not flattened: the flattening drops ``owed``.
        and not exits.exits[0].owed
    )


def _arm_evaluations(arms, incoming) -> tuple:
    """The statement evaluations the completed arms of an if made, each key
    with the value it holds on every path through the ``if``.

    ``arms`` are exit sets whose completed arms are the ``if``'s, each under
    its own guard (the ``if`` hands its own exit set: each suite's arms
    under that suite's polarity).  Each key names one statement's evaluation
    (``AugAssign._evaluation_key``) and a statement sits in one suite, so
    after the ``if`` a key is read only by the phi's arm for that suite
    (``If.substitute``), under that suite's guard.  A walrus in the
    condition (``if (n := e):``) is evaluated before either suite: the header
    rule binds its key in ``incoming``, the context the ``if`` runs in
    (``header_ran``), so it is no arm's evaluation, and the ``if``'s record
    leaves it bound for a read after the ``if`` (``statement_record``).  A
    key bound in ``incoming`` to the value an arm holds is not carried.  A
    live loop in a suite publishes each name it carries under
    a binding coordinate under its own key
    (``live_loop_construction.loop_post_binding_key``), an evaluation key
    too: it is carried out the same way, and the phi's arm for that suite
    reads it (``LoopBindingRefSugar``).  The ``if`` carries those values
    out; it carries no name.

    One rule for every key (``_joined_evaluation``): the arms that bound it
    answer one value, or each arm's own value under that arm's guard -- a
    loop in a suite that leaves by a ``break`` on one path and by
    exhaustion on another binds its key to a different value on each, and
    the read after the ``if`` takes each path's value under its guard.

    A call's record (``AfterCallRecordValue``) is no name's value: what it
    states is read by every later call that reads a module global the call
    may have changed (``call_site_sugar._global_after_call``), not by the
    phi's arm for its suite alone.  Where some completed arm did not bind it
    (``if c: bump()``), it is carried under the guard of the arms that did
    (``_record_on_its_arms``): the global is the call's state there and the
    state before the ``if`` on every other arm, never the call's state on a
    path that never ran the call (#7757 H7).
    """
    from sugar_lift_py_tests.floor.call_site_value import AfterCallRecordValue
    from sugar_lift_py_tests.outcome import Completed

    before = getattr(incoming, "temporal", None)
    made: dict = {}
    # How many completed arms the ``if`` has (an empty suite's included, which
    # carries no context and binds nothing): a record fewer arms bound
    # stands only on the arms that bound it.
    completed_arms = 0
    for arm in arms:
        for exit_ in getattr(arm, "exits", ()):
            if not isinstance(exit_, Completed):
                continue
            completed_arms += 1
            context = getattr(exit_.value, "context", None)
            temporal = getattr(context, "temporal", None)
            if temporal is None:
                continue
            for binding in temporal.evaluations():
                if (
                    before is not None
                    and before.value_if_bound(binding.name) is binding.value
                ):
                    continue
                made.setdefault(binding.name, []).append(
                    Completed(exit_.guard, binding.value, exit_.faces)
                )
    carried = []
    for key, bound in made.items():
        value = _joined_evaluation(bound)
        if value is None:
            continue
        if isinstance(value, AfterCallRecordValue) and len(bound) < completed_arms:
            value = _record_on_its_arms(value, bound)
        carried.append((key, value))
    return tuple(carried)


def _record_on_its_arms(record, bound):
    """``record`` (a call's ``AfterCallRecordValue``, bound by the
    completed arms ``bound`` of an ``if`` and by no other) standing only
    where one of those arms ran: guarded by the disjunction of their guards,
    each conjoined with the guard the record already stood under (an ``if``
    nested in the arm).  ``record`` itself where the arms bound different
    values (the one join, ``_joined_evaluation``, answered something else).
    """
    from dataclasses import replace

    from sugar_lift_py_tests.ir import and_, or_

    if any(arm.value is not record for arm in bound):
        return record
    guards = [
        arm.guard if record.guard is None else and_([arm.guard, record.guard])
        for arm in bound
    ]
    return replace(record, guard=guards[0] if len(guards) == 1 else or_(guards))


def _arm_readings(arms, incoming, own=()) -> tuple:
    """The branch-result slots read as their ``if``'s test after an ``if``
    (``GuardedFaces.readings``): ``own``, this ``if``'s slot read as its test's
    condition, and each slot the completed arms of ``arms`` read that
    ``incoming`` (the context the ``if`` runs in) did not -- an ``if`` nested
    in a suite, whose phi a read after this ``if`` still selects by.

    A slot belongs to one ``if`` in one suite, so the arms that read it agree
    on one condition, which is its reading.  Arms that read it as different
    conditions (a nested test whose truth has several completed faces, each
    selecting the suites under its own formula) read it as each arm's own
    condition under that arm's guard: ``or(g_i and c_i)``, never one of them
    for all."""
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import and_, or_
    from sugar_lift_py_tests.outcome import Completed

    before = getattr(incoming, "ground_branch_results", None)
    if not isinstance(before, dict):
        before = {}
    made: dict = {}
    for arm in arms:
        for exit_ in getattr(arm, "exits", ()):
            if not isinstance(exit_, Completed):
                continue
            context = getattr(exit_.value, "context", None)
            table = getattr(context, "ground_branch_results", None)
            if not isinstance(table, dict):
                continue
            for slot_id, reading in table.items():
                if not isinstance(reading, PredicateValue):
                    continue
                if before.get(slot_id) is reading:
                    continue
                made.setdefault(slot_id, []).append((exit_.guard, reading.formula))
    carried = []
    for slot_id, read in made.items():
        first = read[0][1]
        if all(formula == first for _guard, formula in read):
            carried.append((slot_id, first))
            continue
        carried.append(
            (slot_id, or_([and_([guard, formula]) for guard, formula in read]))
        )
    return (*carried, *own)


def _joined_evaluation(arms):
    """One evaluation key's value after the ``if``, from ``arms``: each a
    completed arm of the ``if`` that bound the key, holding the value it
    bound under the arm's guard and faces.

    The arms that bound it to one value answer that value.  Arms that bound
    it to different values answer the guarded value selecting each arm's own
    value under that arm's guard: the completed face factored into one
    ``GuardedValue`` chain through the one door that does it
    (``ExitSet.factor_completed``), which admits it only when the arms are
    provably exclusive.  Arms it cannot prove exclusive hold the key at two
    values on one path: there is no one value to carry, the key is not
    bound, and its read is refused by name (``EvaluationRefSugar``,
    ``LoopBindingRefSugar``), never answered with one of the two.
    """
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import ExitSetFactoringGap

    first = arms[0].value
    if all(arm.value is first for arm in arms):
        return first
    try:
        factored = ExitSet(tuple(arms)).normalize().factor_completed()
    except ExitSetFactoringGap:
        return None
    (arm,) = factored.exits
    return arm.value


@dataclass(frozen=True)
class IfSugar(Sugar):
    """`if <test>: <then> [else: <else>]`, constructed by `If.sugar()` with the
    test's sugar and each branch's statement sugars already built."""

    test: Sugar
    branch_slot: object
    then_body: tuple  # the then-branch statements' sugars, in source order
    else_body: tuple  # the else-branch statements' sugars (empty if no else)
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        # An ``if`` statement over the local `z = 5` binds `out` in each arm:
        # `z == 1` is false, so the truthful twin asserts the else arm's 20,
        # the lying twin the arm not taken, 10.
        return _assertion_pair(
            name="if_guarded_return",
            owner_sugar="IfSugar",
            statements=(
                "z = 5\n"
                "if z == 1:\n"
                "    out = 10\n"
                "else:\n"
                "    out = 20"
            ),
            truthful="out == 20",
            lying="out == 10",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halt_record,
            halts_recorded,
            header_applied,
            plain_completed_value,
        )

        # The test is this statement's header: every walrus bind and callee
        # store its value carried reaches both suites, and what follows the
        # ``if``, by the one header rule (``header_applied``), the stores laid
        # first in every record the ``if`` makes.
        headed, cond = header_applied(self, "test", ctx)
        if headed is not None:
            return headed

        condition = plain_completed_value(cond)
        if condition is not None:
            return self._desugar_condition(condition, ctx)
        if isinstance(cond, ExitSet):
            # Any condition that is not one plain completed arm: one that may
            # raise (an unknown callee completes or raises), one with several
            # faces, or one that owes (an ``is`` nothing decides owes the
            # undecided member, #8984).  Each completed face selects its
            # suites under its own guard, its debt carried onto every arm the
            # suites make (``ExitSet.and_then``); a halted face never reaches
            # either suite.  Returning the condition's faces as the
            # statement's dropped both suites -- every halt and fact in them.
            # A halted face halted before either suite ran: it carries the
            # record of where the condition halted (``halts_recorded``), onto
            # which the block composition splices what ran before the ``if``.
            return halts_recorded(cond, halt_record(ctx)).and_then(
                lambda value: self._select_on_face(value, ctx)
            )
        return cond

    def _select_on_face(self, value, ctx):
        """One completed condition face selects its suites: its truth is
        taken by the one truth rule (``_desugar_condition``), whose faces
        each select under their own guard."""
        return self._desugar_condition(value, ctx)

    def _ground_branch_result(self, ctx, observed_formula, slot) -> None:
        """A ground condition decides this if's branch-result slot, as the
        live loop item running now decides it (``slot``, ``branch_slot_here``)."""
        from sugar_lift_py_tests.outcome.exit_set import true_guard

        if ctx is None or slot is None:
            return
        table = getattr(ctx, "ground_branch_results", None)
        if not isinstance(table, dict):
            return
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        table[slot.slot_id] = (
            TrueBoolLiteralSugar(site=self.site)
            if observed_formula == true_guard()
            else FalseBoolLiteralSugar(site=self.site)
        )

    def _desugar_condition(self, condition, ctx: object = None):
        # Branches carry facts/effects: the guard is the condition's TRUTHINESS
        # as a predicate. `.truth` is uniform -- a predicate condition (`if a ==
        # b`) stands as its own formula, a bare value (`if c`) emits the Python
        # `py.truthy(c)` relation. A ground bool (`if True:`) folds to a literal
        # with no formula and is not lifted yet -- LOUD, never guard by nothing.
        # A condition expression that raised never gets here: its halted arm
        # is handed back before any branch is selected.
        #
        # ``bool(condition)`` is taken through the one truth rule
        # (``bool_op_sugar.truth_of``): a value whose truth is not decided
        # here is its two faces, and each completed truth face selects the
        # suites under its own guard; a halted truth halted at the ``if``'s
        # head, before either suite ran (``halts_recorded``).  A formal's
        # truth is such a value: both suites stay reachable under its
        # undecided atom, and its halt is kept (#7757 NEW-1).
        from sugar_lift_py_tests.sugar.bool_op_sugar import truth_of
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halt_record,
            halts_recorded,
            plain_completed_value,
        )

        truth = truth_of(condition, self.site, owner="IfSugar.test")
        if isinstance(truth, ExitSet) and plain_completed_value(truth) is None:
            return halts_recorded(truth, halt_record(ctx)).and_then(
                lambda truth_value: self._select_suites(
                    condition,
                    truth_formula(ExitSet.completed(truth_value), condition),
                    ctx,
                )
            )
        return self._select_suites(condition, truth_formula(truth, condition), ctx)

    def _select_suites(self, condition, observed_formula, ctx) -> ExitSet:
        """The ``if`` on ``condition`` whose truth states ``observed_formula``:
        a ground formula selects one suite, any other splits both."""
        from sugar_lift_py_tests.floor.branch_result_coordinate import (
            BranchResultAuthentication,
            branch_result_guard,
        )
        from sugar_lift_py_tests.floor.guarded_faces import GuardedFaces
        from sugar_lift_py_tests.outcome import Completed, Halted
        from sugar_lift_py_tests.outcome.exit_set import partition as _partition
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )
        from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import branch_slot_here

        # The slot this run of the ``if`` decides: in a live loop's item, that
        # item's own (``branch_slot_here``), never one shared by every item.
        slot = (
            None if self.branch_slot is None else branch_slot_here(self.branch_slot)
        )
        # Each arm is guarded by the test's own condition (``observed_formula``),
        # the formula the branch slot stands for, so the two arms are exactly
        # the two faces of the test: a ``return`` an arm takes is guarded by
        # it, and what follows the ``if`` goes on under its complement
        # (``continuation_guard``, the fall-through ``past_prior_returns``
        # splits on).  The slot's guard is no arm's guard: a contract row
        # never carries the slot's authentication (it mints nothing), so an
        # arm guarded by the slot was guarded by a flag no input decides, and
        # both arms stood satisfiable for one input (#7757).  The assignment
        # phi after the ``if`` (``If.substitute``) selects by the same
        # condition: the path after a symbolic ``if`` reads its slot as it
        # (``GuardedFaces.readings``, ``branch_result_reading``).  The slot's
        # guard keys the partition this ``if`` mints, one per run of the
        # ``if``.
        formula = observed_formula
        slot_guard = (
            observed_formula
            if observed_formula in (false_guard(), true_guard())
            else branch_result_guard(slot, self.site)
        )
        authentication = BranchResultAuthentication(slot, observed_formula, self.site)

        # Carry the call-frame temporal into each branch. Formals are
        # BindingCoordinateRefSugar keyed by coordinate cid; without ctx the
        # branch suite cannot resolve authenticated actuals and panics as
        # unspecialized source-call formal (dual-mode EffectBoundary factories
        # nest further ifs that read those formals).
        # A ground condition selects one suite before that suite is reduced.
        # Reducing the dead peer first can demand a loud producer that Python
        # never executes, turning an unreachable diagnostic into a function
        # construction failure. Symbolic conditions still reduce both suites
        # and preserve their guarded exits exactly as before.
        # A FloorValue with non-identity extend_scope binds before branch
        # selection -- Python makes it visible in BOTH arms.  Default
        # FloorValue.extend_scope is identity.  The test's walrus binds and
        # callee stores are already in ``ctx``: the header rule ran this
        # ``if`` in the context they leave (``header_applied``).
        branch_ctx = condition.extend_scope(ctx)

        if observed_formula in (false_guard(), true_guard()):
            selected = reduce_block_to_exitset(
                self.then_body if observed_formula == true_guard() else self.else_body,
                branch_ctx,
            )
            self._ground_branch_result(ctx, observed_formula, slot)
            if isinstance(selected, ExitSet) and not _is_linear(selected):
                # A ground condition selects ONE suite: the if is that suite.
                # Its faces are handed back as they are -- each with its own
                # temporal record -- never flattened into one completed face
                # whose entries are merely guarded.  Flattening put a store
                # made only after a call completed beside a completed face
                # under ``true``, so the constructor forked an impossible
                # companion that completed WITHOUT the store where the call
                # in fact raised.
                return selected
            then_exits, else_exits = (
                (selected, ExitSet(()))
                if observed_formula == true_guard()
                else (ExitSet(()), selected)
            )
        else:
            then_exits = reduce_block_to_exitset(self.then_body, branch_ctx)
            else_exits = reduce_block_to_exitset(self.else_body, branch_ctx)

        # If is union in the exit algebra: each branch is restricted to its
        # polarity, then the partitions normalize together. In particular, a
        # halt on one face coexists with the complementary Completed exit.
        # A selected ground-false else arm is the true face, not the merely
        # equivalent ``not(not(true))`` spelling.  Do not unwrap symbolic
        # branch guards: their internal negation is part of their identity.
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome.exit_set import complement_guard

        not_formula = (
            complement_guard(formula) if formula == false_guard() else not_(formula)
        )
        # This If OWNS the split, so it mints the partition and stamps each
        # branch with its face. Downstream factoring reads the exclusion off
        # the arms as testimony instead of re-proving it from guard spelling,
        # which stops being legible once these guards are conjoined with a
        # prefix or merged with a sibling arm.
        then_face, else_face = _partition(("IfSugar", self.site, slot_guard))
        join = functools.partial(
            self._join_branches,
            formula=formula,
            not_formula=not_formula,
            then_face=then_face,
            else_face=else_face,
            observed_formula=observed_formula,
            authentication=authentication,
            # The context the ``if`` runs in, not ``branch_ctx``: a value whose
            # scope binds an evaluation into ``branch_ctx`` is held by every
            # arm, and is carried out of the if like an arm's own.
            incoming=ctx,
        )
        return join(then_exits, else_exits)

    def _join_branches(
        self,
        then_exits,
        else_exits,
        *,
        formula,
        not_formula,
        then_face,
        else_face,
        observed_formula,
        authentication,
        incoming=None,
    ) -> ExitSet:
        from dataclasses import replace as _replace

        from sugar_lift_py_tests.floor.guarded_faces import GuardedFaces
        from sugar_lift_py_tests.outcome import Completed, Halted
        from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            face_record,
            past_prior_returns,
        )

        exits = then_exits.guarded(formula, then_face).union(
            else_exits.guarded(not_formula, else_face)
        )
        # A suite arm that falls through after a guarded ``return`` (``if a:
        # if b: return 1``) took that ``return`` where its guard held: what
        # follows the ``if`` is not a statement of that suite, so the arm is
        # split there by the one composition a block gives a statement after
        # a guarded ``return`` (``past_prior_returns``). The ``return`` leaves
        # the ``if`` as its own completed arm (``left``), its record unable
        # to fall through; the arm goes on into the join (``went_on``) only
        # under the guard that it was not taken, without the ``return``
        # entries that guard excludes -- so the statement after the ``if``
        # never stands beside it unguarded. An arm with no earlier ``return``
        # goes on as it is.
        left = ExitSet(
            tuple(exit_ for exit_ in exits.exits if isinstance(exit_, Completed))
        ).and_then(
            lambda record: past_prior_returns(
                record, record.context, lambda _went_on: ExitSet(()), ExitSet.completed
            )
        )
        went_on = (
            exits.and_then(
                lambda record: past_prior_returns(
                    record,
                    record.context,
                    ExitSet.completed,
                    lambda _left: ExitSet(()),
                )
            )
            if left.exits
            else exits
        )
        # No arm is guarded by the branch-result slot: every arm is guarded
        # by the test's own condition. A ground condition decides the slot in
        # the reduction context (``_ground_branch_result``); authenticating it
        # too would inject BranchResultAuthentication into every folded `if
        # not args:` factory prefix, and prefix CIDs cannot project that
        # testimony. A symbolic split publishes the slot's authentication
        # (read by a ``with``'s guards, ``resolve_branch_result_guards``, and
        # a class body's record), and the path after it reads the slot as
        # the test's condition (``readings``): the phi after the ``if``
        # selects by that condition, never by the slot's coordinate, which
        # no contract row ties to the test.
        # The callee stores the condition's value carried lead it on every
        # arm: the header rule lays them (``header_ran``).
        symbolic = observed_formula not in (false_guard(), true_guard())
        unconditional_entries = (authentication,) if symbolic else ()
        own_reading = (
            ((authentication.slot.slot_id, observed_formula),)
            if symbolic and authentication.slot is not None
            else ()
        )

        entries = []
        for exit_ in went_on.exits:
            if isinstance(exit_, Completed):
                entries.extend(
                    entry.guarded(exit_.guard) for entry in exit_.value.entries
                )

        def falls_through(branch_exits):
            return any(
                isinstance(exit_, Completed) and exit_.value.can_fall_through
                for exit_ in branch_exits.exits
            )

        def only_halts(branch_exits):
            # A suite whose every exit is a halt sets no continuation guard:
            # its halts are arms of their own, and the completed face's arm
            # guard already excludes them.
            return bool(branch_exits.exits) and all(
                isinstance(exit_, Halted) for exit_ in branch_exits.exits
            )

        then_branch_exits = not falls_through(then_exits)
        else_branch_exits = not falls_through(else_exits)
        can_fall_through = not (then_branch_exits and else_branch_exits)
        # The tail rides under the polarity of whichever branch did NOT exit; if
        # both fall through it is unconditional, if both exit it is unreachable.
        continuation_guard = None
        if (
            then_branch_exits
            and not else_branch_exits
            and not only_halts(then_exits)
        ):
            continuation_guard = not_formula
        elif (
            else_branch_exits
            and not then_branch_exits
            and not only_halts(else_exits)
        ):
            continuation_guard = formula

        faces = GuardedFaces(
            guard=formula,
            entries=tuple(entries),
            then_exits=then_branch_exits,
            else_exits=else_branch_exits,
            can_fall_through=can_fall_through,
            continuation_guard=continuation_guard,
            unconditional_entries=unconditional_entries,
            # Each suite's arms under its polarity: a key's value on each
            # path is read under that path's own guard.
            evaluations=_arm_evaluations((went_on,), incoming),
            readings=_arm_readings((went_on,), incoming, own_reading),
        )
        if not exits.halts() and not exits.owed_items() and not left.exits:
            return ExitSet.completed(faces)

        def halted_after_condition(halt):
            # A halt in either suite stays a halted arm of the if (#7826): no
            # completed record holds a halt.  The condition's own testimony
            # (the branch-result slot's authentication) was established
            # before either suite ran, so the halted arm's record carries it
            # ahead of what the suite reached before halting. Every suite
            # halt carries the record its block composition gave it; one
            # with no record is stopped by name (``face_record``), never
            # given one made up with no context.
            inner = face_record(halt, owner="IfSugar.suite", blame=self.site)
            return ExitSet.halted(
                halt.effect,
                state=_replace(
                    inner, entries=(*unconditional_entries, *inner.entries)
                ),
            )

        # Every completed arm of both suites continues as the one completed
        # face; ``normalize``'s join merges those continuations into one arm
        # under the disjunction of their guards, owing every debt of the arms
        # it stands for. Each halt continues as itself over the condition's
        # testimony. Both compose through ``ExitSet.and_then``, so no guard,
        # face or ``owed`` is restated by hand. A ``return`` an arm took before
        # it fell through (``left``) leaves beside them, over the condition's
        # testimony, its record unable to fall through.
        joined = went_on.and_then(
            lambda _suite: ExitSet.completed(faces), consume=halted_after_condition
        )
        if not left.exits:
            return joined
        return joined.union(
            left.and_then(
                lambda record: ExitSet.completed(
                    _replace(
                        record, entries=(*unconditional_entries, *record.entries)
                    )
                )
            )
        )

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import atomic, ctor, not_, str_const
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


def _is_authenticated_stop_iteration(effect) -> bool:
    """Iterator exhaustion only by authenticated ``StopIteration`` type coordinate.

    The kit's ``next`` producer mints ``exception_type_coordinate``. Display
    spelling of ``exception_name`` is never consulted: a foreign coordinate
    wearing the same name is not exhaustion, and a RaiseEffect that omitted
    its coordinate is unwritten work (throw), not a name-based guess.
    """
    from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity
    from sugar_source_tree.panic import SugarNotWritten

    owner = "LoopRecurrenceSugar._advance_iterator"
    stop_identity, _ = _builtin_exception_identity("StopIteration")
    coordinate = getattr(effect, "exception_type_coordinate", None)
    if coordinate is None:
        raise SugarNotWritten(
            blame=getattr(effect, "occurrence_id", None) or owner,
            owner=owner,
            observed="RaiseEffect without exception_type_coordinate",
            requested="authenticated StopIteration type coordinate from next producer",
            fix=(
                "mint the halt through ground_exceptional_exit / the iterator "
                "floor; never decide exhaustion by exception_name spelling"
            ),
        )
    return coordinate == stop_identity


def _else_witnesses(runtime, else_ctx) -> tuple:
    """``(key, value)`` for every key a live loop bound for its ``else``
    suite where the suite begins (``else_ctx``): each carried name's
    header and the target's key (``_enter_header``, ``_leave_target``),
    qualified where the suite runs (``evaluation_here``) -- read where the
    loop binds them, before the suite reduces.  A context the suite left
    from holds each of them at that very value (``_else_left_from``)."""
    from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here

    temporal = getattr(else_ctx, "temporal", None)
    if temporal is None:
        return ()
    keys = (
        *(
            header
            for header, _writes, _else_writes in getattr(
                runtime, "carried_evaluations", ()
            )
            if header is not None
        ),
        *getattr(runtime, "target_evaluations", ()),
    )
    witnesses = []
    for key in keys:
        here = evaluation_here(key)
        value = temporal.value_if_bound(here)
        if value is not None:
            witnesses.append((here, value))
    return tuple(witnesses)


def _else_left_from(runtime, else_ctx, witnesses, halt, *, site):
    """The context a live loop's publication is read from where ``halt``
    left its ``else`` suite, which began at ``else_ctx``.

    A suite that writes no name the loop publishes (no ``else`` write in
    ``carried_evaluations`` nor ``published_evaluations``) leaves every name
    as it began: ``else_ctx``.  One that writes is read where it halted --
    the context of the halt's record, or the bare context it holds -- once
    that context is authenticated as the suite's: every key the loop bound
    for the suite holds there the very value it was bound to (``witnesses``,
    object identity), as a ``break``'s record is
    (``LoopRecurrenceSugar._require_loop_control_state``).  A halt that left
    from another context (a callee's record, which the block composition
    splices on as it is) does not hold what the suite wrote before it: it
    is refused by name, never read in its place."""
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    writes = any(
        else_writes
        for _key, _writes, else_writes in (
            *getattr(runtime, "carried_evaluations", ()),
            *getattr(runtime, "published_evaluations", ()),
        )
    )
    if not writes:
        return else_ctx
    state = halt.state
    context = state.context if isinstance(state, _ReducedBlock) else state
    temporal = getattr(context, "temporal", None)
    if (
        witnesses
        and temporal is not None
        and all(temporal.value_if_bound(key) is value for key, value in witnesses)
    ):
        return context
    from sugar_source_tree.panic import SugarNotWritten

    raise SugarNotWritten(
        owner="LoopRecurrenceSugar.else-halt",
        blame=site,
        observed=(
            f"a {type(halt.effect).__name__} halt leaving a live loop's else "
            "suite, which writes a name the loop publishes, from a context "
            "that is not the suite's"
        ),
        requested=(
            "the context the else suite halted in, holding what it wrote "
            "before the halt"
        ),
        fix=(
            "carry the suite's context on the halt's record; never read the "
            "loop's publication from another frame's context"
        ),
    )


# The recurrence's value of a name a live loop writes
# (``recurrence_head``).
RECURRENCE_HEAD = "python:loop.recurrence"
# The recurrence's one symbolic item of the iterable (``loop_item``).
LOOP_ITEM = "python:loop.item"
# The suffix of a recurrence's own evaluation key of the module globals as
# its symbolic item begins from them (``global_recurrence``).
_GLOBAL_RECURRENCE = "#global-recurrence"
# The values a live loop's recurrence states and nothing decides.
_RECURRENCE_VALUES = frozenset({RECURRENCE_HEAD, LOOP_ITEM})


def recurrence_head(target_cid: str, key: str):
    """The recurrence's value of the name a read after the recurrence
    reads through ``key`` (a binding coordinate, a post-loop key, a
    comprehension member's final coordinate): its symbolic fixed point,
    ``python:loop.recurrence(<target>, <key>)``.  ``target_cid`` names the
    recurrence: a loop's owned target, a comprehension generator's binding
    coordinate.  Nothing decides it: a read of it owes
    (``holds_recurrence_value``)."""
    return ctor(
        RECURRENCE_HEAD,
        [str_const(target_cid), str_const(key)],
        symbol_kind="coordinate",
    )


def global_recurrence(target_cid: str):
    """``(key, record)``: the module globals as the items before a
    recurrence's symbolic item left them -- a ``for``'s or ``while``'s
    (``LoopRecurrenceSugar``), a comprehension generator's
    (``ComprehensionSugar._recurrence``), ``target_cid`` naming it as
    ``recurrence_head`` does -- one call's record (``AfterCallRecordValue``)
    whose result is the recurrence's fixed point of that state
    (``recurrence_head``) and which reaches every module global
    (``EVERY_GLOBAL_SLOT``), under the recurrence's own evaluation key of
    it (the construct-time key: ``evaluation_here`` qualifies it where it
    is bound).  A later call that reads a mutable global reads
    ``python:after(python:loop.recurrence(<target>, <key>),
    "global:<name>")`` (``call_site_sugar._global_after_call``): the
    global as an unknown number of earlier items left it, which nothing
    decides -- never the value from before the recurrence, which an item
    after the first may no longer see (#7757 H7)."""
    from sugar_lift_py_tests.floor.call_site_value import (
        EVERY_GLOBAL_SLOT,
        AfterCallRecordValue,
    )
    from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX

    key = f"{EVALUATION_PREFIX}{target_cid}{_GLOBAL_RECURRENCE}"
    return key, AfterCallRecordValue(
        recurrence_head(target_cid, key), ((EVERY_GLOBAL_SLOT, None),)
    )


def entering_the_recurrence(target_cid: str, ctx):
    """``ctx`` (where a recurrence's symbolic item, or a loop
    recurrence's ``else`` suite, begins) with the recurrence's record of the
    module globals bound (``global_recurrence``): an item may follow earlier
    items whose calls changed a global, so a call in it reads the global as
    the recurrence leaves it, never as it stood before the recurrence.  The
    one starting context a loop's recurrence and a comprehension's run their
    symbolic item from.  ``ctx`` itself where it holds no temporal."""
    if getattr(ctx, "temporal", None) is None:
        return ctx
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
    from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here

    key, record = global_recurrence(target_cid)
    return ScopeRebind(evaluation_here(key), record).extend_scope(ctx)


def records_left(target_cid: str, made) -> tuple:
    """The calls' records (``AfterCallRecordValue``) a recurrence leaves
    with, from ``made`` -- the ``(key, value)`` bindings a path through it
    made, in the order it made them -- in that order: the one rule a loop's
    (``LoopRecurrenceSugar._records_made_here``) and a comprehension's
    (``ComprehensionSugar._complete``) records leave by.

    Published, the newest record a later call reads is the last one a path
    through the recurrence made: on an item that ran in hand, that item's
    call; on the symbolic item, its call, over the record it began with
    (``global_recurrence``); a record made under a guard (one arm of an
    ``if`` in an item) keeps it.

    Nothing where the path made none, or made only the record the
    recurrence began its item with: the globals then stand as they did
    before it.  A key an ``if`` in the item joined from arms that bound
    different records holds their join (``is_call_record``), which leaves
    as it is."""
    from sugar_lift_py_tests.floor.call_site_value import is_call_record

    records = tuple((key, value) for key, value in made if is_call_record(value))
    _began_key, began = global_recurrence(target_cid)
    if all(value == began for _name, value in records):
        return ()
    return records


def loop_item(target_cid: str, iterable, site=None):
    """The recurrence's one symbolic item of ``iterable`` (None: a
    ``while``, which iterates nothing): ``python:loop.item(<target>,
    <iterable>)``, the value every item of a recurrence over an iterable
    whose members are not in hand stands as -- a ``for``'s
    (``LoopRecurrenceSugar._enter_symbolic_item``) and a comprehension
    generator's (``ComprehensionSugar._recurrence``), ``target_cid`` the
    loop's owned target or the generator's binding coordinate.  No equation
    ties it to a member of the iterable: a read of it owes
    (``holds_recurrence_value``).

    The iterable is named as the loop at ``site`` finds it
    (``object_identity.identity_term``): a container whose contents are not
    current -- one that arrived by binding, the recurrence's own reason for
    running -- by its identity, never by contents it may no longer hold
    (#7757 H7); a current one by its display."""
    from sugar_lift_py_tests.floor.object_identity import identity_term

    return SymbolicValue(
        ctor(
            LOOP_ITEM,
            [
                str_const(target_cid),
                *(
                    ()
                    if iterable is None
                    else (
                        identity_term(
                            iterable, site, "iterable", owner="LoopRecurrenceSugar"
                        ),
                    )
                ),
            ],
            symbol_kind="coordinate",
        )
    )


def project_iteration_target(pattern, value, ctx, *, owner: str, prefix=("target",)):
    """Project every target leaf of ``pattern`` (a ``TargetPatternV1``)
    through the Floor-owned unpack door: the one unpack an item of a
    recurrence takes into its target -- a ``for``'s
    (``LoopRecurrenceSugar._project_iteration_target``) and a comprehension
    generator's (``ComprehensionSugar._member_unpack``).  ``prefix`` is the
    projection path of the pattern's root (``("target",)`` for a ``for``,
    ``("generators", <index>, "target")`` for a comprehension generator,
    ``SourceUnit.target_pattern_enrollment``); ``owner`` names the unpack.

    Completes with ``(name, coordinate, value)`` per leaf, in source
    order; each unpack's halt is an arm beside it, nothing bound.  An
    item with authenticated members answers one plain roster or halts;
    one without (the symbolic item, a concrete item's symbolic member)
    answers both faces of its runtime unpack (``runtime_unpack_faces``):
    the leaves are read from each completed arm (``ExitSet.and_then``),
    beneath its guard and carrying what it owes, and an inner unpack's
    halt is an arm beneath the outer one's."""
    from sugar_lift_py_tests.operations.positional_unpack_operation import (
        PositionalUnpackOperation,
        UnpackMemberRoster,
    )
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set
    from sugar_source_tree.nodes import List, Name, Tuple_

    coordinates = {
        coordinate.projection_path: coordinate
        for coordinate in pattern.target_coordinates
    }

    def project(target, current, path=()):
        if isinstance(target, Name):
            coordinate = coordinates[(*prefix, *path)]
            return ExitSet.completed(((target.id, coordinate.cid, current),))
        if not isinstance(target, (Tuple_, List)):
            raise TypeError("iteration target contains an unsupported target leaf")
        operation = PositionalUnpackOperation(
            fixed_prefix=len(target.elts),
            fixed_suffix=0,
            has_star=False,
            owner=owner,
            blame=target.fragment,
        )
        # An item with no authenticated members (the symbolic item, a
        # symbolic member) is unpacked through the one undecided
        # operation: two faces (``runtime_unpack_faces``), completing with
        # the roster or halting with the unpack's raise, both owing its
        # ``undecided`` member.  The leaves are read from each completed
        # arm beneath its guard and owing what it owes, and the halt is an
        # arm as it is (``ExitSet.and_then``): never refused for its debt.
        unpacked = _require_exit_set(operation.submit(current, ctx), owner=owner)

        def leaves(roster):
            if not isinstance(roster, UnpackMemberRoster):
                raise TypeError(
                    "positional target unpack omitted its authenticated roster"
                )
            # The roster is this operation's: minted under its occurrence
            # (``mint_roster``), the one fragment it was built with.
            # ``target.fragment`` is a new ``SourceFragment`` at every read,
            # so it is never the roster's by identity.
            if (
                roster.occurrence is not operation.blame
                or roster.demand_cid != operation.demand_cid()
                or len(roster.members) != len(target.elts)
            ):
                raise TypeError(
                    "positional target unpack returned cross-wired testimony"
                )

            def collect(index, bindings):
                if index == len(target.elts):
                    return ExitSet.completed(bindings)
                # A child's halt is an arm as it is; its leaves join the
                # siblings' on each completed arm.
                return project(
                    target.elts[index], roster.members[index], (*path, index)
                ).and_then(lambda child: collect(index + 1, (*bindings, *child)))

            return collect(0, ())

        return unpacked.and_then(leaves)

    return project(pattern.target, value)


def holds_recurrence_value(value) -> bool:
    """Whether ``value`` is, on some face, a value a live loop's recurrence
    states and nothing decides: its value of a name (``RECURRENCE_HEAD``) or
    its symbolic item (``LOOP_ITEM``).  A guarded value is opened into its
    arms.

    The recurrence states the value of a name only as the fixed point of the
    loop's step (``head = python:loop.step(head, ...)``), and the step is
    uninterpreted.  It states the item as ``python:loop.item(<loop>,
    <iterable>)`` and nothing else: no equation ties it to a member of the
    iterable.  Nothing at prove constrains either, no input decides either,
    and no closed form or loop invariant is stated on this path.  Read as it
    stands either is a free term the solver may choose, so a claim over it --
    a lie included -- could read ``sat`` (#7757, step 6).  A decided item (a
    member of an in-hand list, tuple or range) is a concrete item's value,
    never ``LOOP_ITEM``: the loop runs unrolled over it.

    A comprehension over an iterable whose members are not in hand runs as
    the same recurrence (``ComprehensionSugar._recurrence``): its member is
    the recurrence's one symbolic item (``loop_item``), and its final
    member, what a lambda made in it reads after it, is the recurrence's
    value of that member's coordinate (``recurrence_head``).  The
    ``ComprehensionValue`` it completes with holds the comprehension's own
    coordinate, ``py.listcomp(<occurrence>, <evaluation key>)`` (or its
    set, dict or generator kind, ``ComprehensionSugar._own_coordinate``), a
    constructor prove does not interpret, so the list, set or dict it
    accumulates (and what a generator yields) is a value the solver
    chooses.  One whose owner projected every member (``finite_elements``)
    is decided."""
    from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.ir import _Ctor

    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, GuardedValue):
            pending.extend((current.when_true, current.when_false))
        elif isinstance(current, ComprehensionValue):
            if current.finite_elements is None:
                return True
        elif isinstance(current, SymbolicValue):
            term = current.term
            if isinstance(term, _Ctor) and term.name in _RECURRENCE_VALUES:
                return True
    return False


def read_of_bound_value(value, site):
    """A read, at ``site``, of the value a key holds: the value itself, or,
    where it holds a value a live loop's recurrence states and nothing
    decides (``holds_recurrence_value``) -- the name the loop carries read
    after it (``LoopBindingRefSugar``), in its ``else`` suite or inside its
    symbolic item through the header, or the item itself read through the
    target's key (``EvaluationRefSugar``), and a comprehension run as its
    recurrence, read where the comprehension completes with it
    (``ComprehensionSugar._complete``) and through any key it is bound
    under, and its member (the recurrence's symbolic item) read in its
    element, key, value or condition (``EvaluationRefSugar._member``), or its
    final member read after it -- the undecided member, as a slot
    nothing decided is (``branch_result_coordinate.undecided_slot_debt``):
    the value still stands, and every claim that reads it owes, never
    decided by a value the solver selects (#7757)."""
    if not holds_recurrence_value(value):
        return value
    from sugar_lift_py_tests.floor.branch_result_coordinate import (
        undecided_slot_debt,
    )

    return ExitSet.completed(value, owed=undecided_slot_debt(site))


@dataclass(frozen=True)
class LoopBindingRefSugar(ConstructedTermSugar):
    """A read after a live loop of ``name``, which the loop carries under
    its binding coordinate: one face (``completion_kind``) of the loop's
    post-binding projection (``project_loop_post_binding``).

    The read resolves through the loop's own key of the name only
    (``post_key``, ``live_loop_construction.loop_post_binding_key``), never
    through the binding coordinate: two loops writing one name carry it
    under one coordinate, and a read after the later one must never find the
    earlier one's value there.  The loop binds the key on every exit it
    leaves by, concrete or symbolic, guarded or not
    (``LoopRecurrenceSugar._publication``), so a read reduced after the loop
    in the block that ran it finds it bound, and an ``if`` carries it out of
    the arm the loop sits in as it carries any evaluation
    (``if_sugar._arm_evaluations``).  The key is an evaluation key, read
    where the reduction runs (``evaluation_read_here``): inside the item of a
    live loop around the write, that item's.  Unbound -- no context, or a
    context the loop's publication never reached -- the read is refused by
    name (``_unbound``): no value is made up in its place."""

    target_cid: str
    binding_coordinate_cid: str
    completion_kind: str
    name: str
    post_key: str
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str):
        del owner
        return ctor(
            "python:loop.post_binding",
            [
                str_const(self.target_cid),
                str_const(self.binding_coordinate_cid),
                str_const(self.completion_kind),
            ],
            symbol_kind="coordinate",
        )

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
            evaluation_read_here,
        )

        temporal = getattr(ctx, "temporal", None)
        bound = None
        if temporal is not None:
            key = evaluation_read_here(temporal, self.post_key)
            bound = temporal.key_read(key)
        if bound is None:
            self._unbound()
        # The loop ran as its recurrence: the name is the recurrence's value
        # of it, which nothing decides, so the read owes the undecided member
        # (``read_of_bound_value``).  A concrete loop's value reads as it is.
        return read_of_bound_value(bound, self.site)

    def _unbound(self):
        """A read whose key the loop's publication never reached here.
        Refused by name, naming the key and the binding coordinate: the name
        is never read in its place, the coordinate is never read in its
        place either (another loop writing the name binds the same one), and
        the loop is never assumed to have left some value nobody bound."""
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="LoopBindingRefSugar",
            blame=self.site,
            observed=(
                f"read of `{self.name}` after loop {self.target_cid} "
                f"({self.completion_kind} face) with the loop's key "
                f"{self.post_key} of binding coordinate "
                f"{self.binding_coordinate_cid} unbound"
            ),
            requested=(
                "the loop's publication of the name under its own key "
                "(LoopRecurrenceSugar._publication) on the exit the read "
                "follows"
            ),
            fix=(
                "reduce the read after the loop in the block that ran it, "
                "or carry the loop's publication to where the read is "
                "reduced; never answer an unbound post-binding term"
            ),
        )


@dataclass(frozen=True)
class LoopRecurrenceSugar(ConstructedTermSugar):
    target_cid: str
    loop_construction_cid: str
    binding_coordinate_cids: tuple[str, ...]
    # The loop's own key of each name it carries under a binding coordinate
    # (``binding_coordinate_cids`` order,
    # ``live_loop_construction.loop_post_binding_key``): what it publishes
    # the name under as it leaves (``_publication``).
    post_binding_keys: tuple[str, ...]
    outward_faces: tuple[object, ...]
    construction: object = field(compare=False)
    site: object = field(compare=False)
    # What the iterable's walrus writes leave the loop as, on every exit
    # (``desugar``, ``_iterable_writes``): bound by the reduction that
    # evaluated the iterable, never by the construction.
    iterable_writes: tuple = field(default=(), compare=False)
    # The temporal the loop's first item begins from, after its iterable
    # (``_desugar_with_iterable``, ``_desugar_while``): a call's record
    # (``AfterCallRecordValue``) bound anywhere else was made by the loop
    # (``_records_made_here``).  Bound by the reduction, never by the
    # construction.
    entered: object = field(default=None, compare=False, repr=False)

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str):
        """Project the authenticated loop construction as one canonical term."""
        from sugar_lift_py_tests.loop_construction import (
            LoopWireError,
            decode_loop_construction_v1,
        )

        construction = decode_loop_construction_v1(self.construction.wire_graph())
        if construction.loop_construction_cid != self.loop_construction_cid:
            raise LoopWireError("loop recurrence construction CID mismatch")
        if construction.target.target_cid != self.target_cid:
            raise LoopWireError("loop recurrence target CID mismatch")

        root = construction.wire_graph()["root"]
        outward_face_cids = tuple(root["outwardHaltedFaceCids"])
        if len(outward_face_cids) != len(self.outward_faces):
            raise LoopWireError("loop recurrence outward-face testimony mismatch")
        coordinates = (*self.binding_coordinate_cids, *outward_face_cids)
        if any(
            not isinstance(cid, str) or not cid.startswith("blake3-512:")
            for cid in coordinates
        ):
            raise LoopWireError("loop recurrence testimony must be content-addressed")

        return ctor(
            "python:loop-recurrence-construction",
            (
                str_const(self.target_cid),
                str_const(self.loop_construction_cid),
                self.occurrence_term(owner=owner),
                ctor(
                    "python:loop-binding-coordinates",
                    tuple(str_const(cid) for cid in self.binding_coordinate_cids),
                    symbol_kind="coordinate",
                ),
                ctor(
                    "python:loop-outward-face-testimony",
                    tuple(str_const(cid) for cid in outward_face_cids),
                    symbol_kind="coordinate",
                ),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.loop_construction import LoopWireError

        runtime = self.construction.loop_runtime
        if getattr(runtime, "test_sugar", None) is not None:
            # A live ``while`` (``LiveWhileRuntimeV1``): its items run where
            # its test decides, exactly as a live ``for``'s run.
            return self._desugar_while(runtime, ctx)
        iterable_sugar = self.construction.iterable_sugar
        iterable_cid = self.construction.iterable_value_construction_cid
        if iterable_cid is None:
            return self._desugar_with_iterable(None, ctx)
        if iterable_sugar is None:
            raise LoopWireError("for recurrence omitted its live iterable sugar")
        if iterable_sugar.site.seal().cid != iterable_cid:
            raise LoopWireError("loop recurrence iterable occurrence mismatch")
        from sugar_lift_py_tests.floor.named_expression_value import (
            peel_walrus_binds,
            written_by,
        )

        from dataclasses import replace

        # The iterable is evaluated once, before the first item: a walrus in
        # it has written before the pre-loop values are read and every item
        # runs (``written_by``).  A carried name it writes starts the loop
        # from the walrus's key (``construct_live_loop_recurrence``).  The
        # loop iterates the value the iterable presents, and leaves, on every
        # exit, with the writes of the names it does not carry
        # (``_iterable_writes``).
        #
        # A live loop runs its items on that value as every operation reads
        # its receiver (``FloorValue.project_operation_receiver_outcome``): a
        # source call's value is the Call retaining its body's completion, and
        # the loop iterates the one authenticated return it projects (``for x
        # in g()`` over ``return (1, 2)``), as a subscript, an operator or a
        # method call on that Call does.  A Call that projects no single
        # return stays the Call, and its ``iter`` is refused by name.  The
        # recurrence (no live runtime) keeps the presented value's own term.
        def with_iterable(iterable):
            binds, presented = peel_walrus_binds(iterable)
            loop = replace(self, iterable_writes=self._iterable_writes(binds))
            after = written_by(iterable, ctx)
            if self.construction.loop_runtime is None:
                return loop._desugar_with_iterable(presented, after)
            return presented.project_operation_receiver_outcome(
                after, owner="LoopRecurrenceSugar iterable"
            ).and_then(lambda receiver: loop._desugar_with_iterable(receiver, after))

        # A halt of the iterable halted before any item ran: it carries the
        # record of where it halted (``halts_recorded``), onto which the block
        # composition splices what ran before the loop.
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halt_record,
            halts_recorded,
        )

        iterated = halts_recorded(iterable_sugar.desugar(ctx), halt_record(ctx))
        return iterated.and_then(with_iterable)

    def _iterable_writes(self, binds):
        """The iterable's walrus writes (``binds``, ``peel_walrus_binds``
        order) of the names the loop does not carry, each as the rebind of
        the key it wrote (``NamedExpressionValue.written``).  A read of such
        a name after the loop is a reference to that key
        (``Statement._substitute_body_tracked``); the iterable ran once,
        before the loop, so the key holds on every exit, the one where no
        item ran included.  A name carried under its binding coordinate
        leaves as the loop's value (``_publish_runtime_bindings``); one
        published through its post-loop key reads the walrus's key on the
        exit no item wrote it (``nodes._live_loop_publication``)."""
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind

        runtime = self.construction.loop_runtime
        carried = (
            frozenset()
            if runtime is None
            else frozenset(self._coordinate_names(runtime))
        )
        writes = []
        for bind in binds:
            written = bind.written()
            if written is None or bind.name in carried:
                continue
            writes.append(ScopeRebind(*written))
        return tuple(writes)

    def _start(self, runtime, ctx, first):
        """The live loop (a ``for``'s or a ``while``'s) from its first item:
        ``first(runtime_ctx, carried)``, where ``runtime_ctx`` is the context
        the first item begins in, with the header of each carried name bound
        to its pre-loop value, and ``carried`` those values.

        A pre-loop value is an outcome like every other, and the loop is what
        follows it on every face it completes on (``ExitSet.and_then``): under
        that face's guard and faces, owing what it owes -- a read after an
        earlier loop is that loop's exit route under its guard
        (``guarded_binding_read_sugar._read_loop_projection``).  A face that halts halted before the first item: it
        leaves carrying the record of where it halted (``halts_recorded``).
        The pre-loop value is never the loop's outcome in its place: the
        loop runs and publishes on every exit it leaves by."""
        from sugar_lift_py_tests.outcome.exit_set import _require_exit_set
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halt_record,
            halts_recorded,
        )
        from sugar_lift_py_tests.temporal import bind_temporal

        runtime_ctx = ctx
        starts = tuple(
            zip(
                self._carried_evaluations(runtime),
                runtime.initial_value_sugars,
                strict=True,
            )
        )

        def start_from(index, runtime_ctx, initial_values):
            if index == len(starts):
                # The first item begins with the pre-loop values.
                return first(runtime_ctx, initial_values)
            (header, _writes, _else_writes), sugar = starts[index]
            if sugar is None:
                # A name first bound in the loop: its header starts unbound.
                # Nothing is bound under it until an item writes the name,
                # and each item decides its write slot (``_enter_header``).
                return start_from(index + 1, runtime_ctx, (*initial_values, None))

            def bound(initial_value):
                # The pre-loop value is bound under the header's key where
                # the loop stands (``evaluation_here``), outside every item of
                # it: the header's evaluation before the first item.  The name
                # is never written; each item binds its own header to what it
                # begins with (``_enter_header``).
                started = runtime_ctx
                if header is not None:
                    started = bind_temporal(
                        started,
                        evaluation_here(header),
                        initial_value,
                        owner="LoopRecurrenceSugar.pre-loop",
                        blame=str(self.site),
                    )
                return start_from(index + 1, started, (*initial_values, initial_value))

            initial = halts_recorded(sugar.desugar(runtime_ctx), halt_record(ctx))
            initial = _require_exit_set(initial, owner="LoopRecurrenceSugar.pre-loop")
            initial_value = initial.completed_value()
            if initial_value is not None and not initial.owed_items():
                # One unconditional value owing nothing: the loop is exactly
                # what follows it.
                return bound(initial_value)
            return initial.and_then(bound)

        return start_from(0, runtime_ctx, ())

    def _desugar_with_iterable(self, iterable, ctx):
        entering = self._entered_at(ctx)
        if entering is not None:
            return entering._desugar_with_iterable(iterable, ctx)
        runtime = self.construction.loop_runtime
        if iterable is None:
            # A ``while`` iterates nothing: no ``iter`` runs.
            return self._recurrence(None, ctx)

        from sugar_lift_py_tests.operations.iterator_operation import (
            in_hand_iterator,
            in_hand_members,
        )
        from sugar_lift_py_tests.outcome.exit_set import _require_exit_set
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halt_record,
            halts_recorded,
        )

        # The loop's one mechanism (#7757 new 6): its items run one by one
        # here, through the one item runner a comprehension's members run
        # through too (``iterator_operation.advance_in_hand``), where the
        # reduction holds the iterable's members in iteration order within
        # the one unroll budget (``in_hand_members``: a container in hand,
        # the ints a ground ``range(...)`` yields).  Iterating those is
        # decided never to raise, so no ``iter`` is submitted (as
        # ``iterated`` submits none).  Anything else runs as the recurrence
        # below.  No rewrite unrolls the loop before it gets here.  An item
        # hands the next only the names the loop carries: a loop whose item
        # leaves changed a name it does not carry (a name a call in the body
        # may rebind, a ``match`` capture: ``uncarried_item_changes``) never
        # runs in hand, where a later item would read that name as it stood
        # before the loop.  It runs as its recurrence.
        in_hand = runtime is not None and not getattr(
            runtime, "uncarried_item_changes", ()
        )
        members = in_hand_members(iterable) if in_hand else None
        if members is not None:

            def first(runtime_ctx, carried):
                return self._advance_iterator(
                    in_hand_iterator(members),
                    runtime,
                    runtime_ctx,
                    entries=(),
                    carried=carried,
                )

            return self._start(runtime, ctx, first)

        # An iterable whose members the reduction does not hold in order --
        # a symbolic value (a formal, an unknown), a call's result (what the
        # callee returned is its contract's, joined at prove: #7757 steps 5
        # and 6, so its ``iter`` is the undecided read,
        # ``CallSiteValue.iter_with``), a generator pulled where it is
        # consumed (``GeneratorValue``: its pull is stated by its ``next``),
        # a container whose contents are not current
        # (``object_identity.contents_stale``), an instance, a ``str``, a
        # ``set`` -- runs as the recurrence, as a comprehension over such an
        # iterable does (``ComprehensionSugar._recurrence``).  The receiver
        # answers its
        # ``iter`` as it answers
        # ``iter(x)`` (``SymbolicValue.iter_with``, ``ListValue.iter_with``):
        # the one two-faced outcome (``FloorValue.undecided_iteration``), a
        # formal's included -- it waits on no caller's actual (#7757 NEW-1).
        # The loop's recurrence is what follows the face ``iter`` completes
        # on, under its guard and owing what it owes
        # (``ExitSet.and_then``); the face it raises on leaves the loop
        # before any item.  The recurrence stays over the iterable's own
        # term, and steps the iterator ``iter`` completed with
        # (``_recurrence``).  It is the one iterator path a comprehension's
        # recurrence takes too (``iterator_operation.iterated``): where
        # the iteration is decided never to raise
        # (``iterator_operation.iteration_total``) no ``iter`` is submitted.
        from sugar_lift_py_tests.operations.iterator_operation import iterated

        iteration = halts_recorded(
            iterated(iterable, ctx, owner="LoopRecurrenceSugar", site=self.site),
            halt_record(ctx),
        )

        def after_iter(iterator):
            return self._recurrence(iterable, ctx, iterator=iterator)

        return _require_exit_set(iteration, owner="LoopRecurrenceSugar.iter").and_then(
            after_iter
        )

    def _recurrence(self, iterable, ctx, *, iterator=None):
        """The loop as its recurrence over ``iterable`` (None: a ``while``):
        one symbolic item beside the loop exhausted, each name the loop
        writes its fixed point of the loop's step.  For a ``for`` this is
        what follows the completed face of the iterable's ``iter``
        (``_desugar_with_iterable``), never the loop's whole outcome, and
        each item is what follows the faces its ``next`` of ``iterator``
        goes on by (``iterator_operation.stepped``).

        A ``while`` has the symbolic item evaluate its test first
        (``_symbolic_test``, ``_tested``), as a live item does: a halt of
        the test leaves the loop, and the body runs after what the test
        stored.  Where the test reads no binding (its truth decides,
        ``LiveSymbolicItemV1.test_decides``) a truth decided false leaves by
        exhaustion and runs no item; a truth decided true runs the item with
        no exhaustion arm at all (an arm that falls through goes round
        again); each decided path publishes the exit it left by
        (``_exit_decision``), which a read after the loop selects by
        (``guarded_binding_read_sugar.decided_loop_exit``).  An undecided
        truth, and the truth of a test that reads a binding (its value at
        the symbolic item is not its value at every item), runs the item
        under the test's slot guard."""
        runtime = self.construction.loop_runtime

        from sugar_lift_py_tests.floor import InvValue

        # The recurrence's value of each name the loop writes: one head per
        # name, keyed by what a read after the loop reads it through -- its
        # binding coordinate (``binding_coordinate_cids``), or its post-loop
        # key (``LiveForRuntimeV1.published_evaluations``) -- each the fixed
        # point of the loop's step over the iterable.
        heads = tuple(
            self._recurrence_head(coordinate_cid)
            for coordinate_cid in self.binding_coordinate_cids
        )
        post_keys = tuple(
            post_key
            for post_key, _writes, _else_writes in getattr(
                runtime, "published_evaluations", ()
            )
        )
        post_heads = tuple(self._recurrence_head(post_key) for post_key in post_keys)
        recurrences = []
        for h in (*heads, *post_heads):
            step = ctor(
                "python:loop.step",
                [
                    h,
                    str_const(self.loop_construction_cid),
                    *(
                        ()
                        if iterable is None
                        else (iterable.to_term(owner="LoopRecurrenceSugar"),)
                    ),
                ],
                symbol_kind="coordinate",
            )
            recurrences.append(InvValue(atomic("=", [h, step]), self.site))
        recurrences = tuple(recurrences)
        # The loop leaves publishing what a concrete loop publishes
        # (``_publication``): each coordinate name's value under its binding
        # coordinate, and each other written name's under its post-loop key,
        # with its write slot decided -- here as the guard that some item
        # wrote it, which the symbolic iterable does not decide true or false.
        posted = tuple(
            (
                post_key,
                SymbolicValue(h),
                atomic(
                    "python.loop.wrote",
                    [str_const(self.target_cid), str_const(post_key)],
                ),
            )
            for post_key, h in zip(post_keys, post_heads, strict=True)
        )
        published = (
            *recurrences,
            *self._publication(tuple(SymbolicValue(h) for h in heads), posted),
        )

        def published_after_else(context, decided=()):
            # After the ``else`` suite ran (``context``, where it left), a
            # name is what the suite last wrote it to, as a concrete loop's
            # is (``_after_else``, ``_post_loop_writes``).
            return (
                *recurrences,
                *self._publication(
                    *self._after_symbolic_else(runtime, context, posted)
                ),
                *decided,
            )

        def recurrence(entries=(), *, halt=None, can_fall_through=True, decided=()):
            # The loop leaves as its recurrence with what the item it leaves
            # from left (``entries``), as a concrete loop leaves with what its
            # items left (``_left_with``); no item: nothing.  The recurrence
            # (``recurrences``) is what the items before it did, on every
            # exit; the loop publishes where it leaves as a loop (a fall
            # through, its own ``break``/``continue``, no item), never where
            # a ``return`` (``can_fall_through`` false) or another halt
            # (``halt``) leaves from inside the item, as a concrete item's
            # do (``_after_iteration_state``, ``_after_loop_control``).
            # ``decided``: the exit this path left by, where the symbolic
            # item's test decided it (``_exit_decision``), published with the
            # rest as a concrete loop's is.
            if halt is None and can_fall_through:
                return self._left_with(entries, (*published, *decided))
            return self._left_with(
                entries, recurrences, halt=halt, can_fall_through=can_fall_through
            )

        # The loop's ``else`` suite runs once, outside every item, where the
        # loop is exhausted: after an item that falls through or continues,
        # and where no item ran -- never after a ``break``.  It reduces once
        # (``_symbolic_else``), and each exhausted arm leaves beneath its
        # faces, as a concrete loop's (``_finish_iterator``).
        else_ctx, otherwise = self._symbolic_else(runtime, ctx, heads)
        witnesses = _else_witnesses(runtime, else_ctx)

        def exhausted(entries=(), *, decided=()):
            if otherwise is None:
                return recurrence(entries, decided=decided)
            from sugar_lift_py_tests.sugar.function_universe_sugar import (
                past_prior_returns,
            )

            def after_suite(record):
                # The calls' records the suite made follow the items' (in
                # ``entries``): they leave with the loop (#7757 H7).
                return self._left_with(
                    (
                        *entries,
                        *record.entries,
                        *self._records_made_here(record.context),
                    ),
                    published_after_else(record.context, decided),
                    fall_through=record.fall_through,
                    can_fall_through=record.can_fall_through,
                )

            def leave_after_else(otherwise):
                # A completed face of the suite that falls through after a
                # guarded ``return`` leaves by that ``return`` as its own arm,
                # and as a loop only under the guard that it was not taken
                # (``past_prior_returns``), as a concrete loop's ``else``
                # does (``_finish_iterator``).
                return otherwise.and_then(
                    lambda state: past_prior_returns(
                        state, state.context, after_suite, after_suite
                    ),
                    consume=lambda halt: self._left_with(
                        entries,
                        published_after_else(
                            _else_left_from(
                                runtime, else_ctx, witnesses, halt, site=self.site
                            ),
                            decided,
                        ),
                        halt=halt,
                    ),
                )

            from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

            return leave_after_else(
                _require_exit_set(otherwise, owner="LoopRecurrenceSugar.else")
            )

        # The item's target unpack runs first: the item's body (and the
        # recurrence) are what follows its completed arm
        # (``ExitSet.and_then``), and its halt (too few, too many, not
        # iterable) leaves the loop with what the items before it did, as
        # every halt does (``recurrence``).
        projected, enter, item = self._enter_symbolic_item(
            runtime, ctx, iterable, heads
        )

        # The symbolic item runs the body once, whether or not it has a
        # ``return``/``raise``, through the one block composition a concrete
        # item and a function body use (``reduce_block_to_exitset``), in the
        # item's context: what it stores, mutates, owes and splits on is the
        # loop's, as a concrete item's is.  Its reads of a carried name and of
        # the target are references to their keys (``For.substitute``), bound
        # here for that item exactly as for a concrete one
        # (``_enter_symbolic_item``); its reads of what an earlier statement of
        # the body wrote (an inner loop's publication) are bound by that
        # statement, which ran ahead of it.  The loop's exits are the arms of
        # that one run (``_leave_symbolic_item``).
        body_sugars, item_guard = self._symbolic_item()
        test_sugar, test_decides = self._symbolic_test()

        def run_body(item_ctx, target_bindings, guard, left, left_exhausted):
            from sugar_lift_py_tests.sugar.function_universe_sugar import (
                reduce_block_to_exitset,
            )

            with item():
                body = reduce_block_to_exitset(body_sugars, item_ctx)
            return self._leave_symbolic_item(
                body,
                left,
                guard,
                target_bindings=target_bindings,
                exhausted=left_exhausted,
            )

        def after_symbolic_test(face, target_bindings):
            # One completed face of the test the symbolic item evaluated
            # (``_WhileTest``): what its evaluation stored (``face.entries``)
            # leads every way the loop leaves from it, and the body runs in
            # the context after it (``face.ctx``), as a live item's does
            # (``_after_test``, ``_with_body``).
            from sugar_lift_py_tests.outcome.exit_set import _is_false, _is_true

            ahead = tuple(face.entries)
            # A test that reads a binding decides nothing at every item from
            # its truth here (``LiveSymbolicItemV1.test_decides``): the item
            # runs under its slot guard, after what it stored.
            truth = face.formula if test_decides else None
            if truth is not None and _is_false(truth):
                # Decided false at every item: no item runs.  The loop leaves
                # by exhaustion, decided on this path.
                return exhausted(ahead, decided=(self._exit_decision(True),))
            if truth is not None and _is_true(truth):
                # Decided true at every item: an item always runs, and the
                # loop never leaves by exhaustion.  An arm of the item that
                # falls through or continues goes round again: it leaves the
                # loop by no arm (the empty set).  Its own ``break`` leaves,
                # decided on that path; a ``return`` or a halt leaves as it
                # does from any item.
                decided = (self._exit_decision(False),)
                return run_body(
                    face.ctx,
                    target_bindings,
                    truth,
                    lambda entries=(), **leaving: recurrence(
                        (*ahead, *entries), decided=decided, **leaving
                    ),
                    lambda entries=(): ExitSet(()),
                )
            # Not decided here: the item runs under the test's slot guard,
            # the no-item arm under its negation, both owed as before.
            return run_body(
                face.ctx,
                target_bindings,
                item_guard,
                lambda entries=(), **leaving: recurrence((*ahead, *entries), **leaving),
                lambda entries=(): exhausted((*ahead, *entries)),
            )

        def run_item(projections):
            item_ctx, target_bindings = enter(projections)
            if test_sugar is None:
                # The item may follow items whose calls changed a module
                # global: it begins from the loop's record of the globals
                # (``entering_the_recurrence``, #7757 H7).
                return run_body(
                    entering_the_recurrence(self.target_cid, item_ctx),
                    target_bindings,
                    item_guard,
                    recurrence,
                    exhausted,
                )
            # A ``while`` (``LiveSymbolicItemV1.test_sugar``): the test runs
            # first, in the item, through the one rule a live item's test
            # runs by (``_tested``).  Each halt of it leaves the loop with
            # what the items before it did (``recurrence``), as a live
            # item's test halt does (``_test_item``); each completed face
            # decides, or not, whether the item runs.
            if item_ctx is None:
                from sugar_lift_py_tests.context import ReduceContext

                item_ctx = ReduceContext.root(owner="LoopRecurrenceSugar.symbolic-test")
            # The test, and the body after it, begin from the loop's record
            # of the globals, as a ``for``'s item does.
            item_ctx = entering_the_recurrence(self.target_cid, item_ctx)
            with item():
                tested = self._tested(test_sugar, item_ctx)
            return tested.and_then(
                lambda face: after_symbolic_test(face, target_bindings),
                consume=lambda halt: recurrence(halt=halt),
            )

        from sugar_lift_py_tests.outcome import Completed

        def items():
            if len(projected.exits) == 1 and isinstance(projected.exits[0], Completed):
                # One way in (a name target, a ``while``): the item is exactly
                # what follows it.
                return projected.and_then(run_item)
            return projected.and_then(
                run_item, consume=lambda halt: recurrence(halt=halt)
            )

        if iterable is None:
            # A ``while`` steps no iterator: its test decides each item.
            return items()
        # Each item is what follows its ``next`` (the one iterator path a
        # comprehension's recurrence takes too, ``iterator_operation.stepped``):
        # the item runs on its value face, the loop leaves exhausted on its
        # ``StopIteration``, and its halt -- an undecided raise of an
        # iterator whose ``__next__`` is not decided here, on any step --
        # leaves the loop with what the items before it did
        # (``recurrence``), as the live loop's ``next`` halt does
        # (``_advance_iterator``).  Where the iteration's type is decided
        # and its ``__next__`` cannot raise there is no step: the items
        # alone.
        from sugar_lift_py_tests.operations.iterator_operation import stepped
        from sugar_lift_py_tests.sugar.function_universe_sugar import halt_record

        return stepped(
            iterable,
            iterator,
            ctx,
            items,
            owner="LoopRecurrenceSugar",
            site=self.site,
            exhausted=exhausted,
            record=halt_record(ctx),
            left=lambda halt: recurrence(halt=halt),
        )

    def _symbolic_item(self):
        """``(body_sugars, guard)``: the body the recurrence's one symbolic
        item runs, and the guard under which an item runs at all (the loop's
        ``BodyFallthrough`` guard: some item is reached, or the ``while``
        test holds), from the construction
        (``live_loop_construction.LiveSymbolicItemV1``).  A construction that
        handed none is refused by name: no body is made up in its place."""
        symbolic_item = getattr(self.construction, "symbolic_item", None)
        if symbolic_item is None:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner="LoopRecurrenceSugar.symbolic-item",
                blame=self.site,
                observed="a symbolic loop with no symbolic item to run",
                requested="the loop body and its item guard from the construction",
                fix=(
                    "construct the loop through construct_live_loop_recurrence, "
                    "which hands its body to the symbolic item"
                ),
            )
        return symbolic_item.body_sugars, symbolic_item.guard

    def _symbolic_test(self):
        """``(test_sugar, decides)``: the ``while`` test the recurrence's
        symbolic item evaluates before its body
        (``live_loop_construction.LiveSymbolicItemV1.test_sugar``), None for
        a ``for``; and whether its truth there decides the item
        (``LiveSymbolicItemV1.test_decides``): False for a test that reads a
        binding, whose value at the symbolic item is not its value at every
        item -- it is evaluated all the same, and its halts leave the loop.
        The construction hands it undecided; its truth is decided here, by
        the one rule a live item's test takes (``_tested``), never by the
        rewrite."""
        symbolic_item = getattr(self.construction, "symbolic_item", None)
        return (
            getattr(symbolic_item, "test_sugar", None),
            getattr(symbolic_item, "test_decides", False) is True,
        )

    def _recurrence_starts(self, runtime, heads):
        """The value each carried name (``runtime.carried_names`` order) has
        where the recurrence stands: its recurrence value -- the fixed point
        of the loop's step under the key a read after the loop reads it
        through, the one value ``_recurrence`` states and publishes for it.

        - a name carried under a binding coordinate: ``heads`` (in
          coordinate order), the head of its coordinate;
        - a name carried through its header alone (a module binding, a name
          first bound in the loop, a ``nonlocal`` cell): the head of its
          post-loop key (``published_evaluations``, ``loop_post_writes``:
          its header's key), the head ``_recurrence`` publishes it under.

        An item may follow earlier items, so it begins with what they handed
        on, never with the value before the loop: the recurrence's value,
        which nothing decides, so a read of it owes the undecided member
        (``read_of_bound_value``).  A name first bound in the loop keeps its
        write slot undecided (``_enter_header``, ``decide``): both its arms
        stand, the ``NameError`` where no earlier item wrote it included.

        None only for a carried name the loop publishes under no key, whose
        header is then left unbound and a read of it refused by name."""
        by_name = dict(zip(self._coordinate_names(runtime), heads, strict=True))
        for name, (post_key, _writes, _else_writes) in zip(
            getattr(runtime, "published_names", ()),
            getattr(runtime, "published_evaluations", ()),
            strict=True,
        ):
            if by_name.get(name) is None:
                by_name[name] = self._recurrence_head(post_key)
        return tuple(
            None if by_name.get(name) is None else SymbolicValue(by_name[name])
            for name in runtime.carried_names
        )

    def _symbolic_else(self, runtime, ctx, heads):
        """``(else_ctx, otherwise)``: the ``else`` suite of a loop run as its
        recurrence, reduced once (``otherwise``), outside every item, where
        the loop is exhausted, and the context it began in (``else_ctx``);
        ``(None, None)`` when it has none.  It reads each carried name
        through its header, bound here to
        the recurrence's value of it (``_recurrence_starts``), as a concrete
        loop's ``else`` reads what the last item handed on
        (``_finish_iterator``); whether an earlier item wrote a name first
        bound in the loop is not known here, so its write slot is left
        undecided (``decide``).  The target's key is not bound: no item is
        known to be the last, so a read of the target there is refused by
        name, never made up."""
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        else_sugars = () if runtime is None else getattr(runtime, "else_sugars", ())
        if not else_sugars:
            return None, None
        if ctx is None:
            from sugar_lift_py_tests.context import ReduceContext

            ctx = ReduceContext.root(owner="LoopRecurrenceSugar.symbolic-else")
        if hasattr(ctx, "temporal"):
            ctx = self._enter_header(
                runtime, ctx, self._recurrence_starts(runtime, heads), decide=False
            )
            # The suite may run after items whose calls changed a module
            # global: it begins from the loop's record of the globals, as
            # the symbolic item does (``entering_the_recurrence``, #7757 H7).
            ctx = entering_the_recurrence(self.target_cid, ctx)
        return ctx, reduce_block_to_exitset(tuple(else_sugars), ctx)

    def _after_symbolic_else(self, runtime, context, posted):
        """``(coordinate_values, posted)`` (``_publication``) of a loop run as
        its recurrence, leaving its ``else`` suite where ``context`` holds
        what the suite did: each coordinate name is the latest of the
        suite's writes of it and its header, bound to the recurrence's value
        (``_after_else``); each name published through its post-loop key is
        the suite's latest write of it, its write slot decided true, or, the
        suite not having written it, as ``posted`` holds it (the
        recurrence's value under the guard that some item wrote it)."""
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here

        left = self._after_else(runtime, context)
        latest = dict(zip(runtime.carried_names, left, strict=True))
        values = []
        for name in self._coordinate_names(runtime):
            value = latest[name]
            if value is None:
                raise TypeError("loop recurrence omitted a carried binding")
            values.append(value)
        temporal = context.temporal
        written = []
        for (post_key, _writes, else_writes), entry in zip(
            getattr(runtime, "published_evaluations", ()), posted, strict=True
        ):
            keys = tuple(evaluation_here(key) for key in else_writes)
            binding = temporal.latest(*keys) if keys else None
            if binding is not None:
                entry = (post_key, binding.value, True)
            written.append(entry)
        return tuple(values), tuple(written)

    def _leave_symbolic_item(
        self, body, recurrence, guard, *, target_bindings, exhausted=None
    ):
        """The loop's exits from the one run of the symbolic item's
        ``body`` (``reduce_block_to_exitset``'s arms), under ``guard``
        (an item runs), beside the loop exhausted under its negation (no item
        runs).  ``recurrence(entries, *, halt=None, can_fall_through=True)``
        is the loop leaving with ``entries``, what the item left
        (``_left_with``): as its recurrence, or by ``halt``, or by a
        ``return``; ``exhausted(entries)`` is the loop leaving as its
        recurrence where its iterator is exhausted, through its ``else``
        suite when it has one (``recurrence`` when none is handed); where a
        ``while`` test is decided true at every item it is the empty set: the
        loop goes round again and never leaves by exhaustion.

        Each arm leaves as a concrete item's does (``_after_iteration_state``,
        ``_after_loop_control``): an arm that does not fall through (a
        ``return``) leaves the loop with its entries; an arm that falls
        through leaves exhausted with its entries -- every store, container
        mutation and rebind the item made, as a concrete item's fall-through
        hands its entries on to the loop's publication -- and this loop's
        own ``break`` leaves as the recurrence, its ``continue`` exhausted,
        with the entries of its halt's record, what the item did before it,
        once the record's context is authenticated as this item's
        (``_require_loop_control_state`` against ``target_bindings``, what
        ``_enter_symbolic_item`` bound), as a concrete item's does; any
        other halt (a ``raise``, an inner loop's or a call's, an enclosing
        loop's ``break``/``continue``) leaves with its record and what the
        items before it did (``recurrence(halt=...)``), as a concrete
        item's does.  Every arm keeps the guard, partition faces and
        ``owed`` of the item's arm it continues (``ExitSet.and_then``).  An
        arm that falls through after
        an earlier guarded ``return`` took its exit where that return's guard
        held: it is split as the block composition splits a later halt
        (``past_prior_returns``), the returned arm with its entries, the
        recurrence under the fall-through guard without the ``return``
        entries that guard excludes.  Each exit is an arm of the
        one run, so each is reported once."""
        from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
        from sugar_lift_py_tests.outcome import Completed
        from sugar_lift_py_tests.outcome.exit_set import _require_exit_set
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            past_prior_returns,
        )

        if exhausted is None:
            exhausted = recurrence

        def left(record):
            # What the item left, and the calls' records it made after the
            # record it began with, which leave with the loop on every exit
            # it completes by (``_records_made_here``, #7757 H7).  A halt
            # holds them already, in the context it halted in.
            return (
                *record.entries,
                *self._records_made_here(getattr(record, "context", None)),
            )

        def returned(block):
            return recurrence(left(block), can_fall_through=False)

        def leave(state):
            if not state.can_fall_through:
                return returned(state)
            # The loop goes on under the guard that no earlier ``return`` of
            # the item was taken, and that ``return`` took its exit beside
            # it: the one composition a block gives a statement after a
            # guarded ``return`` (``past_prior_returns``).
            return past_prior_returns(
                state,
                state.context,
                lambda record: exhausted(left(record)),
                returned,
            )

        def own_control(halt):
            effect = halt.effect
            if (
                isinstance(effect, LoopControlEffect)
                and effect.target_cid == self.target_cid
            ):
                record = LoopRecurrenceSugar._require_loop_control_state(
                    halt.state, target_bindings=target_bindings
                )
                if effect.action == "break":
                    return recurrence(left(record))
                return exhausted(left(record))
            return recurrence(halt=halt)

        def compose(body):
            # No item runs (the guard's negation): the loop leaves exhausted;
            # an item runs (the guard): the loop leaves from its arms.
            ran = ExitSet((Completed(not_(guard), False), Completed(guard, True)))

            def after(item_ran):
                if item_ran:
                    return body.and_then(leave, consume=own_control)
                return exhausted()

            return ran.and_then(after)

        return compose(
            _require_exit_set(body, owner="LoopRecurrenceSugar.symbolic-item")
        )

    def _advance_iterator(self, iterator, runtime, ctx, *, entries, carried, index=0):
        """Run item ``index`` of the live loop.

        ``carried`` is the value of each carried name (``runtime.carried_names``
        order) the item begins with: the pre-loop values for the first item,
        the previous item's latch (``_latched``) after it.  An item handed
        nothing for the names it carries is refused by name
        (``_require_carried``): the names are never read in its place.

        The item is stepped by the one item runner a comprehension's members
        are stepped by too (``iterator_operation.advance_in_hand``, #7757 new
        6): its ``next``, read arm by arm.  A halt of it halted where the
        items before it left (``ctx``): it carries that record
        (``halts_recorded``).  Exhaustion is this loop's own control: the
        loop consumes the ``StopIteration`` and leaves beneath it, under its
        guard and faces, owing what the exhausting ``next`` owed, through its
        ``else`` suite (``_finish_iterator``).  Any other halt of the
        ``next`` leaves the loop with what the items before it did
        (``_left_with``).  The value runs the item (``_run_item``).
        """
        from sugar_lift_py_tests.operations.iterator_operation import (
            advance_in_hand,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import halt_record

        return advance_in_hand(
            iterator,
            ctx,
            index=index,
            owner="LoopRecurrenceSugar",
            site=self.site,
            record=halt_record(ctx),
            item=lambda value, advanced: self._run_item(
                value,
                advanced,
                runtime,
                ctx,
                entries=entries,
                carried=carried,
                index=index,
            ),
            exhausted=lambda: self._finish_iterator(
                runtime, ctx, entries=entries, carried=carried, items=index
            ),
            left=lambda halt: self._left_with(entries, (), halt=halt),
        )

    def _run_item(self, value, advanced, runtime, ctx, *, entries, carried, index):
        """Item ``index`` of the live loop on the member ``value`` its
        ``next`` yielded: the target unpacked, the body run, and the next
        item stepped from ``advanced`` (``_advance_iterator``)."""
        from dataclasses import replace

        from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment
        from sugar_lift_py_tests.outcome import Halted
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halt_record,
            reduce_block_to_exitset,
        )

        # The item's unpack is the item's own evaluation, inside its segment
        # as the body is (and as a comprehension member's unpack is,
        # ``ComprehensionSugar._run_in_hand``, and the symbolic item's,
        # ``_enter_symbolic_item``): two items' unpacks of a symbolic member
        # are two keys, never one.
        with entered(loop_iteration_segment(self.target_cid, index)):
            projected = self._project_iteration_target(
                runtime.target_pattern, value, ctx
            )
            # On a halted arm assignment has not begun: the positional-unpack
            # Floor owns the halt, and its record is the empty one in the
            # exact context entering this iteration (``halt_record``).  The
            # item runs beneath each completed arm: one plain roster, or the
            # completed face of a symbolic member's runtime unpack beside its
            # halt.
            projected = ExitSet(
                tuple(
                    replace(face, state=halt_record(ctx))
                    if isinstance(face, Halted)
                    else face
                    for face in projected.exits
                )
            ).normalize()

        def resume(ctx, *, entries, carried, index):
            # The next item takes the iterator's next element.
            return self._advance_iterator(
                advanced,
                runtime,
                ctx,
                entries=entries,
                carried=carried,
                index=index,
            )

        def run_item(projections):
            # Each iteration is its own evaluation of the body's sites: a call
            # in iteration 2 is never claimed to complete exactly when
            # iteration 1's did (the unrolled loop's law, sugar/loop iteration
            # segments).  Its statement evaluations are its own keys too
            # (``evaluation_here``), its reads of a carried name read this
            # item's header, and its reads of the target read this item's
            # projection, bound under the target's key after the header (a
            # carried target's header is that key).
            with entered(loop_iteration_segment(self.target_cid, index)):
                iteration_ctx = self._enter_header(runtime, ctx, carried)
                iteration_ctx, target_bindings = self._enter_target(
                    runtime, iteration_ctx, projections
                )
                body = reduce_block_to_exitset(runtime.body_sugars, iteration_ctx)
            return self._after_item(
                body, runtime, target_bindings, resume, entries=entries, index=index
            )

        projections = projected.completed_value()
        if projections is not None:
            # One plain roster: the item is exactly what follows it.
            return run_item(projections)
        # The unpack's halt leaves the loop with what the items before it
        # did (``_left_with``).
        return projected.and_then(
            run_item, consume=lambda halt: self._left_with(entries, (), halt=halt)
        )

    def _after_item(self, body, runtime, target_bindings, resume, *, entries, index):
        """The loop's outcome after item ``index``'s ``body`` reduced, for a
        live ``for`` and a live ``while`` alike.  ``resume(ctx, entries=,
        carried=, index=)`` runs the next item: the iterator's next element,
        or the test evaluated again."""
        from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

        def after_body(body):
            # Each face of this iteration is its own path, and what follows it
            # runs beneath it (``ExitSet.and_then``): a completed face carries
            # its own state into the next iteration, this loop's own
            # break/continue is consumed and continues, any other halt leaves
            # the loop with what the items before it did and its own record
            # (``_after_loop_control``). The first iteration's faces are never
            # the loop's outcome.
            if len(body.exits) != 1:
                return body.and_then(
                    lambda state: self._after_iteration_state(
                        state, runtime, resume, entries=entries, index=index
                    ),
                    consume=lambda halt: self._after_loop_control(
                        halt,
                        runtime,
                        target_bindings,
                        resume,
                        entries=entries,
                        index=index,
                    ),
                )
            face = body.exits[0]
            following = self._after_iteration_face(
                face,
                runtime,
                target_bindings,
                resume,
                entries=entries,
                index=index,
            )
            # The one face, whichever kind, continues into ``following``.
            return body.and_then(
                lambda _state: following, consume=lambda _halt: following
            )

        return after_body(_require_exit_set(body, owner="LoopRecurrenceSugar.body"))

    def _after_iteration_face(
        self, face, runtime, target_bindings, resume, *, entries, index
    ):
        """The loop's outcome after one face of an iteration."""
        from sugar_lift_py_tests.outcome import Halted

        if isinstance(face, Halted):
            return self._after_loop_control(
                face,
                runtime,
                target_bindings,
                resume,
                entries=entries,
                index=index,
            )
        return self._after_iteration_state(
            face.value, runtime, resume, entries=entries, index=index
        )

    def _after_loop_control(
        self, halt, runtime, target_bindings, resume, *, entries, index
    ):
        """The loop's outcome after a halted iteration face.

        The halt's record holds what the item did before it (every store,
        container mutation and rebind, spliced on by the block composition
        that ran it): they join what the earlier items left (``entries``),
        as a completed item's do (``_after_iteration_state``).  On this
        loop's own ``break``/``continue`` the loop goes on, or leaves, with
        them, from the record's authenticated context; any other halt (a
        ``raise``, a call's halt, an enclosing loop's ``break``/``continue``)
        leaves the loop with them, through the one carry (``_left_with``)."""
        from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect

        effect = halt.effect
        if (
            isinstance(effect, LoopControlEffect)
            and effect.target_cid == self.target_cid
        ):
            record = self._require_loop_control_state(
                halt.state,
                target_bindings=target_bindings,
            )
            state = record.context
            combined = (*entries, *record.entries)
            if effect.action == "continue":
                return resume(
                    state,
                    entries=combined,
                    carried=self._latched(runtime, state, index),
                    index=index + 1,
                )
            if effect.action == "break":
                return self._publish_runtime_bindings(
                    runtime,
                    state,
                    entries=combined,
                    carried=self._latched(runtime, state, index),
                    items=index + 1,
                    exhausted=False,
                )
        return self._left_with(entries, (), halt=halt)

    def _after_iteration_state(self, state, runtime, resume, *, entries, index):
        """The loop's outcome after a completed iteration face whose record is
        ``state``: a ``return`` leaves the loop with what the items left,
        through the one carry (``_left_with``).

        An item that falls through after a guarded ``return`` (``if x == c:
        return x``) took that ``return`` where its guard held: the next item
        -- and, after the last, the loop's exit -- runs only under the guard
        that it was not taken, and the ``return`` leaves the loop as its own
        arm beside it, through the one composition a block gives a statement
        after a guarded ``return`` (``past_prior_returns``). So a later
        ``return`` never stands beside it unguarded."""
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            past_prior_returns,
        )

        def returned(record):
            # The calls' records the items made leave with the ``return``,
            # for a ``finally`` that runs after it (``_records_made_here``).
            return self._left_with(
                (*entries, *record.entries),
                self._records_made_here(getattr(record, "context", None)),
                can_fall_through=False,
            )

        if not state.can_fall_through:
            return returned(state)

        def goes_on(record):
            return resume(
                record.context,
                entries=(*entries, *record.entries),
                carried=self._latched(runtime, record.context, index),
                index=index + 1,
            )

        return past_prior_returns(state, state.context, goes_on, returned)

    def _desugar_while(self, runtime, ctx):
        """A live ``while``: its first item begins with the pre-loop values
        (``_start``).  A test that does not decide where the first item
        begins leaves the loop its recurrence, as a ``while`` whose items do
        not run (``_desugar_with_iterable``)."""
        entering = self._entered_at(ctx)
        if entering is not None:
            return entering._desugar_while(runtime, ctx)
        return self._start(
            runtime,
            ctx,
            lambda runtime_ctx, carried: self._test_item(
                runtime, runtime_ctx, entries=(), carried=carried, index=0, before=ctx
            ),
        )

    def _test_item(self, runtime, ctx, *, entries, carried, index, before=None):
        """Run item ``index`` of a live ``while``: bind its header to what the
        previous item handed on (``carried``), evaluate the test there, and
        run the body under every face whose truth is true.  A face whose
        truth is false leaves the loop (``_after_test``).

        The test decides each face or the loop does not run as items: at the
        first item an undecided test leaves the loop its recurrence (``before``
        is the context the loop began in); after an item ran, an undecided
        test is refused by name, never guessed true or false.  So is a loop
        whose test has not decided false within ``runtime.fuel`` items."""
        from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment
        from sugar_lift_py_tests.outcome import Completed
        from sugar_lift_py_tests.outcome.exit_set import _is_false, _is_true
        from sugar_source_tree.panic import SugarNotWritten

        if index >= runtime.fuel:
            raise SugarNotWritten(
                owner="LoopRecurrenceSugar.while",
                blame=self.site,
                observed=(
                    f"a live while ran {index} items without its test deciding "
                    "false"
                ),
                requested="the item at which the test decides false, or a break",
                fix=(
                    "decide the loop's exit from what its items hand on; never "
                    "cut the loop short"
                ),
            )
        with entered(loop_iteration_segment(self.target_cid, index)):
            item_ctx = self._enter_header(runtime, ctx, carried)
            # The test is evaluated before every item (``_tested``).
            tested = self._tested(runtime.test_sugar, item_ctx)
            undecided = any(
                isinstance(face, Completed)
                and not (
                    _is_true(face.value.formula) or _is_false(face.value.formula)
                )
                for face in tested.exits
            )
            if not undecided:
                # Each true face runs the body in this item, after the test.
                tested = tested.and_then(
                    lambda item: ExitSet.completed(self._with_body(item, runtime))
                )
        if undecided and index == 0:
            return self._desugar_with_iterable(None, before)
        if undecided:
            raise SugarNotWritten(
                owner="LoopRecurrenceSugar.while",
                blame=self.site,
                observed=(
                    f"undecided while test at item {index}: its truth is not "
                    "decided by what the previous item handed on"
                ),
                requested="a decided truth of the test at every item",
                fix=(
                    "carry the testimony that decides the test into the item; "
                    "never guess the loop continues or stops"
                ),
            )
        # A halt of the test leaves the loop with what the items before it
        # did (``_left_with``).
        return tested.and_then(
            lambda item: self._after_test(item, runtime, entries=entries, index=index),
            consume=lambda halt: self._left_with(entries, (), halt=halt),
        )

    def _tested(self, test_sugar, ctx):
        """A ``while`` test evaluated once in ``ctx``: the one way the test
        runs, at a live item (``_test_item``) and at the recurrence's
        symbolic item (``_recurrence``) alike.  Each evaluation is that
        item's header (``_WhileItemTestV1``): a walrus bind or callee store
        its value carried reaches the body and the loop's exit by the one
        header rule (``header_applied``), the stores laid in the item's
        record (``_WhileTest.entries``), after the items before it.  Each
        completed face is a ``_WhileTest`` whose truth the one truth rule
        took (``truth_of``); each halt carries the record of where the item
        began (``halts_recorded``)."""
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            header_applied,
        )

        item = _WhileItemTestV1(test_sugar, self.site)
        headed, test = header_applied(item, "test", ctx)
        return headed if headed is not None else item.faces(test, ctx)

    @staticmethod
    def _with_body(item, runtime):
        """A true face of the test with the body reduced in its context (in
        the item the caller has entered); a false face as it is."""
        from dataclasses import replace

        from sugar_lift_py_tests.outcome.exit_set import _is_true
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        if not _is_true(item.formula):
            return item
        return replace(
            item, body=reduce_block_to_exitset(runtime.body_sugars, item.ctx)
        )

    def _after_test(self, item, runtime, *, entries, index):
        """The loop's outcome after item ``index``'s test decided: false
        leaves the loop with what the test left each carried name (the
        previous item's latch, or a walrus in the test), through the ``else``
        suite (``_finish_iterator``); true continues from the body as a live
        ``for``'s item does (``_after_item``).  Either way what the test's
        evaluation stored (``item.entries``) follows what the items before it
        did and leads what follows it."""
        from sugar_lift_py_tests.outcome.exit_set import _is_false

        entries = (*entries, *item.entries)
        if _is_false(item.formula):
            # Item ``index`` evaluated the test: a walrus in it wrote there,
            # so the items the loop leaves after are ``index + 1``.
            return self._finish_iterator(
                runtime,
                item.ctx,
                entries=entries,
                carried=self._latched(runtime, item.ctx, index),
                items=index + 1,
            )

        def resume(ctx, *, entries, carried, index):
            # The next item evaluates the test again.
            return self._test_item(
                runtime, ctx, entries=entries, carried=carried, index=index
            )

        return self._after_item(
            item.body, runtime, (), resume, entries=entries, index=index
        )

    @staticmethod
    def _coordinate_names(runtime):
        """The carried names the loop publishes under their binding
        coordinates (``binding_coordinate_cids`` order,
        ``LiveForRuntimeV1.coordinate_names``); a runtime that names none
        apart publishes every carried name so.  Every other carried name is
        published through its post-loop key (``_post_loop_writes``)."""
        return tuple(getattr(runtime, "coordinate_names", runtime.carried_names))

    @staticmethod
    def _carried_evaluations(runtime):
        """``(header, writes, else_writes)`` per carried name; a runtime that
        names none has no header and no writes for any name."""
        triples = tuple(getattr(runtime, "carried_evaluations", ()))
        if len(triples) != len(runtime.carried_names):
            return tuple((None, (), ()) for _ in runtime.carried_names)
        return triples

    def _require_carried(self, runtime, carried):
        """``carried``: the value of each carried name an item begins with or
        the loop leaves with (the pre-loop values, an item's latch, what the
        ``else`` suite left).  Handed nothing, a loop that carries no name
        carries the empty tuple; one that carries names is refused by name.
        The names are never read in its place: nothing writes them."""
        if carried is not None:
            return carried
        if not runtime.carried_names:
            return ()
        from sugar_source_tree.panic import SugarNotWritten

        names = ", ".join(f"`{name}`" for name in runtime.carried_names)
        raise SugarNotWritten(
            owner="LoopRecurrenceSugar",
            blame=self.site,
            observed=(
                f"a live loop item entered or left with no value handed on for "
                f"the names it carries ({names})"
            ),
            requested=(
                "the pre-loop values, the previous item's latch, or what the "
                "else suite left, handed to the item"
            ),
            fix=(
                "enter every item through the recurrence, which hands it what "
                "it carries; never read the carried names in its place"
            ),
        )

    def _enter_header(self, runtime, ctx, carried, *, decide=True):
        """Bind the header evaluation of each carried name: the value an item
        begins with (``carried``), under the header's key qualified by where
        it is bound (``evaluation_here``): inside an item (the caller has
        entered it), that item's header; after the last item, the header the
        ``else`` suite reads, outside every item.  The body's and the else's
        reads of a carried name are references to it (``For.substitute``).

        A name first bound in the loop (no pre-loop value:
        ``initial_value_sugars``) is read as ``<header> if <an item wrote
        it> else <unbound>`` (``nodes._loop_header_bindings``): its header's
        write slot (``loop_write_slot``) is decided here, true exactly when
        an earlier item handed it a value, so a read before any write is a
        ``NameError``.  The recurrence's symbolic item does not know whether
        an earlier item wrote it (``decide`` false): the slot stays
        undecided there."""
        from sugar_lift_py_tests.floor.branch_result_coordinate import (
            BranchResultDecision,
        )
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here
        from sugar_lift_py_tests.temporal import bind_temporal
        from sugar_source_tree.binding_state import loop_write_slot

        carried = self._require_carried(runtime, carried)
        if ctx is None:
            return ctx
        starts = tuple(getattr(runtime, "initial_value_sugars", ()))
        for index, ((header, _writes, _else_writes), value) in enumerate(
            zip(self._carried_evaluations(runtime), carried, strict=True)
        ):
            if header is None:
                continue
            if decide and len(starts) == len(carried) and starts[index] is None:
                ctx = BranchResultDecision(
                    loop_write_slot(header), value is not None, self.site
                ).extend_scope(ctx)
            if value is None:
                continue
            ctx = bind_temporal(
                ctx,
                evaluation_here(header),
                value,
                owner="LoopRecurrenceSugar.header",
                blame=str(self.site),
            )
        return ctx

    def _target_keys(self, runtime):
        """Each target leaf's name, to the key the recurrence binds its
        projection under (``LiveForRuntimeV1.target_evaluations``)."""
        names = tuple(runtime.target_pattern.names)
        keys = tuple(getattr(runtime, "target_evaluations", ()))
        if len(keys) != len(names):
            raise TypeError("live for runtime omitted its target evaluation keys")
        return dict(zip(names, keys, strict=True))

    def _enter_target(self, runtime, ctx, projections):
        """Bind this item's projection of each target leaf under the leaf's
        key, qualified by the item (``evaluation_here``), and under the
        leaf's binding coordinate.  The name is never written: the body and
        the ``else`` read the target through its key (``For.substitute``).

        Returns the context and, per leaf, ``(key, coordinate, value)``: the
        identity a loop-control halt's state must hold
        (``_require_loop_control_state``)."""
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here
        from sugar_lift_py_tests.temporal import bind_temporal

        keys = self._target_keys(runtime)
        bindings = []
        for name, coordinate_cid, value in projections:
            key = evaluation_here(keys[name])
            ctx = bind_temporal(
                ctx,
                key,
                value,
                owner="LoopRecurrenceSugar.target",
                blame=str(self.site),
            )
            ctx = bind_temporal(
                ctx,
                coordinate_cid,
                value,
                owner="LoopRecurrenceSugar.target-coordinate",
                blame=str(self.site),
            )
            bindings.append((key, coordinate_cid, value))
        return ctx, tuple(bindings)

    def _enter_symbolic_item(self, runtime, ctx, iterable, heads):
        """The recurrence's one symbolic item: ``(projected, enter, item)``.
        ``projected`` is the item's target unpack, an ``ExitSet`` whose
        completed arms hold the leaves' projections; ``enter(projections)``
        is ``(ctx, target_bindings)``: the context the item's body reduces in
        on such an arm, and the identity a loop-control halt's record must
        hold (``_enter_target``, ``_require_loop_control_state``); ``item``
        is the item to enter while it does.

        A concrete item binds, inside its own segment, each carried name's
        header to the value the item begins with (``_enter_header``), then
        unpacks its value into the target (``_project_iteration_target``)
        and binds each leaf's key to its projection (``_enter_target``).
        The symbolic item does the same, inside its own segment
        (``loop_symbolic_item_segment``): each header to the recurrence's
        value of the name (``heads``, ``python:loop.recurrence``), then the
        item of the symbolic iterable (``python:loop.item``) through the same
        unpack.  A read in the body decides through its key; the name is
        never read.

        A name target's unpack is the item whole.  A destructuring target's
        is the item's runtime unpack, two-faced: each leaf's key (a
        carried leaf's header is its key) is bound to its projection on the
        unpack's completed arm, and its halt is an arm as it is, from the
        context entering the item, as a concrete item's unpack halt is
        (``_advance_iterator``).  A ``while`` without a runtime has no item:
        the context is unchanged and nothing is entered; a live ``while``'s
        symbolic item binds its headers only (it has no target, so nothing
        to unpack)."""
        from contextlib import nullcontext
        from dataclasses import replace
        from functools import partial

        from sugar_lift_py_tests.occurrence import entered, loop_symbolic_item_segment
        from sugar_lift_py_tests.outcome import Halted

        if runtime is None or (ctx is not None and not hasattr(ctx, "temporal")):
            return ExitSet.completed(()), lambda _projections: (ctx, ()), nullcontext
        if ctx is None:
            from sugar_lift_py_tests.context import ReduceContext

            ctx = ReduceContext.root(owner="LoopRecurrenceSugar.symbolic-item")
        item = partial(entered, loop_symbolic_item_segment(self.target_cid))
        # The recurrence has a value for each name it carries: the head of
        # its binding coordinate (``heads``) or, carried through its header
        # alone, of its post-loop key (``_recurrence_starts``); each header
        # is bound to it inside the item.  Whether an earlier item wrote a name
        # first bound in the loop is not known here: its write slot is left
        # undecided (``decide``).
        starts = self._recurrence_starts(runtime, heads)
        pattern = getattr(runtime, "target_pattern", None)
        if pattern is None:
            with item():
                header_ctx = self._enter_header(runtime, ctx, starts, decide=False)
            return ExitSet.completed(()), lambda _projections: (header_ctx, ()), item
        # The item is free: a read of it through the target's key owes the
        # undecided member (``read_of_bound_value``).
        element = loop_item(self.target_cid, iterable, self.site)
        with item():
            header_ctx = self._enter_header(runtime, ctx, starts, decide=False)
            projected = self._project_iteration_target(
                pattern, element, header_ctx
            )
        from sugar_lift_py_tests.sugar.function_universe_sugar import halt_record

        # The unpack's halt carries the empty record in the context entering
        # the item (``halt_record``), as a concrete item's does.
        projected = ExitSet(
            tuple(
                replace(exit_, state=halt_record(ctx))
                if isinstance(exit_, Halted)
                else exit_
                for exit_ in projected.exits
            )
        ).normalize()

        def enter(projections):
            # Each completed arm binds its own leaves, inside the item, and
            # hands on what it bound: a ``break``/``continue`` of the item is
            # authenticated against it.
            with item():
                return self._enter_target(runtime, header_ctx, projections)

        return projected, enter, item

    def _leave_target(self, runtime, ctx, items):
        """Bind, outside every item, each target leaf's key to the last
        item's projection of it (item ``items - 1``): the value the ``else``
        suite reads the target as.  A carried target's header is the same
        key, and ``_enter_header`` binds it after this to what the last item
        handed on.  With no item, nothing is bound: the target was never
        assigned.  A ``while`` has no target: nothing is bound."""
        from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here
        from sugar_lift_py_tests.temporal import bind_temporal

        temporal = getattr(ctx, "temporal", None)
        if (
            temporal is None
            or items < 1
            or getattr(runtime, "target_pattern", None) is None
        ):
            return ctx
        keys = tuple(self._target_keys(runtime).values())
        with entered(loop_iteration_segment(self.target_cid, items - 1)):
            last = tuple(
                temporal.value_if_bound(evaluation_here(key)) for key in keys
            )
        for key, value in zip(keys, last, strict=True):
            if value is None:
                continue
            ctx = bind_temporal(
                ctx,
                evaluation_here(key),
                value,
                owner="LoopRecurrenceSugar.target-after-items",
                blame=str(self.site),
            )
        return ctx

    def _latched(self, runtime, ctx, index):
        """The value of each carried name item ``index`` hands on: the latest
        of every write of it in the body (``x += e``, a walrus ``(x := e)``,
        an assignment, a nested loop's publication) and this item's header
        (``_latest_written``).  Read inside item ``index``, so each key is
        that item's.  The loop publishes the last item's latch under its own
        key of the name (``post_binding_keys``), which is what a read after
        the loop reads
        (a walrus's included: ``_substitute_body_tracked``)."""
        from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment

        temporal = getattr(ctx, "temporal", None)
        if temporal is None:
            # Nothing to latch from: the next item and the publication are
            # handed nothing, and refuse by name (``_require_carried``).
            return None
        with entered(loop_iteration_segment(self.target_cid, index)):
            return self._latest_written(runtime, temporal, else_suite=False)

    def _after_else(self, runtime, ctx):
        """The value of each carried name the loop leaves with after its
        ``else`` suite: the latest of every write of it in the suite and the
        header the suite read it through (bound by ``_finish_iterator`` to
        what the last item handed on).  Read where the suite ran, outside
        every item."""
        temporal = getattr(ctx, "temporal", None)
        if temporal is None:
            raise TypeError("loop recurrence omitted its temporal context")
        return self._latest_written(runtime, temporal, else_suite=True)

    def _latest_written(self, runtime, temporal, *, else_suite):
        """Per carried name, the binding bound last of the keys every write of
        it binds (the body's, or the ``else`` suite's:
        ``LiveForRuntimeV1.carried_evaluations``) and the header's, qualified
        by the reduction running now (``evaluation_here``).  A write never
        binds the name, and the name is never read: the latest write is the
        one that ran last on the path taken, wherever it sits (an arm of an
        ``if``, before a ``continue``).  A loop target's header is its
        per-item key, bound to the item's projection after the header
        (``_enter_target``)."""
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here

        values = []
        for header, writes, else_writes in self._carried_evaluations(runtime):
            keys = tuple(
                evaluation_here(key) for key in (else_writes if else_suite else writes)
            )
            starts = () if header is None else (evaluation_here(header),)
            binding = temporal.latest(*keys, *starts)
            values.append(None if binding is None else binding.value)
        return tuple(values)

    def _project_iteration_target(self, pattern, value, ctx):
        """Project every target leaf of this loop's ``pattern`` through the
        one unpack an item of a recurrence takes into its target
        (``project_iteration_target``), under this loop's owner and the
        ``for`` target's projection path."""
        return project_iteration_target(
            pattern, value, ctx, owner="LoopRecurrenceSugar.target"
        )

    @staticmethod
    def _require_loop_control_state(state, *, target_bindings):
        """Authenticate a loop-control halt's record and the producer's
        exact current reduction context in it; return the record the loop
        goes on from.

        A loop-control halt carries a record (``LoopControlSugar``): the
        entries the item made before it, spliced on by the block
        composition that ran it, and the context the ``break``/``continue``
        received at its source occurrence.  The current target Floor was
        bound into that context by this recurrence, under the target's
        per-item key and its binding coordinate (``_enter_target``), so
        object identity authenticates the context without rebuilding a
        reduced block or accepting an ambient/foreign scope.  A halt with no
        record, or a record with no such context, is refused: its entries
        are never taken without it.

        The loop goes on after the halt (the next item after a
        ``continue``, the statement after the loop after a ``break``) from
        the one record a continuation after a halt starts from
        (``function_universe_sugar.resumed``): the record's entries and
        context, without the ``return`` entries it holds (none is live on
        the halt's arm; a ``return`` the item took before it leaves as its
        own arm, ``_prior_return_face``).
        """
        from sugar_lift_py_tests.context.reduce_context import ReduceContext
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _ReducedBlock,
            resumed,
        )

        if not isinstance(state, _ReducedBlock):
            raise TypeError("loop control omitted its record")
        context = state.context
        if not isinstance(context, ReduceContext):
            raise TypeError("loop control omitted its exact ReduceContext state")
        for target_key, coordinate_cid, target_value in target_bindings:
            if (
                context.temporal.value_if_bound(target_key) is not target_value
                or context.temporal.value_if_bound(coordinate_cid) is not target_value
            ):
                raise TypeError(
                    "loop control state lacks exact iteration target identity"
                )
        return resumed(
            state,
            context,
            owner="LoopRecurrenceSugar.loop-control",
            blame="LoopRecurrenceSugar.loop-control",
        )

    def _finish_iterator(self, runtime, ctx, *, entries, carried, items=0):
        """The loop's outcome after its ``items`` items were exhausted."""
        from sugar_lift_py_tests.outcome.exit_set import _require_exit_set
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            past_prior_returns,
            reduce_block_to_exitset,
        )

        if not runtime.else_sugars:
            # The loop leaves with what the last item handed on (or the
            # pre-loop values when there was no item).
            return self._publish_runtime_bindings(
                runtime,
                ctx,
                entries=entries,
                carried=carried,
                items=items,
                exhausted=True,
            )
        # The else runs once, after every item.  It reads each carried name
        # through the header, bound here, outside every item, to what the last
        # item handed on (``carried``), and the target through its key, bound
        # here to the last item's projection (``_leave_target``; a carried
        # target's is its header); the loop leaves with the latest of the
        # else's writes of each name and that header (``_after_else``).
        else_ctx = self._enter_header(
            runtime, self._leave_target(runtime, ctx, items), carried
        )
        witnesses = _else_witnesses(runtime, else_ctx)
        otherwise = reduce_block_to_exitset(runtime.else_sugars, else_ctx)

        def leave(context, left, **how):
            return self._publish_runtime_bindings(
                runtime,
                context,
                entries=left,
                carried=self._after_else(runtime, context),
                items=items,
                else_ran=True,
                exhausted=True,
                **how,
            )

        def after_suite(record):
            return leave(
                record.context,
                (*entries, *record.entries),
                fall_through=record.fall_through,
                can_fall_through=record.can_fall_through,
            )

        def publish(otherwise):
            # The published bindings run beneath every face of the else suite
            # (``ExitSet.and_then``): each takes that face's guard and faces
            # and owes what it owes.  A completed face leaves with what the
            # items and the suite left; a halt (a ``raise``, a call's halt,
            # an enclosing loop's ``break``/``continue``) leaves with what the
            # items left, its own record, and what the loop publishes where
            # the suite halted (``_else_left_from``, ``_left_with``).  A
            # completed face that falls through after a guarded ``return``
            # (``else: if c: return 1``) took that ``return`` where its guard
            # held: the loop leaves by it as its own arm, and leaves as a
            # loop only under the guard that it was not taken, through the
            # one composition a block gives a statement after a guarded
            # ``return`` (``past_prior_returns``) -- so the statement after
            # the loop never stands beside it unguarded.
            return otherwise.and_then(
                lambda state: past_prior_returns(
                    state, state.context, after_suite, after_suite
                ),
                consume=lambda halt: leave(
                    _else_left_from(
                        runtime, else_ctx, witnesses, halt, site=self.site
                    ),
                    entries,
                    halt=halt,
                ),
            )

        return publish(_require_exit_set(otherwise, owner="LoopRecurrenceSugar.else"))

    def _publish_runtime_bindings(
        self,
        runtime,
        ctx,
        *,
        entries,
        carried,
        fall_through=(),
        can_fall_through=True,
        items=0,
        else_ran=False,
        halt=None,
        exhausted: bool,
    ):
        """Publish the value of each name carried under a binding coordinate
        (``_coordinate_names``) as the loop leaves: ``carried``,
        what the leaving item (``_latched``) or the ``else`` suite
        (``_after_else``) left it with; handed nothing, refused by name
        (``_require_carried``).  The value is published under the loop's own
        key of the name only (``post_binding_keys``): every read after the
        loop is a ``LoopBindingRef`` to it (``project_loop_post_binding``),
        and neither the name nor its binding coordinate is written or read.
        The iterable's walrus writes of the names the loop does not carry
        (``iterable_writes``) are published
        first, under their keys: the iterable ran before every item.  Each
        name the items write that the loop does not carry under a binding
        coordinate (a name first bound in the loop, a module binding) is
        published last, under its post-loop key, with its write slot decided
        on this exit (``_post_loop_writes``): ``items`` items ran, and the
        ``else`` suite ran when ``else_ran``.  Last, the exit the loop left
        by is decided on this path (``_exit_decision``): by exhaustion when
        ``exhausted``, else by its own ``break``.  With ``halt`` (a halt
        leaving the ``else`` suite), the loop leaves by it, carrying all this
        (``_left_with``)."""
        temporal = getattr(ctx, "temporal", None)
        if temporal is None:
            raise TypeError("loop recurrence omitted its temporal context")
        carried = dict(
            zip(
                runtime.carried_names,
                self._require_carried(runtime, carried),
                strict=True,
            )
        )
        values = []
        for name in self._coordinate_names(runtime):
            value = carried[name]
            if value is None:
                raise TypeError("loop recurrence omitted a carried binding")
            values.append(value)
        posted = self._post_loop_writes(
            runtime, temporal, items=items, else_suite=else_ran
        )
        # The calls' records the items (and the ``else`` suite) made leave
        # with the loop, before the names it publishes (``_records_made_here``,
        # #7757 H7).  A halt holds them already, in the context it halted in.
        records = () if halt is not None else self._records_made_here(ctx)
        return self._left_with(
            entries,
            (
                *records,
                *self._publication(tuple(values), posted),
                self._exit_decision(exhausted),
            ),
            halt=halt,
            fall_through=fall_through,
            can_fall_through=can_fall_through,
        )

    def _exit_decision(self, exhausted: bool):
        """The exit this loop left by, decided on the path it publishes on:
        its exit slot (``loop_exit_slot``) true when it left by exhaustion
        (``NormalExhaustion``), false when it left by its own ``break``
        (``BreakExit``).

        A loop whose items the reduction ran one by one knows which way it
        left: it ran them.  A read after it (``guarded_binding_read_sugar.
        decided_loop_exit``) takes that face's binding, as a read of its
        write slot takes one arm (``_publication``), never the face under
        the guard the recurrence states it by (``python.loop.exhausted``,
        the ``break``'s branch guard), which no input decides.  Read under
        that guard, a function's return after a loop it ran in hand was a
        post no caller's join could read: the unrolled loop it replaced
        (#8957) had no such guard.  The decision is this path's own
        (``BranchResultDecision``).  The recurrence decides only where its
        symbolic item's ``while`` test decided the exit (``_recurrence``:
        true at every item, the loop leaves by its ``break``; false, by
        exhaustion); anywhere else its read stays guarded and owed."""
        from sugar_lift_py_tests.floor.branch_result_coordinate import (
            BranchResultDecision,
        )
        from sugar_source_tree.binding_state import loop_exit_slot

        return BranchResultDecision(
            loop_exit_slot(self.target_cid), exhausted, self.site
        )

    def _left_with(
        self,
        entries,
        published,
        *,
        halt=None,
        fall_through=(),
        can_fall_through=True,
    ):
        """The loop leaving with ``entries`` -- what its items (and its
        ``else`` suite) left: every store, container mutation and rebind
        they made, in the order they ran -- and ``published``, what it
        publishes as it leaves (``_publication``, and the recurrence's step
        for a symbolic loop).  The iterable's walrus writes
        (``iterable_writes``) come first: the iterable ran before every
        item.  One record, for a concrete loop (``_publish_runtime_bindings``)
        and the recurrence alike (``_desugar_with_iterable``): what an item
        left is carried out of the loop the one way.

        Every way out is this one carry: a ``return`` (``can_fall_through``
        false), and a halt (``halt``: a ``raise``, a call's halt, an
        enclosing loop's ``break``/``continue``, from an item, its target
        unpack, its ``next`` or ``while`` test, or the ``else`` suite).  A
        halt leaves as itself, its record holding the iterable's writes,
        ``entries`` -- what the items before it left -- what its own record
        holds (what ran before it, spliced on by the block composition
        that ran it), then ``published``; its context is its record's, with
        ``published`` bound in it (``extend_scope``) as the block
        composition binds a completed loop's (``reduce_block_to_exitset``),
        so an enclosing loop reads its latch from what this loop published.
        Its guard, faces and ``owed`` are its arm's: the caller composes
        beneath it (``ExitSet.and_then``).  With nothing to carry its record
        is left as it is, by identity (``function_universe_sugar._prefixed``'s
        law).  Every halt carries a record, built by its producer
        (``function_universe_sugar.halt_record``: an unpack's, ``next``'s
        and a ``while`` test's halt included); a halt whose state is no
        record (``None``, a bare context, any other payload) is refused by
        name, never given an empty one: what ran before it is never dropped
        beside what the items did."""
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

        before = (*self.iterable_writes, *entries)
        if halt is None:
            return ExitSet.completed(
                BlockValue(
                    (*before, *published),
                    fall_through=fall_through,
                    can_fall_through=can_fall_through,
                )
            )
        state = halt.state
        if not isinstance(state, _ReducedBlock):
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner="LoopRecurrenceSugar.left-with",
                blame=self.site,
                observed=(
                    f"a {type(halt.effect).__name__} halt leaving a live loop "
                    f"from a {type(state).__name__} state, not a record"
                ),
                requested=(
                    "the halt's record, to carry what the loop's items did "
                    "beside what ran before the halt"
                ),
                fix=(
                    "halt with a record at the producer (halt_record); never "
                    "make one up in its place, never drop what the items did"
                ),
            )
        if before or published:
            from dataclasses import replace

            context = state.context
            if published and context is not None:
                context = BlockValue(published).extend_scope(context)
            state = replace(
                state,
                entries=(*before, *state.entries, *published),
                context=context,
            )
        return ExitSet.halted(halt.effect, state=state)

    def _recurrence_head(self, key):
        """The recurrence's value of the name a read after the loop reads
        through ``key`` (a binding coordinate or a post-loop key): the loop's
        symbolic fixed point of it (``recurrence_head``)."""
        return recurrence_head(self.target_cid, key)

    def _entered_at(self, ctx):
        """This loop holding the temporal of ``ctx`` -- the context its first
        item begins from, after its iterable -- as ``entered``, where it
        holds none yet; None where it holds one already or ``ctx`` holds no
        temporal."""
        temporal = getattr(ctx, "temporal", None)
        if self.entered is not None or temporal is None:
            return None
        from dataclasses import replace

        return replace(self, entered=temporal)

    def _records_made_here(self, context):
        """The calls' records (``AfterCallRecordValue``) the loop made on the
        path that leaves it in ``context`` -- each bound there and not, to
        the same value, where its first item began (``entered``) -- in the
        order they were made, each as the rebind of its key
        (``ScopeRebind``), for the loop to publish as it leaves.

        A loop leaves through one record (``_left_with``): what its items
        did, and the bindings it publishes, bound after it where the block
        composition binds a completed loop's (``extend_scope``).  The
        context its items ran in is not carried out, and the records a call
        made in it went with it: after ``for _ in xs: bump()`` a call that
        read a module global was handed the global as it stood before the
        loop (#7757 H7).  Which of them leave is the one rule a recurrence's
        records leave by (``records_left``), which a comprehension's
        recurrence leaves by too.

        Nothing where the loop never held where it began (``entered`` None)
        or ``context`` holds no temporal."""
        temporal = getattr(context, "temporal", None)
        if temporal is None or self.entered is None:
            return ()
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind

        before = {binding.name: binding.value for binding in self.entered.bindings}
        made = tuple(
            (binding.name, binding.value)
            for binding in temporal.bindings
            if before.get(binding.name) is not binding.value
        )
        return tuple(
            ScopeRebind(name, record)
            for name, record in records_left(self.target_cid, made)
        )

    def _publication(self, coordinate_values, posted):
        """What the loop leaves bound for a read after it, on every exit it
        publishes on, concrete or symbolic: each coordinate name's value
        (``coordinate_values``, ``binding_coordinate_cids`` order) under the
        loop's own key of it (``post_binding_keys``), bound outside every
        item of this loop (``evaluation_here``) -- every read after the loop
        is a ``LoopBindingRef`` to it (``project_loop_post_binding``), and
        no other loop binds it, so a read after this loop never finds another
        loop's value of the name -- then, per name published
        through its post-loop key, ``(post_key, value, wrote)``
        (``_post_loop_writes``): the post-loop key bound outside every item
        (``evaluation_here``) to ``value`` where ``value`` is not None, and
        the name's write slot (``loop_write_slot``) decided by ``wrote``.  A
        ``bool`` decides the slot on this exit (``BranchResultDecision``): a
        concrete loop knows whether an item wrote it.  A formula authenticates
        the slot as that guard (``BranchResultAuthentication``): the symbolic
        recurrence does not know, and states no condition under which an item
        wrote it (``python.loop.wrote`` is the recurrence's own atom, which no
        input decides), so nothing on the path decides or reads the slot and
        a read after the loop (``nodes._live_loop_publication``) is the
        undecided member (``branch_result_coordinate.undecided_slot_debt``):
        both arms stand -- the post-loop key, and the binding before the loop
        (unbound when there was none) -- and the read owes, never a value the
        solver selects by choosing the flag (#7757).  The name is never
        written nor read."""
        from sugar_lift_py_tests.floor.branch_result_coordinate import (
            BranchResultAuthentication,
            BranchResultDecision,
        )
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here
        from sugar_source_tree.binding_state import loop_write_slot

        published = [
            ScopeRebind(evaluation_here(post_key), value)
            for post_key, value in zip(
                self.post_binding_keys, coordinate_values, strict=True
            )
        ]
        for post_key, value, wrote in posted:
            if value is not None:
                published.append(ScopeRebind(evaluation_here(post_key), value))
            slot = loop_write_slot(post_key)
            published.append(
                BranchResultDecision(slot, wrote, self.site)
                if isinstance(wrote, bool)
                else BranchResultAuthentication(slot, wrote, self.site)
            )
        return tuple(published)

    def _post_loop_writes(self, runtime, temporal, *, items, else_suite):
        """``(post_key, value, wrote)`` (``_publication``) for each name the
        items write that the loop does not carry
        (``LiveForRuntimeV1.published_evaluations``): ``value`` is the latest
        write of the name on the path the loop leaves by -- the ``else``
        suite's when it ran and wrote it, else that of the last of the
        ``items`` items that wrote it (each item's writes are keyed by that
        item) -- and ``wrote`` whether there was one.  A read after the loop
        reads the name through the post-loop key, as a function-level live
        loop's ``else`` reads its target's and header's keys bound after the
        last item (``_leave_target``, ``_enter_header``).  A name no item and
        no ``else`` wrote binds nothing, and its write slot is decided false
        on this exit: the read takes the binding before the loop."""
        from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here

        posted = []
        for post_key, writes, else_writes in getattr(
            runtime, "published_evaluations", ()
        ):
            binding = None
            if else_suite and else_writes:
                binding = temporal.latest(
                    *(evaluation_here(key) for key in else_writes)
                )
            index = items - 1
            while binding is None and index >= 0 and writes:
                with entered(loop_iteration_segment(self.target_cid, index)):
                    keys = tuple(evaluation_here(key) for key in writes)
                binding = temporal.latest(*keys)
                index -= 1
            posted.append(
                (
                    post_key,
                    None if binding is None else binding.value,
                    binding is not None,
                )
            )
        return tuple(posted)


@dataclass(frozen=True, eq=False)
class _WhileTest:
    """One face of a live ``while``'s test in one item: the truth of the
    test's value as a guard, the context the
    body runs in (after the test: a walrus in it is bound), and, for a true
    face, the body reduced there.  ``entries``: the item's record before its
    body -- the stores a callee the test called made on objects the loop's
    frame sees, laid by the header rule (``laid_in_record``)."""

    formula: object
    ctx: object
    body: object = None
    entries: tuple = ()


@dataclass(frozen=True)
class _WhileItemTestV1:
    """A live ``while``'s test evaluated at one item: that item's header.

    Python evaluates the test before every item, so each evaluation is its
    own header, run by the one header rule (``header_applied``): its walrus
    binds and callee stores are in the context the item's body and the
    loop's exit read, and its stores are in the item's record
    (``_WhileTest.entries``), consistent with the loop rule -- each item's
    writes follow the items before it."""

    test: object
    site: object = None

    def desugar(self, ctx: object = None) -> ExitSet:
        return self.faces(self.test.desugar(ctx), ctx)

    def faces(self, outcome, ctx) -> ExitSet:
        """Each face of the test's ``outcome`` in ``ctx``: a completed face
        is a ``_WhileTest`` (its truth as a guard, the context after it); a
        halt halted where this item began, after the items before it: it
        carries that record (``halts_recorded``) and leaves the loop with
        what they did (``_left_with``)."""
        from sugar_lift_py_tests.outcome.exit_set import _require_exit_set
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halt_record,
            halts_recorded,
        )

        test = halts_recorded(
            _require_exit_set(outcome, owner="LoopRecurrenceSugar.while-test"),
            halt_record(ctx),
        )
        return test.and_then(lambda value: self._truth_faces(value, ctx))

    def _truth_faces(self, value, ctx) -> ExitSet:
        """The test's value's truth, taken through the one truth rule
        (``bool_op_sugar.truth_of``), as ``_WhileTest`` faces.

        A plain truth is one face whose guard is its formula.  A value whose
        truth is not decided here is its two faces: each completed
        truth face is a ``_WhileTest`` under its own guard, and a halted truth
        halted where this item began, so it carries that record
        (``halts_recorded``), as a halt of the test itself does.  A formal's
        truth is such a value: it waits on no caller's actual (#7757
        NEW-1)."""
        from sugar_lift_py_tests.sugar.bool_op_sugar import truth_of
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halt_record,
            halts_recorded,
            plain_completed_value,
        )
        from sugar_lift_py_tests.sugar.if_sugar import truth_formula

        scope = value.extend_scope(ctx)
        truth = truth_of(value, self.site, owner="LoopRecurrenceSugar.while-test")
        if plain_completed_value(truth) is not None:
            return ExitSet.completed(_WhileTest(truth_formula(truth, value), scope))
        return halts_recorded(truth, halt_record(ctx)).and_then(
            lambda truth_value: ExitSet.completed(
                _WhileTest(
                    truth_formula(ExitSet.completed(truth_value), value), scope
                )
            )
        )

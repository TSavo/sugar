from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import ClassVar

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import (
    NotVerdictBearing,
    _assertion_pair,
    typed_red_effect_witness,
)


@dataclass(frozen=True)
class AssignSugar(Sugar):
    """A `name = <rhs>` statement: the rhs is evaluated HERE, once.

    substitute runs before sugar (FunctionDef.sugar) and threads the binding:
    every later read of the name is a reference to the name's projection of
    this statement's evaluation (``Assign.target_evaluations``), never the rhs
    inlined at the read.  This sugar evaluates the rhs at the statement (its
    halts are the statement's) and binds the completed value under that key,
    so the read answers the value the name was given here, whatever was
    rebound since.  An assignment states no fact, post or effect of its own.

    Meaning-only, node-constructed: no owns/new/role. Single Name target only;
    other target shapes stay gaps on the tree node.
    """

    name: str
    value: object  # the rhs sugar, evaluated at this statement
    site: object = dataclass_field(compare=False)
    # ``(name, key)``: the name's value is bound under ``key``
    # (``Assign.target_evaluations``); every later read of the name reads it.
    evaluations: tuple = ()
    # Evaluating the RHS is the statement's only work before it binds; a
    # walrus in it binds first, and then the claim is refused unless the
    # halt carries its record (``_require_recorded_halts``).
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        # `x = z` binds `x` to what `z` holds: the truthful twin rides the
        # identity, the lying twin asserts another.
        return _assertion_pair(
            name="assign_return",
            owner_sugar="AssignSugar",
            statements="z = 5\nx = z",
            truthful="x == 5",
            lying="x == 6",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        # The binding was consumed by substitute, but the RHS is evaluated
        # HERE: its halts are this statement's, and a later read sees the
        # completed value (sugar/assigned_value.py).
        from sugar_lift_py_tests.sugar.assigned_value import (
            evaluate_assignment_values,
        )

        bind = ((self.name, 0),)
        return evaluate_assignment_values(
            (self.value,),
            ctx,
            evaluations=_evaluation_indices(self.evaluations, bind),
        )


@dataclass(frozen=True)
class ChainedAssignSugar(Sugar):
    """One evaluated RHS distributed left-to-right across names and stores.

    The RHS is evaluated HERE, once, and bound under ``evaluation`` (the
    statement's key) and under each Name target's key (``evaluations``).
    ``stores`` are the store targets' own statements' sugars
    (``Assign._store_statements``), left to right: each reads the value
    through ``evaluation`` and stores it exactly as ``o.x = v`` alone does,
    binding what a later read of the place reads.  The targets are assigned
    left to right (``target_order``): a store's halt leaves every Name
    target to its left assigned and every one to its right not
    (``x = o.a = y = e`` where ``o.a`` raises: ``x`` assigned, ``y`` not).
    """

    bindings: tuple
    stores: tuple
    value: object
    site: object = dataclass_field(compare=False)
    evaluations: tuple = ()  # (name, key) per Name target, as AssignSugar's
    evaluation: str | None = None  # the key the stores read the value under
    # The targets left to right: each Name target's name (in ``bindings``
    # order) and each store target's index in ``stores``
    # (``nodes._target_order``); empty, every Name target before every store.
    target_order: tuple = ()
    # A record-less halt is the RHS's, before any target is assigned; the
    # stores' halts carry the record their block gave them.
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="typed store effect",
            reason="mixed chained stores stay red while lexical bindings continue",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.context import ReduceContext
        from sugar_lift_py_tests.sugar.assigned_value import (
            evaluate_assignment_values,
        )

        bind = tuple((name, 0) for name in _chained_names(self.bindings))
        value_key = () if self.evaluation is None else ((self.evaluation, 0),)
        if not self.stores:
            return evaluate_assignment_values(
                (self.value,),
                ctx,
                evaluations=(*_evaluation_indices(self.evaluations, bind), *value_key),
            )
        if ctx is None:
            ctx = ReduceContext.root(owner="ChainedAssignSugar")
        # The RHS is evaluated once and bound under its key before any
        # target; then the targets are assigned left to right, each store
        # target's statement reading the value there.
        return evaluate_assignment_values(
            (self.value,),
            ctx,
            evaluations=value_key,
            targets=_ordered_targets(
                self.target_order, bind, self.evaluations, self.stores
            ),
        )


@dataclass(frozen=True)
class KeyedStoreSugar(Sugar):
    """``o.x = v`` whose stored value a later read of the place reads.

    Substitution threads the store into later reads of the place (every
    read of ``o``, or of one of its fields, after the one field store reads
    the receiver's post-state, ``ReceiverFieldStoreState``).  Each such read
    is a reference to this statement's evaluation (``place``), never ``v``
    inlined at the read and evaluated again against whatever was rebound
    since (``o.x = x; x += 1; return o.x``).

    ``value`` is the right-hand side, evaluated HERE, once: its halts are the
    statement's, and its completed value is bound under ``evaluation``.
    ``store`` is the store itself, built with its value read through that
    key, and runs after the value is bound (Python evaluates the right-hand
    side before the target).

    ``o.x OP= v`` evaluates its receiver first (``receiver``) and binds it
    under ``receiver_evaluation`` as soon as it completes: the field's read
    in ``value``, the store and every later read of the object read it
    there, never the receiver evaluated again.

    ``writes`` are ``(state, keys)``: the state after the store of the names
    the store rebinds (``ReceiverFieldStoreStatement.written_keys``), each
    evaluated once with the statement and bound under every key in ``keys``
    once the store completed -- a store that halts writes nothing.  A live
    loop carries them from item to item, as it carries the one mutation
    door's writes (``ContainerMutationStatementSugar.result_evaluations``).
    The states read the keys the statement binds (the value's, the
    receiver's), so the value's is bound as soon as it completes.
    """

    value: Sugar
    store: Sugar
    evaluation: str
    site: object = dataclass_field(compare=False)
    receiver: Sugar | None = None
    receiver_evaluation: str | None = None
    writes: tuple = ()
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="typed store effect",
            reason="the store's own sugar owns its faces; this binds its value once",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.context import ReduceContext
        from sugar_lift_py_tests.sugar.assigned_value import (
            evaluate_assignment_values,
        )

        if ctx is None:
            ctx = ReduceContext.root(owner="KeyedStoreSugar")

        def store(active, completed):
            # The value is bound under the key: the store reads it there.
            del completed
            return _reduce_targets((self.store,), active, ctx)

        values = (self.value,)
        receiver = ()
        if self.receiver is not None:
            values = (self.receiver, self.value)
            receiver = ((self.receiver_evaluation, 0),)
        value_key = (self.evaluation, len(values) - 1)
        if not self.writes:
            return evaluate_assignment_values(
                values,
                ctx,
                tail=store,
                evaluations=(value_key,),
                as_completed=receiver,
            )
        # The states are evaluated with the statement, reading the keys it
        # bound; the store runs, then each state is bound under its keys
        # (``AssignedNames``), so a halted store writes none of them.
        written = tuple(
            (key, len(values) + index)
            for index, (_state, keys) in enumerate(self.writes)
            for key in keys
        )
        return evaluate_assignment_values(
            (*values, *(state for state, _keys in self.writes)),
            ctx,
            as_completed=(*receiver, value_key),
            targets=(self.store, *written),
        )


@dataclass(frozen=True)
class DynamicUnpackStoreAssignSugar(Sugar):
    """Any RHS, a display among them (#7757 S2): Name|Attribute|Subscript|*Name
    unpack (LTR).

    Python: evaluate RHS **once**, UNPACK materializes all members, then each
    target applies its member **left-to-right**.  A halt on an earlier target
    leaves later names unbound and later stores unrun; earlier completed
    rebinds/stores survive on the halted face state.

    Projection is positional (``PositionalUnpackOperation`` →
    ``UnpackMemberRoster``) — no fabricated synthetic lexical binding keys.
    Targets are typed variants (``unpack_projection_targets``) owning apply.
    """

    value: Sugar
    targets: tuple  # Name|Star|Attribute|Subscript unpack targets, source order
    site: object = dataclass_field(compare=False)
    # A record-less halt is the RHS's or the unpack's, before any target
    # applies its member (after a walrus in the RHS bound, the unpack's
    # carries the record of that bind); a target's halt carries the record
    # the targets' block gave it (``_apply_authenticated_roster``).
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        return typed_red_effect_witness(
            name="dynamic_unpack_store_star",
            owner_sugar="DynamicUnpackStoreAssignSugar",
            source=("def A(o, xs):\n" "    o.x, *rest = xs\n" "    return rest\n"),
            effect_class="UndeterminedRaiseEffect",
            reason_needle="undetermined exception identity",
            blame_needle="SourceFragment",
            wrong_reason_needle="raise ValueError",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            caller_stores_of,
            peel_walrus_binds,
            written_by,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halts_at_operand_head,
            laid_in_record,
        )

        self._require_typed_targets()
        operation, expected_demand_cid = self._operation()

        def unpack(value):
            # A walrus in the right-hand side (``o.x, y = (a := v)``) is
            # bound before the unpack runs: the unpack and every target run
            # in the context it wrote, so the targets' block carries it on,
            # and the unpack's own halt (before any target applies) carries
            # its record (``halts_at_operand_head``, the unpack running no
            # walrus).  A callee's store the value carried was made before
            # the unpack: it is first in the record of every arm, completed
            # or halted (``laid_in_record``).
            binds, presented = peel_walrus_binds(value)
            if not binds:
                return self._unpack(operation, expected_demand_cid, value, ctx)
            after = written_by(value, ctx)
            _walrus, stores = caller_stores_of(binds)
            return laid_in_record(
                stores,
                halts_at_operand_head(
                    self._unpack(operation, expected_demand_cid, presented, after),
                    None,
                    after,
                ),
            )

        return self.value.desugar(ctx).and_then(unpack)

    def unpack(self, value, ctx) -> ExitSet:
        """Unpack ``value``, already evaluated, into the targets left to
        right: the one positional unpack this statement submits
        (``desugar``), and the one a nested level submits for its member
        (``NestedUnpackTarget``), whose ``value`` field is unused."""
        self._require_typed_targets()
        operation, expected_demand_cid = self._operation()
        return self._unpack(operation, expected_demand_cid, value, ctx)

    def _require_typed_targets(self) -> None:
        from sugar_lift_py_tests.sugar.unpack_projection_targets import (
            UnpackProjectionTarget,
        )

        for target in self.targets:
            if not isinstance(target, UnpackProjectionTarget):
                raise TypeError(
                    "DynamicUnpackStoreAssignSugar.targets must be "
                    f"UnpackProjectionTarget; got {type(target).__name__}"
                )

    def _operation(self):
        from sugar_lift_py_tests.operations.positional_unpack_operation import (
            PositionalUnpackOperation,
        )

        prefix, suffix, has_star = self._fixed_counts()
        operation = PositionalUnpackOperation(
            fixed_prefix=prefix,
            fixed_suffix=suffix,
            has_star=has_star,
            owner=type(self).__name__,
            blame=self.site,
        )
        return operation, operation.demand_cid()

    def _unpack(self, operation, expected_demand_cid, value, ctx) -> ExitSet:
        def apply(roster):
            return self._apply_authenticated_roster(
                roster,
                expected_demand_cid=expected_demand_cid,
                ctx=ctx,
            )

        # The stores run beneath every completed arm of the unpack (a store
        # waiting on its caller's actuals composed there); its halt is an arm
        # as it is.
        return operation.submit(value, ctx).and_then(apply)

    def _apply_authenticated_roster(self, roster, *, expected_demand_cid: str, ctx):
        """Zip targets only after the roster testifies this unpack occurrence."""
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.operations.positional_unpack_operation import (
            UnpackMemberRoster,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )
        from sugar_lift_py_tests.sugar.unpack_projection_targets import (
            ApplyUnpackMemberSugar,
        )

        if not isinstance(roster, UnpackMemberRoster):
            construction_panic_gap(
                owner=type(self).__name__,
                blame=self.site,
                observed=type(roster).__name__,
                requested="UnpackMemberRoster with occurrence and demand_cid",
                fix="mint members through PositionalUnpackOperation.mint_roster",
            )
        if roster.demand_cid != expected_demand_cid:
            construction_panic_gap(
                owner=type(self).__name__,
                blame=self.site,
                observed=f"roster demand_cid={roster.demand_cid!r}",
                requested=f"unpack demand_cid={expected_demand_cid!r}",
                fix=(
                    "apply only the roster minted by this statement's "
                    "PositionalUnpackOperation; same members under a foreign "
                    "occurrence/demand are not this unpack"
                ),
            )
        if roster.occurrence is not self.site and roster.occurrence != self.site:
            construction_panic_gap(
                owner=type(self).__name__,
                blame=self.site,
                observed=f"roster occurrence={roster.occurrence!r}",
                requested=f"unpack occurrence={self.site!r}",
                fix=(
                    "require the roster occurrence to be this statement fragment; "
                    "same members under a substituted occurrence are refused"
                ),
            )
        return reduce_block_to_exitset(
            tuple(
                ApplyUnpackMemberSugar(target, member, self.site)
                for target, member in zip(self.targets, roster.members, strict=True)
            ),
            ctx,
        )

    def _fixed_counts(self) -> tuple[int, int, bool]:
        """Positional UNPACK layout from target-owned star-slot testimony.

        Star position is an obligation method on ``UnpackProjectionTarget`` —
        not a kinds ``isinstance`` ladder over concrete leaf classes.
        """
        prefix = 0
        suffix = 0
        has_star = False
        seen_star = False
        for target in self.targets:
            if target.occupies_star_slot():
                if has_star:
                    raise AssertionError("at most one star unpack target")
                has_star = True
                seen_star = True
                continue
            if seen_star:
                suffix += 1
            else:
                prefix += 1
        return prefix, suffix, has_star


def _evaluation_indices(evaluations, bind):
    """``(key, value index)`` for each keyed name: ``evaluations`` holds
    ``(name, key)`` (``Assign.target_evaluations``), ``bind`` the index of
    the value each name is bound to."""
    keys = dict(evaluations)
    return tuple((keys[name], index) for name, index in bind if name in keys)


def _ordered_targets(order, bind, evaluations, stores):
    """A statement's targets left to right, as ``evaluate_assignment_values``
    assigns them (``targets``): each keyed Name target's ``(key, value
    index)`` and each store target's statement.

    ``order`` (``nodes._target_order``) holds each Name target's name, in
    ``bind``'s order (``bind`` pairs each with the index of its value), and
    each store target's index in ``stores``; empty (a statement built
    without its order), every Name target precedes every store.
    ``evaluations`` holds ``(name, key)`` (``Assign.target_evaluations``): a
    name with no key binds nothing here, as in ``_evaluation_indices``."""
    if not order:
        order = (*(name for name, _index in bind), *range(len(stores)))
    keys = dict(evaluations)
    names = iter(bind)
    targets = []
    for item in order:
        if isinstance(item, int):
            targets.append(stores[item])
            continue
        name, index = next(names)
        if name in keys:
            targets.append((keys[name], index))
    return tuple(targets)


def _reduce_targets(targets, active, ctx):
    """The statement's store targets, after its RHS completed.

    Where the RHS bound no evaluation this is the block the statement always
    reduced to; where it bound one (a Name target's, a value a store reads),
    the targets' exits carry that context on to the next statement.
    """
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
        reduce_body,
    )

    from sugar_lift_py_tests.sugar.assigned_value import AssignedNames

    if (
        (ctx is None or getattr(active, "temporal", None) is ctx.temporal)
        # A Name target bound among the stores (``AssignedNames``) is carried
        # on by the targets' record, as one bound before them is.
        and not any(isinstance(target, AssignedNames) for target in targets)
    ):
        return reduce_body(targets, active)
    return reduce_block_to_exitset(targets, active)


def _chained_names(bindings):
    """The lexical names a chained assignment binds (``x = y = e``)."""
    return tuple(
        binding if isinstance(binding, str) else binding[0] for binding in bindings
    )

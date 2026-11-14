from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import ClassVar

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import (
    NotVerdictBearing,
    _call_pair,
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
    # Evaluating the RHS is the statement's only work before it binds.
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        # `x = z; return x` inlines to `return z` via substitute: the truthful
        # twin rides the identity, the lying twin asserts another.
        prefix = "def A(z):\n    x = z\n    return x\n\n"
        return _call_pair(
            name="assign_return",
            owner_sugar="AssignSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
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
            bind=bind,
            evaluations=_evaluation_indices(self.evaluations, bind),
            site=self.site,
        )


@dataclass(frozen=True)
class MultiAssignSugar(Sugar):
    """More than one name bound by a single Assign statement -- either a
    destructured display (`a, b = <tuple/list display>`) or a chained
    assignment (`x = y = e`). Just like AssignSugar, substitute has already
    threaded every binding into the rest of the block by the time this sugar
    reduces: an assignment states no fact of its own, so this too is inert
    meaning. `bindings` holds each bound name with its own rhs sugar --
    provenance only, never re-stated.

    Meaning-only, node-constructed: no owns/new/role. Only shapes the tree
    node has already proven destructure (or chain) reach here; anything else
    stays a loud gap on the node.
    """

    bindings: tuple  # tuple of (name, value_sugar) pairs, in target order
    site: object = dataclass_field(compare=False)
    evaluations: tuple = ()  # (name, key) per Name target, as AssignSugar's
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        # A destructuring bind that discriminates ON THE PAIRING: swap the
        # two names' rhs and the sum through both flips.
        prefix = "def A(p, q):\n    a, b = p, q\n    return a + b\n\n"
        return _call_pair(
            name="multi_assign_destructure",
            owner_sugar="MultiAssignSugar",
            truthful=prefix + "def test_a():\n    assert A(2, 3) == 5\n",
            lying=prefix + "def test_a():\n    assert A(2, 3) == 6\n",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        # Every binding was consumed by substitute; each RHS member is still
        # evaluated HERE, left to right, before any name is bound.
        from sugar_lift_py_tests.sugar.assigned_value import (
            evaluate_assignment_values,
        )

        values = _distinct_in_order(value for _name, value in self.bindings)
        bind = tuple(
            (name, next(i for i, v in enumerate(values) if v is value))
            for name, value in self.bindings
        )
        return evaluate_assignment_values(
            values,
            ctx,
            bind=bind,
            evaluations=_evaluation_indices(self.evaluations, bind),
            site=self.site,
        )


@dataclass(frozen=True)
class ChainedAssignSugar(Sugar):
    """One evaluated RHS distributed left-to-right across names and stores.

    The RHS is evaluated HERE, once, and bound under ``evaluation`` (the
    statement's key) and under each Name target's key (``evaluations``).
    ``stores`` are the store targets' own statements' sugars
    (``Assign._store_statements``), left to right: each reads the value
    through ``evaluation`` and stores it exactly as ``o.x = v`` alone does,
    binding what a later read of the place reads.
    """

    bindings: tuple
    stores: tuple
    value: object
    site: object = dataclass_field(compare=False)
    evaluations: tuple = ()  # (name, key) per Name target, as AssignSugar's
    evaluation: str | None = None  # the key the stores read the value under
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
        evaluations = _evaluation_indices(self.evaluations, bind)
        if self.evaluation is not None:
            evaluations = (*evaluations, (self.evaluation, 0))
        if not self.stores:
            return evaluate_assignment_values(
                (self.value,),
                ctx,
                bind=bind,
                evaluations=evaluations,
                site=self.site,
            )
        if ctx is None:
            ctx = ReduceContext.root(owner="ChainedAssignSugar")

        def stores(active, completed):
            # The RHS was evaluated once, above, and bound under its key;
            # each store target's statement reads it there, left to right.
            del completed
            return _reduce_targets(self.stores, active, ctx)

        return evaluate_assignment_values(
            (self.value,), ctx, tail=stores, evaluations=evaluations
        )


@dataclass(frozen=True)
class KeyedStoreSugar(Sugar):
    """``o.x = v`` whose stored value a later read of the place reads.

    Substitution threads the store into later reads of the place (``o.x``
    on a coordinate receiver, ``_ReceiverFieldProjection``; every read of
    ``o`` after a receiver field store, ``ReceiverFieldStoreState``).  Each
    such read is a reference to this statement's evaluation (``place``),
    never ``v`` inlined at the read and evaluated again against whatever was
    rebound since (``o.x = x; x += 1; return o.x``).

    ``value`` is the right-hand side, evaluated HERE, once: its halts are the
    statement's, and its completed value is bound under ``evaluation``.
    ``store`` is the store itself, built with its value read through that
    key, and runs after the value is bound (Python evaluates the right-hand
    side before the target).
    """

    value: Sugar
    store: Sugar
    evaluation: str
    site: object = dataclass_field(compare=False)
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

        return evaluate_assignment_values(
            (self.value,), ctx, tail=store, evaluations=((self.evaluation, 0),)
        )


@dataclass(frozen=True)
class DynamicUnpackStoreAssignSugar(Sugar):
    """Non-display RHS: flat Name|Attribute|Subscript|*Name unpack (LTR).

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
    # applies its member; a target's halt carries the record the targets'
    # block gave it (``_apply_authenticated_roster``).
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
        self._require_typed_targets()
        operation, expected_demand_cid = self._operation()
        return self.value.desugar(ctx).and_then(
            lambda value: self._unpack(operation, expected_demand_cid, value, ctx)
        )

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

        unpacked = operation.submit(value, ctx)
        if len(unpacked.exits) == 1:
            # One way in: the stores are exactly what follows it, a store
            # waiting on its caller's actuals handed on.
            return unpacked.and_then(apply)
        # A runtime unpack's two faces: the stores run beneath its completed
        # arm (a deferred store composed there), its halt an arm as it is.
        return unpacked.sequence(apply)

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


@dataclass(frozen=True)
class UnpackStoreAssignSugar(Sugar):
    """Flat display unpack with Attribute/Subscript store leaves (and optional Names).

    Python law this sugar sequences (the unpack's own faces, not a second store
    door):

    - RHS display members are already projected one-to-one onto leaves at tree
      construction (arity decided there; mismatch stays loud until a ground
      ``ValueError`` exit exists).
    - Name leaves are spent by substitute (same as MultiAssign) — binding
      before later store leaves run.
    - Each store leaf's member is bound under its member key (``members``)
      when it completes; the store leaves' own statements
      (``Assign._store_statements``) then run left to right, each reading
      its member there and storing it exactly as ``o.x = v`` alone does. A
      later halt means the statement did not complete; earlier bindings and
      completed stores are not rolled back.

    One temporal model: names thread, stores effect — no second door.
    """

    bindings: tuple  # (name, value_sugar) — provenance; substitute spent them
    stores: tuple  # each store leaf's own statement's sugar, left to right
    site: object = dataclass_field(compare=False)
    evaluations: tuple = ()  # (name, key) per Name leaf, as AssignSugar's
    members: tuple = ()  # (member key, value_sugar) per store leaf
    # A record-less halt is a RHS member's, before any target is assigned;
    # the stores' halts carry the record their block gave them.
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        return typed_red_effect_witness(
            name="unpack_attribute_store",
            owner_sugar="UnpackStoreAssignSugar",
            source=("def A(o, p, q):\n" "    o.x, o.y = p, q\n" "    return p\n"),
            effect_class="UndeterminedRaiseEffect",
            reason_needle="undetermined exception identity",
            blame_needle="SourceFragment",
            wrong_reason_needle="raise AttributeError",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        # Name bindings are spent by substitute; only store effects remain.
        # Sequencing of store success/halt is the shared reducer — not a local
        # second composition algebra.
        from sugar_lift_py_tests.context import ReduceContext
        from sugar_lift_py_tests.sugar.assigned_value import (
            evaluate_assignment_values,
        )

        if ctx is None:
            ctx = ReduceContext.root(owner="UnpackStoreAssignSugar")
        # Python evaluates the whole RHS display first, left to right, then
        # assigns each target left to right. Every RHS member is evaluated
        # here in source order and bound under its keys; a store then reads
        # its member there and evaluates only its own target.
        values = sorted(
            (
                *(value for _name, value in self.bindings),
                *(value for _key, value in self.members),
            ),
            key=_source_start,
        )
        values = _distinct_in_order(values)

        def index(value):
            return next(i for i, v in enumerate(values) if v is value)

        def stores(active, completed):
            del completed
            return _reduce_targets(self.stores, active, ctx)

        bind = tuple((name, index(value)) for name, value in self.bindings)
        return evaluate_assignment_values(
            values,
            ctx,
            tail=stores if self.stores else None,
            evaluations=(
                *_evaluation_indices(self.evaluations, bind),
                *((key, index(value)) for key, value in self.members),
            ),
        )


def _evaluation_indices(evaluations, bind):
    """``(key, value index)`` for each keyed name: ``evaluations`` holds
    ``(name, key)`` (``Assign.target_evaluations``), ``bind`` the index of
    the value each name is bound to."""
    keys = dict(evaluations)
    return tuple((keys[name], index) for name, index in bind if name in keys)


def _reduce_targets(targets, active, ctx):
    """The statement's store targets, after its RHS completed.

    Where the RHS recorded nothing and bound no evaluation this is the block
    the statement always reduced to; where it recorded completed values or
    bound a Name target's evaluation, the targets' exits carry that context
    on to the next statement.
    """
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
        reduce_body,
    )

    if getattr(active, "assigned_values", ()) == getattr(
        ctx, "assigned_values", ()
    ) and (ctx is None or getattr(active, "temporal", None) is ctx.temporal):
        return reduce_body(targets, active)
    return reduce_block_to_exitset(targets, active)


def _distinct_in_order(values):
    """Each RHS sugar once, in order: ``x = y = e`` evaluates ``e`` once."""
    seen = []
    for value in values:
        if any(value is prior for prior in seen):
            continue
        seen.append(value)
    return tuple(seen)


def _source_start(sugar):
    site = getattr(sugar, "site", None)
    span = getattr(site, "span", None)
    return getattr(span, "start", 0)


def _chained_names(bindings):
    """The lexical names a chained assignment binds (``x = y = e``)."""
    return tuple(
        binding if isinstance(binding, str) else binding[0] for binding in bindings
    )

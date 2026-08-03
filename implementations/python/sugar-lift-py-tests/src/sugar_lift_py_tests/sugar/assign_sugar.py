from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import (
    NotVerdictBearing,
    _call_pair,
    typed_red_effect_witness,
)


@dataclass(frozen=True)
class AssignSugar(Sugar):
    """A `name = <rhs>` statement -- SPENT by the time it reaches the meaning layer.

    substitute runs before sugar (FunctionDef.sugar), and an assignment IS a
    temporal binding: substitute threads it, inlining the rhs into every later
    reference of the name. So by the time this sugar reduces, the binding has
    already done its work in the tree -- there is nothing left to state. An
    assignment contributes no fact, no post, no effect; it is inert meaning.

    (The rhs is not re-stated either: wherever the name was used, the rhs node
    was substituted in and sugared THERE, in the position that consumes it.)

    Meaning-only, node-constructed: no owns/new/role. Single Name target only;
    other target shapes stay gaps on the tree node.
    """

    name: str
    value: object  # the rhs sugar -- provenance only; substitute already inlined it
    site: object = dataclass_field(compare=False)

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

    def desugar(self, ctx: object = None) -> Outcome:
        # Inert: the binding was consumed by substitute. Contribute nothing.
        from sugar_lift_py_tests.floor.block_value import BlockValue

        return Complete(BlockValue((), can_fall_through=True))


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

    def desugar(self, ctx: object = None) -> Outcome:
        # Inert: every binding was consumed by substitute. Contribute nothing.
        from sugar_lift_py_tests.floor.block_value import BlockValue

        return Complete(BlockValue((), can_fall_through=True))


@dataclass(frozen=True)
class ChainedAssignSugar(Sugar):
    """One evaluated RHS distributed left-to-right across names and stores."""

    bindings: tuple
    stores: tuple
    value: object
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="typed store effect",
            reason="mixed chained stores stay red while lexical bindings continue",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_body

        return self.value.desugar(ctx).and_then(
            lambda value: (
                reduce_body(
                    tuple(
                        _PreconstructedStoreSugar(store, value) for store in self.stores
                    ),
                    ctx,
                )
                if self.stores
                else Complete(BlockValue((), can_fall_through=True))
            )
        )


@dataclass(frozen=True)
class _PreconstructedStoreSugar(Sugar):
    """One chained target consuming the statement's already-reduced RHS."""

    store: Sugar
    value: object

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="chained store projection",
            reason="the public ChainedAssignSugar twins own RHS-once sequencing",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.store.desugar_store(ctx, self.value)


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

    @classmethod
    def witnesses(cls):
        return typed_red_effect_witness(
            name="dynamic_unpack_store_star",
            owner_sugar="DynamicUnpackStoreAssignSugar",
            source=("def A(o, xs):\n" "    o.x, *rest = xs\n" "    return rest\n"),
            effect_class="SequenceUnpackRuntimeEffect",
            reason_needle="sequence unpack",
            blame_needle="at least 1 members",
            wrong_reason_needle="unpack demands exactly 3 members",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.operations.positional_unpack_operation import (
            PositionalUnpackOperation,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )
        from sugar_lift_py_tests.sugar.unpack_projection_targets import (
            ApplyUnpackMemberSugar,
            UnpackProjectionTarget,
        )

        for target in self.targets:
            if not isinstance(target, UnpackProjectionTarget):
                raise TypeError(
                    "DynamicUnpackStoreAssignSugar.targets must be "
                    f"UnpackProjectionTarget; got {type(target).__name__}"
                )
        prefix, suffix, has_star = self._fixed_counts()
        operation = PositionalUnpackOperation(
            fixed_prefix=prefix,
            fixed_suffix=suffix,
            has_star=has_star,
            owner=type(self).__name__,
            blame=self.site,
        )
        expected_demand_cid = operation.demand_cid()
        return self.value.desugar(ctx).and_then(
            lambda value: operation.submit(value, ctx).and_then(
                lambda roster: self._apply_authenticated_roster(
                    roster,
                    expected_demand_cid=expected_demand_cid,
                    ctx=ctx,
                )
            )
        )

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
    - Store leaves desugar left-to-right through ``reduce_body``: each reuses
      the Attribute/Subscript store law (#6599 / attribute-store window). A
      later halt means the statement did not complete; earlier bindings and
      completed stores are not rolled back.

    One temporal model: names thread, stores effect — no second door.
    """

    bindings: tuple  # (name, value_sugar) — provenance; substitute spent them
    stores: tuple  # AttributeStoreEffectSugar | SubscriptStoreEffectSugar | PlaceAssign
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return typed_red_effect_witness(
            name="unpack_attribute_store",
            owner_sugar="UnpackStoreAssignSugar",
            source=("def A(o, p, q):\n" "    o.x, o.y = p, q\n" "    return p\n"),
            effect_class="AttributeStoreRuntimeEffect",
            reason_needle="attribute store",
            blame_needle="attr=x",
            wrong_reason_needle="attribute store target `.z`",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_body

        # Name bindings are spent by substitute; only store effects remain.
        # Sequencing of store success/halt is the shared reducer — not a local
        # second composition algebra.
        if not self.stores:
            return Complete(BlockValue((), can_fall_through=True))
        return reduce_body(self.stores, ctx)

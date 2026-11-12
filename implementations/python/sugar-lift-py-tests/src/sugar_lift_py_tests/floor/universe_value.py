from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue


@dataclass(frozen=True)
class UniverseValue(FloorValue):
    """A function body lowered to its universe: name, formals, record. The
    slots are PROJECTIONS of the record -- each entry answers for itself
    (inv_contribution / post_contribution), the universe just concatenates.
    invs are the stated facts; post is `out == <exit term>`."""

    name: str
    formals: tuple[str, ...]
    record: object  # the body's BlockValue
    bridge_source_symbol: str | None = None
    formal_coordinates: tuple = ()

    def guarded(self, formula):
        """Ride under a branch by guarding every body record entry.

        Nested ``def`` under ``if`` places this universe as a block entry; the
        if/exit-set router then calls ``entry.guarded(guard)``. Each statement
        already owns its own guarded arm (InvValue → implication, ReturnValue →
        GuardedReturn, …); reassemble the same universe shape over the guarded
        entries. Full-dump: 26 of 32 ``guarded`` panics were UniverseValue.
        """
        from dataclasses import replace

        from sugar_lift_py_tests.floor.block_value import BlockValue

        guarded_entries = tuple(
            entry.guarded(formula) for entry in self.record.statements
        )
        if isinstance(self.record, BlockValue):
            record = replace(self.record, statements=guarded_entries)
        else:
            record = BlockValue(guarded_entries)
        return replace(self, record=record)

    def derived_companions(self) -> tuple[Formula, ...]:
        return tuple(
            formula
            for entry in self.record.statements
            for formula in getattr(entry, "derived_post_contribution", lambda: ())()
        )

    def invs(self) -> tuple[Formula, ...]:
        return tuple(
            formula
            for entry in self.record.statements
            for formula in entry.inv_contribution()
        )

    def post(self) -> Formula:
        from sugar_lift_py_tests.caller_parameter_contract import (
            ContractConditionalConstructionV1,
        )

        # A pending conditional candidate is NOT projectable. The resume path
        # MECHANICALLY REPLACES each exactly-resolved candidate with its retained
        # .value before projecting, so a resumed record reaches post() with NO
        # pending entry. Any candidate still standing here means no resume
        # authorized it -- post() panics (resume-exclusive; never a fast lane).
        pending = tuple(
            entry
            for entry in self.record.statements
            if isinstance(entry, ContractConditionalConstructionV1)
        )
        if pending:
            from sugar_lift_py_tests.gap.info import GapKind, GapLocus
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="UniverseValue.post",
                blame=self.name,
                observed=(
                    "pending parameter contract demands "
                    + ",".join(
                        demand.demand_cid
                        for entry in pending
                        for demand in entry.demands
                    )
                ),
                requested="authenticated ParameterContractResolutionV1 rows",
                fix=(
                    "discharge every exact demand/candidate CID through the Rust "
                    "linker; never admit the serialized candidate before resolution"
                ),
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        exits = tuple(
            formula
            for entry in self.record.statements
            for formula in entry.post_contribution()
        )
        if not exits:
            from sugar_lift_py_tests.floor.guarded_raise import GuardedRaise
            from sugar_lift_py_tests.floor.raise_value import RaiseValue

            raises = tuple(
                entry
                for entry in self.record.statements
                if isinstance(entry, (RaiseValue, GuardedRaise))
            )
            if not raises:
                from sugar_lift_py_tests.floor.none_value import NoneValue
                from sugar_lift_py_tests.ir import eq, make_var

                return eq(
                    make_var("out"),
                    NoneValue().to_term(owner="UniverseValue.post"),
                )
            from sugar_lift_py_tests.gap.panic import construction_panic_gap
            from sugar_lift_py_tests.gap.info import GapKind, GapLocus

            construction_panic_gap(
                owner="UniverseValue",
                blame=self.name,
                observed="raise-only exits",
                requested="a post slot",
                fix=(
                    "preserve the carried raise effect; do not fabricate an "
                    "implicit None post for a raise-only body"
                ),
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        post = exits[0] if len(exits) == 1 else None
        from sugar_lift_py_tests.ir import and_

        if post is None:
            post = and_(list(exits))
        companions = self.derived_companions()
        if not companions:
            return post
        return and_([post, *companions])

    def call_edges(self):
        # The record entries project their own call edges (CallSiteValue direct,
        # InvValue via carried operand_callsites, GuardedFaces via children).
        return tuple(
            edge
            for entry in self.record.statements
            for edge in entry.edge_contribution(self.name)
        )

    def mints(self):
        # The record entries mint their own rows; the universe mints its post
        # (Derived: the lift composed it from the exits).
        from sugar_lift_py_tests.floor.universe_mint_projection import claim_formula
        from sugar_lift_py_tests.proofir.nodes import (
            ConstructionSite,
            Derived,
            Provenance,
        )
        from sugar_lift_py_tests.proofir.nodes.universe_mint import UniverseMint

        rows = tuple(
            row
            for entry in self.record.statements
            for row in entry.mint_contribution(self.name, self.formals)
        )
        post_provenance = Provenance(
            node_class="UniverseMint",
            construction_site=ConstructionSite(path=self.name, line=0, column=0),
            warrant=Derived(floor_chain=("UniverseValue.post",)),
        )
        return (
            *rows,
            UniverseMint(
                name=self.name,
                slot="post",
                formula=claim_formula(
                    self.post(),
                    formals=self.formals,
                    provenance=post_provenance,
                    role="post",
                ),
                provenance=post_provenance,
                formals=self.formals,
            ),
        )

    def link_unit_projection(self, def_memento):
        """PRE-POST projection: assemble this function's ParameterContractLinkUnitV1
        WITHOUT calling post(). Gathers the pending ContractConditionalConstructionV1
        the body enrolled, emits the ParameterOwnedContractV1 (its own formals +
        the demands it STRUCTURALLY OWNS), and returns the link unit. The RPC
        level retains this immutable universe keyed by link_unit_cid so Phase-3
        resume reuses it (materialize-once) rather than reconstructing."""
        from sugar_lift_py_tests.caller_parameter_contract import (
            ContractConditionalConstructionV1,
            ParameterContractLinkUnitV1,
            ParameterOwnedContractV1,
        )

        pending = tuple(
            entry
            for entry in self.record.statements
            if isinstance(entry, ContractConditionalConstructionV1)
        )
        coords = tuple(self.formal_coordinates)
        if not coords:
            # No formals -> no formal coordinate -> no demand can be owned here.
            if pending:
                from sugar_lift_py_tests.gap.info import GapKind, GapLocus
                from sugar_lift_py_tests.gap.panic import construction_panic_gap

                construction_panic_gap(
                    owner="UniverseValue.link_unit_projection",
                    blame=self.name,
                    observed="pending demands without any formal coordinate",
                    requested="a formal coordinate that owns each demand",
                    fix="thread formal coordinates into the universe",
                    gap_kind=GapKind.FLOOR,
                    gap_locus=GapLocus.CONSTRUCTION,
                )
            return None
        owner_cid = coords[0].owner_source_identity_cid
        owner_locus = coords[0].owner_definition_locus
        coord_cids = {coordinate.coordinate_cid for coordinate in coords}
        # Flatten over the entry's demand SET (#6352). `contribution` already
        # split it into one row per demand on the way into the record, so this
        # normally sees singletons; iterating the set keeps the reader correct
        # for any producer that reaches the record without splitting, instead of
        # silently owning only the first.
        owned_demands = [
            demand.demand_cid
            for entry in pending
            for demand in entry.demands
            if demand.formal_coordinate_cid in coord_cids
            and demand.owner_source_identity_cid == owner_cid
        ]
        owned = ParameterOwnedContractV1.mint(
            name=self.name,
            owner_source_identity_cid=owner_cid,
            owner_definition_locus=owner_locus,
            formal_coordinates=coords,
            declared_demand_cids=owned_demands,
        )
        return ParameterContractLinkUnitV1.mint(
            source_memento=def_memento,
            parameter_owned_contract=owned,
            candidates=pending,
            call_edges=(),
        )


def _stated_formal_sorts(formals, formal_coordinates):
    """One sort per formal, or none at all.

    A formal coordinate of an abstract definition carries its sort; the
    binding coordinate of a frame applied at a call (``BindingCoordinateV1``)
    carries none. A signature is stated only when every formal has a sorted
    coordinate: a partial signature would be a claim nothing made.
    """
    sorts = [getattr(coordinate, "sort", None) for coordinate in formal_coordinates]
    if len(sorts) != len(formals) or any(sort is None for sort in sorts):
        return []
    return [{"kind": "primitive", "name": sort.name} for sort in sorts]


def function_contract_row(
    *, name, formals, bridge_source_symbol, formal_coordinates, post, def_memento
):
    """The one function-contract row: the post, the def's sealed warrant.

    ``formalSorts`` states one sort per formal, the sort its authenticated
    formal coordinate carries (the same statement ``ParameterOwnedContractV1``
    makes). The linker's catalog reads a contract's signature from it.
    """
    from sugar_lift_py_tests.floor.universe_mint_projection import claim_formula
    from sugar_lift_py_tests.kit_rpc import BodyUniverseDto
    from sugar_lift_py_tests.proofir.nodes import (
        ConstructionSite,
        Derived,
        Provenance,
    )

    span = def_memento.span
    post_provenance = Provenance(
        node_class="BodyUniverseDto",
        construction_site=ConstructionSite(
            path=def_memento.file,
            line=span.start_line,
            column=span.start_col,
        ),
        warrant=Derived(floor_chain=("UniverseValue.post",)),
    )
    return BodyUniverseDto(
        name=name,
        post=claim_formula(
            post,
            formals=formals,
            provenance=post_provenance,
            role="post",
        ),
        source_warrants=[def_memento],
        formals=list(formals),
        formal_sorts=_stated_formal_sorts(formals, formal_coordinates),
        kind="function-contract",
        bridge_source_symbol=bridge_source_symbol or name,
    )


def mint_rows(name, formals, entries):
    """The contract rows the record entries mint for themselves."""
    import dataclasses

    from sugar_lift_py_tests.kit_rpc import BodyUniverseDto

    rows = []
    for entry in entries:
        for row in entry.mint_contribution(name, formals):
            rows.append(
                BodyUniverseDto(
                    name=row.name,
                    inv=row.formula,
                    source_warrants=[
                        dataclasses.replace(
                            warrant,
                            source_function_name=name,
                            role="assertion",
                        )
                        for warrant in row.source_warrants
                    ],
                    formals=list(row.formals),
                    kind="contract",
                    proofir_provenance=row.provenance().to_rpc(),
                )
            )
    return rows


def assertion_site_key(site):
    """An assertion site's identity: the fragment's own address."""
    from sugar_lift_py_tests.effect.runtime_effect import resolve_runtime_effect_site

    fragment = resolve_runtime_effect_site(site)
    return (fragment.filename, fragment.line, fragment.col)


def exit_arms_payload_rows(
    *,
    name,
    formals,
    bridge_source_symbol,
    formal_coordinates,
    arms,
    halted_assertion_sites,
    def_memento,
):
    """Every arm of one reduction, projected to the wire (#7766).

    ``arms`` are the completed arms ``(guard, UniverseValue)``.
    ``halted_assertion_sites`` are the ``assert`` statements at which a halted
    arm of the SAME reduction left: the reduction reached the assertion and
    control halted there.

    * post: the conjunction over completed arms of ``g_i -> post_i``.
    * one contract row per assertion SITE the reduction evaluated: the OR over
      the completed arms that hold the site of ``g_i AND fact_i``. The claim of
      an assertion is that an execution reaches it and it holds there; a guard
      that can be made false must not satisfy it, so this is never
      ``g -> fact``. A site an arm halted at and no completed arm holds states
      the OR over nothing: false.

    Every site comes from the reduction. An ``assert`` no arm evaluated (dead
    code: a handler that never runs, a branch the floor decided away) has no
    row, because nothing was reduced there; and a fact held on an arm that
    later halts elsewhere is not a completed arm's fact.

    This is the ONE projection from a reduction to rows; a single arm under
    guard true is its one-arm case and keeps the rows it always had.
    """
    from sugar_lift_py_tests.floor.inv_value import InvValue
    from sugar_lift_py_tests.ir import and_, implies, or_
    from sugar_lift_py_tests.outcome.exit_set import _is_true, false_guard

    if len(arms) == 1 and _is_true(arms[0][0]):
        guard, value = arms[0]
        rows = [
            function_contract_row(
                name=name,
                formals=formals,
                bridge_source_symbol=bridge_source_symbol,
                formal_coordinates=formal_coordinates,
                post=value.post(),
                def_memento=def_memento,
            )
        ]
        rows.extend(mint_rows(name, formals, value.record.statements))
        reached = {
            assertion_site_key(entry.site)
            for entry in value.record.statements
            if isinstance(entry, InvValue)
        }
    else:
        post = and_([implies(guard, value.post()) for guard, value in arms])
        rows = [
            function_contract_row(
                name=name,
                formals=formals,
                bridge_source_symbol=bridge_source_symbol,
                formal_coordinates=formal_coordinates,
                post=post,
                def_memento=def_memento,
            )
        ]
        by_site: dict = {}
        for arm_index, (guard, value) in enumerate(arms):
            for entry in value.record.statements:
                if isinstance(entry, InvValue):
                    key = assertion_site_key(entry.site)
                    by_site.setdefault(key, {}).setdefault(arm_index, (guard, []))[
                        1
                    ].append(entry)
                    continue
                if entry.mint_contribution(name, formals):
                    from sugar_source_tree.panic import SugarNotWritten

                    raise SugarNotWritten(
                        owner="exit_arms_payload_rows",
                        blame=name,
                        observed=f"{type(entry).__name__} mints rows on one arm of several",
                        requested="the entry's rows under its arm's guard",
                        fix=(
                            f"give {type(entry).__name__} the arm-guarded "
                            "projection InvValue has"
                        ),
                    )
        reached = set(by_site)
        combined = []
        for per_arm in by_site.values():
            arm_rows = list(per_arm.values())
            first = arm_rows[0][1][0]
            derived_arms = [
                (guard, [d for inv in invs for d in inv.derived_formulas])
                for guard, invs in arm_rows
            ]
            derived = (
                (or_([and_([guard, *ds]) for guard, ds in derived_arms]),)
                if all(ds for _guard, ds in derived_arms)
                else ()
            )
            combined.append(
                InvValue(
                    or_(
                        [
                            and_([guard, *(inv.formula for inv in invs)])
                            for guard, invs in arm_rows
                        ]
                    ),
                    first.site,
                    tuple(
                        callsite
                        for _guard, invs in arm_rows
                        for inv in invs
                        for callsite in inv.operand_callsites
                    ),
                    derived,
                    tuple(
                        chain
                        for _guard, invs in arm_rows
                        for inv in invs
                        for chain in inv.rewrite_chains
                    ),
                )
            )
        rows.extend(mint_rows(name, formals, combined))
    never_held = []
    for site in halted_assertion_sites:
        key = assertion_site_key(site)
        if key in reached:
            continue
        reached.add(key)
        never_held.append(InvValue(false_guard(), site))
    rows.extend(mint_rows(name, formals, never_held))
    return rows

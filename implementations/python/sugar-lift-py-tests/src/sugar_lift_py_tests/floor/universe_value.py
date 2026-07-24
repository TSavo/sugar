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
    # Phase-3: authenticated {demand_cid: resolution} attached by the resume when
    # reusing THIS retained universe (materialize-once). None on the plain path.
    resolutions: object = None

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

        pending = tuple(
            entry
            for entry in self.record.statements
            if isinstance(entry, ContractConditionalConstructionV1)
        )
        # Resume-exclusive: post() projects ONLY when every pending demand has an
        # authenticated resolution attached by the Phase-3 resume. A plain
        # enumerate (resolutions=None) of a pending-demand universe STILL panics
        # -- the resume is the sole projection path, never a fast lane.
        resolved = self.resolutions or {}
        unresolved = tuple(
            entry
            for entry in pending
            if entry.demand.demand_cid not in resolved
        )
        if unresolved:
            from sugar_lift_py_tests.gap.info import GapKind, GapLocus
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="UniverseValue.post",
                blame=self.name,
                observed=(
                    "pending parameter contract demands "
                    + ",".join(entry.demand.demand_cid for entry in unresolved)
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
        owned_demands = [
            entry.demand.demand_cid
            for entry in pending
            if entry.demand.formal_coordinate_cid in coord_cids
            and entry.demand.owner_source_identity_cid == owner_cid
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

    def payload_rows(self, def_memento):
        # The wire projection: one function-contract row (post + the def's
        # sealed warrant) and one contract row per stated inv (Stated, its
        # own warrant). The caller owns the loop; this value owns the shape.
        import dataclasses

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
        rows = [
            BodyUniverseDto(
                name=self.name,
                post=claim_formula(
                    self.post(),
                    formals=self.formals,
                    provenance=post_provenance,
                    role="post",
                ),
                source_warrants=[def_memento],
                formals=list(self.formals),
                kind="function-contract",
                bridge_source_symbol=self.bridge_source_symbol or self.name,
            )
        ]
        rows.extend(self.inv_payload_rows())
        return rows

    def inv_payload_rows(self):
        """Project stated body claims without requiring a constructed post."""
        import dataclasses

        from sugar_lift_py_tests.kit_rpc import BodyUniverseDto

        rows = []
        for entry in self.record.statements:
            for row in entry.mint_contribution(self.name, self.formals):
                rows.append(
                    BodyUniverseDto(
                        name=row.name,
                        inv=row.formula,
                        source_warrants=[
                            dataclasses.replace(
                                warrant,
                                source_function_name=self.name,
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

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace
import json
from typing import Any

from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.context_manager_contract import _json_value
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.ir import (
    Formula,
    Term,
    atomic,
    ctor,
    formula_to_value,
    str_const,
    term_to_value,
)


class NativeOperationResolutionV1:
    """The closed caller-discharge result for one native operation.

    The exceptional arm is authenticated only when both the exception type
    coordinate and operation occurrence coordinate are present.  A halt without
    those coordinates is not a fourth exit kind: it remains ``undischarged``.
    """

    __slots__ = (
        "_kind",
        "value",
        "exception_type_coordinate",
        "raise_occurrence_coordinate",
        "reason",
    )

    def __init__(
        self,
        *,
        kind,
        value=None,
        exception_type_coordinate=None,
        raise_occurrence_coordinate=None,
        reason=None,
    ):
        if kind not in {"completed", "exceptional", "undischarged"}:
            raise ValueError(f"unknown native operation resolution: {kind}")
        if kind == "completed" and value is None:
            raise ValueError("completed native operation requires a value")
        if kind == "exceptional" and (
            exception_type_coordinate is None or raise_occurrence_coordinate is None
        ):
            raise ValueError(
                "exceptional native operation requires authenticated type and occurrence"
            )
        if kind == "undischarged" and not reason:
            raise ValueError("undischarged native operation requires a reason")
        if kind != "exceptional" and (
            exception_type_coordinate is not None
            or raise_occurrence_coordinate is not None
        ):
            raise ValueError(
                "non-exceptional resolution cannot carry exception testimony"
            )
        self._kind = kind
        self.value = value
        self.exception_type_coordinate = exception_type_coordinate
        self.raise_occurrence_coordinate = raise_occurrence_coordinate
        self.reason = reason

    @classmethod
    def completed(cls, value):
        return cls(kind="completed", value=value)

    @classmethod
    def exceptional(cls, *, exception_type_coordinate, operation_occurrence):
        return cls(
            kind="exceptional",
            exception_type_coordinate=exception_type_coordinate,
            raise_occurrence_coordinate=operation_occurrence,
        )

    @classmethod
    def undischarged(cls, reason: str):
        return cls(kind="undischarged", reason=reason)

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def is_completed(self) -> bool:
        return self._kind == "completed"

    @property
    def has_authenticated_exception_type(self) -> bool:
        return (
            self._kind == "exceptional"
            and self.exception_type_coordinate is not None
            and self.raise_occurrence_coordinate is not None
        )

    @property
    def is_undischarged(self) -> bool:
        return self._kind == "undischarged"

    @property
    def is_exceptional(self) -> bool:
        return self._kind == "exceptional"

    @property
    def is_authenticated_exceptional_exit(self) -> bool:
        """The only resolution arm admitted to an authenticated-exit tally."""
        return self.has_authenticated_exception_type

    def project(self, *, source_node):
        """Project the closed resolution into an ExitSet or a typed refusal."""
        from sugar_lift_py_tests.effect import RaiseEffect
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_source_tree.panic import SugarNotWritten

        if self.is_completed:
            return ExitSet.completed(self.value)
        if self.has_authenticated_exception_type:
            occurrence = self.raise_occurrence_coordinate
            assert occurrence is not None
            return ExitSet.halted(
                RaiseEffect(
                    exception_type_coordinate=self.exception_type_coordinate,
                    occurrence=str(occurrence.wire()),
                    blame=str(occurrence.wire()),
                )
            )
        raise SugarNotWritten(
            blame=str(source_node),
            owner="NativeOperationResolutionV1.project",
            observed=self.reason or "native operation exception identity unproven",
            requested="authenticated exception type and operation occurrence coordinates",
            fix="retain the operation as undischarged until both coordinates are proven",
        )


def authenticated_exceptional_resolution_count(resolutions) -> int:
    """Count named exceptional resolutions by coordinates, never by arm kind."""
    return sum(
        resolution.is_authenticated_exceptional_exit for resolution in resolutions
    )

def _json(value) -> Any:
    return json.loads(encode_jcs(value))


def _cid(value: Any) -> str:
    return blake3_512_of(encode_jcs(_json_value(value)).encode("utf-8"))


def source_coordinate(site) -> SourceFragmentCoordinateV1:
    span = site.line_col_span
    return SourceFragmentCoordinateV1(
        site.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def native_operator_demand(operator: str, operands: tuple[Term, ...]) -> Formula:
    """The unresolved caller obligation for one ordered native operation.

    This formula records a question.  It does not choose a result, an exception
    type, or a runtime coordinate; caller discharge supplies authenticated
    actual operands and the ordinary Floor answers the question later.
    """
    return atomic(
        "python:native_operator_demand",
        [str_const(operator), *operands],
    )


@dataclass(frozen=True)
class NativeOperationDemandV1:
    """Content identity for an ordered native-operation occurrence."""

    source_node: SourceFragmentCoordinateV1
    operator: str
    operand_terms: tuple[Term, ...]
    operand_coordinate_cids: tuple[str | None, ...]
    candidate: Term
    candidate_cid: str
    demanded_formula: Formula
    demand_cid: str

    @classmethod
    def mint(cls, *, site, operator, operands, coordinates):
        if not isinstance(operator, str) or not operator:
            raise ValueError("native operation requires a nonempty operator")
        operands = tuple(operands)
        coordinates = tuple(coordinates)
        if not operands or len(coordinates) != len(operands):
            raise ValueError(
                "native operation requires ordered operands and aligned coordinates"
            )

        source_node = source_coordinate(site)
        operand_terms = tuple(
            operand.to_term(owner=f"native operation {operator} operand")
            for operand in operands
        )
        coordinate_cids = tuple(
            None if coordinate is None else coordinate.coordinate_cid
            for coordinate in coordinates
        )
        candidate = ctor(
            "python:native_operation",
            [str_const(operator), *operand_terms],
        )
        candidate_preimage = {
            "kind": "native-operation-candidate",
            "schemaVersion": "1",
            "sourceNode": source_node.wire(),
            "operator": operator,
            "operands": [_json(term_to_value(term)) for term in operand_terms],
            "formalCoordinates": list(coordinate_cids),
            "candidate": _json(term_to_value(candidate)),
        }
        candidate_cid = _cid(candidate_preimage)
        demanded_formula = native_operator_demand(operator, operand_terms)
        demand_preimage = {
            "kind": "native-operation-demand",
            "schemaVersion": "1",
            "sourceNode": source_node.wire(),
            "operator": operator,
            "operands": [_json(term_to_value(term)) for term in operand_terms],
            "formalCoordinates": list(coordinate_cids),
            "candidateCid": candidate_cid,
            "demandedFormula": _json(formula_to_value(demanded_formula)),
        }
        return cls(
            source_node=source_node,
            operator=operator,
            operand_terms=operand_terms,
            operand_coordinate_cids=coordinate_cids,
            candidate=candidate,
            candidate_cid=candidate_cid,
            demanded_formula=demanded_formula,
            demand_cid=_cid(demand_preimage),
        )


@dataclass(frozen=True)
class NativeOperationExitCarrierV1:
    """Deferred native operation whose discharge codomain is an ``ExitSet``.

    The same recorded operation can complete or raise after its formal operands
    are replaced by authenticated caller actuals.  Keeping that codomain here,
    rather than retaining a ``FloorValue``, is what preserves the exceptional
    arm until an enclosing effect boundary consumes it.
    """

    demand: NativeOperationDemandV1
    operands: tuple[FloorValue, ...]
    coordinates: tuple[object | None, ...]
    site: object = dataclass_field(compare=False, repr=False)
    continuations: tuple = dataclass_field(default=(), compare=False, repr=False)

    def __post_init__(self):
        operand_count = len(self.operands)
        coordinate_count = len(self.coordinates)
        demand_count = len(self.demand.operand_coordinate_cids)
        if len({operand_count, coordinate_count, demand_count}) != 1:
            from sugar_lift_py_tests.gap.info import GapKind
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="NativeOperationExitCarrierV1.__post_init__",
                blame=self.demand.source_node,
                observed=(operand_count, coordinate_count, demand_count),
                requested="one authenticated coordinate slot per ordered operand",
                fix="rebuild the carrier with aligned operands and coordinates",
                gap_kind=GapKind.FLOOR,
            )
        stored_cids = tuple(
            None if coordinate is None else coordinate.coordinate_cid
            for coordinate in self.coordinates
        )
        if stored_cids != self.demand.operand_coordinate_cids:
            from sugar_lift_py_tests.gap.info import GapKind
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="NativeOperationExitCarrierV1.__post_init__",
                blame=self.demand.source_node,
                observed=(stored_cids, self.demand.operand_coordinate_cids),
                requested="stored coordinates authenticating to the demand CID tuple",
                fix="preserve ordered coordinate identity when constructing the carrier",
                gap_kind=GapKind.FLOOR,
            )

    @classmethod
    def mint(cls, *, site, operator, operands, coordinates):
        operands = tuple(operands)
        coordinates = tuple(coordinates)
        return cls(
            demand=NativeOperationDemandV1.mint(
                site=site,
                operator=operator,
                operands=operands,
                coordinates=coordinates,
            ),
            operands=operands,
            coordinates=coordinates,
            site=site,
        )

    def and_then(self, step):
        """Retain enclosing expression work until the operation discharges."""
        return replace(self, continuations=(*self.continuations, step))

    def discharge(self, actuals_by_formal_coordinate):
        """Evaluate against authenticated actual operands and project exits."""
        from sugar_lift_py_tests.floor import RaiseValue
        from sugar_lift_py_tests.outcome import Complete, ExitSet, Incomplete
        from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset

        def undischarged(reason):
            return NativeOperationResolutionV1.undischarged(reason).project(
                source_node=self.demand.source_node
            )

        actual_operands = []
        for original, coordinate_cid in zip(
            self.operands, self.demand.operand_coordinate_cids, strict=True
        ):
            if coordinate_cid is None:
                actual_operands.append(original)
                continue
            if coordinate_cid not in actuals_by_formal_coordinate:
                return undischarged(
                    "authenticated caller actual absent for "
                    f"{coordinate_cid}"
                )
            actual_operands.append(actuals_by_formal_coordinate[coordinate_cid])

        if len(actual_operands) not in {1, 2}:
            return undischarged(
                "native operation arity is unavailable until a unary or binary "
                f"producer is authenticated (arity={len(actual_operands)})"
            )
        left = actual_operands[0]
        operation = getattr(left, self.demand.operator, None)
        if not callable(operation):
            return undischarged(
                "native producer operation unavailable on authenticated actual: "
                f"{self.demand.operator}"
            )

        if len(actual_operands) == 1:
            projected = operation(self.site)
        elif len(actual_operands) == 2:
            projected = operation(actual_operands[1], self.site)
        else:
            return undischarged("native operation arity is unavailable")
        if isinstance(projected, Complete) and isinstance(projected.value, RaiseValue):
            effect = projected.value.effect
            if effect.exception_type_coordinate is None or effect.occurrence_id is None:
                resolution = NativeOperationResolutionV1.undischarged(
                    "native operation exception identity unproven"
                )
            else:
                resolution = NativeOperationResolutionV1.exceptional(
                    exception_type_coordinate=effect.exception_type_coordinate,
                    operation_occurrence=self.demand.source_node,
                )
            exits = resolution.project(source_node=self.demand.source_node)
        elif isinstance(projected, Complete):
            exits = NativeOperationResolutionV1.completed(projected.value).project(
                source_node=self.demand.source_node
            )
        elif isinstance(projected, Incomplete):
            exits = NativeOperationResolutionV1.undischarged(projected.reason).project(
                source_node=self.demand.source_node
            )
        elif isinstance(projected, ExitSet):
            exits = projected
        else:
            # Other Outcome variants must pass through the exit algebra's loud
            # door.  In particular, never reinterpret an unresolved carrier as
            # a normal completion.
            exits = outcome_to_exitset(projected)

        for continuation in self.continuations:
            exits = exits.and_then(continuation)
        return exits


@dataclass(frozen=True)
class ParameterContractDemandV1:
    owner_source_identity_cid: str
    formal_coordinate_cid: str
    operation_site: SourceFragmentCoordinateV1
    demanded_formula: Formula
    candidate_cid: str
    demand_cid: str

    @classmethod
    def mint(cls, **fields) -> "ParameterContractDemandV1":
        preimage = {
            "kind": "parameter-contract-demand",
            "schemaVersion": "1",
            "ownerSourceIdentityCid": fields["owner_source_identity_cid"],
            "formalCoordinateCid": fields["formal_coordinate_cid"],
            "operationSite": fields["operation_site"].wire(),
            "demandedFormula": _json(formula_to_value(fields["demanded_formula"])),
            "demandedEffectBound": None,
            "candidateCid": fields["candidate_cid"],
        }
        return cls(**fields, demand_cid=_cid(preimage))

    def to_value(self) -> dict[str, Any]:
        return {
            "kind": "parameter-contract-demand",
            "schemaVersion": "1",
            "ownerSourceIdentityCid": self.owner_source_identity_cid,
            "formalCoordinateCid": self.formal_coordinate_cid,
            "operationSite": self.operation_site.wire(),
            "demandedFormula": _json(formula_to_value(self.demanded_formula)),
            "demandedEffectBound": None,
            "candidateCid": self.candidate_cid,
            "demandCid": self.demand_cid,
        }


def merge_demands(*groups) -> tuple[ParameterContractDemandV1, ...]:
    """The demand SET: union by content address, ordered by content address.

    `demand_cid` is the content address of the WHOLE obligation — owner source
    identity, formal coordinate, operation site, demanded formula, candidate —
    so equal cids are the same obligation and dedupe is not a heuristic. It is
    the arithmetic of the obligation: a conjunction is idempotent, `F and F` IS
    `F`, and one obligation reaching a join twice through a shared outcome DAG
    (`p[0]` read once and consumed on both faces of a fold) is one obligation.

    Ordering is by cid, never by arrival. The universe is content: a set that
    ordered by the order two folds happened to run would make the same
    obligations mint two different rows, and there is no RNG and no clock here
    to justify that.
    """
    by_cid: dict[str, ParameterContractDemandV1] = {}
    for group in groups:
        for demand in group:
            by_cid.setdefault(demand.demand_cid, demand)
    return tuple(by_cid[cid] for cid in sorted(by_cid))


def merge_pending(*groups) -> tuple:
    """Union pending CARRIERS by candidate content address (#6352 family).

    The carrier set is the exit-level counterpart of ``merge_demands``. Two
    carriers are the same pending construction exactly when their
    ``candidate_cid`` agrees -- that address is taken over the source node AND
    the candidate term, so equal addresses are the same construction at the
    same site, and dedupe is arithmetic rather than a heuristic.

    Same candidate reaching a join twice: ONE carrier, demand sets unioned by
    ``merge_demands`` -- which is idempotent, so a shared outcome DAG that
    delivers the same obligation on two faces still owes it once. Different
    candidates: two carriers, both kept, nothing conjoined.

    Ordering is by ``candidate_cid``, never by arrival, for the reason
    ``merge_demands`` orders by ``demand_cid``: the universe is content, and
    two folds that happened to run in a different order must not mint two
    different rows.
    """
    # THE EMPTY AND SINGLETON CASES COST NOTHING. This is called once per exit
    # pair in `ExitSet.sequence` -- the innermost loop of every k-operand fold
    # in the lift -- and almost every arm owes nothing at all, so building a
    # dict, sorting it and rebuilding a tuple to answer `()` is work done per
    # arm per fold step for no result. A group of at most one carrier is
    # already sorted and already deduped, so it is returned as it stands.
    populated = [group for group in groups if group]
    if not populated:
        return ()
    if len(populated) == 1 and len(populated[0]) <= 1:
        return tuple(populated[0])

    by_candidate: dict[str, "ContractConditionalConstructionV1"] = {}
    for group in groups:
        for entry in group:
            prior = by_candidate.get(entry.candidate_cid)
            by_candidate[entry.candidate_cid] = (
                entry
                if prior is None
                else replace(
                    prior, demands=merge_demands(prior.demands, entry.demands)
                )
            )
    return tuple(by_candidate[cid] for cid in sorted(by_candidate))


def weaken_pending(entries, formula) -> tuple:
    """Every carrier in a group weakened to one guarded face.

    Weakening only some of a group would leave the rest owed unconditionally on
    a face that may never run, which is a STRONGER obligation than the source
    states -- the same reason ``demanded_under`` weakens every demand in a set.
    """
    return merge_pending(tuple(entry.demanded_under(formula) for entry in entries))


@dataclass(frozen=True)
class ContractConditionalConstructionV1:
    """A constructed value together with every caller obligation it incurred.

    `demands` is a SET, not one demand (#6352). One expression can incur several
    distinct obligations — `[p[0], q[1]]` owes `python:indexable(p)` AND
    `python:indexable(q)`, `f(p[0], q[1])` the same — and the entry used to hold
    exactly one. Every join that met a second one panicked NAMED: `collection
    TupleValue`, `IfExpSugar._join`, and `ContractConditionalConstructionV1
    .and_then` each said the same sentence, "widen ... to carry a demand SET".
    Three call sites requesting one widening is the ontology telling you it is
    missing a kind of thing, so the thing is here now.

    Two demands are NOT conjoined into one. Each carries its own
    `formal_coordinate_cid` and `owner_source_identity_cid`; fusing their
    formulas would mint one obligation attributed to one formal that actually
    spans two, which is a fabricated fact, not a smaller answer.

    THE WIRE SHAPE IS UNCHANGED. `contribution` splits the entry into one entry
    per demand before anything is projected, so `to_value`, the link unit, and
    the Rust linker still see exactly one demand per row. The set exists only
    in flight, where the joins happen.
    """

    source_node: SourceFragmentCoordinateV1
    candidate: Term
    candidate_cid: str
    demands: tuple[ParameterContractDemandV1, ...]
    value: FloorValue

    @classmethod
    def mint(cls, *, site, candidate, demand_formula, value, coordinate):
        source_node = source_coordinate(site)
        candidate_preimage = {
            "kind": "parameter-contract-candidate",
            "schemaVersion": "1",
            "sourceNode": source_node.wire(),
            "candidate": _json(term_to_value(candidate)),
        }
        candidate_cid = _cid(candidate_preimage)
        demand = ParameterContractDemandV1.mint(
            owner_source_identity_cid=coordinate.owner_source_identity_cid,
            formal_coordinate_cid=coordinate.coordinate_cid,
            operation_site=source_node,
            demanded_formula=demand_formula,
            candidate_cid=candidate_cid,
        )
        return cls(source_node, candidate, candidate_cid, (demand,), value)

    def and_then(self, step):
        """Continue with the carried value; every demand rides on the result.

        A following ``Complete`` takes the demands back and the entry rides on
        into the block record, where ``link_unit_projection`` enrols it and the
        linker discharges it.

        Anything else has nowhere to carry it, and this used to ``return
        following`` -- silently dropping the obligation. A dropped demand is
        never enrolled and never discharged, so `p[0]` would stand with no
        `python:indexable(p)` owed by anyone. That is not a smaller answer, it is
        a wrong one, and it is loud now. Measured on 25 pandas modules / 158
        functions: 4 such drops before this branch existed, and threading the
        collection/f-string/bool-op reducers through ``and_then`` exposed 20
        more that had previously been lost inside an `.value` read instead.
        """
        from sugar_lift_py_tests.outcome import Complete

        following = step(self.value)
        if isinstance(following, Complete):
            return replace(self, value=following.value)
        from sugar_lift_py_tests.floor.single_outcome_law import rewrap_pending

        return rewrap_pending(
            self,
            following,
            owner="ContractConditionalConstructionV1.and_then",
            blame=self.source_node,
        )

    def demanded_under(self, formula):
        """Weaken the pending obligation to a guarded face; carried value untouched.

        The demand is owed only where the branch runs. `python:indexable(p)` for
        `if c: return p[0]` is `c -> python:indexable(p)`, never the
        unconditional obligation: a caller that never takes the branch owes
        nothing. Re-minting changes `demand_cid`, which is correct -- it IS a
        different obligation.

        This is the half a caller wants when the caller is guarding the VALUE
        itself (an `IfExp` that fuses both arms into one `GuardedValue`), so
        guarding the value here too would guard it twice. `guarded` is the other
        door, for a caller that hands the whole entry under a branch.
        """
        from sugar_lift_py_tests.ir import implies

        # EVERY demand weakens. Weakening only one of a set would leave the
        # others owed unconditionally on a face that may never run, which is a
        # stronger obligation than the source states.
        return replace(
            self,
            demands=merge_demands(
                tuple(
                    ParameterContractDemandV1.mint(
                        owner_source_identity_cid=demand.owner_source_identity_cid,
                        formal_coordinate_cid=demand.formal_coordinate_cid,
                        operation_site=demand.operation_site,
                        demanded_formula=implies(formula, demand.demanded_formula),
                        candidate_cid=demand.candidate_cid,
                    )
                    for demand in self.demands
                )
            ),
        )

    def guarded(self, formula):
        """Ride under a branch: the CARRIED value guards, the DEMAND weakens.

        This entry is a wrapper -- `and_then` threads the branch's real floor
        value through `self.value`, and `resume_project` substitutes exactly
        that value once the linker discharges the demand. So a guard reaching
        this entry has two distinct arms to conserve, and neither may be
        dropped:

        1. The carried value guards the way it would have if no demand were
           pending (ReturnValue -> GuardedReturn, InvValue -> implication, ...).
           Guarding the wrapper without guarding the value would let the
           resumed record project an UNGUARDED return for a branch that only
           runs under `formula`.
        2. The demand is owed only on the guarded face. `python:indexable(p)`
           for `if c: return p[0]` is `c -> python:indexable(p)`, never the
           unconditional obligation -- a caller that never takes the branch
           owes nothing. Weakening re-mints the demand, so `demand_cid`
           changes: it IS a different obligation.

        Nested guards compose by repeated application, innermost first, which
        is the same accumulation `Incomplete.guarded` records positionally.
        """
        return replace(
            self.demanded_under(formula), value=self.value.guarded(formula)
        )

    def contribution(self):
        """One row per demand: the SET collapses back to singletons HERE.

        This is the boundary the wire lives behind. `to_value`, the link unit,
        and the Rust linker each state one demand per row, and they are right
        to -- an obligation is owned by ONE formal coordinate. The set is an
        in-flight join carrier, not a wire shape, so it never reaches them.
        """
        return tuple(replace(self, demands=(demand,)) for demand in self.demands)

    def inv_contribution(self):
        return ()

    def mint_contribution(self, name, formals):
        # A resolved candidate mints no independent contract row: its constructed
        # value already flows through the return term. The demand is discharged
        # by the linker, not re-stated as an inv here.
        del name, formals
        return ()

    def post_contribution(self):
        return ()

    def derived_post_contribution(self):
        return ()

    def edge_contribution(self, source_name):
        del source_name
        return ()

    def follow(self):
        return self.value.follow_rest()

    def extend_scope(self, ctx):
        return self.value.extend_scope(ctx)

    def sole_demand(self) -> ParameterContractDemandV1:
        """The one demand a PROJECTED row states, or a named gap.

        Every projection boundary reads this. `contribution` splits the set
        before anything is projected, so a set arriving here means a producer
        reached the wire without going through the block record -- loud, not
        silently first-of-set.
        """
        if len(self.demands) == 1:
            return self.demands[0]
        from sugar_lift_py_tests.gap.info import GapKind
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="ContractConditionalConstructionV1.sole_demand",
            blame=self.source_node,
            observed=(
                f"a projected contract row carries {len(self.demands)} demands "
                f"({', '.join(demand.demand_cid for demand in self.demands)})"
            ),
            requested="exactly one demand per projected row",
            fix=(
                "route the entry through `contribution`, which splits the "
                "in-flight demand SET into one row per demand, before "
                "projecting it to the wire"
            ),
            gap_kind=GapKind.FLOOR,
        )

    def to_value(self) -> dict[str, Any]:
        return {
            "kind": "contract-conditional-construction",
            "schemaVersion": "1",
            "sourceNode": self.source_node.wire(),
            "candidate": _json(term_to_value(self.candidate)),
            "candidateCid": self.candidate_cid,
            "demand": self.sole_demand().to_value(),
        }


@dataclass(frozen=True)
class ValueOccurrenceCoordinateV1:
    source: SourceFragmentCoordinateV1
    occurrence_cid: str

    @classmethod
    def mint(cls, source):
        return cls(source, _cid({"kind": "value-occurrence", "source": source.wire()}))

    def to_value(self):
        return {"source": self.source.wire(), "occurrenceCid": self.occurrence_cid}

    @classmethod
    def from_value(cls, value):
        if not isinstance(value, dict) or set(value) != {"source", "occurrenceCid"}:
            raise ValueError("value occurrence requires an exact key set")
        result = cls(
            SourceFragmentCoordinateV1.decode(value["source"]),
            value["occurrenceCid"],
        )
        if result != cls.mint(result.source):
            raise ValueError("value occurrence CID is stale")
        return result


@dataclass(frozen=True)
class FormalActualBindingV1:
    formal_coordinate_cid: str
    actual_occurrence: ValueOccurrenceCoordinateV1
    actual_term: Term
    actual_contract_ref_cid: str | None = None

    def to_value(self):
        return {
            "formalCoordinateCid": self.formal_coordinate_cid,
            "actualOccurrence": self.actual_occurrence.to_value(),
            "actualTerm": _json(term_to_value(self.actual_term)),
            "actualContractRefCid": self.actual_contract_ref_cid,
        }

    @classmethod
    def from_value(cls, value):
        expected = {
            "formalCoordinateCid",
            "actualOccurrence",
            "actualTerm",
            "actualContractRefCid",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("formal actual binding requires an exact key set")
        return cls(
            value["formalCoordinateCid"],
            ValueOccurrenceCoordinateV1.from_value(value["actualOccurrence"]),
            _term_from_value(value["actualTerm"]),
            value["actualContractRefCid"],
        )


@dataclass(frozen=True)
class CallEdgeV2:
    source_contract_cid: str
    target_contract_cid: str
    call_site: SourceFragmentCoordinateV1
    formal_actual_bindings: tuple[FormalActualBindingV1, ...]
    edge_cid: str

    @classmethod
    def mint(
        cls,
        *,
        source_contract_cid,
        target_contract_cid,
        call_site,
        formal_actual_bindings,
    ):
        bindings = tuple(formal_actual_bindings)
        coordinates = tuple(item.formal_coordinate_cid for item in bindings)
        if len(coordinates) != len(set(coordinates)):
            raise ValueError("CallEdgeV2 has a duplicate formal coordinate")
        preimage = {
            "kind": "call-edge",
            "schemaVersion": "2",
            "sourceContractCid": source_contract_cid,
            "targetContractCid": target_contract_cid,
            "callSite": call_site.wire(),
            "formalActualBindings": [item.to_value() for item in bindings],
        }
        return cls(
            source_contract_cid,
            target_contract_cid,
            call_site,
            bindings,
            _cid(preimage),
        )

    def to_value(self):
        return {
            "kind": "call-edge",
            "schemaVersion": "2",
            "sourceContractCid": self.source_contract_cid,
            "targetContractCid": self.target_contract_cid,
            "callSite": self.call_site.wire(),
            "formalActualBindings": [
                item.to_value() for item in self.formal_actual_bindings
            ],
            "edgeCid": self.edge_cid,
        }

    @classmethod
    def from_value(cls, value):
        expected = {
            "kind",
            "schemaVersion",
            "sourceContractCid",
            "targetContractCid",
            "callSite",
            "formalActualBindings",
            "edgeCid",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("CallEdgeV2 requires an exact key set")
        result = cls.mint(
            source_contract_cid=value["sourceContractCid"],
            target_contract_cid=value["targetContractCid"],
            call_site=SourceFragmentCoordinateV1.decode(value["callSite"]),
            formal_actual_bindings=tuple(
                FormalActualBindingV1.from_value(item)
                for item in value["formalActualBindings"]
            ),
        )
        if (
            value["kind"] != "call-edge"
            or value["schemaVersion"] != "2"
            or result.edge_cid != value["edgeCid"]
        ):
            raise ValueError("CallEdgeV2 CID is stale")
        return result


def _term_from_value(value):
    from sugar_lift_py_tests.ir import (
        bool_const,
        ctor,
        make_var,
        num,
        real_lit,
        str_const,
    )

    if not isinstance(value, dict):
        raise ValueError("actual term must be a ProofIR term")
    if value.get("kind") == "var" and set(value) == {"kind", "name"}:
        return make_var(value["name"])
    if value.get("kind") == "ctor" and set(value) == {"kind", "name", "args"}:
        return ctor(value["name"], [_term_from_value(item) for item in value["args"]])
    if value.get("kind") == "const" and set(value) == {"kind", "value", "sort"}:
        sort = value["sort"].get("name") if isinstance(value["sort"], dict) else None
        if sort == "Int" and type(value["value"]) is int:
            return num(value["value"])
        if sort == "Bool" and type(value["value"]) is bool:
            return bool_const(value["value"])
        if sort == "String" and isinstance(value["value"], str):
            return str_const(value["value"])
        if sort == "Real" and isinstance(value["value"], str):
            return real_lit(value["value"])
    raise ValueError("actual term shape is unsupported")


# --- Phase 1/2/3 continuation schema (mirrors sugar-linker/src/caller_parameter.rs) ---


@dataclass(frozen=True)
class ParameterOwnedContractV1:
    """The callee's structural identity: its formals + the demands it
    STRUCTURALLY OWNS, independent of any post projection. `semantic_decl` is a
    contract declaration whose JCS CID is `contract_cid`; the four ownership
    sub-fields are re-derived byte-for-byte by Rust `ParameterOwnedContractV1::
    validate` against the sibling fields."""

    contract_cid: str
    semantic_decl: Any
    owner_source_identity_cid: str
    owner_definition_locus: SourceFragmentCoordinateV1
    formal_coordinates: tuple
    formal_sorts: tuple
    declared_demand_cids: tuple

    @classmethod
    def mint(
        cls,
        *,
        name: str,
        owner_source_identity_cid: str,
        owner_definition_locus: SourceFragmentCoordinateV1,
        formal_coordinates: tuple,
        declared_demand_cids,
    ) -> "ParameterOwnedContractV1":
        from sugar_lift_py_tests.ir import ContractDecl, contract_decl_to_value

        coords = tuple(formal_coordinates)
        # Rust BTreeSet<Cid>: sorted, de-duplicated.
        declared = tuple(sorted(set(declared_demand_cids)))
        formal_declarations = [
            {"coordinate": coordinate.to_value()} for coordinate in coords
        ]
        decl = ContractDecl(
            name=name,
            owner_source_identity_cid=owner_source_identity_cid,
            owner_definition_locus=owner_definition_locus.wire(),
            formal_declarations=formal_declarations,
            declared_parameter_demand_cids=list(declared),
        )
        semantic_decl = _json(contract_decl_to_value(decl))
        return cls(
            contract_cid=_cid(semantic_decl),
            semantic_decl=semantic_decl,
            owner_source_identity_cid=owner_source_identity_cid,
            owner_definition_locus=owner_definition_locus,
            formal_coordinates=coords,
            formal_sorts=tuple(coordinate.sort for coordinate in coords),
            declared_demand_cids=declared,
        )

    def to_value(self) -> dict[str, Any]:
        return {
            "contractCid": self.contract_cid,
            "semanticDecl": self.semantic_decl,
            "ownerSourceIdentityCid": self.owner_source_identity_cid,
            "ownerDefinitionLocus": self.owner_definition_locus.wire(),
            "formalDeclarations": [
                {"coordinate": coordinate.to_value()}
                for coordinate in self.formal_coordinates
            ],
            "formalSorts": [
                {"kind": "primitive", "name": sort.name} for sort in self.formal_sorts
            ],
            "declaredDemandCids": list(self.declared_demand_cids),
        }


@dataclass(frozen=True)
class ParameterContractLinkUnitV1:
    """One function's closed enrollment row: its owned contract, the candidates
    its body enrolled, the already-constructed call edges, and the retained
    continuation key `link_unit_cid`."""

    source_memento: Any
    parameter_owned_contract: ParameterOwnedContractV1
    candidates: tuple
    call_edges: tuple
    link_unit_cid: str

    @classmethod
    def mint(cls, *, source_memento, parameter_owned_contract, candidates, call_edges):
        cands = tuple(candidates)
        edges = tuple(call_edges)
        preimage = {
            "kind": "parameter-contract-link-unit",
            "schemaVersion": "1",
            "sourceMemento": source_memento,
            "parameterOwnedContract": parameter_owned_contract.to_value(),
            "candidates": [candidate.to_value() for candidate in cands],
            "callEdges": [edge.to_value() for edge in edges],
        }
        return cls(
            source_memento, parameter_owned_contract, cands, edges, _cid(preimage)
        )

    def to_value(self) -> dict[str, Any]:
        return {
            "kind": "parameter-contract-link-unit",
            "schemaVersion": "1",
            "sourceMemento": self.source_memento,
            "parameterOwnedContract": self.parameter_owned_contract.to_value(),
            "candidates": [candidate.to_value() for candidate in self.candidates],
            "callEdges": [edge.to_value() for edge in self.call_edges],
            "linkUnitCid": self.link_unit_cid,
        }


@dataclass(frozen=True)
class ParameterContractResolutionSetV1:
    """The Phase-2 fold's authenticated verdict set, bound to the continuation
    it discharges. `set_cid` mutually binds `link_unit_cid` (the replay guard):
    a resume accepts a set ONLY when both CIDs agree with the retained
    continuation."""

    link_unit_cid: str
    resolutions: tuple
    set_cid: str

    @classmethod
    def mint(cls, *, link_unit_cid: str, resolutions):
        rows = tuple(resolutions)
        preimage = {
            "kind": "parameter-contract-resolution-set",
            "schemaVersion": "1",
            "linkUnitCid": link_unit_cid,
            "resolutions": list(rows),
        }
        return cls(link_unit_cid, rows, _cid(preimage))

    @classmethod
    def from_value(cls, value) -> "ParameterContractResolutionSetV1":
        expected = {"kind", "schemaVersion", "linkUnitCid", "resolutions", "setCid"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("resolution set requires an exact key set")
        result = cls.mint(
            link_unit_cid=value["linkUnitCid"],
            resolutions=tuple(value["resolutions"]),
        )
        if (
            value["kind"] != "parameter-contract-resolution-set"
            or value["schemaVersion"] != "1"
            or result.set_cid != value["setCid"]
        ):
            raise ValueError("resolution set CID is stale")
        return result

    def to_value(self) -> dict[str, Any]:
        return {
            "kind": "parameter-contract-resolution-set",
            "schemaVersion": "1",
            "linkUnitCid": self.link_unit_cid,
            "resolutions": list(self.resolutions),
            "setCid": self.set_cid,
        }


class ResumeStalePanic(Exception):
    """A resume that could not be honored: loud, never a silent reconstruction."""


def _resolution_preimage(resolution: dict) -> dict:
    return {
        "kind": resolution["kind"],
        "schemaVersion": resolution["schemaVersion"],
        "demandCid": resolution["demandCid"],
        "candidateCid": resolution["candidateCid"],
        "contractCid": resolution["contractCid"],
        "basis": resolution["basis"],
        "callerUniverseCid": resolution["callerUniverseCid"],
    }


def _validate_resolution(resolution: dict) -> None:
    expected = {
        "kind",
        "schemaVersion",
        "demandCid",
        "candidateCid",
        "contractCid",
        "basis",
        "callerUniverseCid",
        "resolutionCid",
    }
    if not isinstance(resolution, dict) or set(resolution) != expected:
        raise ResumeStalePanic("resolution requires an exact key set")
    if (
        resolution["kind"] != "parameter-contract-resolution"
        or resolution["schemaVersion"] != "1"
        or _cid(_resolution_preimage(resolution)) != resolution["resolutionCid"]
    ):
        raise ResumeStalePanic("resolution CID is stale")
    basis = resolution["basis"]
    if basis == "declared-demand":
        if resolution["callerUniverseCid"] is not None:
            raise ResumeStalePanic(
                "declared-demand resolution carries a caller universe"
            )
    elif basis == "closed-callers":
        if resolution["callerUniverseCid"] is None:
            raise ResumeStalePanic("closed-callers resolution lacks a caller universe")
    else:
        raise ResumeStalePanic("resolution basis is unknown")


def resume_project(universe, accepted: dict[str, dict]):
    """Mechanically replace each exactly-resolved ContractConditionalConstruction
    V1 entry with its RETAINED .value (same object -> occurrence identity
    unchanged), returning a resumed universe whose record projects post()
    NORMALLY. The candidate's carried value contributes its own post; nothing is
    suppressed to an implicit None. Entries with no accepted resolution are left
    standing, so post() still panics on any unresolved candidate."""
    import dataclasses

    new_statements = tuple(
        (
            entry.value
            if (
                isinstance(entry, ContractConditionalConstructionV1)
                and entry.sole_demand().demand_cid in accepted
            )
            else entry
        )
        for entry in universe.record.statements
    )
    return dataclasses.replace(
        universe,
        record=dataclasses.replace(universe.record, statements=new_statements),
    )


def resume_apply_resolutions(link_unit, resolution_set) -> dict[str, dict]:
    """The Phase-3 resume decision. Given the RETAINED link unit (the immutable
    continuation) and the presented resolution set, honor the resume ONLY when:

      1. Replay guard: the set is bound to THIS continuation --
         resolution_set.link_unit_cid == link_unit.link_unit_cid, and set_cid
         re-derives (both checked mutually by ParameterContractResolutionSetV1.
         from_value + this equality). A foreign/lost continuation is loud.
      2. Exact complete bijection over the link unit's PENDING candidates: every
         enrolled (demand_cid, candidate_cid, contract_cid) has exactly one
         resolution; none missing, duplicated, foreign-contract, or
         wrong-candidate; every resolution CID re-derives.

    Returns {demand_cid: resolution} on success; raises ResumeStalePanic (which
    the caller lifts to a ConstructionPanic) otherwise. Never reconstructs.
    """
    if resolution_set.link_unit_cid != link_unit.link_unit_cid:
        raise ResumeStalePanic(
            "resolution set is bound to a different continuation "
            f"({resolution_set.link_unit_cid} != {link_unit.link_unit_cid})"
        )
    pending = {}
    for candidate in link_unit.candidates:
        key = candidate.sole_demand().demand_cid
        if key in pending:
            raise ResumeStalePanic("duplicate pending demand in link unit")
        pending[key] = candidate
    accepted: dict[str, dict] = {}
    for resolution in resolution_set.resolutions:
        _validate_resolution(resolution)
        demand_cid = resolution["demandCid"]
        candidate = pending.get(demand_cid)
        if candidate is None:
            raise ResumeStalePanic(f"resolution for a foreign demand {demand_cid}")
        if demand_cid in accepted:
            raise ResumeStalePanic(f"duplicate resolution for demand {demand_cid}")
        if resolution["candidateCid"] != candidate.candidate_cid:
            raise ResumeStalePanic("resolution names the wrong candidate")
        if resolution["contractCid"] != link_unit.parameter_owned_contract.contract_cid:
            raise ResumeStalePanic("resolution names a foreign contract")
        accepted[demand_cid] = resolution
    missing = set(pending) - set(accepted)
    if missing:
        raise ResumeStalePanic(
            f"resolution set is incomplete: missing {sorted(missing)}"
        )
    return accepted

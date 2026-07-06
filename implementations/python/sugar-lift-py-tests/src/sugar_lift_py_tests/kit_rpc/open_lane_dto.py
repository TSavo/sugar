"""TypedDict membranes for lift-report lanes that are genuinely open.

These lanes (call_edges, vendor_conjoins, diagnostics, source_audits,
factory_audits) have no closed recognizer hierarchy backing them yet: their
producers emit shapes that vary by branch (CallEdgeDecl.to_declaration(),
package accounting summaries, FactoryAuditRow.to_json(), ad hoc diagnostic
dicts). Per the enforcement-ladder ceiling test (issue #3657/#3661) an open
lane still gets a NAMED TypedDict membrane instead of an accidental
`dict[str, Any]` -- the boundary is declared, even where individual field
values remain `Any` because the producer's own shape is not yet a closed
sort. When a producer's shape closes (a fixed enum of statuses, a finite
dispatch matrix), narrow the corresponding TypedDict's field types then --
do not widen it back to `dict[str, Any]`.
"""

from __future__ import annotations

from typing import Any, TypedDict


class CallEdgeDto(TypedDict, total=False):
    """Mirrors CallEdgeDecl.to_declaration() (proofir/nodes/call_edge_decl.py).

    `callsite` is polymorphic (bare str OR a nested locus dict) in the
    producer itself, so it stays `Any` here rather than pretending to a
    sort the producer does not carry yet.
    """

    kind: str
    schemaVersion: str
    sourceContract: str
    targetSymbol: str
    targetContract: str | None
    targetContractCid: str | None
    targetProofCid: str
    callSiteLocus: dict[str, Any]
    callsite: Any


class VendorConjoinDto(TypedDict, total=False):
    """No producer populates this lane yet (dead-but-declared RPC slot).

    Kept as an explicit, empty-shaped membrane so a future producer is
    forced to extend a named type instead of reaching for a bare dict.
    """

    kind: str


class DiagnosticDto(TypedDict, total=False):
    """Ad hoc diagnostic rows (dig refusals, agreement violations, proofir
    provenance notes). Each producer stamps its own `kind`; the payload
    fields vary by kind, so `Any` is the honest membrane for now.
    """

    kind: str


class SourceAuditDto(TypedDict, total=False):
    """Two distinct producers stamp this lane: package_source_audits_for_source()
    (factory/package_source_accounting.py, `kind: "source-audit"`, structural
    package accounting) and AuditMemento.to_declaration()
    (proofir/nodes/audit_memento.py, no `kind`, per-assertion source-locus
    counts). Their `contract` field alone differs in shape (a dict in one, a
    plain contract-name str in the other), which is why it stays `Any` here:
    the membrane is honest about carrying two producers' shapes rather than
    forcing a false merge.
    """

    kind: str
    language: str
    contract: Any
    role: str
    universe_kind: str
    accounting_mode: str
    package: str
    package_root: str
    file: str
    sourceFunctionName: str
    totals: dict[str, int]
    ast_type_counts: dict[str, Any]
    package_file_count: int
    loci: list[dict[str, Any]]
    sample_loci: list[dict[str, Any]]
    loci_elided: bool


class FactoryAuditDto(TypedDict, total=False):
    """Mirrors FactoryAuditRow.to_json() (factory/factory_audit_row.py)."""

    kind: str
    role: str
    status: str
    observed: str
    blame: str
    selected: str | None
    candidates: list[str]
    message: str

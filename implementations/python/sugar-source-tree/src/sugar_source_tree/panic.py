"""SourceTreePanic: the loud arm of the tree's two-arm match.

Every question the tree answers has exactly two outcomes: a resolved,
Typed answer, or a panic. There is no third arm — no permissive fallback,
no default case, no quiet ``False``, no bare ``None`` gap.

Two panics were one before, and the merge was itself a bug: an ``owner``
string a caller had to read and interpret to tell apart two entirely
different failures. Now they are two classes, so no caller can conflate
them by reaching for a string:

``VocabularyMissing``
    OUR vocabulary is incomplete. The backend handed up a shape it
    legitimately produces (a node kind, an operator, an import target
    shape, a slot value) and we have no node class, adapter rule, or
    frozen-vocabulary entry for it yet. The fix always adds vocabulary:
    a class, a rule, a mapping entry — never a fallback.

``BackendDefect``
    The backend (or its adapter's translation of it) produced something
    structurally invalid: a position outside the source, a degenerate
    span, a coordinate collision, a root of the wrong shape, output that
    is not even valid Python. The fix is never "add vocabulary" — it is
    "the backend or the adapter is buggy; fix or uninstall it."

Both are ``SourceTreePanic`` (this is the common base — kept so that a
caller that genuinely needs to treat every panic the same way,
such as the corpus's "record and keep going" loop in ``corpus.py``, has one
name for "any panic happened." Catching the base is NEVER the
easy default for anything that needs to react differently to the two —
there is no code path in this package that catches ``SourceTreePanic``
and then re-derives which of the two arms it was by reading ``owner``;
if a caller needs that distinction it must catch the concrete subclass).

Modeled on ``construction_panic_gap`` (sugar_lift_py_tests.gap.panic),
but standalone: this package deliberately imports nothing from the existing
tree (#5940 builds the tree in isolation).
"""

from __future__ import annotations

from enum import Enum


def _render_blame(blame: object) -> str:
    """Project a native coordinate to actionable prose only at the panic edge."""
    filename = getattr(blame, "filename", None)
    line = getattr(blame, "line", None)
    col = getattr(blame, "col", None)
    if filename is not None and line is not None and col is not None:
        return f"{filename}:{line}:{col}"
    return str(blame)


class SourceTreePanic(Exception):
    """Common base. Every refusal carries the native coordinate it blames."""

    def __init__(
        self,
        *,
        blame: object,
        owner: str,
        observed: str,
        requested: str,
        fix: str,
    ) -> None:
        if blame is None:
            raise TypeError(
                "blame must be a real source or backend coordinate, not None"
            )
        super().__init__(blame, owner, observed, requested, fix)
        self.blame = blame
        self.owner = owner
        self.observed = observed
        self.requested = requested
        self.fix = fix

    _LABEL = "SOURCE TREE PANIC"

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return (
            f"{self._LABEL} [{self.owner}]\n"
            f"  blame:     {_render_blame(self.blame)}\n"
            f"  observed:  {self.observed}\n"
            f"  requested: {self.requested}\n"
            f"  fix:       {self.fix}"
        )


class VocabularyMissing(SourceTreePanic):
    """OUR vocabulary has no class/rule for a shape the backend legitimately
    produced. The fix is always to add vocabulary — a class, a rule, a
    mapping entry — deliberately, never a permissive fallback."""

    _LABEL = "VOCABULARY MISSING"


class SugarNotWritten(SourceTreePanic):
    """The node knows exactly what it is — and nobody has written its sugar
    yet. Raised by the abstract ``Node.sugar()``; every concrete class either
    OVERRIDES ``sugar()`` and constructs, or inherits this throw. Two arms
    enforced by inheritance itself: no registry to consult, no lookup that
    can miss quietly, no third state. Writing the override IS writing the
    sugar, so coverage is visible in the hierarchy, not in a census table.

    Distinct from ``VocabularyMissing`` (there the NODE class is absent;
    here the node class exists and speaks) and from ``BackendDefect``
    (the backend did nothing wrong). The fix is always: write the sugar,
    deliberately.
    """

    _LABEL = "SUGAR NOT WRITTEN"


class UnattributableRefusal(SugarNotWritten):
    """A construction refusal that this attribution boundary cannot classify.

    Unlike an ordinary ``SugarNotWritten``, consuming this refusal as a
    completed attribution would hide a prerequisite owned by an outer layer.
    Callers discriminate on this type, never on the mutable diagnostic owner.
    """

    _LABEL = "UNATTRIBUTABLE REFUSAL"


class OpaqueSourceCallResolutionGap(SugarNotWritten):
    """A reached source-call obligation whose target stayed unresolved."""

    _LABEL = "OPAQUE SOURCE CALL RESOLUTION GAP"


class RuntimeSelectedContextManager(SugarNotWritten):
    """A `with` whose manager has no authenticated exit-suppression contract.

    Resource managers (`open(...)`, `tm.ensure_clean(...)`, …) are not
    enrolled as ``NeverSuppresses`` / ``Expects`` / ``Suppresses``: the lift
    never reads ``__enter__`` / ``__exit__``, so suppression is
    ``RuntimeSelected`` and must stay LOUD. This residual is deliberately a
    *named* subclass of ``SugarNotWritten`` so the frontier census can count
    unauthenticated context managers separately from shapes that simply have
    no ``.sugar()`` override yet.

    Never a normal-path-only ``__enter__``/``__exit__(None,None,None)``
    rewrite — that drops the exceptional edge and is a different language
    (issue #5994 step 4).
    """

    _LABEL = "RUNTIME-SELECTED CONTEXT MANAGER"


class ConstructedValueTestimonyNotWritten(SugarNotWritten):
    """A construction succeeded but its constructed-value testimony could not
    be content-addressed.

    The coordinate registered, the node constructed, and the testimony
    serialization failed. Before, both failure doors in
    ``ConstructionTestimonyReporterV1.present_construction`` returned silently:
    the node kept its PRESENT discharge and the failure disappeared -- a falsely
    green construction coordinate. There is no such third arm now. Either the
    constructed value canonicalizes (present testimony) or this typed gap is
    reported through the same roll call and raised.

    A *named* subclass of ``SugarNotWritten`` (like
    ``RuntimeSelectedContextManager``) so the census counts testimony gaps
    separately from shapes with no ``.sugar()`` override. The fix is always to
    teach canonicalization the general value CATEGORY -- never a per-type
    allowlist, never a silent return.
    """

    _LABEL = "CONSTRUCTED VALUE TESTIMONY NOT WRITTEN"


class WithConstructionGapKind(str, Enum):
    RUNTIME_SELECTED = "runtime-selected"
    UNRESOLVED_SYMBOL = "unresolved-symbol"
    AMBIGUOUS_SYMBOL = "ambiguous-symbol"
    WRONG_CONTRACT_KIND = "wrong-contract-kind"
    SIGNATURE_MISMATCH = "signature-mismatch"
    UNAUTHENTICATED_MEMBER = "unauthenticated-member"
    PAYLOAD_CID_MISMATCH = "payload-cid-mismatch"
    UNSUPPORTED_CM_SCHEMA = "unsupported-cm-schema"
    NO_DERIVED_CONTRACT = "no-derived-contract"
    STALE_DERIVED_CONTRACT = "stale-derived-contract"
    UNSUPPORTED_CONTEXT_MANAGER_SEMANTICS = "unsupported-context-manager-semantics"
    UNSUPPORTED_WITH_BINDING_TARGET = "unsupported-with-binding-target"
    ASYNC_CONTEXT_MANAGER_UNSUPPORTED = "async-context-manager-unsupported"
    # Export-resolution kinds that ride the same preconstruction table into With.
    # A missing member here crashed the pandas control-effect census for 780/1415
    # files with ``ValueError: 'dynamic-export' is not a valid WithConstructionGapKind``
    # — instrument defect, not residual silence.
    DYNAMIC_EXPORT = "dynamic-export"
    STATIC_EXPORT_ABSENT = "static-export-absent"
    UNSUPPORTED_STATEMENT = "unsupported-statement"
    MALFORMED_IMPORT_BINDING = "malformed-import-binding"
    ARTIFACT_MODULE_ABSENT = "artifact-module-absent"
    TARGET_OUTSIDE_BINDING = "target-outside-binding"
    AMBIGUOUS_STATIC_EXPORT = "ambiguous-static-export"
    OPAQUE_SOURCE = "opaque-source"
    REEXPORT_CYCLE = "reexport-cycle"
    # Source-derived preconstruction kinds.  Each is minted by a typed Literal
    # (`ManagerConstructionGapV1`, `ManagerProtocolConstructionGapV1`,
    # `DerivedManagerSummaryGapV1`), so this is a closed structural vocabulary,
    # not a name table -- the derivation layer used to fuse `kind:detail` into
    # one string and hand the wire decoder a kind it would have REFUSED.
    INCOMPLETE_CALL_ACTUALS = "incomplete-call-actuals"
    ARTIFACT_MISMATCH = "artifact-mismatch"
    DEFINITION_MISSING = "definition-missing"
    NON_MANAGER_RESULT = "non-manager-result"
    CALL_BINDING = "call-binding"
    FORCE_FLOOR = "force-floor"
    # The four conditions that `opaque-call-target` fused into one name; see
    # `manager_construction.py` for what decides each.
    CALL_GRAPH_CYCLE = "call-graph-cycle"
    VALUE_CALL_TARGET = "value-call-target"
    CALL_TARGET_SOURCE_ABSENT = "call-target-source-absent"
    CALL_TARGET_EXPORT_UNRESOLVED = "call-target-export-unresolved"
    # Authenticated stdlib / off-pin: cite, never MaterializeModule (membrane).
    CALL_TARGET_OFF_POPULATION = "call-target-off-population"
    ENTER_MISSING = "enter-missing"
    EXIT_MISSING = "exit-missing"
    METHOD_CONSTRUCTION = "method-construction"
    GENERATOR_MISSING = "generator-missing"
    GENERATOR_PROTOCOL = "generator-protocol"
    ENTER_MAY_HALT = "enter-may-halt"
    EXIT_MAY_HALT = "exit-may-halt"
    OPAQUE_EXIT_TRUTHINESS = "opaque-exit-truthiness"
    # Catch-all: never crash the census on a newly minted resolution kind.
    # The original string is preserved on ``ContextManagerResolutionConstructionGap.resolution_kind``.
    UNRECOGNIZED_RESOLUTION_KIND = "unrecognized-resolution-kind"

    @classmethod
    def parse(cls, kind: str) -> "WithConstructionGapKind":
        try:
            return cls(kind)
        except ValueError:
            return cls.UNRECOGNIZED_RESOLUTION_KIND


class WithConstructionGap(SugarNotWritten):
    def __init__(
        self,
        *,
        gap_kind: WithConstructionGapKind,
        demand_cid: str | None = None,
        candidate_member_cids: tuple[str, ...] = (),
        member_cid: str | None = None,
        coordinate: object | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.gap_kind = gap_kind
        self.kind = gap_kind.value
        self.demand_cid = demand_cid
        self.candidate_member_cids = candidate_member_cids
        self.member_cid = member_cid
        self.coordinate = coordinate


class ContextManagerResolutionConstructionGap(WithConstructionGap):
    """A prereq-2 typed resolution gap consumed unchanged by ``With``."""

    _LABEL = "CONTEXT MANAGER RESOLUTION GAP"

    def __init__(
        self,
        *,
        kind: str,
        demand_cid: str,
        candidate_member_cids: tuple[str, ...],
        **kwargs,
    ) -> None:
        gap_kind = WithConstructionGapKind.parse(kind)
        # Preserve the wire kind even when it falls into UNRECOGNIZED_*.
        self.resolution_kind = kind
        super().__init__(
            gap_kind=gap_kind,
            demand_cid=demand_cid,
            candidate_member_cids=candidate_member_cids,
            **kwargs,
        )
        # ``self.kind`` is what census buckets on. Prefer the original resolution
        # kind so ``dynamic-export`` stays ``dynamic-export``, not collapsed.
        if gap_kind is WithConstructionGapKind.UNRECOGNIZED_RESOLUTION_KIND:
            self.kind = kind
        else:
            self.kind = gap_kind.value


class UnsupportedContextManagerSemantics(WithConstructionGap):
    _LABEL = "UNSUPPORTED CONTEXT MANAGER SEMANTICS"

    def __init__(self, **kwargs) -> None:
        super().__init__(
            gap_kind=WithConstructionGapKind.UNSUPPORTED_CONTEXT_MANAGER_SEMANTICS,
            **kwargs,
        )


class UnsupportedWithBindingTarget(WithConstructionGap):
    _LABEL = "UNSUPPORTED WITH BINDING TARGET"

    def __init__(self, **kwargs) -> None:
        super().__init__(
            gap_kind=WithConstructionGapKind.UNSUPPORTED_WITH_BINDING_TARGET,
            **kwargs,
        )


class AsyncContextManagerUnsupported(WithConstructionGap):
    _LABEL = "ASYNC CONTEXT MANAGER UNSUPPORTED"

    def __init__(self, **kwargs) -> None:
        super().__init__(
            gap_kind=WithConstructionGapKind.ASYNC_CONTEXT_MANAGER_UNSUPPORTED,
            **kwargs,
        )


class SubstituteNotWritten(SourceTreePanic):
    """Nobody has written this node's substitution yet. Raised by the abstract
    ``Node.substitute()``; every concrete class either OVERRIDES it (a leaf
    returns itself, a compound recurses into its children, a scope-owner masks
    its bound names before recursing, a ``Name`` binds) or inherits this throw.

    There is deliberately NO permissive "recurse by default": a silent default
    would let a newly-added scope-owning node CAPTURE -- substitute an outer
    name into a body that rebinds it -- and never say so. So substitution is
    written per node, coverage visible in the hierarchy, and the one hazard
    (a binder that has not been taught to mask) cannot slip in quietly: an
    unwritten node is loud here, not a silent wrong answer.
    """

    _LABEL = "SUBSTITUTE NOT WRITTEN"


class BackendDefect(SourceTreePanic):
    """The backend, or its adapter's translation of it, produced something
    structurally invalid: an out-of-range position, a degenerate span, a
    coordinate collision, a malformed root, output that is not even valid
    for the language it claims to parse. The fix is on the backend/adapter
    side, never "add vocabulary".
    """

    _LABEL = "BACKEND DEFECT"


def vocabulary_missing(
    *, blame: object, owner: str, observed: str, requested: str, fix: str
) -> "VocabularyMissing":
    raise VocabularyMissing(
        blame=blame,
        owner=owner,
        observed=observed,
        requested=requested,
        fix=fix,
    )


def backend_defect(
    *, blame: object, owner: str, observed: str, requested: str, fix: str
) -> "BackendDefect":
    raise BackendDefect(
        blame=blame,
        owner=owner,
        observed=observed,
        requested=requested,
        fix=fix,
    )

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


# Taxonomy deleted. Construct or panic.


class ContextManagerResolutionConstructionGap(SugarNotWritten):
    """With cannot construct: no authenticated CM contract for this use-site.

    One named door for the require path — not a residual-kind vocabulary.
    When the preconstruction table carries a gap row, ``kind`` / ``target_symbol``
    are the row's detail strings (opaque evidence), never a closed enum the
    board invents kinds from. When the table has no row, those fields are None
    and ``observed`` names the missing coordinate.

    Construct when a ``ContextManagerContractRefV1`` (or source-derived peer)
    is present; otherwise this panic — never SoftUnresolvedWithSugar.
    """

    _LABEL = "CONTEXT MANAGER RESOLUTION GAP"

    def __init__(
        self,
        *,
        use_site: object | None = None,
        target_symbol: str | None = None,
        resolution_kind: str | None = None,
        demand_cid: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.use_site = use_site
        self.target_symbol = target_symbol
        self.demand_cid = demand_cid
        # Optional detail from the resolution row (e.g. "runtime-selected").
        # Not a closed WithConstructionGapKind vocabulary — deleted.
        self.kind = resolution_kind


class UnsupportedContextManagerSemantics(SugarNotWritten):
    """Manager semantics not constructible — write the arm or stay loud."""

    _LABEL = "UNSUPPORTED CONTEXT MANAGER SEMANTICS"


class UnsupportedWithBindingTarget(SugarNotWritten):
    """With-as binding target not constructible — write the arm or stay loud."""

    _LABEL = "UNSUPPORTED WITH BINDING TARGET"


class AsyncContextManagerUnsupported(SugarNotWritten):
    """Async with not constructible yet — write the arm or stay loud."""

    _LABEL = "ASYNC CONTEXT MANAGER UNSUPPORTED"


class SubstituteNotWritten(SourceTreePanic):
    """Nobody has written this node's substitution yet."""

    _LABEL = "SUBSTITUTE NOT WRITTEN"


class BackendDefect(SourceTreePanic):
    """Backend or adapter produced something structurally invalid."""

    _LABEL = "BACKEND DEFECT"


def vocabulary_missing(
    *, blame: object, owner: str, observed: str, requested: str, fix: str
) -> "VocabularyMissing":
    raise VocabularyMissing(
        blame=blame, owner=owner, observed=observed, requested=requested, fix=fix,
    )


def backend_defect(
    *, blame: object, owner: str, observed: str, requested: str, fix: str
) -> "BackendDefect":
    raise BackendDefect(
        blame=blame, owner=owner, observed=observed, requested=requested, fix=fix,
    )

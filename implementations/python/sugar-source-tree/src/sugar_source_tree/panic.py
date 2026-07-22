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


class SourceTreePanic(Exception):
    """Common base. Never raised directly — always one of the two below."""

    def __init__(self, owner: str, observed: str, requested: str, fix: str) -> None:
        super().__init__(owner, observed, requested, fix)
        self.owner = owner
        self.observed = observed
        self.requested = requested
        self.fix = fix

    _LABEL = "SOURCE TREE PANIC"

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return (
            f"{self._LABEL} [{self.owner}]\n"
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


def vocabulary_missing(owner: str, observed: str, requested: str, fix: str) -> "VocabularyMissing":
    raise VocabularyMissing(owner=owner, observed=observed, requested=requested, fix=fix)


def backend_defect(
    owner: str, observed: str, requested: str, fix: str
) -> "BackendDefect":
    raise BackendDefect(owner=owner, observed=observed, requested=requested, fix=fix)

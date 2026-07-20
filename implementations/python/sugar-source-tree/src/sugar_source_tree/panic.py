"""SourceTreePanic: the loud arm of the tree's two-arm match.

Every question the tree answers has exactly two outcomes: a resolved,
Typed answer, or a panic. There is no third arm — no permissive fallback,
no default case, no quiet ``False``, no bare ``None`` refusal.

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

Modeled on ``factory_panic_gap`` (sugar_lift_py_tests.factory.factory_gap),
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

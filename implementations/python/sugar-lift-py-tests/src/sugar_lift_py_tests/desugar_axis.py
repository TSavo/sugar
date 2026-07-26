"""The desugar-layer census axis: four disjoint quantities, one membrane.

The census measures two axes that are NEVER summed into one R:

    R_construction   tree construction totality      (door: ``fn.sugar()``)
    R_desugar        typed semantic refusals/effects (door: ``sugar.desugar(None)``)

Behind the desugar door three different things can happen, and folding any of
them into ``R_desugar`` produces a number whose denominator is a lie:

``R_desugar``                 typed refusals (``SugarNotWritten``) and typed red
                              effects (``Incomplete`` / ``Halted``).
``desugarConstructionPanics`` a construction-law None arm fired *during*
                              desugar. ``ConstructionPanic`` is a
                              ``BaseException``: neither ``except
                              SugarNotWritten`` nor ``except Exception`` sees
                              it, so without an explicit arm here it escapes
                              the per-function loop and can abort a whole
                              census run with no row at all. Caught BY NAME —
                              never ``except BaseException``.
``desugarDefects``            ordinary exceptions (implementation bugs), plus
                              named audit defects raised by the instrument
                              itself (unsupported outcome envelope, outcome
                              cycle, effect with no occurrence coordinate).
``desugarDesignedGaps``       a DECLARED mechanism refusing on purpose, as its
                              correct answer, in something that is not a
                              ``SugarNotWritten`` — AND classifying as not
                              remaining work. Counted under its own owner,
                              never red, never summed into the three above.

The first two new collections make the final instrument exit RED. None of the
three is ever added to ``R_desugar``.

WHY THE FOURTH EXISTS. ``ExitSetFactoringGap`` is a ``ValueError``, so it landed
in ``desugarDefects`` — twelve rows of the pandas board, every one classifying
``isRemainingWork: False``, which is ``factor_completed`` doing exactly its job.
Counting correct output as a defect is the same disease that made ``R_desugar``
overstate its board by 7.6x, at smaller scale.

THE DOOR TAKES TWO CONDITIONS, and neither alone is enough. Type identity says
which MECHANISM spoke — see ``_designed_gap_types`` for why it is an exact
declared type and not ``isinstance``, and never "a ValueError from this call".
The carried classification says whether THIS OCCURRENCE was that mechanism
working — see ``_is_designed_gap``. Gating on type alone would file a producer
that owns a split and never testified as a finished result, in a bucket that is
never red. That is the same disease pointed the other way, and the worse
direction: a wrong defect count is loud, a wrong designed-gap count is not.

Row identity is the *effect occurrence*, not the enclosing function line. A
function holding three distinct stores is three rows; the same occurrence
reached twice through a shared outcome DAG is one row. An effect that carries
no authenticated occurrence coordinate does not get a fabricated key: it is
reported as an instrument gap in ``desugarDefects``.

The outcome graph is walked with an explicit worklist and a visited set. There
is NO depth cap: a depth cap makes a deep-but-valid body look cleaner than it
is, which is exactly the silent skip this axis exists to eliminate.
"""

from __future__ import annotations

# Not the board. This module measures its own named denominator; the sole
# authoritative Python corpus scoreboard is scripts/control_effect_recensus.py.
# See tests/test_one_authoritative_scoreboard.py.
SCOREBOARD_AUTHORITY = False

import dataclasses
from collections import Counter
from enum import Enum
from typing import Any

# --------------------------------------------------------------------------
# occurrence coordinates
# --------------------------------------------------------------------------


def effect_owner(effect: object) -> str:
    """The family key of a typed red effect: its named type."""
    return type(effect).__name__


def effect_occurrence(effect: object) -> str | None:
    """The authenticated occurrence coordinate of one typed effect.

    Each arm reads a field the effect ITSELF carries about where it occurred:

    * ``RuntimeEffect``      -- ``witness.site`` (the one SourceFragment
                                currency: filename/line/col).
    * ``RaiseEffect`` /
      ``GroupedRaiseEffect`` -- ``occurrence_id`` (the raise site, distinct
                                from the exception type name).
    * ``LoopControlEffect``  -- ``occurrence_cid`` (a CID, not a name).
    * ``CoverageGapEffect``  -- ``boundary``.
    * ``ExpectationNotMetEffect`` / ``WarningEffect`` -- their own ``site`` /
      ``blame``.

    ``None`` means the effect states no occurrence. The caller reports that as
    an instrument gap; it must NOT fall back to the enclosing function's line,
    which would silently collapse distinct effects into one row.
    """
    witness = getattr(effect, "witness", None)
    fragment = _fragment_coordinate(getattr(witness, "site", None))
    if fragment is not None:
        return f"site:{fragment}"

    occurrence = getattr(effect, "occurrence_id", None)
    if isinstance(occurrence, str) and occurrence:
        return f"occurrence:{occurrence}"

    occurrence_cid = getattr(effect, "occurrence_cid", None)
    if isinstance(occurrence_cid, str) and occurrence_cid:
        return f"occurrence-cid:{occurrence_cid}"

    site = _fragment_coordinate(getattr(effect, "site", None))
    if site is not None:
        return f"site:{site}"

    boundary = getattr(effect, "boundary", None)
    if isinstance(boundary, str) and boundary:
        return f"boundary:{boundary}"

    blame = getattr(effect, "blame", None)
    if isinstance(blame, str) and blame:
        # A locus the effect carries about ITSELF (file:line:col prose minted
        # from the owning fragment). Tagged so a row never claims fragment
        # authority it does not have.
        return f"blame:{blame}"

    return None


def _fragment_coordinate(site: object) -> str | None:
    """``filename:line:col`` from anything answering the fragment contract."""
    filename = getattr(site, "filename", None)
    line = getattr(site, "line", None)
    col = getattr(site, "col", None)
    if isinstance(filename, str) and isinstance(line, int) and isinstance(col, int):
        return f"{filename}:{line}:{col}"
    return None


# --------------------------------------------------------------------------
# outcome traversal
# --------------------------------------------------------------------------


# The walk's domain is the outcome/value graph the desugar door returns: the
# lift's own outcome envelopes and floor values, plus plain containers.
#
# It is NOT the whole object world. Measured on a 20-file slice, an unrestricted
# dataclass walk left the outcome graph entirely through provenance fields and
# reached tree infrastructure — SourceUnit, _Handle, ShadowNode, LineTable,
# SymbolTable, CollectingReporter, ConstructionCache (and SourceUnit's genuine
# parent/child cycle). Those are foreign currencies: an outcome cannot live
# inside them, and walking them would drown real audit defects in noise.
#
# Two subdomains inside the lift are leaves by nature: ``ir`` (the proof-term /
# formula language — terms hold no outcomes) and ``effect`` (an effect is
# RECORDED at its Incomplete/Halted position; its interior is testimony, and
# descending would recount a construction-total RaiseValue's effect as red).
_SCALAR_TERMINALS = (str, bytes, bytearray, int, float, complex, bool, type, Enum)
_WALK_DOMAIN = "sugar_lift_py_tests."
_LEAF_SUBDOMAINS = ("sugar_lift_py_tests.ir", "sugar_lift_py_tests.effect")


def _is_walkable_domain(obj: object) -> bool:
    module = type(obj).__module__ or ""
    return module.startswith(_WALK_DOMAIN) and not module.startswith(_LEAF_SUBDOMAINS)


def _is_terminal(obj: object) -> bool:
    if obj is None or isinstance(obj, _SCALAR_TERMINALS):
        return True
    if isinstance(obj, (tuple, list, set, frozenset, dict)):
        return False
    return not _is_walkable_domain(obj)


def _children(obj: object) -> list[object] | None:
    """Structural children, or ``None`` when the shape is not walkable."""
    if isinstance(obj, (tuple, list, set, frozenset)):
        return list(obj)
    if isinstance(obj, dict):
        return [*obj.keys(), *obj.values()]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return [getattr(obj, f.name) for f in dataclasses.fields(obj)]
    return None


class OutcomeWalk:
    """One traversal of an outcome DAG: typed red effects + audit defects.

    Worklist + visited identity set, so a shared sub-outcome reached twice is
    walked once and a cycle terminates. No depth cap. Every shape the walk
    cannot descend and cannot justify as a leaf is recorded as a named audit
    defect.
    """

    def __init__(self) -> None:
        self.effects: list[object] = []
        self.defects: list[str] = []

    def walk(self, outcome: object) -> "OutcomeWalk":
        # The two effect-bearing outcome positions. Every other envelope
        # (Complete, Completed, ExitSet, and every floor value) is walked
        # structurally as a dataclass, so a new envelope class cannot silently
        # hide an effect from the census.
        from sugar_lift_py_tests.outcome import Halted, Incomplete

        visited: set[int] = set()
        on_path: set[int] = set()
        # (object, entering) — the exit marker pops the DFS path so a genuine
        # back edge is distinguishable from lawful DAG sharing.
        work: list[tuple[object, bool]] = [(outcome, True)]
        while work:
            obj, entering = work.pop()
            if not entering:
                on_path.discard(id(obj))
                continue
            if id(obj) in on_path:
                self.defects.append(f"outcome-cycle:{type(obj).__name__}")
                continue
            if id(obj) in visited:
                continue
            visited.add(id(obj))

            if isinstance(obj, (Incomplete, Halted)):
                self.effects.append(obj.effect)
                continue
            if _is_terminal(obj):
                continue
            children = _children(obj)
            if children is None:
                self.defects.append(
                    f"unsupported-outcome-envelope:{type(obj).__name__}"
                )
                continue
            on_path.add(id(obj))
            work.append((obj, False))
            work.extend((child, True) for child in reversed(children))
        return self


# --------------------------------------------------------------------------
# the audit membrane
# --------------------------------------------------------------------------


def _designed_gap_types() -> tuple[type, ...]:
    """THE DECLARED SET of designed gaps, by type, stated here and nowhere else.

    A designed gap is a refusal a mechanism raises ON PURPOSE, as its correct
    answer, which happens not to be a ``SugarNotWritten``. ``ExitSetFactoringGap``
    is one: ``factor_completed`` refuses arms it cannot prove exclusive because
    collapsing them would drop a reachable outcome, and its own module says so —
    "the honest answer is a named gap". Twelve of the pandas board's defect rows
    were that refusal working, every one classifying ``isRemainingWork: False``.

    MEMBERSHIP IS BY DECLARED TYPE, never by "a ValueError out of this call".
    That distinction is the whole reason this door exists rather than a wider
    catch: ``ExitSetFactoringGap`` IS a ``ValueError``, so anything shaped like
    "the exception class of the thing I expected" would swallow every genuine
    ``ValueError`` bug raised anywhere under desugar — which is precisely the
    failure this is built to prevent. Exact type identity, not ``isinstance``:
    a subclass is a different mechanism and must earn its own line here.
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSetFactoringGap

    return (ExitSetFactoringGap,)


def _is_designed_gap(exc: BaseException) -> bool:
    """Whether THIS occurrence is correct output. Type is necessary, not sufficient.

    A DECLARED TYPE ONLY SAYS WHICH MECHANISM SPOKE. It does not say that this
    occurrence was the mechanism working. ``ExitSetFactoringGap`` has two
    populations and its own classifier is what tells them apart:

    * ``isRemainingWork: False`` — the gate doing its job. Correct output.
    * ``isRemainingWork: True``  — ``UNSTAMPED`` and not merged: a producer that
      owns a split and has not testified. That is CLOSABLE WORK, and it is the
      shape #6375 actually closed at ``selectn.py:224``.

    Gating on type alone would file the second kind as correct output in a
    bucket that is never red and never summed — publishing a closable
    producer-omission as a finished result and silencing it. That is a red
    residual ratified as a baseline. It is the same disease this door cures,
    pointed the other way, and it is the WORSE direction: counting correct
    output as a defect is loud and self-correcting, counting work as correct
    output is neither.

    It is latent only because all twelve occurrences on tonight's board classify
    ``False``. That is a fact about one measurement, not a property of the type.

    NO VERDICT IS NOT A VERDICT OF "DESIGNED". ``classification()`` answers
    ``None`` when the refusal carries no arms, and an unclassifiable occurrence
    stays a defect and stays red rather than defaulting into the quiet bucket.
    """
    if type(exc) not in _designed_gap_types():
        return False
    verdict = _carried_verdict(exc)
    if verdict is None:
        return False
    return getattr(verdict, "is_remaining_work", True) is False


def _carried_verdict(exc: BaseException):
    """The verdict the exception itself carries, or ``None``. Never re-derived.

    #6364 mints the classification as data ON the exception, off the arms it
    already holds. Re-deriving it here would be a second classifier that can
    disagree with the first, so this only READS.
    """
    classify = getattr(exc, "classification", None)
    if not callable(classify):
        return None
    return classify()


class DesugarAxis:
    """Accumulates the four disjoint desugar-layer quantities for a file/run."""

    def __init__(self) -> None:
        self.families: Counter[str] = Counter()
        # The disjoint split of R_desugar, read off the occurrence-key prefix.
        self.categories: Counter[str] = Counter()
        self.by_category_owner: Counter[str] = Counter()
        self.construction_panics: list[dict[str, Any]] = []
        self.defects: list[dict[str, Any]] = []
        # Designed gaps: correct output from a named mechanism, COUNTED in its
        # own bucket. Never folded into defects (they are not bugs), never into
        # R_desugar (they are not typed refusals), and never dropped — a
        # designed refusal is reported correct output, not silence.
        self.designed_gaps: list[dict[str, Any]] = []
        # Row identity: (owner, authenticated effect-occurrence coordinate).
        self._seen: set[tuple[str, str]] = set()

    # -- rows ---------------------------------------------------------------

    def _tally(self, owner: str, occurrence: str) -> None:
        key = (owner, occurrence)
        if key in self._seen:
            return
        self._seen.add(key)
        self.families[owner] += 1
        # R_desugar is a MIXED number and must never be published raw. The
        # occurrence key already says which kind of row this is: a
        # ``desugar-call:`` key is a typed refusal (the reduction stopped and
        # owes work), anything else is an authenticated effect occurrence --
        # the correct OUTPUT of a reduction that succeeded. Publishing the sum
        # as "work remaining" overstated the earlier board by 7.6x, because
        # 7483 of 8624 rows were accounted semantics.
        category = (
            "typed-refusal"
            if occurrence.startswith("desugar-call:")
            else "constructed-effect"
        )
        self.categories[category] += 1
        self.by_category_owner[f"{category}/{owner}"] += 1

    def _defect(
        self, kind: str, where: str, detail: str, *, exc: object | None = None
    ) -> None:
        row: dict[str, Any] = {"kind": kind, "where": where, "detail": detail}
        # If the exception carries a classifier verdict, RECORD IT. #6364 built
        # the remaining-work vs correct-refusal split as data on the exception
        # (ExitSetFactoringGap.classification), and this census was
        # stringifying the message and throwing that data away -- so every
        # factoring gap reached the ledger UNCLASSIFIED and the split could not
        # be read at corpus scale. Never re-derive it by parsing a repr.
        classify = getattr(exc, "classification", None)
        if callable(classify):
            try:
                verdict = classify()
            except Exception:  # noqa: BLE001 -- a classifier defect is not R
                verdict = None
            if verdict is not None and hasattr(verdict, "row"):
                row["classification"] = verdict.row()
        self.defects.append(row)

    def _designed_gap(self, where: str, exc: BaseException) -> None:
        """Record one designed gap: named owner, carried verdict, counted."""
        row: dict[str, Any] = {
            "owner": type(exc).__name__,
            "where": where,
            "detail": f"{type(exc).__name__}: {exc}",
        }
        classify = getattr(exc, "classification", None)
        if callable(classify):
            verdict = classify()
            if verdict is not None and hasattr(verdict, "row"):
                row["classification"] = verdict.row()
        self.designed_gaps.append(row)

    # -- the one door -------------------------------------------------------

    def measure(self, sugar: object, *, where: str) -> None:
        """Reduce one constructed function and classify the outcome.

        ``where`` is the construction coordinate of the function whose sugar
        this is (``file:line:col``) — it identifies the desugar CALL, which is
        the true grain of a refusal (one refusal per reduction), and appears in
        defect rows. It is never used as an effect-occurrence key.
        """
        from sugar_lift_py_tests.audit_only.collect_construction_gaps import (
            collect_construction_panic,
        )
        from sugar_source_tree.panic import SugarNotWritten

        # ConstructionPanic is a BaseException. Hold it only through the sole
        # sanctioned audit membrane (collect_construction_panic) — never with a
        # local ``except ConstructionPanic`` soft continue (panic-catch law).
        def _desugar():
            try:
                return sugar.desugar(None)  # type: ignore[attr-defined]
            except SugarNotWritten as gap:
                return ("refusal", gap)
            except Exception as exc:  # noqa: BLE001 -- ordinary defect, not R
                return ("defect", exc)

        outcome, panic_row = collect_construction_panic(where, _desugar)
        if panic_row is not None:
            self.construction_panics.append(
                {
                    "where": where,
                    "owner": (
                        (panic_row.info or {}).get("owner")
                        if isinstance(panic_row.info, dict)
                        else getattr(getattr(panic_row, "info", None), "owner", None)
                    ),
                    "message": panic_row.message,
                }
            )
            return
        if isinstance(outcome, tuple) and len(outcome) == 2 and outcome[0] == "refusal":
            owner = _refusal_owner(outcome[1])
            self._tally(owner, f"desugar-call:{where}")
            return
        if isinstance(outcome, tuple) and len(outcome) == 2 and outcome[0] == "defect":
            exc = outcome[1]
            # A designed gap gets its own counted bucket. TWO conditions, and
            # the second is the load-bearing one — see `_is_designed_gap`.
            if _is_designed_gap(exc):
                self._designed_gap(where, exc)
                return
            # A DECLARED TYPE THAT CARRIES NO VERDICT IS NEITHER. The classifier
            # is supposed to attach one, so its absence is a defect in the
            # INSTRUMENT, not a finding about the code under measurement.
            # Defaulting it into either bucket — quietly correct, or quietly a
            # code defect — is the silent-lossy shape one level up from the one
            # this door closes. It gets its own named kind and stays red.
            if type(exc) in _designed_gap_types() and _carried_verdict(exc) is None:
                self._defect(
                    "instrument-gap",
                    where,
                    f"designed-gap-without-classification:{type(exc).__name__}: "
                    f"{exc}",
                    exc=exc,
                )
                return
            self._defect(
                "desugar-exception", where, f"{type(exc).__name__}: {exc}", exc=exc
            )
            return

        walk = OutcomeWalk().walk(outcome)
        for defect in walk.defects:
            self._defect("audit-defect", where, defect)
        for effect in walk.effects:
            occurrence = effect_occurrence(effect)
            if occurrence is None:
                # No authenticated coordinate: report the instrument gap rather
                # than fabricating a key from the enclosing function.
                self._defect(
                    "instrument-gap",
                    where,
                    f"no-occurrence-coordinate:{effect_owner(effect)}",
                )
                continue
            self._tally(effect_owner(effect), occurrence)

    # -- reporting ----------------------------------------------------------

    def merge(self, other: "DesugarAxis") -> None:
        self.families.update(other.families)
        self.categories.update(other.categories)
        self.by_category_owner.update(other.by_category_owner)
        self.construction_panics.extend(other.construction_panics)
        self.defects.extend(other.defects)
        self.designed_gaps.extend(other.designed_gaps)
        self._seen |= other._seen

    def row(self) -> dict[str, Any]:
        return {
            "desugarFamilies": dict(self.families),
            "R_desugar": sum(self.families.values()),
            # Disjoint and summing to R_desugar. Read these, not the total.
            "desugarCategories": dict(self.categories),
            "desugarByCategoryOwner": dict(self.by_category_owner),
            "R_desugar_owed_work": int(self.categories.get("typed-refusal", 0)),
            "R_desugar_accounted_semantics": int(
                self.categories.get("constructed-effect", 0)
            ),
            "desugarConstructionPanics": list(self.construction_panics),
            "desugarDefects": list(self.defects),
            # Designed gaps: correct output, counted and named, never red and
            # never summed into any of the four quantities above.
            "desugarDesignedGaps": list(self.designed_gaps),
            "R_desugar_designed_gaps": len(self.designed_gaps),
            "desugarDesignedGapOwners": dict(
                Counter(row["owner"] for row in self.designed_gaps)
            ),
        }

    @property
    def red(self) -> bool:
        """Panics and defects make the instrument exit red. R_desugar does not:
        a typed refusal is a measured frontier row, not a broken instrument.

        Neither does a DESIGNED gap. It is a named mechanism answering
        correctly, so holding the run red on it would be the 171.6x disease in
        miniature: counting correct output as remaining work. It is counted and
        published under its own owner instead — reported, never silent."""
        return bool(self.construction_panics or self.defects)


def _refusal_owner(gap: BaseException) -> str:
    owner = getattr(gap, "owner", None)
    if isinstance(owner, str) and owner:
        return owner
    return type(gap).__name__

"""The bounded owner of every source-resolution memo.

Authority model
---------------
A memo may only be served inside the session that produced it.

Two kinds of registry are legitimate in this tree, and they are not
interchangeable:

* A **content-addressed** registry (``construction_cache._SHAPE_CIDS``, the
  ``_interned`` ClassVar tables) is legitimately process-global, because the CID
  *is* the complete key: the same content addresses to the same value
  everywhere, forever, under every authority.

* A **projection** memo is not. ``resolve_export`` and
  ``resolve_source_visible_frame`` are keyed by a content address, but their
  *values* are not content: they are objects bound to one live
  ``TreeConstructionContextV1`` -- a mutable per-session table of
  ``source_call_frames`` / ``source_call_resolutions`` / ``source_class_bases``
  that ``_resolve_source_visible_frame_uncached`` writes into as it projects.
  Serving such a value to a later construction hands that construction a node
  whose context belongs to somebody else's session. That is a leak of authority,
  not a cache hit, and it is how one project warms another project's answer
  inside a long-lived ``lift_rpc`` daemon.

So the memo is owned by a session object, created by whoever owns the
construction, and discarded with it. It is deliberately NOT a module-level dict
with an ever-more-elaborate key: an elaborate global key is how this class of
bug returns, because every newly authenticated input is one more thing someone
forgets to add to the key. A session cannot be forgotten -- it either exists for
this construction or the memo does not answer.

``enabled=False`` disables memoization entirely. That switch must change
performance ONLY: never a formula, never a gap, never a verdict.

Decision of record (session-memo liveness)
------------------------------------------
The memos on this class are real amortization, not decorative. They fire in two
places:

1. **Inside one call tree** -- even a single-shot explicitly constructed session
   still needs ``frame_active`` (cycle detection) and nested export/frame hits
   while that one top-level resolve walks reexports and nested callees.
2. **Across top-level resolves** -- only when the *same* session object is
   threaded. Multi-resolve owners (file-open population, package-level
   enumeration that projects the same dependency definitions for many consumer
   files) MUST mint one session and pass it through every resolve. Leaving
   ``session=None`` at those doors re-opens a session per call and the across-
   call amortization is gone -- correct isolation, wrong owner.

Deletion of these memos is refused: the pandas megamodule wall was re-materializing
SourceFile + class-base sugar once per call-site receipt of the same authenticated
definition. The session is the boundary that makes that amortization safe.

An explicitly constructed session remains the honest single-shot leaf: slower,
always correct, never process-global. ``None`` is unknown population authority
and refuses; it is not permission for any owner to invent a roster.

Walk-scoped multi-resolve owner (``walk_session_for``)
------------------------------------------------------
A census / package walk is ONE workspace root under ONE pin authority. Production
doors that open many files under that root (``open_source_file_for_construction``,
``sugar.enumerate`` functions/facts for a corpus) are multi-resolve owners in the
sense of the decision of record above: they must thread ONE session so projection
memos survive file-to-file and re-open of the same content.

Legitimacy (why this is not process-global free-for-all):

* Key is the resolved workspace root — the authority locus of the walk, not a
  content CID. Different roots mint different sessions; one project cannot warm
  another's answers.
* Values remain session-bound live Nodes (frame / module materialize). They are
  never parked under a process-global content map. §4 residency covers pure
  content-derived prep (SourceFile body, lexical import pass); visible-frame
  projection stays on the session object the walk owns.
* ``frame_results`` / ``frame_holds`` are LRU-capped (default 512, same order
  of magnitude as process-resident file limit). A hold exists only while its
  memo row is served — walk-scoped sessions must not retain every projected
  SourceFile for the whole corpus (that was the unbounded-accumulation
  disease: shared session degraded across opens while fresh stayed flat).
* Measured (orange, tip #7078): cross-file shared session is ~15% on a mixed
  20-file lib sample (frame_results after 20 files ≈ 1 — almost no shared
  definitions). Same-content re-open under the same walk session is the
  amortization that is real (identical definition coordinates hit). Do not bet
  a 6× census cut on walk session alone.

``walk_session_for(root, enrolled_distributions=...)`` is the small production
default for multi-file doors. Callers that need isolation construct an explicit
``SourceResolutionSession(enrolled_distributions=...)``. Unknown authority is
not a session state; an authoritative empty population is ``frozenset()``.
"""

from __future__ import annotations

import collections
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .manager_construction import PrefixFallthroughOutcomeV1

# (resolved workspace root, authenticated population) -> walk-owned session.
# Not content-keyed; not a substitute for §4 residency. Cleared only by tests.
_WALK_SESSIONS: dict[tuple[str, frozenset[str]], "SourceResolutionSession"] = {}
_ROSTER_UNSET = object()

# Default matches process-resident file LRU (#7071). A walk-scoped session that
# retained frame_holds for every projected SourceFile forever recreated the
# "shared context degrades across opens" disease at corpus scale.
_DEFAULT_FRAME_MEMO_LIMIT = 512


ENROLLED_POPULATIONS_ENV = "SUGAR_ENROLLED_POPULATIONS"

_POPULATION_ENTRY = re.compile(r"^[A-Za-z0-9_.\-]+(:[A-Za-z_][A-Za-z0-9_]*)?$")


def declared_extra_populations() -> frozenset[str]:
    """The extra authenticated source populations this measurement enrolls.

    Declared, never inferred: ``SUGAR_ENROLLED_POPULATIONS`` is a comma list
    of entries. An entry is a distribution name as its dependency graph
    spells it (``pytest``, ``numpy``, ``cpython-stdlib``) or a module-scoped
    form ``<distribution>:<top-level module>`` (``cpython-stdlib:contextlib``)
    that enrolls one module of a distribution so a population can be widened
    one module at a time and measured (plan Cut 1). Malformed entries refuse.
    """
    raw = os.environ.get(ENROLLED_POPULATIONS_ENV, "")
    entries = frozenset(item.strip() for item in raw.split(",") if item.strip())
    for entry in entries:
        if not _POPULATION_ENTRY.match(entry):
            raise TypeError(
                f"{ENROLLED_POPULATIONS_ENV} entry {entry!r} is not a distribution "
                "name or '<distribution>:<module>'"
            )
    return entries


def enrolled_population_roster(distribution: str) -> frozenset[str]:
    """The corpus distribution plus every declared extra population."""
    if not isinstance(distribution, str) or not distribution:
        raise TypeError("enrolled_population_roster requires the corpus distribution")
    return frozenset({distribution}) | declared_extra_populations()


def population_admits(roster: frozenset[str], name: str, module_name: str | None) -> bool:
    """True when ``name`` (a graph's distribution name) is enrolled for this
    module: by distribution, or by a module-scoped entry naming its top-level
    module. ``None`` module means only a distribution-level entry admits."""
    if name in roster:
        return True
    if module_name:
        top = module_name.split(".", 1)[0]
        return f"{name}:{top}" in roster
    return False


def _require_enrolled_distribution_roster(value: object) -> frozenset[str]:
    """Return one explicit population authority; unknown is unconstructible."""
    if not isinstance(value, frozenset) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise TypeError(
            "enrolled_distributions must be an authoritative frozenset[str]; "
            "None is unknown, not empty"
        )
    return value


def _frame_memo_limit() -> int:
    """Cap for session frame_results (+ co-evicted frame_holds).

    Env ``SUGAR_SESSION_FRAME_MEMO_LIMIT`` (default 512). Hold lifetime must
    track the memo row it guards — never longer (see remember_frame).
    """
    raw = os.environ.get(
        "SUGAR_SESSION_FRAME_MEMO_LIMIT", str(_DEFAULT_FRAME_MEMO_LIMIT)
    )
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_FRAME_MEMO_LIMIT


class SourceResolutionSession:
    """One bounded construction / source-oracle session and its memo tables."""

    __slots__ = (
        "enabled",
        "enrolled_distributions",
        "export_resolutions",
        "export_terminals",
        "frame_results",
        "frame_holds",
        "frame_active",
        "module_materializations",
        "prefix_files",
        "prefix_fallthrough",
        "import_use_rosters",
        "import_value_rosters",
        "lexical_passes",
        "dependency_graphs",
    )

    def __init__(
        self,
        *,
        enrolled_distributions: frozenset[str],
        enabled: bool = True,
    ) -> None:
        enrolled_distributions = _require_enrolled_distribution_roster(
            enrolled_distributions
        )
        self.enabled = enabled
        # Pin membership for the population membrane. Any graph whose
        # distribution_name is absent is off-pin and must cite, never
        # MaterializeModule. An empty set is authoritative emptiness; there is
        # no unknown/None state that can silently admit every distribution.
        self.enrolled_distributions = enrolled_distributions
        # (distribution_artifact_cid, module_name, exported_name) -> pure-entry
        # resolution (includes module-structural reexport warrants; no path
        # import_binding_cid).
        self.export_resolutions: dict[tuple[str, str, str], Any] = {}
        # Same key -> definition/gap only (no warrants). Shared by reexport hops
        # that carry path warrants and cannot use export_resolutions.
        self.export_terminals: dict[tuple[str, str, str], Any] = {}
        # definition coordinate -> (frame, target) | ManagerConstructionGapV1.
        # OrderedDict LRU: walk-scoped sessions must not retain every projected
        # definition forever. Access order tracks hits/remembers; oldest keys
        # evict with their frame_holds (hold outlives memo by zero extra time).
        self.frame_results: collections.OrderedDict[tuple, Any] = (
            collections.OrderedDict()
        )
        # SourceFile that owns cached (frame, target) node identity — alive for
        # exactly as long as frame_results serves that key, not one moment longer.
        self.frame_holds: collections.OrderedDict[tuple, Any] = (
            collections.OrderedDict()
        )
        # In-progress definition coordinates.  A cross-module call graph that
        # re-enters a definition already being projected is a cycle: it stays
        # typed-loud exactly like the local recursive case, and never loops.
        # Re-entrancy is a property of THIS traversal, so it is session state.
        self.frame_active: set[tuple] = set()
        # Module SourceFile + producer root + pin roster for one authenticated
        # module under this session. Frame projection is per-definition, but
        # materializing the whole module per definition multiplied in-population
        # megamodules (pandas/_config/config.py ×18 in one _json.py open). The
        # value is live context-bound, so it lives here — never process-global.
        self.module_materializations: dict[tuple, Any] = {}
        # Prefix-door SourceFile (no frame_projection). Export fallthrough called
        # _module_prefix_outcome once per export locus and rebuilt config N times.
        # Separate from module_materializations: different context settings.
        self.prefix_files: dict[str, Any] = {}
        # (source_cid, lineno, col_offset) -> PrefixFallthroughOutcomeV1.  The
        # locus key is complete authority; the closed value prevents refusal
        # from becoming a memoized ordinary non-fallthrough.
        self.prefix_fallthrough: dict[tuple, Any] = {}
        # source_cid -> import-use / value-use receipt tuples (lexical pass once)
        self.import_use_rosters: dict[str, Any] = {}
        self.import_value_rosters: dict[str, Any] = {}
        # source_cid -> full lexical _Pass product (rows + value_rows). One walk
        # fills both roster doors; avoids a second SourceFile for the same body.
        self.lexical_passes: dict[str, Any] = {}
        # top_level -> DependencyArtifactGraph for this session (and walk). Call
        # sites used to mint a fresh ``dependency_graphs={}`` per frame /
        # prefix / populate path, re-entering authenticate_dependency_top_level
        # 21× for the same warnings/re/inspect tops on one test_pandas open
        # (65 total across 5 unique tops). Process cache makes each hit cheap;
        # session ownership makes the ask once per content under the walk.
        # Graphs are content-addressed install facts (no live construction
        # context) — process-resident top-level cache remains legal; this
        # table deletes the path-local re-ask disease.
        self.dependency_graphs: dict[str, Any] = {}

    # -- export resolution memo ------------------------------------------

    def export_hit(self, key: tuple[str, str, str]) -> Any | None:
        return self.export_resolutions.get(key) if self.enabled else None

    def remember_export(self, key: tuple[str, str, str], result: Any) -> None:
        if self.enabled:
            self.export_resolutions[key] = result

    def export_terminal_hit(self, key: tuple[str, str, str]) -> Any | None:
        return self.export_terminals.get(key) if self.enabled else None

    def remember_export_terminal(self, key: tuple[str, str, str], result: Any) -> None:
        if self.enabled:
            self.export_terminals[key] = result

    # -- source-visible frame memo ---------------------------------------

    def frame_hit(self, key: tuple) -> Any | None:
        if not self.enabled:
            return None
        hit = self.frame_results.get(key)
        if hit is not None:
            # LRU access: keep hold + memo co-ordered.
            self.frame_results.move_to_end(key)
            if key in self.frame_holds:
                self.frame_holds.move_to_end(key)
        return hit

    def remember_frame(self, key: tuple, result: Any, hold: Any = None) -> None:
        """Memo one frame result; pin hold for exactly the memo's lifetime.

        Hold invariant: a ``frame_holds`` entry outlives its ``frame_results``
        row by zero extra time. Walk-scoped sessions used to retain every
        projected SourceFile for the whole 1421-file walk; that unbounded hold
        is the accumulation disease (shared context degrades across opens).
        LRU co-evicts hold when the memo row is dropped.
        """
        if not self.enabled:
            return
        if hold is not None:
            self.frame_holds[key] = hold
            self.frame_holds.move_to_end(key)
        self.frame_results[key] = result
        self.frame_results.move_to_end(key)
        self._evict_frame_memo_lru()

    def _evict_frame_memo_lru(self) -> None:
        """Drop oldest frame memos until at limit; release holds in lockstep."""
        limit = _frame_memo_limit()
        while len(self.frame_results) > limit:
            old_key, _ = self.frame_results.popitem(last=False)
            self.frame_holds.pop(old_key, None)
        # Holds without a memo row are dead weight (should not happen if
        # remember_frame is the only writer; scrub anyway).
        if len(self.frame_holds) > len(self.frame_results):
            for dead in list(self.frame_holds.keys()):
                if dead not in self.frame_results:
                    del self.frame_holds[dead]

    # -- module materialize memo (shared across definitions in one module) --

    def module_materialize_hit(self, key: tuple) -> Any | None:
        return self.module_materializations.get(key) if self.enabled else None

    def remember_module_materialize(self, key: tuple, product: Any) -> None:
        if self.enabled:
            self.module_materializations[key] = product

    # -- prefix-door SourceFile + fallthrough (export path) --------------

    def prefix_file_hit(self, source_cid: str, source_seat: str) -> Any | None:
        return self.prefix_files.get((source_cid, source_seat)) if self.enabled else None

    def remember_prefix_file(
        self, source_cid: str, source_seat: str, source_file: Any
    ) -> None:
        if self.enabled:
            self.prefix_files[(source_cid, source_seat)] = source_file

    def fallthrough_hit(self, key: tuple) -> PrefixFallthroughOutcomeV1 | None:
        if not self.enabled:
            return None
        return self.prefix_fallthrough.get(key)

    def remember_fallthrough(
        self, key: tuple, value: PrefixFallthroughOutcomeV1
    ) -> None:
        from .manager_construction import PrefixFallthroughOutcomeV1

        if type(value) is not PrefixFallthroughOutcomeV1:
            raise TypeError("prefix fallthrough memo requires its closed outcome")
        if self.enabled:
            self.prefix_fallthrough[key] = value

    # -- lexical import rosters (call / value doors) ---------------------

    def import_use_hit(self, source_cid: str) -> Any | None:
        return self.import_use_rosters.get(source_cid) if self.enabled else None

    def remember_import_use(self, source_cid: str, receipts: Any) -> None:
        if self.enabled:
            self.import_use_rosters[source_cid] = receipts

    def import_value_hit(self, source_cid: str) -> Any | None:
        return self.import_value_rosters.get(source_cid) if self.enabled else None

    def remember_import_value(self, source_cid: str, receipts: Any) -> None:
        if self.enabled:
            self.import_value_rosters[source_cid] = receipts

    def lexical_pass_hit(self, source_cid: str) -> Any | None:
        return self.lexical_passes.get(source_cid) if self.enabled else None

    def remember_lexical_pass(self, source_cid: str, runner: Any) -> None:
        if self.enabled:
            self.lexical_passes[source_cid] = runner


def session_or_new(
    session: SourceResolutionSession | None,
    *,
    enrolled_distributions: frozenset[str] | object = _ROSTER_UNSET,
) -> SourceResolutionSession:
    """Return the caller's authoritative session; refuse unknown authority.

    Multi-resolve owners (populate, package enumeration, file-open, census walk)
    must pass an explicit session — or use ``walk_session_for(workspace_root)``
    — so amortization reaches every receipt they own. Do not call this at those
    doors and throw the result away between receipts.
    """
    if session is None:
        if enrolled_distributions is _ROSTER_UNSET:
            raise TypeError(
                "session construction requires an enrolled distribution roster; "
                "pass enrolled_distributions=frozenset(...)"
            )
        return SourceResolutionSession(
            enrolled_distributions=_require_enrolled_distribution_roster(
                enrolled_distributions
            )
        )
    if (
        enrolled_distributions is not _ROSTER_UNSET
        and enrolled_distributions != session.enrolled_distributions
    ):
        raise ValueError(
            "supplied enrolled distribution roster differs from session authority"
        )
    return session


def walk_session_for(
    workspace_root: Path | str,
    *,
    enrolled_distributions: frozenset[str],
) -> SourceResolutionSession:
    """Return the multi-resolve session owned by one workspace walk.

    One resolved root + one explicit roster → one session for the life of the
    process (or until ``clear_walk_sessions``). Different population authority
    cannot share projection state merely because the filesystem root matches.
    """
    enrolled_distributions = _require_enrolled_distribution_roster(
        enrolled_distributions
    )
    key = (str(Path(workspace_root).resolve()), enrolled_distributions)
    session = _WALK_SESSIONS.get(key)
    if session is None:
        session = SourceResolutionSession(enrolled_distributions=enrolled_distributions)
        _WALK_SESSIONS[key] = session
    return session


def clear_walk_sessions() -> None:
    """Test door: drop walk-owned sessions so teeth start cold."""
    _WALK_SESSIONS.clear()

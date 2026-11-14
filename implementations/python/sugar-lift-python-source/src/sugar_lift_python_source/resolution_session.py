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

* A **projection** memo is not. ``resolve_export`` and module materialization
  are keyed by a content address, but their *values* are not content: they are
  objects bound to one live ``TreeConstructionContextV1`` -- a mutable
  per-session table of ``source_call_frames`` / ``source_call_resolutions`` /
  ``source_class_bases`` that construction writes into as it projects.
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
   still needs nested export hits while that one top-level resolve walks
   reexports.
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
* Values remain session-bound live Nodes (module materialize). They are
  never parked under a process-global content map. §4 residency covers pure
  content-derived prep (SourceFile body, lexical import pass); module
  materialization stays on the session object the walk owns.

``walk_session_for(root, enrolled_distributions=project_file_roster(root))`` is
the production default for multi-file doors: the population is step 2's file
list (content CIDs), nothing else. Callers that need isolation construct an
explicit ``SourceResolutionSession(enrolled_distributions=...)``. Unknown
authority is not a session state; an authoritative empty population is
``frozenset()``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# (resolved workspace root, authenticated population) -> walk-owned session.
# Not content-keyed; not a substitute for §4 residency. Cleared only by tests.
_WALK_SESSIONS: dict[tuple[str, frozenset[str]], "SourceResolutionSession"] = {}
_ROSTER_UNSET = object()

# resolved workspace root -> step 2's file list for it, as content CIDs.
_PROJECT_FILE_ROSTERS: dict[str, frozenset[str]] = {}


def project_file_roster(workspace_root: Path | str) -> frozenset[str]:
    """The population of a lift: step 2's file list, and nothing else.

    Step 2 lists the files as content-addressed mementos (the ``source_files``
    level: ``SourceTree.paths()`` through the oracle's ``fragment_of``). The
    roster is the content CID of every file on that list. A file the oracle
    cannot read is not on the list, so it is not on the roster. No distribution
    name, no standing extra and no environment entry is added: a module whose
    source is not one of these files is not enrolled, whatever it is.

    Read once per resolved root and shared by every open under it, so a walk
    lists its files once, not once per file.
    """
    from sugar_source_tree.tree import SourceTree

    from .source_oracle import SourceUnavailable

    key = str(Path(workspace_root).resolve())
    roster = _PROJECT_FILE_ROSTERS.get(key)
    if roster is None:
        tree = SourceTree(Path(key))
        cids: set[str] = set()
        for path in tree.paths():
            try:
                cids.add(tree.fragment_of(path).source_cid)
            except SourceUnavailable:
                continue
        roster = frozenset(cids)
        _PROJECT_FILE_ROSTERS[key] = roster
    return roster


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


class SourceResolutionSession:
    """One bounded construction / source-oracle session and its memo tables."""

    __slots__ = (
        "enabled",
        "enrolled_distributions",
        "export_resolutions",
        "export_terminals",
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
    _PROJECT_FILE_ROSTERS.clear()

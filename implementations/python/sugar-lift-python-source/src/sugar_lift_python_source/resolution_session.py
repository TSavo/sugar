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

1. **Inside one call tree** -- even a single-shot ``session_or_new(None)`` entry
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

``session_or_new(None)`` remains the honest single-shot leaf: slower, always
correct, never process-global. It is not permission for a multi-resolve owner to
drop the session.
"""

from __future__ import annotations

from typing import Any


class SourceResolutionSession:
    """One bounded construction / source-oracle session and its memo tables."""

    __slots__ = (
        "enabled",
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
    )

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        # (distribution_artifact_cid, module_name, exported_name) -> pure-entry
        # resolution (includes module-structural reexport warrants; no path
        # import_binding_cid).
        self.export_resolutions: dict[tuple[str, str, str], Any] = {}
        # Same key -> definition/gap only (no warrants). Shared by reexport hops
        # that carry path warrants and cannot use export_resolutions.
        self.export_terminals: dict[tuple[str, str, str], Any] = {}
        # definition coordinate -> (frame, target) | ManagerConstructionGapV1
        self.frame_results: dict[tuple, Any] = {}
        # Keep the SourceFile that owns cached (frame, target) node identity
        # alive for exactly as long as this session serves that memo.
        self.frame_holds: dict[tuple, Any] = {}
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
        # (source_cid, lineno, col_offset) -> bool fallthrough answer
        self.prefix_fallthrough: dict[tuple, bool] = {}
        # source_cid -> import-use / value-use receipt tuples (lexical pass once)
        self.import_use_rosters: dict[str, Any] = {}
        self.import_value_rosters: dict[str, Any] = {}
        # source_cid -> full lexical _Pass product (rows + value_rows). One walk
        # fills both roster doors; avoids a second SourceFile for the same body.
        self.lexical_passes: dict[str, Any] = {}

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
        return self.frame_results.get(key) if self.enabled else None

    def remember_frame(self, key: tuple, result: Any, hold: Any = None) -> None:
        if not self.enabled:
            return
        if hold is not None:
            self.frame_holds[key] = hold
        self.frame_results[key] = result

    # -- module materialize memo (shared across definitions in one module) --

    def module_materialize_hit(self, key: tuple) -> Any | None:
        return self.module_materializations.get(key) if self.enabled else None

    def remember_module_materialize(self, key: tuple, product: Any) -> None:
        if self.enabled:
            self.module_materializations[key] = product

    # -- prefix-door SourceFile + fallthrough (export path) --------------

    def prefix_file_hit(self, source_cid: str) -> Any | None:
        return self.prefix_files.get(source_cid) if self.enabled else None

    def remember_prefix_file(self, source_cid: str, source_file: Any) -> None:
        if self.enabled:
            self.prefix_files[source_cid] = source_file

    def fallthrough_hit(self, key: tuple) -> bool | None:
        if not self.enabled:
            return None
        return self.prefix_fallthrough.get(key)

    def remember_fallthrough(self, key: tuple, value: bool) -> None:
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


def session_or_new(session: SourceResolutionSession | None) -> SourceResolutionSession:
    """Resolve the caller's session, or open one bounded to this single call tree.

    ``None`` never means "share the process": it means "this call is its own
    session". Nested resolves inside that call still share the returned object
    (cycle detection and within-tree amortization stay real). The memo dies with
    the call tree -- slower across independent top-level calls, always correct.

    Multi-resolve owners (populate, package enumeration, file-open) must pass an
    explicit session so amortization reaches every receipt they own. Do not call
    this at those doors and throw the result away between receipts.
    """
    return SourceResolutionSession() if session is None else session

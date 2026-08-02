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
"""

from __future__ import annotations

from typing import Any


class SourceResolutionSession:
    """One bounded construction / source-oracle session and its memo tables."""

    __slots__ = (
        "enabled",
        "export_resolutions",
        "frame_results",
        "frame_holds",
        "frame_active",
        "module_packs",
        "prefix_files",
        "prefix_fallthrough",
    )

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        # (distribution_artifact_cid, module_name, exported_name) -> resolution
        self.export_resolutions: dict[tuple[str, str, str], Any] = {}
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
        # module.source_cid -> (source_file, producer_root, mutable_global_bindings)
        # Frame-path materialize: N definitions in one module must not rebuild
        # the same SourceFile N times (enum.py measured 35x on one open).
        self.module_packs: dict[str, Any] = {}
        # module.source_cid -> SourceFile for prefix fallthrough (no frame_projection)
        self.prefix_files: dict[str, Any] = {}
        # (source_cid, lineno, col_offset) -> bool fallthrough verdict
        self.prefix_fallthrough: dict[tuple, bool] = {}

    # -- export resolution memo ------------------------------------------

    def export_hit(self, key: tuple[str, str, str]) -> Any | None:
        return self.export_resolutions.get(key) if self.enabled else None

    def remember_export(self, key: tuple[str, str, str], result: Any) -> None:
        if self.enabled:
            self.export_resolutions[key] = result

    # -- source-visible frame memo ---------------------------------------

    def frame_hit(self, key: tuple) -> Any | None:
        return self.frame_results.get(key) if self.enabled else None

    def remember_frame(self, key: tuple, result: Any, hold: Any = None) -> None:
        if not self.enabled:
            return
        if hold is not None:
            self.frame_holds[key] = hold
        self.frame_results[key] = result

    # -- module materialize memo (by source_cid) -------------------------

    def module_hit(self, source_cid: str) -> Any | None:
        """Return the session's materialize pack for this source body, or None."""
        return self.module_packs.get(source_cid) if self.enabled else None

    def remember_module(self, source_cid: str, pack: Any) -> None:
        """Hold one materialize pack for this source body for the session life."""
        if self.enabled:
            self.module_packs[source_cid] = pack

    # -- prefix fallthrough memo -----------------------------------------

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


def session_or_new(session: SourceResolutionSession | None) -> SourceResolutionSession:
    """Resolve the caller's session, or open one bounded to this single call.

    ``None`` never means "share the process": it means "this call is its own
    session". The memo then dies with the call, which is slower and always
    correct.

    Production file open must thread ONE session through the whole resolve
    graph (``open_source_file_for_construction`` → populate → resolve_*). A
    memo that lives on a per-call session is born empty and dies immediately.
    """
    return SourceResolutionSession() if session is None else session

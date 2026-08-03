# Dependency Artifact Cache Coherence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refuse and visibly invalidate impossible dependency-artifact graph cache entries, then rebuild through the existing authenticated cache-miss path.

**Architecture:** Put the relationship invariant at `DependencyArtifactGraph.__post_init__`, the shared mint/reconstruction door. Advance the disk schema to `dep-graph-v4`; rejected seats are warning-logged with their key and field pair, unlinked exactly, and returned as a miss so the existing consumer rebuilds without defaults.

**Tech Stack:** Python 3.12, frozen dataclasses, pickle disk cache, `logging`, pytest.

## Global Constraints

- Rebuild only through the existing cache-miss path; do not add a fallback graph.
- Emit `dependency-artifact-cache-refused` with the requested artifact CID, rejected `artifact_kind` and `distribution_name`, named reason, and invalidation outcome.
- Invalidate only `_artifact_disk_cache_path(artifact_cid)`.
- Do not connect this defect to the 94 off-population dependency rows; a cold-cache census disproved that suspected cause.
- Run only the focused cache-authority tests locally; do not take battleaxe from the width census.

---

### Task 1: Cache reconstruction coherence and refusal

**Files:**
- Modify: `implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/dependency_artifact.py`
- Test: `implementations/python/sugar-lift-python-source/tests/test_dependency_artifact_cache_authority.py`

**Interfaces:**
- Consumes: `DependencyArtifactGraph.authenticate(distribution) -> DependencyArtifactGraph`, `_load_authenticate_disk_cache(artifact_cid) -> DependencyArtifactGraph | None`, and the existing `None`-as-cache-miss rebuild path.
- Produces: `DependencyArtifactGraphCoherenceError`, schema `dep-graph-v4`, and warning event `dependency-artifact-cache-refused`.

- [x] **Step 1: Write the coherent disk-hit discrimination arm**

Append a focused test that warms a distribution seat, clears process-local tables, replaces `DependencyArtifactGraph._read_recorded_installation` with a function that raises, and authenticates again:

```python
def test_coherent_disk_graph_is_served_without_refusal(
    tmp_path, monkeypatch, caplog
):
    distribution = _install(
        tmp_path / "project", implementation_source=_IMPL_A
    )
    warm = DependencyArtifactGraph.authenticate(distribution)
    seat = da._artifact_disk_cache_path(warm.distribution_artifact_cid)
    da._AUTHENTICATE_GRAPH_CACHE.clear()
    da._AUTHENTICATE_BY_INSTALLATION_FINGERPRINT.clear()
    da._TOP_LEVEL_GRAPH_CACHE.clear()

    def forbidden_rebuild(_distribution):
        raise AssertionError("coherent disk hit rebuilt")

    monkeypatch.setattr(
        DependencyArtifactGraph,
        "_read_recorded_installation",
        staticmethod(forbidden_rebuild),
    )
    served = DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(distribution._path)
    )

    assert _observable(served) == _observable(warm)
    assert seat.is_file()
    assert "dependency-artifact-cache-refused" not in caplog.text
```

- [x] **Step 2: Write the incoherent-pair red arm**

Add a helper that loads the production-written pickle payload, changes its pair to `stdlib/pandas`, recomputes the artifact CID with `cid_of_json`, writes the forged payload to the forged CID seat, and rewrites the fingerprint-to-CID seat. Then authenticate the unchanged distribution and assert:

```python
assert served.artifact_kind == "distribution"
assert served.distribution_name == warm.distribution_name
assert served.distribution_artifact_cid == warm.distribution_artifact_cid
assert not forged_seat.exists()
assert "dependency-artifact-cache-refused" in caplog.text
assert forged_cid in caplog.text
assert "artifact_kind=stdlib" in caplog.text
assert "distribution_name=pandas" in caplog.text
assert "DependencyArtifactGraphCoherenceError" in caplog.text
```

The current implementation must fail by serving the impossible stdlib/pandas graph or leaving its seat resident; this is the intended red, independent of census sealing.

- [x] **Step 3: Run both discrimination arms and record red**

Run unpiped:

```bash
PYTHONPATH=implementations/python/sugar-lift-python-source/src python -m pytest --noconftest -q \
  implementations/python/sugar-lift-python-source/tests/test_dependency_artifact_cache_authority.py \
  -k 'coherent_disk_graph_is_served_without_refusal or incoherent_cached_graph_is_refused_invalidated_and_rebuilt'
```

Expected: coherent arm PASS; incoherent arm FAIL because current main accepts the impossible pair. Record the exact worktree SHA, two test names, first failing assertion, command, and unpiped exit.

- [x] **Step 4: Add the shared coherence constructor law**

Add:

```python
class DependencyArtifactGraphCoherenceError(
    DependencyArtifactAuthenticationError
):
    """Authenticated fields describe no graph a production intake can mint."""
```

In the `stdlib` arm of `DependencyArtifactGraph.__post_init__`, require:

```python
expected_name = f"{sys.implementation.name}-stdlib"
if self.distribution_name != expected_name:
    raise DependencyArtifactGraphCoherenceError(
        "stdlib dependency artifact graph identity is incoherent: "
        f"artifact_kind=stdlib distribution_name={self.distribution_name} "
        f"expected_distribution_name={expected_name}"
    )
```

Do not infer, repair, or replace the rejected name.

- [x] **Step 5: Make cache refusal visible and exact**

Add `logging`, `_LOG = logging.getLogger(__name__)`, and `_DEPENDENCY_ARTIFACT_CACHE_SCHEMA = "dep-graph-v4"`. Factor a loader-local rejection helper whose exact interface is:

```python
def _refuse_authenticate_disk_cache(
    *,
    artifact_cid: str,
    path: Path,
    artifact_kind: object,
    distribution_name: object,
    reason: str,
) -> None:
```

It must call `path.unlink(missing_ok=True)`, capture whether invalidation succeeded, and warning-log one stable event:

```python
_LOG.warning(
    "dependency-artifact-cache-refused "
    "artifact_cid=%s artifact_kind=%s distribution_name=%s "
    "reason=%s invalidated=%s",
    artifact_cid,
    artifact_kind,
    distribution_name,
    reason,
    invalidated,
)
```

Route schema mismatch, malformed/unpickle/reconstruction failures, and wrong parked CID through this helper, then return `None`. Preserve the named coherence exception in `reason` as `DependencyArtifactGraphCoherenceError: ...`.

- [x] **Step 6: Advance writer and reader to schema v4**

Replace both literal `dep-graph-v3` uses with `_DEPENDENCY_ARTIFACT_CACHE_SCHEMA`. Keep the v3 comment as historical context and add that v4 authenticates field relationships.

- [x] **Step 7: Run the two discrimination arms green**

Run the Step 3 command unpiped. Expected: 2 passed, exit 0. Confirm the coherent arm made `_read_recorded_installation` unreachable and the incoherent arm rebuilt the real distribution graph after visible invalidation.

- [x] **Step 8: Add the v3 schema-successor arm**

Warm a coherent seat, rewrite only its payload schema to `dep-graph-v3`, clear process-local tables, authenticate again, and assert the refusal warning names `schema-mismatch`, the returned graph is coherent, and the replacement seat contains schema `dep-graph-v4`.

- [x] **Step 9: Run the focused cache-authority file**

Run unpiped:

```bash
PYTHONPATH=implementations/python/sugar-lift-python-source/src python -m pytest --noconftest -q \
  implementations/python/sugar-lift-python-source/tests/test_dependency_artifact_cache_authority.py
```

Expected: all tests pass, exit 0. This is measured only on the focused file; it is not a broad suite, pandas census, or claim about the 94 rows.

- [x] **Step 10: Commit and push the completed branch**

```bash
git add \
  implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/dependency_artifact.py \
  implementations/python/sugar-lift-python-source/tests/test_dependency_artifact_cache_authority.py \
  docs/superpowers/plans/2026-08-03-dependency-artifact-cache-coherence.md
git commit -m "Refuse incoherent dependency graph cache entries"
git push -u origin fenster/7215
git rev-parse HEAD
```

Report the full 40-character SHA, focused test count and unpiped exit, branch name, and that the branch remains unmerged. State explicitly that the cache defect is not claimed to cause the 94 off-population rows.

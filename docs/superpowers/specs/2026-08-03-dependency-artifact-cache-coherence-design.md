# Dependency Artifact Cache Coherence Design

## Goal

Refuse a dependency-artifact disk-cache entry whose individually authenticated
fields describe no graph the production constructors can mint. Treat that
refusal exactly like the cache miss it is: invalidate the seat, make the refusal
visible, and rebuild from the authenticated installed artifact.

This closes #7215. It does not explain or alter the 94 off-population dependency
rows: a cold-cache census reproduced all 94 and inspected only coherent fresh
cache entries, disproving that suspected connection.

## Existing behavior

`_load_authenticate_disk_cache()` unpickles the independent payload fields and
passes them to `DependencyArtifactGraph`. `__post_init__` authenticates intake
authority, retained file bytes, artifact CID, module projection, and—for
distribution graphs—the name and version carried by METADATA. For a stdlib
graph it checks only that `artifact_kind == "stdlib"`; it does not require the
constructor-owned identity `distribution_name == "cpython-stdlib"` for this
runtime.

Consequently, a payload with `artifact_kind="stdlib"` and
`distribution_name="pandas"` can pass reconstruction when its CID is recomputed
over those forged fields. No production constructor emits that relationship.
The cache authenticates each field without authenticating the relationship.

The consumer already has the correct recovery path. A disk-cache load returning
`None` is a miss; `DependencyArtifactGraph.authenticate()` then reads the
recorded installation, authenticates its files, constructs the graph, stores
the rebuilt graph, and serves it. No new recovery branch is needed.

## Design

### Shared coherence door

`DependencyArtifactGraph.__post_init__` remains the one reconstruction door.
For `artifact_kind == "stdlib"`, it will require the runtime-owned stdlib
identity:

```text
distribution_name == f"{sys.implementation.name}-stdlib"
```

Violation raises a named `DependencyArtifactGraphCoherenceError`, derived from
`DependencyArtifactAuthenticationError`. This places the relationship law at
the constructor rather than duplicating it in the cache loader. Direct minting
and cache reconstruction therefore have the same legal population.

The distribution arm keeps its existing stronger METADATA preimage check. No
distribution name is inferred or repaired.

### Cache schema and invalidation

The disk payload schema advances from `dep-graph-v3` to `dep-graph-v4`, because
the set of payloads the reader accepts has changed. A v3 seat cannot answer the
v4 reader even when its bytes and CID remain authentic.

When an existing seat is rejected for schema mismatch, malformed payload,
wrong parked CID, or graph-coherence failure, the loader deletes that exact
seat. Invalidation targets only `_artifact_disk_cache_path(artifact_cid)`; it
does not clear broad cache directories or unrelated entries.

### Visible refusal and rebuild

The loader records each rejected seat through a module logger at warning level.
The stable event name is:

```text
dependency-artifact-cache-refused
```

The coherence refusal includes:

- the requested artifact CID/cache key;
- `artifact_kind=stdlib`;
- `distribution_name=pandas` (or the actual rejected name);
- the named coherence reason;
- whether deletion of the seat succeeded.

After recording and invalidating, the loader returns `None`. The existing miss
path performs the authenticated rebuild. It never returns an empty, default, or
substitute graph. If the installed artifact itself cannot authenticate, the
existing `DependencyArtifactAuthenticationError` remains fatal.

## Discrimination teeth

Both arms use the real disk loader and the real `authenticate()` consumer.

### Coherent hit

1. Authenticate a test distribution and let production write its disk seat.
2. Clear only the process-local graph/fingerprint tables.
3. Make `_read_recorded_installation` fail if called.
4. Authenticate the unchanged distribution again.
5. Assert the coherent graph is served from disk, no refusal event is logged,
   and the disk seat remains.

This proves the detector does not condemn every cache entry.

### Incoherent pair

1. Start from a production-written coherent payload so its current schema,
   files, modules, and version are authentic.
2. Deliberately change `artifact_kind` to `stdlib` and `distribution_name` to
   `pandas`.
3. Recompute the forged stdlib artifact CID over those exact fields, park the
   payload at that CID's seat, and point the distribution fingerprint seat at
   the forged CID.
4. Clear process-local tables and authenticate the distribution.
5. Assert a `dependency-artifact-cache-refused` warning names the forged CID and
   `stdlib/pandas` pair, the forged seat is deleted, and the returned graph is a
   freshly authenticated distribution graph with the real distribution name.

On current main this lying arm serves the impossible stdlib/pandas graph and
therefore goes red for the intended reason.

### Schema successor

A focused third tooth parks a coherent `dep-graph-v3` payload under its existing
CID. The v4 reader must record a schema refusal, delete the v3 seat, rebuild,
and write a v4 replacement. This prevents a past semantic schema from remaining
resident merely because the content CID did not change.

## Scope and retirement

Only `dependency_artifact.py` and its existing cache-authority test file change.
There is no census, pandas walk, cache scan, default graph, or connection to the
94 off-population rows.

The runtime constructor check is the honest enforcement ceiling in Python. The
test/auditor shell can retire if `DependencyArtifactGraph` becomes a closed
discriminated union whose stdlib variant carries its runtime identity by type,
making the incoherent pair unconstructable before `__post_init__`.

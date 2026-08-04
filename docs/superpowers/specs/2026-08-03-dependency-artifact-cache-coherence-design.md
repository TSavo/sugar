# Dependency Artifact Cache Construction Design

## Goal

Make a cached dependency-artifact graph rehydrate through the same constructor
as live intake. The cache persists constructor inputs, not a graph projection,
so independent `artifact_kind` and `distribution_name` fields cannot exist in a
cache seat.

This closes #7215. It does not explain the 94 off-population dependency rows: a
cold-cache census reproduced those rows with coherent newly written seats.

## Finding

The v3 payload carries enough information to reconstruct lawfully. Every
recorded file retains its relative seat, full bytes, and content CID, including
the distribution METADATA preimage. Those inputs determine the distribution
name and version, artifact CID, module projection, and fixed
`artifact_kind="distribution"`.

The defect is that v3 also pickles the already-constructed file objects and the
derived graph fields. Unpickling bypasses `AuthenticatedArtifactFileV1`'s
constructor, while `_load_authenticate_disk_cache()` directly allocates a graph
from independent derived fields. The seat is a redundant input/output mixture,
not a missing-preimage artifact.

## One construction path

`DependencyArtifactGraph` will not expose its dataclass-generated field
initializer. A direct attempt to allocate one from graph fields raises named
`DependencyArtifactConstructionError` and directs the caller to authenticated
intake.

One internal graph constructor consumes a closed input variant:

- distribution input: ordered `(AuthenticatedArtifactFileV1, diagnostic_path)`
  pairs;
- stdlib input: the same file pairs plus the requested module name.

The constructor derives the variant's fields. For distribution input it parses
the single retained METADATA file, derives name/version, fixes kind to
`distribution`, projects modules from retained Python source, and derives the
artifact CID. For stdlib input it fixes kind and runtime identity from the
running interpreter and requires the requested module in the projection. No
constructor accepts an independent kind/name pair.

Live distribution intake, live stdlib intake, and cache rehydration all call
this constructor. Cache diagnostic paths are retained relative seats; live
paths remain their installed coordinates. Diagnostic paths do not contribute
to graph identity.

The cache may only be selected after live intake has content-addressed the
recorded bytes. A path plus `(mtime_ns, size)` fingerprint is not authenticated
content identity: two different equal-size byte strings can carry the same
stat metadata and select a stale graph without reading either one. That warm
front door is removed rather than widened with another metadata field. The
artifact CID derived from constructor inputs is the only cache key.

## Cache schema v4

A v4 payload has exactly two keys:

```text
schema = dep-graph-v4
files = [{source_seat, content_cid, content}, ...]
```

The loader reconstructs each `AuthenticatedArtifactFileV1` from the primitive
row, firing its content-CID constructor law, then supplies the resulting input
files to the shared distribution constructor. Name, version, artifact CID,
modules, and artifact kind are never deserialized.

Extra keys, including the old `artifact_kind` and `distribution_name`, make the
stored input schema invalid. A v3 seat is likewise invalid for the v4 reader.

## Refusal and recovery

Any malformed input row, schema mismatch, constructor refusal, or mismatch
between the requested cache key and the constructor-derived CID:

1. records warning event `dependency-artifact-cache-refused` with the requested
   artifact CID, named reason, and invalidation result;
2. deletes exactly `_artifact_disk_cache_path(artifact_cid)`;
3. returns `None` to the existing cache-miss branch.

The existing branch reads the installed distribution and constructs it through
the same constructor. No empty or default graph exists. A failure of live
authenticated intake remains fatal.

## Discrimination teeth

1. **Constructor tooth:** use a real coherent graph's fields to attempt direct
   allocation with `artifact_kind="stdlib"` and
   `distribution_name="pandas"`. It must raise
   `DependencyArtifactConstructionError` by name. Current main accepts the
   pair when given the module-private authority token.
2. **Coherent cache tooth:** after live intake derives the content identity, a
   production-written v4 seat survives a cold process table and is served
   without recording a refusal.
3. **Poisoned cache tooth:** remove the retained METADATA input from an otherwise
   exact v4 seat. The shared graph constructor refuses it by its existing
   METADATA rule; the loader records and invalidates the exact seat, then
   `authenticate()` invokes the real installation reader, constructs a
   non-empty lawful distribution graph, and writes a clean v4 replacement.
   This proves constructor refusal and miss execution, not merely skip behavior.
4. **Schema successor tooth:** a v3 seat is visibly invalidated and rebuilt as
   v4.
5. **Stat-collision tooth:** two equal-size source preimages are forced to the
   same mtime. The second authentication must address the second bytes rather
   than serving the first graph through metadata coincidence.

## Identity and scope

For lawful inputs, all public graph fields and artifact CIDs remain identical.
The change removes cache authority over derived fields; it does not rename or
reinterpret them. Focused twins compare the complete observable graph before
and after cold rehydration.

Only `dependency_artifact.py`, its cache-authority tests, and these design/plan
receipts change. No census, pandas walk, broad test run, or battleaxe lease is
part of this shot.

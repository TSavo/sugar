# Runtime Identity V1 Design

## Goal

No control-effect recensus body may claim a measured `frontierWidth` unless it
is bound to the exact authenticated Python interpreter that produced it. The
runtime is producer identity, parallel to loaded stage source CIDs, and belongs
inside the sealed body rather than in the host-noise `sourceStamp` excluded
from `bodyCid`.

The diagnostic artifact produced at commit `8c117c65` remains an honest
unmeasured refusal because it omitted `frontierWidth`. It was observed
externally under CPython 3.12.12 and lacks this runtime identity, so it is not a
fully self-supporting v1 receipt.

## Authority and ownership

`sugar_lift_py_tests.authenticated_pytest` remains the sole Python runtime
authority. It already owns `interpreter_identity()`, reads `[tools].python`
from `sugar-build.toml`, and refuses an implementation/version mismatch.
Runtime identity v1 extends that door; census scripts consume its result and do
not reproduce interpreter inspection or hashing.

The floor-only `no_call_body_attribution.AUTHENTICATED_RUNTIME` constant is a
different domain and must never be imported by the census.

## Runtime identity schema

`runtimeIdentity` has schema `runtimeIdentity/v1` and carries:

- `implementation`: `sys.implementation.name`;
- `version`: `major.minor.micro`;
- `sysVersion`: the complete `sys.version` string;
- `cacheTag`: `sys.implementation.cache_tag`;
- `SOABI`: `sysconfig.get_config_var("SOABI")`;
- `hexVersion`: `hex(sys.hexversion)`;
- `platformTag`: `platform.platform()`;
- `invokedExecutable`: absolute `sys.executable` testimony;
- `resolvedBaseExecutable`: resolved `sys._base_executable` when available,
  otherwise resolved `sys.executable`;
- `executableSha256`: SHA-256 over the resolved base executable bytes.

`requiredRuntime` is derived exclusively from `sugar-build.toml` and is
`cpython-3.12.13` on this pin.

`runtimeCid` is the canonical BLAKE3-512 CID of the schema, implementation,
version, complete `sys.version`, cache tag, SOABI, hex version, platform
tag, and executable SHA-256. Both executable path fields are deliberately
excluded. Moving byte-identical interpreter content preserves `runtimeCid`;
changing interpreter bytes changes it even when every version string remains
the same.

Identity resolution is total or it fails. Missing fields, a missing base
executable, an unreadable executable, or hashing failure produce a typed
runtime identity resolution failure. No `unavailable` marker may appear inside
`runtimeIdentity`.

## Data flow and refusal order

1. After command-line parsing, the recensus resolves the full observed
   identity and authenticates it against `requiredRuntime` before checking or
   selecting corpus paths, deriving or loading demand tables, creating output
   directories, opening checkpoints, or executing stages.
2. A successfully resolved but wrong runtime writes only the existing
   unmeasured envelope. It carries `requiredRuntime`, the fully observed
   `runtimeIdentity`, `runtimeCid`, and the mismatch reason. It emits no width.
3. An identity-resolution or hashing failure writes only the unmeasured
   envelope with `requiredRuntime` when available and a separate
   `runtimeIdentityFailure`. It carries neither `runtimeIdentity` nor
   `runtimeCid` and emits no width.
4. Every shard partial carries `requiredRuntime`, `runtimeIdentity`, and
   `runtimeCid`. The fields participate in `partialCid`.
5. Compose authenticates its own runtime before reading plan or partial
   artifacts. It validates every partial's runtime schema and recomputed CID,
   requires all partial CIDs to agree with its own, and requires each observed
   implementation/version to equal `requiredRuntime`.
6. Any absent, malformed, mismatched, or disagreeing runtime witness produces
   the existing unmeasured envelope and omits `frontierWidth`.
7. A measured board embeds `requiredRuntime`, `runtimeIdentity`, and
   `runtimeCid` before the common conservation mint and before `bodyCid` is
   computed. These fields remain in the `bodyCid` seal domain. They are not
   placed only in `sourceStamp`.
8. An ordinary instrument refusal after successful runtime resolution carries
   the same runtime fields in its unmeasured envelope because those diagnostics
   are runtime-dependent.

## Constructors and validation boundary

The runtime authority exposes observation, authentication, canonical CID
recomputation, and wire validation from one module. Producers cannot mint a
measured partial without supplying authenticated runtime testimony. Consumers
validate raw JSON again; a producer-owned object alone cannot authenticate an
artifact loaded from disk.

No third product category is introduced. Runtime mismatch or identity failure
is instrument/environment failure and therefore unmeasured, never a
`construction-panic` terminal.

## Discrimination teeth

Focused tests must prove:

- two different paths containing identical interpreter bytes mint the same
  `runtimeCid` while retaining distinct path testimony;
- changing only executable bytes changes `executableSha256` and `runtimeCid`;
- a wrong implementation/version refuses before any corpus selection or
  output/checkpoint creation and carries the complete observed identity;
- identity/hash failure produces `runtimeIdentityFailure` and never an
  unavailable marker or width;
- a partial cannot be measured without runtime testimony;
- a partial with a non-recomputable CID refuses;
- equal-count shards with different valid runtime CIDs refuse at compose;
- a truthful set of agreeing partials seals and embeds runtime identity;
- mutating any sealed semantic identity field changes the recomputed
  `runtimeCid` and invalidates/recomputes `bodyCid`;
- changing only host path testimony leaves `runtimeCid` unchanged while the
  sealed body still records the path testimony.

The existing With entrance repair remains an independent prerequisite. No
corpus width run is admissible until both it and runtime identity v1 have
landed.

## Deferred scope

V1 does not add a full standard-library hash, loaded `libpython` hash,
installed-distribution lock, cryptographic signature, cross-host equivalence
tooling, performance telemetry, or generalized provenance framework.

## Enforcement rung and retirement

This is a constructor/consumer refusal contract backed by focused tests. Python
cannot make a raw JSON artifact's fields statically unforgeable, so compose must
recompute and refuse at the boundary. The focused tests may retire only if a
future typed receipt decoder makes missing or inconsistent runtime testimony
unconstructable before compose.

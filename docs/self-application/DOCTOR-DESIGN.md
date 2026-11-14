# Doctor Design

## Goal

`sugar doctor` is the startup health gate for the verifier product. It
answers one question before a self-check result is allowed to become a K claim:
is the configured substrate capable of producing a sound, reproducible,
non-silent proof verdict for this target?

The check names and JSON surface must stay substrate-level. Rust is the v1
adapter, not the doctor vocabulary. For example, doctor reports
`oracle.host.ready`; the Rust adapter evidence may say `rust-analyzer` and
`sugar-linkerd`.

## Product Contract

Doctor has two surfaces:

1. `sugar doctor --target <kit>`: standalone diagnostic for humans and CI.
2. `sugar self-check --doctor ...` or equivalent internal preflight/runtime
   call: the same check engine, with stricter policy when the result is a
   published self-check scoreboard.

The default standalone mode is cheap and structural. The release gate mode is
strict and may run proof-producing checks twice. The implementation should share
the same check data model across both modes:

```text
DoctorReport {
  ok: bool,
  releaseReady: bool,
  mode: "structural" | "strict" | "releaseGate",
  target: string,
  checks: [DoctorCheck],
  floors: DoctorFloorSummary,
}

DoctorCheck {
  id: string,
  status: "pass" | "warn" | "fail",
  severity: "advisory" | "hard",
  domain: string,
  detail: string,
  evidence: object,
}
```

Hard checks fail closed in strict and release-gate mode. Advisory checks may
warn in standalone mode when no proof claim is being made.

## Validation Domains

### 1. Kit Configuration and Manifest Contract

Substrate check names:

- `kit.config.parse`
- `kit.manifest.parse`
- `kit.plugin.command.available`
- `kit.consumer_surface.contract`

Mechanism:

- Reuse the existing `cmd_doctor::run_checks` logic from #1742, but refactor it
  behind a reusable check engine instead of keeping it only in the CLI command.
- Parse `.sugar/config.toml` and every configured manifest. TOML parse or
  missing manifest remains a hard fail.
- Resolve plugin binaries the same way kit dispatch resolves them: manifest
  `working_dir`, relative path handling, and PATH lookup. Missing or
  non-executable binaries remain hard fails.
- Query each plugin over JSON-RPC `initialize`. The plugin self-declares any
  consumer surfaces and the required method/phase pair. Doctor compares the
  manifest against the plugin declaration. This keeps the CLI language-blind:
  the CLI does not know what `rust-implications` means.
- Preserve the current #1742 behavior for manifest method/phase footguns:
  miswired consumers fail with a fix hint.

Rust v1 evidence:

- Current `cmd_doctor.rs` already implements TOML parse, command resolution,
  imports warning, oracle locatability warning, and consumer-surface method/phase
  validation.
- The implementation work is mostly refactoring that code into a reusable
  `doctor` module and adding mode-aware severity.

### 2. Dependency Proof State Consistency

Substrate check names:

- `proof.dependency_resolver.available`
- `proof.dependency_pool.stable`

Mechanism:

- Treat dependency proof resolution as configured substrate wiring, not a best
  effort optimization. If a resolver is configured and cannot spawn, returns an
  unsupported required method, returns malformed proof entries, or closes without
  response, strict doctor fails closed. This is the doctor-facing version of
  #1766.
- Stage dependency proofs through the configured RPC resolver into scratch
  directories. Do not inspect package-internal `.proof` paths. Proof bytes cross
  the RPC seam; the CLI may hash and stage those bytes because they are now
  normalized proof data.
- In release-gate mode, stage the dependency proof pool twice from a clean
  scratch state with the same target, environment, and resolver config.
- For each staged proof, record:
  - label reported by the resolver
  - expected CID, if present
  - derived BLAKE3-512 CID of proof bytes
  - byte length
  - byte hash
  - destination filename
- Compare the two canonical proof sets. The proof pool is stable only if the
  sorted set of derived CIDs and byte hashes is identical. Expected CID mismatch
  remains an immediate hard fail.
- Compare the final self-check `.sugar/imports` pool against the release-gate
  staged proof set before mint/prove and again after prove. This extends #1755:
  #1755 catches mid-run mutation; doctor catches clean/warm pool variance before
  the K claim is published.
- A cheap standalone doctor can still report the current `.sugar/imports`
  fingerprint, but that fingerprint is only a receipt. It is not sufficient for
  v1 because #1774 is a reproducibility bug, not just an observed directory hash.

Rust v1 evidence:

- `cmd_self_check.rs` already snapshots imports filenames and fails on mid-run
  mutation.
- `stage_rpc_dependency_proofs_to_imports` already validates expected CID
  against derived bytes.
- `kit_dispatch::resolve_dependency_proofs` currently records diagnostics and
  returns `Ok(None)` for several resolver failures. Strict doctor and strict
  self-check must turn configured resolver absence into a hard fail.

### 3. Oracle Host Readiness and Engagement

Substrate check names:

- `oracle.requested`
- `oracle.host.locatable`
- `oracle.host.ready`
- `oracle.host.engaged`
- `oracle.resolution.converged`

Mechanism:

- Doctor should distinguish "oracle not requested" from "oracle requested but
  unavailable." If the oracle is not requested in structural mode, absence is
  not a failure.
- If the oracle is requested in strict or release-gate mode, locatability is a
  hard check. The adapter must name the configured host binaries and environment
  inputs.
- Add an actual readiness probe. Locating binaries is not enough. The v1 Rust
  adapter should spawn or connect to `sugar-linkerd`, verify the host can
  start, and perform the cheapest available request that proves the host is not
  inert. If no clean health RPC exists yet, the first implementation can expose
  one in linkerd rather than encoding rust-analyzer behavior in the CLI.
- Self-check already has convergence logic over `(attempted, resolved)` and
  fails if `--oracle` requested but the oracle resolves zero attempted sites.
  Doctor should move the infrastructure failure earlier and name it as
  `oracle.host.ready`, while self-check keeps the convergence proof as
  `oracle.resolution.converged`.
- If the oracle is requested and the host cannot start, fail closed immediately.
  That is #1763.

Rust v1 evidence:

- Existing `cmd_doctor::check_oracle_wiring` only warns and only checks binary
  locatability.
- `sugar-walk::ra_oracle` and `ra_daemon_client` already contain the actual
  host/session path. The design should expose a language-adapter readiness
  probe rather than making `cmd_doctor` understand rust-analyzer semantics.

### 4. Panic Annotation and Residue Consistency

Substrate check names:

- `panic_annotations.manifest.parse`
- `panic_annotations.keys.unique`
- `panic_annotations.census.joinable`
- `panic_annotations.proven_site_collision`
- `panic_annotations.bundle_propagation`

Mechanism:

- Standalone structural doctor parses target-local annotation manifests and
  checks shape and duplicate keys. For Rust v1 that is `.sugar/residue.toml`,
  but the doctor check name is panic annotation consistency, not Rust residue.
- Runtime doctor, called from self-check after mint/prove has a current panic
  census, reuses the fail-closed join logic from #1775:
  - stale annotation key fails
  - duplicate key fails
  - annotation for a proven site fails
  - malformed annotation fails
- The check result should include counts by status/category/tier so the health
  summary can say whether remaining unproven sites are named.
- #1773 is the next propagation layer. Once annotations become proof-bundle
  mementos, doctor should validate both target-local annotations and loaded
  dependency annotation mementos using the same normalized key
  `(bundle,file,line,callee)` or whatever exact key the proof layer stores.
- Annotation propagation must not change K. It enriches the panic census; it
  does not discharge proof obligations.

Rust v1 evidence:

- Rust kit emits `panic-site-annotation` diagnostics from
  `.sugar/residue.toml`.
- `cmd_self_check::panic_census` already fails closed on stale annotations,
  duplicates, and proven-site collisions when joining diagnostics.

### 5. No-Silent-Failure Aggregation

Substrate check names:

- `floor.silently_dropped.zero`
- `floor.false_pass.zero`
- `floor.dropped_sites.empty`
- `floor.panic_census.named`
- `floor.total_callsites.nonzero`
- `floor.discharge_split.present`

Mechanism:

- Doctor aggregates floor evidence already produced by self-check and prove
  instead of inventing another interpretation layer.
- Runtime doctor consumes the `SelfCheckScoreboard` and emits a single health
  section:
  - `silentlyDropped == 0`
  - `falsePass == 0`
  - `droppedSites == []`
  - `panicCensus` has no unnamed rows
  - `totalCallsites > 0`
  - oracle requested implies engaged and converged
  - dependency proof pool stable for the current mode
- Any hard-floor violation fails closed. These are product invariants, not
  advisory warnings.
- Human output should preserve readable per-site reasons. JSON output should be
  stable enough for CI golden diffs.

Rust v1 evidence:

- `cmd_self_check::run` already fails on `silentlyDropped > 0`, `falsePass > 0`,
  and requested oracle with attempted sites but no engagement.
- `prove_project` already refuses `totalCallsites == 0`.
- The missing piece is one report that correlates these separate failures with
  doctor configuration health and release readiness.

## Open Questions Answered

### Where Does Doctor Run?

Both.

- Standalone `sugar doctor --target ...` stays the human and CI diagnostic.
- Self-check calls the same engine as preflight for configuration, resolver, and
  oracle readiness.
- Self-check calls it again as runtime/finalization for proof-pool stability,
  annotation-to-census consistency, and floor aggregation.

The split matters because some checks are only knowable before mint, while
others require the current minted/proven census.

The release-gate `sugar doctor` validates infrastructure independently of
`sugar self-check`. Both must pass for v1 release tagging. They are not
chained by default; the v1 release script runs doctor plus self-check for both
`libsugar` and `sugar-cli` and tags only if all four commands are green.

### What Is the Failure Mode?

Fail closed for anything that can invalidate a proof claim.

Hard fail:

- invalid config or manifest
- missing/non-executable configured plugin command
- consumer surface method/phase mismatch
- configured dependency resolver unavailable or protocol-incompatible
- dependency proof byte/CID mismatch
- release-gate dependency proof pool instability
- requested oracle host unavailable
- requested oracle does not engage/converge
- stale/duplicate/proven-site panic annotation
- `silentlyDropped > 0`
- `falsePass > 0`
- nonzero dropped sites
- zero callsites

Warn only when the feature is not requested and no proof claim depends on it,
such as no oracle wiring in structural mode with no oracle request.

### How Should Dependency Proof Determinism Be Checked?

Use re-stage comparison for the release gate. Hashing `.sugar/imports` is
useful as an evidence receipt, but it is not enough to prove reproducibility.

The release gate should perform two clean RPC staging passes and compare the
canonical proof set by derived CID and byte hash. Then self-check should prove
against exactly that staged set and assert it remains unchanged through mint and
prove. This directly addresses #1774 because the K=14/K=21 split is about
different proof pools producing different scoreboards from the same source.

### What Is the v1 Release Gate?

Rust v1 is taggable when this command class is green on clean and warm roots:

```sh
sugar doctor --target implementations/rust/sugar-cli --release-gate --oracle --json
sugar self-check --target implementations/rust/sugar-cli --oracle --json
sugar doctor --target implementations/rust/libsugar --release-gate --oracle --json
sugar self-check --target implementations/rust/libsugar --oracle --json
```

Release readiness means:

- doctor hard checks pass
- dependency proof pool is byte-stable across clean staging passes
- self-check hard floors pass
- K is reproducible across clean and warm roots
- remaining panic census rows are named as `proven`, `residue`, or `unproven`
  with category/tier evidence

Then the v1 claim can say: Rust self-check is sound, residue is named, K is
reproducible, and the substrate health gate is green.

## Implementation Shape

Suggested code organization:

- Extract `cmd_doctor` internals into a reusable module, for example
  `doctor::{DoctorMode, DoctorContext, DoctorReport, DoctorCheck}`.
- Keep `cmd_doctor.rs` as argument parsing and output.
- Add preflight call sites from `cmd_self_check.rs`.
- Add runtime/finalization call that accepts the `SelfCheckScoreboard` and the
  staged dependency proof pool evidence.
- Add a kit-adapter health probe trait for host/oracle readiness so the CLI
  depends on substrate checks, not rust-analyzer names.
- Refactor dependency proof staging so strict mode can distinguish optional
  absence from configured resolver failure.
- Preserve existing test coverage and add focused regression tests for each
  hard-fail domain before implementation.

### Testing Discipline

Each hard-fail condition in the failure-mode list requires a red discrimination
test before implementation. Tests pair a positive case where valid
configuration passes with a negative case where a specific corruption fails
closed and names the corruption. This mirrors #1750 fail-closed extraction,
#1755 mid-run mutation guard, and #1775 residue annotation join. The tests are
the floor; implementation follows them.

## Questions Surfaced While Drafting

1. The config format needs a machine-readable way to tell doctor whether a
   dependency proof resolver is required or merely optional for the target. The
   current resolver path can degrade to diagnostics plus empty proof set.
2. The oracle readiness probe needs a substrate RPC shape. A dedicated
   `health`/`ready` method is cleaner than asking doctor to know rust-analyzer
   protocol details. #1777 tracks the substrate host readiness RPC method.
3. Runtime doctor needs access to `SelfCheckScoreboard`. Some scoreboard structs
   are currently private to `cmd_self_check.rs`; making the report reusable will
   require a small module boundary cleanup.
4. Annotation consistency has two phases: structural manifest checks can run
   before mint, but stale/proven-site collision checks require the current panic
   census. The design should represent both rather than pretending standalone
   doctor can prove census consistency without mint/prove.
5. The release gate needs a bounded runtime mode. Two clean dependency staging
   passes are acceptable for release, but likely too expensive for every local
   structural doctor run.
6. The implementation should file focused follow-ups for the release-gate mode
   boundary and `SelfCheckScoreboard` module cleanup once this design is merged.

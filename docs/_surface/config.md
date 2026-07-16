# Configuration & Knobs

This document maps the real configuration surface for Sugar: files that users and contributors tune, environment variables that affect behavior, feature flags, and CLI knobs.

---

## 1. Workspace Solver Portfolio: `.sugar/config.toml`

**What it is:** Central configuration for the Sugar workspace specifying which SMT solvers to use, their execution order, and IR-compiler backends.

**Where:** `/Users/tsavo/provekit/.worktrees/sugar-20260628/.sugar/config.toml`

**Audience:** End-user, integrator, contributor

**Priority:** P0 (blocks proof verification if misconfigured)

**What's configured:**

- **Solver portfolio** (field `solvers.portfolio`): ordered list of solver identifiers to invoke. Default: `["maude", "z3", "cvc5", "vampire", "coq", "lean"]`
  - Mode: `first-wins` (stops at first definitive verdict; absent solvers gracefully return `Undecidable`)
  - Alternative mode (per spec): `consensus`, `consensus-coverage_required` (v2 protocol)

- **Per-solver configuration** blocks (e.g., `[solvers.z3]`, `[solvers.maude]`):
  - `binary` (string): executable name or path (resolved via PATH)
  - `ir_compiler` (string): IR dialect to compile down to for this solver (`smt-lib-v2.6`, `maude`, `coq`, `lean`)
  - `flags` (array): command-line arguments (e.g., `z3` uses `["-smt2", "-in"]`)
  - `timeout_seconds` (integer): per-solver timeout before returning `Undecidable`
  - `version` (string): version constraint (e.g., `"4.x"` for z3) used for solver provenance in mementos
  - **Maude-specific:** `ceta_gate`, `ceta_binary`, `termination_prover`, `confluence_checker`
  - **Lean-specific:** `lake_project` (path to Lean Lake project root)

- **Kit aliases** (array `[[kits]]` entries): logical names for language/surface pairs
  - `alias` (string): shorthand (e.g., `"rust"`)
  - `project` (string): filesystem path relative to repo root
  - `surface` (string): language surface (`rust`, `csharp`, `clr-bytecode`)
  - `lang` (string): language identifier

**Example:** See actual file at path above; Maude has 30-second timeout, Z3 is the primary SMT solver.

**Existing docs:** `protocol/specs/2026-05-02-multi-solver-protocol-v2.md` (solver composition rules); `docs/contributing/build.md` (setup instructions)

---

## 2. Library Concept Bindings: `.sugar/library-bindings.json`

**What it is:** Maps semantic concept CIDs to language-specific library implementations.

**Where:** `/Users/tsavo/provekit/.worktrees/sugar-20260628/.sugar/library-bindings.json`

**Audience:** Integrator, contributor

**Priority:** P1 (enables concept-to-implementation resolution for cross-language composition)

**What's configured:**

- `language` (string): language for this binding map (e.g., `"rust"`)
- `bindings` (object): key-value map where:
  - **Key:** concept CID (e.g., `"concept:sql-connection-open"`)
  - **Value:** implementation identifier (e.g., `"rust-rusqlite"`)

**Purpose:** Allows Sugar to resolve which library realizations satisfy a given concept contract during cross-language proof composition.

**Existing docs:** `docs/contributing/writing-a-lift-adapter/` tutorial series (implicit in adapter steps)

---

## 3. Release Artifact Manifest: `sugar-release.toml`

**What it is:** Declarative manifest pinning which binaries to ship and their supply-chain dependencies.

**Where:** `/Users/tsavo/provekit/.worktrees/sugar-20260628/sugar-release.toml`

**Audience:** Integrator, contributor

**Priority:** P0 (gates release automation; produces the `binaryCid` admission pin)

**What's configured:**

- `version` (string): semantic version of the release
- `[[artifact]]` array: each shipping binary
  - `name` (string): display name (e.g., `"sugar"`)
  - `path` (string): build output path relative to manifest dir (e.g., `"implementations/rust/target/release/sugar"`)
- `[dependencies]` section:
  - `lockfile` (string): Cargo.lock path for supply-chain total accounting (all transitive deps)
- `[coverage]` section:
  - `cargo_manifest` (string): workspace Cargo.toml path
  - `exclude` (array): binaries in the workspace that are NOT shipped (test/dev/RPC bins)

**Gate behavior:** `sugar package release --manifest sugar-release.toml` content-addresses each artifact and dependency vector, producing a `PackageReleaseReceipt` (`binaryCid`). The receipt is re-verified by CI gates; any missing/excluded artifact or locked-dep drift causes the gate to fail.

**Existing docs:** `docs/plans/2026-06-05-docs-refresh.md` (mentions release process); `docs/contributing/release-process.md`

---

## 4. Per-Project Kit Configuration: `.sugar/config.toml` (in individual kits)

**What it is:** Language-specific and project-specific lift surface declarations.

**Where:** Each kit directory under `implementations/rust/`, `implementations/python/`, `examples/*/`, etc., has a `.sugar/config.toml`

**Audience:** Contributor, integrator

**Priority:** P1 (required for `sugar mint` to work on a kit)

**What's configured:**

- `[[plugins]]` array: each lift surface that the kit publishes
  - `name` (string): human-readable surface name
  - `surface` (string): authoring surface identifier (e.g., `"rust-contracts"`, `"rust-fn-contracts"`, `"rust-bind"`)
  - `layer` (string, optional): grouping/layer (e.g., `"library-bindings"`)
  - `emit` (string, optional): output route (e.g., `"ir-document"`)

- `[platform_profile]` section:
  - `language` (string): language (e.g., `"rust"`, `"python"`)
  - `family` (string): concept family CID (e.g., `"concept:family:sugar"`, `"concept:family:rust-std"`)
  - `library` (string): semantic library identifier (NOT the Cargo crate name; used to tag emitted contracts)
  - `version` (string): library semantic version (all minted contracts carry this tag)

**Example shape:**
```toml
[[plugins]]
name = "rust-fn-contracts"
surface = "rust-fn-contracts"
emit = "ir-document"

[platform_profile]
language = "rust"
family = "concept:family:sugar"
library = "sugar-cli"
version = "0.4.0"
```

**Existing docs:** `docs/self-application/KIT-SETUP-AND-SELF-APPLICATION.md` (full runbook with real examples)

---

## 5. Lift Surface Manifests: `.sugar/lift/<surface-name>/manifest.toml`

**What it is:** Dispatch config for each lift surface, specifying the lifter binary and invocation method.

**Where:** One manifest per surface, e.g., `.sugar/lift/rust-fn-contracts/manifest.toml`

**Audience:** Contributor, integrator

**Priority:** P1 (silent failure if misconfigured; produces empty-set attestation)

**What's configured:**

- `name` (string): surface name (typically matches parent directory)
- `command` (array): binary + args to invoke the lifter (e.g., `["../target/debug/sugar-walk-rpc", "--rpc"]`)
- `working_dir` (string): directory from which `command` is resolved (relative paths; "." = project dir)
- `method` (string, optional): JSON-RPC method for this surface (e.g., `"sugar.plugin.lift_implications"`)
- `phase` (string, optional): execution phase tag (e.g., `"consumer"` for implication surfaces)

**Critical footgun:** Relative paths in `command` are resolved from `working_dir`, which is typically the PROJECT directory. Copy-pasting a manifest from a shallow kit into a deep example dir requires re-counting `..` to reach the shared `implementations/rust/target/` directory. Symptom: "lifter binary not found: producing empty-set attestation".

**Existing docs:** `docs/self-application/KIT-SETUP-AND-SELF-APPLICATION.md` §2 (THE FOOTGUN section)

---

## 6. Cross-Language Conformance Fixtures: `conformance/fixtures.toml`

**What it is:** Pinned test vectors; every kit must derive identical BLAKE3-512 CIDs for each fixture.

**Where:** `/Users/tsavo/provekit/.worktrees/sugar-20260628/conformance/fixtures.toml`

**Audience:** Contributor (kit developers)

**Priority:** P1 (conformance gate for multi-language implementations)

**What's configured:**

- `catalog_version` (string): protocol catalog version (e.g., `"v1.6.6-2026-05-26"`)
- `catalog_cid` (string): BLAKE3-512 CID of the full fixture catalog
- `[[fixture]]` array: each test vector
  - `name` (string): fixture identifier (e.g., `"eq_atomic"`)
  - `capability` (string): feature being tested (e.g., `"ir.formula.jcs"`, `"claim.bridge.v1_4.jcs"`)
  - `description` (string): human-readable description
  - `jcs` (string): JCS-canonicalized JSON of the fixture
  - `hash` (string): expected BLAKE3-512 CID

**Update process:** Adding a new fixture requires:
1. Define it in the Rust kit (canonical reference)
2. Compute its JCS and CID
3. Record name + CID here
4. All other kits must independently derive the same CID

**Existing docs:** Inline in `conformance/fixtures.toml` (comments at lines 11-15)

---

## 7. Rust Workspace Features: `implementations/rust/Cargo.toml`

**What it is:** Cargo feature flags controlling compilation and link-time behavior.

**Where:** `/Users/tsavo/provekit/.worktrees/sugar-20260628/implementations/rust/Cargo.toml` (workspace-level)

**Audience:** Contributor

**Priority:** P2 (optional; most projects work without features)

**What's configured:**

- **workspace.package:** shared metadata (version, license, authors, edition)
- **workspace.dependencies:** pinned versions of key deps:
  - `blake3` = 1.5 (hashing)
  - `ed25519-dalek` (signatures)
  - `serde` + `serde_json` (IR serialization)
  - `syn` (AST walking for lifters)
  - `toml` (config file parsing)
  - `rayon` (parallelism)

- **Per-crate features** (in individual Cargo.toml files, e.g., `sugar-walk/Cargo.toml`):
  - `sugar-walk`: `default = ["rpc"]`, feature `rpc = []` (gates RPC code)
  - `sugar-canonicalizer`: `default = []`, feature `pure-blake3 = ["blake3/pure"]` (gates Blake3 implementation selection)

**Release profile:** `[profile.release]` sets `opt-level = 3`, `lto = false`, `debug = false`

**Existing docs:** `docs/contributing/build.md`

---

## 8. Build Broker Adapters: `bin/sugarbin`, `bin/bcargo`, and `bin/brun`

**What it is:** `bin/sugarbin` owns artifact resolution and local/battleaxe execution. `bcargo` and `brun` are thin compatibility adapters that select `--host bx`.

**Where:** `/Users/tsavo/provekit/.worktrees/sugar-20260628/bin/bcargo`

**Audience:** Contributor (macOS developers targeting Linux CI parity)

**Priority:** P1 (build parity; wrong config produces stale binaries)

**Environment variables:**

| Variable | Default | Effect |
|----------|---------|--------|
| `BCARGO_REMOTE_HOST` | `battleaxe` | SSH host alias (must be in `~/.ssh/config`) |
| `BCARGO_REMOTE_ROOT` | `/home/tsavo/remote/sugar-bcargo-<checkout-hash>` | Remote scratch root; per-checkout isolation via shasum of repo path |
| `BCARGO_CLEAN_REMOTE_ROOT` | `never` | Cleanup after remote cargo: `never`, `success`, or `always` |
| `BCARGO_CLEAN_REMOTE_ROOT_UNSAFE` | `0` | Set to 1 to allow cleanup outside `/home/tsavo/remote/sugar-bcargo-*` (safety guard) |
| `BCARGO_SSH` | `ssh` | SSH binary to use |
| `BCARGO_RSYNC` | `rsync` | rsync binary to use |

Battleaxe ambient execution never provisions dependencies. The caller owns the
ambient host. Select a declared immutable environment or named task for managed
dependencies, for example `bin/sugarbin run --host bx --task python-unit -- -q`
or `bin/sugarbin run --host bx --env docker:solver-z3 -- z3 --version`.

**CLI options (bcargo-specific):**

- `--sync-bin NAME`: After successful cargo command, copy `target/<profile>/NAME` back to local machine
- `--sync-bins LIST`: Comma-separated form of `--sync-bin`
- `--help`: Show usage

**Usage:** `bin/bcargo --sync-bin sugar build --release` (builds remotely, syncs the compatible binary back)

**Existing docs:** `docs/build-execution.md` and inline `--help` output.

---

## 9. Rust Lifter & Walker Environment Variables

**What it is:** Per-component runtime behavior toggles for AST walking, oracle resolution, and compilation.

**Where:** Read by individual Rust crates (sugar-walk, sugar-lift, etc.)

**Audience:** Contributor, operator

**Priority:** P1 (wrong values silently produce incomplete lifts)

**Variables:**

| Variable | Effect | Example |
|----------|--------|---------|
| `SUGAR_RESOLVE_ORACLE` | Selects AST-resolution oracle: `"rust-analyzer"` or empty (none). Default: none (fast path). | `SUGAR_RESOLVE_ORACLE=rust-analyzer` enables full-source symbol resolution for Rust code |
| `SUGAR_RUST_ANALYZER` | Explicit path to rust-analyzer binary (overrides `rustup which`) | `SUGAR_RUST_ANALYZER=/path/to/ra` |
| `SUGAR_ORACLE_READY_TIMEOUT_MS` | How long to wait for oracle readiness (ms) | Default: ~1000ms |
| `SUGAR_CAPTURE_REQUEST` | Capture JSON-RPC request for debugging | Set to any value to enable |
| `SUGAR_PLUGIN_STDERR` | Redirect plugin stderr to file | `SUGAR_PLUGIN_STDERR=/tmp/plugin.log` |
| `SUGAR_IR_COMPILER_TIMEOUT_SECS` | Timeout for IR compiler invocation (seconds) | Default: per-solver config (e.g., 30s for z3) |
| `SUGAR_SOLVER_TIMEOUT_SECS` | Override per-solver timeout (seconds) | Overrides `.sugar/config.toml` values |
| ~~`SUGAR_WITNESS_DISCHARGE*`~~ | **Retired (#3860 / #3809 step 3).** Not a config channel. Package recompute uses typed `WitnessDischargeContext` (project_dir + resolvers) only. Showcase lie scripts may still set `SUGAR_WITNESS_DISCHARGE_<TOOL>` as process pollution; production never reads or writes it. | — |
| ~~`SUGAR_WITNESS_RESOLVERS`~~ | **Retired (#3809 step 3).** Typed `WitnessDischargeContext.resolvers` only. | — |
| ~~`SUGAR_WITNESS_PROJECT_DIR`~~ | **Retired (#3809 step 3).** Typed `WitnessDischargeContext.project_dir` only. | — |
| `SUGAR_WITNESS_SIGNER_SEED` | Ed25519 seed for witness signing (hex, 32 bytes) | `0x42424242...` (64 hex chars) |
| `SUGAR_VERIFY_SIGNER_KEY` | Public key for proof verification (hex) | Used in `sugar verify` |
| `SUGAR_VERIFY_SIGNER_KEY_FILE` | Path to public key file (PEM format) | Alternative to `SUGAR_VERIFY_SIGNER_KEY` |
| `SUGAR_RA_ORACLE_BIN` | Path to the rust-analyzer oracle binary (`sugar-ra-oracle`) | Used by the Rust lift pipeline's method-call resolution (daemon-2 repoint; was `SUGAR_LINKERD_BIN`) |
| `SUGAR_RA_ORACLE_LOG` | Log file for the rust-analyzer oracle daemon | `/tmp/ra-oracle.log` |
| `SUGAR_RA_ORACLE_SOCKET` | Unix socket for the rust-analyzer oracle RPC | `/tmp/ra-oracle.sock` |
| `SUGAR_CONTRACTS_RPC` | JSON-RPC URL for contract resolution | `http://localhost:9999` |
| `SUGAR_CONTRACTS_RPC_TARGET_DIR` | Target directory for RPC responses | `/tmp/contracts` |
| `SUGAR_COMPONENT_PATH` | Component search path (colon-separated) | `/path1:/path2` |
| `SUGAR_LEAN_PROJECT` | Lean Lake project root | `/home/user/lean-mathlib` |
| `SUGAR_VERIFY_SAMPLE` | Sample N proofs for verification (diagnostic) | E.g., `"10"` to sample 10 of N proofs |
| `SUGAR_BIN` | Path to sugar CLI binary | Used by pre-commit hooks; default: `"sugar"` on PATH |
| `SUGAR_REPO_ROOT` | Repository root (for Python kit bootstrap) | Set by phase5py drivers |
| `PYTHON` | Python interpreter to use (fallback) | Default: `sys.executable` or `"python3"` |

**Subsetting for Python kit:**

| Variable | Effect |
|----------|--------|
| `SUGAR_PY_PACKAGE_ACCOUNTING_MODE` | Lift mode: empty, `"strict"`, or other | 
| `SUGAR_PY_PACKAGE_ACCOUNTING_LOCI` | Scope loci: empty, `"broad"`, or other |
| `SUGAR_PY_PACKAGE_ACCOUNTING_SAMPLE_LIMIT` | Limit samples (integer) |
| `SUGAR_LEAN_SOURCE` | Enable Lean source oracle (for Python) | Set to `"1"` |

**Existing docs:** Scattered in docstrings; no centralized reference doc

---

## 10. CLI Flags and Subcommands: `sugar` CLI

**What it is:** User-facing command-line interface with 20+ subcommands and 100+ flags.

**Where:** `implementations/rust/sugar-cli/src/main.rs` (CLI definition via clap)

**Audience:** End-user, integrator

**Priority:** P0 (primary user interface)

**Common flags (global across subcommands):**

- `--json`: Output structured JSON instead of human text
- `--quiet`: Suppress non-error output

**Major subcommands:**

| Subcommand | Purpose | Key Flags |
|---|---|---|
| `prove` | Run six-stage verifier on proofs in a directory | `--project`, `--z3`, `--with`, `--artifact`, `--proof`, `--policy`, `--emit-witnesses` |
| `verify` | End-to-end verify: lift contracts, discharge via solver, mint witness, emit receipt | `--project`, `--z3`, `--with`, `--report` |
| `mint` | Dispatch configured lift surfaces and write `.proof` envelope | `--project`, `--out`, `--manifest`, `--kit` |
| `lift` | Dispatch lift surface and write ProofIR JSON (no `.proof` envelope) | `--project`, `--output`, `--kit` |
| `diff` | Compare two proof sets: report behavior changes, additions, removals | `--old`, `--new`, `--json` |
| `implicate` / `imp` | Mint an implication memento (antecedent → consequent via Z3) | `--from`, `--to`, `--z3`, `--with` |
| `dump` | Pretty-print `.proof` file structure: members, bodies, signatures | `--proof`, `--json` |
| `hash` | Compute BLAKE3-512 CID of a file or stdin | `--algo`, `--canonical` |
| `recognize` | Scan source for sugar binding shapes; emit tags (reverse of `materialize`) | `--source`, `--kit` |
| `emit` | Generate target-framework test artifacts from contracts | `--target`, `--language`, `--from-proof` |
| `bind` | Cluster and scope concepts: lift, cluster, name, scope, identify, realize, witness | `--rewrite`, `--mode`, `--target-language` |
| `compose` | JSON-RPC subprocess transport for contract composition protocol | (stdin/stdout mode; no flags) |
| `init` | Initialize a project: create `.sugar/`, sample contract, GitHub Action | `--project` |
| `doctor` | Validate kit config/manifest wiring before running mints (catch manifest-path footgun) | `--project` |
| `package` | Inspect package artifacts and supply-chain receipt inputs | `--manifest`, `--artifact` |
| `release-gate` | Run v1 release health gate; emit evidence receipt | `--manifest` |
| `self-check` | Run deterministic self-application scoreboard (prove Sugar over itself) | (no major flags) |
| `materialize` | Resolve source-oracle bodies by reference | `--proof`, `--output` |
| `version` | Print CLI version | (no flags) |

**Plugin flags (used by many subcommands):**

- `--plugin <kind>:<source>`: Load a plugin (canonical form)
- `--sugar <source>`: Alias for `--plugin sugar:<source>`
- `--loss-fn <source>`: Alias for `--plugin loss-function:<source>`
- `--lifter <source>`: Alias for `--plugin lift:<source>`
- `--strict-plugins`: Promote plugin load failures to refusals
- `--plugin-registry-out <path>`: Write PluginRegistryMemento to file

**Solver flags (where applicable):**

- `--z3 <path>`: Path to z3 binary (default: `"z3"` on PATH)
- `--with <source> ...`: Additional solver to try (repeatable; e.g., `--with cvc5`)
- `--real-solver`: Force use of real solver (vs. mock for testing)

**Exit codes:**

- `0` = success
- `1` = verification failure (formula refuted or policy violated)
- `2` = user error (bad args, file not found)
- `3` = solver failure (z3 unavailable, timeout, error)

**Existing docs:** `docs/contributing/overview.md` (routing table for subcommands); `README.md` (quick start); in-code docstrings (run `sugar --help`)

---

## 11. Conformance Test Harness: Cargo Test Fixtures

**What it is:** Integration tests pinning canonicalization, fixture derivation, and kit conformance.

**Where:** Individual Cargo test suites in each kit (e.g., `sugar-canonicalizer/tests/`, `sugar-claim-envelope/tests/`)

**Audience:** Contributor

**Priority:** P1 (conformance gate; prevents silent CID drift)

**Environment variables for testing:**

- `SUGAR_CONFORMANCE_REASON`: If set, test failure messages include extended diagnostic (causal chain)
- `RUST_LOG`: Tracing log level (e.g., `RUST_LOG=debug cargo test`)

**Configuration files:**

- `conformance/fixtures.toml` (see §6 above)
- Per-kit fixture files (e.g., `sugar-claim-envelope/tests/bridge_v14_roundtrip.rs` with pinned test data)

**Existing docs:** Inline in `conformance/fixtures.toml`; `docs/contributing/writing-a-kit/01-conformance-first.md`

---

## 12. Python Kit Configuration: `sugar-lift-py-tests/src/sugar_lift_py_tests/lsp.py`

**What it is:** Python lift surface configuration and accounting modes.

**Where:** `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lsp.py`

**Audience:** Contributor (Python kit developers)

**Priority:** P2 (affects Python lift coverage and telemetry)

**What's configured (via env vars; see §9 above):**

- `SUGAR_PY_PACKAGE_ACCOUNTING_MODE`: Lift strategy mode
- `SUGAR_PY_PACKAGE_ACCOUNTING_LOCI`: Scope selection (e.g., `"broad"` for exhaustive accounting)
- `SUGAR_PY_PACKAGE_ACCOUNTING_SAMPLE_LIMIT`: Cap on samples to process

**Existing docs:** Comments in the lsp.py source file

---

## 13. IR Compiler Protocol Dispatch: Per-Solver Compiler Selection

**What it is:** Mapping from solver to IR dialect compiler (e.g., z3 → smt-lib-v2.6, coq → coq, lean → lean).

**Where:** Configured in `.sugar/config.toml` (field `[solvers.<name>.ir_compiler]`); implementations in `implementations/rust/sugar-ir-compiler-*/`

**Audience:** Integrator, contributor

**Priority:** P1 (wrong compiler means mismatched dialect; formula fails to verify)

**Dialect options:**

| Dialect | Compiler Crate | Target Solver | Protocol Version |
|---------|---|---|---|
| `smt-lib-v2.6` | `sugar-ir-compiler-smt-lib` | z3, cvc5, vampire | v2 (OpacityManifest support) |
| `maude` | `sugar-ir-compiler-maude` | Maude 3.x | v2 |
| `coq` | `sugar-ir-compiler-coq` | Coq 8.x (`coqc` binary) | v2 |
| `lean` | `sugar-ir-compiler-lean` | Lean 4.x + mathlib (`lake` binary) | v2 |

**Existing docs:** `protocol/specs/2026-05-02-multi-solver-protocol-v2.md` §1 (IR-compiler tags); `protocol/specs/2026-05-02-ir-compiler-protocol-v2.md` (compiler protocol)

---

## Open Questions

1. **Sugar-specific config in home directory:** Is there a `~/.config/sugar/` or `~/.sugar/` user-level config file for overriding defaults? Code search suggests per-workspace `.sugar/config.toml` only; no user-home fallback documented.

2. **Conformance mode vs. production mode:** Are there environment toggles or CLI flags that switch between "strict conformance verification" and "fast path" modes? Tests reference `SUGAR_CONFORMANCE_REASON` but unclear if this gates a mode or just enhances diagnostics.

3. **Witness oracle strategies:** The codebase references multiple witness resolvers (ci-log, local-test-run, etc.) but no single canonical list or configuration file that declares available strategies. Where is the strategy registry?

4. **LSP-specific config:** Language server (`sugar-lsp`, `sugar-lsp-rust`) has no visible `.sugar/` config; does it read from parent project `.sugar/config.toml` or use separate settings?

5. **Plugin discovery:** Code references `sugar-plugin-loader` and plugin manifests but unclear if plugins are discovered from `.sugar/plugins/` or if they must be declared in `.sugar/config.toml`. Full plugin registration protocol unclear.

6. **Cache/artifact storage:** Where does Sugar store intermediate build artifacts, downloaded dependencies, and cached proof objects? No visible `.sugar/.cache/` or similar documented.

7. **GitHub Actions integration:** `sugar init` mentions creating a GitHub Action; what env vars or config does that Action expect? Template location?

8. **Distributed verifier coordination:** resolved -- the `sugar-linkerd` daemon this question referred to never did cross-machine coordination (it was a per-project editor linker/prove daemon); it is retired (#3844 flipped the editor path to `sugar-lsp --in-process`; daemon-3-delete removed the crate). The one job it did that still needs a resident process, the rust-analyzer oracle, lives on in `sugar-ra-oracle` with no peer discovery -- it is a per-project subprocess, not a distributed service.

---

**Last updated:** 2026-06-28  
**Scope:** Configuration surface as of main @ 5b00979d9  
**Area:** Configuration & knobs (P0-P2)

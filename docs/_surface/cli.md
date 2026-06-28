# Sugar CLI Reference

This document maps the **user-facing and programmatic CLI surface** of Sugar: every binary, command, and entry point across the Rust, Python, and Java kits.

Sugar ships two kinds of CLIs:
1. **User CLI** (`sugar`): 20+ subcommands for proving, verifying, lifting, and composing contracts.
2. **Dispatch CLIs**: language-specific lifters, solvers, RPC services, and build wrappers.

---

## User CLI: `sugar`

**Binary:** `implementations/rust/sugar-cli/src/main.rs`  
**Package:** `sugar-cli`  
**Kind:** Primary user-facing CLI  
**Audience:** end-user  

The main entry point routing user requests into the Sugar proof ecosystem.

### Subcommands

#### prove
**Summary:** Six-stage verifier: load proofs, enumerate callsites, solve obligations, report.  
**Typical use:** `sugar prove [--z3 <path>] [--proof <file>] [--artifact <file>] [--policy <file>] [project]`  
**Key flags:**
- `--z3 <path>` — Path to Z3 binary (default: "z3" on PATH)
- `--proof <file>` — Package release proof/receipt
- `--artifact <file>` — Artifact bytes to verify
- `--policy <file>` — Consumer policy proof/receipt
- `--require-empirically-witnessed <string>` — Require promotion tier
- `--with <dirs...>` — Additional project directories
- `--json`, `--quiet` — Output formatting flags

**Exit codes:**
- 0 = success
- 1 = verification failure
- 2 = user error
- 3 = solver failure

**Documentation:** Covered in `docs/papers/01-whitepaper.md`, `docs/papers/02-bluepaper.md`

---

#### verify
**Summary:** Kit end-to-end verification: lift contracts, discharge via solver-dispatch table, mint signed witness, emit receipt.  
**Typical use:** `sugar verify <kit-path>`  
**Kind:** Keystone gate verb (issue #1405)  
**Key flags:**
- Kit-level verification, solver dispatch, witness minting
- Emits verification receipt (JSON + human-readable)

**Documentation:** `implementations/rust/sugar-cli/src/cmd_verify.rs` header; integration docs in `docs/papers/`

---

#### self-check
**Summary:** Run the deterministic self-application scoreboard.  
**Typical use:** `sugar self-check`  
**Kind:** Internal gate  
**Audience:** contributor, CI/CD

**Documentation:** `docs/self-application/` folder

---

#### diff
**Summary:** Behavior diff between two minted proof sets. Report contracts that changed CID (behavior moved), were added, or removed.  
**Typical use:** `sugar diff <proof-set-1> <proof-set-2>`  
**Exit code:** Nonzero when behavior moved or surface dropped.  
**Key flags:**
- `--json`, `--quiet`

**Documentation:** `docs/papers/03-substrate-not-blockchain.md`; `sugar diff` is "the no-vendor report" (thesis note: `project_sugar_diff_is_the_no_vendor_report.md`)

---

#### implicate / imp
**Summary:** Mint an implication memento (antecedent CID → consequent CID) via Z3.  
**Typical use:** `sugar implicate <antecedent-cid> <consequent-cid> [--z3 <path>]`  
**Short alias:** `sugar imp`  
**Key flags:**
- `--z3 <path>` — Z3 binary path

**Documentation:** Implication protocol in `protocol/specs/2026-05-09-contract-composition-protocol.md`

---

#### dump
**Summary:** Pretty-print a .proof envelope: members, bodies, signatures.  
**Typical use:** `sugar dump <proof-file>`  
**Kind:** Inspection utility  
**Audience:** end-user, contributor

**Documentation:** Proof file format in `protocol/specs/2026-04-30-proof-file-format.md`

---

#### hash
**Summary:** Compute the BLAKE3-512 self-identifying CID of a file (or stdin).  
**Typical use:** `sugar hash [file]` or `cat file | sugar hash`  
**Kind:** Utility  
**Audience:** end-user, integrator

**Documentation:** `protocol/specs/2026-04-29-correctness-is-a-hash.md`

---

#### recognize
**Summary:** Recognizer (protocol §4.2.5): scan source for shapes matching published sugar binding templates; emit tags.  
**Typical use:** `sugar recognize <source-file>`  
**Kind:** Reverse of `materialize` — fingerprint scanner  
**Audience:** contributor, integrator

**Documentation:** Binding protocol in protocol specs

---

#### init
**Summary:** Initialize a project: sugar.toml, .sugar/, sample invariant, GitHub Action.  
**Typical use:** `sugar init [project-dir] [--force]`  
**Key flags:**
- `--force` — Overwrite pre-existing files

**Documentation:** `docs/self-application/KIT-SETUP-AND-SELF-APPLICATION.md`

---

#### lift
**Summary:** Dispatch the configured lift surface and write ProofIR term JSON (no `.proof` envelope; use `mint` for that).  
**Typical use:** `sugar lift [project] [-o output.json]`  
**Key flags:**
- `-o, --output <path>` — Output file (default: stdout)
- `--identify-only` — Report native contract identities without full ProofIR lowering
- `--library-bindings` — Ask lifter for proof-producing library-sugar bindings
- `--report` — Print lifter's source-audit countdown
- `--report-summary` — With --report, print only source/factory summary
- `--visual` — Print source walk as ANSI green/red lines
- `--prove` — Append verifier discharge report
- `--z3 <path>` — Z3 for --report --prove
- `--with <dirs...>` — Additional project directories for --report --prove
- `--contract <string>` — Restrict --report to contracts matching this string

**Documentation:** `docs/contributing/writing-a-lift-adapter/03-emit-canonical-IR.md`; `implementations/rust/sugar-lift/README.md`

---

#### mint
**Summary:** Dispatch the lift-plugin protocol: spawn the configured plugin, write its `.proof`.  
**Typical use:** `sugar mint [project]`  
**Kind:** Proof minting, plugin spawning  
**Audience:** contributor, CI/CD

**Documentation:** Plugin protocol in `protocol/specs/`

---

#### emit
**Summary:** Emit target/framework test artifacts from neutral contract predicates.  
**Typical use:** `sugar emit [project]`  
**Kind:** Reverse direction of lift — code generation  
**Audience:** contributor

---

#### version
**Summary:** Print CLI version.  
**Typical use:** `sugar version [--json]`

---

#### compose
**Summary:** JSON-RPC subprocess transport for the canonical compose primitive.  
**Typical use:** Reads JSON-RPC requests on stdin, writes responses on stdout.  
**Key flags:**
- `--rpc` — Speak JSON-RPC (required)

**Protocol:** `protocol/specs/2026-05-09-contract-composition-protocol.md` §6.3  
**Audience:** integrator, CI/CD

**Documentation:** Contract composition protocol spec

---

#### bind
**Summary:** Bind concept contracts to source code: lift, cluster, name, scope, identify, realize, witness.  
**Typical use:** Implements the eight-verb pipeline (paper 20 §9) against arbitrary user code.  
**Key flags:**
- `--rewrite={annotate,canonical,invisible}`
- `--mode={witness,emitter,monitor,gate}`
- `--target-language=<lang>`

**Documentation:** Paper 20 (eight-verb pipeline)

---

#### materialize
**Summary:** Materialize source-oracle bodies by resolving real source by reference.  
**Typical use:** Opposite direction of `recognize`  
**Audience:** contributor, integrator

---

#### doctor
**Summary:** Validate a kit's config/manifest wiring before a run.  
**Typical use:** `sugar doctor [project]`  
**Purpose:** Catches missing binaries (the manifest-path footgun) before silent empty-set attestation.  
**Exit codes:**
- 0 = pass (warnings allowed)
- 2 = hard failure (invalid TOML or missing/non-executable binary)

**Documentation:** Manifest validation in kit setup docs

---

#### release-gate
**Summary:** Run the v1 release health gate and emit a release evidence receipt.  
**Typical use:** `sugar release-gate [project]`  
**Kind:** Release CI gate  
**Audience:** contributor, CI/CD

---

#### derive
**Summary:** Derive a concrete output from a lifted universe BV expression via Z3 model extraction.  
**Typical use:** `sugar derive [--from-proof <file> | --bv-expr <json>]`  
**Purpose:** Asks Z3 what the definition COMPUTES via `(get-value)`. Derived, not executed.  
**Example:** Flagship use case: `abs(Integer.MIN_VALUE) = -2147483648`, derived from lifted Math.abs body.  
**Audience:** researcher, contributor

---

## Cargo Subcommand: `cargo-sugar`

**Binary:** `implementations/rust/cargo-sugar/src/main.rs`  
**Package:** `cargo-sugar`  
**Kind:** Cargo subcommand plugin  
**Invocation:** `cargo sugar`  
**Audience:** end-user (Rust crate maintainer)  

**Summary:** Behavioral semver for Rust crates. Runs `sugar diff` against the last published version to detect breaking changes in behavior (not just API shape).

**Documentation:** Behavioral semver philosophy in `docs/papers/`

---

## Lifter & IR Compilers

### sugar-lift / cargo-sugar-lift

**Binaries:**
- `sugar-lift` — Direct invocation
- `cargo-sugar-lift` — Cargo plugin invocation (`cargo sugar-lift`)

**Package:** `sugar-lift`  
**Kind:** Lifter dispatcher  
**Audience:** integrator, CI/CD  

**Summary:** Walk a Rust workspace, run all registered adapters, mint signed contract mementos, bundle into a single `.proof` catalog.

**Typical use:**
```
sugar-lift [project] [-o output.json]
cargo sugar-lift
```

**Key flags:** (same as `sugar lift` subcommand)
- `-o, --output` — Output file
- `--identify-only` — Identity scan only
- `--report`, `--report-summary`, `--visual` — Reporting modes
- `--prove` — Append discharge report

**Documentation:** `implementations/rust/sugar-lift/README.md`; lift adapter tutorials in `docs/contributing/writing-a-lift-adapter/`

---

### IR Compilers

#### sugar-ir-smt-lib
**Binary name:** `sugar-ir-smt-lib`  
**Package:** `sugar-ir-compiler-smt-lib`  
**Kind:** IR compiler (subprocess)  
**Audience:** integrator, solver backend  

**Summary:** SMT-LIB v2.6 IR compiler. Lowers ProofIR to Z3/cvc5/bitwuzla compatible input.

**Typical use:** Dispatched from `sugar prove` / `sugar verify`  
**Documentation:** Compiler protocol in `protocol/specs/`

---

#### sugar-ir-coq
**Binary name:** `sugar-ir-coq`  
**Package:** `sugar-ir-compiler-coq`  
**Kind:** IR compiler (subprocess)  
**Audience:** researcher, contributor  

**Summary:** Compiles ProofIR to Coq formal-logic syntax.

---

#### sugar-ir-lean
**Binary name:** `sugar-ir-lean`  
**Package:** `sugar-ir-compiler-lean`  
**Kind:** IR compiler (subprocess)  
**Audience:** researcher, contributor  

**Summary:** Compiles ProofIR to Lean 4 formal-logic syntax.

---

#### sugar-ir-maude
**Binary name:** `sugar-ir-maude`  
**Package:** `sugar-ir-compiler-maude`  
**Kind:** IR compiler (subprocess)  
**Audience:** researcher, contributor  

**Summary:** Compiles ProofIR to Maude rewriting logic syntax.

---

## Language Server Protocols

### sugar-lsp
**Binary name:** `sugar-lsp`  
**Package:** `sugar-lsp`  
**Kind:** LSP server  
**Audience:** IDE integrators, editor plugins  

**Summary:** Generic Sugar language server providing IDE integration (diagnostics, hover, completions) for proof files and contracts.

**Typical use:** Spawned by editor extension per LSP protocol  
**Documentation:** LSP plugin tutorial in `docs/contributing/writing-an-LSP-plugin.md`

---

### sugar-lsp-rust
**Binary name:** `sugar-lsp-rust`  
**Package:** `sugar-lsp-rust`  
**Kind:** LSP server (Rust-specific)  
**Audience:** Rust IDE integrators  

**Summary:** Rust-specific language server extending base LSP with Rust AST walking and assertion recognition.

**Typical use:** Spawned by Rust IDE extension  
**Documentation:** Rust kit LSP in `implementations/rust/sugar-lsp-rust/`

---

## Test & Witness Services

### Rust Test Assertion Sweeper

#### coretests_sweep
**Binary name:** `coretests_sweep`  
**Package:** `sugar-lift-rust-tests`  
**Kind:** Test walker / sweeper  
**Audience:** contributor, CI/CD  

**Summary:** Walks Rust coretests (e.g., `std` library tests), lifts all `assert!` / `assert_eq!` assertions, produces total accounting report.

**Example output:** 6377 assertions, 74.8% discharged (as of main 5b00979d9)  
**Typical use:** Benchmarking coverage over Rust stdlib  
**Documentation:** `examples/rust-coretests-report/README.md`; `docs/self-application/ASSERTION-ACCOUNTING-LEDGER.md`

---

#### discharge_sweep
**Binary name:** `discharge_sweep`  
**Package:** `sugar-lift-rust-tests`  
**Kind:** Discharge reporter  
**Audience:** contributor, researcher  

**Summary:** Processes lifted assertions, invokes Z3 solver, reports coverage metrics and refutation certificates.

**Typical use:** Post-lift analysis, discharge metrics  
**Documentation:** Coverage audit reports in `docs/plans/2026-06-13-stdlib-unclassified-to-zero.md`

---

#### rust_test_assertions_rpc
**Binary name:** `rust_test_assertions_rpc`  
**Package:** `sugar-lift-rust-tests`  
**Kind:** RPC service  
**Audience:** contributor, CI/CD  

**Summary:** RPC server for test assertion discovery and walking.

**Typical use:** Dispatched by lifter over NDJSON  
**Documentation:** Lift RPC protocol in `protocol/specs/`

---

### Witness Services

#### witness_rpc
**Binary name:** `witness_rpc`  
**Package:** `sugar-lift-rust-cargo-test-witness`  
**Kind:** RPC server  
**Audience:** integrator, CI/CD  

**Summary:** Witness oracle RPC server. Resolves witness oracle requests (test runs, CI logs); provides witness body content-addressing.

**Purpose:** Mints signed witness packages + custom-evidence contracts from cargo-test runs  
**Typical use:** Dispatched by lifter from `sugar verify` / CI gate  
**Documentation:** Witness protocol in `protocol/specs/2026-05-09-contract-composition-protocol.md`

---

#### discharge_cli
**Binary name:** `discharge_cli`  
**Package:** `sugar-lift-rust-cargo-test-witness`  
**Kind:** CLI tool  
**Audience:** contributor, integrator  

**Summary:** Verifies proof discharges locally without RPC; used for hermetic testing.

**Typical use:** Local discharge verification, debugging  
**Documentation:** Hermetic testing in `docs/self-application/KIT-SETUP-AND-SELF-APPLICATION.md`

---

## Source Walk & Plugin Dispatch

### sugar-walk Binaries

#### sugar-walk-rpc
**Binary name:** `sugar-walk-rpc`  
**Package:** `sugar-walk`  
**Kind:** RPC service  
**Audience:** lifter backend, integrator  

**Summary:** RPC server for source AST walking and symbolic effect enumeration.

**Typical use:** Dispatched by lifter for Rust source walking  
**Documentation:** Walk protocol in `protocol/specs/`

---

#### sugar-walk-demo
**Binary name:** `sugar-walk-demo`  
**Package:** `sugar-walk`  
**Kind:** Demo / test utility  
**Audience:** contributor  

**Summary:** Demonstration of sugar-walk capabilities.

---

#### sugar-walk-emit
**Binary name:** `sugar-walk-emit`  
**Package:** `sugar-walk`  
**Kind:** Emitter utility  
**Audience:** contributor  

**Summary:** Emits walk results for external consumption or analysis.

---

### Plugin & Contract Services

#### contracts_rpc
**Binary name:** `contracts_rpc`  
**Package:** `sugar-lift-contracts`  
**Kind:** RPC service  
**Audience:** lifter backend, integrator  

**Summary:** Rust `#[requires]`/`#[ensures]` contract lifter as RPC service. Dispatched per manifest; walks source and lifts Rust attribute contracts to IR.

**Purpose:** The Sever (as of v0.1) — contracts no longer statically linked, now RPC  
**Typical use:** Spawned by lifter for Rust contract discovery  
**Documentation:** Contracts protocol in `protocol/specs/`

---

#### sugar-plugin-loader-stub-rpc
**Binary name:** `sugar-plugin-loader-stub-rpc`  
**Package:** `sugar-plugin-loader`  
**Kind:** RPC service  
**Audience:** contributor, plugin developer  

**Summary:** Stub RPC server for plugin loader protocol testing and scaffolding.

**Documentation:** Plugin loader architecture in `protocol/specs/`

---

#### mint-plugin-cid
**Binary name:** `mint-plugin-cid`  
**Package:** `sugar-plugin-loader`  
**Kind:** Utility  
**Audience:** contributor, plugin developer  

**Summary:** Computes and mints the CID of a plugin envelope.

**Typical use:** Plugin registry sealing, plugin artifact versioning  
**Documentation:** Plugin protocol in `protocol/specs/2026-04-30-proof-file-format.md` (§7)

---

## Symbol Resolution & Linking

### sugar-linkerd
**Binary name:** `sugar-linkerd`  
**Package:** `sugar-linkerd`  
**Kind:** Daemon / RPC service  
**Audience:** lifter backend, integrator  

**Summary:** Rust symbol resolver and oracle service. Resolves method-call receiver/param mutability and other semantic queries over Rust AST.

**Typical use:** Spawned by lifter to answer semantic questions (mutability, ownership, lifetime)  
**Example:** Queried from `sugar-lift-rust-tests` over RPC for call-site effect classification  
**Documentation:** Oracle protocol in `protocol/specs/`

---

## Build & Test Infrastructure

### bcargo
**Type:** Bash wrapper script  
**Location:** `bin/bcargo`  
**Kind:** Build multiplexer  
**Audience:** developer, CI/CD  

**Summary:** Synchronizes Rust workspace to remote battleaxe host and runs Cargo there. Enables CI-parity testing and cross-platform building.

**Typical use:**
```bash
bcargo [--sync-bin NAME] [--sync-bins LIST] [--] [cargo args...]
```

**Key flags:**
- `--sync-bin NAME` — Sync single binary back after build
- `--sync-bins LIST` — Comma-separated binary list
- `--` — End bcargo options, begin cargo args

**Environment:**
- `BCARGO_REMOTE_HOST` — SSH host (default: `battleaxe`)
- `BCARGO_REMOTE_ROOT` — Remote scratch root (default: `/home/tsavo/remote/sugar-bcargo-<hash>`)
- `BCARGO_CLEAN_REMOTE_ROOT` — Cleanup behavior (`success|always|never`)
- `BCARGO_PYTHON_ENV` — Provision Python kit env (default: 1)
- `BCARGO_SSH` — SSH binary (default: `ssh`)
- `BCARGO_RSYNC` — rsync binary (default: `rsync`)

**Exit codes:**
- 0 = success
- 2 = user error (bad args, outside repo, etc.)
- Other = cargo exit code

**Documentation:** `reference_bcargo_cwd_and_real_exit.md` in user memory

---

### compute_fixture_cid
**Binary name:** `compute_fixture_cid`  
**Package:** `sugar-canonicalizer`  
**Kind:** Utility  
**Audience:** contributor, conformance harness  

**Summary:** Computes BLAKE3-512 CID of a file (JCS-JSON canonicalized).

**Typical use:** Computing expected CIDs in conformance fixtures  
**Documentation:** Canonicalization in `docs/contributing/writing-a-kit/02-canonicalizer.md`

---

## Output Format Flags (Global)

All user-facing CLIs support these common flags:

- `--json` — Emit structured JSON instead of human-readable text
- `--quiet` — Suppress non-error output

Structured logging to stderr can be controlled:
- `RUST_LOG=info` — Pipeline narrative (stage counts, totals)
- `RUST_LOG=debug` — Per-item decisions
- `RUST_LOG=trace` — RPC payloads, RA queries
- `SUGAR_LOG_FILE=<path>` — Write logs to file instead of stderr

---

## Exit Codes (Canonical)

**sugar CLI exit codes** (from `implementations/rust/sugar-cli/src/main.rs`):
- `0` = EXIT_OK — Success
- `1` = EXIT_VERIFY_FAIL — Verification failure (proof does not hold)
- `2` = EXIT_USER_ERROR — User error (bad args, file not found, invalid config)
- `3` = EXIT_SOLVER_FAIL — Solver failure (Z3 unavailable, timeout, unsupported theory)

Other binaries may use their own conventions; see individual documentation.

---

## Plugin Protocol Flags (PEP 1.7.0)

Subcommands participating in plugin registry (`--plugin`, `--sugar`, `--lifter`, etc.) support:

- `--plugin <kind>:<source>` — Load a plugin (canonical form)
- `--sugar <source>` — Alias for `--plugin sugar:<source>`
- `--loss-fn <source>` — Alias for `--plugin loss-function:<source>`
- `--lifter <source>` — Alias for `--plugin lift:<source>`
- `--strict-plugins` — Promote every plugin load failure to a refuse
- `--plugin-registry-out <path>` — Write PluginRegistryMemento to path after sealing

**Documentation:** Protocol §7, §9 in `protocol/specs/`

---

## Discovery & Introspection

### Version Information
```bash
sugar version                    # Print CLI version
sugar version [subcommand]       # Version info per subcommand (if supported)
```

### Configuration
- Project config file: `sugar.toml` in project root
- Kit manifests: `.sugar/*.toml` (lift adapters, plugins, signers)
- Verify config via: `sugar doctor`

---

## Cross-Language Kits

Sugar's poly-lingua design includes Kit-level CLIs for Python and Java:

### Python Kit
**Location:** `implementations/python/`  
**Entry points:** TBD (check `pyproject.toml` files)  
**Audience:** Python package maintainers  

See `implementations/python/` for sugar-lift-python-source, sugar-emit-python-pytest, etc.

### Java Kit
**Location:** `implementations/java/`  
**Entry points:** TBD (check Maven/Gradle configs)  
**Audience:** Maven/Gradle users  

See `implementations/java/` for JUnit lifting, JSR-380 annotation support.

---

## Open Questions

1. **Python & Java kit CLIs:** Do Python/Java kits expose CLI binaries, or are they library/RPC only? Verify `pyproject.toml` and `pom.xml` for `scripts` / `entry-points` / `plugins` sections.

2. **Embedded plugin registry:** Does the plugin-registry sealing produce a durable artifact (e.g., `registry.cid` file)? Clarify the lifecycle of `PluginRegistryMemento` emitted by `--plugin-registry-out`.

3. **RPC transport:** Which RPC services use NDJSON (line-delimited JSON) vs. JSON-RPC? Confirm transport for `witness_rpc`, `contracts_rpc`, `walk_rpc`, `linkerd`.

4. **Batch operations:** Do any CLIs support batch input (e.g., `sugar hash` over multiple files, or `sugar prove` over multiple `.proof` sets in one invocation)?

5. **Configuration inheritance:** How do `.sugar/*.toml` manifests cascade (global → kit → project)? Clarify precedence.

6. **Witness package versioning:** Does `sugar verify` produce reproducible witness packages, or do they include timestamps?

7. **Python kit invocation:** Is the Python kit invoked via `python -m` (e.g., `python -m sugar_lift_python_source`) or via explicit entry-point scripts?

8. **Cross-repo projects:** When `sugar prove --with <dir>` loads multiple projects, how are conflicting CIDs resolved? De-duplication or union?

---

## Related Documentation

- **User Guides:** `docs/contributing/`, `docs/self-application/KIT-SETUP-AND-SELF-APPLICATION.md`
- **Protocol Specs:** `protocol/specs/` — proof format, composition, plugin registry, effect discharge classification
- **Examples:** `examples/` — rust-coretests-report, tokio-channel-implication-edge, signup-service (Java)
- **Architecture:** `docs/papers/` — whitepapers and bluepapers explaining proof format and substrate philosophy
- **Threat Model:** `docs/security/threat-model.md`


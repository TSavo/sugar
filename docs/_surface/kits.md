# Language Kits (Federation Seats)

Sugar is a polyglot correctness substrate where each language kit implements the protocol in its native ecosystem. Every kit must emit byte-deterministic IR for the same canonical formula — this contract is enforced by the cross-language conformance harness. This document inventories the real documentable surface of each kit, organized by language.

---

## Rust Kit

**Location:** `/implementations/rust/`  
**Maturity:** Production (flagship implementation, reference IR+canonicalizer)  
**Coverage:** Rust workspace lift, test-assertion discovery, contract attributes, implication edges, multiple IR backends

The Rust kit is the core federation seat. It owns the reference IR types (CDDL-generated), SMT solver bridge, formal-logic backends, and multi-language IR compiler suite.

### Core Libraries

#### libsugar — Reference Protocol Library
- **Path:** `implementations/rust/libsugar/`
- **Kind:** Library + C-linkable cdylib
- **Summary:** Core Rust reference implementation for protocol workflows; memento structures, canonicalization, proof substrate primitives, content-addressed naming.
- **Audience:** integrators, contributors
- **Priority:** P0 (shipped as public C API)
- **Existing coverage:** `./implementations/rust/libsugar/README.md`

#### sugar-ir-types — IR Generation from Grammar
- **Path:** `implementations/rust/sugar-ir-types/`
- **Kind:** Library (codegen)
- **Summary:** Auto-generated Rust types from CDDL grammar (protocol/sugar-ir.cddl); canonical term representation, contract families, bound-variable sidecar.
- **Audience:** contributors
- **Priority:** P1
- **Existing coverage:** none

#### sugar-canonicalizer — JCS Encoder + BLAKE3 Hasher
- **Path:** `implementations/rust/sugar-canonicalizer/`
- **Kind:** Library + binary
- **Summary:** Deterministic JSON canonicalization (RFC 8785) + BLAKE3-512 CID computation; byte-identical output across language kits.
- **Audience:** integrators, contributors
- **Priority:** P0 (cross-language determinism foundation)
- **Existing coverage:** none

#### sugar-claim-envelope — Memento Builders
- **Path:** `implementations/rust/sugar-claim-envelope/`
- **Kind:** Library
- **Summary:** Builders for contract, bridge, and implication memento envelopes; claim structure, envelope signing, content-address minting.
- **Audience:** contributors
- **Priority:** P1
- **Existing coverage:** none

#### sugar-proof-envelope — CBOR Proof Format
- **Path:** `implementations/rust/sugar-proof-envelope/`
- **Kind:** Library
- **Summary:** Deterministic CBOR builder for .proof files; memento catalog assembly, Ed25519 signing, CID filename generation.
- **Audience:** integrators, contributors
- **Priority:** P0 (proof file format)
- **Existing coverage:** `./protocol/specs/2026-04-30-proof-file-format.md`

#### sugar-ir-symbolic — IR Authoring API + JSON Serializer
- **Path:** `implementations/rust/sugar-ir-symbolic/`
- **Kind:** Library
- **Summary:** Rustic authoring API for IR contracts (non-codegen entry point); JSON emitter for v1.1.0 IR protocol serialization.
- **Audience:** contributors
- **Priority:** P1
- **Existing coverage:** none

### Lifters & Adapters

#### sugar-lift — Main Lift Toolchain
- **Path:** `implementations/rust/sugar-lift/`
- **Kind:** Library + two binaries (`sugar-lift`, `cargo-sugar-lift`)
- **Summary:** Walks a Rust workspace, discovers and runs all registered lift adapters, mints signed contract mementos, bundles into single `.proof` catalog. Non-rewriting: reads existing tests, promotes them. Supports Layer 0 (mechanical), Layer 2 (structural), Layer 3 (future LLM).
- **Audience:** end-users, integrators, contributors
- **Priority:** P0 (primary user entrypoint)
- **Existing coverage:** `./implementations/rust/sugar-lift/README.md`, `./docs/contributing/writing-a-lift-adapter/`

**Supported Adapters (statically linked or RPC):**
1. **proptest** — lifts `proptest! { #[test] ... }` invariant assertions into `inv` contracts
2. **contracts** — lifts `#[requires]`/`#[ensures]` attributes into pre/post contracts

#### sugar-lift-contracts — contracts Crate Adapter
- **Path:** `implementations/rust/sugar-lift-contracts/`
- **Kind:** Library
- **Summary:** AST walker for `#[contracts::requires]`/`#[contracts::ensures]` function attributes; emits pre/post contract mementos.
- **Audience:** contributors
- **Priority:** P1 (Rust ecosystem adapter)
- **Existing coverage:** none

#### sugar-lift-rust-tests — Unit Test Assertion Lifter
- **Path:** `implementations/rust/sugar-lift-rust-tests/`
- **Kind:** Library + binaries (`coretests_sweep`, `discharge_sweep`)
- **Summary:** Layer 2 structural lifter for `#[test]` assertions; walks Rust coretests, emits invariant-only contracts. Binaries are measurement tools: `coretests_sweep` enumerates total assertions, `discharge_sweep` reports SMT coverage. **Total accounting:** 6377 assertions, 74.8% discharged (main baseline).
- **Audience:** contributors, researchers
- **Priority:** P0 (self-application measurement harness)
- **Existing coverage:** `./examples/rust-coretests-report/`, `./docs/self-application/ASSERTION-ACCOUNTING-LEDGER.md`

#### sugar-lift-rust-cargo-test-witness — Test Witness Lifter
- **Path:** `implementations/rust/sugar-lift-rust-cargo-test-witness/`
- **Kind:** Library + binaries (`witness_rpc`, `discharge_cli`)
- **Summary:** Runs a crate's test suite, content-addresses per-test pass/fail outcomes, mints witness-package bundle with signed WitnessPackageMemento. Parity for Python pytest-witness kit. `discharge_cli` verifies proofs locally without RPC.
- **Audience:** contributors
- **Priority:** P1 (execution witness bridge)
- **Existing coverage:** none

#### sugar-walk — Backward WP Propagation for Callsites
- **Path:** `implementations/rust/sugar-walk/`
- **Kind:** Library + RPC binary
- **Summary:** Walks backward from callsites to allocations via weakest-precondition substitution; lifts production preconditions (guards, asserts, unwrap patterns) into implication edges bridging caller to callee contracts. Powers callsite composition.
- **Audience:** contributors
- **Priority:** P1 (cross-crate correctness flow)
- **Existing coverage:** none

### IR Compilers (Backends)

#### sugar-ir-compiler — Dispatcher + Protocol
- **Path:** `implementations/rust/sugar-ir-compiler/`
- **Kind:** Library
- **Summary:** Plugin dispatcher architecture; protocol traits for IR→target-language compilation; JSON-RPC subprocess client; plugin discovery and invocation.
- **Audience:** contributors
- **Priority:** P1 (extensibility substrate)
- **Existing coverage:** none

#### sugar-ir-compiler-smt-lib — SMT-LIB2 Backend
- **Path:** `implementations/rust/sugar-ir-compiler-smt-lib/`
- **Kind:** Library + binary
- **Summary:** Lowers ProofIR to Z3 SMT-LIB2 syntax; automated theorem proving backend; pluggable into verifier pipeline. Subprocess-invokable; used by `sugar verify` discharge step.
- **Audience:** integrators, contributors
- **Priority:** P0 (primary verifier backend)
- **Existing coverage:** none

#### sugar-ir-compiler-lean — Lean 4 Backend
- **Path:** `implementations/rust/sugar-ir-compiler-lean/`
- **Kind:** Library + binary
- **Summary:** Compiles ProofIR to Lean 4 formal-logic syntax; emits tactic stubs and library scaffolding for manual proof inspection/extension.
- **Audience:** researchers, contributors
- **Priority:** P1 (formal-verification interop)
- **Existing coverage:** none

#### sugar-ir-compiler-coq — Coq Backend
- **Path:** `implementations/rust/sugar-ir-compiler-coq/`
- **Kind:** Library + binary
- **Summary:** Compiles ProofIR to Coq formal-logic syntax.
- **Audience:** researchers, contributors
- **Priority:** P1 (formal-verification interop)
- **Existing coverage:** none

#### sugar-ir-compiler-maude — Maude Backend
- **Path:** `implementations/rust/sugar-ir-compiler-maude/`
- **Kind:** Library + binary
- **Summary:** Compiles ProofIR to Maude rewriting logic syntax for equational theory obligations; bundled solver.
- **Audience:** researchers, contributors
- **Priority:** P2 (specialized reasoning backend)
- **Existing coverage:** none

### Verification & Proof Processing

#### sugar-verifier — Six-Stage Verifier Pipeline
- **Path:** `implementations/rust/sugar-verifier/`
- **Kind:** Library
- **Summary:** Core verifier: loads proofs → enumerates contracts → resolves dependencies → instantiates universes → emits SMT → solves → reports coverage and refutation certificates. Powers `sugar verify` and `sugar prove`.
- **Audience:** integrators, contributors
- **Priority:** P0 (core verification logic)
- **Existing coverage:** none

#### sugar-linker — Pure Linker Algebra
- **Path:** `implementations/rust/sugar-linker/`
- **Kind:** Library
- **Summary:** Derives bridges from (contracts ∪ call-edges) per spec 2026-05-03; composable linker without IO. Used by `sugar link` CLI and LSP plugins.
- **Audience:** contributors
- **Priority:** P1 (cross-crate bridging)
- **Existing coverage:** none

#### sugar-linkerd — Linker Daemon
- **Path:** `implementations/rust/sugar-linkerd/`
- **Kind:** Binary (JSON-RPC daemon)
- **Summary:** Long-running service for per-kit LSP plugins; serves linker queries over NDJSON; implements daemon protocol spec 2026-05-04.
- **Audience:** integrators
- **Priority:** P1 (IDE integration infrastructure)
- **Existing coverage:** none

### CLI & Entry Points

#### sugar-cli — Main User-Facing CLI
- **Path:** `implementations/rust/sugar-cli/`
- **Kind:** Binary (`sugar`)
- **Summary:** Universal CLI with 20+ subcommands: `prove` (discharge), `verify` (check proofs), `diff` (behavioral diff), `lift` (discover contracts), `mint` (create proof), `emit` (code generation), `bind` (bridge builder), `compose` (cross-crate), `doctor`, `hash`, `recognize`, `materialize`, `init`, and RPC services. Routes to libsugar for reusable logic.
- **Audience:** end-users, integrators
- **Priority:** P0 (public interface)
- **Existing coverage:** `./README.md`, `./docs/contributing/overview.md`

#### cargo-sugar — Cargo Subcommand
- **Path:** `implementations/rust/cargo-sugar/`
- **Kind:** Binary (`cargo sugar`)
- **Summary:** Cargo plugin for behavioral semver: `cargo sugar diff` compares two proof sets by behavior (new/lost/none), not bytes. Freezes coupling surface at upgrade time.
- **Audience:** end-users, integrators
- **Priority:** P0 (public interface)
- **Existing coverage:** `./README.md`

### Language Server & IDE Integration

#### sugar-lsp — Base LSP Implementation
- **Path:** `implementations/rust/sugar-lsp/`
- **Kind:** Binary (LSP server)
- **Summary:** Language Server Protocol implementation; delegates verification to configurable JSON-RPC backends; standard IDE integration (diagnostics, hover, completions).
- **Audience:** integrators
- **Priority:** P1 (editor integration)
- **Existing coverage:** none

#### sugar-lsp-rust — Rust-Specific LSP Plugin
- **Path:** `implementations/rust/sugar-lsp-rust/`
- **Kind:** Binary (LSP plugin over NDJSON)
- **Summary:** Thin shim dispatching rust-contracts lift kit over RPC; speaks per-language plugin protocol (initialize/parse/shutdown).
- **Audience:** contributors
- **Priority:** P1 (Rust IDE support)
- **Existing coverage:** none

### Plugin & RPC Infrastructure

#### sugar-plugin-loader — PEP 1.7.0 Plugin Loader
- **Path:** `implementations/rust/sugar-plugin-loader/`
- **Kind:** Library
- **Summary:** Implements PEP 1.7.0 plugin protocol: file interface (§3), JSON-RPC interface (§4), content-addressing (§6), error model (§8), registry semantics (§9). Universal plugin loader for all kits.
- **Audience:** integrators, contributors
- **Priority:** P0 (cross-kit plugin substrate)
- **Existing coverage:** `./protocol/specs/` (PEP 1.7.0 numbered sections)

#### libsugar-rpc — RPC Server Library
- **Path:** `implementations/rust/libsugar-rpc/`
- **Kind:** Library
- **Summary:** JSON-RPC 2.0 NDJSON server for lift-plugin protocol; vendorable, external-crate-only. Adapter binaries call `run_server()` with their adapter-specific `AdapterLifter`; library handles protocol mechanics, content-addressed naming, dedup.
- **Audience:** contributors
- **Priority:** P1 (plugin RPC transport)
- **Existing coverage:** none

#### sugar-lift-rpc-client — RPC Client for Adapters
- **Path:** `implementations/rust/sugar-lift-rpc-client/`
- **Kind:** Library
- **Summary:** Minimal leaf client that locates and drives the rust-contracts lift kit over NDJSON; returns raw ir-document. Used by `sugar-lift`, build systems, and LSP plugins to reach adapters over RPC instead of static linking.
- **Audience:** contributors
- **Priority:** P1 (plugin RPC transport)
- **Existing coverage:** none

### Utility & Instrumentation

#### sugar-lifter — sugar Attribute Proc-Macro
- **Path:** `implementations/rust/sugar-lifter/`
- **Kind:** Proc-macro library
- **Summary:** No-op at compile time; recognized by lift kit at lift time. Allows inline marking of code sections for selective lifting.
- **Audience:** contributors
- **Priority:** P2 (instrumentation)
- **Existing coverage:** none

#### sugar-verify-build-rs — build.rs Integration
- **Path:** `implementations/rust/sugar-verify-build-rs/`
- **Kind:** Library
- **Summary:** Cargo build.rs hook for verification at build time; memento IS the verification artifact.
- **Audience:** contributors
- **Priority:** P2 (build-time verification)
- **Existing coverage:** none

---

## Python Kit

**Location:** `/implementations/python/`  
**Maturity:** Production (pytest/unittest adapters, hypothesis emitter)  
**Coverage:** pytest/unittest lift, hypothesis property test emission, behavioral semver pre-commit hook

The Python kit mirrors Rust for cross-language protocol parity. It specializes in Python test framework integration and pre-commit behavioral-change detection.

### Core Library

#### libsugar-py — Python Reference Library
- **Path:** `implementations/python/libsugar-py/`
- **Kind:** Library (Python package)
- **Summary:** Experiment in honest FFI refusal at the first shim gap; Python bindings to Rust libsugar via ctypes; demonstrates contract boundary where Python cannot bind deeper.
- **Audience:** integrators, contributors
- **Priority:** P2 (FFI exploration)
- **Existing coverage:** none

### Lifters & Test Framework Adapters

#### sugar-lift-py-tests — pytest/unittest Structural Lifter
- **Path:** `implementations/python/sugar-lift-py-tests/`
- **Kind:** Library (Python package)
- **Summary:** Layer 2 structural adapter for pytest and unittest; walks Python AST; recognizes: bounded for-loops→forall-implies, helper inlining, multi-assertion characterization, @pytest.mark.parametrize literal rows, callsite value-scope facts. Emits canonical IR mementos byte-identical to Rust canonicalizer. Production-side WP walker for composition.
- **Audience:** end-users, integrators, contributors
- **Priority:** P0 (Rust parity lifter)
- **Existing coverage:** `./implementations/python/sugar-lift-py-tests/README.md`

#### sugar-lift-py-pytest-witness — pytest Witness Lifter
- **Path:** `implementations/python/sugar-lift-py-pytest-witness/`
- **Kind:** Library (Python package)
- **Summary:** Execution-witness proofchain linker for pytest runs; k(I)=t linking model; resolves witness oracle requests (test body, execution outcome).
- **Audience:** contributors
- **Priority:** P1 (execution witness bridge)
- **Existing coverage:** none

#### sugar-lift-python-source — Python Source Lifter
- **Path:** `implementations/python/sugar-lift-python-source/`
- **Kind:** Library (Python package)
- **Summary:** Language lifter over a Python operation algebra; discovers Python-native terms (assignments, conditionals, exceptions) in source; powers source-level contract discovery.
- **Audience:** contributors
- **Priority:** P1 (source-level analysis)
- **Existing coverage:** none

### Code Generation (Emitters)

#### sugar-emit-python-pytest — pytest Emitter
- **Path:** `implementations/python/sugar-emit-python-pytest/`
- **Kind:** Library + PEP 1.7.0 plugin (RPC binary)
- **Summary:** Materializes neutral predicates as native pytest assertions (assert a == b, assert a is None, pytest.raises, etc.). Framework spelling lives in Python kit (not catalog). Supports 9 predicate types. Unsupported predicates recorded as honest emit-assertion-gaps. RPC interface per PEP 1.7.0.
- **Audience:** integrators, contributors
- **Priority:** P0 (Rust parity emitter)
- **Existing coverage:** `./implementations/python/sugar-emit-python-pytest/README.md`

#### sugar-emit-python-unittest — unittest Emitter
- **Path:** `implementations/python/sugar-emit-python-unittest/`
- **Kind:** Library + PEP 1.7.0 plugin (RPC binary)
- **Summary:** Materializes neutral predicates as native unittest assertions (assertEqual, assertIsNone, assertRaises, etc.). Parity with pytest emitter for unittest-first projects.
- **Audience:** integrators, contributors
- **Priority:** P1 (alternative test framework)
- **Existing coverage:** `./implementations/python/sugar-emit-python-unittest/README.md`

#### sugar-emit-python-hypothesis — hypothesis Emitter
- **Path:** `implementations/python/sugar-emit-python-hypothesis/`
- **Kind:** Library + PEP 1.7.0 plugin (RPC binary)
- **Summary:** Materializes neutral predicates as hypothesis property tests (@given, strategies); first slice emits predicates whose strategies satisfy without guessing host semantics (eq, ne, lt, gt, le, ge, option-is-none/some over direct vars + integer constants). Unsupported predicates returned in gaps.
- **Audience:** integrators, contributors
- **Priority:** P1 (property-test emission)
- **Existing coverage:** `./implementations/python/sugar-emit-python-hypothesis/README.md`

### Build & Witness Infrastructure

#### sugar-build-witness — Build Script Witness Lifter
- **Path:** `implementations/python/sugar-build-witness/`
- **Kind:** Library (Python package)
- **Summary:** Captures build-script execution as reproducible witness (environment, return code, stdout/stderr); links build outcomes to proofs for supply-chain continuity.
- **Audience:** contributors
- **Priority:** P2 (build integration)
- **Existing coverage:** none

### Integration & LSP

#### sugar_lsp — Python LSP Plugin
- **Path:** `implementations/python/sugar_lsp/`
- **Kind:** Directory (LSP integration)
- **Summary:** Python-side LSP plugin shim; integrates Python lifters with linker daemon for IDE diagnostics.
- **Audience:** integrators
- **Priority:** P1 (editor integration)
- **Existing coverage:** none

---

## Java Kit

**Location:** `/implementations/java/`  
**Maturity:** Early (test assertion lifter, Bay witness oracle)  
**Coverage:** JUnit5/TestNG assertion discovery, Java source AST walking, Panama FFM call-edge bridge lifter

The Java kit is a pure-Java implementation with no Maven/Gradle build files. It uses shell scripts and JDK 21+ com.sun.source tree API.

### Core Lifter

#### sugar-lift-java-tests — JUnit/TestNG Assertion Lifter
- **Path:** `implementations/java/sugar-lift-java-tests/`
- **Kind:** Java source files + RPC binaries (shell-compiled)
- **Summary:** Walks Java AST via com.sun.source tree API; lifts JUnit5 and TestNG assertions into canonical IR mementos. Emits three RPC binaries: `JavaTestAssertionsRpc` (contract lift), `JavaJunitWitnessRpc` (witness resolve), `JavaPanamaFfmRpc` (call-edge bridge lifter, P5b feature).
- **Audience:** integrators, contributors
- **Priority:** P0 (Java ecosystem entry point)
- **Existing coverage:** none

**Build:** `build.sh` compiles with `--release 21` (pure Java) and `--add-exports jdk.compiler` (tree API).

**RPC Binaries:**
1. **JavaTestAssertionsRpc** — lift assertions from test bodies into ContractDecls + vocabulary + universes
2. **JavaJunitWitnessRpc** — resolve witness oracle (test execution records, outcomes)
3. **JavaPanamaFfmRpc** — lift call-edge bridges via Panama FFM introspection (future feature P5b)

**Supported Assertion Types:**
- JUnit5: `assertEquals`, `assertNotEquals`, `assertTrue`, `assertFalse`, `assertNull`, `assertNotNull`, etc.
- TestNG: `Assert.assertEquals`, `Assert.assertTrue`, etc.
- Bean Validation / JSR-380 annotations (recognized but not lifted in v0)

**Test Fixtures:**
- `tests/fixtures/commons-codec-crc32/` — real Apache Commons Codec CRC32 library assertions
- `tests/fixtures/numeric-universe/` — isolated numeric predicate universe tests
- `tests/fixtures/vendor/junit5/`, `vendor/testng/` — annotation vocabulary reference

---

## Cross-Kit Concerns

### Conformance Harness

**Purpose:** Enforce byte-deterministic protocol compliance across all language kits.  
**Mechanism:** Every kit emits IR for the same canonical formula; the harness compares JCS-encoded JSON + BLAKE3 CIDs across implementations and fails on any mismatch.  
**Trigger:** `make conformance` (repo root) or `make ci` (which includes conformance).

**Locations:**
- `conformance/` — test fixtures and harness runner
- `implementations/{rust,python,java}/conformance/` — per-kit harness outputs

### Kit Configuration

**Path:** `.sugar/config.toml` (per project directory)  
**Surfaces:** Named authoring patterns (rust-bind, rust-contracts, py-tests, java-assertions)  
**Lift Manifests:** `.sugar/lift/<surface>/manifest.toml` specifies RPC binary path + protocol method  
**Cross-Kit Discovery:** Plugin loader resolves adapters via PEP 1.7.0 registry; LSP + linker daemon multiplex across languages

### Shared Protocol Specs

- `protocol/sugar-ir.cddl` — CDDL grammar (Term, ContractDecl, Bridge, etc.)
- `protocol/specs/2026-04-29-correctness-is-a-hash.md` — CID/BLAKE3 commitment
- `protocol/specs/2026-05-09-contract-composition-protocol.md` — implication edges, witness discharge
- `protocol/specs/PEP-1.7.0*.md` — plugin protocol (numbered sections §1–§12)

---

## Open Questions

1. **Java Kit Production Readiness:** `JavaPanamaFfmRpc` is marked P5b (future). What is the current GA status? Are JavaTestAssertionsRpc + JavaJunitWitnessRpc stable for production lifting, or do they still require conformance harness green before shipping?

2. **Python Emitter Output Quality:** Do emitted pytest/unittest/hypothesis tests pass when run standalone (beyond parse checks)? The README claims end-to-end tests verify emission, but are there known gaps in assertion semantics (e.g., floating-point tolerance, collection membership)?

3. **Cross-Kit Bridge Composition:** The composition protocol (implication edges, witness discharge) is specified in `2026-05-09-contract-composition-protocol.md`. Which implementations currently support cross-kit bridging (e.g., Rust callsite → Java library)? Is Python→Java lifting implemented?

4. **LSP Plugin Stability:** `sugar-lsp`, `sugar-lsp-rust`, and `sugar_lsp` (Python) all exist. Are they interoperable? Can a single IDE session load both Rust and Python kit plugins simultaneously, or do they require separate language-server instances?

5. **Build Witness Infrastructure:** `sugar-build-witness` (Python) and `sugar-lift-rust-cargo-test-witness` (Rust) exist, but how are they invoked? Are they wired into CI/CD, or are they library APIs for manual integration?

6. **Lift Adapter RPC Marshalling:** The Rust kit migrated `sugar-lift-contracts` to RPC (via `sugar-lift-rpc-client`). Is this pattern recommended for Python and Java adapters, or is static linking acceptable in those ecosystems? Where is this decision documented?

7. **Proof Catalog Distribution:** How do kits publish and consume `.proof` files across languages? Is there a package registry (npm, PyPI, Maven Central), or do users manually copy proofs into `.sugar/imports/`? This is critical for end-user adoption.


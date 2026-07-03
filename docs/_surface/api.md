# Sugar / ProvekIt API Surface for Integrators

This document catalogs the programmatic API surface of the Sugar correctness verification system, organized for integrators and kit contributors. It covers crates, public modules, key traits, and extension points.

---

## Core Substrate Libraries

These are foundational libraries used throughout the ecosystem. They handle serialization, content addressing, cryptography, and proof envelopes.

### libsugar — Rust Reference Library

**Crate:** `libsugar`  
**Type:** Library (Rust cdylib + staticlib + lib for FFI and in-process use)  
**Public Modules:**
- `canonical` — deterministic canonicalization, alpha-normal form, pure-let reduction
- `compose` — proof composition across library boundaries
- `core` — core types (Effect, EffectOutcome, Memento, ProofGraph)
- `desugar` — lowering ProofIR to logical floor
- `effect_propagation` — effect discharge and propagation
- `ffi` — C-linkable interface for libsugar.so/libsugar.dylib
- `panic_freedom` — panic-safety analysis and contracts
- `policy_profile_registry` — policy/profile configuration
- `transport` — witness oracle and RPC client communication
- `witness_registry` — witness indexing and resolution
- `wp` — weakest-precondition calculation

**Audience:** Integrators (Rust), Contributors (kit writers)  
**Priority:** P0  
**Existing Docs:** `./implementations/rust/libsugar/README.md`  
**Summary:** Core Rust library providing proof composition, effect discharge, canonicalization, and witness resolution. Exports C linkage for C/C++ kit integration.

---

### sugar-proof-envelope — .proof File Format & Signing

**Crate:** `sugar-proof-envelope`  
**Public API:**
- `ProofEnvelopeInput` — builder struct for signing proof bundles
- `ProofGraph` — content-addressed memento DAG
- `ClaimContractMemento` — signed contract claim
- `build_proof_envelope()` — mints signed .proof file
- `proof_filename()` — computes canonical .proof CID-based filename
- `Ed25519Seed` — signing key type ([u8; 32])
- `ed25519_pubkey_string()` — serializes public key

**Audience:** Integrators (proof minting), Contributors (kit writers)  
**Priority:** P0  
**Summary:** CBOR serialization, Ed25519 signing, and envelope construction for the .proof file format. Used by every kit to mint signed proof bundles.

---

### sugar-ir-types — Canonical ProofIR Type Definitions

**Crate:** `sugar-ir-types`  
**Public API:**
- `Declaration` enum: `Contract`, `Bridge`
- `ContractDeclaration` — name, outBinding, pre/post/inv formulas
- `BridgeDeclaration`, `BridgeDeclarationV14` — library-boundary claims
- `IrFormula`, `IrTerm`, `LetBinding` — logical formula AST
- `canonicalize_formula()`, `canonicalize_property()` — canonical form normalization

**Source:** Auto-generated from `protocol/sugar-ir.cddl` (CDDL grammar)  
**Audience:** Integrators (proof consumers), Contributors (all kits)  
**Priority:** P0  
**Summary:** SERDE-derived types matching the formal Sugar IR grammar. All kits emit these types; they are the bridge between source code and logical foundation.

---

### sugar-canonicalizer — Deterministic Canonicalization & JCS

**Crate:** `sugar-canonicalizer`  
**Public API:**
- `blake3_512_of()` — BLAKE3-512 content address (self-identifying string form)
- `encode_jcs()` — RFC 8785 JSON Canonicalization Scheme
- `Value` — re-export of serde_json::Value

**Audience:** Integrators (proof infrastructure), Contributors (all kits)  
**Priority:** P0  
**Summary:** Deterministic byte-hashing and JSON canonicalization. Critical for content-addressing and cross-implementation parity.

---

### sugar-claim-envelope — Contract Minting

**Crate:** `sugar-claim-envelope`  
**Public API:**
- `mint_contract()` — produces signed contract with CID
- `compute_contract_cid()`, `compute_contract_set_cid()` — CID computation
- `MintContractArgs` — builder for minting options
- `Authoring` enum — lift authorship metadata
- `KIT_DECLARATION_RPC_METHOD` — RPC method name constant

**Audience:** Contributors (kit lifters)  
**Priority:** P1  
**Summary:** Contract minting and CID computation. Used by lift adapters to produce canonical contract mementos before proof bundling.

---

## Lifter APIs: Authoring New Lift Adapters

Extension point for writing new language lifters, test-discovery adapters, or custom contract sources.

### libsugar-rpc — Lift Adapter Protocol & RPC Server

**Crate:** `libsugar-rpc`  
**Public Trait:**
```rust
pub trait AdapterLifter {
    fn lift(&self, workspace_root: &Path, source_paths: &[String]) -> LiftResult;
    fn surface(&self) -> &str;  // e.g., "pytest", "unittest", "hypothesis"
    fn name(&self) -> &str;     // e.g., "sugar-lift-py-pytest"
}
```

**Public API:**
- `run_server()` — main JSON-RPC server loop on stdio
- `AdapterLifter` trait — implement to add a new source language
- `LiftResult` struct — { mementos: Vec<Value>, diagnostics: Vec<Value> }
- `build_ir_document()` — lifter invocation and content-addressing
- `encode_jcs()` — JCS canonicalization (RFC 8785)
- `blake3_512_of()` — content-address hashing
- Protocol constants: `PROTOCOL_VERSION` ("pep/1.7.0"), `IR_VERSION` ("v1.1.0")

**Spec:** `protocol/specs/2026-04-30-lift-plugin-protocol.md` (legacy, renamed under PEP 1.7.0)  
**Audience:** Contributors (new language kit authors)  
**Priority:** P0  
**Existing Docs:** `./docs/contributing/writing-a-lift-adapter/` (5-part tutorial)  
**Summary:** The trait and RPC server for pluggable lift adapters. Adapters parse host-language source (tests, contracts, assertions), walk the AST, and emit canonical IR JSON mementos. The library handles content-addressing, dedup, and envelope construction.

---

### sugar-lifter — Annotation Macros

**Crate:** `sugar-lifter` (proc-macro library)  
**Public Proc Macros:**
- `#[sugar]` — marks source code as a concept materialization
- `#[boundary]` — marks cross-library boundary callsite
- `#[refuse]` — declines a surface as out-of-scope

**Usage in Source:**
```rust
#[sugar(concept = "hash", library = "blake3")]
pub fn blake3_digest(data: &[u8]) -> Hash { ... }

#[boundary(concept = "hash", library = "blake3", api = "blake3_digest")]
fn call_blake3(data: &[u8]) { ... }

#[refuse(surface = "blake3::Hasher::finalize_xof", concept = "streaming_hash", reason = "XOF not in scope")]
pub fn finalize_xof(&self) { ... }
```

**Audience:** Contributors (annotation-driven lifters)  
**Priority:** P1  
**Summary:** Proc-macro attributes for lifting. No-op at compile time; the lift kit pattern-matches the attribute paths during AST walks to mark declarations, boundaries, and refusals.

---

### sugar-lift — Rust Workspace Lifter & Minting

**Crate:** `sugar-lift`  
**Public API:**
- `lift_path()` → `LiftReport` — walks Rust workspace, runs adapters
- `mint_proof()` → signed .proof bytes + CID — mints proof bundle
- `lift_and_mint()` — convenience: both in one call
- `LiftOptions` struct — produced_by, produced_at, signer_seed, lifter, catalog_*
- `LiftReport` struct — decls, call_edges, adapter_reports, parse_errors
- `call_edges` module — extracts inter-function call edges per spec

**Audience:** Integrators (invoking Rust lifter), Contributors (Rust-kit extension)  
**Priority:** P1  
**Existing Docs:** `./implementations/rust/sugar-lift/README.md`  
**Summary:** High-level lifter API for Rust workspaces. Walks all .rs files, dispatches to registered adapters over RPC, collects contracts, and mints a signed .proof catalog.

---

### sugar-ir-symbolic — Contract IR Types & Parsing

**Crate:** `sugar-ir-symbolic`  
**Public API:**
- `ContractDecl` — a lifted contract declaration
- `Formula` — IR formula AST
- `parse_document()` — deserialize JSON IR to `Vec<ContractDecl>`
- `marshal_declarations()` — serialize `Vec<ContractDecl>` to JSON

**Audience:** Integrators (IR consumers), Contributors (lift kit backend)  
**Priority:** P1  
**Summary:** Logical IR representation and round-trip serialization. Bridges JSON IR exchange with typed Rust AST.

---

## IR Compiler APIs: Proof Backends

Extension point for writing new formal-logic backends (SMT, Lean, Coq, Maude, etc.).

### sugar-ir-compiler — IR Compiler Protocol & Registry

**Crate:** `sugar-ir-compiler`  
**Public Trait:**
```rust
pub trait IrCompiler: Send + Sync {
    fn compile_typed(&self, ir: &CompilerInput, dialect: &str) -> Result<CompiledFormula, CompileError>;
    fn capabilities(&self) -> Capabilities;
}
```

**Public Structs:**
- `CompilerInput` — typed frontend output: `Formula`, `Term`, or `EquationalTheory`
- `CompiledFormula` — { preamble, body, free_vars, opacity_manifest, metadata }
- `Capabilities` — { name, version, protocol_version, dialects, supported_sorts, supported_predicates }
- `FreeVar` — { name, sort }
- `OpacityManifest` — { protocol_version, compiler, compiler_version, opacities }
- `OpacityEntry` — { position_cid, reason_code }

**Submodules:**
- `manifest` — plugin manifest discovery and loading
- `registry` — in-process compiler registry by dialect
- `subprocess` — JSON-RPC subprocess client for plugins
- `server` — RPC server for plugin compilers
- `error` — `CompileError` enum

**Spec:** `protocol/specs/2026-04-30-ir-compiler-protocol.md`  
**Audience:** Contributors (new solver backends)  
**Priority:** P0  
**Summary:** Trait and RPC protocol for pluggable IR-to-dialect compilers. Translates canonical ProofIR to SMT-LIB, Lean 4, Coq, Maude, or other target languages. The registry auto-discovers plugin manifests from `~/.config/sugar/ir-compilers/` and `.sugar/ir-compilers/`.

---

### sugar-ir-compiler-smt-lib — Z3 SMT-LIB2 Backend

**Crate:** `sugar-ir-compiler-smt-lib`  
**Binary:** `sugar-ir-smt-lib` (implements `IrCompiler` trait over RPC)  
**Dialects Supported:** `smt-lib2.6`  
**Target Solver:** Z3  

**Audience:** End users (via registry), Contributors (solver integration)  
**Priority:** P1  
**Summary:** Compiles ProofIR formulas to SMT-LIB2.6 syntax for Z3. Part of the reference discharge pipeline.

---

### sugar-ir-compiler-lean, sugar-ir-compiler-coq, sugar-ir-compiler-maude

**Crates:** `sugar-ir-compiler-lean`, `sugar-ir-compiler-coq`, `sugar-ir-compiler-maude`  
**Binaries:** `sugar-ir-lean`, `sugar-ir-coq`, `sugar-ir-maude`  
**Dialects:** `lean4`, `coq`, `maude-rewrite-logic`  

**Audience:** Researchers (formal verification backends), Contributors (formal-logic integrators)  
**Priority:** P2  
**Summary:** Proof backends for formal-logic verifiers. Emit verified-correct proofs in Lean 4, Coq, or Maude syntax.

---

## Plugin Systems

### sugar-plugin-loader — Plugin Discovery & Management

**Crate:** `sugar-plugin-loader`  
**Public API:**
- `PluginRegistry` — in-memory registry of loaded plugins
- `PluginMemento` — signed plugin record with CID
- `PluginHeader`, `PluginMetadata` — plugin envelope structure
- `PluginLoadFailureMemento` — error records
- `load_plugin_from_file()`, `load_plugin_from_rpc()` — load functions
- `read_plugin_registry_memento()`, `write_plugin_registry_memento()` — persistence

**Spec:** PEP 1.7.0 (Plugin Extension Protocol)  
**Audience:** Contributors (plugin infrastructure)  
**Priority:** P2  
**Summary:** Plugin discovery, loading, and registry. Implements protocol/specs/2026-04-30-lift-plugin-protocol.md (now PEP 1.7.0). Discovers plugins from `.sugar/lift/*/manifest.toml` and `~/.config/sugar/lift/*/manifest.toml`.

---

## Language Kits

### Rust Kit

**Location:** `implementations/rust/`  
**Main Crates:**
- `sugar-lift` — workspace lifter (RPC dispatcher to contracts_rpc)
- `sugar-lift-contracts` — Rust #[requires]/#[ensures] lifter
- `sugar-lift-rust-tests` — Rust test assertion lifter (`coretests_sweep` binary)
- `sugar-walk` — AST walker and ir-walk infrastructure
- `sugar-lsp-rust` — Rust-specific LSP server

**Audience:** Integrators (Rust code verification), Contributors (Rust kit developers)  
**Priority:** P0  
**Existing Docs:** `./docs/contributing/writing-a-kit/` (5-step tutorial starting with conformance)  

---

### Python Kit

**Location:** `implementations/python/`  
**Main Packages:**
- `libsugar-py` — Python runtime (canonicalization, witness registry)
- `sugar-lift-py-tests` — pytest/unittest test lifter (RPC server)
- `sugar-lift-python-source` — source-code contract recognizer
- `sugar-emit-python-pytest`, `sugar-emit-python-unittest`, `sugar-emit-python-hypothesis` — contract emitters
- `sugar_lsp` — Python LSP server

**Audience:** Integrators (Python code verification), Contributors (Python kit developers)  
**Priority:** P1  

---

### Java Kit

**Location:** `implementations/java/`  
**Main Components:**
- Test lifting for JUnit/TestNG
- Bean Validation (JSR-380) annotation recognition
- JML (Java Modeling Language) support

**Audience:** Integrators (Java code verification), Contributors (Java kit developers)  
**Priority:** P1  

---

## CLI Tools & Binaries

### sugar (Main CLI)

**Binary:** `sugar-cli/src/main.rs`  
**Subcommands:**
- `prove` — lift and mint proof for a workspace
- `verify` — verify a .proof file
- `diff` — behavioral diff between library versions
- `lift` — run lifters and emit IR
- `compose` — compose proofs across boundaries
- `mint` — sign a proof envelope
- `emit` — serialize IR to JSON
- `bind` — establish implication edges
- `hash` — compute proof CIDs
- `recognize` — identify contract patterns
- `materialize` — instantiate templates
- `init` — initialize `.sugar/` config
- `doctor` — diagnose environment
- And 10+ others

**Audience:** End users, Integrators  
**Priority:** P0  

---

### bcargo (Build Multiplexer)

**Script:** `bin/bcargo`  
**Purpose:** Invokes `cargo` while coordinating cross-kit lifting and testing  
**Usage:** `bcargo build`, `bcargo test`, etc. (falls through to cargo + lifters)  

**Audience:** End users (building Sugar-instrumented workspaces)  
**Priority:** P1  

---

### cargo-sugar, cargo-sugar-lift (Cargo Plugins)

**Binaries:** `cargo-sugar`, `cargo-sugar-lift`  
**Usage:** 
- `cargo sugar [subcommand]` — integrates sugar CLI into Cargo
- `cargo sugar-lift` — directly invoke Rust lifter

**Audience:** End users (Rust projects)  
**Priority:** P1  

---

### coretests_sweep, discharge_sweep (Rust Test Coverage)

**Binaries:** `sugar-lift-rust-tests/src/bin/coretests_sweep.rs`, `discharge_sweep.rs`  
**Purpose:**
- `coretests_sweep` — walks Rust stdlib, lifts all test assertions, produces total accounting
- `discharge_sweep` — runs Z3 on lifted assertions, reports discharge metrics

**Output:** Coverage reports, refutation certificates, classification (Dug/Hit/refuted/unclassified)  

**Audience:** Contributors (stdlib coverage audit)  
**Priority:** P2  

---

## Protocol Specifications

Key formal specifications for integrators and architects:

### Core Protocols

| Spec File | Subject | Audience | Priority |
|-----------|---------|----------|----------|
| `protocol/sugar-ir.cddl` | IR formal grammar (CDDL) | Contributors | P0 |
| `protocol/specs/2026-04-30-proof-file-format.md` | .proof CBOR structure | Integrators | P0 |
| `protocol/specs/2026-04-29-correctness-is-a-hash.md` | Content addressing doctrine | Architects | P1 |
| `protocol/specs/2026-04-30-ir-compiler-protocol.md` | Compiler backend protocol | Contributors | P0 |
| `protocol/specs/2026-04-30-lift-plugin-protocol.md` | Lift plugin RPC (legacy; see PEP 1.7.0) | Contributors | P0 |
| `protocol/specs/2026-05-06-extension-protocols.md` | Extension protocol doctrine | Architects | P2 |

### Composition & Bridging

| Spec File | Subject | Priority |
|-----------|---------|----------|
| `protocol/specs/2026-05-09-contract-composition-protocol.md` | Cross-library proof composition | P1 |
| `protocol/specs/2026-05-03-bridge-linkage-protocol.md` | Library boundary bridges | P1 |
| `protocol/specs/2026-05-03-substrate-layers-envelope-header-body.md` | Layered envelope structure | P1 |

### Security & Pinning

| Spec File | Subject | Priority |
|-----------|---------|----------|
| `protocol/specs/2026-05-03-contract-cid-vs-attestation-cid.md` | CID distinctness | P1 |
| `protocol/specs/2026-05-03-multi-dimensional-pinning.md` | Rank-3 pinning (contract/witness/binary) | P2 |
| `protocol/specs/2026-05-06-effect-discharge-classification.md` | Effect outcome taxonomy (Dug/Hit/refuted/unclassified) | P1 |

### Language & Dialect Support

| Spec File | Subject | Priority |
|-----------|---------|----------|
| `protocol/specs/2026-04-29-per-language-kit-standard.md` | Kit authoring standard | P1 |
| `protocol/specs/2026-04-30-ir-formal-grammar.md` | IR grammar and canonicalization | P0 |
| `protocol/specs/2026-04-29-ts-ir-language.md` | TypeScript IR binding | P2 |

---

## Extension Points for Integrators

### Writing a New Language Kit

**Steps:** See `./docs/contributing/writing-a-kit/01-conformance-first.md` onwards (5-step tutorial)

**Core Deliverables:**
1. Canonicalizer — byte-deterministic canonical form
2. Lifter — AST walk → IR JSON via `libsugar-rpc::AdapterLifter` trait
3. Proof envelope builder — call `sugar-proof-envelope` APIs
4. LSP server (optional) — extend base LSP for IDE integration
5. Self-application — contracts over the kit itself

**Reference Implementations:** Rust, Python, Java kits in `implementations/`

---

### Writing a New Lift Adapter

**Steps:** See `./docs/contributing/writing-a-lift-adapter/01-pick-a-source-library.md` onwards (3-step guide)

**Core:**
1. Implement `libsugar-rpc::AdapterLifter` trait
2. Discover source (files, AST parse, contract patterns)
3. Emit canonical-JSON mementos matching `sugar-ir-types` shapes
4. Call `run_server()` to spawn JSON-RPC server
5. Register plugin in `.sugar/lift/<name>/manifest.toml`

**Examples:** Rust contracts, pytest, hypothesis, kani, proptest adapters

---

### Writing a New IR Compiler Backend

**Steps:** Not yet in formal tutorial (contributor-only for now)

**Core:**
1. Implement `sugar-ir-compiler::IrCompiler` trait
2. Accept JSON IR formula, target dialect name
3. Compile to target language (SMT-LIB, Lean, Coq, Maude, etc.)
4. Return `CompiledFormula` with preamble, body, free_vars, opacity_manifest
5. Call `run_server()` or register as in-process compiler
6. Register plugin in `.sugar/ir-compilers/<name>/manifest.toml`

**Examples:** Z3 (SMT-LIB), Lean 4, Coq, Maude backends

---

## Key Types & Patterns

### Content Addressing

All artifacts (proofs, mementos, contracts, formulas) are **content-addressed by BLAKE3-512**. The canonical form is:

```
blake3-512:<128 lowercase hex digits>
```

Computed via `sugar-canonicalizer::blake3_512_of()` over deterministically canonicalized bytes (RFC 8785 JCS).

### Proof Envelope Structure

A `.proof` file is a CBOR-encoded bundle with:
- Manifest: array of mementos (contracts, bridges, orchestration records)
- Signatures: Ed25519 signatures over JCS-canonicalized subsets
- CID: BLAKE3-512(JCS(envelope)) as filename

APIs: `sugar-proof-envelope::build_proof_envelope()`, `ProofGraph`

### Contract Memento Shape

```json
{
  "kind": "contract",
  "name": "original_name#blake3-512:...",
  "outBinding": "out",
  "pre": { ... ir-formula ... },
  "post": { ... ir-formula ... },
  "inv": { ... ir-formula ... }
}
```

### Effect Discharge Classification

When a proof obligation is discharged:
- **Dug** — successfully verified by solver
- **Hit** — blocked by an external effect (file I/O, randomness, etc.)
- **refuted** — unsatisfiable (UNSAT certificate proves it impossible)
- **unclassified** — no sugar yet (gap in coverage)

See `protocol/specs/2026-05-06-effect-discharge-classification.md`

---

## Dependency Graph for New Kit Authors

If writing a new language kit, the minimum dependency path is:

1. `sugar-canonicalizer` — JCS + BLAKE3
2. `sugar-ir-types` — contract memento types
3. `libsugar-rpc` — `AdapterLifter` trait + RPC server
4. `sugar-proof-envelope` — .proof signing + CID
5. (Optional) `libsugar` — for composition and advanced features

Python and Java kits **do not depend on libsugar itself** (they have their own runtimes), but they do implement the same protocols.

---

## Open Questions

1. **Go kit public surface** — The Go kit exists but its public API surface is not yet documented here. Intended scope unclear.

2. **LSP server extensibility** — The LSP servers (`sugar-lsp`, `sugar-lsp-rust`, `sugar_lsp`) exist but no trait/plugin interface is formally defined for LSP extensions.

3. **Witness oracle protocol** — `libsugar::witness_registry` and `sugar-lift-rust-cargo-test-witness::witness_rpc` are live but their RPC protocol is not formally documented in `protocol/specs/`.

4. **Policy profile registry** — `libsugar::policy_profile_registry` is exported but no spec or tutorial exists for authoring policies.

5. **Effect propagation semantics** — `libsugar::effect_propagation` module is public but the formal semantics of how effects compose across call chains are not accessible to integrators (internal-only documentation).

6. **C FFI stability** — libsugar exports `cdylib` + `staticlib` for C use, but no C header file (.h) or C API documentation exists; only Rust consumers are documented.

7. **Multi-solver coordination** — `protocol/specs/2026-04-30-multi-solver-protocol.md` exists but no public Rust crate implements the multi-solver registry or coordinator yet.

8. **Conformance harness** — Test conformance fixtures exist in `conformance/` but no public API / documented extension mechanism for adding new conformance suites.

---

## Recommended Reading Order for Integrators

1. **Product orientation:** `./README.md` (overview)
2. **Correctness definition:** `./docs/INVARIANTS.md` (false_discharges==0, silent=0)
3. **For Rust users:** `./examples/rust-coretests-report/README.md` (coverage showcase)
4. **For contributors:** `./docs/contributing/overview.md` (routing table)
5. **For kit authors:** `./docs/contributing/writing-a-kit/01-conformance-first.md` (5-step tutorial)
6. **For lifter authors:** `./docs/contributing/writing-a-lift-adapter/01-pick-a-source-library.md` (3-step guide)
7. **For formal understanding:** `./docs/papers/01-whitepaper.md` then `./docs/papers/02-bluepaper.md` (protocol philosophy)
8. **For security:** `./docs/security/threat-model.md` (attack scope)

---

**Generated:** 2026-06-28  
**Repo:** `/Users/tsavo/provekit/.worktrees/sugar-20260628`

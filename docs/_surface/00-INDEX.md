# Sugar / ProvekIt Documentation Surface Index

## Orientation

Sugar (ProvekIt) is a cross-language **correctness verification product** that ingests vendor source code and tests, lifts them into a canonical first-order logic intermediate representation (ProofIR), discharges obligations through SMT solvers, and produces content-addressed proof artifacts (.proof files). The system enforces two non-negotiable invariants: **false_discharges==0** (no false claims are proven), and **silent==0** (every assertion is accounted for, never dropped). Users ship proofs alongside libraries; consumers verify that compositions are sound before deployment. The documentation surface spans 269 discoverable items across 10 areas: CLI tooling, core concepts, language kits (Rust/Python/Java), proof artifacts and protocols, end-to-end workflows, build/environment setup, public APIs and libraries, 67 runnable examples, CI gates, and configuration reference.

---

## Documentation Surface by Area

| Area | File | Items | Coverage |
|------|------|-------|----------|
| **CLI & Binaries** | [./cli.md](./cli.md) | 36 | 20+ subcommands, IR compilers, RPC services, LSP, build wrapper |
| **Core Concepts** | [./concepts.md](./concepts.md) | 34 | Sugar, ProofIR, Lift, CID, Memento, Federation, Teeth, Totality, Outcomes |
| **Language Kits** | [./kits.md](./kits.md) | 12 | Rust, Python, Java kit architectures; conformance harness |
| **Proof Artifacts & Protocols** | [./artifacts.md](./artifacts.md) | 21 | .proof format, ProofIR, Mementos, Bind-lift entries, Witness packages |
| **End-to-End Journeys** | [./journeys.md](./journeys.md) | 20 | Vendor/consumer/upgrade workflows, cross-language composition, lift adapters |
| **Build & Environment Setup** | [./setup.md](./setup.md) | 13 | Dependencies, quick start, per-lang builds, Make, bcargo, CI, demos |
| **APIs & Protocol Specs** | [./api.md](./api.md) | 43 | libsugar, plugin protocol, IR compilers, lift/emitter framework, kits, tutorials |
| **Runnable Examples** | [./examples.md](./examples.md) | 67 | 48 real library proofs, cross-language demos, technique showcases, fixtures |
| **CI Gates & Invariants** | [./gates_ci.md](./gates_ci.md) | 11 | Teeth test, coretests sweep, conformance, soundness/completeness guards |
| **Configuration & Knobs** | [./config.md](./config.md) | 12 | Solver portfolio, release manifest, kit configs, lift surfaces, env vars |

**Total: 269 items across 10 areas**

---

## P0 Items (Must-Document)

Critical surface that anchors all other documentation:

### CLI & Binaries (9 items)
- `sugar` (main CLI) — **cli.md** — Primary entry point; 20+ subcommands route all user workflows
- `sugar prove` — **cli.md** — Verifies proof discharge; six-stage core gate
- `sugar verify` — **cli.md** — Kit end-to-end verification; discharge + witness check
- `sugar diff` — **cli.md** — Behavioral semver; detects supply-chain changes
- `sugar lift` — **cli.md** — Discovers contracts; core lift dispatch
- `sugar mint` — **cli.md** — Creates signed proof envelopes
- `sugar-lift` / `cargo-sugar-lift` — **cli.md** — Workspace lifter dispatcher
- `sugar-ir-smt-lib` — **cli.md** — Z3 SMT-LIB compiler; discharge backend
- `bcargo` — **cli.md** — Remote build multiplexer for CI parity

### Core Concepts (10 items)
- **Sugar** — **concepts.md** — Uninterpreted subject matter; domain-blind claim anchor
- **ProofIR** — **concepts.md** — Canonical first-order logic IR; language-blind boundary
- **Lift** — **concepts.md** — Deterministic translation to FOL; core verb
- **CID (Content IDentifier)** — **concepts.md** — BLAKE3-512 hash; only identity mechanism
- **Memento** — **concepts.md** — Signed attestation; composable proof step
- **Outcome (Effect Classification)** — **concepts.md** — Trichotomy: Dug/Hit/refuted/unclassified
- **Contract** — **concepts.md** — Pre/post FOL obligation; travels with sugar
- **Implication (Composition Operator)** — **concepts.md** — Edge operator; Hoare's composition rule
- **Kit** — **concepts.md** — Language-specific federation seat
- **Federation** — **concepts.md** — Identical CIDs across languages/time; no hubs

### Language Kits (8 items)
- **Rust Kit Overview & Architecture** — **kits.md** — Reference implementation; libsugar, canonicalizer, lifters, backends
- **libsugar** — **kits.md** — Core reference library; memento, proof envelope, canonicalization
- **sugar-canonicalizer** — **kits.md** — JCS encoder + BLAKE3; byte-determinism anchor
- **sugar-lift** — **kits.md** — Rust workspace lifter; non-rewriting contract discovery
- **Rust Kit (contracts/tests/walk)** — **kits.md** — Full kit: annotations, assertions, AST walking
- **Python Kit Overview & Architecture** — **kits.md** — pytest/unittest lifters, 3 emitters, witness oracle
- **Java Kit Overview & Architecture** — **kits.md** — JUnit/TestNG lifters, JSR-380 recognition
- **Cross-Kit Conformance Harness** — **kits.md** — Byte-deterministic protocol enforcement

### Proof Artifacts & Protocols (4 items)
- **.proof File (Proof Bundle)** — **artifacts.md** — Distribution artifact; CBOR catalog; shipping trust root
- **ProofIR** — **artifacts.md** — Canonical JSON FOL; language-neutral syntax
- **Memento Envelope** — **artifacts.md** — Universal claim wrapper; signature container
- **Bind-Lift Entry** — **artifacts.md** — Plugin output format; function-level contract witness

### End-to-End Journeys (3 items)
- **Vendor Workflow: Ship a .proof** — **journeys.md** — Library maintainer lifts code; ships signed proof
- **Consumer Workflow: Verify Inherited Correctness** — **journeys.md** — Loads vendor proofs; composes; refutes contradictions
- **Upgrade Workflow: Sugar Diff** — **journeys.md** — Behavioral semver; detects blast radius

### Build & Environment Setup (5 items)
- **System Dependencies** — **setup.md** — Platform-specific packages and toolchain pins
- **Quick Start** — **setup.md** — Three-step bootstrap to first demo
- **Per-Language Builds** — **setup.md** — Independent build commands for each kit
- **Make Targets & Orchestration** — **setup.md** — Top-level `make ci`, conformance, test, clean
- **Installing the sugar CLI Binary** — **setup.md** — Cargo install; verification; first command

### APIs & Protocol Specs (12 items)
- **libsugar** — **api.md** — Core Rust library; proof composition, effect discharge, canonicalization
- **sugar-proof-envelope** — **api.md** — CBOR, Ed25519 signing, .proof construction
- **sugar-ir-types** — **api.md** — SERDE auto-generated ProofIR types
- **sugar-canonicalizer** — **api.md** — RFC 8785 JCS + BLAKE3-512
- **Rust Kit (libsugar-rpc, lifters, walk, IR backends)** — **api.md** — Extension points; trait-based protocol
- **Python Kit (libsugar-py, lifters, emitters)** — **api.md** — Full kit libraries and integration
- **Java Kit (AST walker, RPC services)** — **api.md** — Complete kit implementation
- **sugar-cli** — **api.md** — 20+ subcommands CLI orchestrator
- **sugar-ir.cddl** — **api.md** — Formal ProofIR grammar; locked key order
- **Lift Plugin Protocol (PEP 1.7.0)** — **api.md** — JSON-RPC 2.0 plugin interface
- **IR Compiler Protocol** — **api.md** — Backend abstraction for solvers
- **Proof File Format & Content Addressing** — **api.md** — CBOR encoding, CID computation

### Examples (8 items)
- **rust-coretests-report** — **examples.md** — Honest Rust stdlib assertion ledger; 6377 assertions, 74.8% discharged
- **std-core-showcase** — **examples.md** — Point-wise scalar correctness on Rust core
- **serde-json-showcase** — **examples.md** — Real Rust library proof; good/bad contradiction suites
- **regex-showcase** — **examples.md** — Regex correctness; invalid rejection + valid acceptance
- **pandas-showcase** — **examples.md** — Pandas Series.sum() on consistency + witness axes
- **numpy-showcase** — **examples.md** — NumPy rot90 full lifecycle
- **signup-service** — **examples.md** — Ordinary Maven project; real transitive dependencies
- **lsp-plugins** — **examples.md** — Plugin architecture reference; 5+ language examples

### CI Gates & Invariants (6 items)
- **test-rust** — **gates_ci.md** — Acid test; false assertions REFUTED; soundness regression guard
- **test-python** — **gates_ci.md** — Cross-language RPC; byte-determinism enforcement
- **check-no-concept-name** — **gates_ci.md** — Hard law: ban concept hubs; CID-only federation
- **coretests-source-audit** — **gates_ci.md** — Honest assertion classification per-locus
- **false_discharges==0 (soundness invariant)** — **gates_ci.md** — FALSE never proved true
- **silent==0 (completeness invariant)** — **gates_ci.md** — No assertion silently dropped

### Configuration (3 items)
- **Workspace Solver Portfolio Configuration** — **config.md** — Central .sugar/config.toml; solver modes, timeouts, backends
- **Release Artifact Manifest** — **config.md** — sugar-release.toml; binary pins, Cargo.lock closure, coverage gates
- **Per-Project Kit Configuration** — **config.md** — Kit-specific lift surfaces and manifests

---

## Gaps (Missing Documentable Surface)

Critical user needs NOT captured in any area:

1. **IDE/Editor Integration Guide** — How to set up Rust-Analyzer LSP, VSCode extensions, JetBrains plugins; language-specific setup
2. **Performance & Optimization** — Solver timeout tuning, proof caching strategies, parallel verification, memory profiling
3. **Error Handling & Diagnostics** — Interpreting error messages, debugging failed proofs, common failure patterns
4. **Witness Oracle Lifecycle** — Operational guide: how witnesses are captured, cached, invalidated, and re-verified
5. **Multi-Solver Coordination in Practice** — Real examples of portfolio first-wins vs. consensus; solver fallback strategies
6. **Dependency & Version Management** — How Sugar resolves transitive proofs, version ranges, proof deprecation
7. **Upgrade Paths & Migration** — Moving from .proof v1 to v2; schema evolution; backward compatibility
8. **Debugging Composition Failures** — When implication edges fail to discharge; missing premises; opacity obstacles
9. **Custom Solver Integration** — Step-by-step: writing a new IR compiler backend; registering with portfolio
10. **Governance & Contributing** — RFC process, proposal for new lift adapters, review standards, conflict resolution
11. **Proof Artifact Lifecycle** — Versioning, archival, deprecation; how long to keep .proof files
12. **Continuous Verification Integration** — Beyond GitHub Actions: Jenkins, GitLab CI, Cloud Build integration examples

---

## Overlaps (Duplicated Surface)

Items documented in multiple areas that should be unified:

| Item | Areas | Recommendation |
|------|-------|-----------------|
| **Rust Kit** | kits.md, api.md | Keep short overview in kits.md; full API in api.md (link from kits) |
| **Python Kit** | kits.md, api.md | Keep short overview in kits.md; full API in api.md (link from kits) |
| **Java Kit** | kits.md, api.md | Keep short overview in kits.md; full API in api.md (link from kits) |
| **sugar-cli** | cli.md, api.md | Keep CLI subcommands in cli.md; move API/trait docs to api.md; link between them |
| **cargo-sugar** | cli.md, api.md | Keep CLI reference in cli.md (short); detailed API in api.md |
| **Protocol Specs** (Lift, IR Compiler) | artifacts.md, api.md | Move formal specs to api.md; keep protocol overview in artifacts.md |
| **.sugar/config.toml** | setup.md, config.md | Move formal reference to config.md; setup.md links to it |
| **Multi-Solver Portfolio** | setup.md, config.md, api.md | Single reference in api.md (protocol spec); setup links; config links |
| **bcargo** | cli.md, setup.md | Keep bcargo details in setup.md; cli.md only mentions it as a wrapper |
| **Conformance** | kits.md, setup.md, api.md, gates_ci.md | Single conformance section in api.md; others link |

---

## Recommended Documentation Pillars (Top-Level Structure)

Four to eight candidate doc sections that the surface naturally suggests:

### 1. **Getting Started** (entry point for new users)
- Quick start (3-step bootstrap)
- System dependencies
- Installation (sugar CLI, Python kit, Java kit, Rust kit)
- First runnable demo (numpy-vendor or rust-coretests-report)
- Troubleshooting common setup issues

### 2. **Core Concepts & Model** (vocabulary and mental model)
- Sugar, ProofIR, CID, Memento, Contract, Outcome
- Lift, Desugar, Lower, Discharge
- Teeth, Totality, Federation, Kit
- Three-coordinate pinning (name@version, contentHash, proofHash)
- Silent==0, False_discharges==0 invariants

### 3. **User Workflows** (what users do day-to-day)
- Vendor: Ship a .proof (lift → mint → verify → witness)
- Consumer: Verify inherited correctness (load proofs, compose, refute)
- Upgrade: Sugar diff (behavioral semver, blast radius, safe deployment)
- Pre-commit: sugar-check enforcement
- Recognize & Materialize (binding reflection)

### 4. **Integration & Extension** (for library/tool authors)
- Writing a lift adapter (AST walking, IR emission, conformance)
- Implementing a kit (Rust, Python, Java, new language)
- IR compiler backends (Z3, Coq, Lean, Maude, custom)
- Plugin discovery and manifest protocol
- Witness oracle implementation

### 5. **Verification & Composition** (proof discharge and safety)
- Prove: Six-stage verification pipeline
- Verify: Kit end-to-end discharge + witness recomputation
- Compose: Multi-crate implication edges, seam binding
- Multi-solver coordination (portfolio modes, fallback)
- Effect classification (opacity obstacles, discharge requirements)

### 6. **Supply Chain & Security** (threats, pinning, trust)
- Threat model: what Sugar catches, what it doesn't
- Multi-dimensional pinning (contract CID, witness CID, binary CID, Cargo.lock)
- Binary attestation protocol
- Witness oracle trust model (untrusted resolution, recomputable)
- Proof replayability and independent verification

### 7. **Architecture & Reference** (formal specs, protocols, APIs)
- ProofIR grammar (CDDL), protocol specs (Lift, IR Compiler, Composition, Memento)
- Kits and their RPC interfaces
- Configuration cascade (global, project, per-kit)
- All 43 public APIs (libsugar, sugar-cli, protocol traits)
- Solver portfolio protocol (v2)

### 8. **Contributing & Development** (for collaborators)
- CI gates, invariants, and what they catch
- Self-application (Sugar proves Sugar)
- Conformance harness (cross-kit byte-parity)
- Development setup (bcargo, remote builds, multi-solver portfolio)
- Release process and binary pinning

---

## Summary Statistics

- **Total Documentable Items:** 269
- **P0 Items (must-document):** ~68
- **Language Kits Implemented:** 3 (Rust, Python, Java)
- **Runnable Examples:** 67 (48 real proofs + 19 fixtures)
- **CI Gates & Invariants:** 11 critical enforcement points
- **Duplicate Surface Areas (should unify):** 10 item-pairs
- **Missing Documentation Gaps:** 12 critical user journeys

---

## Next Steps for Doc Architects

1. **Consolidate overlaps** (e.g., unify kit docs, move protocol specs to api.md)
2. **Create gap docs** (IDE setup, error diagnostics, solver tuning, contrib guide)
3. **Structure around pillars** (use the 4-8 recommended sections as top-level chapters)
4. **Link all areas** (cross-reference via markdown links; avoid duplication)
5. **Add visual diagrams** (proof DAG, lift pipeline, composition flow, federation model)
6. **Prioritize by audience** (user journey vs. contributor pathway vs. operator)

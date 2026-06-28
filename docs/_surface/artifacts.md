# ProvekIt / Sugar Artifacts & File Formats

On-disk and wire artifacts users and integrators encounter when building, proving, and distributing correctness proofs.

---

## 1. `.proof` File — Proof Bundle

**Kind:** Shipped artifact, protocol-standard distribution format  
**Summary:** Binary proof catalog bundle in CBOR containing all mementos needed to verify software correctness without network access.

**Paths:**
- `/protocol/specs/2026-04-30-proof-file-format.md` (normative spec)
- `/protocol/sugar-ir.cddl` (CDDL schema)

**Structure:**
- **On-disk:** Deterministic CBOR (RFC 8949 §4.2.1) encoding
- **Filename:** `blake3-512_<128-hex-chars>.proof` (CID with `:` → `_` for Windows compat)
- **Contents:** 
  - Catalog memento with embedded member bodies (no dangling CIDs)
  - Per-member CID-to-bytes map; each member's bytes hash to its map key
  - Optional `binaryCid` for supply-chain anchor (matches running binary hash)
  - Optional `metadata` map (tooling-facing, not verification-bearing)
  - Catalog signature (Ed25519 over canonical bytes)
  - Per-member signatures where required

**Produced by:** `sugar mint catalog`, kit self-application workflows  
**Consumed by:** Any conformant verifier (framework-agnostic); typically loaded at package install time  
**Audience:** end-user, integrator  
**Priority:** P0 (core user-facing deliverable)  
**Existing docs:** `./docs/papers/01-whitepaper.md` (executive summary); `./protocol/specs/2026-04-30-proof-file-format.md` (full spec)

**Key design invariants:**
- No external fetches; self-contained + fail-closed
- Filename IS the trust root (CID)
- All CIDs recomputable by verifier
- Embeds all mementos (no references to external proof bundles at resolution time)

---

## 2. `.prove.json` — Proof Discharge Report

**Kind:** Structured proof result / evidence report  
**Summary:** JSON summary of assertion discharge outcomes after running the proof-verification pipeline; includes classification (discharged/violated/refused/unclassified), discharge tiers, per-row evidence.

**Paths:**
- `/examples/rust-witness-showcase/good/.prove.json` (example)
- `/examples/rust-witness-showcase/bad/.prove.json` (example)
- Emitted by: `sugar prove`, `sugar discharge`, witness consensus runners

**Structure (JSON object):**
- **Metadata:**
  - `totalCallsites`: count of assertion sites examined
  - `discharged`: count successfully proven
  - `violations`: count found false (UNSAT)
  - `refused`: count that could not be classified
  - `loadErrors`: list of import/parse errors

- **Discharge Split (tier breakdown):**
  - `panicSafe`: proven via panic-freedom path
  - `reflexive`: proven by syntactic equality (hash tier)
  - `solverSubstantive`: proven by Z3 / SMT substantive reasoning
  - `vacuous`: proven vacuously (unreachable assertion)
  - `hashTier`: proven by CID match (no solver needed)
  - `undecidable`: too complex for solver; resource limit exceeded
  - `falsePass`: (should always be 0; SECURITY invariant)

- **Per-assertion rows (`rows[]` array):**
  - `property`: CID of the property/contract being discharged
  - `propertyCid`: content-address of property formula
  - `status`: "discharged" | "violated" | "refused" | "unclassified"
  - `reason`: human-readable summary (e.g., "witnessed by recompute (kit)")
  - `dischargeMethod`: e.g., "consistency", "solver", "reflexive"
  - `file`, `line`, `callee`: source location (if known)
  - `bridge`: cross-library implication evidence source (if applicable)
  - `panicSite`: boolean; true if this assertion guards a panic locus

- **Call graph (`callEdges[]` array):**
  - Edges between functions for composition analysis

**Produced by:** Rust kit (`coretests_sweep`, `discharge_sweep`, `sugar prove` CLI)  
**Consumed by:** Test dashboards, CI gates, developers reviewing coverage  
**Audience:** end-user, contributor  
**Priority:** P1 (essential for interpreting proof results)  
**Existing docs:** None yet (opportunity for user guide)

**Key invariants:**
- `falsePass` MUST be 0 (security gate; any non-zero is a correctness bug)
- `silent` (unclassified) MUST be 0 for complete audits
- `rows` MUST be exhaustive over assertions encountered

---

## 3. ProofIR — Sugar Intermediate Representation (IR)

**Kind:** Canonical proof term format, language-neutral, SMT-solver-ready  
**Summary:** JSON-serialized first-order logic formulae; abstract syntax for contracts, predicates, and implications, agnostic to source language.

**Paths:**
- `/protocol/sugar-ir.cddl` (CDDL grammar, NORMATIVE)
- `/protocol/specs/2026-04-30-ir-formal-grammar.md` (reference)
- `/implementations/rust/sugar-ir-types/src/lib.rs` (Rust bindings, generated)
- `/generated/rust/ir_types.rs` (codegen output)

**Structure (JSON, locked key order):**
- **Top level:** `Document = [* Declaration]` (array of declarations)

- **Declaration types:**
  - `ContractDeclaration`: `{ kind: "contract", name, outBinding, ?pre, ?post, ?inv }`
    - Pre-condition, post-condition, loop invariant as `IrFormula`
  - `BridgeDeclaration` (v1.1 flat shape): `{ kind: "bridge", name, sourceSymbol, sourceLayer, sourceContractCid, targetContractCid, targetProofCid, targetLayer, ?notes }`
  - `BridgeDeclarationV14` (v1.4 layered): envelope/header/metadata layers for signed attestations

- **IrFormula** (recursive):
  - `Atomic { name, args[] }`: predicate (e.g., `"="`, `"<"`, custom)
  - `And, Or, Not, Implies { operands[] }`: logical combinators
  - `Forall { name, sort, body }`, `Exists { name, sort, body }`: quantifiers

- **IrTerm** (recursive):
  - `Var { name }`: bound variable
  - `Const { value, sort }`: literal constant (Int, Real, Bool, String)
  - `Ctor { name, args[] }`: algebraic constructor (e.g., `List`, `Option`)
  - `Lambda { param_name, param_sort, body }`: function abstraction
  - `Let { bindings[], body }`: let-binding (desugared into term substitution at canonicalization)

- **Sorts:**
  - `Int`, `Real`, `Bool`, `String` (primitive)
  - User-defined algebraic types

**Produced by:** Language-specific lift kits (Rust, Python, Java, etc.)  
**Consumed by:** IR compilers (SMT-LIB, Lean, Coq, Maude backends), verifier, `sugar compose`  
**Audience:** contributor (kit author), integrator (framework extension)  
**Priority:** P0 (core IR; every proof must be reducible to this)  
**Existing docs:** `/protocol/specs/2026-04-30-ir-formal-grammar.md` (normative), no dedicated user guide yet

**Key invariants:**
- Byte-deterministic: identical source → identical canonical JSON (linked to CID stability)
- Locked key order in all objects (per CDDL §14)
- Alpha-equivalence: variable names are syntactic artifacts; canonicalization renames to canonical forms
- Pure logic: no side effects; all effects tracked separately in distinct rows

---

## 4. SourceMemento — Content-Addressed Source Pointer

**Kind:** Memento / metadata artifact  
**Summary:** Lightweight pointer into source code (file, span, function name) plus recomputable content-address hashes of source text and AST template; never carries source bytes.

**Paths:**
- `/implementations/rust/sugar-walk/src/source_oracle.rs` (Rust implementation)
- `/implementations/rust/sugar-lift-rust-tests/src/bin/rust_test_assertions_rpc.rs` (consumer example)

**Structure (JSON, from `source_oracle.rs::SourceMemento`):**
```json
{
  "kind": "source-memento",
  "file": "src/lib.rs",
  "span": {
    "start_line": 4,
    "start_col": 0,
    "end_line": 4,
    "end_col": 20
  },
  "paramNames": ["x", "y"],
  "sourceCid": "blake3-512:...",    // BLAKE3-512(source_body_text)
  "templateCid": "blake3-512:...",  // BLAKE3-512(ast_template JSON)
  "sourceFunctionName": "identity"
}
```

**Fields:**
- `file`: project-root-relative path (forward slashes)
- `span`: 1-based lines, 0-based byte columns (matching syn/proc_macro2)
- `paramNames`: parameter identifiers in declaration order
- `sourceCid`: content-address of function body text (verifier re-reads source and recomputes)
- `templateCid`: content-address of AST template (for structural stability checks)
- `sourceFunctionName`: bare function name (optional; empty if not a named function)

**Produced by:** SourceOracle (Rust kit) during lift  
**Consumed by:** Verifier re-reading source, discharge pipeline for witness correlation  
**Audience:** contributor (kit author)  
**Priority:** P2 (internal implementation detail, not shipped as user-facing artifact)  
**Existing docs:** Inline in `source_oracle.rs`, not in protocol specs yet

**Key invariants:**
- CIDs recomputable by reading source file at (file, span)
- Never embeds source bytes (only hashes)
- Span must match a lexically contiguous region (no multi-line terms)

---

## 5. Memento Envelope — Signature & CID Container

**Kind:** Protocol-standard wrapper for all signed claims  
**Summary:** Universal claim wrapper that binds an evidence body (contract, bridge, verdict, audit, etc.) to a signer and CID via signature; every semantic artifact in Sugar is a memento.

**Paths:**
- `/protocol/specs/2026-04-30-memento-envelope-grammar.md` (v1.1 flat shape, NORMATIVE)
- `/protocol/specs/2026-05-03-substrate-layers-envelope-header-body.md` (v1.4 layered shape, NORMATIVE for new mementos)
- `/implementations/rust/sugar-claim-envelope/src/lib.rs` (Rust types)

**Structure (v1.1 flat, JSON):**
```json
{
  "kind": "contract",  // | "bridge" | "verdict" | "audit" | "deprecation" | ...
  "evidence": {
    "kind": "contract",
    "name": "string",
    "body": { "pre": IrFormula, "post": IrFormula, ... }
  },
  "bindingHash": "blake3-512:...",      // hash of (kind, evidence)
  "propertyHash": "blake3-512:...",     // hash of evidence.body (the semantic content)
  "inputCids": ["blake3-512:...", ...], // refs to prior mementos this cites
  "cid": "blake3-512:...",              // self-CID (computed without cid & signature)
  "producerSignature": "...",           // Ed25519 signature over canonical {kind, evidence, bindingHash, propertyHash, inputCids}
  "declaredAt": "2026-06-28T12:34:56Z"
}
```

**Structure (v1.4 layered, 3-part):**
```json
{
  "envelope": {
    "signer": "ed25519:...",
    "declaredAt": "RFC 3339 timestamp",
    "signature": "base64-encoded Ed25519 signature"
  },
  "header": {
    "schemaVersion": "1",
    "kind": "contract",
    "...": "load-bearing substrate fields"
  },
  "metadata": {
    "name": "...",
    "...": "tooling fields, non-normative for verification"
  }
}
```

**Roles (evidence.kind variants):**
- `contract`: pre/post/inv over a function body
- `bridge`: implication from one contract to another (cross-library composition)
- `verdict`: Z3 solver outcome (UNSAT certificate proving implication)
- `audit`: human-reviewed correctness claim
- `deprecation`: mark proof invalid / withdrawn
- `extension-declaration`: plugin-supplied axiom or theory
- `implication`: published witness that formula A implies formula B (hash-keyed cache for discharge)
- `catalog`: root index memento (special, not in roles enum, only in .proof files)

**Produced by:** Lift kits, `sugar mint`, verifier (for verdicts)  
**Consumed by:** Verifier (all code paths), browser (signature verification), `sugar dump`  
**Audience:** integrator, contributor  
**Priority:** P0 (every proof artifact is wrapped)  
**Existing docs:** `/protocol/specs/2026-04-30-memento-envelope-grammar.md` (normative)

**Key invariants:**
- CID recomputable: `blake3_512(canonical(envelope_without_cid_and_signature))`
- Signature covers deterministic JCS-canonical bytes
- `propertyHash` uniquely identifies semantic content (independent of signer / attestationCid)
- `inputCids` must be sorted lexicographically (ORDERING constraint, not in CDDL)

---

## 6. Bind Lift Entry — Bind Pipeline Input Format

**Kind:** Lift result shape for bind pipeline  
**Summary:** Language-specific lift plugin output: per-function metadata (name, signature, location), structural fingerprint, and contract witnesses; input to cluster/name/scope/realize verbs.

**Paths:**
- `/protocol/specs/2026-05-13-bind-ir-lift-result.md` (NORMATIVE v1.1.0)
- `/protocol/specs/2026-05-12-plugin-protocol.md` (wire envelope: plugin protocol)

**Structure (JSON, locked alphabetical key order):**
```json
{
  "attr_post": null,        // LEGACY; new producers omit
  "attr_pre": null,         // LEGACY; new producers omit
  "concept_annotation": "identity",  // from `// concept: NAME` comment
  "file": "src/lib.rs",
  "fn_line": 4,             // 1-based line of `fn` keyword
  "fn_name": "identity",
  "kind": "bind-lift-entry",
  "param_names": ["x"],
  "param_types": ["i32"],
  "return_type": "i32",
  "term_shape": {           // Language-neutral body fingerprint
    "kind": "body",
    "stmts": [{ "kind": "opaque" }]
  },
  "term_shape_cid": "blake3-512:...",  // cluster key
  "witnesses": [            // Contract evidence
    {
      "role": "post",
      "source_kind": "annotation",
      "predicate": IrFormula,
      "line": 4,
      "col": 10,
      "confidence_basis_points": 1000
    }
  ]
}
```

**Fields:**
- `fn_line`, `fn_name`, `file`, `param_names`, `param_types`, `return_type`: function signature
- `term_shape`: structural fingerprint for clustering identical functions across languages
- `term_shape_cid`: `blake3-512:hex(blake3_512(canonical(term_shape)))` — bucket key for Verb 6 (Identify)
- `witnesses`: array of contract witnesses (pre/post/inv/custom), each with `predicate` (IrFormula preferred) or `predicate_text` (legacy)
- `concept_annotation`: editorial hook for name assignment (from preceding comment or decorator)

**Produced by:** Language-specific `kind: "lift"` plugins (PEP 1.7.0) when invoked from `sugar bind`  
**Consumed by:** `cmd_bind` (eight-verb pipeline: Cluster → Name → Scope → Identify → Realize → Witness)  
**Audience:** contributor (kit author)  
**Priority:** P1 (required for bind workflow; new path forward vs legacy annotation-only lifts)  
**Existing docs:** `/protocol/specs/2026-05-13-bind-ir-lift-result.md` (normative spec)

**Key invariants:**
- Byte-deterministic (locked key order, no timestamps/random IDs)
- `term_shape` must have canonical JCS bytes (for CID stability)
- `witnesses[]` is authoritative; `attr_pre`/`attr_post` ignored if witnesses present
- `concept_annotation` is a carrier from source edit into naming, not a proof term

---

## 7. IR Compiler Manifest — Plugin Configuration

**Kind:** Plugin registry / configuration  
**Summary:** TOML manifest declaring an IR compiler plugin (name, version, binary path, supported dialects).

**Paths:**
- `/implementations/rust/sugar-ir-compiler/src/manifest.rs` (Rust type)
- `/protocol/specs/2026-04-30-ir-compiler-protocol.md` §"Plugin discovery"

**Structure (TOML):**
```toml
name = "smt-lib-reference"
version = "0.1.0"
protocol_version = "sugar-ir-compiler/1"
binary = "sugar-ir-smt-lib"              # PATH-resolvable or absolute
dialects = ["smt-lib-v2.6"]              # dialect names this binary serves
```

**Discovery:**
- Location: `~/.config/sugar/ir-compilers/<name>/manifest.toml`
- Each `dialects` entry is a dispatcher index; first manifest claiming a dialect wins
- Missing directory is not an error (empty registry, only built-in compilers available)

**Produced by:** Plugin authors installing custom IR backends  
**Consumed by:** `sugar ir-compiler list`, verifier dispatcher  
**Audience:** integrator (framework extension)  
**Priority:** P1 (required for pluggable solver backends)  
**Existing docs:** `/protocol/specs/2026-04-30-ir-compiler-protocol.md` (full spec)

**Key invariants:**
- `protocol_version` must match running Sugar version (hard error on mismatch)
- `binary` must be resolvable in `$PATH` or be an absolute path
- Dialect names are opaque strings; no namespace (first-wins conflict resolution)

---

## 8. IR Compiler Output — Solver-Native Formula

**Kind:** Translated proof term  
**Summary:** ProofIR lowered to target solver syntax (SMT-LIB for Z3/CVC5, Lean tactic, Coq Gallina, etc.); output from IR compiler plugin after receiving ProofIR input.

**Paths:**
- `/protocol/specs/2026-04-30-ir-compiler-protocol.md` §"Response shapes"
- `/implementations/rust/sugar-ir-compiler-smt-lib/src/bin/sugar_ir_smt_lib.rs` (SMT-LIB backend example)

**Structure (example SMT-LIB v2.6):**
```smt2
(set-logic QF_LIA)
(declare-fun x () Int)
(declare-fun y () Int)
(assert (and (> x 0) (> y 0)))
(check-sat)
```

**Produced by:** IR compiler plugin (invoked by verifier via JSON-RPC)  
**Consumed by:** SMT solver (Z3, CVC5, etc.) for discharge  
**Audience:** integrator (solver plugin author)  
**Priority:** P1 (critical path for discharge)  
**Existing docs:** `/protocol/specs/2026-04-30-ir-compiler-protocol.md` (protocol envelope and methods)

**Key invariants:**
- Deterministic: same ProofIR → same solver input (no randomized variable renaming)
- Solver-agnostic canonicalization first (ProofIR desugars to alpha-canonical form)
- Preserves quantifier structure: no non-prenex conversion (per protocol restrictions)

---

## 9. Lift Result / IR Document — Plugin Output Envelope

**Kind:** Wire format for lift plugin response  
**Summary:** JSON envelope wrapping lift-kit output (array of per-function entries, diagnostics); used by both prove-time and bind-time lifts, distinguished by entry `kind`.

**Paths:**
- `/protocol/specs/2026-04-30-lift-plugin-protocol.md` (legacy, NORMATIVE for v1; wire shape)
- `/protocol/specs/2026-05-12-plugin-protocol.md` (PEP 1.7.0; new plugin discovery & dispatch)
- `/protocol/specs/2026-05-13-bind-ir-lift-result.md` (bind entry kinds)

**Structure (JSON):**
```json
{
  "kind": "ir-document",
  "ir": [
    {
      "kind": "bind-lift-entry",
      "file": "src/lib.rs",
      "fn_name": "foo",
      ...
    },
    {
      "kind": "proof-envelope",
      "body": { ... },
      ...
    }
  ],
  "diagnostics": [
    {
      "level": "error" | "warning",
      "message": "...",
      "file": "...",
      "line": 42
    }
  ]
}
```

**Envelope fields:**
- `kind`: always `"ir-document"` (discriminator for future versions)
- `ir[]`: array of per-function/per-concept entries; each entry's `kind` field determines role
  - `bind-lift-entry`: function ready for bind pipeline
  - `proof-envelope`: (legacy, prove-time) memento ready to mint
  - Other kinds as extended by plugins
- `diagnostics[]`: non-fatal warnings/errors (parser issues, unsupported syntax)

**Produced by:** Language-specific lift plugins (invoked via JSON-RPC by `sugar lift`, `sugar bind`, or `sugar prove`)  
**Consumed by:** Verifier (entry dispatcher), `cmd_bind` (filters by kind), `sugar prove` (assembles mementos)  
**Audience:** contributor (kit author)  
**Priority:** P1 (every lift plugin must emit this envelope)  
**Existing docs:** `/protocol/specs/2026-04-30-lift-plugin-protocol.md` (normative), `/protocol/specs/2026-05-13-bind-ir-lift-result.md` (entry kinds)

**Key invariants:**
- `ir[]` order is stable and deterministic (same source → same order)
- No dangling references; all CIDs in entries are self-contained or cross-reference via inputCids in mementos
- Diagnostics are informational; absence means no errors

---

## 10. Loss Record — Incompleteness Tracking

**Kind:** Metadata artifact / audit log  
**Summary:** Structured JSON recording gaps, unsupported syntax, and coverage limits during lift or discharge; enables targeted follow-up work and transparent accounting of "silent drops."

**Paths:**
- `/protocol/specs/2026-05-12-loss-function-memento.md` (loss function encoding for behavioral loss)
- `/protocol/specs/2026-05-13-bind-ir-lift-result.md` §1.2 (loss-record-contribution in bind entries)

**Structure (JSON, schema-free with typed form field):**
```json
{
  "form": "literal",
  "value": {
    "lossKind": "unsupported-syntax",
    "sourceFile": "src/foo.rs",
    "reason": "macro expansion not supported in witness oracle",
    "proposedRetirement": "macroExpander v0.2.0",
    "count": 5
  }
}
```

**Fields (examples; extensible):**
- `lossKind`: "unsupported-syntax", "incomplete-lift", "solver-timeout", "unknown-type", etc.
- `sourceFile`: file where gap was encountered
- `reason`: human-readable explanation
- `proposedRetirement`: proposed mitigation (tool version, language feature, design change)
- `count`: number of instances of this gap

**Produced by:** Lift kits (during bind-lift or prove-time lift), verifier (during discharge when solver resource-limits are hit)  
**Consumed by:** Coverage dashboards, Verb 6 (Identify) scoping logic, audit reports  
**Audience:** contributor, operator  
**Priority:** P1 (HARD INVARIANT: silent=0 means loss records must exist for everything not discharged)  
**Existing docs:** `/protocol/specs/2026-05-12-loss-function-memento.md` (format for loss functions); `/protocol/specs/2026-05-13-bind-ir-lift-result.md` (loss in bind entries)

**Key invariants:**
- No freeform explanatory strings; all gaps typed and enumerable
- Byte-deterministic (no timestamps in loss value)
- `silent=0` INVARIANT: every assertion not discharged must have a corresponding loss record

---

## 11. Lift Manifest — Kit Configuration for Lift Process

**Kind:** Kit metadata  
**Summary:** TOML manifest configuring a lift kit's behavior: name, version, protocol, language, supported surfaces.

**Paths:**
- `/implementations/rust/sugar-lift/src/lib.rs` (example Rust kit structure; manifest referenced in build)
- `/protocol/specs/2026-04-30-lift-plugin-protocol.md` (discovery and manifest shape)

**Structure (implied TOML, per protocol spec):**
```toml
[lift-kit]
name = "sugar-lift-rust"
version = "0.1.0"
language = "rust"
protocol_version = "sugar-lift-plugin/1"
surfaces = ["prove", "bind"]  # which verbs the kit supports
```

**Produced by:** Kit authors during kit setup  
**Consumed by:** Plugin dispatcher, `sugar lift --list`  
**Audience:** contributor (kit author)  
**Priority:** P2 (kit internal, not shipped in .proof)  
**Existing docs:** `/protocol/specs/2026-04-30-lift-plugin-protocol.md`

---

## 12. Proof Envelope (Legacy) — Per-Concept Proof Claim

**Kind:** Legacy memento variant (superseded by v1.4 layering, but examples exist)  
**Summary:** Self-contained proof artifact wrapping a single concept/contract with witness oracle references; older shape predating the envelope/header/body split.

**Paths:**
- Examples in `/bootstrap/` (historical baseline catalogs)
- Spec: `2026-04-30-memento-envelope-grammar.md` (v1.1 flat shape, includes proof-envelope role)

**Structure (v1.1):**
```json
{
  "kind": "proof-envelope",
  "evidence": {
    "kind": "verdict",
    "property": "blake3-512:...",  // CID of the contract
    "status": "discharged",
    "reason": "Z3 substantive",
    "z3_certificate": "..."
  },
  ...memento fields...
}
```

**Produced by:** Legacy verifier (pre-v1.4); witness consensus runners  
**Consumed by:** Verifier (backward compatibility), proof archivists  
**Audience:** none (informational/historical)  
**Priority:** P2 (legacy, kept for monotonicity)  
**Existing docs:** Historical only

---

## 13. Protocol Catalog — Versioned Format Reference

**Kind:** Master index / registry  
**Summary:** JSON catalog enumerating all protocol specs and their CIDs for a Sugar release; enables version negotiation and graceful upgrade.

**Paths:**
- `/protocol/specs/2026-04-30-protocol-catalog.json` (master index)

**Structure (JSON):**
```json
{
  "formatVersion": "1",
  "releaseVersion": "0.1.0",
  "specs": {
    "proof-file-format": {
      "cid": "blake3-512:...",
      "path": "protocol/specs/2026-04-30-proof-file-format.md"
    },
    "memento-envelope-grammar": {
      "cid": "blake3-512:..."
    },
    ...
  }
}
```

**Produced by:** Release engineering (`scripts/catalog.sh`)  
**Consumed by:** Verifier (version negotiation), test suites  
**Audience:** operator, contributor  
**Priority:** P2 (infrastructure, not user-facing)  
**Existing docs:** Inline in file, not separate spec

---

## 14. Binary Attestation (binaryCid) — Supply-Chain Anchor

**Kind:** Security metadata  
**Summary:** BLAKE3 hash of the compiled binary that produced the proof; enables verifier to reject proofs from tampered, recompiled, or supply-chain-injected binaries.

**Paths:**
- `/protocol/specs/2026-05-02-binary-attestation-protocol.md` (normative)
- `/docs/security/what-binaryCid-catches.md`, `/docs/security/what-binaryCid-does-not-catch.md` (threat model)

**Structure:**
```json
{
  "kind": "catalog",
  "binaryCid": "blake3-512:e04b...",
  ...
}
```

**Verification:**
- Verifier computes hash of running binary (e.g., `sha256sum /usr/bin/sugar`)
- Compares to `binaryCid` field
- REJECTS if mismatch (fail-closed)

**Produced by:** `sugar mint` (when `--include-binary-cid` flag set)  
**Consumed by:** Verifier (optional but recommended check)  
**Audience:** operator, integrator (security-conscious)  
**Priority:** P1 (security-critical, but currently MAY not MUST)  
**Existing docs:** `/protocol/specs/2026-05-02-binary-attestation-protocol.md`

**Key invariants:**
- Supply-chain invariant: proof validity tied to specific compiled binary
- Recompilation or patching invalidates binaryCid check
- Per spec v1.3.0, check is MAY; v1.4.0+ may promote to MUST

---

## 15. Witness Package — Test Execution Evidence

**Kind:** Test result archive  
**Summary:** Signed archive of test execution logs, outputs, and witness oracle records; used by discharge pipeline to prove correctness via automated test re-execution.

**Paths:**
- `/implementations/rust/sugar-lift-rust-cargo-test-witness/src/bin/witness_rpc.rs` (Rust witness oracle RPC server)
- `/implementations/rust/sugar-lift-rust-cargo-test-witness/src/bin/discharge_cli.rs` (discharge verifier client)
- `/protocol/specs/2026-05-14-witness-consensus-promotion.md` (consensus protocol)

**Structure (implied):**
- **Contents:**
  - Per-test output (stdout/stderr)
  - Per-test exit code
  - System logs (if applicable)
  - Content-addressed metadata (file list, hashes)
  - Signer attestation

**Produced by:** Test runner with `--witness` flag (Cargo + witness-oracle integration)  
**Consumed by:** Discharge verifier to re-check test outcomes without re-running  
**Audience:** contributor  
**Priority:** P1 (essential for performant discharge; enables caching)  
**Existing docs:** `/protocol/specs/2026-05-14-witness-consensus-promotion.md` (consensus protocol)

---

# Open Questions

1. **ProofGraph representation:** Is there a `ProofGraph` artifact format shipped to users, or is it purely internal (DAG in verifier memory)? No spec found; clarify scope.

2. **Term shape format:** The `term_shape` structure in bind-lift-entries (§6) could use a standalone reference spec or examples across languages (Rust, Python, Java, C#).

3. **Loss record taxonomy:** Currently extensible with `lossKind` strings; would benefit from an enumerated registry (e.g., LOSS_KINDS.md catalog).

4. **Manifest discovery:** Multiple manifest types (PluginManifest, LiftManifest, IR compiler, lift kit); unify discovery pattern or document per-type locations?

5. **Effect discharge classification (Dug/Hit/refuted/unclassified):** Where is the formal spec? Only found in `/protocol/specs/2026-05-06-effect-discharge-classification.md` (high-level); exact CDDL for verdict rows missing.

6. **Library-sugar-binding-entry format:** Spec in bind-ir-lift-result (§1.2) is normative but no example .prove.json or real integration test shown yet.

7. **Catalog `header.cid` recipe:** Spec says sort member CIDs lexicographically; but no reference implementation or test for stability across multiple enumerations.

8. **Version evolution and monotonicity:** If .proof format evolves to v2, how do v1.x verifiers handle mixed catalogs? Spec says v1 mementos "remain valid forever"; clarify backward-compat guarantees.

9. **Opacity manifest:** Mentioned in `/protocol/specs/2026-05-02-opacity-manifest-grammar.md` but no schema or example; scope unclear.

10. **Discharge method taxonomy:** `.prove.json` lists `dischargeMethod` (e.g., "consistency", "solver", "reflexive"); is this enumerated or open-ended? Where is it defined?

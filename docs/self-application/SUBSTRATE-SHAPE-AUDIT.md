# Phase 4 Substrate Shape Audit

Status: draft for the first Phase 4 slice after Rust v1.

This audit inventory names the pieces that are already substrate-shaped, the
pieces that correctly stay in kits, and the pieces that are currently
Rust-shaped but should become substrate vocabulary before Python parity. It is a
design artifact only. No source schema is changed by this document.

## Invariants

- The CLI and verifier stay language-blind. They may compute over normalized
  proof data and RPC responses, but they do not learn Rust, Python, Java, or Go
  semantics.
- Kits own language semantics. Rust owns rust-analyzer, cargo, Rust AST
  parsing, Rust stdlib partials, and Rust shim catalogs. Python must own the
  Python equivalents.
- Proof bytes cross the RPC seam. The CLI does not read package-local `.proof`
  paths.
- Rust v1 proof compatibility is preserved. Existing Rust proof envelopes and
  release-gate evidence must keep loading. Promotions start as aliases and
  readers; replacing emitted field names or atom names is a migration step.

## Naming Convention

Use explicit concept identifiers for substrate panic-freedom vocabulary:

- `concept:panic-freedom.result.ok`
- `concept:panic-freedom.result.err`
- `concept:panic-freedom.option.some`
- `concept:panic-freedom.option.none`
- `concept:panic-freedom.guard`
- `concept:panic-freedom.choice`
- `concept:panic-freedom.leaf.unwrap`
- `concept:panic-freedom.leaf.expect`
- `concept:panic-freedom.leaf.unwrap-err`
- `concept:panic-freedom.leaf.runtime-failure-site`
- `concept:panic-freedom.effect-locus`

The exact wire spelling can remain a string atom in ProofIR. The important
property is that the identifier is a substrate concept, not the Rust observer or
method spelling. Rust adapters map existing Rust tokens to these concept
identifiers; Python adapters will map Python partials and guards to the same
concept identifiers where the semantics match.

## Backward-Compat Protocol

Phase 4 promotions are staged in three compatibility levels:

1. **Alias-read only.** Add a substrate alias table so readers and doctor can
   interpret existing Rust v1 tokens as concept identifiers. This does not
   change newly minted Rust proof bytes.
2. **Dual-read, optional emit.** Accept both old and new identifiers, and allow
   a kit opt-in to emit concept identifiers for new proofs. Existing Rust v1
   release-gate evidence remains reproducible by default.
3. **Migration-required emit.** Default emission changes field names, atom names,
   or header content. This changes canonical bytes and must land behind an
   explicit migration plan, golden refresh, and release-gate evidence update.

No Phase 4 implementation should default to emitting new Rust concept fields if
that would perturb Rust v1 proof envelope bytes.

## Bucket 1: Substrate Already

These shapes are already appropriate as substrate-level surfaces.

| Surface | Current location | Why it is substrate |
|---|---|---|
| CID and canonical bytes | `libsugar::core::types::Cid`, `sugar-canonicalizer` users | Content identity and canonicalization are language-independent. |
| ProofIR terms and formulas | `libsugar::core::types::Term`, `sugar-ir-symbolic`, `sugar-ir-types` | Terms, atoms, constraints, and sorts are normalized proof data. |
| Contract core fields | `sugar-claim-envelope::MintContractArgs` `pre`, `post`, `inv`, `formals`, `formal_sorts`, `input_cids` | These are normalized contract content, not language syntax. |
| Proof memento envelope | `sugar-claim-envelope/src/lib.rs` layered contract/bridge/implication/witness builders | The envelope is the content-addressed packaging layer. |
| Bridge target pinning | `MintBridgeArgs`, `BridgeCallsite`, `sugar-verifier::resolve_target` | Target contract identity and bundle pinning are language-independent safety properties. |
| `DoctorReport` and `DoctorCheck` | `sugar-cli/src/doctor.rs` | Check IDs, severities, evidence, and `releaseReady` are substrate health reporting. |
| No-silent-failure floor | `sugar-cli/src/floor_runtime_check.rs` | `silentlyDropped`, `falsePass`, `droppedSites`, and `panicCensus` are release invariants over proof data. |
| Release-gate receipt | `sugar-cli/src/cmd_release_gate.rs` | It composes public command surfaces and emits product evidence; it does not encode a language. |
| Dependency proof bytes over RPC | `kit_dispatch::resolve_dependency_proofs`, doctor dependency checks | Once proof bytes cross RPC, the CLI may hash and stage normalized proof data without knowing package paths. |

## Bucket 2: Correctly Kit-Specific

These must stay in kits or kit adapters.

| Surface | Current location | Why it stays kit-specific |
|---|---|---|
| rust-analyzer and linkerd probing | `sugar-cli/src/doctor_oracle.rs`, `sugar-walk/src/ra_oracle.rs`, `sugar-walk/src/ra_daemon_client.rs` | Rust's oracle implementation is not the Python or Java oracle implementation. Doctor consumes adapter evidence only. |
| Cargo/crate/package resolution | `sugar-walk/src/bin/walk_rpc.rs`, Rust project config, Rust shim manifests | Cargo metadata and crate names are Rust kit concerns. |
| Rust AST/HIR/body lifting | `sugar-walk/src/lift.rs`, `walk_rpc.rs`, Rust lifters | Parsing and resolving Rust source is always the Rust kit's job. |
| Rust stdlib shim catalog | `examples/sugar-shim-rust-std/src/lib.rs` | The functions and tests express Rust stdlib algebra. The emitted concepts can map into substrate, but the shim remains Rust. |
| `library:rust-*` shim concept names | `examples/sugar-shim-rust-std/src/lib.rs` | These identify Rust library facts. They may map to substrate concepts, but the original catalog remains kit-owned. |
| Rust native contract annotations | `#[requires]` / `#[ensures]` handling in the Rust lift stack | Attribute parsing and library binding extraction are Rust kit semantics. |
| Resolver binaries and command paths | `.sugar/*/manifest.toml`, `project_config`, `lift_plugin` | Registration is manifest/config-driven; concrete commands remain per kit. |
| Residue meanings like lock poisoning | `.sugar/residue.toml`, `panic_annotations_runtime.rs` rows | The category schema is substrate, but the reason "Rust mutex poisoning" is language/runtime-specific. |

## Bucket 3: Promote

These are the Phase 4 promotion candidates. Each entry includes the current
identifier, proposed substrate identifier, Rust adapter shape, and
compatibility classification.

| Current identifier | Location | Proposed substrate identifier | Rust adapter shape | Compatibility |
|---|---|---|---|---|
| `is_ok(result)` | `sugar-lift-contracts/src/lib.rs`, `examples/sugar-shim-rust-std/src/lib.rs`, `sugar-verifier/src/body_discharge.rs` tests and comments | `concept:panic-freedom.result.ok(result)` | Rust adapter maps `Result::is_ok`, `Result::unwrap`, and `Result::expect` pre/post facts to the concept. Verifier reads aliases so old `is_ok` remains valid. | Alias-read first. Optional dual-emit later. Default Rust emit must not change in v1. |
| `is_err(result)` | same as above, plus `Result::unwrap_err` shim | `concept:panic-freedom.result.err(result)` | Rust adapter maps `Result::is_err` and `Result::unwrap_err` pre/post facts. | Alias-read first. |
| `is_some(result)` | `sugar-lift-contracts`, `sugar-walk`, rust-std shim, verifier tests | `concept:panic-freedom.option.some(result)` | Rust adapter maps `Option::is_some`, `Option::unwrap`, `Option::expect`, and Option-return totality facts. | Alias-read first. Python can map non-None guards here when semantically exact. |
| `is_none(result)` | `sugar-lift-contracts`, rust-std shim | `concept:panic-freedom.option.none(result)` | Rust adapter maps `Option::is_none` and Option totality disjunctions. | Alias-read first. |
| `cf_guarded(guard, value)` | `sugar-walk/src/lift.rs`, `sugar-verifier/src/enumerate_callsites.rs` | `concept:panic-freedom.guard(guard, value)` | Rust adapter continues wrapping dominated branches. Verifier accepts both carrier names and copies the guard atom opaquely. | Dual-read can land without changing Rust emit. Renaming default emit is migration-required. |
| `cf_ite(cond, then, else)` | `sugar-walk/src/lift.rs`, `sugar-verifier/src/enumerate_callsites.rs` | `concept:panic-freedom.choice(cond, then, else)` | Rust adapter emits control-flow choice; verifier descends without treating the condition as a fact. | Dual-read can land first. Default emit migration changes proof bytes. |
| `method:unwrap` | `sugar-walk/src/bin/walk_rpc.rs`, `sugar-verifier/src/enumerate_callsites.rs`, panic census tests | `concept:panic-freedom.leaf.unwrap` | Rust adapter maps `Option::unwrap` and `Result::unwrap` call leaves to the concept plus a type-family precondition concept. Existing bridge `sourceSymbol` remains accepted. | Alias-read first. Bridge source symbol default change is migration-required. |
| `method:expect` | same as above | `concept:panic-freedom.leaf.expect` | Rust adapter maps `Option::expect` and `Result::expect` to the concept plus type-family precondition concept. | Alias-read first. |
| `method:unwrap_err` | rust-std shim and future callsite census | `concept:panic-freedom.leaf.unwrap-err` | Rust adapter maps `Result::unwrap_err` to result-err precondition. | Alias-read first. |
| Kit-declared runtime failure leaves such as Python `raise`, Java `throw`, Go `panic`, TypeScript `throw`, nil dereference, and checked runtime-failure assertions | Non-Rust kit declarations and future effect-locus metadata | `concept:panic-freedom.leaf.runtime-failure-site` | Rust v1 leaves stay parallel for now; no Rust default emission changes. Non-Rust kits map local/subkind diagnostics to this concept while the verifier discharges only over normalized pre/post/guard facts. | Additive Path A. Subkind strings are kit-owned diagnostics, not libsugar taxonomy or verifier semantics. |
| `panicLoci` header field | `sugar-claim-envelope/src/lib.rs`, `sugar-lift/src/lib.rs`, `sugar-verifier/src/enumerate_callsites.rs` | `effectLoci` with `effectKind = concept:panic-freedom` | Rust adapter reads/writes current `panicLoci`; substrate readers can also accept `effectLoci`. Existing `panicLoci` remains the Rust v1 default. | Dual-read is safe. Default dual-write changes envelope bytes, so emit migration is required. |
| `panicSite` bridge callsite field | `BridgeCallsite`, `walk_rpc.rs`, `enumerate_callsites.rs` | `effectSite = concept:panic-freedom` | Rust adapter maps current boolean to the effect-site concept. Verifier can keep bool path while accepting concept metadata. | Dual-read is safe. Default emit migration is required. |
| `panic-site-annotation` diagnostic kind | `panic_annotations_runtime.rs`, Rust kit lift diagnostics | `effect-site-annotation` with `effectKind = concept:panic-freedom` | Rust adapter maps residue and tier annotations for Rust panic leaves. Python adapter can emit same shape for Python exception sites. | Additive reader first. Existing diagnostic kind remains accepted. |
| `bodyDischargeEligible` and `bodyDischargeRefusalReason` | `sugar-claim-envelope/src/lib.rs`, `cmd_self_check.rs`, `walk_rpc.rs` | `dischargePolicy.bodyReduction = allowed/refused` with `reason` | Rust adapter maps current metadata to explicit discharge policy. Verifier and self-check can read both. | Dual-read is safe. Replacing metadata keys is migration-required. |
| `library` metadata value as crate/package string | `MintContractArgs.library`, `walk_rpc.rs`, verifier pool comments | `producerScope = {kind, language, package}` | Rust adapter maps Cargo crate names to producer scope. The old `library` metadata remains for Rust v1 resolution. | Additive only; replacing `library` would break existing bridge resolution. |
| `AnnotationCheckMode`, `FloorCheckMode`, `DoctorMode` parallel enums | `panic_annotations_runtime.rs`, `floor_runtime_check.rs`, `doctor.rs` | shared `GateMode = structural | strict | releaseGate` | Internal Rust CLI adapter maps all three domains to shared mode semantics. | Internal refactor; no proof bytes affected. |
| `oracle.host.*` Rust evidence keys with RA values | `doctor.rs`, `doctor_oracle.rs` | `kit.oracle.host.*` with adapter-declared `hostKind` | Rust adapter declares `hostKind = rust-analyzer`; Python adapter can declare `pyright`, `mypy`, or another host. Doctor validates generic evidence. | Additive report schema field; old evidence keys remain for v1 receipts. |
| `library:rust-*` concepts that have true cross-language meaning | rust-std shim annotations | matching `concept:panic-freedom.*` or domain concept | Rust shim keeps `library:rust-*`; adapter declares which ones refine substrate concepts. | Additive declaration; do not rename shim concepts by default. |

## Contract Shape Audit Notes

### Fields That Should Stay As-Is

- `pre`, `post`, `inv`, `formals`, `formalSorts`, `inputCids`,
  `targetContractCid`, `targetProofCid`, `sourceSymbol`, and `targetSymbol`
  are substrate mechanics. Their values may contain kit-local symbols, but the
  fields themselves are not Rust-specific.
- `bridge_target_proof_cid`, `bridge_self_bundle_cid`, and target pinning logic
  are proof-safety mechanisms. They should not move into a kit.
- `guard_facts` in verifier `CallSite` is correctly opaque. The promotion
  target is the carrier/predicate vocabulary that kits emit, not the fact vector
  itself.

### Fields That Need Additive Alias Readers

- `panicLoci` -> `effectLoci`.
- `panicSite` -> `effectSite`.
- `bodyDischargeEligible` / `bodyDischargeRefusalReason` ->
  `dischargePolicy.bodyReduction`.
- Formula atom names `is_ok`, `is_err`, `is_some`, `is_none` -> concept atom
  aliases.
- Constructor names `cf_guarded`, `cf_ite` -> concept carrier aliases.
- Bridge leaf names `method:*` for partial calls -> concept leaf aliases.

### Fields That Need Declarations Instead Of Renames

- `library` should not be replaced abruptly. It is part of today's resolution
  metadata and is used to avoid same-name cross-target collisions. Add
  `producerScope` later and keep `library` until migration.
- `library:rust-*` concept names should remain kit catalog identifiers. A kit
  declaration can state that `library:rust-result-unwrap` implements
  `concept:panic-freedom.leaf.unwrap`.

## Doctor Cross-Kit Envelope Sketch

The next doctor surface should validate declarations, not Rust implementations.
The declaration should be manifest/config driven and supplied over RPC or a
manifest file by each kit.

Minimum kit declaration:

- `kit.id`, `kit.language`, `kit.version`.
- `rpc.methods`: declared required and optional RPC methods, including
  `resolve_dependency_proofs`, lift, emit, materialize, recognize, and doctor
  probe methods where present.
- `proofResolution`: how the kit self-resolves packaged `.proof` bytes and how
  it reports them over RPC.
- `effectKinds`: supported effect concepts such as
  `concept:panic-freedom`.
- `effectLeaves`: mapping from kit-local leaf names to substrate leaf concepts.
- `guardPredicates`: mapping from kit-local predicates to substrate predicate
  concepts.
- `controlCarriers`: mapping from kit-local control carrier names to substrate
  carrier concepts.
- `oracleHost`: optional language-specific host declaration, with generic
  locatable/ready/engaged/converged evidence.
- `residueCategories`: categories the kit may emit, with whether each is
  irreducible residue or tier-to-close.

Doctor validates:

- The declaration parses and is complete for every configured surface.
- Declared RPC methods are reachable and either supported or explicitly
  optional.
- Declared effect leaves and guard predicates have adapter mappings.
- Any proof bytes returned over RPC derive the reported CID.
- In strict/releaseGate mode, requested oracle hosts and dependency resolvers
  fail closed when unavailable.
- No kit is required to declare Rust-specific behavior unless it is the Rust
  kit.

Doctor vocabulary validation is language-aware. For Rust kit declarations,
doctor validates both the local and concept sides against
`libsugar::concept::*` constants, because Rust owns the current canonical
local panic-freedom vocabulary. For non-Rust kit declarations, doctor validates
the concept side against known substrate concepts and treats local strings as
kit-owned, format-free syntax. Mapping surfaces are checked only against the
configured kit surface for manifest/declaration coherence; doctor does not own
per-language surface registries.

The rationale is that kits own language semantics. Per-language local
vocabulary in `libsugar` would require substrate edits for each new kit and
would violate the language-boundary invariant. Concept identifiers are the
federated substrate identity; local names are language-specific renderings of
that identity. Cross-kit local consistency is deferred to later doctor work.

## Python Parity Target

Python parity at v2 means more than "Python can mint". The v2 claim should be:

- A Python kit, written in Python, lifts Python source/tests/contracts into the
  same ProofIR substrate.
- Python effect sites such as `None` dereference, `KeyError`, `IndexError`,
  `AttributeError`, and failed `assert` participate in
  `concept:panic-freedom` or a sibling exception-freedom concept.
- `sugar self-check`, `sugar doctor`, and `sugar release-gate` produce
  the same shape of K, residue, raw unproven, and floor evidence for a Python
  target.
- The CLI/verifier consume the Python kit through config/manifest/RPC and proof
  bytes, not Python-specific code paths.

Python's first likely consumption set:

- `concept:panic-freedom.option.some` for non-None guards.
- `concept:panic-freedom.guard` and `concept:panic-freedom.choice` for branch
  dominance.
- Effect leaves for exception-producing operations. These may need sibling
  concepts under `concept:exception-freedom` if "panic" is too Rust-loaded for
  Python's operator space.

## Implementation Order After This Audit

1. Add concept alias readers for formula atoms and control carriers. Do not
   change Rust default emission.
2. Add effect-site alias readers for `panicLoci`/`panicSite` while preserving
   Rust v1 fields.
3. Add kit declaration shape for effect leaves, guard predicates, and control
   carriers.
4. Make doctor validate the declaration generically.
5. Start Python parity against the declaration and concept aliases.

## Open Decisions

- Whether the canonical concept namespace should remain
  `concept:panic-freedom.*` or split Python exception safety into
  `concept:exception-freedom.*` with a relation to panic-freedom.
- Whether concept aliases live in a static Rust module, a catalog asset, or kit
  declarations. The language-agnostic invariant prefers kit declarations plus a
  small substrate catalog of concept identifiers.
- Whether old Rust atom names should ever be retired. Retiring them is a
  migration-required change and should not be part of Python parity unless it is
  necessary.

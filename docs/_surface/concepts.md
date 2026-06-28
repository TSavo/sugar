# Sugar: Core Concepts & Vocabulary

> The mental model every reader must understand to work with Sugar effectively.
> Each concept here is a building block; they compose to form the complete system.

---

## Core Primitives

### Sugar
The **subject matter** that an obligation rides on — arbitrary, uninterpreted, content-addressed. Sugar can be anything: a function, a test, an entire codebase, a Wikipedia article. The genius of the model: **sugar is never formalized**. You place a formal obligation (a contract) on something you can never formalize, because the domain lives entirely in the sugar and never enters the solver. Sugar is the asymmetry that makes federation domain-blind and universal.

**Related concepts:** Desugar, boundary, contract  
**Key files:** `/SHARED-LANGUAGE.md` (lines 73–98), `/README.md` (lines 3–14)  
**Audience:** end-user, integrator, contributor  
**Doc priority:** P0

### ProofIR (Proof Intermediate Representation)
The **universal logical form** that lifters emit and the solver understands. ProofIR is first-order logic: atoms (equality, comparison, uninterpreted function calls) plus and/or/not/implies/forall/exists. It is the **only formal vocabulary** in Sugar — language-blind, domain-blind, the same for Rust, Python, Java, and everything else. Vendors' tests and contracts desugar into ProofIR; the IR is the boundary language where all claims meet for composition.

ProofIR is not authored by hand — it is **lifted from source**. The lifter reads vendor tests and assertions and emits ProofIR terms. The canonical form is specified in precise, byte-deterministic grammar; content-addressing applies to ProofIR because two identical claims in different languages produce identical CIDs by construction.

**Related concepts:** Lift, literal floor, sort universe, desugar  
**Key files:** `/protocol/specs/2026-04-29-ir-library.md`, `/protocol/specs/2026-04-30-ir-formal-grammar.md`, `/docs/INVARIANTS.md` (lines 162–206)  
**Audience:** architect, integrator, contributor  
**Doc priority:** P0

### ProofGraph (Proof DAG)
A **directed acyclic graph** where:
- **Nodes** = the program's operations (calls, tests, assertions)
- **Node labels** = contracts (pre/post obligations on each operation)
- **Edges** = implications (`post → pre` between producer and consumer)
- **Root** = the top-level postcondition
- **Leaves** = base preconditions (⊤, the empty conjunction)

A program verifies when **every edge discharges** — every composition obligation holds. The whole program is correct when traversing from leaves to root, every edge checks out. The proof DAG IS the mathematical proof; it is the data structure form of a formal inductive argument. Each memento in the DAG is a proof step.

**Related concepts:** Memento, implication, composition, Outcome  
**Key files:** `/protocol/specs/2026-04-29-correctness-is-a-hash.md` (lines 13–27), `/SHARED-LANGUAGE.md` (lines 125–132)  
**Audience:** architect, integrator  
**Doc priority:** P0

### Lift
**Two parts:** (1) **Contract lift** — read vendor tests/assertions and emit contracts into ProofIR. (2) **Sugar lift** — read sugar bodies (function code) and emit sugar surface text. Lift is a **function, not a relation** — one source surface must desugar to exactly one contract (determinism is forced by content-addressing). Multiple surfaces can lift separately and compose/conjoin.

The lifter is **per-language, per-platform**. It speaks RPC to the CLI. It emits language-agnostic ProofIR. After the RPC line, everything is language-blind.

**Related concepts:** Desugar, lower, contract, ProofIR, kit  
**Key files:** `/SHARED-LANGUAGE.md` (lines 6–18), `/docs/INVARIANTS.md` (lines 112–142)  
**Audience:** contributor, integrator  
**Doc priority:** P0

### Desugar
**Synonym for "lift" when emphasizing desugaring.** A source form (a test, an annotation, a function signature) is sugar for an underlying logical form (ProofIR). Desugaring means **reading the sugar and emitting the FOL** it represents. Every language is sugar; the language-blind part sees only the desugared form. Desugaring is unidirectional and lossless — you extract the logical content without loss.

**Related concepts:** Lift, sugar, ProofIR  
**Key files:** `/docs/INVARIANTS.md` (lines 33–42)  
**Audience:** architect, contributor  
**Doc priority:** P1

### Lower
**Inverse of lift.** Takes ProofIR and emits it as native artifacts: tests, annotations, gates, etc. Lower is **plural** (a relation) — one contract can lower to many faithful native forms simultaneously. Lower has **two parts:** (1) **Contract lower** (formerly called "emit") — turn ProofIR contracts into native tests/annotations. (2) **Sugar lower** (formerly called "materialize") — write sugar into boundary bodies (library call sites).

The kit implements multiple lowerers; which ones run is declared in config (`lift/manifest.toml`). Lowering is how proofs reach the developer as red squigglies, gate failures, or test assertions.

**Related concepts:** Lift, emitter, materializer, contract, sugar  
**Key files:** `/SHARED-LANGUAGE.md` (lines 12–32), `/docs/INVARIANTS.md` (lines 112–142)  
**Audience:** integrator, contributor  
**Doc priority:** P1

### CID (Content IDentifier)
A **deterministic, fixed-length hash** (currently blake3-512, 64 bytes) of the canonical form of an artifact. Two artifacts with the same CID are byte-identical and claim the same properties. CIDs are the **only identity mechanism** — there are no hubs, no version numbers, no concept registries. A CID **pins everything**: source tree, contract, proof, witness, binary. Changing **any part** changes the CID.

The CID is encoded with its algorithm prefix (e.g., `blake3-512:…`) so migration is built-in; the address names its own hash. This is **not a storage optimization** — it is a cryptographic commitment that correctness claims never silently drift.

**Related concepts:** Content-address, memento, proof hash, property hash  
**Key files:** `/protocol/specs/2026-04-29-correctness-is-a-hash.md` (lines 29–40), `/docs/INVARIANTS.md` (lines 220–246)  
**Audience:** end-user, integrator, contributor  
**Doc priority:** P0

### Memento
A **signed attestation** that a property holds. Mementos are content-addressed (they have CIDs). They compose via **inputCids** — a memento naming other mementos it depends on. The proof DAG is built from mementos; each is a proof step. A memento includes:
- The property claimed (via its propertyHash)
- The binding(s) it was verified under
- The verdict: `holds` or `violated`
- Producer identity (who attested it)
- Signatures (ed25519)
- Canonicalized wrapper (JCS-encoded envelope)

Mementos accumulate in a pool. Re-verification checks mementos against a consumer's own producer pool; mismatches surface. A memento that does not recompute to its pinned CID is refused loudly.

**Related concepts:** Verdict, witness, ProofGraph, CID, property hash  
**Key files:** `/protocol/specs/2026-04-30-memento-envelope-grammar.md`, `/protocol/specs/2026-04-29-correctness-is-a-hash.md` (lines 640–667)  
**Audience:** integrator, contributor  
**Doc priority:** P0

### Outcome (Effect Classification)
The **trichotomy of verification results:**

1. **Dug** — a claim is proved discharged. The solver says it is satisfiable (SAT) and consistent with the rest of the proof. The edge holds; composition proceeds.

2. **Hit** — a claim hits an obstacle. An effect (read, write, unsafe, panic, unresolved call, opaque loop, early return, closure capture, aliasing, etc.) blocks the claim from discharging. The obstacle requires a memento (a separate proof) to discharge. Until the memento appears, composition refuses.

3. **Refuted** — a claim is contradicted. The solver says it is unsatisfiable (UNSAT). This is a **true bug** — the claimed contract is false. The proof is refused and the bug is reported.

4. **Unclassified** — the claim was never lifted. No contract was produced for this code path (not a gap — no assertion to lift). Silent by design (invariant 2: we see only claims).

**Related concepts:** Teeth, discharge, refusal, effect, memento  
**Key files:** `/protocol/specs/2026-05-06-effect-discharge-classification.md`, `/docs/INVARIANTS.md` (lines 69–81)  
**Audience:** architect, integrator  
**Doc priority:** P0

### Teeth
The **guards and constraints** that keep a proof honest — i.e., that prevent false discharge. Teeth are the **refusing power**. Without teeth, a proof gate is inert (casing without closure); with teeth, the gate blocks invalid compositions. Teeth are enforced through:
- **Contradiction detection** (UNSAT certificates from the solver)
- **Effect classification** (unresolved obstacles blocking composition)
- **Totality checking** (zero unclassified claims)
- **Signature validation** (recomputed CIDs refusing mismatched bytes)

A proof with teeth refuses false claims loudly. The absence of teeth is worse than missing a proof — it is a **false light** that claims safety where none exists. This is why `false_discharges == 0` is a **security invariant**.

**Related concepts:** Refusal, contradiction, falsePasses, Outcome (refuted), totality  
**Key files:** `/docs/INVARIANTS.md` (lines 66–81, 248–330), `/project_sugar_correctness_isomorphic_to_total_accounting.md`  
**Audience:** architect  
**Doc priority:** P0

### Totality
**Complete accounting** of every claim in a codebase. Totality means:
- Every assertion that exists is lifted (or refused and named).
- Every call edge that exists is composed (or blocked and named).
- No silent gaps (unclassified = 0).
- Every node in the proof DAG is accounted for.

Totality is verified by walking the entire source AST and counting: total assertions = lifted + refused. If they don't match, the ledger is incomplete. Totality is a **structural invariant** — not optional, enforced at the gate, non-negotiable. A proof that doesn't account for everything is dishonest.

**Related concepts:** Silent, accounting, teeth, INVARIANTS (§0)  
**Key files:** `/docs/INVARIANTS.md` (lines 44–57), `/project_provekit_coretests_total_accounting.md`  
**Audience:** architect, integrator  
**Doc priority:** P0

### Literal Floor
The **ground level** of the proof where the solver touches reality — the **primitive terms** that the solver directly interprets: integer literals, boolean constants, known-scalar call results, and FOL primitives (`=`, `<`, etc.). Everything above the floor (user types, complex calls, abstract domains) is **uninterpreted** — handled by the solver's EUF (Extensional Uninterpreted Functions) theory.

The floor is **where the proof grounds out**. Z3 knows `5 + 3 == 8` at the floor; above the floor, Z3 knows only what you tell it (via EUF rows: `call:foo(a) == result` is a constraint, not a computation). Lifters emit constraints that bind user-level calls to the floor, and the solver verifies the binding is sound.

**Related concepts:** Sort universe, primitives, EUF, universe  
**Key files:** `/docs/INVARIANTS.md` (lines 192–210), `/SHARED-LANGUAGE.md` (lines 79–90)  
**Audience:** architect, contributor  
**Doc priority:** P1

### Universe (Sort Universe)
The **type hierarchy** that ProofIR uses: `Int`, `Real`, `Bool` — **platform-free, abstract**. Number values (whether from Rust `i32` or Python `int`) all map to `Int` or `Real`. Platform intrinsics (bit-width, wrapping, IEEE semantics) are NOT IR sorts; they are **refinements over the base sorts**, expressed as FOL constraints in the kit layer.

Example: Rust `u8` → `Int` with the refinement `0..=255`; `i32::wrapping_add` → `Int` with the constraint `(a+b) mod 2^32`. This separation allows the CLI to stay platform-blind (it handles only `Int`/`Real`/`Bool` + FOL) while the kit layer preserves the semantic guarantees. Kits federate because they emit the **same canonical base sorts**; platform details ride as constraints.

**Related concepts:** Literal floor, ProofIR, kit, refinement  
**Key files:** `/docs/INVARIANTS.md` (lines 192–217), `/protocol/specs/2026-04-29-ir-library.md` (lines 111–160)  
**Audience:** architect, contributor  
**Doc priority:** P1

### Discharge / Verify
**Discharge** = the solver's act of proving a contract is satisfiable. The formula is fed to Z3 (or another solver), and if Z3 says SAT, the contract **discharges**. Discharge is consistency checking — "is this claimed contract internally coherent?"

**Verify** (a broader term) = the full act of confirming a proof: (1) signature checking (ed25519 over the memento CID), (2) CID recomputation (blake3 over canonical bytes), (3) witness recomputation (re-running the test and hashing its output), (4) discharge via solver.

Both are **recomputable** — anyone with the same software can re-verify independently. You trust nothing; you verify everything.

**Related concepts:** Refusal, consistency, Outcome (Dug), solver  
**Key files:** `/README.md` (lines 193–200), `/docs/INVARIANTS.md` (lines 156–159)  
**Audience:** end-user, integrator  
**Doc priority:** P1

### Refusal
When verification **refuses** to proceed — a hard stop. Refusal happens when:
- A contract is **contradictory** (UNSAT from the solver — a real bug).
- An **opaque obstacle** blocks composition and no memento discharges it (effect classification).
- A **signature or CID doesn't recompute** (tampering or oracle failure).
- **Totality is violated** (silent gaps exist).

Refusal is **not a judgment call**; it is mechanical. A refused proof cannot be bypassed; the default posture is fail-closed. This is why refusal is the teeth — it catches false claims before they propagate.

**Related concepts:** Teeth, Outcome (refuted/Hit), discharge, contradiction  
**Key files:** `/docs/INVARIANTS.md` (lines 69–81, 253–254), `/protocol/specs/2026-05-06-effect-discharge-classification.md` (§4)  
**Audience:** end-user, integrator  
**Doc priority:** P1

---

## Composition & Binding

### Contract
A **pre/post obligation tied to a specific sugar**. Contracts are **FOL formulas** emitted by the contract lifter from the vendor's tests. A contract has:
- A **scope** (which function/module it governs).
- A **precondition** (what must be true on entry).
- A **postcondition** (what must be true on exit).

Contracts **never travel naked** — they co-travel with their sugar (the function being contracted). When you materialize the sugar at a boundary, the contract propagates with it. This is the **binding, dischargeable obligation**: the contract is the lien on the sugar; you cannot take the subject free of the obligation.

**Related concepts:** Implication, boundary, sugar, seam  
**Key files:** `/SHARED-LANGUAGE.md` (lines 49–71), `/docs/INVARIANTS.md` (lines 44–57)  
**Audience:** end-user, integrator  
**Doc priority:** P0

### Implication (Composition Operator)
The **edge operator** of the proof DAG. When two operations compose (`A(B())`), the only proof obligation is:

```
post(B) → pre(A)
```

This is **Hoare's rule of composition** — the producer's postcondition must imply the consumer's precondition. Implications are the **durable layer**: a proven implication is a lemma, reusable forever, federated by CID. Terms and contracts are local; implications are the composable, content-addressed links.

Implications are minted by `cmd_implicate` at every call edge. The graph of terms + contracts + implications is the proof DAG.

**Related concepts:** Composition, contract, seam, bridge  
**Key files:** `/SHARED-LANGUAGE.md` (lines 100–132), `/docs/INVARIANTS.md` (lines 126–154)  
**Audience:** architect, integrator, contributor  
**Doc priority:** P0

### Boundary
A **realization site where sugar materializes**. The boundary is where the library author's sugar meets the consumer's code. At the boundary, the sugar's contract comes due — this is where **red squigglies fire** in the LSP, where gates refuse, where obligations become debts. A boundary is the seam between proof domains.

The library author supplies the sugar; the user has boundaries where the sugar is materialized. A library might define `search(q)` that returns sorted results; each call to `search()` in the consumer's code is a boundary; the contract `sorted` propagates to each boundary.

**Related concepts:** Seam, sugar, contract, LSP, FFI  
**Key files:** `/SHARED-LANGUAGE.md` (lines 38–43), `/README.md` (lines 81–105)  
**Audience:** end-user, integrator  
**Doc priority:** P1

### Seam (Call Edge)
A **locus of composition** — a place where two contracts meet. A seam is not just function calls; it is any boundary: a function call, an `.await`, a channel send, a lock acquire, an FFI crossing, a version bump. Every seam carries a **post → pre obligation**. The lifter's job (the implication lifter) is to extract every seam and emit the obligation.

All seams are unified — async, FFI, sync, locks — they are one primitive, because Sugar **doesn't model what seams do** (that is an effect, which we refuse to formalize). The seam simply carries a contract from producer to consumer.

**Related concepts:** Boundary, implication, effect, call edge  
**Key files:** `/docs/INVARIANTS.md` (lines 83–91), `/SHARED-LANGUAGE.md` (lines 156–191)  
**Audience:** architect, contributor  
**Doc priority:** P1

### Bridge (Cross-Language Binding)
An **edge that binds a caller's callsite to a callee's contract across language boundaries**. A bridge is a CallEdgeDecl that records:
- The caller's contract CID (sourceContractCid).
- The callee's symbol + contract CID (targetSymbol, targetContractCid).

The bridge works because both lifters emit **byte-identical canonical forms** for the same logical content — the symbol resolution, the sort encoding, the FOL bytes. The CID **is** the cross-language identity; no concept layer is needed. A bridge refutes if the caller's post contradicts the callee's pre, just like an intra-language edge.

**Related concepts:** FFI, seam, symbol resolution, federation  
**Key files:** `/docs/INVARIANTS.md` (lines 234–246), `/SHARED-LANGUAGE.md` (lines 156–191)  
**Audience:** architect, integrator  
**Doc priority:** P1

---

## Witness & Verification

### Witness
The **execution proof** — the bytes that demonstrate a program actually runs and produces the claimed postcondition. A witness is:
- The output of running the program (test log, coverage report, execution trace).
- Content-addressed via blake3 (the witnessHash).
- Signed by a kit-specific oracle (who re-ran the code).

The **witness lifter (kit oracle)** resolves the witness by re-running the program and hashing its output. Verification recomputes the blake3 of the resolved bytes against the pinned witnessHash — a body that does not recompute is a **broken oracle**, refused. This is correctness's 4th slot: the program satisfies its spec, witnessed.

**Related concepts:** Correctness tuple (spec + coherence + satisfaction + witness), oracle, memento  
**Key files:** `/docs/INVARIANTS.md` (lines 135–159), `/README.md` (lines 185–200)  
**Audience:** integrator, contributor  
**Doc priority:** P1

### Sworn Statement
A **claim made explicitly in code** — an assertion, a test, a contract annotation, a function signature. A sworn statement is distinguished from a **convention** (code that is right because nothing says it shouldn't be). Sugar only sees sworn statements; it is silent on conventions. This is why "no assertion = no row = silent by design." The sworn statement is what gets lifted into a contract.

**Related concepts:** Contract, claim, assertion, silent  
**Key files:** `/README.md` (lines 31–39), `/docs/INVARIANTS.md` (lines 44–57)  
**Audience:** end-user, integrator  
**Doc priority:** P1

---

## Federation & Kits

### Kit
A **language-specific implementation** of the Sugar model. Each kit (Rust, Python, Java, Go, etc.) implements:
- **Contract lifter** — reads vendor tests, emits ProofIR contracts.
- **Sugar lifter** — reads sugar bodies, emits sugar surface.
- **Implication lifter** — reads call edges, emits `post → pre` obligations.
- **Bridge lifter** — reads FFI/cross-language calls, emits cross-language edges.
- **Witness lifter (oracle)** — re-runs programs, witnesses outputs.
- **Emitters** — lower contracts back to tests, annotations, gates.

Every kit speaks **RPC to the Rust CLI** and emits **language-agnostic ProofIR**. After the RPC line, everything is language-blind. A kit is a **federation seat** — two kits at the same table, speaking one IR language, get identical CIDs by construction.

**Related concepts:** Lift, ProofIR, federation, dialect, Rust CLI  
**Key files:** `/SHARED-LANGUAGE.md` (lines 193–200), `/docs/INVARIANTS.md` (lines 112–159)  
**Audience:** contributor, integrator  
**Doc priority:** P0

### Federation
The **property that identical logical content produces identical CIDs across languages, teams, and time**. Federation is enabled by:
- **Canonical form** — every kit emits the same byte-exact ProofIR for the same claim.
- **Content-addressing** — the CID is deterministic from the canonical form.
- **No hubs** — identity is the CID itself, not a naming service.

Two Rust functions and a Python function can all claim the same property; their lifted contracts hash to the same CID; composition proceeds across language boundaries without a registry or concept layer. Federation is structural; it falls out from byte-identical CIDs.

**Related concepts:** Kit, CID, bridge, cross-language composition  
**Key files:** `/docs/INVARIANTS.md` (lines 220–246), `/SHARED-LANGUAGE.md` (lines 156–191)  
**Audience:** architect, integrator  
**Doc priority:** P0

### Dialect
A **language-specific label** for a family of sugars under the same vendor. Dialects represent **federation seats** at the table. A dialect is a **newtype String** — a content-addressed name for a language/kit/library combination. Different dialects federate through CID equivalence; no central concept hub is needed.

Example: `rust:tokio`, `python:asyncio`, `go:select`. Each dialect emits the same canonical base sorts and FOL atoms for the same logical concepts, so cross-dialect composition is CID-driven.

**Related concepts:** Kit, federation, CID  
**Key files:** `/project_provekit_dialect_memento_catalog.md`  
**Audience:** architect, contributor  
**Doc priority:** P2

---

## Effects & Opacity

### Effect
A **side behavior** that blocks composition until discharged. Effects include:
- **Unconditionally blocked:** Reads, writes, I/O, unsafe code, panics (v1 cannot model these).
- **Memento-required:** Opaque loops, early returns, closure captures, raw-pointer provenance, atomic access, aliasing, destructors (dischargeable via external mementos).
- **Informational:** Statically-known atomic ordering, trivial/structural drops (never block).

An effect is a **honest obstacle** — the lifter knows the effect exists but cannot resolve it locally. The verifier refuses composition until a memento (a separate proof by an authority) discharges it. Effects are the **primary extensibility mechanism** — new effects can be added without changing the core substrate.

**Related concepts:** Memento, Outcome (Hit), opacity, discharge  
**Key files:** `/protocol/specs/2026-05-06-effect-discharge-classification.md`, `/implementations/rust/sugar-walk/src/contract.rs`  
**Audience:** architect, integrator, contributor  
**Doc priority:** P1

### Opacity
A **claim whose implications cannot be resolved locally**. Opaque functions (e.g., loops with unknown invariants, closures capturing external state) block composition because their behavior cannot be verified without additional proof. Opacity is not a refusal — it is an **honest hold** waiting for a memento that supplies the missing contract.

The opposite of opacity is **transparency** — a function whose behavior is fully determined by its inputs and is verifiable locally. Opacity is the main reason effects exist; it is the category of obstacles that can be discharged.

**Related concepts:** Effect (Memento-required), memento, bridge  
**Key files:** `/protocol/specs/2026-05-06-effect-discharge-classification.md` (§3.2)  
**Audience:** architect, integrator  
**Doc priority:** P1

---

## Execution & Distribution

### Property Hash
The CID of a **claimed property** — what the property hash doesn't include are the bindings (variables, concrete values). A `propertyHash` exists the moment the lifter computes it. A `verdict` (holds/violated) is optional — it is minted only when a producer attests the claim. An unverified propertyHash is first-class; it exists in the DAG with no verdict attached. This is **lazy evaluation** applied to proofs.

**Related concepts:** CID, memento, verdict, unverified  
**Key files:** `/protocol/specs/2026-04-29-correctness-is-a-hash.md` (lines 746–826)  
**Audience:** architect, integrator  
**Doc priority:** P1

### Proof Hash
The CID of the **entire proof DAG root**. It identifies all the properties claimed and their verifications. Three coordinates pin an artifact: `(name@version, contentHash, proofHash)`. Changing any contract or verdict changes the proof hash; library upgrades are readable as proof-hash diffs, not changelog prose.

**Related concepts:** CID, ProofGraph, binding hash  
**Key files:** `/protocol/specs/2026-04-29-correctness-is-a-hash.md` (lines 223–285)  
**Audience:** end-user, integrator  
**Doc priority:** P1

### Concept (Shared Tag)
A **name shared among multiple sugars** — e.g., `json_encode`, `sorted`, `authenticated`. Whether two sugars under the same concept mean the **same FOL** is entirely the **vendor's decision**. Sugar sets nothing. Equivalence is pinned via three-axis pinning (contract CID + witness CID + binary CID), not through a concept registry.

**Related concepts:** Contract equivalence, federation, three-axis pinning  
**Key files:** `/SHARED-LANGUAGE.md` (lines 44–46, 202–210)  
**Audience:** integrator, architect  
**Doc priority:** P1

### Solver
The **discharge engine** — a theorem prover that verifies ProofIR formulas are satisfiable. Solvers include Z3, CVC5, Vampire, Lean, Coq, Maude. The substrate does not prescribe a single solver; it is solver-agnostic. A contract may be discharged by multiple solvers for redundancy; disagreement surfaces as competing mementos in the DAG, weighted by producer reputation.

The solver is part of the **trusted computing base (TCB)** but not a trust anchor — it is a **recomputation**, not an oracle. You trust your own local re-verification, not the solver's authority.

**Related concepts:** Discharge, producer, TCB, contradication  
**Key files:** `/SHARED-LANGUAGE.md` (lines 233–237), `/docs/security/solver-trust.md`  
**Audience:** architect, integrator  
**Doc priority:** P1

---

## Open Questions

1. **Does the LSP drive the solver live at boundary, or is squiggle a structural check with full discharge at verify/CI time?** (T to settle; mentioned in `/SHARED-LANGUAGE.md` line 245)

2. **How are "unverified" propertyHashes handled in practice?** The spec describes lazy evaluation, but operational guidance on deferral policies per consumer type is limited.

3. **What is the exact scope of "Totality"** in multi-crate or workspace scenarios? Is per-file, per-crate, or whole-workspace required?

4. **Cross-equivalence claims** (e.g., "TS parseInt and C++ atoi are behaviorally equivalent") — what producers can discharge these? LLMs? Cross-language formal provers?

5. **What is the operational protocol for handling a "broken oracle"** that fails to recompute its witness? How is this surfaced and resolved?

6. **Catalog vs Protocol Record** — the spec mentions an "infection" (delete central catalog), but how does kit-discovery work in practice without *any* registry?


<!--
  Core concepts. House rule: distilled from SHARED-LANGUAGE.md (the canonical
  dictionary T keeps). Do not invent a model; if this page and the dictionary
  ever disagree, the dictionary wins. Keep terms faithful to it.
-->
# Core concepts

The one-paragraph model, then the words.

Sugar places a **dischargeable obligation (a contract) on an arbitrary subject (a
sugar)** without formalizing the subject. The surfaces you already wrote — tests,
function bodies, annotations — are *lifted* into one uniform first-order-logic form
(ProofIR); the verifier composes those contracts along your call graph and
discharges every edge, or refuses. Everything is content-addressed (a BLAKE3-512
CID), so identity is *content*, not a name — which is what lets proofs federate
across packages and languages with no hub. What it cannot discharge, it names.

> Canonical definitions live in [SHARED-LANGUAGE.md](../../SHARED-LANGUAGE.md) — the
> dictionary T keeps. This page is the readable distillation; if the two ever
> disagree, **the dictionary wins.**

## Sugar and contract — a bound pair

- **Sugar** is *that which is under contract* — the arbitrary subject an obligation
  rides on. Literally anything: a function, a test, a poem, a whole codebase.
  Content-addressed but **uninterpreted** — Sugar models nothing about it.
- **Contract** is a **ProofIR first-order-logic** obligation tied to a specific
  sugar: a binding, dischargeable pre/post. `verify` discharges it; the solver is
  the discharge engine.

They co-travel — **sugar is never naked.** A sugar without its contract is just a
call; the contract is the lien that makes it accountable.

The asymmetry is load-bearing: **the contract is uniform — always FOL**, the same
form whether it governs crypto or a tax rule, so it composes in one solver and
federates across domains. **Sugar is unconstrained.** That is *why there is no
bespoke contract language*: you were never meant to formalize the subject — leave it
arbitrary, lift only the obligation, and one universal vocabulary (first-order
logic) proves things about all of it. **Law over subject.**

## Lift and lower — a 2×2, not three verbs

Translation has exactly two verbs, each with two facets:

|                       | contract | sugar |
|-----------------------|----------|-------|
| **in**  (native → IR) | lift     | lift  |
| **out** (IR → native) | lower    | lower |

- **Lift** (native → ProofIR) reads a surface — a test, an annotation, a body — and
  produces its contract and sugar. **Singular**: one surface → exactly one contract
  (forced by content-addressing; two parties lifting the same surface must get the
  same contract, or pinning is meaningless).
- **Lower** (ProofIR → native) writes a contract back out as a test/annotation/gate
  (the *emitter* facet) or a sugar back into source at a boundary (the *materializer*
  facet). **Plural**: one truth, many faithful expressions.

`emit` / `materialize` / `migrate` were never separate concepts — they are facets of
`lower`. **Realize** is the kit *performing* a lower for one language over RPC.

## Boundary, concept, kit

- **Boundary** — a **realization site of a sugar**: a client of a library. The author
  supplies the sugar (and its contract); the user has boundaries where it is
  materialized, and gets **red squigglies when they violate a contract**.
- **Concept** — a **name for a shared tag amongst sugars** (e.g. `json_encode`).
  Whether two sugars under one concept mean the *same* contract is **the vendor's
  call** — Sugar sets nothing.
- **Kit** — a **language-specific implementation**: it lifts that language's surfaces,
  lowers contracts back to native artifacts, and resolves its ecosystem's `.proof`s
  (jar / pip / cargo). All kits speak one RPC language; the CLI is language-blind.
  Kits are **seats in one federation**, not a supported-languages feature list.

## The trinity — terms, contracts, implications — a graph

- **terms** = the operations — the **nodes**.
- **contracts** = pre/post obligations on each — the **node labels**.
- **implications** = `post(B) → pre(A)` — the **edges** that compose them.

Composing `A(B())` is licensed by exactly one obligation: the producer's
postcondition implies the consumer's precondition. That arrow is **Hoare's rule of
composition, content-addressed** — and it is what `implicate` mints. A whole program
verifies by discharging **every edge**, rooted in `true`.

Plainly: **a bug is a missing edge; a contradiction is a present-but-false edge;
correct software is a graph of contracts whose every composition edge discharges.**
Implications are the durable layer — a proven `P → Q` is a reusable lemma. Mint once,
compose forever.

## CID — content identity

Every artifact — sugar, contract, witness, attestation, the protocol record, a whole
`.proof` — is named by its **BLAKE3-512 content hash (CID)**; signatures are Ed25519.
Identity is *content*, not a name or a version number. That is what lets proofs
federate across languages and time without a hub: the same fact has the same CID,
whoever minted it. ("Correctness is a hash.")

## How a claim is discharged — two ways, both must agree

A `.proof` is the claim `k(I) = t`, pinned and content-addressed. It is discharged
two independent ways that must agree:

- **Consistency** — a solver proves the lifted contract is internally satisfiable; a
  self-contradictory spec is refused without running anything.
- **Witness** — the code is actually run, the run is content-addressed, and `verify`
  recomputes it; a witness that does not reproduce its CID is refused.

The solvers are the discharge engine (z3 / cvc5 / Vampire / CeTA / Lean / Maude / Coq
— `implementations/rust/sugar-verifier/src/solvers/`).

## Three axes of pinning — 8 trust postures

A proof binds three independent CIDs, each pinnable (frozen) or floatable:

1. **Contract** — what it conforms to.
2. **Witness** — the chain that endorses it.
3. **Binary** — what it asserts about.

The substrate picks none of it; the consumer/vendor decides per axis (security team:
tight witness; dev team: tight binary; compliance: all three). Together they close
the supply-chain attack class: a correctly-signed package still cannot swap behavior,
forge endorsement, or swap bytes without breaking a pin.

## The honest trichotomy — exact / loudly-bounded-lossy / refuse

Above all, correctness (*supra omnia, rectum*). Every operation is **exact**, or
**loudly-bounded-lossy**, or it **refuses**. When a lift, lower, or discharge cannot
be exact, the loss is **recorded — content-addressed and named, never silent**.
"Loudly-bounded-lossy" is only honest if the bound is written down; silent loss would
be a lie. What cannot be proven gets named — **the residual is the product.**

## A note on "catalog"

Two different things wear the word, and the dictionary is explicit:

- A central **concept/realization catalog is fiction** — the registry anti-pattern
  this content-addressed, vendor-pinned substrate exists to abolish. "The catalog" is
  at most the ephemeral *union of the vendor `.proof`s a consumer has resolved*.
- The **protocol "catalog"** — the signed, content-addressed record of the protocol's
  own evolution (its spec set, each pinned by CID) — is **real but misnamed**. The
  dictionary calls it the **protocol record**: the substrate's own ledger of how its
  rules changed, not a registry of vendor content.

---

See also: [SHARED-LANGUAGE.md](../../SHARED-LANGUAGE.md) (canonical dictionary) ·
[README](../../README.md) (why) · [getting-started](../getting-started.md) (run it).

# Sugar — the spine (positioning north-star)

> Draft co-authored with T, 2026-06-28. Redline freely. This is the lens the grounding pass and the doc architecture both build from. It is not the doc structure — it's the thing the structure has to serve.

## The tin (one line)

**An honest correctness membrane for polyglot software** — it tells you what's proven and what's still flapping in the night, in any language and especially at the seams between them, with no hub and no contract DSL, because identity is content.

## Three things on the tin

### 1. Honest, not correct
"Correct" is a claim about the *code* — unprovable in general, a lie when oversold. "Honest" is a claim about the **report**: it cannot deceive you about its own coverage. `silent==0` makes the residual total; `false_discharges==0` means nothing inside the membrane is a hollow pass. You don't get a green check — you get an accounting you can't be fooled by. The teeth are what make the honesty load-bearing.

The residual — what flaps in the night — is the **deliverable, not the failure**. Types, tests, scanners, swagger all report what they checked and go silent on the rest; their green is a liar's map. This centers the *complement*: it hands you the dark, content-addressed, so unknown-unknowns become known-unknowns you can point a light at. Sell the dragons, not the safety.

### 2. Universal — the trick works in ALL languages
We **model nothing**. We don't reimplement a language's semantics — we lift the claims the authors *already wrote* (tests, asserts, annotations) down to a shared FOL floor. Every language has a claim surface, so every language can be lifted. A new language isn't new product — it's a thin lifter into the same engine, floor, teeth, and CID. The wall of languages is the **fixpoint of one engine**, not N integrations.

No hub, no DSL. Everyone who tried cross-language correctness needed a vendor in the middle — CORBA, SOAP, swagger, protobuf, a bespoke `.invariant` — a thing to trust and a dialect to author against. This needs none: **identity is content, not language.** Same proven fact → same CID whether it came from Rust or Python. One membrane fabric, hubless. Kits are **seats in one federation**, never a "supported languages" feature list.

### 3. Silver bullet — zero code changes
Not low friction. **Zero.** No new annotations, no contracts to write, no first-order logic to learn, no holding your mouth a certain way when you compile. The spec is already in your repo:
- **Your unit tests are your stated facts** — the point-wise claims (`encodeBase64("abc") == "xyz"`).
- **Your function bodies are your stated contracts** — the body, desugared, *is* the constrained universe that carries the teeth. What the code actually computes is the contract it fulfills.

We **recognize** what the authors already wrote; we never **request** anything new. So the flow is just:
- **Produce:** `cd MyProject && sugar mint` → a `.proof`. (`mint` dispatches the lifters and envelopes the result; `sugar lift` is the lower-level peek at the ProofIR terms — the producing verb is `mint`.)
- **Consume:** load the upstream `.proof`, conjoin your own facts against it, verify — **recompute**, inherit the honesty without trusting the producer.

And not in *any* language — in **all** of them, because every codebase in every language already ships tests and bodies. The raw material universally pre-exists.

A `.proof` is a portable, recomputable, language-agnostic **honesty token** — a file that ships with the package. Because every consumer is also a producer, honesty **propagates through the supply chain at three commands a hop**. The membrane composes transitively. Not one honest library — an honest **graph** anyone joins for the price of three commands, in any language.

## One root: the spec is endogenous
The three things on the tin are three faces of one fact — **the spec is already in your repo.** Because the spec is your own tests (facts) and your own bodies (contracts):
- you write nothing new → **zero code changes** (the silver bullet),
- it works everywhere → **universal** (every language already has both),
- and it's **honest, not correct** → we check your claims against your *behavior*, never against an external ideal, and hand you the residual.

No external oracle to author, drift from, or trust. Correctness here is internal consistency made legible — your stated facts against your actual behavior — with the gap content-addressed. It's also why there's no contract DSL and no hub: there is no external spec to put in one.

## The front door
**The silver bullet IS Getting Started.** The two three-command flows — produce a `.proof`, consume one, cross-language — are the hello-world. Everything deeper exists only to answer why those three commands are **trustworthy** (honesty / teeth), **portable** (CID), and **universal** (lift native claims, model nothing).

## The law the docs obey (recursive honesty)
The docs about an honesty product must themselves be honest.
- Every pitch claim ships its **receipt** — the example / test / artifact, shown not asserted.
- Anything aspirational is **named residual with a CID**, never pitch. An unbuilt demo in the headline is the exact hollow proof the product exists to refuse.
- Open receipt to attach in the grounding pass: the **cross-language seam composition** (T: fully realized) — cite the actual example/test, don't just claim it.

## Grounding + structure lens
Judge every surface item by **pitch · plumbing · residual**:
- **pitch** — serves honest-membrane / universal / silver-bullet directly.
- **plumbing** — *how* the membrane holds and honesty is enforced (ProofIR, the multi-solver portfolio, lifters, RPC, canonicalizer). Belongs in Architecture/Reference; never the opening.
- **residual** — real but unfinished; named honestly, never sold.

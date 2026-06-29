<!--
  How contracts COMPOSE — the keystone mechanic, and the one agents get wrong most.
  Grounded in sugar-verifier/src/consistency.rs (the callsite conjoin + closedness gate),
  protocol/specs/2026-05-09-contract-composition-protocol.md (compose_chain_contracts,
  effects, cross-language equivalence, failure modes), and sugar-ir-types (Declaration::Bridge,
  BridgeTarget, EvidenceCertificate). If a single rule here is broken the result is UNSOUND but
  often still green — read the source, not your intuition.
-->
# Bridges & composition — how contracts conjoin

This is the mechanic by which a **vendor's contract and a consumer of that vendor meet at a
callsite and conjoin contracts**. It is the most important thing to get right and the thing
agents fumble most, because the wrong version still produces a green proof. It happens at
three scales:

1. **One callsite** — a vendor's claim and a consumer's claim about *the same call* are
   **conjoined** and checked together.
2. **A call chain** — a producer's `post` discharges a consumer's `pre` (an **implication**),
   composed along the call graph.
3. **Across languages** — the *same* composition produces the *same CID*, so a Rust caller and
   a Java callee meet at a **bridge**.

All three are the same idea: contracts meet by **content identity at the callsite**, never by
who wrote them.

## The core idea: a callsite is a shared unknown

This is the part that isn't obvious, so here it is plainly before any machinery.

- **A callsite is a black box with a name.** `np.add(2, 3)` — the solver has *no idea* what it
  computes. To z3 it's an opaque term, and its name is the content hash of the call
  (`numpy.add#euf#…`). The same call has the same name in every `.proof`, in any language. (It's
  opaque *because we model nothing* — we never reimplement `np.add`.)
- **A universe is the constrained world that black box lives in** — shaped by **constraints**:
  things that actually *limit* what's possible. A precondition, the bounds on a variable, and — when
  the call is *dug* — its body inlined down to literals (the floor). Constraints **narrow** the
  universe.
- **A fact is a vendor-supplied *invariant* — something that must *always* hold within that
  universe.** `np.add(2,3) == 5` is the vendor's claim; in the protocol it's an `inv`. (Keep the two
  words straight: an **invariant** must *hold*; a **constraint** *limits*. A `pre` is a constraint —
  it bounds which inputs the claim is made over; an `inv` is the invariant — it must hold across the
  bounded universe. In `sugar lift --report` a lifted invariant is a **warranted** locus, as opposed
  to `unresolved` dark, a `refused`/`refuted` sound-no, or inert `support`.)
- **The solver's only question: do all the invariants — the vendor's and the user's — hold within
  the universe's constraints at once?**
- **"Vendor facts" and "user facts" are just invariants asserted by different people — and an
  invariant is filed under the *callsite's* name, not the author's.** That one sentence is the whole
  mechanic.

When numpy's own test states `np.add(2,3) == 5` and your code states `np.add(2,3) == 6`, both land
in the **same universe** — the constraint set the verifier checks for that call — because the call
hashes to the **same key**. Neither party coordinated; the vendor never heard of you. You meet
because you constrained the *same named unknown*:

```text
   vendor .proof                 your .proof
   np.add(2,3) == 5              np.add(2,3) == 6
          \                             /
           \   same callsite key       /
            \   numpy.add#euf#…       /
             v                       v
        ┌──────────────────────────────────┐
        │  universe of np.add(2,3)          │
        │      { == 5 , == 6 }              │
        └──────────────────────────────────┘
                      │  satisfiable?
                      v
               and(== 5, == 6)  →  UNSAT  →  YOU are refused
```

So the callsite is the **join key**. The verifier gathers every fact about a call into one universe
and asks "is this consistent?" **Consistent means you *agree* with the vendor** — you've inherited
their contract (PROVEN). **Inconsistent means you're asserting their function does something it
doesn't** — and you don't get to out-vote the vendor about their own call (REFUSED). You inherited
correctness without importing their code or trusting their runtime; you simply cannot contradict a
stated fact about a call you both name.

Everything below is the *machinery* that makes that join sound. Hold the one sentence: **facts meet
at the callsite by content identity, and a universe is consistent exactly when the parties agree.**

## Why this works: two bullets, one gun, and no test was ever fired

Here is the beauty of it. The query we hand z3 is only:

```text
sat?   and( vendor-invariant , user-invariant , universe )
```

and **we throw the model away.** We never ask z3 to *find* a value — only whether these can coexist.
The callsite is a gun; an invariant is a round; the **universe** — the function's own body, dug down
to literals — is the rifling that decides what round can come out. z3 is the ballistics lab. This is
*never* the hard direction of "here's a bullet, go find the gun that fired it" (synthesis — a search
over programs, the expensive, undecidable, *and* unsound direction, because reimplementing the
function would make us a shim).

The easy case is barely a question. Vendor: `enc("abc") == "xyz"`. User: `enc("abc") == "WRONG"`.
Same input, two outputs — `and(== "xyz", == "WRONG")` is UNSAT by equality alone. A trivial clash.

The *cool* case is the whole product. Vendor: `enc("abc") == "xyz"`. User: **`enc("bby") == "chk"`**
— a **different input the vendor never tested.** Nothing clashes on the surface; this is *not*
trivial. So the **universe does the rest**: z3 propagates `"bby"` through the dug body of `enc` and
asks whether the result can be `"chk"`.

- **SAT** → yes — the function really does map `"bby" → "chk"`; the user's claim holds.
- **UNSAT** → no — the user got the encoding wrong; refused with a **refutation certificate** (the teeth).

Now read what just happened: **no unit test ran.** The user asserted a fact about an input they
*never executed*, and it was **proved** against the function's universe instead of **sampled** by
running it. The test they would have written — call `enc("bby")`, assert `== "chk"` — collapses into
one SAT/UNSAT check. That is the silver bullet: your tests become facts, and you can state facts you
never ran, over inputs nobody covered, and have them proved.

This is exactly why the universe must be **dug**, not opaque. Strip `enc` to a bare uninterpreted
function and `enc("bby") == "chk"` is *trivially* SAT — any output satisfies an opaque call, so it
proves nothing. The **dug** universe — the vendor's real body in FOL — is the only thing that can
refute a wrong output for an input no one tested. (We *dig* the vendor's own source; we never
*reimplement* it — digging is lifting, reimplementing would be the shim we forbid.)

That one inversion is why this is cheap, sound, and universal at once. **Cheap** — it's a consistency
check, not a model search; the costly part of SMT is *building a witness*, and we don't want one.
**Sound** — we never invent the function's behavior; the universe is the vendor's own dug body, so
there is no answer for us to fabricate. **Universal** — ballistics doesn't care what language the gun
was machined in. And the polarity stays honest-not-omniscient: **UNSAT is a hard refutation** (we
*proved* the contradiction); **SAT** means "no contradiction in this universe," so the user inherits.

**That is the genius, stated whole:** one z3 consistency check, over *every* language (everything is
ProofIR — z3 never sees the source), over *every* surface authors already wrote (their tests are the
facts, their bodies are the universes), with **zero code changes from anyone** — no contracts, no
annotations, no FOL, no shim. The same single move dissolves all four famously-hard problems at once:
verification (check, don't synthesize), cross-language (lift to one IR), adoption (no new code), and
trust (recompute the CID). The rest of this page is that move's load-bearing machinery.

## Why it falls apart — silently — over two emission details

The join is brittle, and when it breaks it does **not** error. It produces a **green proof that
should have been red.** That false-green is the worst failure in the whole system, and it comes from
exactly two emission mistakes — both invisible at emit time and invisible in the report.

**1. The callsite key must be byte-canonical, or the facts never meet.** The conjoin happens only if
your callsite term hashes to the *exact same* `#euf#` key the vendor emitted for that call. A
different argument encoding, an un-stripped name, a different ctor spelling, a normalization the
vendor didn't apply — any of it yields a *different key*. Then your `np.add(2,3) == 6` and the
vendor's `np.add(2,3) == 5` land in **different universes**, the contradiction is **never computed**,
and you get a clean green that means nothing. The key *is* the join; a near-miss is a silent miss.
This is why "same surface → same contract" and byte-determinism are soundness, not style.

**2. The `pre` / `inv` / `post` slot decides invariant-vs-obligation.** A contract's *structure*
routes it: an `inv` is the **invariant** (must hold) and conjoins into the universe; a `pre` is a
**constraint** (it limits which inputs the invariant is claimed over) and is an *obligation* —
discharged on the call-site path, not asserted true (a `post` is allowed, and is conjoined with the
`inv` as the lifted universe). So a contract with an `inv` and **no** `pre` is the
established-invariant (conjoin) path; a `pre`-bearing contract is the obligation path. Emit an
invariant with a stray `pre` and it leaves the conjoin path entirely — it never enters the universe,
so the contradiction isn't checked. Omit the `pre` on a real obligation and the verifier admits an
*unproven precondition as a free truth*. Either way the universe you check is the wrong set.

Treat the callsite **format** and the `pre` **location** as load-bearing for soundness. A wrong byte
here doesn't fail loud — it passes quiet.

## Part 1 — the callsite conjoin (one site)

**Rule 0: contracts key to the CALLSITE, not the test.** The verifier's shared vocabulary is
*callsites* — `call:*` ctors and the `#euf#` symbol names (`numpy.add#euf#…::assertion`). A
contract named for the *test* that asserted it can never meet another party's claim. A contract
named for the *call* meets every other claim about that call, in any `.proof`. That is what makes
inheritance work at all.

Know the contract taxonomy (`consistency.rs`), because only one kind conjoins:

- **`::assertion`** — a conjoined **invariant** (an asserted property). **This is what gets checked.**
- **`::facts` / `::facts::N`** — a *setup binding* (`y = make_value(x)`). SAT by construction —
  it's a definition, not an invariant — and **excluded** from the consistency check. Reporting it as
  "consistent" would be vacuous.
- **`::facts-implies-assertion`** — an **implication declaration** (a `post → pre` edge), **not a
  contract.** It never reaches the conjoin pass. (Confusing this for a contract is a classic error.)
- **A contract carrying a `pre`** is the *call-site obligation* path, not the conjoin path — a
  `pre` is a constraint to discharge, not an established invariant. The conjoin pass fires only for a
  contract with an `inv` and **no** `pre` (a `post` is allowed and is conjoined with the `inv` as
  the lifted universe).

**The conjoin itself:** the invariants about a callsite are conjoined into one formula
and handed to z3. **SAT → consistent; UNSAT → contradictory → refuse.** This is the whole
inheritance demo: a vendor proves `np.add(2,3) == 5` (keyed to the callsite); a consumer asserts
`np.add(2,3) == 6` (same callsite key); the verifier conjoins them *before* the SAT check →
`and(== 5, == 6)` → UNSAT → the **consumer is refused.** The consumer inherited the vendor's
contract purely by callsite identity.

### The closedness gate — the soundness line agents cross

Not every fact may travel between obligations. The rule:

- **Only CLOSED facts about CONCRETE CALLSITE terms travel.** A universal (`forall`) earns
  cross-obligation force *only through a closed specialized instance*. A `forall` still carrying a
  **free variable** after specialization — an un-elided test-local like a symbolic range bound
  `n` — is a fact about *that test's locals*, not about a callsite. Two unrelated tests can spell a
  local the same way; conjoining the open formula couples them through **name capture** → unsound.
  Open templates may be collected, but their open instances **stay home.**
- **Ground callsite facts** (a closed equality whose subject is a `call:*` ctor, e.g.
  `call:g(3) == 1` from a literal-domain loop replay) *do* travel and constrain sibling `#euf#`
  obligations about *the same concrete call* — but they are **scoped to their assertion context**
  and do **not** pool across independent consumers that merely name the same callsite.
- **Local variables and non-call helper ctors never travel.**

Get this wrong in either direction and you're unsound: conjoin too much (open locals, or two
consumers' unrelated facts about a same-named call) and you couple unrelated programs; conjoin too
little and you miss the contradiction the teeth depend on.

## Part 2 — chain composition (post → pre)

When a call *nests* (`F(x, G(y), z)`), contracts compose along the chain. The canonical primitive
is **`compose_chain_contracts`** (CCP §2, libsugar) — pure, deterministic, byte-identical output
(the composed CID is a function of the input CIDs and the compose-function version, nothing else).

The rules that matter (CCP §9):

- **Singular formal substitution.** Only a formal whose argument is *itself a function call*
  triggers composition. In `F(x, G(y), z)` only `G(y)` composes (G's contract substitutes into F's
  at that position); `x` and `z` are leaf substitutions, not composition. Composing leaf arrivals is
  a common over-reach.
- **The edge is `post(G) → pre(F)`.** The composed `pre` is F's `pre` with the composed inner's
  `post` (renamed) conjoined with its `pre` at the formal position — Hoare's rule, content-addressed.
  This is what `sugar implicate` mints as an implication.
- **Inner-result renaming.** G's `post` references a free `result`; it is renamed to
  `result_<G.cid>` before substitution so nested compositions don't collide. Skip this and you
  capture the wrong result.
- **Composition is PURE-ONLY.** If any atom's effect set is non-empty, `compose_chain_contracts`
  **refuses** (`ImpureInput`, naming the atom by CID). You cannot compose across an effect boundary;
  decompose into pure sub-chains and treat the impure atom as a barrier.
- **Eager or lazy, the CID is identical.** A lifter may pre-compose and ship `ComposedFunctionContract`
  mementos; a verifier may compose lazily at prove time. Both produce byte-identical CIDs because the
  primitive is canonical. **A consumer recomputes the CID and never trusts the producer's composed
  contract** when it can re-derive it; signature and producer identity are metadata.

## Part 3 — effects (the prerequisite that makes composition sound)

Composition is sound only over pure subtrees, so **the lifter must extract effects** first (CCP §3).
Effect kinds: `Reads`, `Writes`, `Io`, `Unsafe`, `Panics`, `UnresolvedCall`. A function's effect set
is the union of effects in its body; pure = ∅.

**Conservative, never liberal.** Over-tagging effects refuses some valid compositions but is always
sound. *Missing* a real effect produces an unsound composed contract — and this is **the most
insidious failure mode (CCP §8.5): it is silent.** The composed CID hashes, the verifier admits it,
consumers reuse it; the unsoundness only surfaces when a real input violates the falsely-claimed
pure-composition property. Mitigation: a lifter declares its effect-tracking completeness as a
**soundness memento** on the lift output, and consumers decide locally whether to admit composed
contracts from incomplete-tracking lifters.

## Part 4 — across languages (the bridge proper)

Cross-language composition is the *same* mechanic: run the *same* canonical compose over
structurally-equivalent sources in two languages and the `ComposedFunctionContract` CIDs are
**byte-identical** (CCP §7). A Rust `vec.iter().map(double).filter(positive).sum()` and a C
`sum(filter(map(double, …), …), …)` with the same pure-helper contracts compose to the same CID —
that *is* the federation guarantee, and the bug-zoo cross-language specimen is its load-bearing test.
If two lifters diverge on the CID, **that divergence is the bug** (which lifter emits different bytes,
and why), never a "close enough."

The carrier is a **`Declaration::Bridge`** (`BridgeDeclarationV14`): a `BridgeTarget`
(`Contract { cid }` or `ContractSet { cid }`) plus an `EvidenceCertificate`. The bridge is the pinned
**weld** at the seam — it holds iff the target CID matches and the evidence recomputes; otherwise the
seam becomes **named residual**, never a silent pass.

## The rules, as a checklist

Most agent errors are one of these:

1. **Key to the callsite, not the test — byte-canonically** — or invariants never meet, the
   contradiction is never computed, and you get a silent false green.
2. **Know the taxonomy** — `::assertion` = a checked invariant; `::facts` = a SAT-by-construction
   binding (excluded); `::facts-implies-assertion` = an implication, not a contract; a `pre` is a
   constraint, so a `pre`-bearing contract rides the obligation path, not the conjoin path.
3. **Respect the closedness gate** — only closed facts about concrete callsite terms travel; open
   test-local formulas stay home (name capture = unsound); ground callsite facts are scoped, not
   pooled across independent consumers naming the same call.
4. **Only function-call args compose** — leaf args are plain substitutions.
5. **Composition is pure-only** — impure input refuses; decompose around the effect barrier.
6. **Rename inner results** (`result_<G.cid>`) — or capture the wrong result.
7. **Effects conservative, never liberal** — a missed effect is a silent unsound composition; declare
   tracking completeness.
8. **Recompute, don't trust** — re-derive the composed CID; the producer's bytes are not authority.
9. **Cross-language means byte-identical CID** — divergence is the bug, not a tolerance.
10. **A bridge needs a matching target CID + recomputing evidence** — a broken weld is named residual,
    not a green pass.

---

Authoritative sources: `sugar-verifier/src/consistency.rs` (the conjoin + closedness gate),
`protocol/specs/2026-05-09-contract-composition-protocol.md` (the composition function, effects,
cross-language equivalence, failure modes), `sugar-ir-types` (`Declaration::Bridge`, `BridgeTarget`,
`EvidenceCertificate`). See also: [lifting-vocabulary](lifting-vocabulary.md) ·
[proofir-z3-dialect](proofir-z3-dialect.md) · [lifting-rules](lifting-rules.md).

<!--
  The lifting vocabulary — what a fact / dig / effect / bridge / implication is, the
  source oracle, mementos & atoms, and how each lands in ProofIR. Grounded in
  implementations/rust/sugar-ir-types/src/lib.rs (Declaration, IrTerm, IrFormula, Sort,
  SourceKind, BridgeDeclarationV14, EvidenceMemento, SourceLocator). Complements
  lifting-rules.md (the laws) and factory-sugar-floor.md (the shape).
-->
# The lifting vocabulary

[lifting-rules](lifting-rules.md) gives the laws and [factory-sugar-floor](factory-sugar-floor.md)
gives the shape. This page gives the **nouns** — the things a lifter actually produces and
the words for them — and how every one of them ties back to **ProofIR**, the single form
the CLI verifies. If you internalize one thing: *whatever your kit recognizes, it ends up
as ProofIR; these terms are the parts of that.*

## ProofIR — the target everything reduces to

ProofIR is the language-neutral first-order logic the solver sees. Its core types
(`sugar-ir-types`):

- **`Declaration`** — the top-level unit. Exactly two kinds: a **`Contract`** (a pre/post
  obligation over an operation) or a **`Bridge`** (see below).
- **`IrFormula`** — the FOL: `Atomic`, `And`, `Or`, `Not`, **`Implies`**, `Forall`,
  `Exists`, `Apply`, … . This is what gets discharged.
- **`IrTerm`** — the term language formulas range over: `Var`, `Const`, `Ctor` (a
  constructor/operation applied to args), `Lambda`, `Let`.
- **`Sort`** — the type discipline: `Primitive`, `Function`, `Dependent`, `Region`.

Everything below is *how a native source shape becomes one of these*.

## Atom

An **atom** is a leaf of the IR — an `IrTerm::Const` (a literal), an `IrTerm::Var`, or an
operator application (`Ctor`/`Apply`). Atoms are what the **CID is computed over**, so they
are load-bearing for identity: if two *different* operations (say `x + y` and `x - y`) lift
to the same atoms, their CIDs **collide** and the verifier can't tell them apart — a real
soundness bug, not a cosmetic one. Emit the operator atom faithfully; never normalize two
distinct operations to the same leaf.

## Fact

A **fact** is a stated claim you lifted from a native surface — a test assertion, an
annotation, a callsite. It lands as an **`IrFormula::Atomic`** (e.g.
`encodeBase64("abc") == "xyz"`). Its `SourceKind` records *where it came from*
(`TestAssertion`, `Annotation`, `TypeSignature`, `LoopInvariant`, `ImplicitEffect`,
`NativeSurface`, …) and its `SourceLocator` records *exactly where* (file + span), so the
fact is traceable and recomputable. A fact is "the vendor says so" — you pin it, you don't
re-derive it.

## Dig

A **dig** is resolving a fact's **universe**: inlining the bodies a fact refers to until
the formula bottoms out in literals (a *constrained universe*). `encodeBase64("abc") == "xyz"`
is a hollow claim until you dig the body of `encodeBase64` down to the constants it
computes — *that* universe is what carries the teeth. A dig is **valid only if it has
teeth**: assert the wrong literal (the bad-twin) and it must come back UNSAT. A stated
`call:f(args) == literal` is a legitimate dig (you pin the vendor's fact and check
coherence, you don't run `f`); `f(x) == g(x)` with no literal anchor is always-SAT — a fake
dig. (See [lifting-rules §5](lifting-rules.md).)

## Effect

An **effect** is a *real* source property that destroys the timeless value relation: IO,
mutation, nondeterminism, dynamic dispatch, environment reads. It is recorded as a
`SourceKind::ImplicitEffect` and surfaces as a **`Hit`** — an obstacle between you and a
literal, not a discharge. Crucially: pure-but-*unlifted* syntax is **not** an effect — it's
a construction gap you panic on (*write more sugar*). Refuse for real effects; never refuse
a pure shape just because you haven't covered it yet (the fake-refuse sin).

## Implication

An **implication** is an **`IrFormula::Implies`** — the composition edge of the trinity
`{terms, contracts, implications}`. Composing `A(B())` is licensed by exactly one
obligation: `post(B) → pre(A)` (Hoare's rule, content-addressed). It is what `sugar
implicate` mints. Implications are the **durable** layer: a proven `P → Q` is a reusable
lemma — terms and contracts are local, the edges between them are the composable,
federatable proof. A whole program verifies by discharging every implication edge, rooted
in `true`.

## Bridge

A **bridge** is a **`Declaration::Bridge`** (`BridgeDeclarationV14`) — a content-addressed
linkage that carries a contract/sugar across a bundle or language boundary. Its
`BridgeTarget` names what it links to (`Contract { cid }` or `ContractSet { cid }`) and it
carries an `EvidenceCertificate`. The bridge is the **seam**: when a Rust caller composes a
Java-proven contract, the bridge is the pinned weld — it holds (CIDs match, contract
discharged) or it becomes named residual. Bridges are how cross-library / cross-language
composition stays honest at the boundary.

## The source oracle

The **source oracle** is how a `.proof` stays *identity, not bodies*. A `.proof` carries
CIDs and `SourceLocator`s, not inlined source. When a dig or a witness needs an actual
body, the oracle resolves it **by locus + CID and recompute-verifies it**: it returns the
on-disk source iff that source recomputes to the pinned CID, and **refuses loudly**
otherwise. This is the anti-shim — it's what lets a 2909-function numpy proof stay lean,
and it's why the producing kit can be untrusted (the CLI recomputes the CID itself). Your
digs and witnesses reference bodies *through* the oracle; you never embed them.

## Mementos

A **memento** is a signed, content-addressed unit — the composable proof step. The kinds
you'll emit or reference: a **contract memento** (a lifted pre/post), a **source memento**
(a locus + CID into real source, resolved via the oracle), a **witness / evidence memento**
(`EvidenceMemento` — a content-addressed run/log/value), a **bridge declaration**, and
specialized ones like `SortMorphismMemento`. A `.proof` is a **DAG of mementos**: every
memento names the exact CIDs it depends on, so old facts stay true about the old bytes that
minted them, and nothing needs a central invalidation service. Mementos are the currency;
the `.proof` is the bundle.

## How it ties back to ProofIR

One sentence: **a lifter turns native surfaces into `Declaration`s — Contracts and Bridges
— built from `IrFormula` over `IrTerm`/`Sort`, sealed as mementos.** Facts become atomic
formulas; digs fill in the term universe down to atoms; effects become Hits instead of
formulas; implications become `Implies` edges; bridges become `Bridge` declarations across
seams; the source oracle resolves the bodies the digs and witnesses point at; and every
piece is content-addressed as a memento. The CLI never sees your language — only this
ProofIR — which is exactly why one solver can discharge a contract whether it came from
Rust, Python, or Java.

---

See also: [lifting-rules](lifting-rules.md) (the laws) · [factory-sugar-floor](factory-sugar-floor.md)
(the shape) · [concepts](../explanation/concepts.md) · [`.proof` file format](../../protocol/specs/2026-04-30-proof-file-format.md).

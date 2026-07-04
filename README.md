# Sugar
**Makes software honest.**

> **Sugar in, `.proof` out.**
> One z3 check. Every language. Every surface you already wrote. Zero code changes.

You don't really know what your software does. You know the packages you installed and the versions you pinned. But you depend on what the code *does* — across every dependency, in every language, including the ones you have never read — and that is the one thing nothing tells you. It is also the only thing that has ever hurt you.

Here is how you get it back: correctness you can prove, hand to someone else, and check for yourself. One command, no changes to your code. (Behind it are nine impossible things. They are waiting at the bottom.)

## You get a proof of your software without touching it

No spec. No annotations. No proof language. You don't change a line, and you don't care what language the code is in. You run `sugar mint`, and out comes a signed `.proof`: a map of what your software actually does.

Every verifier before this made you pick one language, model it, and pay in specs and annotations — which is why verification lived in aerospace and never in your repo. Getting it for free, in any language, from the code you already wrote, is impossible. So Sugar doesn't model your language; it reads a claim your code already makes. `assert encode("abc") == "def"` is your package swearing, in the language it shipped, that this call returns that value. Sugar lifts the *claim*, not the language, so the same proof falls out of Rust, Python, or Java.

## You find out whether a dependency's behavior actually moved

You bump a dependency. SemVer says `minor`; the changelog says trust us; neither answers the only question that matters: did the behavior you lean on change? A version is a promise a human typed. A signature vouches for the bytes, not for what they do. Telling whether *behavior* moved, without trusting whoever shipped it, is impossible.

So Sugar gives behavior a name — which first meant making behavior nameable at all. It takes the program apart down to the one thing a program is supposedly made of, order, and throws it away. What is left is a theory, `A ∧ B ∧ C`, with a single canonical form, and a single canonical form is a thing you can hash. Now "did it move?" is `memcmp(64)` instead of faith, and `sugar diff` shows you exactly which behaviors held, renamed, appeared, or vanished — the silent breaking change and the poisoned patch, both lit up before they reach prod.

## You catch a wrong assumption before you run it

You write a line that leans on a dependency: `np.add(2, 3)` is going to be `5`, you're sure of it. To check that, you'd normally run it — which only tells you about the inputs you tried — or reimplement it, which makes you a second, buggier copy of the thing you're checking. Knowing your assumption is wrong *before* you run anything, without modeling the function at all, is impossible.

So Sugar models nothing. It hands z3 your claim and the function's *own* lifted body and asks one thing: can both be true at once? Claim that `np.add(2,3) == 6` and z3 returns UNSAT — your assumption could not have come from that function — and you get a red squiggle on a line that cannot hold, before prod, on an input nobody ever tested.

## You see what nobody ever proved

A green check tells you the parts that passed. It says nothing about the parts nobody ever made a claim about, which is exactly where the next breach lives. And real code touches the world — files, sockets, clocks, a subprocess, FFI into something no one can read — so any honest map has holes. Drawing those holes instead of painting over them, and selling you the map of your own ignorance, is impossible; nobody buys "I don't know."

So Sugar sells the exact shape of what it doesn't know. Pure code expands the map; every effect stops it and posts a sign, *here be dragons*, drawn to scale. Every behavior lands somewhere named: pinned, contradicted, witnessed, bounded, fixture-only, outside the membrane, or unknown. The green is the boring half. What you actually wanted is the other one — the enumerated list of behavior nobody ever swore to, per dependency, the ground you are standing on with nothing under it, finally drawn.

## You ship your correctness, and the next person inherits it

Correctness has never survived a package boundary, never mind a language boundary; the best you could hand a downstream user was a version number and your word. Handing them correctness they can check *without* trusting you, in a language that isn't even yours, is impossible.

So Sugar makes it a file. Your `.proof` is signed and content-addressed, so the next consumer verifies it without trusting you; they stage it, write their own code against your library, and `sugar prove` checks their assumptions against your proven behavior — in any language. A Rust caller and your Python contract meet at the same callsite, and if the caller contradicts you, it is refused. Your correctness became theirs, for the price of a file.

## You stop importing attacks

A supply-chain attack lives in the gap between what you installed and what behavior you agreed to run. The industry's answer is to add a party to trust — a scanner, a registry, a vendor saying *trust us, we found the bad thing* — which fixes a trust problem by adding one more thing to trust. Closing the gap without becoming the next compromised link is, naturally, impossible.

So Sugar closes it by owning nothing. You own your kit, your solver, your policy; every part is replaceable; Sugar just hands you the claim, the witness, and the hash and tells you to check them yourself. And because behavior now has a hash, the attack has nowhere to hide: change what a package does and its root moves, reach outside its cage and the membrane breaks, ship a quiet `minor` that does something new and the diff lights up. You import behavior, not bytes — and only the behavior you agreed to.

## Nine impossible things

That is what you get. Behind it, in the order they had to happen, are the nine impossible things that put it there:

1. Lift every language into one logic.
2. Throw away order.
3. Give every behavior a name no one has to trust.
4. Prove what a function does without running it, while modeling nothing.
5. Map a program without lying about the parts it can't see.
6. Sell uncertainty.
7. Do all of it with zero changes to your code.
8. Stop supply-chain attacks.
9. Turn the tool on itself — the one test a correctness engine can't talk its way out of — and ship the result. Sugar mints proof data from its own tests and assertions; the snake eats its [tail](docs/self-application/2026-05-28-snake-eats-tail.md).

The White Queen managed to believe six impossible things before breakfast. Sugar does nine, and signs them.

## Who rules on what your code means

When your code says `.map`, someone has to say what that means. Every tool you've ever used answers this the same way: it becomes the authority itself. The linter has opinions. The analyzer has a model. The checker has its own idea of your language, which is why it disagrees with your compiler in the corners, and why you learn to ignore it.

Sugar refuses the throne twice.

The `sugar` CLI is Switzerland. It owns no language semantics, holds no opinion about any line of code. It dispatches, composes, hashes, checks, and reports. If the CLI ever grew an opinion about what `.map` means, it would be one more authority you'd have to trust, and the entire point is that there isn't one.

**Kits** are where meaning lives, one per language surface: the Rust kit, the Python kit, the Java kit. A kit is an arbiter, and an arbiter must rule; "I don't know" is not a ruling, which is why an unrecognized shape panics instead of shrugging. But a kit rules the way a faithful judge rules: by citing the vendor, never by fiat. "This `.map` means that, on this receiver" is only ever warranted as "because Python says so": the vendor's own semantics, the vendor's own passing tests, the vendor's own compiler. A kit that invented meaning would be a bespoke language authority wearing a robe, the one thing a kit is forbidden to become. Every ruling lands in the `.proof` with its citation attached, which is exactly what the report prints next to your line.

And the kit is yours. You own your kit, your solver, your policy; every part is replaceable; a kit you don't trust is a kit you can fork, because its rulings carry their citations with them. Nothing is central. Nothing is registered. Nobody has to be believed.

## How a proof crosses a language boundary

Your Rust service calls into a Python library. Two compilers, two type systems, two test suites, zero shared vocabulary. Every correctness tool you know stops at this border, because each one is built *inside* a language. Carrying a guarantee across it is impossible.

Here is how it crosses. Each kit lifts its own surface into the same logic: vendor-tested assertions become first-order formulas over shared sorts, order thrown away, canonicalized, content-addressed. At the bottom there is no Rust and no Python; there is a theory, `A ∧ B ∧ C`, and a theory doesn't remember what language it was born in. An `Int` that came from `i64` and an `Int` that came from a Python `int` meet in the same sort, with the platform width carried as a refinement in the sidecar, not baked into the meaning.

So when `sugar prove` runs, it enumerates your callsites, resolves your dependencies' `.proof` files through their kits, and conjoins the contracts that name the same behavior, no matter which language swore them. Your Rust caller's assumption and numpy's Python contract land in one z3 query: can all of this be true at once? If your assumption contradicts what the library proved about itself, you are refused at the callsite, in your language, against testimony given in theirs. The witnesses recompute on your machine, with the kit oracle untrusted. Nothing translated your code. Nothing modeled either language. The border was never crossed, because at the level where the proof lives, there was never a border.

## Who answers for a binding

`let y = x;` What does that mean? You'd say "y is x", and every static analyzer would agree with you, and both of you would be guessing. Whether that binding made an independent copy (an integer), a second name for the same place (a reference), or something with provenance too murky to call, is not a fact about the syntax. It is a fact about the *value*, and in Rust it is a fact the compiler already ruled on when it decided Copy.

So Sugar never asks the syntax. Bindings, writes, reads, and consumes are dispatched as events to the **floor**: the typed algebra where values live. The floor replays the event against its own semantics and returns a closed answer: this binding severs (independent value, equal to me), this one shares (two names, one node), this one is a typed effect (opaque provenance, honestly red). The walker that read `let` never decides anything; a syntax walker deciding what a binding means would be a name asking a name. And when severance matters, the floor doesn't model Rust's Copy rules; it asks rustc, the way everything here asks the vendor. Two names on one value node is also why a stale copy can never falsely refute a true assertion: the bug class isn't caught, it's unrepresentable.

## Correctness composes, and the edges are the product

One proof of one function is a fact. Software is composition, and composition is where every correctness story you've heard goes quiet: you proved `B`, you proved `A`, and nobody proved that B's output is acceptable to A.

Sugar makes that edge a first-class object. A contract is a pre/post over an operation. Composing two operations, `A(B())`, is licensed by exactly one obligation: `post(B) → pre(A)`, the producer's postcondition implies the consumer's precondition. That arrow is an **implication**, and `sugar implicate` mints it as a memento: a signed, content-addressed record that this edge holds, antecedent CID to consequent CID, checked by z3. This is Hoare's rule of composition, content-addressed.

So the whole system is a graph: operations are the nodes, contracts are the node labels, implications are the edges. A proven `P → Q` is a lemma, durable and reusable; it never expires, because it is a value, not an event. Your program's correctness is not a monolithic re-verification of everything; it is a walk over edges that already exist, minting only the ones that don't. Correctness accumulates the way a mathematics does: nobody re-proves the lemmas.

## Two kinds of testimony

Every warrant in a `.proof` declares where its authority came from, and the report shows you the difference.

**Stated** is the vendor swearing: `assert np.add(2,3) == 5` in numpy's own test suite is numpy telling you, under its own oath, what its function returns. Sugar transports that oath; it never checks the arithmetic, because impeaching the vendor is not its jurisdiction, and `call: f(args) == literal` sworn by f's own vendor is exactly the fact you wanted. **Derived** is what the kit computed from sworn facts by cited rules: if the vendor swore the parts, arithmetic composes the whole, and the composition carries its derivation. The two never blur. A bad twin makes the distinction do its work: claim the lie, and the truthful value shows up Derived from the vendor's testimony while your lie stands alone as Stated by nobody but you, and z3 refuses the pair. You can always see which kind of ground you are standing on, because the warrant says so next to the line.

Every verdict also pins what it is about: the kit that ruled, the corpus it ruled over, the toolchain it ran under, each by CID. A verdict that names its own inputs cannot be quietly reused against different ones; recompute it anywhere and it either reproduces or it was never real.

## The mechanism, in one expression

For the mechanically minded, the entire lift is:

```
match(Sugar) {
    Some(s) => cite_or_effect(s),
    None    => panic!(),
}
```

Every recognized shape terminates in exactly two outputs: a warrant cited from the vendor (green) or a typed effect (red). Every warrant ships with a bad twin, the same claim with the answer swapped, which must come back UNSAT: an acquittal only means something in a courtroom capable of conviction. An unrecognized shape panics, loudly, on purpose; the panic is the worklist, not a crash. Refusal exists only at verify, the referee.

Sugar contains zero code for anything the vendor's compiler ensures. rustc's yes is the precondition, so every type composition is correct by construction, and uncompilable input is undefined behavior by design: we make no guarantees about code the vendor makes no guarantees about. And everything in the system, every proof, contract, source file, and memento, is a BLAKE3-512 content address: h = h(p), p = l(h). No RNG, no clocks. Artifacts are values, not events, re-verifiable by anyone, forever.

The full doctrine lives in [AGENTS.md](AGENTS.md).

## Where this goes

The papers take each impossible thing to its conclusion. The ladder starts at the [whitepaper](docs/papers/01-whitepaper.md) and climbs through a sequence of *After X* arguments: what reputation looks like when software is federated truth claims, what verification looks like when bug classes are missing edges, what types look like when the invariant solver replaces trust in logs, how protocols actually evolve, what a commit is when change carries proof, how ProofIR represents every language, what a programming language is when grammars are content-addressed algebras, and what trust means when the universal correctness bundle exists and the author doesn't matter. The full ladder is [docs/papers/](docs/papers/README.md).

The rest of this page is how you run it.

## What the CLI does

> _Naming: the project is **Sugar**. The Rust crates (`sugar-*`) and the CLI
> binary (`sugar`) have been renamed. The proofchain identity layer — kit ids,
> wire tokens, and `.proof` producer strings — still carries the `sugar`
> name, frozen on purpose: it is content-addressed, so re-minting it under the
> `sugar` name is a separate, deliberate swing. The dependency graph is sugar;
> the CID identity is still sugar. Names are sugar, CID is identity._

The canonical CLI is the Rust `sugar` binary. Run `sugar --help` for the
authoritative list; the current subcommands include:

- `sugar mint`: dispatch the configured lift plugins and write `.proof`
  artifacts. This is the verb that actually drives lifting in every example
  here.
- `sugar prove`: run the six-stage verifier. Load proofs, resolve dependency
  proofs through kits, enumerate callsites, conjoin same-named contracts, solve
  obligations, recompute witnesses, and report discharge status.
- `sugar verify`: verify a kit end to end. Lift its contract claims,
  discharge each via the solver-dispatch table, recompute witnesses with the kit
  oracle untrusted, and emit a signed per-claim receipt. This is the gate verb.
- `sugar diff <a> <b>`: compare two minted proof sets by behavior, not text.
  Classifies each behavior-CID as `held` / `renamed` / `new` / `lost` and reports
  the implied bump. `--require <bump>` enforces honest semver at publish time;
  `--frozen` fails on any behavior delta under a pinned dependency. The Rust and
  Python wedges (`cargo sugar`, `sugar-check`) drive this verb.
- `sugar dump`: pretty-print a `.proof` envelope (members, bodies,
  signatures).
- `sugar hash`: compute the BLAKE3-512 CID of a file or stdin.
- `sugar implicate` (alias `imp`): mint an implication memento (antecedent
  CID to consequent CID) via z3.
- `sugar compose`: the JSON-RPC transport for the canonical compose
  primitive.
- `sugar recognize`: scan source for shapes matching published sugar binding
  templates and emit tags (the reverse direction of `materialize`).
- `sugar materialize`: materialize concept-citation carriers into
  library-bound source via realize kits.
- `sugar bind`: bind concept contracts to source code (the eight-verb
  pipeline against arbitrary user code).
- `sugar emit`: emit target/framework test artifacts from neutral contract
  predicates.
- `sugar doctor`: validate a kit's config and manifest wiring before a run.
- `sugar init`: scaffold a project (`sugar.toml`, `.sugar/`, sample
  invariant, GitHub Action).

- `sugar lift`: dispatch the configured lift surface and write its ProofIR
  term JSON. `lift` stops at the lifted terms; `mint` is the verb that envelopes
  them into a signed `.proof`, which is what every example here uses.

The command surface keeps moving as protocol work lands; `sugar --help` is the
source of truth.

## Install

This repository is build-from-source today. Crates.io publishing is still future
work. The current install path is:

```sh
cargo install --path implementations/rust/sugar-cli
```

Confirm it installed:

```sh
sugar --version
```

For a first run, build the workspace binaries the demos invoke (each `run.sh` calls
`implementations/rust/target/debug/…` directly, so `cargo install` alone is not
enough), then work through the demos in [examples/](examples/); each `run.sh` mints,
proves, and verifies end to end:

```sh
(cd implementations/rust && cargo build)
```

If you are working on Sugar itself, see [docs/contributing/build.md](docs/contributing/build.md)
for the polyglot Make targets, system dependencies, and per-implementation build commands.

## Run the demos

The numpy demos provision their own venv on first run.

| Demo | What it shows | Path |
|---|---|---|
| Vendor a whole library | every module-level numpy function lifted into one `.proof`, no shim; witness package; consumer `verify` recomputes | [examples/numpy-vendor/](examples/numpy-vendor/) |
| Discharge two ways | one operation, `numpy.rot90`: consistency discharged (z3) and the degenerate twin refused both ways (z3 UNSAT + witness recompute) | [examples/numpy-showcase/](examples/numpy-showcase/) |
| Inheritance capstone | a consumer inherits numpy's contract and is refused when it contradicts it | [test_inheritance_e2e.py](implementations/python/sugar-lift-py-tests/tests/test_inheritance_e2e.py) |

## Current status

- **Canonical implementation:** the Rust CLI in
  `implementations/rust/sugar-cli`.
- **Protocol catalog:** embedded in the CLI and surfaced by `sugar self-check`.
  The binary is the live authority for the catalog CID; do not trust a version
  written in prose.
- **Supported ecosystem surface:** coverage is empirical and uneven across
  languages, and it changes faster than prose can track. The runnable
  [examples/](examples/) are the honest picture of what works end to end today;
  if it is not a passing example, treat it as in progress.
- **Proof artifacts:** `.proof` envelopes, signed mementos, source CIDs, witness
  CIDs, contract CIDs, attestation CIDs, contract-set CIDs, and protocol catalog
  CIDs are the durable units.
- **Self-application:** the CLI can mint proof data from its own assertions and
  tests; see
  [docs/self-application/2026-05-28-snake-eats-tail.md](docs/self-application/2026-05-28-snake-eats-tail.md).

## Start here

The user-facing docs were written ahead of the implementation and described
installers and per-language flows that do not exist, so they were removed rather
than left as fiction. What remains is real: the runnable demos, the code, the
vocabulary, and the papers. The honest usage docs now return as each end-to-end
path lands — **[docs/getting-started.md](docs/getting-started.md) is the first one
back**, built only on demos that run today. The full map is [docs/](docs/).

| Goal | Read |
|---|---|
| Get from clone to a verified `.proof` | [docs/getting-started.md](docs/getting-started.md) |
| Run the headline demo | [examples/numpy-vendor/](examples/numpy-vendor/) |
| See everything that runs today | [examples/](examples/) |
| Learn the vocabulary | [SHARED-LANGUAGE.md](SHARED-LANGUAGE.md) |
| Browse all docs | [docs/](docs/) |
| Build Sugar from source | [docs/contributing/build.md](docs/contributing/build.md) |
| Read the paper ladder | [docs/papers/README.md](docs/papers/README.md) |

## What Sugar is not

Sugar is not a replacement for tests. Tests remain the source of much of the
evidence that kits lift.

Sugar is not a replacement for Kani, Prusti, Coq, Lean, F*, Dafny, TLA+, z3,
or other verification tools. Those tools produce evidence; Sugar gives that
evidence a portable, content-addressed, recomputable supply chain.

Sugar is not a central registry. `.proof` artifacts verify from their bytes,
CIDs, signatures, witnesses, and local policy. A server may index proof data for
convenience, but it is not the authority.

Sugar is not a promise that any current kit sees every useful contract in a
codebase. Adapter coverage is empirical. Unknown, unsupported, or lossy surfaces
must be reported honestly as residue, loss, or refusal.

## License

Licensed under either of [Apache License, Version 2.0](LICENSE-APACHE) or [MIT license](LICENSE-MIT) at your option.

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion in this work by you shall be dual licensed as above, without any additional terms or conditions.

Proof artifacts you generate with Sugar are yours; no license attaches to them.

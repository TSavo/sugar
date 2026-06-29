# Sugar
**Makes software honest.**

> **Sugar in, `.proof` out.**
> One z3 check. Every language. Every surface you already wrote. Zero code changes.

Sugar stops supply-chain attacks by federating correctness across every language, with zero changes to your code. It got there by doing nine impossible things, and the order is not a list, it is a chain: each one forced the next. It begins with a single unit test and ends with the tool turned on itself. Here is the whole thing.

## 1. Lift every language into one logic

To check a Rust library and a Python library with one tool, you need both in the same form. The textbook way is to *model* each language — its semantics, its standard library, its thousand corner cases — and those models rot, disagree, and never match the real thing. Forty years of formal methods says pick one language and go deep, or stay shallow and lie. Doing it faithfully for *every* language, from the code people already shipped, is impossible.

So Sugar doesn't model the language. It reads a claim the code already makes. `assert encode("abc") == "def"` is the package swearing, in the language it shipped, that this call returns that value. Sugar treats it as a **warrant**, grows just the small universe that claim needs — the literals, the fixtures, the standard-library facts around that one callsite — and lifts *that* into first-order logic. Not the language. The claim. And a claim lifts the same out of Rust, Python, or Java. What Sugar was left holding was logic, not a program. And logic lets you do one thing a program never can.

## 2. Throw away order

A program is made of order. This line before that one, this write before that read, this lock before that access. Order is the whole reason a program means anything; delete it and you don't get a faster program, you get an incident report. Every compiler engineer knows this, and every compiler engineer is right. Building something useful by throwing order away is, of course, impossible.

We didn't know that. So we did it anyway, and the thing left in Sugar's hands was a *theory*: `A ∧ B ∧ C`, and a conjunction doesn't care what order you read it in. Order didn't vanish; where it genuinely matters it survives as a plain fact, `Before(write, read)`. It just stopped being the *structure*. The category error was the door, and what came through it was a theory with a property no program has: one canonical form. A thing you can finally hash.

## 3. Give every behavior a name no one has to trust

You want to ask one question about a dependency: is this the same behavior as last week, or did something move? Names can't tell you — a name is a promise. Versions can't — SemVer is a social claim in a lab coat. Signatures can't — they vouch for bytes, not behavior. Every answer routes back to trusting *someone*. A name for behavior itself, that no human has to vouch for, is naturally impossible.

So Sugar hashes the behavior. Every test, warrant, callsite, contract, and witness gets a 512-bit name (BLAKE3-512, signed with Ed25519); change one byte of what the code *does* and the name changes. "Same behavior?" stops being a database lookup or an act of faith and becomes `memcmp(64)`. The `.proof` is a case file where every exhibit names itself, and the name is the evidence. But a name only tells you that behavior moved, not whether some new claim is allowed to live inside it. For that, you have to check it.

## 4. Prove what a function does without running it, while modeling nothing

Normally, to prove a function returns the right answer you have to know what it computes: reimplement it, model it, or run it on every input. Reimplement it and you've become a second, buggier copy of the thing you're checking. Run it and you only ever learn about the inputs you tried. Knowing what an arbitrary function does without doing either is quite impossible.

So Sugar refuses the problem. It never reimplements the function and never runs your input. It hands z3 your claim and the function's *own* lifted body and asks one thing: can both be true at once? The vendor's tests say `enc("abc") == "xyz"`; you claim `enc("bby") == "chk"`; z3 answers SAT or UNSAT against the body itself. UNSAT means your claim could not have come from that function — proven, on an input nobody ever tested, with no test run. Sugar isn't searching for the answer; it already has it, and only asks whether you contradict it. This works exactly as far as the lifting reaches. And the lifting stops where every honest tool eventually trips: the parts of a program that touch the world.

## 5. Map a program without lying about the parts you can't see

Real code touches the world: the filesystem, the network, the clock, randomness, a subprocess, FFI into something no one can read. A tool that wants to map a program is tempted to model all of it too — and the moment it does, it's a hallucination with a CLI, confidently narrating an Internet it cannot see. Mapping a program *without* lying about the parts you can't model, drawing the edge of the known instead of painting past it, is impossible to do and stay honest.

So Sugar makes purity earn the map and makes every effect mark its own edge. Pure code expands the universe. A file read pins a point and records the trace; a network call, a clock, a coin flip, a subprocess each stop the map and post a sign. That sign is not a failure. It's the map saying *here be dragons*, drawn to scale — the only honest thing a map of real software can say. Which leaves Sugar selling a map that is mostly edges. Mostly "we don't know." Nobody, it turns out, thinks they want that.

## 6. Sell uncertainty

Nobody buys "I don't know." Every tool in this space sells certainty: a green check, a passing suite, a clean scan, because certainty is what people think they want. But certainty about software is mostly a flattering lie, and the information that actually hurts you was never in the part that passed. Selling the *unknown itself* as the product is — in case you haven't guessed yet — quite impossible.

So Sugar sells the exact shape of the unknown. Every claim lands somewhere named: pinned, contradicted, witnessed, bounded, fixture-only, outside the membrane, or unknown. The green proof is the boring half. The product is the other one — the precise, enumerated list of the behavior nobody ever swore to, per dependency, the empty set included and hashed. Certainty you can fake; the shape of your ignorance, drawn honestly, no one else will sell you. And none of it is worth anything if no one runs it, which is exactly where every verifier before Sugar quietly died: at the toll booth.

## 7. Do all of it with zero changes to your code

Every verification tool in history charges a tax: write the spec, add the annotations, learn the proof language, contort the code until the prover can see it. That tax is why verification stayed in aerospace and out of your repo. A tool that asks for *nothing* — no spec, no annotation, no new dialect, not one changed line — shouldn't be able to know anything at all. That is impossible.

Except the spec was already in your repo. Sugar's per-language kit reads what's there — tests, bodies, annotations, package metadata — and that's the entire input. `cd` into a project, `sugar mint`, and out comes a signed `.proof`; the next consumer, in any language, drops it in and `sugar prove`s their code against it. No specs, no logicians, no asking Python to stop being Python or C++ to stop being a haunted mansion full of knives. The numpy demo lifts every module-level function with zero code changes and no shim. When the tax is zero, packages ship their behavior, not just their version number. And a world where packages ship behavior is the only one where the gap an attacker hides in finally closes.

## 8. Stop supply-chain attacks

A supply-chain attack lives in the gap between what you installed and what behavior you agreed to run. The industry's answer is to add a trusted party to the chain — a scanner, a registry, a vendor saying *trust us, we found the bad thing* — which "solves" a trust problem by adding one more thing to trust. Closing that gap without becoming the next link to be compromised is, naturally, impossible.

So Sugar owns nothing. You own your kit, your solver, your policy; every part is replaceable; Sugar just hands you the claim, the warrant, the witness, and the hash, and tells you to check it yourself. That's federated correctness. And because behavior now has a hash, the attack has nowhere to hide: change what a package does and its root moves, reach outside its cage and the membrane breaks, ship a quiet `minor` that does something new and the diff lights up. SemVer says nothing important changed; Sugar shows you whether that's true. Which leaves one question, the one a tool that says "trust nothing" had better be able to answer about itself.

## 9. Wrap the whole thing in a proof of itself and ship it

There is one honesty test a correctness tool cannot talk its way out of: turn it on itself. Most never do, because the machine that checks everything is usually the one thing nobody checked. Proving your own correctness engine with your own correctness engine, and shipping the result, is impossible, or at least deeply unwise.

We didn't know that either. Sugar mints proof data from its own tests and assertions; the snake eats its [tail](docs/self-application/2026-05-28-snake-eats-tail.md). Sugar in, `.proof` out, all the way down.

The White Queen managed to believe six impossible things before breakfast. Sugar does nine, and signs them.

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

Source files use SPDX headers where present. A repository-level license file has
not been added yet.

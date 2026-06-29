# Sugar
**Makes software honest.**

> **Sugar in, `.proof` out.**
> One z3 check. Every language. Every surface you already wrote. Zero code changes.

Sugar stops supply-chain attacks by federating correctness across every language, with zero changes to your code. It does that by doing nine impossible things. Here they are, in the order they had to happen. After each one we will tell you, plainly, that it is impossible. Then we will tell you how Sugar does it anyway.

## 1. Lift every language into one logic.

That's impossible.

Sugar reads the claims your code already makes. `assert encode("abc") == "def"` is a package swearing, in the language it shipped, that this call yields that result. Sugar treats that test as a **warrant**: it grows the one small universe the claim needs — the literals, the fixtures, the standard-library facts around that callsite — and lifts it into first-order logic. Rust, Python, Java: the surface differs, the logic underneath does not.

## 2. Throw away order.

That's impossible. A program is made of order: this line before that one, this write before that read.

So Sugar stops holding a program. Once a claim is lifted, what is left is a theory — `A ∧ B ∧ C` — and a conjunction does not care what order you read it in. Order is not lost; where it matters it becomes just another fact, `Before(write, read)`. An orderless theory is something you can canonicalize, hash, conjoin, and ship. A program is not. That is the whole move.

## 3. Give every behavior a name no one has to trust.

That's impossible.

Sugar hashes all of it. Every test, warrant, callsite, contract, witness, kit, and solver query gets a 512-bit name (BLAKE3-512; signatures are Ed25519); change one byte and the name changes. "Are we talking about the same universe?" stops being a database lookup, or a matter of trust, and becomes `memcmp(64)`. The `.proof` is a case file in which every exhibit names itself.

## 4. Prove what a function does without running it, while modeling nothing.

That's impossible.

Sugar never reimplements the function. It hands the solver your claim and the behavior you imported and asks one thing: can these coexist? The vendor's tests say `enc("abc") == "xyz"`; you say `enc("bby") == "chk"`; z3 answers SAT or UNSAT against the function's own lifted body. UNSAT means your claim could not have come from that function. You can prove an input the vendor never tested, and no unit test runs.

## 5. Map a program without lying about the parts it cannot see.

That's impossible.

Pure code expands Sugar's universe; every effect has to earn its place. A file read pins a point and records the trace. A network call, a clock, randomness, FFI, a subprocess: each one stops the map and marks the edge. That edge is not a failure. It is the map saying *here be dragons*, drawn to scale, instead of a hallucination with a CLI pretending it modeled the Internet.

## 6. Sell uncertainty.

That's impossible.

Sugar does not sell certainty. It sells the exact shape of uncertainty. Every claim lands somewhere named: pinned, contradicted, witnessed, bounded, fixture-only, outside the membrane, or unknown. A green proof is the boring half. The product is the other one: the precise, enumerated list of behavior nobody ever swore to, per dependency, the empty set included and hashed. Unmarked uncertainty is the only enemy.

## 7. Do all of it with zero changes to your code.

That's impossible.

A kit per language reads what is already there: tests, bodies, annotations, package metadata. Existing artifacts in, behavior map out. No specs. No annotations. No proof language. No asking maintainers to become logicians, no asking Python to stop being Python or C++ to stop being a haunted mansion full of knives. `cd` into a project and `sugar mint` writes a signed `.proof`; the next consumer, in any language, drops it in and `sugar prove`s their own code against it. The numpy demo lifts every module-level function with no code changes and no shim.

## 8. Stop supply-chain attacks.

That's impossible. You cannot fix a trust problem by becoming one more vendor saying *trust us, we found the bad thing*.

So Sugar owns none of it. You own your kit, your solver, your policy; every part is replaceable; Sugar hands you the claim, the warrant, the witness, the hash, and tells you to verify it yourself. That is federated correctness. An attack is a *behavior*, and behavior now has a hash: change what a package does and its root moves; reach outside the cage and the membrane breaks. SemVer says nothing important changed, promise; Sugar shows the behavioral diff. There is nowhere quiet left to hide.

## 9. Wrap the whole thing in a proof of itself and ship it.

That's impossible.

Sugar mints proof data from its own tests and assertions. The snake eats its [tail](docs/self-application/2026-05-28-snake-eats-tail.md). Sugar in, `.proof` out, all the way down.

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

# Sugar

**Makes software honest.**

> **Sugar in, `.proof` out.**
> One z3 check. Every language. Every surface you already wrote. Zero code changes.

You don't really know what your software does. You know the packages you installed and the versions you pinned. But you depend on what the code *does*, across every dependency, in every language, including the ones you have never read, and that is the one thing nothing tells you. It is also the only thing that has ever hurt you.

Sugar gives it back as a report you can read and a file you can hand to a stranger.

## The product is a report

```sh
sugar lift --report --visual <your code>
```

pretty-prints your code, green until red. Every green line carries its **warrant**: the vendor's own citation, printed next to the line that earned it. Every red line carries a **typed effect**: a named reason the line touches something no one can prove (a C-backed body, IO, a runtime value, an `unsafe` block). There is no third color.

The report's completeness is the honesty of the entire system. If one line renders as neither green nor red, the product is not "mostly done", it is a lab coat with nothing under it. So the system is built to make an incomplete report impossible to ship quietly: an unrecognized shape does not degrade, it panics.

## The entire product is one match expression

```
match(Sugar) {
    Some(s) => cite_or_effect(s),
    None    => panic!(),
}
```

That is the whole lift.

- **`None => panic!()`** There is no third arm. Not refuse, not a catch-all, not a benign default. The panic is not error handling; it is the worklist generator. The set of panics over a corpus is a number you can census, bucket, and drain. Every recognizer ever written is "add an arm to the match."
- **`Some(s) => cite_or_effect(s)`** The arms are where trust lives. Every arm terminates in exactly two outputs: a warrant cited from the vendor (green) or a typed effect (red). A forged green type-checks fine and is worse than any panic, so every recognizer ships with a **bad twin**: the same claim with the answer swapped, which must come back UNSAT. An acquittal only means something in a courtroom capable of conviction.
- **Refusal does not exist at lift.** "Refused: insufficient evidence" is an honest ruling with exactly one home: verify, the referee. It was evicted from everywhere else.

## Zero code for anything the vendor ensures

Sugar contains no type checker, no borrow checker, no method resolver. Not as an omission: as the load-bearing property.

The kit's domain of definition is **compiling programs**. rustc's yes (or the vendor test suite's pass, per language) is the precondition for everything downstream, so every type composition is correct **by construction**: the vendor's checker already ran, and it didn't panic. Type-correctness enters the system as witnessed input, never as a judgment Sugar computes. This is why Sugar cannot drift into becoming a second rust-analyzer: there is no type-checking code to drift.

The edge of the contract, stated precisely: **we make no guarantees about code the vendor makes no guarantees about.** Feed the system input the vendor's compiler rejects and its behavior is undefined, in the C sense, by design. The red report for uncompilable code belongs to rustc, and rustc is the thing that reports it. `unsafe` is the vendor's own undecidable tag, written into the grammar by the compiler's authors; Sugar transports the tag and renders the interior honestly red, forever.

## Verify is a courtroom

Verification never derives an answer. It asks one question: **given this vendor-sworn fact, this universe of constraints, and this claim, do all three cohere?**

Your code says `np.add(2, 3) == 5`. The vendor's own lifted testimony says what `add` swore under its own tests. The pinned FOL universe says what arithmetic means. z3 is asked whether all three exhibits can coexist in one model. Sugar never runs `np.add`, never reimplements it, never tries the glove on. It exonerates the claim or fails to, and the bad twin (`== 6`) must fail, or the exoneration was theater.

The verdict is conditional all the way down, and honestly so: if the vendor's testimony is false, the verdict inherits the lie. Impeaching the vendor was never this court's jurisdiction. What the court guarantees is that no claim is ever certified by anything other than sworn testimony plus logic, and that every certification can be re-run by anyone.

## The universe is content

```
h = h(p)        the address of a thing is a pure function of the thing
p = l(h)        the thing is recoverable from its address
```

Every proof, contract, source file, and memento in the system is content-addressed under BLAKE3-512. A memento does not reference a program that could drift away from it; it contains h(p), and h(p) admits exactly one preimage. The binding problem is not solved here; it cannot be stated.

There is no RNG in the system. There are no calls to time. Nothing ambient enters an evaluation, so every artifact is a value, not an event: re-evaluable by anyone, forever, always to the same answer. A signature signs "this value is in my universe", never "trust me, I saw it happen." Either p = l(h(p)), given p, or it is not our problem: bring the content and it self-certifies; no oracle, no registry, no availability committee.

## What that buys you

- **You catch a wrong assumption before you run it.** Claim `np.add(2,3) == 6` and z3 returns UNSAT against the function's own lifted testimony: a red squiggle on a line that cannot hold, before prod, on an input nobody ever tested.
- **You find out whether a dependency's behavior actually moved.** Behavior has a canonical form, and a canonical form has a hash. `sugar diff` classifies every behavior-CID as held, renamed, new, or lost, and reports the implied bump. The silent breaking change and the poisoned patch both light up before they reach prod.
- **You ship your correctness, and the next person inherits it.** A `.proof` is signed and content-addressed; a consumer verifies it without trusting you, in a language that isn't even yours. A Rust caller and a Python contract meet at the same callsite, and contradiction is refused.
- **You stop importing attacks.** Sugar owns nothing: your kit, your solver, your policy, every part replaceable. Behavior has a hash, so an attack has nowhere to hide: change what a package does and its root moves; ship a quiet minor that does something new and the diff lights up. You import behavior, not bytes.

## What the CLI does

> _Naming: the project is **Sugar**. The proofchain identity layer (kit ids, wire tokens, `.proof` producer strings) is content-addressed and frozen on purpose. Names are sugar, CID is identity._

The canonical CLI is the Rust `sugar` binary. Run `sugar --help` for the authoritative list; the current subcommands include:

- `sugar lift`: dispatch the configured lift surface and write its ProofIR term JSON. `--report --visual` renders the warrant report.
- `sugar mint`: dispatch the configured lift plugins and envelope the lifted terms into signed `.proof` artifacts.
- `sugar prove`: run the six-stage verifier. Load proofs, resolve dependency proofs through kits, enumerate callsites, conjoin same-named contracts, solve obligations, recompute witnesses, and report discharge status.
- `sugar verify`: verify a kit end to end. Lift its contract claims, discharge each via the solver-dispatch table, recompute witnesses with the kit oracle untrusted, and emit a signed per-claim receipt. This is the gate verb.
- `sugar diff <a> <b>`: compare two minted proof sets by behavior, not text. `--require <bump>` enforces honest semver at publish time; `--frozen` fails on any behavior delta under a pinned dependency.
- `sugar dump`: pretty-print a `.proof` envelope (members, bodies, signatures).
- `sugar hash`: compute the BLAKE3-512 CID of a file or stdin.
- `sugar implicate` (alias `imp`): mint an implication memento (antecedent CID to consequent CID) via z3.
- `sugar compose`: the JSON-RPC transport for the canonical compose primitive.
- `sugar recognize` / `sugar materialize` / `sugar bind` / `sugar emit`: the concept-contract pipeline against arbitrary user code.
- `sugar doctor`: validate a kit's config and manifest wiring before a run.
- `sugar init`: scaffold a project (`sugar.toml`, `.sugar/`, sample invariant, GitHub Action).

The command surface keeps moving as protocol work lands; `sugar --help` is the source of truth.

## Install

This repository is build-from-source today. Crates.io publishing is still future work.

```sh
cargo install --path implementations/rust/sugar-cli
sugar --version
```

For a first run, build the workspace binaries the demos invoke (each `run.sh` calls `implementations/rust/target/debug/…` directly, so `cargo install` alone is not enough), then work through the demos in [examples/](examples/):

```sh
(cd implementations/rust && cargo build)
```

If you are working on Sugar itself, see [docs/contributing/build.md](docs/contributing/build.md).

## Run the demos

The numpy demos provision their own venv on first run.

| Demo | What it shows | Path |
|---|---|---|
| Vendor a whole library | every module-level numpy function lifted into one `.proof`, no shim; witness package; consumer `verify` recomputes | [examples/numpy-vendor/](examples/numpy-vendor/) |
| Discharge two ways | one operation, `numpy.rot90`: consistency discharged (z3) and the degenerate twin refused both ways (z3 UNSAT + witness recompute) | [examples/numpy-showcase/](examples/numpy-showcase/) |
| Inheritance capstone | a consumer inherits numpy's contract and is refused when it contradicts it | [test_inheritance_e2e.py](implementations/python/sugar-lift-py-tests/tests/test_inheritance_e2e.py) |

## Current status

- **Canonical implementation:** the Rust CLI in `implementations/rust/sugar-cli`.
- **The wall is being built.** The totality campaign drives the panic count over real corpora (all of numpy first) to zero, shape by shape, each drain an honest recognizer with a flipping bad twin. R > 0 today, and CI says so, because R > 0 red is honest and a forged green is not.
- **Supported ecosystem surface:** coverage is empirical and uneven across languages, and it changes faster than prose can track. The runnable [examples/](examples/) are the honest picture of what works end to end today; if it is not a passing example, treat it as in progress.
- **Proof artifacts:** `.proof` envelopes, signed mementos, source CIDs, witness CIDs, contract CIDs, attestation CIDs, contract-set CIDs, and protocol catalog CIDs are the durable units.
- **Self-application:** the CLI mints proof data from its own assertions and tests; the snake eats its [tail](docs/self-application/2026-05-28-snake-eats-tail.md).

## Start here

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

Sugar is not a type checker, a borrow checker, or a rust-analyzer. It contains zero code for anything the vendor's compiler ensures, on purpose, forever.

Sugar is not a contract language. There are no annotations, no spec files, no proof DSL. The only path to ProofIR is the lift of native source the vendor already tested.

Sugar is not a replacement for tests. Tests remain the source of much of the evidence that kits lift: the vendor's tests are the testimony.

Sugar is not a replacement for Kani, Prusti, Coq, Lean, F*, Dafny, TLA+, or z3. Those tools produce evidence; Sugar gives evidence a portable, content-addressed, recomputable supply chain.

Sugar is not a central registry. `.proof` artifacts verify from their bytes, CIDs, signatures, witnesses, and local policy. A server may index proof data for convenience, but it is never the authority.

Sugar is not a promise that any current kit sees every useful contract in a codebase. Coverage is empirical, the frontier is a number, and the number is public: unknown surfaces panic loudly rather than report green quietly.

## License

Source files use SPDX headers where present. A repository-level license file has not been added yet.

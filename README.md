# Sugar
**Makes software honest.**

> **Sugar in, `.proof` out.**

Nobody depends on your code. They depend on what your code *does*. Sugar takes
the ordinary surface you already write, the *sugar* (tests, assertions,
contracts, schemas, validators, framework annotations, boundary and library
bindings), and turns it into a signed, content-addressed `.proof` of the
**behavior**: a portable claim other packages, tools, and languages can
re-verify by recomputation, without trusting your test runner and without
re-running your proof. It never asks anyone to rewrite code in a proof language.
"Just sugar," the surface everyone waves off as not-the-real-thing, is exactly
where correctness turns out to live.

Sugar in, `.proof` out. CIDs are BLAKE3-512; signatures are Ed25519.

## The part that should keep you up at night

Invert how you read a proof. Your `.proof` is not your *score* — it is your
**safe ground**. It is the one part of your system where things are not going to
go wrong, because it is the one part that cannot lie about itself. Everything
outside it is not "untested." It is a **crime scene waiting to happen**: the
staked-out territory where the next breach, the next silent regression, the next
poisoned dependency already lives, because nothing there is holding it back.

So a `.proof` is the easy half. The hard half — the half no other tool can
print — is the **shape of what was never proven at all**: the exact outline of
the ground you are standing on that has nothing underneath it.

Sort every fact in a program into two piles. *Right by construction*: the things
something **stated** and staked its name on — a compiler axiom, a sworn test, a
walked implementation. These are recomputable, signed, and yours to check.
*Right by convention*: everything else. The code that is "right" the way an
unmarked intersection is "safe" — nothing certifies it, nothing contradicts it,
and everyone drives through because driving-through is the convention. **It is
right because nothing says it shouldn't be.** And almost all of the software
running the banks, the hospitals, and the grid is this second kind: a tower of
hot promises, twenty layers deep, with nothing tying any floor to the next.

And here is the inversion that actually matters: **the value of the analysis is
not in the satisfied. It is in the *these parts are undecided*.** A green proof
is table stakes — honest software is mostly consistent, so the satisfied rows are
the *expected* result, not the product. The product is the precise, enumerated
list of the parts that are **not** decided: the ground with nothing under it,
named.

Because Sugar accounts for *everything* it reads — every statement lifted or
refused **by name**, never silently — the unsworn remainder stops being a blur
and acquires a perimeter. A coverage tool tells you 78% of your lines ran. Sugar
tells you the one thing nobody has ever been able to print: **here is the exact
list of behaviors no one ever promised you** — per dependency, drawn by the
proofs around it. The empty set is an artifact too; it gets a hash.

So the alarm inverts. Everyone else fires when something makes a noise. Sugar
fires when something that should have testified, *didn't* — when a dependency
updates and its entire behavioral delta lands in territory no one ever swore to.
Not detection of the backdoor. Detection of the conditions that make backdoors
the rational move. The dog that didn't bark — with a signature on the silence.

The thing that flaps in the night was never the unit test. It is the **lack** of
one. It is the API shape that lifts to `[]`. It is the endpoint with no `.proof`
behind it — load-bearing, shipped, depended on by thousands, and warranted by
absolutely nothing. That is the product. We do not sell *"here is a `.proof`
file, and here is where it solves."* We sell:

> **Here is the gap between what you hope is true, and what is completely without
> warrant.**

That is the vision. Not "we prove your code is correct." **We make software
honest** — it can no longer claim more than it can prove, and it can no longer
hide what it never swore.

## Why a contract beats a test

A test checks your code against the world *as it was the day you wrote the
test* — the inputs in your fixtures, the dependency in your lockfile, the
environment on your laptop.

Here is the one no compiler and no test will catch. You depend on a library
whose `search(q)` returns matches **sorted by score**, so your code takes
`results[0]` as the best match — and has, correctly, for years. One release, the
vendor drops the guarantee: *"results are no longer ordered; sort client-side if
you need it."* It is right there in the changelog. They **advertised** it.

Nothing in your code changes — nothing *can*. The type never moved: `Vec<Match>`
before, `Vec<Match>` after; order was never in the type. And not one unit test
turns red, because your tests run against the version in your lockfile — the old
one, still sorted — so `results[0]` is still best, and green is green. The
breaking change is real, shipped, and announced, and **completely invisible to
your suite**, because your suite verifies your code against the dependency *as it
sat in dev*, not as it now *is*.

Then prod pulls the new release. `results[0]` is whatever came back first, and
every user silently gets the wrong top result. Here is the part that should
sting: **that same unit test, run in production against the new dependency, goes
red.** The test was never wrong — it was running in the *wrong universe*, pinned
to a behavior the world had already moved past.

A type can't catch it: order is not a shape. A test can't catch it: it only ever
saw the old behavior, in dev. What moved was the **contract** — a postcondition
the vendor advertised away — and the contract is the one thing neither your
compiler nor your test runner is even looking at.

> **Tested says it didn't break here, now. Correct says it cannot break, anywhere.**

That contract is what a `.proof` *is*: the dependency's behavior, pinned and
content-addressed, that you compose against instead of trusting a version
number. The day the vendor's behavior moves, its `.proof` moves with it — a new
CID — and your composition stops verifying, **at the diff, in any environment,
before prod ever pulls the release.** A passing test is an existence proof:
*there exist* inputs, in dev, on which it worked. A `.proof` is a universal one:
*for all* inputs, against the behavior as it actually is, it holds. One says it
didn't break here. The other says it can't break anywhere — and trips the
instant the ground moves under it.

## Why it matters: the version lied, the behavior moved, Sugar saw it

SemVer versions the *shadow*. It bumps when the bytes change and holds still when
they don't, so it is jumpy about a rename and **stone blind to a backdoor**: a
bugfix and a malicious patch are both "a patch." Nobody can read a version number
and learn the one thing they actually need. Did the behavior move.

Sugar versions the *object*. Lift any source and each behavior becomes a
content-addressed contract; `sugar diff` compares two proof sets by behavior, not
by text:

- A rename, a reformat, a behavior-preserving refactor reads as `none`. No false
  alarm, so you never train yourself to ignore the tool.
- A behavior that appears or vanishes under a frozen version reads as `new` or
  `lost`. That is the malicious patch the version number hid.

You cannot bolt a credential harvester onto a package for free. New behavior means
new effects (reads, writes, sockets), and effects cannot hide inside a fingerprint
that records them: the CID moves, or the fingerprint is lying. This is the shape of
the npm and PyPI supply-chain compromises that publish poisoned versions under
continuous-looking version numbers. `sugar diff --frozen` fails on any behavior
delta under a pinned dependency; `--require <bump>` turns the version from a
promise a human types into a measurement derived from the proof delta, so a
release that calls itself `minor` while a behavior was lost is refused at publish
time.

Honest scope: this works **today** as `cargo sugar` (Rust) and `sugar-check`
(Python pre-commit hook). The npm/JS wedge is in progress; what is missing is the
lifter, not the thesis.

## What `sugar diff` measures: your coupling, their cohesion

Upgrade a dependency and run `sugar diff`. You don't get the *"these bytes
changed"* report — that's `git`, the shadow: blind to a backdoor, loud about a
rename. You don't get the *"we think the API works this way now"* report —
that's the changelog, prose, optimistic and unmapped to your code. You get the
**"here be the new dragons"** report: the diff of the **behavior**, recomputed,
intersected with exactly what your code leans on. Not *"the vendor changed
`search`"* — *"your dependence on `search` returning sorted is now unproven."*
The exact welds that broke. Your real blast radius, before prod.

That is **cohesion and coupling, finally measured.** They have been the two axes
of software quality since 1974, and for fifty years they were *adjectives* —
eyeballed in review, approximated by what-imports-what. A `.proof` makes them
data. The provider's `.proof` is a **cohesion surface**: the coherent set of
behaviors it actually holds — *our surface is this.* Your composition is a
**coupling**: the subset of that surface your code provably leans on — *you are
coupled in this way.* Every dependency edge is a coupling aimed at a cohesion
surface, and `sugar diff` is what happens when the surface moves under the
coupling.

Two levers fall out — the ones shape-based metrics could never hand you:

- **Minimize coupling on purpose.** Depend on the smallest surface you can, and
  your blast radius on *any* release is exactly the size of `your coupling ∩
  their change` — a number you drive toward zero deliberately, instead of
  praying through the upgrade.
- **Publish cohesion, and be held to it.** A provider states their surface —
  *this, and no more* — and a tight, honest surface is visibly safer to depend
  on than a sprawling, accidental one, *before* you take the dependency.

And it is the one report **no vendor can ship**, for a precise reason: the
dragons are `your coupling ∩ their change`, and that needs **both halves at
once**. The provider owns the cohesion surface and can publish it; only you own
your coupling. Only you, at compose time, hold both — so the vendor has one side
of the equation and cannot finish it. You have the other, and `sugar diff`
completes it.

## How a `.proof` works: the claim, formally

Correctness is `k(I) = t`: a program `k` applied to an input/precondition `I`
produces an output/postcondition `t`. A `.proof` is a kept promise made
checkable. The program, the input, and the result are each content-addressed
and pinned, so the claim names exactly what it is about and cannot be silently
rebound. `sugar verify` lets a stranger recompute the guarantee.

A `.proof` is discharged **two independent ways, and both must agree**:

- **CONSISTENCY.** A solver (z3) proves the lifted contract is internally
  satisfiable. A self-contradictory spec is refused without running anything.
- **WITNESS.** The code is actually run, the run is content-addressed, and
  `verify` recomputes it. A witness that does not reproduce its pinned CID is
  refused.

The numpy showcase (`examples/numpy-showcase/`) exercises both on a real library
operation: a self-contradictory assertion is refused **both ways** — z3 finds the
conjunction UNSAT, and the witnessed re-run fails to reproduce it. The demo is the
receipt; run it for the current output.

## First principle: supra omnia, rectum (above all, correctness)

Every operation is exact, or loudly-bounded-lossy, or it refuses. Verification
*is* recomputation: trust nothing, not even the kit that produced the proof.
Where a lift, lower, or solver discharge cannot be exact, the loss is recorded,
content-addressed, and named, never silent. "Loudly-bounded-lossy" is only
honest if the bound is written down.

## The oracle trio: a `.proof` carries identity, not bodies

A `.proof` does not embed source code or test logs. It carries IDENTITY: CIDs,
loci, and signatures. Bodies are resolved on demand and recompute-verified.
This is what lets a 2909-function numpy `.proof` stay 13M instead of shipping
all of numpy inside it.

- **Source Oracle.** Given a locus plus a CID, return the on-disk source iff it
  recomputes to that CID, else refuse loudly. `recognize` and `materialize`
  both feed source through this one oracle.
  (`implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/source_oracle.py`.)
- **Witness Oracle.** A witness is arbitrary signed content: a test run, a CI
  log, a poem. The kit oracle (python/java) is UNTRUSTED. Over RPC it only
  RESOLVES the witness body. The Rust CLI BLAKE3's the body itself and compares
  to the pinned CID. A wrong body for a CID (broken oracle) is distinguished
  from an honest re-run that differs (drift).
  (`implementations/rust/sugar-cli/src/witness_verify.rs`,
  `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/witness_oracle.py`.)
- A contract is already a CID. So the `.proof` is pure correctness identity:
  source, witness, and contract are all resolved-and-recomputed, never trusted.

## Ship a `.proof` for a whole library, no shim

`examples/numpy-vendor/` is the headline demo. The universal lifter reads
numpy's installed python source and sugar-lifts **every module-level function**
(the symbol is its qualified path, e.g. `lib._function_base_impl.rot90`) into
one lean `.proof` — **no code changes to numpy and no hand-written shim.** The
member count is whatever the lifter finds in the installed numpy, so it tracks the
numpy version (`numpy.add` is a C ufunc with no python body, so it is not among the
python functions lifted; the thousands that are python all lift).

The vendor ships the `.proof` plus a separately deployed witness package
(`<cid>.witness`, the audit material). A consumer runs `sugar verify`, which
recomputes everything — resolving the source and witness bodies through the package
and re-checking every CID. Run it with `examples/numpy-vendor/run.sh` (builds a venv
on first run); the demo prints the live output.

## The capstone: correctness is inheritable, and composition failures are caught

The important failure mode is composition. A package can pass its tests, another
package can pass its tests, and the assembled system can still contain
contradictory behavioral claims. This is no longer aspirational. There is a
working demo of catching exactly that.

A numpy vendor mints a `.proof` carrying the callsite-keyed contract
`np.add(2,3) == 5`. A consumer stages that `.proof` in `.sugar/imports/`,
asserts something about the same call, and runs `prove`:

- A consumer asserting `np.add(2,3) == 6` is **REFUSED**. It inherits numpy's
  `== 5`; z3 finds `and(== 5, == 6)` UNSAT.
- A consumer asserting `np.add(2,3) == 5` is **PROVEN**.

This works because contracts key to the CALLSITE under test (e.g.
`numpy.add#euf#...::assertion`), not to the test, and the verifier conjoins
same-named contracts across proofs before the SAT check. The consumer inherits
the vendor's correctness and is caught contradicting it.

Verified end to end:
`implementations/python/sugar-lift-py-tests/tests/test_inheritance_e2e.py`
(parametrized: `consumer-agrees-PROVEN`, `consumer-contradicts-REFUSED`) and the
unit test `cross_proof_same_named_contracts_are_conjoined` in
`implementations/rust/sugar-verifier/src/consistency.rs`.

## The shape: kits own language, the CLI owns proof

Sugar has two deliberately separate responsibilities.

**Kits own language reality.** A kit knows the language, package manager,
compiler, test framework, annotation library, and ecosystem conventions. A Rust
kit can walk Rust tests and contracts. A Java kit can read Bean Validation, JML,
Spring, JUnit, and Maven-shaped package data. A TypeScript kit can read Zod,
class-validator, fast-check, and npm-shaped package data. Kits **lift** native
evidence into ProofIR, **lower** admitted claims back into native source when a
workflow calls for it (the contract-facet of lower is an emitter, the
sugar-facet is a materializer), and resolve dependency `.proof` artifacts
through the package manager and filesystem rules of their ecosystem. Kits never
verify: they only resolve bodies over RPC.

**The CLI owns proof computation over normalized data.** The `sugar` CLI is
language-agnostic. It loads `.proof` artifacts, speaks RPC to configured kits,
normalizes claims, composes implications, conjoins same-named contracts, runs
the solver, recomputes witnesses, and reports discharge status. The CLI does not
know what a Maven classifier, npm workspace, Rust proc macro, or Spring
annotation means. The kit translates those surfaces to proof data; the CLI
computes over the proof data.

That boundary is the product. Sugar is not "a better Rust verifier" or "a
new test runner." It is the place where language-native evidence becomes a
portable, recomputable claim that survives package boundaries. For the canonical
definitions of sugar, boundary, lift, lower, concept, and contract, see
[SHARED-LANGUAGE.md](SHARED-LANGUAGE.md).

## The `.proof` DAG

A `.proof` artifact is a signed, content-addressed bundle of proof data. It can
contain contract mementos, source mementos, witness mementos, implication
witnesses, bridge attestations, materialization receipts, package inspection
claims, and policy-relevant metadata.

The graph is a DAG because every claim names the exact content it depends on:
contract CIDs, source CIDs, witness CIDs, attestation CIDs, contract-set CIDs,
proof-bundle CIDs, binary CIDs, and protocol catalog CIDs. Old facts remain true
about the old bytes that minted them. When code or claims change, new CIDs
appear. Nothing needs a central invalidation service; unchanged commitments
remain checkable by content identity.

```text
native evidence -> kit lift -> ProofIR / protocol claim
               -> signed memento -> .proof DAG -> sugar prove / verify
```

Previously minted, unchanged commitments can often be checked cheaply by CID
equality, signature checks, and graph walking. Semantic proving still happens
when claims are minted, changed, or newly composed in a way the DAG does not
already justify. Sugar does not make all proving constant-time. It amortizes
expensive proof work by making prior commitments content-addressed and reusable.

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
- **Protocol catalog:** embedded in the CLI and verified by `sugar
  verify-protocol`. The binary is the live authority for the catalog CID; do not
  trust a version written in prose.
- **Supported ecosystem surface:** coverage is empirical and uneven across
  languages, and it changes faster than prose can track. The runnable
  [examples/](examples/) are the honest picture of what works end to end today;
  if it is not a passing example, treat it as in progress.
- **Proof artifacts:** `.proof` envelopes, signed mementos, source CIDs, witness
  CIDs, contract CIDs, attestation CIDs, contract-set CIDs, and protocol catalog
  CIDs are the durable units.
- **Executable exhibits:** [menagerie/bug-zoo/](menagerie/bug-zoo/) runs checked
  specimens where native checks pass while lifted cross-package or
  cross-language obligations fail until the missing edge is closed.
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

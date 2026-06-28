<!--
  Getting started — the honest front door.
  House rule for this page (and every user-facing doc): receipts, not assertions.
  Every command and every output block below must trace to a runnable artifact in
  this repo. If a claim here is not backed by something that runs end to end,
  it does not belong on this page — name it as residual instead.
-->
# Getting started with Sugar

**Sugar makes software honest.** It takes the surface you already wrote — your
tests, your function bodies, your annotations and schemas — and turns it into a
signed, content-addressed `.proof` of what your code *does*. No new annotations.
No contracts to author. No proof language to learn. No special incantation when
you compile. And because it accounts for *everything* it reads, the parts it
**can't** prove don't vanish — they get named.

> **Sugar in, `.proof` out.** Your unit tests are your stated facts; your function
> bodies are your stated contracts. In every language, not just one.

This page takes you from a clone to a verified `.proof` and out the honest other
side, using demos that run end to end **today**. Every output below is reproducible
from a `run.sh` in this repo.

## Install (build from source)

Sugar is build-from-source today (crates.io publishing is future work):

```sh
cargo install --path implementations/rust/sugar-cli
sugar --version         # confirm the binary installed
```

`sugar --help` is the authoritative command list; it moves as protocol work lands.

The runnable demos below invoke the freshly-built workspace binaries directly
(`implementations/rust/target/debug/…`), so build the workspace too — `cargo install`
alone is **not** enough:

```sh
(cd implementations/rust && cargo build)
```

## The whole idea in 60 seconds

A `.proof` is the claim `k(I) = t` — a program `k` applied to input/precondition
`I` yields output/postcondition `t` — pinned and content-addressed so it names
exactly what it is about and can be re-verified by **recomputation**, without
trusting your test runner. It is discharged two independent ways that must agree:

- **Consistency** — a solver (z3) proves the lifted contract is internally
  satisfiable. A self-contradictory spec is refused without running anything.
- **Witness** — the code is actually run, the run is content-addressed, and
  `verify` recomputes it. A witness that does not reproduce its pinned CID is
  refused.

You write none of this. The lifter reads what is already in the code.

## 1. Produce — vendor a whole library, no shim

The headline demo lifts **every module-level function** of an installed numpy into
one lean `.proof`, with zero changes to numpy and no hand-written shim:

```sh
examples/numpy-vendor/run.sh        # provisions a venv on first run
```

Real output (numpy 2.4.6):

```
numpy.proof:  13M, 2909 sugar members
witness: passed blake3-512:049e169f... -> .sugar/witnesses/<cid>.witness
oracle resolved via package; rust recomputed the CID and it matched
pass
```

The verb underneath is **`sugar mint`**: it dispatches the configured lift plugins
and writes the signed `.proof`. (`sugar lift` is the lower-level step that stops at
the ProofIR terms; `mint` is what envelopes them.) The `.proof` carries *identity* —
CIDs and loci — not bodies, which is how 2909 functions fit in 13M; bodies are
resolved and recomputed on demand.

## 2. Verify — two independent ways

```sh
examples/numpy-showcase/run.sh
```

On `numpy.rot90`, `sugar prove` discharges the good test's consistency obligation
via **z3** (`z3 via smt-lib-v2.6: discharged, authoritative=true`) and **refuses the
degenerate twin both ways**: the contradiction — one `rot90` element asserted two
different values — is z3-UNSAT, and the witness re-run via the package body fails it
(`1/2 outcomes failed: test_rot90_contradiction`). The demo's own self-check confirms
all four (consistency discharges, consistency refuses, witness refuses, witness names
the failing test) and prints `PASS`.

> Reproduced locally 2026-06-28 on a full `cargo build`: `discharged: 1, violations: 2, PASS`.

## 3. Inherit — across the seam, any language to any language

Correctness is inheritable. A consumer composes against a vendor's `.proof` and is
caught the instant it contradicts it:

- a consumer asserting `np.add(2,3) == 5` → **PROVEN** (it inherits numpy's contract)
- a consumer asserting `np.add(2,3) == 6` → **REFUSED** (`and(==5, ==6)` is UNSAT)

```
# verified end to end:
implementations/python/sugar-lift-py-tests/tests/test_inheritance_e2e.py
#   parametrized: consumer-agrees-PROVEN, consumer-contradicts-REFUSED
```

Contracts key to the **callsite**, not the test, and the verifier conjoins
same-named contracts across `.proof` files before the SAT check. That is the
membrane holding at the seam between packages — and, because a `.proof` is content
not language, between languages.

## 4. The honest half — what was never proven

The point is not the green rows. Honest software is mostly consistent, so the
satisfied obligations are the *expected* result, not the product. The product is
the **enumerated list of what is undecided** — the behavior no one ever swore to.

Upgrade a dependency and run **`sugar diff`** to get the *"here be the new dragons"*
report: the diff of the **behavior**, intersected with exactly what your code leans
on — your coupling ∩ their change, the exact welds that broke, before prod. The
empty set is an artifact too; it gets a hash.

Read the full argument in the README:
[*"The part that should keep you up at night"*](../README.md#the-part-that-should-keep-you-up-at-night).

## What runs today (honest scope)

- **Rust** (`cargo sugar`) and **Python** (`sugar-check` pre-commit hook) drive the
  behavioral-diff wedge today.
- The **npm / JS** wedge is in progress — what is missing is the lifter, not the
  thesis.
- Coverage is empirical and uneven across languages. The runnable
  [examples/](../examples/) are the honest picture of what works end to end today;
  if it is not a passing example, treat it as in progress.

## Where to go next

| Goal | Read |
|---|---|
| Run the headline demo | [examples/numpy-vendor/](../examples/numpy-vendor/) |
| See everything that runs today | [examples/](../examples/) |
| Learn the vocabulary | [SHARED-LANGUAGE.md](../SHARED-LANGUAGE.md) |
| Why a contract beats a test | [README](../README.md#why-a-contract-beats-a-test) |
| Build Sugar from source | [contributing/build.md](contributing/build.md) |
| The paper ladder | [papers/README.md](papers/README.md) |

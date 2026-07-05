<!--
  How-to: publish a .proof, and inherit one. House rule: receipts, not assertions.
  Every step is backed by a runnable artifact (examples/numpy-vendor, the
  inheritance e2e test). Verb names checked against the 21-verb dispatch table.
-->
# Publish a `.proof`, and inherit one

Two flows: a **vendor** ships a `.proof` for a library; a **consumer**, in any
language, composes against it and inherits its correctness — and is caught the moment
it contradicts it. Both are grounded in runnable demos under `examples/`.

## As a vendor — ship a `.proof`

A `.proof` carries **identity, not bodies**: CIDs, loci, and signatures. Source and
witness bodies are resolved and recompute-verified on demand, which is how a
2909-function numpy proof stays 13M instead of embedding all of numpy.

1. **Mint the proof.** From the project, `sugar mint` dispatches the configured lift
   plugins and writes a signed `.proof` of every lifted behavior — no code changes,
   no shim.
2. **Write the witness package.** The audit material (the actual run, content-addressed)
   is deployed *separately* as `<cid>.witness`, not embedded in the `.proof`.
3. **Publish** the `.proof` plus its `<cid>.witness`.

The headline demo does exactly this end to end:

```sh
examples/numpy-vendor/run.sh        # provisions a venv on first run
```

```
numpy.proof:  13M, 2909 sugar members
witness: passed blake3-512:049e169f... -> .sugar/witnesses/<cid>.witness
oracle resolved via package; rust recomputed the CID and it matched
pass
```

The consumer's `verify` will **recompute** all of it — the producing kit is untrusted;
the Rust CLI BLAKE3's the witness body itself and checks the signature. You are not
asking anyone to trust your test runner.

## As a consumer — inherit a `.proof`

Correctness is inheritable. Stage an upstream `.proof`, assert against the same
behavior, and `prove`:

1. **Stage** the vendor `.proof` in `.sugar/imports/`.
2. **Assert** something about the same call in your own code/tests.
3. **`sugar prove`.** The verifier conjoins same-named contracts across `.proof`
   files before the SAT check — so you inherit the vendor's contract, and a
   contradiction is refused.

```
consumer asserting  np.add(2,3) == 5  ->  PROVEN   (inherits numpy's contract)
consumer asserting  np.add(2,3) == 6  ->  REFUSED  (and(==5, ==6) is UNSAT)
```

Verified end to end:

```
examples/numpy-consumer-demo/run.sh
  runnable: four-verdict membrane receipt plus vendor proof v1 -> v2 update delta

implementations/rust/sugar-cli/tests/cross_proof_imported_implications.rs
  e2e: imported precondition, imported universe, and vendor-update callsite delta
```

Contracts key to the **callsite** (e.g. `numpy.add#euf#…::assertion`), not to the
test — which is why the consumer's claim and the vendor's claim meet at the same
node. And because a `.proof` is content, not language, the consumer can be in a
different language than the vendor: the membrane holds at the seam.

## Honest scope

These flows run today through the numpy demos. Coverage is empirical and uneven
across languages — the runnable [examples/](../../examples/) are the honest picture of
what works end to end. Trust a passing example; treat anything else as in progress.

---

See also: [getting-started](../getting-started.md) · [concepts](../explanation/concepts.md)
· the CID/witness model in the [README](../../README.md#the-oracle-trio-a-proof-carries-identity-not-bodies).

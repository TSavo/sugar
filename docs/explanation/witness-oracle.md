<!--
  The witness oracle — how a witnessed claim is recomputed and verified. The BACK of the
  pipeline, counterpart to rendezvous (the front). Grounded in
  implementations/rust/sugar-cli/src/witness_verify.rs: verification lives in the Rust CLI;
  the kit oracle RESOLVES, the CLI RECOMPUTES; trust the recomputation, never the resolver.
-->
# The witness oracle — capture, resolve, recompute

[Rendezvous](rendezvous.md) is the front of the pipeline: it selects which kits handle a
project. The witness oracle is the back: it is how a claim backed by a *run* — a test that
executed, a value that was produced — gets re-checked by a stranger without trusting whoever
produced it. Its one law: **trust the recomputation, never the resolver.**

A `.proof` is discharged two independent ways that must agree (see [concepts](concepts.md)):
**consistency** (a solver proves the lifted contract satisfiable) and **witness** (the run is
actually reproduced). This page is the witness half.

## What a witness is

A **witness** is arbitrary *signed content* — a test run, a CI log, a captured value, a poem —
named by a `witness_cid`, which is the **BLAKE3-512 of its body bytes**. The `.proof` carries
the CID and a signature, never the body (that is the [oracle-trio](../README.md) rule: identity,
not bodies). The body is fetched on demand and recompute-verified.

## The lifecycle

```
capture  ──►  resolve  ──►  recompute  ──►  verdict
(kit)         (kit, RPC,     (Rust CLI,      verified /
              untrusted)     BLAKE3 itself)  refused / broken-oracle
```

1. **Capture.** A kit runs the thing (executes the test, captures the output), takes the
   BLAKE3-512 of the body, and mints a `witness-memento`: the pinned `witness_cid`, a signer,
   and a signature. The body ships separately, in a witness package (`<cid>.witness`).
2. **Resolve.** When verification needs the body, the Rust CLI calls
   `sugar.plugin.resolve_witness` on the kit oracle (python/java) to fetch the bytes — from the
   witness package, or by re-running. **The kit oracle is UNTRUSTED.** It is a resolver, not an
   authority; its job is only to hand back bytes.
3. **Recompute.** The Rust CLI takes the BLAKE3-512 of the bytes the oracle returned **itself**
   and compares it to the pinned `witness_cid`. This is the load-bearing step. The CLI never
   takes the oracle's word that the body is right; it re-derives the name from the bytes.
4. **Verdict** (`WitnessVerifyResult.status`):
   - **`verified`** — signature checked and the recomputed CID matches.
   - **`refused`** — a check failed (e.g. envelope integrity: the body's own `witness_cid`
     disagrees with the header's `witnessCid`).
   - **`broken-oracle`** — the oracle returned a body that does **not** recompute to the pinned
     CID. The resolver lied or is buggy; the CLI refuses loudly.

## The two checks the CLI performs

Both run in the Rust substrate, on substrate primitives, never on the oracle's say-so:

- **Signature** — verified with the substrate's own `ed25519_verify_string`, not the oracle's
  word that it signed anything.
- **Content-address recompute** — `blake3_512_of(body) == witness_cid`. The body and the name
  are checked against each other, locally.

The `checks` field on each result records what passed, e.g. `["signature", "content-address:recompute"]`.

## broken-oracle vs drift — the distinction that matters

Two different failures look superficially alike, and Sugar separates them:

- **broken-oracle** — the oracle hands back a body whose bytes do not BLAKE3 to the pinned CID.
  That is a *lying or broken resolver*. It is never tolerated.
- **drift** — an honest *re-run* legitimately produces a different result than the one pinned.
  That is the world moving: the behavior changed. It is a real, reportable signal, not a bug in
  the oracle.

Conflating the two is how a verifier quietly starts trusting its resolver. Keeping them apart is
why the producing kit can be wholly untrusted: a `broken-oracle` is caught by recomputation, and
`drift` is caught by the CID simply no longer matching.

## Why this shape

Because the CLI recomputes every witness CID from bytes, the kit that *produced* the proof never
has to be trusted, the `.proof` can stay lean (it carries CIDs, the bodies live in the witness
package), and a stranger can re-verify the whole thing from first principles. That is the
[first principle](../README.md) made operational on the witness side: *verification is
recomputation; trust nothing, not even the kit that made the proof.*

---

Authoritative source: `implementations/rust/sugar-cli/src/witness_verify.rs`
(`verify_witnesses`, `WitnessVerifyResult`). See also: [rendezvous](rendezvous.md) (the front
of the pipeline) · [concepts](concepts.md) · [reading a refusal](../how-to/reading-a-refusal.md).

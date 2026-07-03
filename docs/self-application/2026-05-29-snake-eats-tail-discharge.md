# 2026-05-29 — snake eats tail, with discharge

The [2026-05-28 entry](2026-05-28-snake-eats-tail.md) lifted `sugar-cli`'s
own assertions into a signed contract catalog and named its honest gap:

> `verify`'s discharge model expects callsites at vendor boundaries. sugar-cli
> has no vendor boundaries. It IS the vendor for its own behavior. [...] there
> is no separate consumer whose obligations get checked against them.

Today that gap is closed. The CLI now bridges its own call sites into contracts
and the substrate discharges the obligations: some by a real solver, some by a
principled refusal, none by a silent pass.

## What changed

Four lift surfaces are conjoined by one `sugar mint`, not two:

```
rust-bind          native library-binding contracts
rust-contracts     #[test] asserts -> inv witnessed facts
rust-fn-contracts  every production fn -> body-bearing formals + pre + post
rust-implications  every intra-body call -> a kind:bridge memento
```

`rust-fn-contracts` is what makes the discharge substantive. A test witnesses
one fact (`inv`); a general call site cannot discharge against it. A function's
body-derived `pre`/`post` is a contract a caller *can* discharge against. The
implication lifter then emits a bridge per call expression, matched to a
contract by callee name, preferring the body-bearing contract when a name has
both.

The vendor boundary the 2026-05-28 entry said did not exist now does: a
cross-crate call (`libsugar::cid_of_value`, `execute_path`, ...) is exactly a
vendor boundary. `mint` harvests the contracts published by the dependency
proofs sitting in `.sugar/imports/` (here: `libsugar.proof` and the rust
stdlib sugar shim) and forwards them so the implication lifter bridges into
them. Same model as a TypeScript consumer bridging into a shim; the dependency
is just another crate.

## Bridge pinning: one shape, no unenforced path

Every bridge now carries a forward pin so the verifier enforces
`ConsequentBundlePinned` (the shim-poisoning defence): the contract that
discharges a bridge must come from the bundle the bridge names, not a same-named
impostor from another bundle.

- A cross-bundle bridge (into a dependency proof) carries
  `targetProofCid = <that proof's bundle CID>`. The verifier requires the
  target contract to be a member of that bundle.
- An intra-bundle bridge carries no `targetProofCid`. It is **self-pinned**: the
  target must be a co-member of the bridge's own bundle. It cannot name its own
  not-yet-computed bundle CID, so absence *is* the self-pin, and it is enforced,
  not skipped.

There is no third, unenforced case. The old "no `targetProofCid`, warn and
continue" back-compat path is gone, and so is the second bridge mint variant
(`mint_bridge_v14`) that nothing in production used. One bridge shape.

Same-name collisions across crates are resolved at mint time by precedence: an
intra-crate contract wins over a same-named dependency contract, so a bare
callee `foo` in the CLI resolves to the CLI's `foo`, never a dependency's.

## The empirical

```
$ sugar mint --project implementations/rust/sugar-cli   # 4 surfaces, 2 deps
deps: 871 dependency contract(s) forwarded for cross-crate bridging,
      6 dropped (name collides with an intra-crate contract; intra-crate wins)
  catalog CID: blake3-512:7b31044eeb1d7d1d...0505ea7
  proof bytes: 1454026

$ sugar prove implementations/rust/sugar-cli --json      # z3 + cvc5 + vampire
```

| metric | libsugar only | + stdlib shim, pinned |
|--------|------------------|------------------------|
| callsites | 1087 | **1305** |
| discharged | 749 | **965** |
| &nbsp;&nbsp;— by real solver (z3+cvc5) | 217 | **211** |
| &nbsp;&nbsp;— vacuous (publisher post-only) | 499 | 723 |
| &nbsp;&nbsp;— inv-tier (memento-is-verification) | 33 | 31 |
| not discharged | 338 | **340** |
| &nbsp;&nbsp;— principled refusal (can't reduce) | 252 | 252 |
| &nbsp;&nbsp;— solver-undecidable | 63 | 63 |
| &nbsp;&nbsp;— wp reduction failure | 23 | 25 |
| back-compat (unenforced) warnings | every bridge | **0** |
| pin-enforcement failures | n/a | **0** |

211 obligations discharged by z3 or cvc5. 252 refused: the callee has a
body-derived contract but the harvested obligation could not be reduced, so the
verifier returns `undecidable` rather than vacuous-passing. That refusal arm is
the point — under *supra omnia, rectum*, "I cannot prove this" is a first-class
answer, not a failure to paper over.

Spot-check of the cross-crate vendor boundary: the calls into libsugar's
substantive contracts (`cid_of_value`, `jcs_bytes_of_value`, `json_jcs`,
`address`, `member_envelope_canonical`) all resolved to libsugar's pinned
contracts and returned `undecidable` — the bridge reached the right contract and
the verifier refused the obligation it could not discharge. Zero rows resolved
to the wrong bundle.

## The honest caveats

1. **The stdlib shim buys coverage, not solver work.** Its 24 wrappers
   (`to_string`, `len`, `clone`, `is_empty`, ...) publish *total*, post-only
   contracts, so bridging into them flips a lift-gap into a vacuous-discharged
   row, not a solver obligation. Solver count held steady (211 vs 217) while
   vacuous rose (499 -> 723). An earlier draft fabricated a precondition on
   `slice::get` (which is total, it never panics); that was removed. The shim's
   `assert!`-based partials (`unwrap`, `expect`) do **not** lift a real `pre`
   through the sugar surface (it emits post-only by design), so they remain
   nominal until a shim mint adds `rust-fn-contracts`.

2. **Bare-name matching is the open frontier.** A callee is matched to a
   contract by simple name. The CLI's `unwrap` and an `Option::unwrap` contract
   cannot be told apart without the receiver type. The honest move is to NOT
   bridge an ambiguous name (the 6 dropped at mint, the shim's deliberately
   disambiguated `option_unwrap`/`result_unwrap` names that therefore do not
   bridge). Qualified-callee resolution is the next lever.

3. **Four benign load-time notices remain.** `parse_toml_string_array`,
   `is_blake3_512_cid`, `json_to_cvalue`, `string_field` exist in both the CLI
   and libsugar. The pool logs the name coexistence. It is harmless: bridges
   resolve by `targetContractCid` + `targetProofCid`, not by name, and the
   pin-enforcement failure count is 0. Silencing the cross-bundle name notice is
   a loader-side cleanup, not a correctness fix.

4. **Two dependency-proof mechanisms now coexist.** This mint-time harvest
   (forwarding dependency contract *names* so bridges can be built) is
   complementary to the committed verify-time `resolve_dependency_proofs` kit
   RPC (#1619, carrying dependency proof *bytes* into the pool). The rust kit
   has not implemented that RPC yet, which is why dependency proofs are placed
   in `.sugar/imports/` for `load_all_proofs` to discover. The two should be
   reconciled so one path feeds the other.

## What this is

The 2026-05-28 entry proved the substrate could lift the CLI's assertions and
sign them. This entry proves it can take the next step: build the bridges those
assertions imply, pin each to the exact bundle allowed to discharge it, and run
the solver fleet over the result — across the crate boundary into a real
dependency — returning a discharge, a refusal, or a vacuous pass, each labelled
honestly. The snake reached its tail on 2026-05-28. Today it closed its jaw on
something it had to actually chew.

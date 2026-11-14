# 2026-05-28 — snake eats tail

The Sugar CLI lifted its own contracts.

## What happened

`sugar-cli` is the program. Its `#[test]` functions assert specific things
about its own behavior — that `cmd_mint`'s attestation routine produces a
signed payload, that `cmd_materialize_integration` discharges a refused
boundary, that `project_config::read_project_config` returns the expected
shape for a given input. Each one of those assertions is a contract the
program is willing to make about itself.

Today the substrate accepted them.

```
$ cd implementations/rust/sugar-cli
$ ../target/debug/sugar mint --project .
config: 2 plugin(s) declared: rust-bind, rust-contracts
dispatch: surface=`rust-bind` plugin=`rust-bind-lift` command=["../target/debug/sugar-walk-rpc", "--rpc"]
sugar-walk-rpc listening on stdio (JSON-RPC 2.0, line-delimited)
ok: plugin `sugar-walk-rpc` ready
dispatch: surface=`rust-contracts` plugin=`rust-contracts-lift` command=["../target/debug/sugar-lift", "--rpc"]
ok: plugin `sugar-lift` ready

  catalog CID:        blake3-512:02aaf3404b4565df49ccc6a443a80cadb3eae4f0f4bd4588e4fcaab587064d5809a62c672d2e0171b8e7a0b5caf699aa13eeacd92073320966dfafb629137a0c
  contractSetCid:     blake3-512:674833821f2ca04f321602a79de7e7075bd046bdaeee6bc893b28d46c391b7e7b7416ac4bf5d025ef492ee8e643ee1ca53b5f7b45f8b686654187e950f6e4d96
  proof bytes:        183735
  .proof file:        ./blake3-512:02aaf340...proof
attest: wrote /Users/tsavo/sugar/.sugar/self-contracts-attestations/rust-bind.json
```

That command resolved `.sugar/config.toml` at the CLI crate root, walked
the two declared lift surfaces — `rust-bind` (the bind-IR shape) and
`rust-contracts` (the contracts adapter) — and produced an `ir-document`
proof envelope. 107 members, 183 KB, written next to the CLI crate.

Then I asked the contracts lifter directly:

```
$ ../target/debug/sugar-lift --workspace .
blake3-512:8e3b0dd70773519d15daf70c8f5acfeed2676dfa9d872a68adca8bfb2963761e810e833f837d9cdfa168b071641de283463f06caa39456cbf17f3d3a4803202f
```

One CID. Inside the envelope at that CID: **105 `kind:contract` mementos**,
each ed25519-signed by the substrate's lift-time key, each carrying the
file-and-line of the assertion it was lifted from. The shapes:

| count | kind        |
|-------|-------------|
| 105   | `contract`  |
| 107   | `atomic`    |
| 110   | `const`     |
| 110   | `primitive` |
| 114   | `var`       |
| 215   | `ctor`      |
| 2     | `and`       |

105 contract claims, 101 distinct `file:line:column` targets, spanning both
production sources and tests. Sample claim names from the lifted catalog:

```
and_then@tests/cmd_materialize_integration.rs:720:8
and_then@tests/cmd_materialize_integration.rs:724:8
and_then@tests/cmd_materialize_integration.rs:728:8
as_deref@src/project_config.rs:395:19
as_deref@src/project_config.rs:402:19
as_deref@src/project_config.rs:414:19
as_deref@src/project_config.rs:421:12
build_signed_attestation@src/cmd_mint.rs:2214:16
extract_cset@tests/mint_kit_integration.rs:660:8
```

Each name is a `function@file:line:col` of a real call site in the CLI. The
contracts are the invariants the CLI's authors already wrote — `assert_eq!`,
`assert_ne!`, `assert!`, and panic / early-return shapes that the rust-tests
adapter walks via the syn AST. The substrate just signed them.

## The honest gap

`sugar verify` (since removed; `sugar prove` is the door) from the same dir reported

```
verify: lifting contract claims from `.`
verify: no contract claims found for `.`; nothing to verify
```

That is correct. `verify`'s discharge model expects callsites at vendor
boundaries — bridges from user code into a shim's published contracts.
sugar-cli has no vendor boundaries. It IS the vendor for its own
behavior. The 105 contracts are mementos of what the CLI says about itself;
there is no separate consumer whose obligations get checked against them.

The discharge happens earlier, every time `cargo test` runs the test
suite. The substrate's contribution is to take those passing asserts and
mint them into a content-addressed, signed catalog whose CIDs are stable
across the host: the same CLI source produces the same contract CIDs no
matter who builds it. That is the closure.

## What we built to make it possible

The CLI crate gained three files:

```
implementations/rust/sugar-cli/.sugar/config.toml
implementations/rust/sugar-cli/.sugar/lift/rust-bind/manifest.toml
implementations/rust/sugar-cli/.sugar/lift/rust-contracts/manifest.toml
```

That config declares two PEP 1.7.0 lift plugins; the manifests point at the
existing `sugar-walk-rpc` and `sugar-lift` binaries inside this same
workspace. No new code; no new lifter. The plumbing the CLI already
shipped was sufficient — once the project root knew which surfaces to ask
for, the rest was a function of `cd`.

The catalog CID the snake left behind:

```
blake3-512:8e3b0dd70773519d15daf70c8f5acfeed2676dfa9d872a68adca8bfb2963761e810e833f837d9cdfa168b071641de283463f06caa39456cbf17f3d3a4803202f
```

## What this is not

This is not a proof that the CLI is bug-free. It is a proof that the
substrate the CLI implements can be applied to the CLI itself, walk its
assertions, lift them to contracts, sign them, and hand back a CID. The
correctness of the lifted contracts is exactly the correctness of the
assertions the authors wrote. The substrate's job was to make those
assertions content-addressed.

That step had not been taken until today.

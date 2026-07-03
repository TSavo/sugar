# Kit config, lift manifests, and self-application: the runbook

Single source of truth so nobody re-derives this from scratch. If you are an agent
told to "mint / prove / make sugar prove itself," read this first; it is the
20 minutes you do not have to spend rediscovering.

All paths below are repo-root-relative. Repo root = `/Users/tsavo/sugar`.
Rust workspace root = `implementations/rust`. The CLI binary after a build is
`implementations/rust/target/debug/sugar`; the walk lifter binary is
`implementations/rust/target/debug/sugar-walk-rpc`.

---

## 1. A kit is a directory with a `.sugar/`

A "kit" / "project" is any dir containing `.sugar/config.toml`. Examples:
`implementations/rust/sugar-cli`, `implementations/rust/libsugar`,
`examples/sugar-shim-rust-std`.

### `.sugar/config.toml`

```toml
[[plugins]]
name    = "rust-sugar"          # display name
surface = "rust-bind"           # the authoring surface this plugin lifts
layer   = "library-bindings"    # optional

[[plugins]]
name    = "rust-contracts"
surface = "rust-contracts"
emit    = "ir-document"         # `emit = "ir-document"` routes to the IR-document path

[[plugins]]
name    = "rust-implications"
surface = "rust-implications"

[[plugins]]
name    = "rust-fn-contracts"
surface = "rust-fn-contracts"
emit    = "ir-document"

[platform_profile]
language = "rust"
family   = "concept:family:sugar"   # or concept:family:rust-std for the shim
library  = "sugar-cli"              # the SEMANTIC library tag (std for the rust-std shim).
                                       # NOT the cargo crate name. Contracts get tagged with this.
version  = "0.4.0"
```

### The four Rust surfaces (what each produces)

| surface           | produces |
|-------------------|----------|
| `rust-bind`       | native library-binding contracts. POST-ONLY by design (no `pre`). |
| `rust-contracts`  | `#[test]` asserts -> `inv` witnessed facts |
| `rust-fn-contracts` | every production `fn` -> body-bearing contract: `formals` + `pre` (entry asserts/guards, via `lift_function_precondition`) + `post` (body-derived, via `lift_function_postcondition`). This is the surface that gives a partial wrapper (`unwrap`/`expect`) a REAL dischargeable `pre`. If a kit lacks this surface, its `assert!`-derived preconditions are NOT published. |
| `rust-implications` | every intra-body call -> a `kind:bridge` memento pinning the call site to the callee's contract |

`sugar mint --project <dir>` runs ALL configured surfaces and conjoins them
into ONE `.proof`.

---

## 2. Lift manifests and THE PATH FOOTGUN

Each surface needs a manifest at `.sugar/lift/<surface-name>/manifest.toml`:

```toml
name        = "rust-fn-contracts-lift"
command     = ["../target/debug/sugar-walk-rpc", "--rpc"]
working_dir = "."
method      = "sugar.plugin.lift_implications"   # only for the implications surface
phase       = "consumer"                             # only for the implications surface
```

**THE FOOTGUN (this is the 20-minute tax):** `command` is resolved relative to
`working_dir`, and `working_dir = "."` means the PROJECT directory. So the
relative path to the shared walk binary DEPENDS ON HOW DEEP THE PROJECT IS:

- project at `implementations/rust/<crate>/` -> `../target/debug/sugar-walk-rpc`
  (one `..` lands in `implementations/rust/`, where `target/` lives).
- project at `examples/<crate>/` -> `../../implementations/rust/target/debug/sugar-walk-rpc`
  (two `..` to repo root, then down into the rust target).

If you copy a manifest from `implementations/rust/libsugar` into an
`examples/` kit verbatim, the lifter binary "is not found" and the surface
silently produces an EMPTY-SET attestation (no `.proof`, the surface looks like
it ran but emitted nothing). Symptom in the logs:
`warn: lifter binary "../target/debug/sugar-walk-rpc" not found: producing empty-set attestation`.
Fix: match the `..` count to the project depth.

Sanity check before minting a new kit: from the project dir,
`ls $(dirname <command-path>)` must show the binary.

---

## 3. Where mint writes, where verify/prove read (caveat #4)

- `sugar mint --project <dir> --out <outdir>` writes `<outdir>/<filename_cid>.proof`.
  `--out` DEFAULTS TO THE CURRENT DIRECTORY. Always pass `--out` explicitly to a
  scratch dir so you can find the result.
- `sugar prove <project>` scans `<project>` for `.proof` files; `--with <dir>`
  adds more. `sugar verify` and `prove` load the dependency pool via
  `load_all_proofs`, which reads `<project>/.sugar/imports/*.proof`.
- **Two dependency-proof mechanisms coexist and are NOT reconciled (caveat #4):**
  (a) MINT-time harvest reads `.sugar/imports/*.proof` to forward dependency
  contract NAMES so the implication lifter can build bridges. (b) VERIFY-time
  discharge needs the dependency contracts in its pool too. A kit that publishes
  its catalog as an embedded artifact (see the shim below) is resolved by that
  artifact at verify time, which can be STALE relative to a freshly-minted
  imports copy. If a contract you expect (e.g. a partial wrapper's `pre`) is not
  discharging, check that the SAME proof is present in BOTH the mint imports and
  the verify pool.

### Cross-crate dependency setup (the cli self-application)

To make sugar-cli bridge into libsugar + the rust-std shim, both dep
proofs must be in `implementations/rust/sugar-cli/.sugar/imports/`:

```
mint libsugar         --out /tmp/dep-libsugar
mint sugar-shim-rust-std --out /tmp/dep-shim
cp /tmp/dep-*/blake3-512_*.proof implementations/rust/sugar-cli/.sugar/imports/
```

(Use `scripts/self-apply.sh`, which does exactly this. Do not hand-run it.)

---

## 4. The rust-std shim publishes an EMBEDDED catalog

`examples/sugar-shim-rust-std/src/lib.rs` embeds its own published proof:

```rust
pub const SUGAR_PROOF_BYTES: &[u8] = include_bytes!(
    "../blake3-512:<CID>.proof"
);
```

`verify` resolves the shim's contracts from THIS committed artifact (kit owns its
own .proof resolution). To regenerate it (e.g. after adding `rust-fn-contracts`
so partials carry real pres):

1. `sugar mint --project examples/sugar-shim-rust-std --out /tmp/shimregen`
2. Replace `examples/sugar-shim-rust-std/blake3-512:<OLD-CID>.proof` with the
   freshly minted `.proof`.
3. Update the `include_bytes!` path in `src/lib.rs` to the NEW CID filename.
4. `rg <OLD-CID-prefix>` across the repo to find any other pin and update it.
5. `sugar dump <new.proof>` and confirm the expected contracts/pres are present.

The CID changes, so this is a checked-in-artifact change: anything pinning the
old CID breaks. It is an architect-visible decision, not a silent edit.

---

## 5. Knobs

- `RUST_LOG=info` -> the loud pipeline summaries: per-surface dispatch,
  `function_contract_lift: N fn-contracts (M body-discharge-eligible, K ineligible)`,
  `lift_implications: complete -> B bridges, G lift-gaps [breakdown]`, and the
  WARN that fires when the majority of a crate's contracts are ineligible.
- `SUGAR_RESOLVE_ORACLE=rust-analyzer` -> enable the Tier 2b receiver-type
  oracle. Off/absent -> the lifter refuses method-call resolution and falls back
  to Tier 1/2a (CI-safe). The oracle cold-indexes the workspace (~minutes) unless
  the resident daemon (sugar-linkerd) is up with a warm/cached index.
- Output: NEVER pipe long mint/prove output through `head`/`tail`/`grep` that
  hides it; write to a file (`2>logfile`, not a pipe, to avoid buffering) and
  grep the file.

---

## 6. One-command self-application

`scripts/self-apply.sh` mints the deps, places them in the cli imports, mints the
cli with the oracle + loud logging, and proves, with the three gates checked
(dep-contracts forwarded > 0; oracle `resolved N/M`; the discharge scoreboard).
Run that instead of reconstructing the flow. Read its top comment for the gates.

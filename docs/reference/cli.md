<!--
  CLI reference. House rule: receipts, not assertions.
  This page is grounded against the `Cmd` dispatch table in
  implementations/rust/sugar-cli/src/main.rs (the 21 match arms ARE the surface).
  `sugar --help` and `sugar <cmd> --help` are the live authority; regenerate this
  page from them, never from prose. Do not list a verb that isn't dispatched.
-->
# CLI reference: `sugar`

The canonical CLI is the Rust `sugar` binary (`implementations/rust/sugar-cli`).
**`sugar --help` is the authoritative list**, and `sugar <cmd> --help` gives a
command's full flags; the surface moves as protocol work lands. This page documents
the **21 subcommands the binary actually dispatches** (the `Cmd` match arms in
`main.rs`) — no more, no less. The CLI is routing only: each verb wraps a library.

## Produce a `.proof`

| Verb | What it does |
|---|---|
| `mint` | Dispatch the lift-plugin protocol: spawn the configured plugin, write its `.proof`. **This is the producing verb** — every example uses it. |
| `lift` | Dispatch the configured lift surface and write its ProofIR term JSON (no `.proof` envelope; use `mint` for that). `--report`/`--visual` print the source-audit walk. |

## Check and verify

| Verb | What it does |
|---|---|
| `prove` | Run the six-stage verifier: load proofs, enumerate callsites, solve obligations, report. |
| `verify` | Verify a kit end to end: lift its contract claims, discharge each via the solver-dispatch table, mint a signed witness citing the discharging solver, emit a per-claim receipt. **The gate verb** (#1405); distinct from `prove`. |
| `diff` | Behavior diff between two minted proof sets: which contracts changed CID (behavior moved), were added, or removed. The CID is the name-stripped behavior identity, so a rename reads `unchanged`. Exits nonzero when behavior moved or surface dropped. |

## Compose and inherit

| Verb | What it does |
|---|---|
| `implicate` (alias `imp`) | Mint an implication memento (antecedent CID → consequent CID) via z3. |
| `compose` | JSON-RPC subprocess transport for the canonical compose primitive (contract-composition-protocol §6.3). Reads requests on stdin, writes responses on stdout. |

## Inspect

| Verb | What it does |
|---|---|
| `dump` | Pretty-print a `.proof` envelope: members, bodies, signatures. |
| `hash` | Compute the BLAKE3-512 self-identifying CID of a file (or stdin). |

## Bind to source / transform

| Verb | What it does |
|---|---|
| `recognize` | Scan source for shapes that match published sugar binding templates; emit tags. The reverse direction of `materialize`. |
| `materialize` | Materialize source-oracle bodies by resolving real source by reference. |
| `bind` | Bind concept contracts to source code (the eight-verb pipeline: lift, cluster, name, scope, identify, realize, witness). Flags: `--rewrite={annotate,canonical,invisible} --mode={witness,emitter,monitor,gate} --target-language=<lang>`. |
| `emit` | Emit target/framework test artifacts from neutral contract predicates. |
| `derive` | Derive a concrete output from a lifted universe BV expression via z3 model extraction (`get-value`) — derived, not executed. Flagship: `abs(Integer.MIN_VALUE) = -2147483648`, from the lifted `Math.abs` body. |

## Project and lifecycle

| Verb | What it does |
|---|---|
| `init` | Initialize a project: `sugar.toml`, `.sugar/`, a sample invariant, a GitHub Action. |
| `doctor` | Validate a kit's config/manifest wiring before a run; catches a missing binary before it silently produces an empty-set attestation. Exit 0 = pass (warnings allowed), 2 = hard failure. |
| `package` | Inspect package artifacts and supply-chain receipt inputs. |
| `release-gate` | Run the v1 release health gate and emit a release evidence receipt. |
| `self-check` | Run the deterministic self-application scoreboard (Sugar over Sugar). Surfaces the protocol catalog CID (`catalogCid:`). |
| `version` | Print CLI version. |

## Exit codes

From `main.rs`:

| Code | Meaning |
|---|---|
| `0` | OK |
| `1` | verification failure (a proof does not hold) |
| `2` | user error (bad args, missing file, invalid config) |
| `3` | solver failure (z3 unavailable, timeout, unsupported theory) |

## Global flags and logging

- `--json` / `--quiet` — per-subcommand output flags (a bare `sugar mint`/`prove` is silent).
- `RUST_LOG=info|debug|trace` — pipeline narrative → per-item decisions → RPC payloads.
- `SUGAR_LOG_FILE=<path>` — write structured logs to a file instead of stderr.

## Plugin flags (lift-plugin protocol)

Subcommands that participate in the plugin registry accept:

- `--plugin <kind>:<source>` (canonical) · `--sugar <source>` · `--lifter <source>` · `--loss-fn <source>` (aliases)
- `--strict-plugins` — promote any plugin load failure to a refuse.
- `--plugin-registry-out <path>` — write the sealed registry memento after the run.

---

*Not a `sugar` subcommand:* the IR-compiler backends (`sugar-ir-smt-lib`,
`sugar-ir-coq`, `sugar-ir-lean`, `sugar-ir-maude`), the RPC services
(`sugar-walk-rpc`, `contracts_rpc`, `witness_rpc`, `sugar-linkerd`, …), `cargo
sugar` / `cargo sugar-lift`, and the `bcargo` build wrapper are separate binaries
— see the repository's `[[bin]]` targets, not `sugar --help`.

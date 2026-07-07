# vscode-sugar — the inline wall (slice A + B)

Part of **#3774** and **#3767 slice 2**. This is the LSP path: **the line flips
red↔green live, through the production pipeline.** Open a project, put a source
line into a state the prover cannot discharge, and a red diagnostic appears from
the **production** pipeline — `sugar-linkerd` lifting the file and calling the
linker, the same construction the proofchain uses. Correct the line and the
squiggle clears. Both directions, live.

Slice B adds the **semantic current**: when a solver is available the daemon
calls `link_with_solvers` instead of pure `link()`, so an obligation that is
structurally distinct but logically decidable is adjudicated by **z3** — a
truthful implication is DISCHARGED (green), a lie is refuted UNSAT (red), live
in the editor.

There is no shadow verifier in this extension. The editor shows exactly what the
linker says because it asks it, over the daemon's `parseFile` RPC.

## What flips, today, through the production daemon

The daemon adjudicates **bridge obligations**: for every call edge it checks
`post_caller ⊃ pre_callee`. The demo fixtures (`test/fixtures/`) exercise that
directly:

- **`red.rs` (the lie):** a contracted helper `checked_index` declares the
  precondition `#[requires(x > 0)]`. The caller `test_index` calls it but its
  postcondition does not establish that rule, so `link()` cannot discharge the
  obligation and refuses it → a red **`implication-undecidable`** diagnostic,
  anchored at the `checked_index(7)` call site, carrying the linker's reason
  text.
- **`green.rs` (the truth):** the same file with the `#[requires(x > 0)]` line
  removed. No precondition ⇒ no obligation ⇒ the bridge discharges vacuously ⇒
  zero diagnostics. The squiggle clears.

Delete the `#[requires(...)]` line to go green; type it back to go red. That is
the red→green→green→red flip the acceptance bar names, running against the real
`sugar-linkerd`.

## The semantic flip (slice B — z3, when a solver is available)

When z3 is on `PATH` (or a workspace `SolversConfig` declares solvers) the daemon
runs in **semantic** mode. The obligation `post_caller ⊃ pre_callee` is then
handed to z3 for any structurally-distinct pair. The semantic fixtures
(`test/fixtures/*_semantic.rs`) exercise a genuine solver decision over the
shared contract quantity `result`:

- **`green_semantic.rs` (z3 discharges):** caller ensures `result >= 5`, callee
  requires `result >= 1`. `result >= 5 ⊃ result >= 1` is valid — z3 discharges
  it and there is **no diagnostic**. Pure `link()` could only call this
  `implication-undecidable`; z3 turns it green.
- **`red_semantic.rs` (z3 refutes):** weaken the caller's `#[ensures]` to
  `result >= 0`. `result >= 0 ⊃ result >= 1` is **not** valid (counterexample
  `result = 0`): z3 returns sat and the daemon emits a red
  **`implication-unprovable`** at the `callee(x)` call site, reason
  `solver 'z3' returned sat (counterexample found)`.

Edit that one `#[ensures]` line and the line flips green↔red on z3's verdict, not
on structure. Observed round-trip (lift + z3 subprocess + link) is ~0.6–0.7 s per
re-derive on a warm daemon — within a debounced editor cadence; a solver call is
bounded by the `SolverPlan`'s own typed `solver-timeout` terminal (default 10 s),
so a pathological obligation degrades loudly instead of hanging the editor.

### Modes are named, never silent

`projectStatus` reports the daemon's discharge mode in its capabilities:
`solverMode: "semantic"` with `solverSeats: ["z3"]` when a registry is wired, or
`solverMode: "structural"` (with an empty seat list) when none is — the honest
degraded mode. Force structural mode explicitly with `--no-solvers`.

## The on-stage script (VS Code, human demo)

1. Build/resolve the daemon (one door, no cargo):
   ```
   bin/sugarbin --bin sugar-linkerd
   ```
   It prints the binary path. Point the extension at it via the
   `sugar.linkerd.binaryPath` setting (or pre-start the daemon yourself and set
   `sugar.linkerd.socketPath`).
2. Launch the extension (F5 in this folder, or package with `vsce`).
3. Open `test/fixtures/red.rs`. Within the debounce window a **red squiggle**
   lands on `checked_index(7)`; hover shows `implication-undecidable: solver
   could not decide post_caller ⊃ pre_callee …`.
4. Delete the `#[requires(x > 0)]` line. On the next keystroke the squiggle
   **clears** — green, live, before saving.
5. Type the line back. The squiggle **returns**. Green→red, on the most basic of
   examples.

## The receipt (headless, CI)

A full editor E2E is not possible headlessly, so the **LSP-protocol-level test
is the receipt.** `test/e2e.test.js` drives the exact `LinkerdClient` the
extension uses, straight against the production daemon binary, and asserts the
full flip:

```
editors/vscode-sugar/test/run-e2e.sh
```

It resolves the daemon through `bin/sugarbin`, compiles the TypeScript client,
and runs the wire-protocol test in **both modes**: a structural leg
(`--no-solvers`, slice A's `implication-undecidable` flip) and a semantic leg
(default z3, slice B's `implication-unprovable` flip). Expected output ends with:

```
slice A + B receipt: structural red->green->red AND semantic (z3) green->red->green verified through sugar-linkerd
```

If z3 is not resolvable the semantic leg **skips** (the daemon honestly reports
`solverMode: "structural"`) and the structural leg still passes — the degraded
mode is honest. The `rust` kit is used because its lifter runs **in-process**
inside the daemon, so the receipt is hermetic — no external kit binary required.

## Daemon glue landed in this change

Two gaps between the linkerd conformance surface and a real editor session were
closed (verified by the receipt):

1. **Absolute-path diagnostics.** The rust lifter emitted the call-site locus
   with the file *basename*, but `parseFile` filters diagnostics by the exact
   `file` the editor sent (an absolute path). Every absolute-path session
   therefore received **zero** diagnostics. The locus now carries the full path
   the editor sent. (`sugar-linkerd/src/methods.rs`)
2. **Real call-site range.** Call-edge loci carried `line: null`, so a squiggle
   had nowhere to anchor. The lifter now stamps each edge with the 1-based line
   and 0-based column of the calling expression. (`sugar-lift/src/call_edges.rs`,
   `sugar-lift/Cargo.toml` enabling `proc-macro2` `span-locations`)

## What is now wired (slice B) and what still remains

- **Semantic, solver-backed adjudication — LANDED.** The daemon now builds the
  solver registry/plan at startup (from the workspace `SolversConfig`, else a
  default single-z3 registry when z3 is on `PATH`) and calls the linker's
  `link_with_solvers` path, so a structurally-distinct obligation is decided by
  z3. The pure-`link()` structural path remains as the named degraded fallback.
- **LinkedProof consumption (the #3767 slice-2 seam).** The daemon's discharge
  now flows entirely through the linker's own semantic output — the mechanical
  slice-2 piece *at the daemon boundary* is done: the editor consumes the
  linker's constructed verdicts, never a shadow. The remaining slice-2 work is
  verify-side: migrating `resolve_target`'s kind-check onto a `LinkedProof`
  value so `verify` accepts `LinkedProof` only. That is correctly still deferred
  (per #3767 slice 1's note) — removing the kind-check before `verify` consumes
  `LinkedProof` would drop a live soundness check with no constructed
  replacement. It is not on the editor's critical path.
- **The literal-fact vendor-universe flip** (`encodeBase64("abc") == "YWJj"`
  green vs `== "AAAA"` red) additionally needs the vendor proof pool loaded into
  the daemon's `LinkerInputs` and per-call argument binding; the z3 discharge
  machinery it rides on is now in place.
- **Green inlay for discharged facts** (the warrant, hover = CID): still to come.
- **Latency hardening** (incremental re-link, warm pool) and the
  `SourcePartition` gutter classes: **slice C**.
- **Stage-rehearsal harness** (scripted, timed red→green→red on the demo
  corpus): **slice D**.
- **Python demo corpus** (`examples/python-literal-base64`): the extension is
  language-agnostic and will send `parseFile` with `kitId: "python"`, but that
  path requires `sugar-lsp-python` on `PATH` and — for the *literal-fact* flip —
  the same solver wiring above. The hermetic receipt therefore uses the rust
  kit.

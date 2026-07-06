# vscode-sugar — the inline wall (slice A)

Part of **#3774**. This is slice A of the LSP path: **one red squiggle, end to
end.** Open a project, put a source line into a state the prover cannot
discharge, and a red diagnostic appears from the **production** pipeline —
`sugar-linkerd` lifting the file and calling `link()`, the same construction the
proofchain uses. Correct the line and the squiggle clears. Both directions,
live.

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
and runs the wire-protocol test. Expected output ends with:

```
slice A receipt: red -> green -> red verified through sugar-linkerd
```

The `rust` kit is used because its lifter runs **in-process** inside the daemon,
so the receipt is hermetic — no external kit binary required.

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

## What slice A does NOT do yet (slice B / C)

- **Semantic, solver-backed adjudication.** Today's daemon runs pure `link()`
  with an empty solver registry, so it discharges only structurally
  (JCS-canonical implication) or vacuously. It cannot yet prove a *literal test
  assertion* SAT/UNSAT against the vendor universe (`encodeBase64("abc") ==
  "YWJj"` green vs `== "AAAA"` red). That flip needs the linker's
  `link_with_solvers` path wired into the daemon (z3 registry + argument
  binding), which is the natural home of **#3767 slice 2 / the LinkedProof
  upgrade**. When it lands, the same extension paints those diagnostics with no
  editor-side change — the wire shape is identical.
- **Green inlay for discharged facts** (the warrant, hover = CID): **slice B**.
- **Latency hardening** (incremental re-link, warm pool) and the
  `SourcePartition` gutter classes: **slice C**.
- **Stage-rehearsal harness** (scripted, timed red→green→red on the demo
  corpus): **slice D**.
- **Python demo corpus** (`examples/python-literal-base64`): the extension is
  language-agnostic and will send `parseFile` with `kitId: "python"`, but that
  path requires `sugar-lsp-python` on `PATH` and — for the *literal-fact* flip —
  the same solver wiring above. The hermetic receipt therefore uses the rust
  kit.

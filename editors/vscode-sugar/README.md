# vscode-sugar — the inline wall (slice A + B, now in-process)

Part of **#3774**, **#3767 slice 2**, and **the-flip (retiring the daemon)**.
This is the LSP path: **the line flips red↔green live, through the production
pipeline.** Open a project, put a source line into a state the prover cannot
discharge, and a red diagnostic appears from the **production** pipeline —
`sugar-lsp --in-process` minting the edited buffer as a scratch proof and
solving it against the resident base index, the same construction the
proofchain uses. Correct the line and the squiggle clears. Both directions,
live.

There is no shadow verifier in this extension. `extension.ts` is a thin
`vscode-languageclient` client: it spawns `sugar-lsp --in-process` (resolved
via `bin/sugarbin --bin sugar-lsp`) over stdio and lets the LANGUAGE SERVER do
everything — diagnostics, hover, and the "replace with proven value" code
action all come FROM the server (`sugar-lsp/src/prove_engine.rs` +
`fol_format.rs` + `prove_diagnostics.rs`). The editor shows exactly what
`sugar-lsp --in-process` says because it asks it, over the LSP wire.

## History: the daemon this replaced

Earlier revisions of this extension (#3774 slice A/B) ran a separate
long-running `sugar-linkerd` daemon: the extension spoke a bespoke
`parseFile`/`getDiagnostics` JSON-RPC protocol over a Unix socket
(`LinkerdClient`, `protocol/specs/2026-05-04-linker-daemon-protocol.md`), and
the daemon itself ran the lifter and linker. #3844 flipped `extension.ts` to
speak the *real* Language Server Protocol instead, over stdio, to
`sugar-lsp --in-process` — no daemon RPC, no bespoke wire protocol, standard
`vscode-languageclient`. The daemon-3-delete cut then deleted `sugar-linkerd`
itself; nothing in this extension depends on it anymore. (One job the daemon
did still needs a resident process — the rust-analyzer oracle for the Rust
lift pipeline — that lives on as `sugar-ra-oracle`, an internal build-time
detail with no editor-facing surface.)

## What flips, today, through the production LSP server

`sugar-lsp --in-process` adjudicates consistency obligations: for each edited
buffer it mints a source-overlay scratch proof and solves it against the
resident vendor-proof base index (THE ONE DOOR,
`sugar_verifier::consistency::verify_consistency_scoped_with_base_index`).
Non-discharged rows become `publishDiagnostics` entries carrying the
three-fact message (vendor fact / vendor universe / your fact / conjoined /
the fix); `hover` repeats the same block; `codeAction` offers the
vendor-proven-value Quick Fix.

`test/lsp-e2e.test.js` is the headless receipt for this path: it drives
`sugar-lsp --in-process` over real LSP stdio (Content-Length framed
JSON-RPC — the exact wire `vscode-languageclient`'s `LanguageClient` speaks)
against `examples/python-base64-federation` (native Python + a staged vendor
`.proof`, no annotations, no mock lifters) and asserts:

- `didOpen` a consumer buffer whose assertion contradicts the vendor proof →
  a RED `publishDiagnostics` at the assertion's line, carrying the
  three-fact message.
- `didChange` to the agreeing text → diagnostics clear.
- `didChange` back to the contradicting text → the diagnostic reappears.

Run it with:

```
editors/vscode-sugar/test/run-lsp-e2e.sh
```

`test/prove-e2e.test.js` / `run-prove-e2e.sh` and
`test/rust-prove-e2e.test.js` / `run-rust-prove-e2e.sh` are the sibling
receipts for the PROVE path (`proveClient.proveProject`, which shells
`sugar prove --json` on a consumer project) for python and rust consumer
projects respectively.

## The on-stage script (VS Code, human demo)

1. Build/resolve the LSP server (one door, no cargo):
   ```
   bin/sugarbin --bin sugar-lsp
   ```
   It prints the binary path. Point the extension at it via the
   `sugar.lsp.binaryPath` setting.
2. Launch the extension (F5 in this folder, or package with `vsce`).
3. Open a consumer project with a vendor `.proof` staged at
   `.sugar/imports/` and an assertion that contradicts it. Within the
   debounce window a **red squiggle** lands on the assertion, carrying the
   three-fact message.
4. Fix the assertion to agree with the vendor proof. On the next keystroke
   the squiggle **clears** — green, live, before saving.
5. Break it again. The squiggle **returns**.

## What is now wired and what still remains

- **In-process engine — LANDED (#3844).** `sugar-lsp --in-process` builds
  the resident `ProveContext` once at `initialize` and solves every edited
  buffer against it; no daemon, no cold `sugar prove` shell-out for the LSP
  path.
- **Green inlay for discharged facts** (the warrant, hover = CID): still to
  come.
- **Latency hardening** (incremental re-link, warm pool) and the
  `SourcePartition` gutter classes: **slice C**.
- **Stage-rehearsal harness** (scripted, timed red→green→red on the demo
  corpus): **slice D**.

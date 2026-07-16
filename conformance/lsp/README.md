# LSP conversation conformance corpus

Epic [#3809](https://github.com/TSavo/sugar/issues/3809) names the LSP as the
**acceptance test after** the one-protocol work: a pure field-mapping
conversation frozen as **golden NDJSON** in the conformance corpus.

This directory holds that golden. It is captured from the **real** python/pandas
kit through `sugar-lsp --in-process` (same path as
`implementations/rust/sugar-lsp/tests/real_python_kit_prove.rs`), never from the
mock lifter.

## Golden

| File | Conversation |
|------|----------------|
| `real_python_pandas_sum_conversation.ndjson` | real `DataFrame` + `Series.sum`, lying dual-assert → UNSAT diagnostic, truthful twin → clear |

## NDJSON line format

One JSON object per line (NDJSON / JSONL). Keys on every object are sorted
recursively (Unicode code-point order) so the file is byte-stable under
re-encode.

```json
{"message":{...},"role":"client"}
{"message":{...},"role":"server"}
```

- `role`: `"client"` (editor → sugar-lsp) or `"server"` (sugar-lsp → editor)
- `message`: a JSON-RPC 2.0 object (request, response, or notification)

## Pure field-mapping sequence (filtered)

Only these methods appear (everything else from the live session is dropped):

1. client `initialize`
2. server initialize **response** (matched by `id`)
3. client `initialized`
4. client `textDocument/didOpen` (lying twin source)
5. server `textDocument/publishDiagnostics` (UNSAT red squiggle)
6. client `textDocument/didChange` (truthful twin source)
7. server `textDocument/publishDiagnostics` (empty diagnostics = clear)

Dropped (not part of the field-mapping DoD): `client/registerCapability`
(proof-watcher registration), log messages, any other chatter.

## Explicit normalizations (loud, never silent)

Every capture and every replay applies the **same** normalizer. Drift in a
normalized field is intentional only if this list is updated in the same PR.

| # | Field / shape | Live value | Golden value | Why |
|---|---------------|------------|--------------|-----|
| 1 | Project absolute path | `/tmp/sugar-lsp-real-py-kit-…` (or remote tmp) | `__PROJECT__` | Fixture dir is unique per run |
| 2 | Document / root URI | `file:///tmp/…/test_pandas_sum.py` | `file://__PROJECT__/test_pandas_sum.py` | URI embeds project path |
| 3 | `initialize.params.processId` | OS pid or `null` | `null` | Process-local |
| 4 | Object key order | insertion order from serde/tower-lsp | recursive Unicode-sorted keys | Byte stability of the frozen file |
| 5 | Conversation filter | full LSP stream | only the 7 field-mapping turns above | Epic: pure field mapping |

**Not normalized (must stay real and stable):**

- Diagnostic `message` text (FOL from real pandas lift + real solve)
- Diagnostic `range`, `severity`, `code`, `source`
- Source buffer text for lying / truthful twins
- Contract property names inside the FOL (`sum`, `pandas.DataFrame`, array literals)

## Replay DoD

`make test-3809-dod-scoreboard` (with the real kit present /
`SUGAR_REAL_KIT_LSP_REQUIRED=1` on the explicit battleaxe instrument):

1. Drive the real kit through the same conversation.
2. Normalize the live stream with the table above.
3. Assert the normalized NDJSON bytes are **identical** to the golden file.

Update the golden only from a real RAN (never a skip):

```bash
SUGAR_LSP_GOLDEN_UPDATE=1 SUGAR_REAL_KIT_LSP_REQUIRED=1 \
  cargo test -p sugar-lsp --test real_python_kit_conversation_golden \
  real_python_kit_conversation_is_byte_identical_to_golden_ndjson \
  -- --ignored --exact --nocapture
```

## #3928 always-on pins (no real kit)

Local ratchet — does **not** need pandas/z3/battleaxe:

```bash
cargo test -p sugar-lsp --test real_python_kit_conversation_golden \
  golden_ndjson_freezes_field_mapping_sequence \
  real_python_kit_prove_instrument_is_enrolled \
  lsp_solve_buffer_uses_resident_base_one_door \
  -- --exact --nocapture
```

| Pin | Axis | What red means |
|-----|------|----------------|
| `golden_ndjson_freezes_field_mapping_sequence` | gap 1 | Golden missing/corrupt/wrong sequence |
| `real_python_kit_prove_instrument_is_enrolled` | gap 2 | Real-kit prove instrument deleted or mock-only |
| `lsp_solve_buffer_uses_resident_base_one_door` | gap 3 | Dual solve path / mint-as-feed / reintroduced `warm_solve(` |

Residual (optional, not red): gap 4 daemon process-wide plan residency across CLI invocations.

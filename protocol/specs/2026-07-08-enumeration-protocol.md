# Enumeration Protocol (`sugar.enumerate`)

**Status:** the levels the Python kit serves after #8193 (#7757)
**Date:** 2026-07-08, rewritten 2026-11-14
**Layer:** kit-membrane wire protocol, one method
**Related:**
- `2026-05-18-sugar-selection-policy-memento.md` -- the `SourceMemento` locator shape this protocol keys on
- `docs/path-forward.md` ("The nine steps") -- the one way a Python file becomes a proof; mint's walk below is that way's enumeration

## Section 0. Purpose

`sugar.enumerate` is the ONE wire method a driver uses to ask a kit about
its source tree. There is no second enumeration transport and no per-level
wire method: a new question is a new `level` value here, not a new RPC
method.

Two drivers ask the Python kit (`sugar_lift_py_tests.lift_rpc`), and nothing
else does:

1. **Mint's walk** (`sugar-compiler/src/tree.rs`,
   `fold_enumerate_source_tree`): one `source_files` scan of the workspace,
   the `parameter-contract-link-units` rows and one
   `parameter-contract-resume` per link unit, then one `universe` scan per
   file. The universe rows are the proof's rows; there is no `lift` method
   and no deeper descent. The kit retains each enrolled unit in its own
   process until its resume, so the walk holds one resident generation from
   the `parameter-contract-link-units` scan through the last resume
   (`LiftPluginKit::hold_generation`); a generation is retired only between
   requests that stand on their own.
2. **The board door** (`scripts/recensus_enumerate_consumer.py`): per file,
   the `functions` scan (D2), the `context-manager-resolutions` and
   `relation-membership` scans, and one `facts` leaf under `auditFrontier`
   (D3), the construction roll call.

The old typed descent (`Kit -> SourceFile -> Function -> CallSite ->
{Assertion -> Fact}`, with a seek per level and a universe seek by call-site
cue) had no driver and is deleted from the Python kit (#8193). An
assertion's fact reaches the proof only as a row of its owner's one
reduction, in the `universe` scan.

## Section 1. Request

```json
{
  "jsonrpc": "2.0",
  "id": <number>,
  "method": "sugar.enumerate",
  "params": {
    "level": "<one of the levels in Section 3>",
    "at": <SourceMemento-as-JSON> | null,
    "seek": <boolean>,
    "workspace_root": "<string, absolute or kit-relative project root>",
    "options": { ... }
  }
}
```

- `level` selects the question. `source_files` and the workspace row levels
  take no `at`; every per-file level requires `at` naming the file
  (`at.file`, optionally `at.source_cid`).
- `at` is always the PARENT: the file being scanned. The driver never
  fabricates a memento; every `at` it sends was the `memento` of a
  `source_files` node.
- `seek` is `false` everywhere except the board door's `facts` leaf, which is
  sought at the file's own memento under `options.auditFrontier: true`. Any
  other seek is refused by name (JSON-RPC error `-32602`: "seek at level ...
  is not answered; the one seek is level 'facts' under auditFrontier ..."),
  never answered with the whole scan.
- `options`:
  - `sourceWorkspaceRoot`: the locus authority, the root the minted address
    is stated against (an installed corpus records seats against its install
    root). Absent, `workspace_root` stands.
  - `auditFrontier: true`: selects the construction roll call; answered at
    `level="facts"` only.
  - `linkUnitCid`, `resolutionSet`: the `parameter-contract-resume` inputs.

## Section 2. Response

```json
{
  "jsonrpc": "2.0",
  "id": <number>,
  "result": {
    "nodes": [
      {"memento": <SourceMemento-as-JSON>, "audit": <object|null>, "payload": <object|null>}
    ],
    "gaps": [
      {"memento": <SourceMemento-as-JSON>|null, "reason": "<string>"}
    ],
    "termTable": { ... }
  }
}
```

- `nodes` are built nodes: their own `memento`, an `audit` object (the row
  the level answers, when it has one) and `payload` (`null` at every level
  the Python kit serves).
- `gaps` are first-class, in the same address space as `nodes`: an
  unreadable file, an `at` with no `file`, a file outside the workspace root,
  a missing file, a stale `source_cid`. A gap never appears silently as an
  empty `nodes` list when the kit had something to say about why.
- The workspace row level (`parameter-contract-link-units`) answers
  `{"rows": [...]}` instead of `nodes`/`gaps`.
- Fragments (`body_text`, `ast_template`) never cross the wire. `memento` is
  the durable, CID-pinned locator.
- A refusal leaves as a JSON-RPC `error` member by name: a seek off the board
  door's leaf, `auditFrontier` at a level other than `facts`, `facts` without
  `auditFrontier`, an unknown level, and every construction refusal the
  `universe` scan does not answer as a row (the typed-loud RPC membrane). It
  is never folded into `gaps` or into an empty answer.

## Section 3. Levels the Python kit serves

| `level` | `at` | Driver | Answer |
|---|---|---|---|
| `source_files` | `null` (whole workspace) | mint | one node per file: `SourceTree.fragments()` minted through the source oracle, memento `{file, source_cid}`; an unreadable file is a gap |
| `parameter-contract-link-units` | none | mint | `rows`: every enrolled parameter-contract link unit of the workspace |
| `parameter-contract-resume` | none (`options.linkUnitCid`, `options.resolutionSet`) | mint | checks the resolution set against the retained link unit; answers no node (a function's rows are the `universe` scan's) |
| `universe` | a file | mint | every row of every function's one reduction (`tree_enumerate.owner_reduction`): the function-contract row and each assertion row; one `undecided` row per unanswered call site the reduction's final arms owe; a function whose rows name a variable outside its scope as one refused `undecided` member; each exception class's ancestry row. Rows ride `audit` as term-refs into the response's `termTable` |
| `functions` | a file | board door (D2) | one node per function definition (transitive through class bodies, in source order), memento `{file, function_name, span, source_cid, file_cid}`; no reduction runs |
| `context-manager-resolutions` | a file | board door | one node per `with` item coordinate, read off the tree: the item's coordinate and the roll identity (kind, line, col) of the statement that owns it. It states no outcome and reads no table: the consumer reads what the statement built off the `facts` roll call |
| `relation-membership` | a file | board door | one node per occurrence the file's one structural walk saw, per relation and role (`expected` / `observed`) |
| `facts` | a file's own memento, `seek: true`, `options.auditFrontier: true` | board door (D3) | one node whose `audit` is the file's construction roll call: every node whose own sugar is unwritten reports itself; status `failed` when any did, `clean` otherwise |

`call_sites`, `assertions`, `implications`, `exports`, `contract-demands`
and `contract-declarations` are not served by the Python kit (`exports` is a native-export kit's level, `Kit::export`); a
request for them is answered "unknown level" by name.

## Section 4. Demand

One request performs the work its level names for the file named by `at`,
and nothing below it is asked for separately: the `universe` scan is the
whole file's rows, read off each owner's one reduction. An assert is reduced
once, inside its owner's reduction, and never alone. Mementos are the only
identities; there are no cursors, conversation tokens, or invented
positional keys.

Demand is memoized for exactly one RPC-client consistency window. The cache
key is the content address of the JCS-canonical question tuple
`(workspace_root, level, at, seek, options)`, never the bare node memento. A
repeated question is answered from the RPC client's private question map
without crossing the wire. There is no clear, eviction, dirty-bit, or
entry-invalidation API. A CLI command owns one client for the run. An LSP
analysis owns one client for that analysis and constructs a new client for
the next potentially changed world. Dropping the client drops its question
cache and resident kit process coherently.

Inside the Python kit, a demanded file is opened through the one opener
(`open_source_file_for_construction`) and is process-resident under its
whole-file content CID; each owner's reduction is remembered through the one
memo door (`construction_cache`). Changing the file changes the CID and
therefore misses without a staleness check. Parsed AST and temporal context
are ephemeral implementation state: they are not mementos, are never
serialized, and never cross the wire.

## Section 5. Content-addressed term DAG

Any response that carries ProofIR terms carries one payload-level
`termTable` object. Its keys are the existing semantic term CIDs. Each value
contains one canonical term node: scalar fields plus immediate child
`{"kind":"term-ref","cid":"..."}` references. Formula term positions carry
the same reference shape. The symbol-kind testimony table remains a separate
payload sidecar and does not enter term identity.

The CID of a table row is computed from the same fully resolved canonical term
bytes used before this wire shape. Therefore the wire representation changes
without changing any term CID or downstream proof identity. A receiver decodes
the table once, interns exactly one shared node per CID, and resolves every
term position by lookup. Missing children, cycles, malformed references, and
CID-to-content mismatches are transport decode failures, and a term-ref in a
response with no `termTable` is malformed. There is no inline term-tree
compatibility arm at this wire door.

The table is a serialization of already constructed terms, not permission to
construct descendants eagerly. It contains only the unique terms reached by
the response being answered.

## Section 6. Conformance obligations

1. **One walk.** Mint's proof rows are exactly the `universe` scan of every
   `source_files` node. No other level, seek, or method states a row.
2. **No silent narrowing.** A question the kit does not answer is a named
   JSON-RPC error; a file it cannot read is a named gap. Neither is an empty
   success.
3. **The board door builds, never reduces.** `functions`,
   `context-manager-resolutions`, `relation-membership` and the `facts` roll
   call construct the file's tree; none of them reduces a function body.

Exercised by `sugar-lift-py-tests/tests/test_enumerate_rpc.py` (including
`test_a_seek_off_the_board_door_leaf_is_refused_by_name` and
`test_the_call_sites_level_is_gone`) and the Rust client in
`sugar-compiler/src/tree.rs`.

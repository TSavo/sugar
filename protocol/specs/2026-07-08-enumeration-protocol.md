# Enumeration Protocol (`sugar.enumerate`)

**Status:** v0.1.0 landed (Part 6, Phases 1+2)
**Date:** 2026-07-08
**Layer:** kit-membrane wire protocol, one method
**Related:**
- `~/.claude/plans/sugar-compiler-liftshift.md` Part 6 ("The refactor at hand: Rust shape -> protocol -> RPC-driven kit")
- `2026-05-18-sugar-selection-policy-memento.md` -- the `SourceMemento` locator shape this protocol keys on
- `2026-05-25-lsp-shared-protocol.md` -- the seek-by-memento query shape this protocol's `seek` mode generalizes

## Section 0. Purpose

`sugar.enumerate` is the ONE wire method behind `sugar-compiler`'s lazy
navigable tree (`Kit -> SourceFile -> Function -> CallSite -> {Assertion ->
Fact}`). Every accessor in `sugar-compiler/src/tree.rs`
(`Kit::source_files`, `SourceFile::functions`, `Function::call_sites`,
`CallSite::assertions`, `Assertion::facts`, plus their singular seek
counterparts) is exactly one `sugar.enumerate` request-response pair. There
is no second enumeration transport and no per-level wire method: adding a
level to the tree means adding a `level` value here, not a new RPC method.

## Section 1. Request

```json
{
  "jsonrpc": "2.0",
  "id": <number>,
  "method": "sugar.enumerate",
  "params": {
    "level": "source_files" | "functions" | "call_sites" | "assertions" | "facts" | "universe",
    "at": <SourceMemento-as-JSON> | null,
    "seek": <boolean>,
    "workspace_root": "<string, absolute or kit-relative project root>"
  }
}
```

- `level` selects the granularity. `source_files` is the root scan (no
  parent); every other level requires `at`.
- `at` is a memento -- either the PARENT's memento (scan mode, `seek:
  false`: "give me every child of this node") or THIS node's OWN memento
  (seek mode, `seek: true`: "give me exactly the one node this memento
  names"). The driver never fabricates a memento; every `at` value it sends
  was itself the `memento` field of a node returned by a previous
  `sugar.enumerate` response (or, for `source_files`, may be omitted
  entirely for a full scan).
- `seek` disambiguates scan-vs-seek at levels where the SAME `level` value
  is used both ways (`source_files`, `functions`, `call_sites` are
  well-defined as scans; `assertions` and `facts` are always answered
  seek-style in this landing, since a call site's own contract item IS its
  one assertion in the granularity landed -- see Section 4).

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
    ]
  }
}
```

- `nodes` are BUILT nodes: their own `memento` (this node's primary key --
  usable as `at` in the NEXT step down, or replayed back as a seek `at` at
  THIS level), an `audit` object (the factory's construction record for
  this node, when the kit tracks one), and a `payload` (populated at
  `level="facts"` with the assertion FOL, and at `level="universe"` with
  the function-contract `inv`/`post` formula when present).
- `gaps` are FIRST-CLASS, in the SAME address space as `nodes` (plan's
  "GAPS ARE NODES" rule): a level's enumeration can find a memento with no
  usable child at all (an unresolved call, a construction the factory
  refused). A gap never appears silently as an empty `nodes` list with no
  explanation when the kit had something to say about why.
- Fragments (`body_text`, `ast_template`) NEVER cross the wire. `memento`
  is always the durable, CID-pinned locator; a driver that wants the
  fragment text calls the existing `sugar.plugin.resolve_source_memento`
  verb separately (`Kit::source`/`SourceFile::source`, unchanged by this
  spec).
- An RPC-level failure (spawn/transport/decode) is a JSON-RPC `error`
  member, standard shape (`{"code": ..., "message": ...}`), never folded
  into `gaps`.

## Section 3. Levels

| `level` | Scan `at` | Seek `at` | Kit-side backing (landed) |
|---|---|---|---|
| `source_files` | `null` (whole workspace) | a file-only memento | `_iter_python_files` |
| `functions` | a `source_files` memento | a function's own memento | `payload.ir` entries (`BodyUniverseDto`), `kind="function-contract"`, plus synthesized nodes for functions that merely enclose a `kind="contract"` assertion with no contract of their own (Section 4) |
| `call_sites` | a `functions` memento | a call site's own memento | `payload.ir` entries, `kind="contract"`, scoped by `source_function_name` |
| `assertions` | -- (seek only) | a call site's own memento | same `kind="contract"` item (1:1 with its call site -- Section 4) |
| `facts` | -- (seek only) | an assertion's own memento | the item's `inv` (else `post`) field, as the FOL payload |
| `universe` | a file memento (`seek=false`: every universe in the file) | a call site's own memento (`seek=true`: the universe linked to that callsite) or a universe node's own memento | `payload.ir` entries, `kind="function-contract"` (body universes + operator builtin universes such as `len::builtin-universe`). Seek from a call site joins via `bridgeSourceSymbol` / FOL `call:`·`method:` ctor identity; missing link is a gap (`no universe sugar for callee <name>`). Node mementos stamp the batch `name` onto `function_name` so member keys survive `SourceMemento` round-trip. |

## Section 4. Granularity landed (report, not hidden)

Per the plan's Phase 3 ("it is ACCEPTABLE ... for the first cut to lift the
WHOLE file server-side ... and slice/serve the requested level from that
one parse"), this landing is **file-granular, not per-node wire-lazy**:
every `functions`/`call_sites`/`assertions`/`facts` request re-lifts the
ONE target file server-side (`lift_source`) and slices the in-memory
result. `source_files` alone is genuinely workspace-scanned without a
per-file lift.

Two further simplifications, both flagged rather than silently narrowed:

1. **Call site == assertion, 1:1.** The shipping python kit's
   `payload.ir` has no distinct "call site" node separate from the
   assertion it carries (`kind="contract"` entries already bundle locus +
   claim formula in one record). `CallSite::assertions()` therefore always
   returns exactly the one `Assertion` built from the same record as its
   `CallSite`. A true multi-assertion-per-call-site split (e.g. more than
   one claim about the same call expression) is not representable by this
   landing; it needs a kit-side change, not a protocol change.
2. **`universe` is function-contract IR, linked by bridge identity.**
   `CallSite::universe()` issues `sugar.enumerate` at `level=universe`
   with the call site's memento and `seek=true`. The kit finds the
   matching `kind="contract"` row, extracts the callee's `call:` /
   `method:` identity from its FOL (or name), and returns the
   `kind="function-contract"` row whose `bridgeSourceSymbol` matches
   (body law or builtin universe). No match → gap node
   (`no universe sugar for callee <name>`); the Rust client maps empty
   nodes to `Ok(None)`. File-level scan (`seek=false`) lists every
   function-contract universe in the file for completeness auditing.
   First-class `bridgeSourceSymbol` on call-site nodes themselves is a
   separate Campaign A task (identity), not this level.
3. **`Function::call_sites()` scoping is name-based.** A call site is
   attributed to its enclosing function by matching the assertion
   record's own `source_function_name` against the target function's
   name -- there is no AST-scope (line-range) index kit-side yet. Two
   same-named nested/shadowing functions in one file would collide; out
   of scope for this landing's fixture-sized corpus.

## Section 5. Obligation side (out of scope this pass)

`CallSite::contract()` and `CallSite::implication()` are LINK-time
(`#3831`): no `sugar.enumerate` request is made for them. `contract()`
always returns `EdgeTarget::Unbound`; `implication()` always returns
`None`. Binding them is `ProofGraph::solve`'s job (SEAM 5), not this
protocol's.

## Section 6. Conformance obligations

1. **Fold == whole-project lift.** Folding the enumeration tree
   (`source_files().flat_map(functions).flat_map(call_sites).flat_map(assertions).flat_map(facts)`)
   over a fixture project must produce the SAME fact set (memento +
   formula, modulo ordering) as the existing whole-project `Kit::lift`'s
   `DomainClaim.payload` (`factoryWalk`/`ir` entries embedded verbatim in
   the `Term::Const` the lift kit's RPC response already carries).
2. **Scan/seek coherence.** For every level, `plural()[i]` and
   `singular(plural()[i].memento)` (i.e. `at=plural()[i].memento,
   seek=true`) must return a byte-identical node (same memento, same
   audit, same payload). This proves the kit serves ONE consistent
   address space, not two dialects for scan vs seek.

Both are exercised by
`sugar-compiler/tests/enumerate_conformance.rs` against
`sugar-compiler/tests/fixtures/enumerate_fixture/`.

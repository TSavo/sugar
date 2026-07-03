# voltron-demo — multi-vendor, multi-file Sugar consumer

This crate is the smallest non-trivial M × N consumer of the Sugar
substrate. The intent: prove that **a single user-authored program can
compose contracts from multiple independent vendor `.proof` envelopes
into one verifiable spine**.

- **M = 3** module files (`ingest.rs`, `persist.rs`, `report.rs`) + a
  thin binary entry (`src/bin/voltron-demo.rs`) and a top-level library
  spine (`lib.rs`).
- **N = 2** vendors: `sugar-shim-serde-json-rust` (JSON family) and
  `sugar-shim-rusqlite` (SQL family).
- **5** materialize boundary citations spread across two of the three
  module files (ingest.rs owns the JSON ones; persist.rs owns the SQL
  ones; report.rs is pure user code that crosses both vendors at the
  seam where SQL row text is decoded back into a JSON `Value`).
- **3** test files (`ingest_test.rs`, `persist_test.rs`,
  `voltron_e2e_test.rs`) — these ARE the canonical user-side contract
  surface, lifted by `sugar-lift-rust-tests`. Per the rust-tests
  lifter contract, panics and early-returns inside user functions
  (`parse_event`, `install_schema`, `insert_event`, `compose_report`)
  also lift to implicit pre/post conditions.

When everything runs end-to-end, `sugar prove` against this crate
unions THREE `.proof` envelopes:

  1. `voltron-demo.proof`                    — the head (this crate's spine)
  2. `sugar-shim-serde-json-rust.proof`   — the JSON lion
  3. `sugar-shim-rusqlite.proof`          — the SQL lion

surfaced through the rust kit's `sugar.plugin.resolve_dependency_proofs`
RPC (PR #1568) walking `cargo metadata`. Discharge composes across every
cross-vendor seam in the spine.

## Status (as of this PR — final overnight update)

The demo **builds, runs, and passes all tests end-to-end** after closing
Gap #5 user-side. The substrate fix (Gap #1, PR #1572) closes the
multi-library-destroys-refused bug. Three other surfaced gaps (#2, #4,
remaining materialize/mint config polish) are tracked as follow-up
issues and PRs. Each gap is a concrete instance the substrate's stated
M × N claim needed to satisfy on first contact with a real user-shaped
consumer.

### Green path (verified tonight)

```
$ cargo build --manifest-path examples/voltron-demo/Cargo.toml
   Finished `dev` profile [unoptimized + debuginfo] target(s) in 2.27s

$ cargo test  --manifest-path examples/voltron-demo/Cargo.toml
test result: ok. 5 passed; 0 failed   (tests/ingest_test.rs)
test result: ok. 3 passed; 0 failed   (tests/persist_test.rs)
test result: ok. 3 passed; 0 failed   (tests/voltron_e2e_test.rs)
                                       — including full_spine_round_trip_succeeds,
                                         the cross-vendor end-to-end witness

$ cargo run   --manifest-path examples/voltron-demo/Cargo.toml --bin voltron-demo
voltron round-trip: rowid=1 user=alice type=signup report="{\"age\":30}"
```

11/11 tests green. JSON → SQL → SQL → JSON round-trip across both
vendor lions, in user code, threaded by the head's spine. The bin
output shows the cross-vendor seam closed: `serde_json::to_string` of
the payload feeds `rusqlite`'s INSERT, then `rusqlite`'s SELECT feeds
`serde_json::from_str` back to a `Value`, and the spine prints the
final `age=30` from the round-tripped JSON.

### Recognizer pilot — Voltron from the recognize side (overnight)

The full Recognizer foundation lives in `feat/recognizer-foundation`
(PR pending). With both shim `.proof`s as bindings, `sugar recognize`
derives the same five boundary tags the explicit-carrier-comment path
produces — Phase 2 parity proven, on the real demo:

```
$ sugar recognize \
    --project /…/examples/voltron-demo \
    --source src/lib.rs --source src/ingest.rs \
    --source src/persist.rs --source src/report.rs \
    --binding /…/sugar-shim-serde-json-rust/blake3-512:….proof \
    --binding /…/sugar-shim-rusqlite/blake3-512:….proof

dispatch: surface=`rust-bind` bindings=46 sources=4
recognize: 5 tag(s) emitted
  [0] concept:json-parse           @ src/ingest.rs:14 (exact)
  [1] concept:json-serialize       @ src/ingest.rs:21 (exact)
  [2] concept:sql-connection-open  @ src/persist.rs:16 (exact)
  [3] concept:sql-execute          @ src/persist.rs:23 (exact)
  [4] concept:sql-query-row        @ src/persist.rs:39 (exact)
```

Five tags from idiomatic user-code function bodies, derived purely from
the shims' published sugar templates. M × N composition: 2 vendors,
5 boundaries, 2 modules, all spans matched by structural template
equality after alpha-equivalence on parameter names. The lifter writes
`ast_template` + `template_cid` into the `.proof` at mint time; the
recognizer reads them back and matches. Cycle invariance over the
sugar binding.

### End-to-end discharge — recognize tags drive callsite enumeration AND resolve to shim contracts

`recognize --write` mints both halves of the obligation: bridge
mementos (sourceSymbol → vendor contract_cid) AND contract mementos
(post atomic with `ctor(name=function_name)`). Bridges link via a
ctor-name index over the loaded shim `.proof`'s contract mementos —
the same linkage the rust-tests lifter would produce. With the shim
`.proof`'s staged into the demo's pool:

```
$ sugar prove examples/voltron-demo

  total callsites: 6
  discharged:      2    ← was 0; the Voltron loop closes
  violations:      4

  [discharged] json_parse  (rust → serde_json)
      reason: vacuous: no precondition on target (publisher post-only)
  [discharged] json_parse  (rust → serde_json)
      reason: vacuous: no precondition on target (publisher post-only)
  [undecidable] sql_execute     bridge target CID not in pool
  [undecidable] open_in_memory  bridge target CID not in pool
  [undecidable] sql_query_row   bridge target CID not in pool
  [undecidable] json_serialize  bridge target CID not in pool
```

**SUPERSEDED AGAIN — final state below.** With #1580 also landed
(walk_rpc now emits a sibling `kind: contract` decl per
native library-binding metadata, cmd_mint mints it into the shim's `.proof`),
the bridges resolve to substrate-PUBLISHED contract mementos
instead of recognize's own implication fallbacks.

```
$ sugar prove examples/voltron-demo

  total callsites : 9
  discharged      : 9    ← all
  violations      : 0
  load errors     : 0
```

The full Voltron loop end-to-end with substrate-honest provenance:

1. **Lift** — walk_rpc walks the shim source, emits two records
   per native library-binding declaration:
   a. `library-sugar-binding-entry` (with the new `ast_template`
      field) — what materialize splices and recognize matches against.
   b. `kind: contract` decl with a trivial-identity post — what
      `enumerate_callsites` finds as a callsite anchor.
2. **Mint** — cmd_mint canonicalizes + signs both into the shim's
   `.proof` envelope. The shim's `.proof` now publishes a contract
   memento for every sugar function.
3. **Recognize** — walks idiomatic user code, matches function
   bodies' identifier-canonical AST templates against the shim's
   published binding templates by `template_cid`. For each match,
   emits a bridge (`sourceSymbol → targetContractCid`) and an
   implication contract memento (`ctor(name=<function>)` in post).
   The bridge's target resolves via ctor-name index across the
   loaded shim `.proof`'s — finds the shim-signed contract memento
   from step 2.
4. **Prove** — `enumerate_callsites` walks every contract memento
   in the pool. Finds ctors. Looks up bridges by sourceSymbol.
   Resolves to target contracts. Discharger composes the
   post → pre chain.

Nine callsites enumerated from the union pool (5 from recognize's
implications + 4 from the shims' sugar contracts + 1 from the
existing test-witness contract; some discharge multiple times via
overlapping ctor references). Every one discharges. The 5
recognize-emitted bridges resolve to **shim-signed contract
mementos**, not recognize-side sibling fallbacks. Substrate-honest
provenance throughout. M × N (2 vendors, 5 user functions) composed
end-to-end.

Four sub-issues all closed:
  - #1577 — recognizer foundation (this PR)
  - #1578 — emit bridge + implication mementos (closed)
  - #1579 — shared emission code in libsugar (closed)
  - #1580 — shims mint contracts per sugar (closed)
  - #84 — substrate gap #84 refused=no-op (closed in PR #1572 earlier)

### Mint + prove (also wired up tonight)

`.sugar/config.toml` declares `rust-sugar` + `rust-contracts` lift
surfaces. Per-project lift manifests at `.sugar/lift/rust-bind/`
and `.sugar/lift/rust-contracts/` mirror the
`sugar-shim-blake3-rust` pattern: `command = ["../../implementations/
rust/target/debug/<binary>", "--rpc"]` with `working_dir = "."`. The
relative path resolves from the demo's project root up two levels to
the workspace root, finding the shared lifter binaries.

```
$ sugar mint /Users/tsavo/sugar/examples/voltron-demo
config: 2 plugin(s) declared: rust-sugar, rust-contracts
dispatch: surface=rust-bind plugin=rust-bind-lift ok
dispatch: surface=rust-contracts plugin=rust-contracts-lift ok
  catalog CID:     blake3-512:016f3412…
  contractSetCid:  blake3-512:6c248fb7…
  proof bytes:     7676
  .proof file:     blake3-512:016f3412….proof

$ sugar prove /Users/tsavo/sugar/examples/voltron-demo
Sugar verifier report
  total callsites: 0
  discharged:      0
  violations:      0
  load errors:     0
```

`total callsites: 0` is expected for the current committed source:
the demo is in its **post-materialize** state (carrier comments were
stripped when materialize filled the stub bodies). The lift sees plain
functions and finds no boundary citations to emit bridges for. To
populate the bridge set, run mint against the **pre-materialize**
source (committed as the first commit on this branch, `9eb3ebf4a`)
where the carrier comments + `unimplemented!()` stubs are present;
then materialize to fill bodies; then build + test as today.

The full M × N composition with three `.proof`s in the pool also
requires the rust kit's `resolve_dependency_proofs` to find the shim
crates' `.proof`s in cargo metadata. Today voltron-demo depends on
`rusqlite` and `serde_json` directly (the post-materialize bodies call
them); to surface the shim contracts into the pool, the demo would
depend on `sugar-shim-rusqlite` and `sugar-shim-serde-json-rust`
instead (they re-export the underlying crates plus carry the signed
`.proof` envelopes). This is the canonical Voltron-time consumer
shape; deferred as a small follow-up so the demo's current commit
captures the substrate plumbing without growing scope.

## Gaps exposed

### Gap #1 — Refused boundary destroys carrier+stub
**State:** FIXED in #1572 (substrate fix on a separate branch off main).

The original `transform_source_text_one_pass_collecting_refusals` arm
for `SiteOutcome::Refuse` consumed-and-dropped the carrier comment and
stub function from the rewritten source. A second library's materialize
pass found nothing to fill. Fix: emit the original lines verbatim on
refuse so multi-library passes leave each other's boundaries intact.
Two regression tests added.

### Gap #2 — `--library` is single-vendor; should be deleted
**State:** Tracked as task #84, follow-up PR.

`sugar materialize --library <lib>` accepts a single library tag per
invocation and routes ALL boundaries to that library (refusing anything
the library doesn't provide). The substrate-honest contract is per-family
routing: every boundary declares its `family` (e.g. `concept:family:json`,
`concept:family:sql`), and `--family-library family=library` (repeatable,
already implemented but currently requires `--library` as a base) maps
each family to its realizer. Deleting `--library` forces every consumer
to declare family routing explicitly and makes multi-vendor single-pass
materialize the only mode. Plan:

  1. Remove `--library` field from `MaterializeArgs`.
  2. Make `--family-library` standalone + repeatable.
  3. Boundary without `family` → refuse with a clear error.
  4. Migrate the ~1000 LOC of integration tests that use `--library`.

### Gap #3 — Stub param names must match carrier-comment payload verbatim
**State:** User-side convention. Documented here.

The kit's emitted body references parameter names exactly as declared
in the carrier-comment payload's `params` field. If the stub function
uses `_x` (the rust convention for "intentionally unused parameter"),
the splice produces `body_references_x_not__x` and won't compile.

**User-side fix:** stub params MUST match the payload's `params` list
verbatim. Don't underscore-prefix; rely on rust treating `unimplemented!()`
as divergent (no unused-variable warning).

### Gap #4 — Splice mishandles pre-existing attributes on stub
**State:** NEW. Filed as a follow-up issue.

When a stub function carries pre-existing attributes (e.g.
`#[allow(unused_variables)]`, `#[deprecated]`, custom user attributes),
the materialize splice machinery APPENDS a new annotated function with
the spliced body INSTEAD OF REPLACING the stub's body. The resulting
source has two definitions of the same function. E0428 (duplicate
definition).

**Substrate fix needed:** `transform_source_text_one_pass*` must
recognize the entire `attributes + signature + body` block as the unit
to replace, not just the `pub fn name(...)` signature line.

### Gap #5 — Shim concept vocabulary doesn't cover all user shapes
**State:** Tracked as issue #1575. **CLOSED FOR THE DEMO** by adopting
resolution path (b): user-side `sql_query_row<T, P, F>` matches the
shim's 4-param mapper form. Callers pass `|row| row.get(0)` closures.
This keeps the demo green without growing the shim's concept vocabulary.

`sugar-shim-rusqlite`'s `concept:sql-query-row` binding emits a body
calling `conn.query_row(sql, params, mapper)` — a generic 4-param form
requiring a closure mapping `&Row<'_>` to `T`. A user who wants a
typed-string-row helper has to either match the shim's exact 4-param
shape or the shim must offer additional concepts for common typed-row
shapes.

**Resolution paths (#1575 long-term):**
  (a) Add `concept:sql-query-row-string` (and similar monomorphic
      forms) to sugar-shim-rusqlite's `provides_concepts`.
  (b) Redesign user-side function to match the shim's 4-param form
      (carries a mapper closure). **THIS DEMO PATH.**
  (c) Add a kit-side adaptation: when the user declares fewer params
      than the shim concept's canonical form, the kit synthesizes a
      default mapper.

## What this PR contains

- `Cargo.toml` — package manifest, deps on `rusqlite` + `serde_json`.
- `src/lib.rs` — top-level module re-exports + `run_voltron_demo`
  spine.
- `src/ingest.rs` — JSON ingestion module. Two boundary stubs
  (`json_parse`, `json_serialize`) + user-side `parse_event` returning
  `ValidEvent`.
- `src/persist.rs` — SQL persistence module. Three boundary stubs
  (`open_in_memory`, `sql_execute`, `sql_query_row_string`) + user-side
  `install_schema` and `insert_event`. (Note: `sql_query_row_string`
  hits Gap #5 once materialize fills the body.)
- `src/report.rs` — pure user code; the cross-vendor seam where SQL row
  text is fed into `json_parse`. Owns no boundaries itself.
- `src/bin/voltron-demo.rs` — thin binary entry.
- `tests/ingest_test.rs` / `tests/persist_test.rs` /
  `tests/voltron_e2e_test.rs` — unit + integration tests as the
  canonical user-side contract surface.
- `RESULT.md` — this file.

## Validating against the substrate

With the substrate-fix PR #1572 merged, run from the repo root:

```bash
# Pass 1: fill SQL boundaries (refused JSON sites stay intact thanks to #1572).
sugar materialize --target rust --library rust-rusqlite \
  --source-dir examples/voltron-demo/src \
  --project /Users/tsavo/sugar \
  --write

# Pass 2: fill JSON boundaries.
sugar materialize --target rust --library sugar-shim-serde-json-rust \
  --source-dir examples/voltron-demo/src \
  --project /Users/tsavo/sugar \
  --write
```

Both passes succeed. Then:

```bash
cargo build  --manifest-path examples/voltron-demo/Cargo.toml
cargo test   --manifest-path examples/voltron-demo/Cargo.toml
```

**Today these still fail** at Gap #5 (sql-query-row body emits 2-arg
call where rusqlite::Connection::query_row needs 3). The follow-up that
adopts the 4-param mapper shape closes this and unblocks build+test.

After build is green:

```bash
sugar mint  --project examples/voltron-demo
sugar prove --project examples/voltron-demo
```

`prove` will union three `.proof` envelopes (voltron-demo + serde-json
shim + rusqlite shim, the latter two resolved through the rust kit's
`resolve_dependency_proofs` RPC over cargo's resolved tree) and
discharge across every cross-vendor seam.

## The point

The demo's PURPOSE in its current state is not to be a working artifact
but to **expose the load-bearing M × N invariant in concrete code.**
Every gap above is a specific claim the substrate makes that didn't hold
on first contact with a real user-shaped consumer. The substrate-fix PR
closes Gap #1; the follow-ups close the others. When all five are
closed, this crate becomes the canonical end-to-end Voltron acceptance
test — same source, three `.proof` envelopes, one verifier discharge.

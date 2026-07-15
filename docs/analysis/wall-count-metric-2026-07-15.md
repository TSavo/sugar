# Wall panic count jump, 2026-07-15: measurement-integrity analysis

## Question

NumPy wall panics moved from 1,211 independent / 4,051 suppressed descendants
(run 29382152736, 2026-07-15 01:39 UTC, head `ea96a8a50`) to 5,569–5,579 / 7,315–7,345
(runs 29392026094 / 29427248254, heads `e9afe8e92` / `ba4f52528`) — a ~4.6x jump in
under 24 hours. Pandas moved similarly (2,517/5,129 → 11,417/12,938). Is this the same
metric, and if so, what moved it?

## Verdict: (a) expanded honest reach — a new loudness rule, not a counting bug

The metric is unchanged; ~83% of the new numpy panics are one new panic class
(`CallSugar` import-alias resolution) introduced by PR #4489, which converts calls that
were previously **silently opaque** into **mandatory panics**. No double-counting, no
schema redefinition, no enumeration change.

## Evidence

### 1. Same metric, same schema

Both artifacts (`gh run download 29382152736` and `29427248254`, artifact `numpy-wall`)
have identical schemas:

- `summary.json` → `frontier.{effectCount, independentPanicCount, kind:
  "recovered-construction-audit", suppressedDescendantCount}` — byte-identical key set.
- `frontier.json` → `{census, effects, kind, panics[], recoveryOverride, status,
  suppressedDescendants[]}`; each panic is `{kind: "FactoryPanic", status:
  "mandatory-panic", reason, locus, gap{owner, blame, observed, requested, fix,
  gap_kind, gap_locus}}` in both runs.
- `panics[]` length equals `independentPanicCount` in both (1,211 and 5,569).
  "Independent panics" and `suppressedDescendantCount` are the same two distinct
  fields in both runs — no field renaming or re-bucketing.

### 2. Enumeration reach did NOT change

`frontier.json.census` is **identical** in both runs:
`{sourceFilesEnumerated: 407, sourceBodiesDemanded: 407, auditLeavesCompleted: 10739}`.
The auditor visited exactly the same corpus. The jump is not "more files scanned."

### 3. No double-counting

- Zero duplicate panic records in the new run (full-record dedup: 5,569 unique of 5,569).
- Per-locus multiplicity is stable (max 14 per locus in both runs, same top locus
  `lib/tests/test_recfunctions.py:5:0`).
- Locus overlap: 1,055 of the old run's 1,179 loci persist; 124 old loci disappeared
  (fixed by the #4483–#4496 lift improvements); 4,443 loci are new.

### 4. The delta is one new panic class

Breakdown by `gap.owner`:

| owner | old (1,211) | new (5,569) |
|---|---|---|
| CallSugar | ~0 | **4,640** |
| TemporalContext | 354 | 328 |
| python.factory | 118 | 108 |
| others | ~739 | ~493 |

Of the 4,640 CallSugar panics, 4,633 carry
`requested = "resolve an exact installed-source FunctionDef for a called import alias"`
and 7 carry the starred-argument expansion message. Every non-CallSugar owner count is
flat or *down*.

### 5. Which commit, and the mechanism

`git log -S "resolve an exact installed-source FunctionDef" ea96a8a..ba4f525` hits exactly
one commit: **`f31ae4509` — "fix: resolve qualified imported function sources exactly"
(#4489)**. The diff in
`implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/call_sugar.py`
adds, in `CallSugar`'s call path:

```python
if isinstance(bound, ImportAliasValue):
    if isinstance(bound.resolved_value, FunctionCallable):
        bound = bound.resolved_value
    else:
        factory_panic_gap(
            owner="CallSugar", ...,
            requested="resolve an exact installed-source FunctionDef for a called import alias",
            fix="install one source-qualified function definition or keep the call opaque outside CallSugar",
        )
```

**Before #4489**: a call target bound to an `ImportAliasValue` whose resolved value was
not a `FunctionCallable` fell through the `isinstance(bound, FunctionCallable)` check and
the call stayed *opaque* — no panic row, invisible to the wall. **After #4489**: CallSugar
demands exact installed-source resolution for import-alias call targets and panics loudly
when it cannot get one. In a corpus like numpy where most call sites go through import
aliases (`from ... import x; x(...)`), this converts thousands of previously-silent
opacity gaps into mandatory panic rows in one step. The companion #4508
("delete import-alias site fallback") tightened the same boundary but did not add the
panic class. The intermediate bisect confirms timing: run 29392026094 (head `e9afe8e92`,
which includes #4489/#4508) already shows 5,579/7,345.

`suppressedDescendantCount` rose proportionally (4,051 → 7,315) because each new
independent panic suppresses its own descendant sites — consistent, not double-counted.

### 6. Candidate PRs ruled out

- **#4503** (suppressed audit ownership): reassigns ownership of already-counted
  suppressed rows; both counts predate and postdate it with the same semantics.
- **#4502** (terminal proof row): panic row *contents* (proof column), not cardinality.
- **#4509**: Rust test-compile warning hygiene; no producer change.
- **#4515** (star exports) / #4483 (varargs) / #4488 (starred args): small contributors
  at most — #4488's message accounts for only 7 of the 4,640 new CallSugar panics, and
  #4515 landed after the count had already reached ~5,569.

### 7. Baseline language implication

The "independent panics" number is comparable across runs **only at fixed lift
capability**. #4489 is a deliberate honesty ratchet: it widened what the wall is allowed
to see, so 1,211 → 5,569 is not a regression to revert but a baseline re-anchor. Any
ratchet gate keyed to `independentPanicCount` should re-baseline at the #4489 boundary
(numpy 5,569/7,315; pandas 11,417/12,938 as of head `ba4f525`), and future capability
PRs that add panic classes should note the expected count step in their description.

## Minor count noise

5,579 vs 5,569 between runs at different heads (`e9afe8e92` vs `ba4f525`/`2cdbc77c`)
reflects ten panics *fixed* by #4511/#4512 (native extension call bridging) — normal
ratchet movement, same metric.

# Python frontier drain directive

> The objective is to eliminate authenticated residuals, not preserve today’s board. Pins protect completed laws only. A red residual is work or reattribution—never a baseline to ratify.

**Authority:** sole control-effect board
`docs/ledgers/pandas-3.0.3-control-effect-9a78828ee.json` (commit `9a78828ee`,
`R_desugar_construction_panics=502`) is a **historical receipt**. It is not a
live work list. #6352/#6354 (demand SET) and #6381 (IfExp face twin) landed
**after** that board.

**Ruling (AGENTS.md — Re-measurement and pins):**

- Re-measurement may prove an owner already drained. It may not replace
  unresolved semantic work with a pin.
- Pins protect completed laws (truthful + lying faces implemented) only.
- Never pin Categories 3 / 5 / 6 as accepted red.
- Baseline receipt: every node is exactly one of categories 1–6.

## Historical owner mass (stale board — remeasure before drain)

| N | owner | default disposition |
|---|-------|---------------------|
| 283 | `ContractConditionalConstructionV1.and_then` | **Re-measure.** Same law as #6354 demand SET. Do not infer closure from ancestry; do not pin survivors. |
| 46 | `IfExpSugar._join` | **ΔR=0 at current baseline; historical 46 already retired by #6354.** Twin #6381 protects the face law. Not a drain. |
| 41 | `collection ListValue` | Re-measure (demand SET family). |
| 26 | `collection build` | Re-measure (demand SET family). |
| 25 | `guarded` | Re-measure → drain general guarded law if live. |
| 15 | `ground_index_error` | Re-measure → drain if live. |
| 11 | `add` | Re-measure → drain operator floor if live. |
| 8 | `bitwise_and` | Re-measure → drain if live. |
| 7 | `GuardedValue._map(subscript)` | Re-measure → drain if live. |
| 6 | `attribute` / `RuntimeEffect` / `multiply` | Re-measure → drain if live. |
| 5 | `subtract` / `collection TupleValue` | Re-measure (TupleValue: demand SET family). |
| ≤2 | bitwise_* / ground_* / truth / divide / unary_plus / dict.subscript / BlockValue.to_term | Re-measure → drain if live. |

## Fleet lanes (non-overlapping)

| Lane | Mission | Do not |
|------|---------|--------|
| **L0** | Live remeasure of all 502 historical desugarConstructionPanic sites at HEAD. Emit `docs/ledgers/python-desugar-panic-remeasure-<commit>.json` with per-row category 1–6. Rank live Category-5 owners by mass. | Do not implement product fixes. Do not pin red. |
| **L1** | Demand-SET family confirmation only: `and_then` + collection ListValue/build/TupleValue. Report zeros or survivor list. | Do not re-widen the carrier if live residual is a different owner. |
| **L2** | IfExp close-out receipt only: record `ΔR=0; historical 46 retired by #6354`; verify #6381 twins; no drain PR. | Do not open a "drain IfExp" PR. |
| **L3** | First live Category-5 owner after L0 rank (expected candidates: `guarded`, `ground_index_error`, or arithmetic). General law + truthful/lying twins + remeasure to zero. | No name/site arms. No pin of residual. |
| **L4** | Second live Category-5 owner (same bar as L3). | Same. |

After L0 lands, re-rank and redispatch L3/L4 if the live mass differs from historical.

## Per-owner cut (when draining)

1. Reproduce occurrence count at the pin commit.
2. Does the general law already exist?
3. If yes: prove all occurrences construct/desugar; discrimination twin only if removing the law fails it.
4. If no: implement the general mechanism—not a name/site arm.
5. Truthful + lying twins.
6. Re-measure the same owner.
7. Accept only if residual is zero or every survivor is reattributed to a **different named owner**.
8. Confirm no other zero axis increases.

## Out of scope for this directive

- Full 1,421-file timeout census (separate hangsafe track).
- Assertion/resource With drain until desugar-panic stableZero terms for enrolled axes are honest.
- Pinning any live Category-5 count as “baseline debt.”

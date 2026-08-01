# METHOD: and_then construction-panic mass (tip board only)

**Scope:** preparation document. No product code, no recensus, no measurement run.
**Authority board:** sole Python corpus scoreboard =
`implementations/python/sugar-lift-py-tests/scripts/control_effect_recensus.py`
artifact **`recensus.json`** (tip run; not a stale 9a ledger).

**Stale claim to kill:** “283 panics at `outcome_to_exitset` means Deferred
(`NativeOperationExitCarrierV1`).” On the stale 9a board that split was
`native=0`, `pending-contract=283`, `guarded=25` of 502 — so **Deferred was
not the mass**. Tip numbers are unknown until this method is applied to the
**tip** board.

---

## 1. When to run

Only after control_effect_recensus completes and produces a **complete** tip
`recensus.json` (denominator complete; not a partial journal). Do not fire a
second recensus to obtain it.

Input path (example):

```text
<path-to-recensus-out-dir>/recensus.json
```

---

## 2. Fields to read (board schema)

Read these **top-level** (or nested under the same keys if the floor wraps them)
arrays of row objects:

| Field | Role |
| --- | --- |
| `desugarConstructionPanics` | ConstructionPanic rows captured during desugar of corpus functions (`desugar_axis`) |
| `constructionPanics` | ConstructionPanic rows from other construction paths the recensus aggregates |

Also read for context only (not partition numerators):

| Field | Role |
| --- | --- |
| `R_desugar_construction_panics` / `R_construction_panics` | Totals; must equal `len(arrays)` if present |
| `controlEffectStableZeroTerms.desugarConstructionPanics` | Stable-zero conjuncts; do not use as the partition input |
| `desugarByCategoryOwner` / family counters | Optional cross-check of owner mass |

### Row fields used for classification

Each panic row (shape from `desugar_axis` / audit membrane) contributes:

| Row field | Use |
| --- | --- |
| `owner` | Primary dispatch key (law name). Must be a law name, not a file:line. |
| `message` | Full panic message / serialized gap (often embeds `owner=… observed=… requested=… fix=…`) |
| `where` | Desugar call coordinate (`file:line:col`); blame locus only, not partition key |

If `info` is nested (dict), prefer `info.owner`, `info.observed`, `info.requested`,
`info.fix` when top-level `owner`/`message` are thin.

**Do not** invent offenders from a hand-curated site list. Every counted row
must appear in those board arrays.

---

## 3. Universe: “and_then-related” mass

Not every board panic is and_then mass. Restrict to rows that match **live
production mouths** for exit conversion / deferred carry / pending-contract
join / guarded arm law (re-derived from tip source at measurement time by
opening the modules below and listing `construction_panic_gap` / equivalent
owners — do not freeze a checklist of corpus files).

**Modules whose panic owners define the universe** (enrollment = path exists on
the tip tree the board was measured against):

- `.../outcome/exit_set.py` — `outcome_to_exitset`
- `.../caller_parameter_contract.py` — `NativeOperationExitCarrierV1.*`, `ContractConditionalConstructionV1.*`
- `.../floor/single_outcome_law.py` — rewrap_pending / require_single_value (owner passed at call site)
- `.../floor/guarded_value.py` — guarded unpack / map arm laws

A board row is **and_then-related** if any of:

- `owner` is `outcome_to_exitset`, or starts with `NativeOperationExitCarrierV1`, or contains `ContractConditionalConstruction`, or starts with `GuardedValue`, or is a call-site owner that rewrap_pending / single-outcome used for pending/guarded joins; **or**
- `message` contains the fixed observed phrases of those mouths (below).

All other panics are **out of scope** for this partition (do not force them into
native/pending/guarded).

---

## 4. Partition rules (three buckets + other)

Apply **first matching** rule in order. Use `owner` + lowercased `message` (and
nested `info.observed` if present).

### A. `native_deferred` — Deferred / native carrier case

**Means:** undischarged native operation demand, or carrier integrity panic on
the Deferred object path.

Include if:

| Signal | Source mouth (product) |
| --- | --- |
| `owner == "outcome_to_exitset"` **and** message/observed contains `undischarged native operation demand` | `outcome_to_exitset` when `isinstance(outcome, NativeOperationExitCarrierV1)` |
| `owner` starts with `NativeOperationExitCarrierV1` | `__post_init__`, `and_then` (conflicting pre-effect state), `compose_prefix` (incompatible demands), etc. |

**Not** every `owner == "outcome_to_exitset"`: unknown outcome variants are
**other**.

### B. `pending_contract` — multi-demand / pending parameter-contract joins

**Means:** obligations that cannot share one linear carrier / join face (the
mass the stale board called “pending-contract”).

Include if:

| Signal | Source mouth (product) |
| --- | --- |
| `owner` contains `ContractConditionalConstructionV1` | `.and_then`, `.sole_demand`, … |
| message contains `pending parameter contract demand` | `rewrap_pending` / single_outcome_law drops |
| message contains `distinct pending constructions` or multi-demand fuse refusal | `sole_completed_outcome` / collapse path (if surfaced as ConstructionPanic on board) |
| message contains `no surviving face to carry` them (pending demands) | rewrap_pending empty partition |

### C. `guarded` — guarded-arm / GuardedValue laws

**Means:** incompleteness on guarded distribution, not Deferred discharge.

Include if:

| Signal | Source mouth (product) |
| --- | --- |
| `owner` starts with `GuardedValue` or contains `GuardedValue` | map / unpack / predicate arms |
| message describes arm unpack without `ScopeRebinds` / single-outcome arm violation under a guard | `guarded_value` / `require_single_value` with arm language |

### D. `other` — and_then-related but not A–C

Examples: `outcome_to_exitset` with observed “not an Outcome the exit algebra
knows” (unknown type), or related owners that match the universe but not A–C.

---

## 5. Counts to report

| Symbol | Definition |
| --- | --- |
| \(N_{\mathrm{board}}\) | `len(desugarConstructionPanics) + len(constructionPanics)` (all rows) |
| \(N_{\mathrm{related}}\) | and_then-related rows (universe filter) |
| \(R_{\mathrm{native}}\) | bucket A |
| \(R_{\mathrm{pending}}\) | bucket B |
| \(R_{\mathrm{guarded}}\) | bucket C |
| \(R_{\mathrm{other}}\) | bucket D |

Identities to check (not optional):

- \(R_{\mathrm{native}} + R_{\mathrm{pending}} + R_{\mathrm{guarded}} + R_{\mathrm{other}} = N_{\mathrm{related}}\)
- \(N_{\mathrm{related}} \le N_{\mathrm{board}}\)

Also report **top owners** within each bucket (count × owner string) so a
single mis-parse is visible.

---

## 6. Pre-committed decision rule: build Deferred or not

**Written before tip numbers exist** so the reading cannot be rationalised after
the fact (how “283 means Deferred” survived on a board that had `native=0`).

Notation (from §5): \(N_{\mathrm{related}}\), \(R_{\mathrm{native}}\),
\(R_{\mathrm{pending}}\), \(R_{\mathrm{guarded}}\), \(R_{\mathrm{other}}\).

Owner ruling (always): Deferred is typed “not yet discharged.” An undischarged
Deferred that reaches a **terminus** must still **panic**, naming demand, source
node, and failed discharger. Accept Deferred only if loud incompleteness is
preserved or increased (relocated), never silenced.

### 6.1 What Deferred is for (object, not slogan)

Deferred is the typed cell for **undischarged `NativeOperationExitCarrierV1`**
(and kin) so composition can be total **without** inventing a completed exit.
It is **not** a generic bucket for every and_then panic, and **not** the object
for multi-demand pending-contract joins or GuardedValue arm laws.

### 6.2 Thresholds (tip board, and_then-related only)

Define **native share**:

\[
s_{\mathrm{native}} = \frac{R_{\mathrm{native}}}{N_{\mathrm{related}}}
\quad (N_{\mathrm{related}} > 0);\quad
s_{\mathrm{native}} := 0 \text{ if } N_{\mathrm{related}} = 0.
\]

| Verdict | Pre-committed condition | Action |
| --- | --- | --- |
| **BUILD Deferred (slice-justified)** | \(N_{\mathrm{related}} > 0\) **and** \(s_{\mathrm{native}} \ge 1/3\) **and** \(R_{\mathrm{native}} \ge 10\) | Build Deferred for the native_deferred class only. Publish pending/guarded as separate objects. Terminus panic required. |
| **BUILD Deferred (dominant)** | \(s_{\mathrm{native}} \ge 1/2\) **and** \(R_{\mathrm{native}} \ge 10\) | Same as above; native is the primary and_then hole. Still do not claim pending/guarded are fixed by Deferred. |
| **DO NOT build Deferred as the answer to and_then mass** | \(R_{\mathrm{native}} = 0\), **or** \(s_{\mathrm{native}} < 1/10\) while \(R_{\mathrm{pending}} \ge 3 \times R_{\mathrm{native}}\), **or** \(R_{\mathrm{pending}} \ge \max(50,\, 2 \times R_{\mathrm{native}})\) with \(s_{\mathrm{native}} < 1/3\) | **Same shape as stale 9a.** Mass is pending-contract (or other). Deferred alone does not retire the bulk. Prefer pending-contract / demand-set object. Deferred may still be a small typed fix if \(R_{\mathrm{native}} \ge 1\) as a **narrow** carrier hole — see §6.3. |
| **DO NOT build Deferred at all this cycle** | \(R_{\mathrm{native}} = 0\) **and** \(N_{\mathrm{related}} > 0\) | No Deferred mass on tip. Building Deferred would not reduce and_then-related loud incompleteness. Spend the climb budget on the dominant bucket (usually pending_contract or guarded). |
| **INSUFFICIENT MEASURE** | Board missing, incomplete denominator, or \(N_{\mathrm{related}} = 0\) while board claims huge construction panic mass outside the and_then filter | **Do not decide.** Fix recognition or re-run board; do not invent Deferred size. |
| **REJECT shipped Deferred** (post-land check) | After Deferred: mid-sequence native panics drop **and** total loud incompleteness drops by that amount **without** equal terminus panics naming demand/source/caller | False green. Revert or fix terminus mouth. |

### 6.3 Plain answer: what split makes Deferred **NOT** worth building?

**Not worth building as the fix for “and_then mass” when:**

1. **\(R_{\mathrm{native}} = 0\)** on tip (stale-9a shape, or cleaner). There is no
   undischarged-native cell mass to hold. Deferred would be a type looking for a
   job.

2. **Pending-contract dominates:** \(R_{\mathrm{pending}} \ge 3 \times R_{\mathrm{native}}\)
   (or \(R_{\mathrm{pending}} \ge 50\) with \(s_{\mathrm{native}} < 1/3\)). Building
   Deferred while selling “we fixed the 283” is the same lie as 9a under a new
   name. The missing object is multi-demand / demand-set algebra, not Deferred.

3. **Guarded dominates with native ~0:** same — different object
   (`GuardedValue` / single-outcome), not Deferred.

**Is any split enough to justify Deferred independent of mass?**

**Yes, narrowly — but not as the and_then-mass story.**

- If product already has `NativeOperationExitCarrierV1` and
  `outcome_to_exitset` **must** panic on undischarged carriers, the algebra is
  already incomplete: composition is not total over a real production type.
  A Deferred Exit variant can still be justified as **making the algebra total
  over an existing type**, with terminus panic as the incompleteness mouth —
  even when \(R_{\mathrm{native}}\) is small — **provided** we do **not** claim
  it retires pending/guarded mass.

- That justification is **geometric** (total composition + honest terminus), not
  “because the board is 283.” If \(R_{\mathrm{native}} = 0\) at tip, even this
  geometric case is weak: either carriers never reach the conversion boundary
  in the corpus, or recognition is wrong. Prefer re-measure recognition before
  inventing Deferred for a zero-mass class.

**Summary one-liner:**

> **Build Deferred only if tip \(R_{\mathrm{native}}\) is a real, non-negligible
> share of and_then-related panics (thresholds in §6.2), or as a narrow
> totality fix for an existing undischarged-native type without claiming
> pending/guarded retirement. Do not build Deferred as the answer when
> \(R_{\mathrm{native}} = 0\) or pending-contract dominates — that is the 9a
> error pre-committed against.**

### 6.4 Observation table (after numbers, map to §6.2 only)

| Observation on tip board | Map to §6.2 verdict |
| --- | --- |
| \(s_{\mathrm{native}} \ge 1/2\), \(R_{\mathrm{native}} \ge 10\) | BUILD dominant |
| \(s_{\mathrm{native}} \ge 1/3\), \(R_{\mathrm{native}} \ge 10\) | BUILD slice-justified |
| \(R_{\mathrm{native}} = 0\), \(N_{\mathrm{related}} > 0\) | DO NOT build this cycle |
| pending \(\ge 3\times\) native, \(s_{\mathrm{native}} < 1/3\) | DO NOT as and_then-mass answer |
| Post-land: mass silenced without terminus panics | REJECT shipped Deferred |
---

## 7. Ladder (why this is a document, not a product type yet)

1. **Type forbid** undischarged carrier mid-sequence? Not on tip without Deferred.
2. **One door** for measurement? The board + this partition method (one scoreboard).
3. **Panic?** Product already panics; this method only **classifies** panics.
4. **Auditor/method** retained until Deferred (or pending-contract type) makes the
   wrong mid-sequence incompleteness unrepresentable; retirement = tip partition
   stable at zero for the retired class with terminus panics carrying the rest.

---

## 8. Explicit non-goals

- No second recensus from this lane.
- No product implementation of Deferred or partition code paths in this prep.
- No local pytest / no bx for this prep.
- No banking of tip \(R_*\) until the tip `recensus.json` is applied with this method.

---

## 9. Procedure checklist (when board lands)

1. Confirm board is tip (manifest / pin matches measured main).
2. Load `desugarConstructionPanics` + `constructionPanics`.
3. Filter and_then-related; partition A–D; print \(R_*\) and top owners.
4. Compare to stale 9a narrative; state whether Deferred is the bulk object.
5. Hand the numbers to the Deferred design decision; do not implement Deferred
   in the same breath as the first tip read unless \(R_{\mathrm{native}}\) warrants it.

# Path forward — living plan (owned by advisor)

**Owner:** advisor (holds joe to this sequence).  
**Tip at plan writing:** `8857e4071` (fetch before each check).  
**Doctrine:** Law of One; constructors over auditors; measurement must testify; no cowboy parallel drains without a validated sequence.

**How to use this document**

1. Execute steps **in order** unless a step is marked `PARALLEL OK`.
2. Before starting step N+1, report completion of step N to **advisor**.
3. Advisor checks **DONE-WHEN** → **PASS** or **FAIL**. FAIL means redo; do not invent a next step.
4. Work **not on this plan** is **OFF-PLAN** — say so before continuing.

**Cowboy record (truth the plan starts from)**

- Validated order was: **measure process floors + recensus → re-rank residual → product drain**.
- What happened: auth/shelf unblocks landed; recensus and sole-construction fired; **product drains (spelling / swallowed / self_sealing) ran in parallel before those receipts were banked** — luck exposed a lying parent vector, but that was luck.
- Sole-construction was **not** re-verified as a complete corpus floor set after auth until the current in-flight run.

---

## Criterion map (what DONE actually requires)

| # | Criterion | What “done” requires | Status at plan writing |
|---|---|---|---|
| **1** | Every pandas file/function on sole tree→sugar path | Complete recensus denominator: every enrolled file has a terminal; no silent skip; construction path is the board door | **Unmeasured at tip** until S1 board banks |
| **2** | R(construction panics)=R(native)=R(timeout)=R(silent/unaccounted)=0 **simultaneously** | Corpus process floors + board on **same pin** | Process floors: sole-construction; panics: recensus board |
| **3** | Source-visible constructs; source-undecidable refuses **naming** the artifact it cannot see | Split R only (below). Hierarchy-lie refusals are **not** C3 progress | Law rewritten 2026-08-02; instrument re-scope held on #6988 |
| **4** | No second mechanisms (spelling, swallow, fabricate, …) | Live parent-vector **citations** + climb to constructors where possible | Parent numbers **were unsound**; re-derive after S2 |
| **5** | Truthful **and** lying twins per semantic family | Every owned residual family has both faces; enrollment = existence | **Barely touched** campaign-wide; not optional |

---

## Measurement topology (do not forget)

| R term (criterion 2) | Instrument | CI door |
|---|---|---|
| R(native crashes) corpus | `native_crash_zero_tolerance.py` + authenticated pandas | `factory-zero-tolerance.yml` → `run_sole_construction_floors.sh` |
| R(timeouts) corpus | `timeout_zero_tolerance.py` + corpus | same |
| R(bare exceptions) corpus | `bare_exception_zero_tolerance.py` + corpus | same |
| R(construction panics) | **`control_effect_recensus.py`** (board) | `control-effect-recensus.yml` (nightly + dispatch) |
| R(silent/unaccounted) | `silent_zero_tolerance` (kit roots in orchestrator) + board denominator completeness | sole-construction + recensus |

**Discrimination workflows are not these numbers.**  
**Single CI SPOF for process floors:** sole-construction orchestrator.  
**Board was unenrolled until #6984** — root cause of July-26 product R.

**One heavy lease on the box.** Recensus and sole-construction **must not** be assumed parallel free — they serialize on the lease. Currently both in flight on `8857e4071` is acceptable only because the lease makes them take turns; do not start a third heavy.

---

## Phase 0 — Close the two in-flight measurements (NOW)

### Step 0.1 — Control-effect recensus run `30720169468`

| | |
|---|---|
| **Action** | Wait for [run 30720169468](https://github.com/TSavo/sugar/actions/runs/30720169468) to finish. Do not cancel unless lease-deadlocked. Do not start product drains. |
| **DONE-WHEN (all required)** | (1) Run `conclusion` is `success` or `failure` (not cancelled). (2) Artifact `control-effect-recensus-lease` present; lease `acquired=true` for class `control-effect-recensus`; commit matches tip measured. (3) Artifact `control-effect-recensus-board` present with recensus JSON under `.sugar/pandas-control-effect/` (or workflow path). (4) Board fields readable: `commit`/`sourceStamp`, `R_construction_panics`, `R_construction`, `R_desugar` (and owed/accounted if present), denominator complete flags. (5) If `leased_exit=75` or missing board → **FAIL** (UNMEASURED). |
| **Criterion** | 1 (denominator), 2 (construction panics), 3 (residual shape on board) |
| **Unblocks** | S2 re-rank; any ranking by panic owner mass |
| **Serial** | Waits only for this run (+ lease vs 0.2) |

### Step 0.2 — Sole-construction floors run `30720199631`

| | |
|---|---|
| **Action** | Wait for [run 30720199631](https://github.com/TSavo/sugar/actions/runs/30720199631). |
| **DONE-WHEN (all required)** | (1) Run finished (not cancelled). (2) Artifact `python-sole-construction-floors-lease` present; `acquired=true`. (3) Log shows `process-floor population: authenticated pandas corpus at …` (auth **succeeded**). (4) Axes ran for **R_native_crashes**, **R_bare_exceptions**, **R_timeouts** against that corpus (not discrimination-only workflows). (5) If auth fails again, or lease 75, or process floors skipped → **FAIL**. (6) Zero-claim gate: if any process-floor axis red, overall red is OK; if green claim without `completed/zero-findings` when claiming R=0 → **FAIL**. |
| **Criterion** | 2 (three process terms) |
| **Unblocks** | Simultaneous-zero reading of criterion 2 (with 0.1) |
| **Serial** | Same tip; may queue behind 0.1 on heavy lease |

### Step 0.3 — Bank tip measurement package

| | |
|---|---|
| **Action** | Download both artifacts; store board + floor lease under a tip ledger path (e.g. `docs/ledgers/` or `.receipts/tip-8857e4071/`) **or** attach CI artifact URLs + SHAs in this file’s **Ledger** section. Prefer a small PR that **commits the board JSON** if policy allows (historical boards live under `docs/ledgers/`). |
| **DONE-WHEN** | Advisor can open a board JSON for `8857e4071` (or successor tip if rebased) with the fields in 0.1(4) **and** a written triple of process-floor R (native/bare/timeout) from 0.2. CommitMeasurement gate, if used, is CompleteVector for tip-owed axes **or** explicit Partial with reasons. |
| **Criterion** | Measurement integrity; enables 1–3 |
| **Unblocks** | Phase 1 |
| **Serial** | After 0.1 and 0.2 both PASS |

**If either 0.1 or 0.2 FAIL:** stop product work. Fix measurement only (auth, shelf, lease, unevictable cells). Re-dispatch **one** heavy at a time.

---

## Phase 1 — Re-derive residual ranking (parent vector was lying)

### Step 1.1 — Live parent-vector / child instruments at tip

| | |
|---|---|
| **Action** | Run **only** the Model A parent (or each child) on tip tree as **CI already does** or a single workflow_dispatch — **not** nine bx jobs. Record live R per axis from child instruments (self_sealing, swallowed, spelling partition, fabricated, nameless, two_producers, soft-skip, etc.). |
| **DONE-WHEN** | Table: axis → live R → child owner module → receipt/log URL. **Discard** R_total=208 / self_sealing=94 / swallowed=79 as planning inputs. |
| **Criterion** | 4 (second mechanisms) |
| **Unblocks** | 1.2 drain order |
| **Serial** | After 0.3 |

### Step 1.2 — Rank product drains from **live** R + board owner mass

| | |
|---|---|
| **Action** | Produce ordered drain list: (a) board `desugarConstructionPanics` / construction panic owners from S0.1; (b) live second-mechanism children with R>0. Prefer **constructor climbs** over new auditors. |
| **DONE-WHEN** | Ranked list checked into this file under **Ledger → Active ranking** with date and tip SHA. |
| **Criterion** | 2 + 4 |
| **Unblocks** | Phase 2 |
| **Serial** | After 1.1 |

---

## Phase 2 — Product drain (serial by default)

**Rule:** one drain shot at a time unless marked PARALLEL OK.  
**Each drain PR must state:** R axis, Epsilon R, floors, **shell deleted**, climb vs permanent membrane.

### Step 2.1 — First product shot from live ranking

| | |
|---|---|
| **Action** | Execute **only** the #1 residual from 1.2 (likely: top board panic owner **or** largest live second-mechanism child — **not pre-judged**; ranking decides). |
| **DONE-WHEN** | PR merged; live child R drops as predicted **or** honest reattribution; board delta on next recensus if panic-owner (may be S3). Twin pair present. |
| **Criterion** | 2 and/or 4 |
| **Unblocks** | Next ranked residual |
| **Serial** | Yes |

### Step 2.2 — Subsequent drains

| | |
|---|---|
| **Action** | Next residual on the live ranking. |
| **DONE-WHEN** | Same as 2.1 for that axis. |
| **PARALLEL OK** | Only if two shots touch **disjoint** packages **and** advisor has checked join (no shared `lift_rpc` / `exit_set` / `and_then` collision). Default **serial**. |

### Residual locators (155) and idd walls (2)

| Item | When |
|---|---|
| **155 residual positional `parents[N]`** in tests/scripts/tools | **After Phase 0–1**, **before** large product refactors that touch test harness layout. Not blocking process-floor corpus R. Blocks **criterion 5** twin reliability if tests resolve wrong roots. → **Step 2.L** |
| **2 remaining idd walls** | **After** live ranking; only if they are on the critical path of a ranked residual or block measurement. Otherwise **after** first board-ranked panic drain. |

### Step 2.L — Positional locator residual (155)

| | |
|---|---|
| **Action** | Drain remaining `parents[N]` layout arithmetic via repo-root resolve door (#6978 family) in tests/scripts/tools. |
| **DONE-WHEN** | Named residual count instrument green (0) or honest permanent exceptions listed; no new parents[N] without enrollment. |
| **Criterion** | 5 (twins must resolve the tree they claim); measurement integrity |
| **When** | After 0.3; **PARALLEL OK** with 1.1 if no heavy lease contention |

---

## Phase 3 — Criterion 1 and 5 (half of DONE — not optional garnish)

### Step 3.1 — Criterion 1 proof from board

| | |
|---|---|
| **Action** | From banked recensus: every enrolled file has exactly one terminal; incomplete denominator = red worklist; map missing path classes to owners. |
| **DONE-WHEN** | Written worklist: file-terminal gaps = 0 **or** ranked list of incomplete terminals with owners; no silent population shrink. |
| **Criterion** | **1** |
| **Unblocks** | Knowing whether “sole path” is structural or still a hole |
| **Serial** | After 0.3 |

### Step 3.2 — Criterion 5 twin census

| | |
|---|---|
| **Action** | For each **live residual family** on the ranking (and each new Sugar/floor climb), require truthful + lying twins; enrollment = existence (catalog test or family registry). |
| **DONE-WHEN** | Table: family → truthful twin path → lying twin path → missing. Missing twins = R_twins > 0, red. |
| **Criterion** | **5** |
| **Unblocks** | Drain PRs that would otherwise ship one face only |
| **Serial** | Start after 1.2; **PARALLEL OK** with 2.x only for families not under active drain |

---

## Phase 4 — Simultaneous zero (criterion 2 endgame)

### Step 4.1 — Same-pin simultaneous read

| | |
|---|---|
| **Action** | On one tip: complete sole-construction process floors **and** recensus board (dispatch if needed). |
| **DONE-WHEN** | Single pin where native=bare=timeout=0 **and** construction_panics=0 **and** silent/unaccounted conservation holds — or explicit non-zero vector with no silent zeros. |
| **Criterion** | **2** |
| **Serial** | After drains that claim to lower those axes; re-measure after each major panic-owner drain |

### Step 4.2 — Stable zero hold

| | |
|---|---|
| **Action** | Next nightly recensus + next main sole-construction both hold zero (or R only on permanent membranes with named retirement). |
| **DONE-WHEN** | Two consecutive boards / floor sets with stable zero terms; Delta R = 0, Epsilon R = 0. |
| **Criterion** | **2** stable |

---

## Criterion 3 — R split (law; do not collapse)

**Criterion text:** Source-visible behaviour CONSTRUCTS; source-undecidable behaviour is specifically refused, **naming the artifact it cannot see** — not fabricated, not soft-failed.

### The confusion that almost banked defects as progress

#6988's AST naming auditor (`R_refusals_naming_nothing`) only checks that `observed` interpolates a type/path. **Naming a type is not the same as being legitimately undecidable.** Brown's post-campaign board: **~159 of 169** defect rows were **hierarchy lies** (wrong type/identity checks), not honest source-undecidable refusals. That auditor would have greenlit those lies as good C3 refusals. One unpark away from counting our own defects as criterion progress.

#7022 sealed grounds (`RefusalDecidability`) climb past the prose auditor for axis-1 shape — but the default ground **`KitConstructionIncomplete.holds()` is always True**, so an honest kit gap and a type-hierarchy bug still mint identically. The default erases the distinction the criterion exists to measure.

### Two R axes (never one number)

| Axis | What counts | Drains by | C3 finality? |
|---|---|---|---|
| **`R_kit_incomplete`** | Mints whose sealed ground is `KitConstructionIncomplete` (OUR missing sugar/floor arm, or a false arm that should not exist) | Write the sugar/floor **or** prove a hierarchy lie and **delete the false arm** | **No** |
| **`R_source_undecidable_refusals`** | Mints with **runtime** sealed grounds that `holds(world)`, **plus** residual classes enrolled as honestly undecidable (today: CM resolution gaps; others only when enrolled) | Produce the missing artifact when source decides it, or keep the named refusal with a ground that still holds | **Yes** — this is C3 |

`R_refusals_over_decidable_source` (mint where `holds(world)` is false) remains a **measurement floor**, not a progress counter to lower by softening refusals: those mints must not exist.

### Unrepeatable rule

> **A refusal that exists because a type was wrong is a defect wearing a refusal.**
> It drains by **fixing the type** (hierarchy / identity / membrane), **never** by improving the prose.

Hierarchy-lie drains (brown's 152–159 class) are **type-ladder work**. They must not enroll as C3 progress when the refusal message is renamed.

### Missing door (makes C3 measurable)

CM resolution residuals currently have nowhere honest to land: derivation returns `ContextManagerResolutionGapV1`, but panic/SNW defaults to `KitConstructionIncomplete` — same bucket as bugs.

**New sealed ground (named; enroll in `sealed_ground.py`):**

| Member | Artifact | `holds(world)` | Why not kit-incomplete |
|---|---|---|---|
| **`EnrolledDemandUnresolved`** | `EnrolledDemandArtifact`: `demand_family` (e.g. `context-manager`), `demand_cid`, `use_site`, `gap_kind` (structural key from the resolution table), `expected_ref_type` (e.g. `ContextManagerContractRefV1`) | True iff the enrolled demand is still a **gap**, not a contract ref, in the resolution world at mint | Machinery **ran**; the enrolled demand has **no source-derived ref** after derivation. That is exhaustion of source-derived resolution, not a missing `match` arm on AST |

Until CM (and sibling) residuals mint this ground, **C3 is re-scoped on paper only** — residual mass still collapses into `R_kit_incomplete`.

**If.substitute class:** default residual is `R_kit_incomplete` (carry `branch_result_slot` through substitute). Enroll under `R_source_undecidable_refusals` only if, after the carry law exists, something still severs authenticated identity for undecidable reasons — then name that artifact with a runtime ground, do not leave it as kit-incomplete prose.

### Disposition of #6988

Advisor holds. Axis-1 AST shell **superseded** by #7022. Do not merge as the C3 instrument. See PR comment on #6988 for full finding.

---

## Standing rules (advisor enforces)

1. **No product drain PR** until Phase 0 PASS (unless already landed — those are done; do not open new ones until 0.3).
2. **One heavy measurement at a time** beyond the two already in flight; after they finish, serial heavy only.
3. **No local pytest; no bx unless assigned** — CI main-push / enrolled workflows are the path.
4. **Never `gh run list` for attendance** — `gh api --paginate`.
5. **Never pipe then `$?`.**
6. **Parent vector 208 is dead** as a plan input until 1.1.
7. **Off-plan work:** advisor says **OFF-PLAN** before any celebration.
8. **Criterion 3:** never count hierarchy-lie refusals or bare `KitConstructionIncomplete` renames as C3 progress; only `R_source_undecidable_refusals`.

---

## Top three steps (execute now)

1. **S0.1** — Finish recensus `30720169468`; bank board artifact (DONE-WHEN above).  
2. **S0.2** — Finish sole-construction `30720199631`; bank process-floor R triple (DONE-WHEN above).  
3. **S0.3** — Package tip measurement (board + floors + optional CommitMeasurement); only then **S1.1** live re-rank.
   - **S1.1 input format (empty of numbers):** `tools/rerank_input.py` — each axis is MeasuredAxis(value, instrument+commit+body) or UnmeasuredAxis; bare chat integers unconstructible. Do not populate until live re-derivation.
   - **REQUIRED:** board JSON (S0.1) + process-floor R triple native/bare/timeout (S0.2).
   - **OPTIONAL:** `CommitMeasurement` via `tools/compose_commit_measurement.py` — **may be PartialVector** (unmeasured axes expected if package suite has not spoken). Do **not** use `commit_measurement_gate --require-complete` for S0.3 packaging.
   - Ready command (run only after S0.1/S0.2 receipts exist; do not contend in-flight runs):
     `python3 tools/compose_commit_measurement.py --commit "$SHA" --receipts-dir receipts/ --output commit-measurement.json`

---

## Ledger (update in place)

| Date | Tip | Event | Advisor verdict |
|---|---|---|---|
| 2026-08-01 | `8857e4071` | Plan v1 written; runs 30720169468 + 30720199631 in_progress | — |
| | | Parent R_total=208 retired as planning input | — |
| 2026-08-02 | tip | C3 R-split law + `EnrolledDemandUnresolved` door named; #6988 finding posted (not closed); hierarchy-lie ≠ C3 progress | advisor disposition of #6988 |

### Active ranking

*(empty until S1.2)*

### Banked tip measurements

*(empty until S0.3)*

---

## Shell this document deletes

**Cowboy sequencing** — ad-hoc parallel drains and unvalidated “next shots” without DONE-WHEN artifacts.  
Not a product shell; a **process** shell. Advisor owns the ratchet: completions checked against this file.

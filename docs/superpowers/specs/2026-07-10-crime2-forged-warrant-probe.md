# Probe: Crime 2 detector (forged warrant) — 2026-07-10

**Issues:** #4016 (Minority Report epic, two-crimes comment), #4013 (liftCoverage), #3809 (substrate).
**Status:** PROBE ONLY — no build. Design seam flagged.

Main HEAD at probe: `ca73f553e` (#4018 implication prove-then-feed) + #4015 liftCoverage dual-axis.

---

## 0. The two crimes (from #4016 comment)

| Crime | Shape | Meaning | Measured? |
|-------|--------|---------|-----------|
| **1** | `stated → ∅` | Vendor assertion → no fact and no dig | **Yes** — `silently_unaccounted` (#4015) |
| **2** | `dig → literal \| effect, ⊥ stated` | Dig floors to ground with no assertion warrant | **No** — this task |

Law: every dig must trace to a stated assertion; literal/effect floor only under that warrant.

Not a crime: voiceless body (no claim, no dig) — stays Minority Report.

---

## 1. Where a “dig” happens

### Trigger (assertion WARRANTS dig) — by design

`literal_call_report._lift_assert` (docstring is the law in code):

1. **THE FACT** — mint EUF obligation `eq(call:callee(args), expected)` from the assert.
2. **THE DIG** — resolve `callee`’s contract because the fact debt warrants it.
   - Source present → continue into body (`_construct_callsite_from_factory_term` / `_function_universe` / `_dig_universe`).
   - Source absent → imported `.proof` is a memoized dig.

Call chain (assertion path):

```text
_lift_assert(stmt)
  → _construct_callsite_from_factory_term(...)   # dig + floor spine
       → mint_universe / _function_universe / BridgeStrategy body walk
       → force_floor(CallSiteValue, dig_sink=...)
            → OpaqueOpCallsite.computed → literal floor
            → DictLiteralValue → literal floor
            → RuntimeEffect / dig-boundary → effect or refuse
  → _lift_callsite_assertion(...)               # stated fact
```

Nested digs: `ReduceContext.dig_sink` / `CallSugar.BridgeStrategy` append transitive callees while reducing; still under the assertion-started floor.

### Floor into a **literal**

Primary spine: `force_floor` (`floor/call_site_value.py`) from `_construct_callsite_from_factory_term` (~3047).

Concrete products:

| Floor outcome | What is emitted | Warrant stamp today |
|---------------|-----------------|---------------------|
| `OpaqueOpCallsite` + `computed` | Companion `call:op(...) == N` + projected `A() == N` | `Derived(floor_chain=("builtin-operator:…",))` etc. |
| `DictLiteralValue` | Dict literal projection path | Derived / callsite floor chains |
| numpy ufunc integer/float floors | Derived facts | `Derived(floor_chain=("literal_call_report.numpy_*",))` |
| closed strip / urlsafe special universes | function-contract posts with literal alphabets | often `Derived(floor_chain=("body-universe-declaration",))` |

### Floor into an **effect**

| Path | Shape |
|------|--------|
| Assertion shapes that cannot become static formulas | `RuntimeEffect` / `AssertionRuntimeEffect` |
| Digger declines tower | `DigBoundary` → diagnostic `kind: dig-boundary` (`factory/dig_boundary.py`) |
| Operations that refuse floor | typed effects via `force_dunder_floor_or_runtime_effect`, etc. |

`DigBoundary` fields: `callee`, `blame`, `caught`, `reason` — **no assertion locus**.

---

## 2. What provenance a dig carries today

### First-class types (`proofir/nodes`)

- `Stated(locus: ConstructionSite)` — vendor/source claim locus.
- `Derived(floor_chain: tuple[str, ...])` — computed projection; chain is a *how*, not a *who asserted*.
- `Provenance { node_class, construction_site, warrants }` — required non-empty warrants.

### What dig products actually stamp

| Product | Typical warrant | Is it “warranting assertion”? |
|---------|-----------------|-------------------------------|
| Digged function-contract universe (`_dig_universe`) | `Stated(return_stmt_frag)` — **body return line** | **No** — body return ≠ vendor assert that triggered dig |
| Body-universe declaration | `Derived("body-universe-declaration")` | **No** — no assert locus |
| Opaque computed companion | `Derived("builtin-operator:…")` | **No** — floor_chain only |
| DigBoundary diagnostic | none (not a Provenance node) | **No** |

### Control-flow truth (not reified)

Dig **starts** only because `_lift_assert` opened the debt. That warrant is **implicit in the call stack**, not written onto dig IR / diagnostics / coverage.

### What #4015 liftCoverage sees (minority)

A body is *dug* if:

1. an on-disk assert falls inside its span, **or**
2. report names it (`sourceFunctionName` / dig-boundary `callee`),

then `un_asserted = present − dug`.

That is **scope**, not Crime 2:

- Does not require dig → floor(literal|effect).
- Does not require dig → **warranting assertion** identity.
- A body can be “dug” via report-name/dig-boundary without proving a grounded literal under a stated claim.

`liftCoverage` **does not** walk dig floor chains or Provenance warrants at all.

---

## 3. Is Crime 2 detectable with existing provenance?

### Verdict: **Not soundly — dig→warranting-assertion thread is missing**

| Need for Crime 2 | Present? |
|------------------|----------|
| Enumerate digs | Partial — dig-boundary diags + digged contracts + Derived floor companions (scattered) |
| Know dig floored to **literal** | Partial — only if you recognize Derived floor_chain / OpaqueOp companion shapes; no single `digFloor: literal` tag |
| Know dig floored to **effect** | Partial — dig-boundary + RuntimeEffect rows; effect may not be labeled as dig-floor |
| Trace dig → **stated assertion that authorized it** | **NO first-class field** |
| Coverage report field for forged warrants | **NO** |

Implicit “all digs come from `_lift_assert`” is **not** an instrument:

- It is not on the report.
- Nested dig_sink / special universes / future entry points can dig without that stack frame.
- A detector that assumes “call stack always ok” cannot bad-twin-inject a forged warrant as a **measured report field** without faking lift internals.

Heuristic link (co-locate Derived floor with any assert on the same line / same callee name) is **invented correspondence** — fabrication-adjacent, not carried == checked.

### Concrete missing seam (name this)

**`dig → warranting-assertion` provenance thread**

Must reify, at dig emission, something equivalent to:

```text
DigOutcome {
  dig_site,                 # callee / body locus
  floor: Literal | Effect | Coordinate | Refusal,
  warranting_assert: Stated(locus) | None,   # ← MISSING
}
```

Attach at least to:

1. **Successful dig floors** — when `force_floor` / companion emits a **literal** Derived fact, or dig emits an **effect**.
2. Optionally **DigBoundary** — `warranting_assert` for refused digs (out of Crime 2 shape, but same thread).
3. **liftCoverage / report** — consume the thread:  
   `forged_warrant = dig floor ∈ {literal, effect} ∧ warranting_assert is None`.

Without (1)+(3), a Crime-2 line item in `sugar lift --report` either:

- hardcodes 0, or  
- guesses linkage from names/lines.

Both violate the campaign’s “never fabricate / measured not hardcoded” teeth.

---

## 4. Where the seam sits (files)

| Layer | File / symbol | Role |
|-------|----------------|------|
| Assert → dig law | `factory/literal_call_report.py` `_lift_assert` | Starts dig; does not stamp assert onto dig products |
| Dig + floor spine | `_construct_callsite_from_factory_term`, `force_floor` | Produces literal floors / effects |
| Dig refuse | `factory/dig_boundary.py` `DigBoundary` | No assert field |
| Provenance algebra | `proofir/nodes` `Stated` / `Derived` / `Provenance` | Exists but dig uses body-Stated or Derived-only |
| Coverage instrument | `idd/lift_coverage_accounting.py` | Crime 1 majority; minority scope only |
| Report wire | `lift_rpc` → `liftCoverage` → CLI `cmd_lift.rs` | No Crime 2 axis |

**Recommended stamp point (when unblocked):** at the moment dig floor emits a literal or effect under `_construct_callsite_from_factory_term` / `_opaque_op_companion_facts` / effect lift — pass through the **assert `stmt` ConstructionSite** as a `Stated` warrant **in addition to** any Derived floor_chain. Then accounting is a pure report partition (mirror #4015).

---

## 5. What would NOT be enough

- Extending minority `dug` only — does not distinguish floor-to-literal vs coordinate-only vs refuse.
- Ratcheting dig-boundary count — refuse ≠ forged ground.
- Assuming call-graph invariant without report field — no bad-twin flip on the report.

---

## 6. Probe verdict

| Question | Answer |
|----------|--------|
| Dig path found? | Yes — assert-warranted dig into body; floor via `force_floor` / companions / effects |
| Floor literal / effect sites? | Yes — named above |
| Dig → assert link reified? | **No** |
| Crime 2 detectable today? | **Not soundly** |
| Design seam? | **`dig → warranting-assertion` provenance on dig floor products + coverage consumer** |
| Action | **STOP** — do not build detector on invented linkage; do not guess stamp shape in proving core without ruling |

---

## 7. Decision needed to proceed (T)

1. **Reify thread in lift emission** (recommended): dig floor products carry `Stated(assert_locus)` (or `warrantingAssert` field on dig diagnostics/facts); then Crime 2 detector is pure report accounting + ratchet + bad-twin (inject dig floor with assert stripped / null warrant).
2. **Report-only heuristic** (weaker): forbid unless T accepts name/line co-location as temporary law (I do **not** recommend — fails “never fabricate”).
3. **Static lifter audit** (different instrument): prove every dig call site is under `_lift_assert` — does not measure forged *grounds* in the report artifact.

Default recommendation: **(1)** then mirror #4015 shape (`forged_warrant_count`, `forged_loci` with file:line, RED if > 0, bad-twin inject).


---

## 8. FROZEN DESIGN (T ruling 2026-07-10) — build this

**Reject** report-only heuristics. Soundness detector = definition made mechanical.

### Stamp

- At dig-floor emission (`_construct_callsite_from_factory_term` / companions / effect lift),
  record a **dig-floor** event with:
  - `floor`: `literal` | `effect`
  - floor locus (file:line)
  - `warrantingAssert`: assert ConstructionSite when dig runs under an assertion, else **absent/null**
- Stamp is **report-side dig-floor provenance** (diagnostics / coverage), **not** a mutation of
  FOL/EUF fact content that would change contract CIDs or sat/unsat rows.
- Floor grounded under assertion → carries that assert's locus.
- Floor with no assertion in provenance → `warrantingAssert: null` → **Crime 2**.

### Detector (mirror #4015)

- `sugar lift --report` line items: `forged_warrant` count + un-warranted floor loci (file:line).
- Ratchet: `forged_warrant == 0`, RED with file:line when > 0.
- Axis lives on `liftCoverage` (alongside majority/minority).

### Teeth

- Bad-twin: inject dig-floor with no warranting assert → count > 0 RED.
- Properly grounded floor under assert → not flagged.
- Remove inject → green.

### Non-goals

- Do not invent co-location heuristics.
- Do not change verdict sat/unsat for existing corpus (stamp is additive report field).


# Measurement machinery — architectural audit (advisor)

**Date:** 2026-08-01 (tip context: S0.2 re-fire `30727525884` on `522197e93`)  
**Trigger:** T — *"audit it and think through what it really should be doing… I don't think it should be doing what it's doing at all."* Plus: *"why is it writing one suite report? Isn't that the problem?"*  
**Status:** Orientation for redesign. Not a PASS on S0.2. Not merge authorization.

---

## 1. What we actually need

For a given tip SHA `T`, the product questions are:

| Question | Criterion | Output shape |
|---|---|---|
| What is true about the **authenticated corpus** (process floors: native / bare / timeout; silent / unaccounted)? | 2 | Axis readings with population pin |
| What is true about **construction / board residual** (panics, desugar, denominator complete)? | 1–3 | Board body from sole authority |
| What second-mechanism residual remains (self-seal, swallow, spelling, …)? | 4 | Per-axis bodies under declared scope |
| Did the **kit test universe** exercise, with identity (which source + which env + which inputs)? | CI confidence | Per-test or per-shard verdicts + identity |
| For any number claimed bankable: is it **Measured** or **Unmeasured**? | integrity | Third value; never silence-as-zero |

Nothing in that list requires:

- a single mutable `suite-report.json`
- a machine-wide flock held by a one-core pytest for three hours
- every measurement peer to share one “heavy” mutex
- merge-to-main to enqueue N superseded tip measurements

Everything in that list requires:

- **identity binding** (commit, source stamp, env/input universe)
- **declared population** (corpus pin and/or `ScanScope`)
- **body artifacts that are content-addressed**
- **enrollment / roll call** so absence is Unmeasured, not green
- **compose** of owed axes into CompleteVector | PartialVector

---

## 2. Derive the shape (target)

### 2.1 One law

```
MeasurementReceipt = {
  tip,                    # commit SHA
  axis_id,                # enrolled name (not "lease class")
  status,                 # completed/findings | completed/zero | unmeasured | cancelled-before | …
  identity,               # sourceStamp, envHash, testExtraInputHash as applicable
  population,             # ScanScopeRecord | authenticated corpus pin | "kit-tests"
  body_cid,               # h(report bytes) — or absent iff status is unmeasured/cancelled
  producer_id,            # run id / job id / shard id (event metadata, not identity)
}
```

```
TipVector(T) = compose( enrolled_axes(T) ↦ lookup(receipt) )
  → CompleteVector | PartialVector
  Measured only if body_cid + identity + population present
  Unmeasured(reason) is a value, not zero
```

Completeness is **enrollment roll call**:  
`R_attendance = |owed_axes \ axes_with_valid_receipt|`  
not “did this class take a flock.”

### 2.2 Two producer kinds (not one “heavy”)

| Kind | Examples | Parallelism | Host mutex? |
|---|---|---|---|
| **A. Identity-bound kit telemetry** | package suite shards, discrimination twins, identity-gate teeth | Default **parallel**; per-shard content-addressed reports | **No** measurement lease |
| **B. Corpus / board instruments** | process floors, walls, control-effect recensus | Parallel **if** isolation holds; else schedule only true contenders | **Maybe** resource isolation — not a universal flock |

Kind A and Kind B are not peers. Kind A must never serialize Kind B.

### 2.3 Completeness without aggregation writers

T’s cut is load-bearing: identity proves *which* universe; it does **not** require *one* report.

- Each shard/job writes **its own** identity-bound body → `body_cid = h(body)`.
- A tip-level “suite complete” claim is: **every enrolled shard/node has a receipt**, proved by roll call — the same machinery as attendance, not by merging N files into one mutable aggregate.
- Human summary boards are **pure functions of receipts** (compose), recomputable, never a live shared file contending writers protect with a mutex.

That is `h = h(p)` applied to measurement: the report *is* its address; there is no hub.

### 2.4 When is any mutex legitimate?

Only when two Kind-B producers **genuinely cannot share** the same host resources without corrupting each other’s measurement (same corpus working tree mutation, same solver port, thrashing the same disk image into non-reproducible timings, etc.).

Even then the right tools are, in order:

1. **Isolation** (separate workdirs, content-addressed corpus pins, separate runners).
2. **Narrow resource leases** (corpus-cache lock, not “all measurement on this kernel”).
3. **Last resort:** serialize only the proven contender set.

A global “heavy measurement lease” for every long job is not (1)–(3). It is a compensation for treating “long” and “authoritative” as one class, and for a singleton report writer.

---

## 3. What exists today (causal chain)

```
one suite-report.json (mutable aggregate)
  → one writer / one process (unsharded pytest)
    → serialization of the suite itself
      → “protect the box while the suite runs”
        → machine-wide heavy lease
          → every Kind-B floors/recensus/wall waits
            → three-hour starvation on 1/32 cores
```

GitHub concurrency eviction was a *real* prior defect. Splitting “preserve every run” (no concurrency group) from “serialize on box” (flock) fixed *eviction*. It then **expanded the flock’s claimant set** to include the suite, walls, floors, recensus — so the cure for dropped runs became the cause of never-running floors.

Secondary amplifiers (real, not root):

- Push fires **two** Kind-mixed claimants (suite + floors) per merge.
- No tip-supersede: superseded SHAs lease-wait for hours.
- 4h lease timeout × deep queue ⇒ mass exit 75 / UNMEASURED.
- Attendance roster keys off **lease class**, so “spoke” means “held the flock,” not “produced a body about T.”

---

## 4. Mechanism-by-mechanism judgment

### 4.1 Identity gate — **load-bearing law, wrong singularity**

**Survives as law:** a measurement without commit / sourceStamp / env / input universe is not authoritative. Unavailable markers must not pass truthiness. Conservation of collected↔verdicts is real.

**Wrong shape:** one gate on one `suite-report.json`.  
**Right shape:** every producer body is identity-bound; the gate is a pure function `body → R_identity`; enrollment requires each enrolled producer to pass.

**Today’s merges:** identity teeth/twins are good. Do not abandon them when killing the singleton.

### 4.2 Scan scope / population seal (#7001, #7002, #6998) — **load-bearing, keep climbing**

**Survives.** `R` without population is unconstructible. Self-exclusion and auth-pin exclusion are correct structural seals for product scans. Silent default roots are the same class of defect as silence-as-zero.

**Not a substitute for** lease or attendance. Orthogonal axis: *what was measured*, not *whether something ran*.

**Do not widen** exclusions to “all instruments” without closed enrollment and root discipline first (prior ruling stands).

### 4.3 Attendance / roll call — **load-bearing concept, wrong key**

**Survives as concept:** silence ≠ clean floor; `R_attendance = |owed \ attended|`; cadence split per-commit vs nightly is correct (do not sum moods).

**Wrong key:** attended ⇔ lease receipt with `acquired=true`.  
**Right key:** attended ⇔ **valid MeasurementReceipt with body_cid (or explicit Unmeasured body)** for that tip and axis.

Lease-gated attendance makes “took the mutex” the definition of “measured,” which is circular and will fight lease removal.

### 4.4 Machine-wide heavy lease — **mostly accidental; not the architecture**

**What it correctly encodes:** “a timing number taken beside another census is not a measurement” *when true resource interference exists*; exit 75 rather than false concurrent R; kernel-released lock; status vocabulary (lease-waiting vs completed/zero-findings).

**What it incorrectly encodes:** suite ∈ heavy; walls/floors/recensus/suite are one mutex peer set; Measured requires flock receipt; “heavy” is a real ontology.

**T is right** that the suite must not live under this.  
**Inference I refuse:** “no mutex anywhere.” Kind-B corpus instruments on one self-hosted box may still need isolation or a *narrow* scheduler — proved by resource conflict, not by roster membership.

**Target:** lease either **evaporates** (isolation) or **shrinks** to an explicit contender set of Kind-B jobs, never Kind A.

### 4.5 “Heavy class” — **artifact of the mutex, not a natural kind**

Today: heavy = on `HEAVY_ROSTER` = takes the flock.  
That is not a category of *what we need to know*; it is a category of *who we decided to serialize*.

Replace with:

- enrolled **axes** (product R terms, process floors, board)
- enrolled **kit shards** (CI telemetry)
- **cadence** (per-tip vs nightly window)
- **resource class** only if isolation fails (optional, late)

### 4.6 CommitMeasurement — **load-bearing compose idea; lease coupling is wrong shape**

**Survives:** cite-only; `SCOREBOARD_AUTHORITY = False`; `Measured | Unmeasured`; Complete vs Partial; forbid inventing board axes; body_cid + value path.

**Wrong shape:** `Measured` requires `lease_receipt_cid` as a first-class seal. That freezes the flock into the type system. After suite leaves the lease (and after shards multiply), correct seal is:

```
Measured requires: body_cid + measurement_receipt_cid + identity + population
```

where `measurement_receipt` proves the producer ran (run/job metadata + status vocabulary), **not** that it held `/…/heavy-measurement.lease`.

Be willing to revise today’s CommitMeasurement field names in a follow-on — better now than defending lease-in-the-type.

### 4.7 Sole-construction orchestrator script — **mixed**

**Survives:** one pinned tip; authenticated pandas population; all permanent axes run (`if: always` semantics); R>0 ⇒ red; process floors not discrimination-only.

**Wrong coupling:** “one lease interval so axes cannot interleave” is a host-scheduling concern, not a semantic one. Semantically: same tip + same corpus pin + all axis receipts present. Axes **may** be separate CI jobs with content-addressed bodies; compose + enrollment replace the flock-as-pin.

### 4.8 Push triggers (suite + floors on every main push) — **harmful under merge rate**

**Real need:** tip `T` that we intend to bank gets Kind-B measurement.  
**What we built:** every merge enqueues suite + floors on that SHA; no supersede; queue of superseded tips.

**Target:**  

- Kind A (suite shards): free to run on push (no measurement lease).  
- Kind B (floors/recensus): prefer **tip-supersede** (cancel waiters for older SHAs), or dispatch/campaign control; freeze merges during Phase-0 remains operational belt.

---

## 5. What survives / accidental / compensatory

| Piece | Verdict |
|---|---|
| Identity binding + gate law | **Survives** (apply per producer) |
| ScanScope / refuse empty roots / silent seal | **Survives** (keep climbing) |
| Unmeasured ≠ zero; status vocabulary | **Survives** |
| Attendance as roll call | **Survives** (rekey off receipts/bodies) |
| CommitMeasurement as compose | **Survives** (drop lease-as-Measured seal) |
| Board SCOREBOARD_AUTHORITY single producer | **Survives** |
| Auth corpus pin / env identity | **Survives** |
| Single suite-report.json | **Kill** — shared identity hub |
| Unsharded suite on global lease | **Kill** |
| Universal heavy peer set | **Kill** |
| GitHub concurrency group as serializer | Already killed (correct) |
| Machine-wide flock as architecture | **Compensatory** — shrink or evaporate |
| “Heavy class” ontology | **Accidental** |
| Push→two heavies without supersede | **Compensatory/harmful** |
| Lease-waiting 4h as “measurement attempt” | **Compensatory** — cancel-for-requeue is honest |

---

## 6. Things merged or sealed recently — keep or revise

| Item | Judgment |
|---|---|
| #7002 InstrumentScanScope | **Keep** — population is meaning |
| #7001 silent seal / require explicit roots | **Keep** |
| #6998 MeasuredAxis needs scope | **Keep** for product axes |
| #6997/#7000 env-auth | **Keep** — wrong population was a real crime |
| Identity gate on suite-report | **Keep law, migrate artifact** to per-shard bodies |
| CommitMeasurement lease_cid requirement | **Revise** when lease leaves universal path |
| Attendance HEAVY_ROSTER including package-suite | **Revise** — suite is not a corpus peer |
| Expanding “everything long” onto the lease | **Wrong direction** — today’s starvation |

Hearing that CommitMeasurement’s lease seal and the heavy roster peer-set are wrong shapes is better **now** than defending them through S1.

---

## 7. Redesign order (aligns T WHAT + advisor WHEN)

Still under freeze until S0.2 banks (or release):

1. **mr_black (b):** package-suite **off** measurement lease; lease remains only for true Kind-B contenders until isolation exists.  
2. **mr_black (a) / T:** per-test or per-shard **CI jobs**, each with identity-bound body; completeness by **enrollment roll call**, not merge-N-into-one.  
3. **Rekey attendance** to MeasurementReceipt/body, not flock acquired.  
4. **Revise CommitMeasurement** Measured seal: measurement receipt + body, not heavy lease.  
5. **Tip-supersede** for Kind-B push storms (or keep merge freeze during campaigns).  
6. **Only then** ask whether Kind-B needs any host mutex; prefer isolation.

Do **not** strip floors/recensus/walls from all coordination by slogan. Prove isolation, then delete the lock.

---

## 8. One sentence

**The product is a tip-indexed enrollment of content-addressed, identity-bound, population-scoped axis receipts, composed into Measured|Unmeasured vectors; the machine-wide lease and the singleton suite-report are scaffolding that grew around a shared mutable hub and should not be the architecture.**

---

## 9. S0.2 note (this document does not judge the run)

S0.2 re-fire `30727525884` @ `522197e93` remains the only in-flight heavy. This audit costs no lease. DONE-WHEN for that run is unchanged in `docs/path-forward.md` §0.2.

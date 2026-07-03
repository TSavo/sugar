# Temporal Floor Campaign — Phase 3: the name-time algebra by construction

> **For agentic workers:** This is a CAMPAIGN plan, not an implementation patch. The
> coordinator dispatches slices ONE AT A TIME from current main. Instruments come
> before drains, every slice is red-first, and **byte-compatibility of emitted
> proof/verifier output plus witness-verdict identity is the acceptance bar on every
> implementation slice.** S1 (instruments) is PARALLEL-SAFE NOW — it measures without
> moving code. Read `AGENTS.md` (IDD manifesto, enforcement ladder, coordination
> density, the capstone law, construction closure) and this plan's decision of record
> before your first line. Every claim below is grounded in the decision of record or
> in file:line/issue references; re-verify against live main.

**Campaign umbrella:** #3026 ([rust-kit][campaign] Phase 3: temporal floor, MANDATORY).
**Depends:** Phase 2 effect algebra (#3025, **CLOSED** — PRs #3324/#3329/#3347/#3349/#3351);
the Rust witness surface (#3283–#3290, the enrollment acceptance); #3017 item 4 (BoundVar floor).
**Downstream:** #3027 (match-ladder demolition), #3043 (rust-kit closure capstone).

## Goal

Port the Python kit's temporal mechanism — bind/curry/rewrite name-time algebra — to
the Rust kit, **by construction rather than by model**: the stdlib's own combinators
execute over clever floor objects, the composition is observed and counted, and time
and branching dissolve into the two structures FOL natively has (distinct constants
and implications). Exit: every in-scope stdlib temporal sugar enrolled with witnesses;
a lying count UNSAT through the production pipeline; the catalog boundary manifest'd;
zero second temporal representations.

## Decision of record (T Savo, 2026-07-02, verbatim)

The design was ratified in conversation on 2026-07-02 (evening session). The
load-bearing statements, quoted:

1. **The catalog boundary:** *"Stdlib in Rust IS sugar. Everything else is out."*
   Tokio is explicitly OUT OF SCOPE — an async runtime is a scheduler, not semantic
   sugar; there is no composition to run. This matches the typed async opt-outs the
   Python witness close landed (PR #3365: AsyncFor/AsyncWith/Await as intrinsic
   `non_fol_support`). Per lift-the-shape-not-the-crate, stdlib vocabulary used
   *inside* third-party code still lifts (a foreign type that `impl Iterator` gets
   its `.map()` lifted); the runtime stays dark.

2. **The sugar trick, implemented in terms of the thing being desugared:**
   *"The MapSugar does temporal rewriting by calling map, and for the parameters,
   Sugar lhe and rhe objects that compose, and then you desugar those. X(1) becomes
   X_1()."* The sugar calls the REAL stdlib combinator — the kit implements NO
   combinator semantics, ever. The parameters are clever floor objects that compose
   by construction when the genuine combinator applies them. Each composed object
   desugars as an ordinary sugar the factory already recognizes. The temporal rewrite
   is **occurrence-renaming**: `X(1)` becomes `X_1()`, the second occurrence `X_2()`,
   and so on — each tick is a distinct timeless term, so a time-varying call cannot
   contradict itself in FOL (`X_1() == 5` and `X_2() == 7` are two facts about two
   constants; `X(1) == 5 ∧ X(1) == 7` would have been a lie about one).

3. **Counting is measurement:** *"you record how many times it was called, and emit
   that many pinned terms."* The unroll count is a MEASUREMENT of the real
   composition executing — never a static analysis of loop bounds. A shape whose
   count cannot be measured from pinned inputs is not in the catalog: it refuses,
   loudly, and lands in R as a named row.

4. **Branching, the TrySugar three-path form:** a raise inside an `if` becomes
   GuardedRaise DATA — three paths as guarded emissions into one universe:
   fall-through under `¬cond`; a caught result RE-GUARDED under `cond` (the guard
   prefix survives routing; nested guards stack in order); an uncaught raise stays
   loud residual data, never a silent branch. **Branches = guard-implications,
   time = name-splits; FOL natively has both.** The Phase 2 effect algebra is the
   precondition: an effect mid-composition refuses rather than silently truncating
   the count — Phase 2 bought the right to count.

5. **Total floor mediation:** *"ALL values go through the floor... You dispatch
   through the sugar, ask it to map, and the floor rises up to meet you. Thus the
   RHE and LHE are just templated types, with specialization."* Every value in the
   lift is a floor object; dispatch goes down through one door and semantics rise to
   meet it; `Lhe<S>`/`Rhe<S>` are generic over sort with per-sort behavior.
   **Engineering note (T-acknowledged):** "specialization" lands as per-sort trait
   impls under stable coherence — NOT the unstable `specialization` feature; no
   nightly. **Consequence:** the floor × operation dispatch matrix becomes the trait
   coherence matrix — Python needs a pinned auditor to watch that matrix (#3061);
   in Rust a missing cell is a missing impl, i.e. a compile error. **#3061's axis is
   born-retired in the Rust kit.**

6. **Fold's wrinkle — the accumulator threads:** occurrence-renames CHAIN. `acc_2`
   is defined in terms of `acc_1`; the temporal rewrite emits the recurrence as EUF
   facts (`acc_1 == f(acc_0, x_1)`, `acc_2 == f(acc_1, x_2)`, …). The chain is the
   fold's temporal shape, measured tick by tick.

7. **Enrollment is existence (the capstone law):** every temporal sugar enters via
   `witnesses()` with truthful/lying twins through the production pipeline
   (`sugar lift → ir compiler → solver`). **A lying twin with a WRONG COUNT must go
   UNSAT.** The Rust witness flip (#3283, non-defaulted `witnesses` on the claim
   structs) is the enrollment surface; a temporal sugar that cannot testify does not
   compile.

### Relation to the original #3026 mechanism spec

The issue's Python-port framing maps onto this design rather than competing with it:

- **TemporalContext** (immutable binding tuple; rebind = drop-prior + append-fresh;
  `value_for` reverse-scan as THE ONLY name resolution; miss = Floor-kind gap) is the
  S2 substrate — it is what makes occurrence identity well-defined.
- **The three mutations** map: Rust shadowing = **bind** (a fresh binding appended),
  `mut` assignment = **rewrite** (occurrence-rename of the rebound name from that
  point forward), closures = **curry** (scope-captured floor values riding inside the
  clever object). BoundVar scope-captured lazy aliasing (`x = x + 1` terminates by
  construction) rides on #3017 item 4.
- **ARCHITECT DECISION REQUIRED IN-PHASE (unchanged from the issue, held for T):**
  the AST-lift vs LLBC/MIR seam. The temporal floor likely owns the AST side, with
  the LLBC side proving equivalence via differential test (same source, both paths,
  same pinned FOL). This decision gates S3+ drains that would commit to a seam; S1
  and S2 are seam-neutral. Do not assume it — flag to the coordinator when reached.

## Instruments (S1 — before any drain)

- **Instrument A — the catalog enumeration:** `R(stdlib-temporal-surface-unenrolled)`.
  A DELIBERATE enumeration of the in-scope stdlib trait/combinator surface: Iterator
  adapters (map/filter/fold/take/skip/chain/zip/enumerate/…), Option/Result
  combinators (map/and_then/unwrap_or/ok_or/…), the operator traits (partially done),
  Try. The enumeration IS the scope decision — the catalog's edge is the refusal
  boundary. Each row: trait, method, temporal shape (counted / guarded / recurrence),
  owner, target slice. Tokio/async rows appear exactly once: in the OUT set, with the
  typed-opt-out cross-reference. Law-8 rung: auditor over a checked-in catalog;
  retires row-by-row as enrollment (the witness gate) subsumes it.
- **Instrument B — uncounted composition paths:** `R(uncounted-composition-paths)`.
  Detects lift paths that consume an in-catalog combinator without routing through
  the counted clever-object composition (the temporal equivalent of a naked-formula
  crossing). Baseline the live set with owners/retirements.
- **Instrument C — byte/verdict harness:** reuse Phase 2's `phase2_byte_compat_harness`
  pattern (baseline/changed SHAs + planted-drift control) and the witness triple
  suite. Deterministic occurrence-renaming is a FLOOR: same composition + same pinned
  inputs → same counts → same `X_n()` names → same CIDs, replayable.

## Slices

### S1 — Instruments, RED/measuring (PARALLEL-SAFE NOW)
Land Instruments A+B; pin both vectors with baselines; no production change.
- Red-first: a planted in-catalog combinator consumed outside the counted path reds B;
  a catalog row without an enrollment target reds A's completeness check.
- Bad-twins: an out-of-catalog call (a Tokio spawn) is NOT flagged by B (it is out,
  not unrouted); a planted catalog row deletion reds (enumeration is non-regressing).
- Exit: both vectors pinned; the catalog checked in; OUT set named with reasons.

### S2 — The clever-object substrate
`Lhe<S>`/`Rhe<S>` templated floor values with per-sort trait impls (stable coherence);
the TemporalContext port (immutable binding tuple, reverse-scan resolution, bind/
curry/rewrite through one `perform_temporal_operation` mirror); the occurrence-rename
mint (`X(1)` → `X_1()` — deterministic, CID-stable, collision-free by context);
the counting harness. Consumes #3017 item 4 (BoundVar) — if absent, flag, don't fork it.
- Red-first: a composition test that needs the substrate (compile-red before it exists).
- Bad-twins: (a) rebind drops-prior + appends-fresh (shadowing twin); (b) a name-miss
  is a Floor-kind gap, never a default; (c) direct-context-minting (the side-door from
  the Python auditor `collect_temporal_dispatch_frontier.py`) refuses — port the
  offender kind; (d) `x = x + 1` terminates by construction (lazy aliasing).
- Exit: substrate compiles; occurrence mints deterministic under replay; no drain yet.

### S3 — MapSugar, the exemplar
The full mechanism once, end to end: MapSugar calls the REAL `Iterator::map` with
composing `Lhe`/`Rhe` parameters; the composition is counted; each composed object
desugars through the factory; occurrence-renames emit that many pinned terms.
- Red-first: the witness pair before the mechanism (twin red).
- Bad-twins: (a) truthful map → SAT with N pinned terms for N elements; (b) **lying
  count** (one term too few/many, or a wrong element fact) → UNSAT; (c) an effectful
  closure mid-map → the Phase 2 effect refuses the emission (never a short trace);
  (d) byte/verdict identity on any already-lifted map shapes.
- Exit: MapSugar enrolled (witnesses through the production pipeline); the exemplar
  is the template every S5+ drain copies.

### S4 — FoldSugar, the recurrence
The accumulator chain: `acc_n` defined in terms of `acc_{n-1}` as EUF facts; the
recurrence measured tick by tick through the real `fold`.
- Bad-twins: (a) truthful fold → SAT with the full chain; (b) a lying intermediate
  (`acc_2` misstated) → UNSAT (the chain makes every tick load-bearing); (c) empty
  iterator → the init value alone (no vacuous chain links).
- Exit: FoldSugar enrolled; the chain pattern documented for scan/reduce relatives.

### S5 — Iterator adapter drain, batch 1
filter / take / skip / chain / zip / enumerate — each by the S3 template: real
combinator, counted composition, occurrence-renames, witness pair. filter's wrinkle:
the count is data-dependent on the predicate — guards carry it (kept elements emit
under the predicate-guard, like TrySugar's paths), or the shape refuses if the
predicate cannot be floored. Batch at the family boundary; split if any member
needs its own design conversation.

### S6 — Option/Result combinator drain
map / and_then / or_else / unwrap_or / ok_or across Option and Result — these compose
with Phase 2's RaiseEffect world (an `Err` flowing through `and_then` is the routed
raise, already typed). Reuse the router, do not re-model.

### S7 — Close: gate armed, boundary manifest'd
- Drive A and B to zero for the enumerated catalog; arm both as gates (a new
  unenrolled catalog row or uncounted path is a hard red).
- The catalog boundary lands in the conformance manifest: the OUT set (Tokio, async,
  anything scheduler-shaped) as declared rows with the reason ("not semantic sugar —
  no composition to run") and the typed-opt-out cross-reference (#3365's pattern).
- Stable-zero declaration (R/ΔR/εR per axis); campaign closure statement: what became
  unrepresentable (the dispatch matrix, per #3061-retirement; uncounted paths where
  the type system now forces the clever-object door), what stays measured.

## Ratchet table

| Vector | S1 baseline | Target |
|---|---|---|
| `R(stdlib-temporal-surface-unenrolled)` | full catalog enumeration | 0 (every row enrolled or typed-opt-out) |
| `R(uncounted-composition-paths)` | live set, owners+retirements | 0, gate-armed |
| `R(byte-drift)` | 0 | 0 every slice, planted control red |
| `R(witness-triples-failing)` | inherited | never regressed by this campaign; new temporal rows red only as honest catches |
| dispatch-matrix axis | — | **born-retired** (coherence; cite #3061) |

## Sequencing with sibling campaigns

- **Rust witness drain (#3283–#3290)** — the acceptance surface. Enrollment through
  `witnesses()` is how every temporal sugar proves itself; S3+ lands alongside or
  after the one-law flip (#3283). Coordinate: temporal sugars enroll as they land,
  never as a separate later pass.
- **Phase 2 (#3025, CLOSED)** — consumed, not touched. The effect algebra is the
  truncation-refusal floor; the router is how guarded raises route. Any gap found in
  the spine is a Phase 2 regression issue, not a temporal workaround.
- **#3027 match-ladder demolition** — downstream; the temporal floor is one of its
  prerequisite seams.
- **#3061 (Python dispatch-matrix auditor)** — the Rust mirror retires the axis by
  coherence; the Python auditor remains Python's (its retirement path is documented
  there).

## Anti-goals

- **No combinator reimplementation.** The kit owns ONLY value protocols. If a slice
  finds itself writing map's loop, it has failed the campaign's one law.
- **No static count analysis.** Counts are measured from the real composition over
  pinned inputs. Loop-bound inference, range analysis, symbolic iteration counts —
  all forbidden; unmeasurable = refused.
- **No async/Tokio modeling.** Out means out. The OUT set is manifest'd, not silent.
- **No nightly `specialization` feature.** Per-sort trait impls under stable coherence.
- **No second temporal representation.** A static temporal model is the
  shadow-interpreter crime in the time dimension (CL S6 deleted the spatial one; do
  not mint a temporal one).
- **No silent truncation.** An effect mid-composition refuses the emission; a short
  trace with a valid CID is a lie — Phase 2's routers are the enforcement.

## Campaign closure

CLOSED when: the enumerated stdlib temporal catalog is fully enrolled (or typed-opt-out)
with witness pairs whose lying counts go UNSAT through the production pipeline;
`R(uncounted-composition-paths) = 0` gate-armed; occurrence-renaming deterministic
under replay (CID-stable); the OUT boundary manifest'd; the dispatch matrix enforced
by coherence with #3061's axis cited as born-retired; byte-drift 0 throughout; and the
AST-vs-LLBC seam decision made BY T on the record (not assumed by a worker). At that
point time and branching are carried entirely by name-splits and guard-implications —
FOL's own structures — and the kit still owns nothing but value protocols.

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

5. **Total floor mediation — and the floor OWNS the operation:** *"ALL values go
   through the floor... You dispatch through the sugar, ask it to map, and the floor
   rises up to meet you."* And the correction that fixes where the intelligence
   lives (T, verbatim): *"That's the floor's job! Do the RIGHT thing here. Map does
   the right thing. It dispatches to the map floor, and whoever wants to be able to
   map can stand on the mappable floor."*

   **Each operation is a floor with ONE lawful implementation.** The map floor, the
   fold floor — the operation's semantics are written once, owned by the floor.
   Sugars dispatch to the operation's floor. A type gains a capability by
   **standing on that floor**: a membership declaration plus an **embedding** (how
   the sort's values step onto the floor's carrier). The sort-specific part is ONLY
   the embedding — never the operation semantics. **There is NO matrix**: each floor
   has one implementation plus a membership set. In Rust the bound (`T: Mappable`)
   makes a non-member unrepresentable *as an operand* — refusal happens at the
   standing, not at the operation. Laws are proven once per floor and inherited by
   every member. `Lhe<S>`/`Rhe<S>` remain the composing witness values, but their
   cleverness is **recording + embedding**, not operation semantics.
   **Engineering note:** stable Rust throughout — membership = trait bound +
   embedding impl; no nightly `specialization`.
   **Exemplar already on the board:** #3125 (MonoidFold via CarrierEmbedding — "the
   general lawful floor for iterator terminals over non-Int elements, Duration
   first") IS this architecture; this campaign absorbs it (S4).
   **Consequence for #3061:** the Python dispatch-matrix auditor's axis doesn't get
   *enforced* in Rust — it gets *dissolved*: with one owner per operation and
   membership bounds, the missing-cell question is unaskable.

6. **Floors are double dispatch** (T, verbatim, completing the decision of record):
   *"You dispatch to the floor, and the floor dispatches to the literal by raising
   the floor through the sugar."* Two dispatches, one per axis of variation:
   **(1) sugar → floor** = which operation — the sugar knows what's asked, never how;
   **(2) floor → literal via the sugar** = which concrete thing — the floor NEVER
   inspects its operand (no downcast, no type switch); it hands the ask back through
   the sugar, which knows its literal, and the literal's embedding raises it onto the
   floor's carrier — the floor receives the operand already standing on itself.
   Role separation: the sugar owns which-operation + which-literal, the floor owns
   the operation, the literal owns its embedding — no party holds two at once, so
   "what is the receiver" is unwritable. This is the AGENTS.md enforcement-ladder
   Visitor clause made literal ("the 'what is the receiver' bug is unwritable,
   because dispatch *is* the design"). Both extension directions are
   compiler-enumerated: a new floor → members declare standing or cannot be operands;
   a new literal → every floor it stands on demands its embedding arm — rustc hands
   you the todo list.

7a. **The doorway choice is a soundness decision — map over a callsite is a CURRY**
   (T, 2026-07-03: *"What's the temporal floor of map over a callsite? It's a
   curry..."*). `xs.map(f)`: `f` is resolved ONCE at the map boundary — captured,
   frozen, curried into the composition; no later rebinding touches the in-flight
   map. The temporal floor does NOT occurrence-split the callee; it splits the
   APPLICATION side: `call:f(x_1)`, `call:f(x_2)` — ticks are argument occurrences
   under one frozen symbol. **Curry is what preserves EUF congruence across time**:
   splitting the callee (`f_1(), f_2()`) would shatter the single uninterpreted
   function the solver's congruence reasoning needs; the stated-anchor doctrine
   (`call:f(args) == literal`) depends on the callee's unity across occurrences.
   The three doorways are three answers to "what splits when time passes":
   **bind** — nothing splits, a fresh name enters; **rewrite** — the NAME splits
   (`mut`/shadowing: the referent changed; one name would lie); **curry** — the
   name FREEZES and the applications split. Splitting the wrong side is a different
   theory, not a smaller emission: rewrite-where-curry-belonged destroys
   congruence (a lie can slip through); curry-where-rewrite-belonged merges two
   referents and manufactures a false contradiction. THE DISCRIMINATION TEST for
   the floor (mandatory in S3's witness pair): the truthful map-over-callsite twin
   must reach SAT *via congruence across ticks*; the lying twin is the wrong
   doorway — assert both directions.

7. **Fold's wrinkle — the accumulator threads:** occurrence-renames CHAIN. `acc_2`
   is defined in terms of `acc_1`; the temporal rewrite emits the recurrence as EUF
   facts (`acc_1 == f(acc_0, x_1)`, `acc_2 == f(acc_1, x_2)`, …). The chain is the
   fold's temporal shape, measured tick by tick.

8. **Enrollment is existence (the capstone law):** every temporal sugar enters via
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

### Addendum — the iter floor is the foundational membership (T Savo, 2026-07-03)

T: "What stands on an iter() floor? ArrayLiterals for one..." The consequences,
ratified in conversation:

- **The iter floor IS the temporal floor, concretely.** Standing on iter =
  admitting counted enumeration. The counting, the occurrence-renames, the pinned
  terms — all of it is what the iter floor does to its members. The combinator
  floors (map/fold/filter/...) STACK on iter: their operand bound is
  "stands on iter" plus an element embedding; Mappable is not a separate
  membership, it is iter-standing seen through the map floor.
- **Members provide their own counts by enumerating.** ArrayLiteral, TupleLiteral,
  StringLiteral (chars/bytes), RangeLiteral (`0..3` — a literal whose content IS
  its count). The count is never analyzed; the member iterates for real and the
  composition executes exactly that many times.
- **Map's OUTPUT stands on iter** — chaining/composition (`xs.map(f).filter(p)`)
  is floors dispatching to floors; the ecology falls out of one membership.
- **Stated collections stand on iter WITH their provenance.** A vendor-stated
  literal (`call:make_xs() == [1,2,3]`, Stated memento) is an ArrayLiteral, so it
  stands; the count it yields carries the Stated warrant onto every emitted term.
  Derived literals same, warrant Derived. This RESOLVES the data-dependent-arity
  question: there is no special case — the question was never "can we derive the
  count," it is "does the operand stand on iter," and provenance rides the
  standing. A value that does not stand (opaque un-stated call, consumed iterator
  with unknown remainder) cannot be a combinator operand AT ALL — refusal at the
  standing, per the membership law.
- Slice impact: S2's substrate includes iter-floor membership for the literal
  family (the members above); S3's MapSugar bounds its operand on iter-standing;
  the R(embeddings) axis counts per-floor-per-literal doorways.

### Addendum 2 — the keystone: one operation, one aliasing authority (T Savo, 2026-07-03)

T: "Walk it up THROUGH a map floor. It's one operation. Desugar. And that's why
there's a temporal floor: the place where rewrites go to be aliased."

- **Every floor's one operation is desugar.** The map floor does not compute a
  mapping; it runs the real combinator over the composing lhe/rhe and yields
  compositions — rewrites, one per tick. Floors are desugaring authorities per
  shape; nothing else.
- **The temporal floor is the terminal aliasing authority.** ALL rewrites — map
  ticks, fold's threading accumulator, `mut` assignment, shadowing, guarded-raise
  branch occurrences — dispatch to the temporal floor to be aliased
  (X(1) → X_1()). NO combinator owns its own renaming (distributed renaming =
  distributed intelligence = the crime; anti-goal). One door mints every alias,
  so occurrence identity is globally consistent, collision-free, and CID-stable
  under one owner's deterministic discipline.
- **bind/curry/rewrite are one operation through three doorways** — alias this
  rewrite into the timeless universe. That is why #3026 is MANDATORY: nothing in
  the system can be sound about time until there is exactly one place time goes
  to become a name.
- Slice impact: the S2 substrate's occurrence-rename infrastructure IS the
  temporal floor (rename it accordingly in the slice; it is a floor with members
  and a single operation, not a helper library); every combinator slice (S3+)
  consumes it by dispatch, never by local renaming; add the anti-goal to every
  drain slice: a combinator that mints its own occurrence names = reject.

## Instruments (S1 — before any drain)

- **Instrument A — the catalog enumeration:** `R(stdlib-temporal-surface-unenrolled)`.
  A DELIBERATE enumeration of the in-scope stdlib trait/combinator surface: Iterator
  adapters (map/filter/fold/take/skip/chain/zip/enumerate/…), Option/Result
  combinators (map/and_then/unwrap_or/ok_or/…), the operator traits (partially done),
  Try. The enumeration IS the scope decision — the catalog's edge is the refusal
  boundary. Each row: trait, method, temporal shape (counted / guarded / recurrence),
  **owning operation floor** (map floor, fold floor, …), **doorway**
  (bind / rewrite / curry — per DoR 7a the doorway choice is a soundness decision;
  map-over-callsite rows are CURRY), owner, target slice. Tokio/async rows appear
  exactly once: in the OUT set, with the typed-opt-out cross-reference. Law-8 rung:
  auditor over a checked-in catalog; retires row-by-row as enrollment (the witness
  gate) subsumes it.
- **Instrument A′ — the membership vectors (iter-floor addendum):** per-floor
  membership enumeration, starting with the FOUNDATIONAL iter floor: ArrayLiteral,
  TupleLiteral, StringLiteral (chars/bytes), RangeLiteral, **map-output**
  (combinator results stand on iter — the stacking row), and **stated/derived
  collections** (membership WITH provenance: a Stated literal stands on iter and
  its count carries the Stated warrant onto every emitted term). Vectors:
  `R(operation-floors-landed)` and `R(embeddings)` per floor per member sort.
  A value class that should stand but has no embedding is a red row; a combinator
  operand class outside the membership is refusal-at-the-standing, not a row.
- **Instrument B — uncounted composition paths:** `R(uncounted-composition-paths)`.
  Detects lift paths that consume an in-catalog combinator without routing through
  the counted clever-object composition (the temporal equivalent of a naked-formula
  crossing). Baseline the live set with owners/retirements.
- **Instrument B′ — combinator-local renaming (the keystone anti-goal made
  measurable):** `R(combinator-local-renames)`. Detects any combinator/sugar/floor
  site that MINTS ITS OWN occurrence names instead of dispatching to the temporal
  floor's aliasing authority. Target 0 from birth; the S7 close confirms the axis
  either held at zero or became structural (the mint API private to the temporal
  floor = the detector retires by visibility). Law-8 note: this auditor exists only
  until the dispatch shape makes local minting unrepresentable — state the rung and
  the retirement in the row.
- **Instrument C — byte/verdict harness:** reuse Phase 2's `phase2_byte_compat_harness`
  pattern (baseline/changed SHAs + planted-drift control) and the witness triple
  suite. Deterministic occurrence-renaming is a FLOOR: same composition + same pinned
  inputs → same counts → same `X_n()` names → same CIDs, replayable.

## Slices

### S1 — Instruments, RED/measuring (PARALLEL-SAFE NOW)
Land Instruments A+A′+B+B′; pin all vectors with baselines; no production change.
- Red-first: a planted in-catalog combinator consumed outside the counted path reds B;
  a catalog row without an enrollment target reds A's completeness check; a planted
  local-rename site reds B′; a planted membership row without an embedding reds A′.
- Bad-twins: an out-of-catalog call (a Tokio spawn) is NOT flagged by B (it is out,
  not unrouted); a planted catalog row deletion reds (enumeration is non-regressing);
  a stated collection appears in A′'s iter-membership WITH its provenance column.
- Exit: all vectors pinned; the catalog checked in with doorway column; the iter-floor
  membership enumerated (literal family + map-output + stated/derived-with-provenance);
  OUT set named with reasons.

### S2 — THE TEMPORAL FLOOR itself, plus the substrate it serves
Per the keystone (Addendum 2): S2 does not build "occurrence-rename infrastructure" —
it builds **the temporal floor**: a floor in the architecture's own sense, whose
members are REWRITES and whose single operation is *alias this rewrite into the
timeless universe*. Rewrites arrive through the three doorways — **bind** (fresh name
enters, nothing splits), **rewrite** (`mut`/shadowing — the NAME splits), **curry**
(capture — the name FREEZES, applications split) — and per DoR 7a the doorway choice
is a SOUNDNESS decision the floor owns (wrong side split = a different theory).
The mint (`X(1)` → `X_1()`) is deterministic, CID-stable, collision-free, and
**private to the temporal floor** — no other party can mint an alias (this is what
retires Instrument B′ by visibility). Alongside it, the substrate the combinator
floors need:
- `Lhe<S>`/`Rhe<S>` composing witness values (recording + embedding ONLY — no
  operation semantics);
- **iter-floor membership for the literal family** (ArrayLiteral / TupleLiteral /
  StringLiteral / RangeLiteral stand on iter; members enumerate their own counts;
  map-output standing lands with S3; stated/derived collections stand WITH their
  provenance riding onto every emitted term);
- the first operation floor stood up in the floor-owns-the-operation form (the map
  floor: one lawful implementation + a membership set + `CarrierEmbedding`-style
  per-sort embeddings — #3125 is the pattern reference);
- the TemporalContext port (immutable binding tuple, reverse-scan resolution,
  bind/curry/rewrite through one `perform_temporal_operation` mirror = the three
  doorways of the one operation);
- the counting harness.
Membership refusal is at the standing: a non-member operand is a compile error via
the bound, never a runtime arm. Consumes #3017 item 4 (BoundVar) — if absent, flag,
don't fork it.
- Red-first: a composition test that needs the substrate (compile-red before it exists).
- Bad-twins: (a) rebind drops-prior + appends-fresh (shadowing twin); (b) a name-miss
  is a Floor-kind gap, never a default; (c) direct-context-minting (the side-door from
  the Python auditor `collect_temporal_dispatch_frontier.py`) refuses — port the
  offender kind; (d) `x = x + 1` terminates by construction (lazy aliasing);
  (e) a doorway misuse is constructible only through the floor's typed API and
  refuses (the floor owns the doorway decision — no caller picks a doorway by
  passing a flag it can get wrong silently).
- Exit: the temporal floor compiles with its mint private; occurrence mints
  deterministic under replay; iter membership landed for the literal family;
  no drain yet.

### S3 — MapSugar, the exemplar
The full mechanism once, end to end: MapSugar dispatches to the MAP FLOOR (S2's one
lawful implementation), whose operand bound is **iter-standing** (the addendum: not a
separate Mappable membership — iter-standing seen through the map floor; a non-member
operand fails the bound and does not compile); the floor calls the REAL
`Iterator::map` with composing `Lhe`/`Rhe` parameters; the composition is counted;
each composed object desugars through the factory; and **every rename dispatches to
the temporal floor** — MapSugar mints nothing locally (B′ stays at zero).
**Map over a callsite routes through the CURRY doorway** (DoR 7a): `f` is resolved
once at the map boundary, frozen; the callee is ONE symbol across all ticks; the
APPLICATION side splits (`call:f(x_1)`, `call:f(x_2)`) — curry is what preserves EUF
congruence across time.
- Red-first: the witness pair before the mechanism (twin red).
- Bad-twins: (a) truthful map → SAT with N pinned terms for N elements; (b) **lying
  count** (one term too few/many, or a wrong element fact) → UNSAT; (c) an effectful
  closure mid-map → the Phase 2 effect refuses the emission (never a short trace);
  (d) byte/verdict identity on any already-lifted map shapes; (e) **THE MANDATORY
  7a DISCRIMINATION PAIR**: the truthful map-over-callsite twin reaches SAT *via
  congruence across ticks* (`x_1 == x_2 → f(x_1) == f(x_2)` load-bearing in the
  proof — verify the solver actually uses it, not merely tolerates it); the lying
  twin is the WRONG DOORWAY — a split callee (`f_1(), f_2()`) whose broken
  congruence would let a lie through, and a merged rebind manufacturing a false
  contradiction — both directions asserted.
- Exit: MapSugar enrolled (witnesses through the production pipeline); map-output
  stands on iter (the stacking row in A′ goes green); the exemplar is the template
  every S5+ drain copies.

### S4 — FoldSugar, the recurrence (ABSORBS #3125)
The fold floor in the lawful form #3125 already specifies: MonoidFold via
CarrierEmbedding — one general lawful floor for iterator terminals, members standing
on it through embeddings (Duration first, per the issue). The accumulator chain:
`acc_n` defined in terms of `acc_{n-1}` as EUF facts; the recurrence measured tick by
tick through the real `fold` — and **the chain's renames (`acc_0, acc_1, …`) dispatch
to the temporal floor like every other rewrite** (the threading accumulator is the
REWRITE doorway per tick; the folded-over callee, when a callsite, is CURRY — one
fold can exercise two doorways, which is exactly why the floor owns the choice).
(#3125 re-chains into this slice — comment, don't duplicate.)
- Bad-twins: (a) truthful fold → SAT with the full chain; (b) a lying intermediate
  (`acc_2` misstated) → UNSAT (the chain makes every tick load-bearing); (c) empty
  iterator → the init value alone (no vacuous chain links); (d) B′ stays zero —
  fold mints no local names.
- Exit: FoldSugar enrolled; the chain pattern documented for scan/reduce relatives.

### S5 — Iterator adapter drain, batch 1
filter / take / skip / chain / zip / enumerate — each by the S3 template: real
combinator, counted composition, renames BY DISPATCH to the temporal floor (never
local — B′ at zero is an exit criterion of every drain slice), witness pair, operand
bounds on iter-standing. filter's wrinkle: the count is data-dependent on the
predicate — guards carry it (kept elements emit under the predicate-guard, like
TrySugar's paths), or the shape refuses if the predicate cannot be floored. Batch at
the family boundary; split if any member needs its own design conversation.

### S6 — Option/Result combinator drain
map / and_then / or_else / unwrap_or / ok_or across Option and Result — these compose
with Phase 2's RaiseEffect world (an `Err` flowing through `and_then` is the routed
raise, already typed). Reuse the router, do not re-model. Same drain constraints as
S5: renames by dispatch only (B′=0); callback operands through the CURRY doorway
(an `and_then(f)` freezes `f` exactly as map does).

### S7 — Close: gate armed, boundary manifest'd
- Drive A, A′, and B to zero for the enumerated catalog; arm all as gates (a new
  unenrolled catalog row, unembedded member, or uncounted path is a hard red).
- **B′ disposition (the keystone gate):** confirm `R(combinator-local-renames)`
  either held at zero for the whole campaign AND became structural (the mint API
  private to the temporal floor — the planted local-mint bad-twin fails to
  COMPILE), in which case the detector retires by unrepresentability with the
  retirement stated; or any residue is a declared row with owner. Never delete the
  detector while local minting remains representable.
- The catalog boundary lands in the conformance manifest: the OUT set (Tokio, async,
  anything scheduler-shaped) as declared rows with the reason ("not semantic sugar —
  no composition to run") and the typed-opt-out cross-reference (#3365's pattern).
- Stable-zero declaration (R/ΔR/εR per axis); campaign closure statement: what became
  unrepresentable (the dispatch matrix, per #3061-retirement; uncounted paths where
  the type system now forces the clever-object door; local alias-minting, per the
  keystone), what stays measured.

## Ratchet table

| Vector | S1 baseline | Target |
|---|---|---|
| `R(stdlib-temporal-surface-unenrolled)` | full catalog enumeration | 0 (every row enrolled or typed-opt-out) |
| `R(uncounted-composition-paths)` | live set, owners+retirements | 0, gate-armed |
| `R(combinator-local-renames)` | 0 from birth (B′) | 0 held, then STRUCTURAL (mint private to the temporal floor; planted local mint fails to compile) — detector retires by unrepresentability |
| `R(byte-drift)` | 0 | 0 every slice, planted control red |
| `R(witness-triples-failing)` | inherited | never regressed by this campaign; new temporal rows red only as honest catches |
| `R(operation-floors-landed)` | 0 of the floor catalog (map, fold, filter, …) | full catalog, one lawful implementation each |
| `R(embeddings)` per floor | per-sort embedding set enumerated | every member sort embedded or refused-at-standing |
| dispatch-matrix axis | — | **dissolved, not enforced** (one owner per operation + membership bounds make the missing-cell question unaskable; cite #3061) |

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
- **#3125 (MonoidFold via CarrierEmbedding)** — the exemplar of the
  floor-owns-the-operation architecture, already on the board; ABSORBED as S4
  (re-chained, not duplicated).
- **#3061 (Python dispatch-matrix auditor)** — the Rust mirror dissolves the axis
  (one owner per operation + membership bounds; no matrix exists to audit); the
  Python auditor remains Python's, with its retirement path documented there.

## Anti-goals

- **No combinator reimplementation.** The kit owns ONLY value protocols. If a slice
  finds itself writing map's loop, it has failed the campaign's one law.
- **No static count analysis.** Counts are measured from the real composition over
  pinned inputs. Loop-bound inference, range analysis, symbolic iteration counts —
  all forbidden; unmeasurable = refused.
- **No async/Tokio modeling.** Out means out. The OUT set is manifest'd, not silent.
- **No nightly `specialization` feature.** Stable Rust: membership = trait bound +
  embedding impl.
- **No per-sort operation semantics.** The floor owns the operation ONCE; the only
  per-sort code is the embedding. A sort-specific map/fold body anywhere = the matrix
  reborn = reject.
- **No type switches or downcasts in any floor implementation.** A floor that
  matches on its operand's concrete type is the crime the architecture exists to
  kill. The double-dispatch shape prevents it structurally (the floor receives
  operands already standing on itself); if any residue genuinely can't be
  structurally prevented, it becomes a named detector row — never a silent match arm.
- **No second temporal representation.** A static temporal model is the
  shadow-interpreter crime in the time dimension (CL S6 deleted the spatial one; do
  not mint a temporal one).
- **No silent truncation.** An effect mid-composition refuses the emission; a short
  trace with a valid CID is a lie — Phase 2's routers are the enforcement.

## Campaign closure

CLOSED when: the enumerated stdlib temporal catalog is fully enrolled (or typed-opt-out)
with witness pairs whose lying counts go UNSAT through the production pipeline;
`R(uncounted-composition-paths) = 0` gate-armed; occurrence-renaming deterministic
under replay (CID-stable); the OUT boundary manifest'd; every operation floor landed
with one lawful implementation and its membership set (the dispatch matrix dissolved,
#3061 cited); byte-drift 0 throughout; and the AST-vs-LLBC seam decision made BY T on
the record (not assumed by a worker). The closure clause, verbatim shape: **one door
(all values through the floor), one owner per operation (the floor does the right
thing once), membership by standing, embedding as the only per-sort code.** And the
maintenance story: **no auditor watches the dispatch, because the dispatch IS the
design** — both extension directions (new floor, new literal) are compiler-enumerated
todo lists, not review obligations. At that point time and branching are carried
entirely by name-splits and guard-implications — FOL's own structures.

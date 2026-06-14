# Goal: stdlib `unclassified` → 0

> **STATUS 2026-06-14 PM — DISSOLVE-BY-EVALUATION (T-designed live).** unclassified
> **593** (was 1082 at session start; −489 over seven sound wins, all pushed, SILENT=0,
> falsePass=0). The breakthrough past the "huge/supervised flt2dec" floor: a closed/
> deterministic/total/effect-free STDLIB computation is rust *sugar* every (non-`no_std`)
> dev assumes, so the rust kit DISSOLVES it by evaluating with the same stdlib it ships
> — `format!("{}",3.14)`="3.14" — not modeling Grisu (can't), not an uninterpreted EUF
> symbol (tautology), not running the code-under-test (unstable internals, can't). It's
> recompute-don't-trust with an INDEPENDENT correct impl (`format!` is built on flt2dec).
> "Need stdlib to prove stdlib? Yes — that's the named, pinned TCB: axioms all the way
> down, then a floor with a name on it." Sound iff: named + pinned + deterministic +
> independent-of-the-thing-under-test. All FOUR flt2dec modes done (`flt2dec_eval.rs`,
> 78 verbatim-corpus break-the-twin cases, f32+f64): flt2dec −283, ZERO disagreements
> (our eval never contradicted a vendor assertion). f16/f128/ldexp/`format!`-RHS stay
> honestly unclassified. CROSS-KIT: identical to encoding Java `toString`/`equals` into a
> Java kit — each kit encodes its own stdlib as its axiom set. NEXT (messier, lower
> yield): char case-mapping (`to_{lower,upper}case().collect()` via lifter's own char
> methods; helpers nest iterator-consistency + a ptr-identity assert) → general endgame =
> a stable-API closed-expression compile-run evaluator (char/str/int uniformly).
> Commits: type-level markers 77a3bcc55; flt2dec_eval 1c517784a; integration e2ca82504;
> shortest_exp 0c0dc2394.

> **COMPLETE CENSUS 2026-06-14 (every one of the 883 enumerated by concrete class
> + per-class soundness verdict; ground truth from the sweep's own classifier with
> the reason-sample cap temporarily raised 12→5000, captured, reverted — NOT regex
> inference).** unclassified=**876** (was 883; −7 from the type-level-obligation win
> below, commit 77a3bcc55), discharged=5287, refused(terminal)=208, inactive=58,
> SILENT=0, falsePass=0. The 883 partition exhaustively into SIX classes; a FIFTH sound
> autonomous win then drained 7 of class 6 (type-level markers → terminal refused).
> (The original four — byte/mut-ref-pinned/const-item/immutable-value — drained 1082→883.) Each remaining class carries either a
> masked-contradiction risk the consistency sweep CANNOT catch, an R4-proven vacuous-SAT
> false-pass risk, or would require a fake-zero reclassification. Map:
>
> 1. **Higher-order / closure / iterator helper bodies — 516 (58%).** Dispositioned
>    "non-#[test] item, reachable only via call-site inlining." DOMINATED by
>    `num/flt2dec/mod.rs` float→decimal formatting helpers: `to_exact_fixed_str_test`
>    (133), `to_exact_exp_str_test` (130), `to_shortest_exp_str_test` (68),
>    `to_shortest_str_test` (57) = **388 alone**. Rest: `chain.rs::test_chain` (26,
>    `Unfuse::chain().advance_by()`), `iterator.rs::check` (6, `partition_in_place`
>    over a closure), `char.rs::check/lower/upper/string` (24, case mapping),
>    `slice.rs::test/test_mut/case` (28), `ptr.rs` (6), `hint.rs::do_test` (6),
>    `num/mod.rs` (6), `unicode.rs` (6), tail. **Call-site inlining is NOT the wall** —
>    even with literal args substituted, these bodies need float-formatting / iterator-
>    state / closure-application semantics that are not point-wise liftable. Modeling
>    Grisu/Dragon float formatting (388) is the textbook masked-contradiction tier:
>    a subtly-wrong model false-discharges and the sweep is blind to it. SUPERVISED.
> 2. **Conditional / loop / match context — ~106.** `for` over literal range (44) +
>    literal array (16) + opaque-body (1), `while` (30), `if` (8), `match` (7). R4
>    (commit c99d78922) PROVED `if g { assert!(P) }` → `implies(g,P)` is faithful ONLY
>    if g is PINNED; corpus guards reference free params (`if i==0||i==xs.len()`), so
>    `implies(free_guard,P)` is vacuously SAT → sweep-blind false-pass. `for`/`while`
>    need loop-unrolling over the pinned range (real machinery, masked-contradiction
>    risk). SUPERVISED.
> 3. **Float / NaN / bit-pattern refinement — ~80.** `assert_almost_eq!` (22, flt2dec
>    tolerance), `assert_float_result_bits_eq` (23, dec2flt parser-under-test + closure),
>    `assert_eq_const_safe` in carryless_mul (16, GF(2) clmul bits), `a[0]<b[0]` (8 —
>    actually `[NaN]<[1.0f64]` IEEE compares nested in `a.iter().lt(b.iter())==…`),
>    signed-zero -0.0 (7), infinity (4), float-width predicates (2). Float/IEEE
>    semantics — SUPERVISED.
> 4. **Structural nesting — ~81.** Nested in unlifted expr-stmt (38), let-initializer
>    (32), unenumerated stmt position (11). Need statement-graph restructure. SUPERVISED.
> 5. **Unsafe / transmute / raw-ptr / mut-ref terms — 35.** `unsafe{transmute_copy(&1)}`,
>    `unsafe{*p.as_ptr()}`, `unsafe{assume_init()}`, `&mut cx`, `&raw const x`, `const{…}`
>    type-level. Reclassifying to "refused/terminal" would be a FAKE-ZERO —
>    `transmute_copy(&1)` IS finitely constructible (bit reinterpretation of a literal),
>    so it is honestly a lifter limitation, not a terminal source property. Stays
>    unclassified. SUPERVISED (needs raw-memory/transmute term modeling).
> 6. **Cross-file / no-visible-source helpers + small tail — ~65.** `assertion helper
>    has no visible source` (20: `assert_predicates_exact`, `assert_trusted_len`,
>    `assert_send_and_sync` — type-level trait markers we cannot SEE the def of, so
>    cannot safely classify), `macro yielded no liftable assertion` type-level (39),
>    `all`/`any` closure predicate (8), `matches!` non-qualified-variant (3),
>    `starts_with` (2), `array-repeat non-literal length` (1), mutable-container (4).
>    Cross-file resolution + type-level — SUPERVISED.
>
> **MECHANISM-LEVEL CONFIRMATION on class 6 (why even the smallest sub-class is gated).**
> Resolved the defs of the 20 "no visible source" helpers (read-only): **7 are genuine
> empty-body type-level trait markers** — `assert_trusted_len<T: TrustedLen>(_:&T){}` (5,
> flatten.rs:138), `assert_trusted_random_access<T: TrustedRandomAccess>(_a:&T){}` (1,
> zip.rs:257), `assert_send_and_sync() where ChunksMut<…>:Send,… {}` (1, slice.rs:1024).
> These carry ZERO recoverable value-work (the obligation is the trait bound in the
> signature, a typing judgment the compiler discharges), so refusing them "type-level
> trait obligation, no point-wise value predicate" IS a legitimate terminal reason per the
> trichotomy — NOT a fake-zero. The other 13 (`assert_predicates_exact` 8 — TypeId HashSet
> eq; `assert_exact_exp` 5 — formatter output) have real runtime bodies, stay unclassified.
> **DONE (commit 77a3bcc55, −7, 883→876).** I first wrote this off as supervised because
> the GLOBAL registry (`ReductionCtx::collect_items`) only collects MODULE-level fns and a
> FLAT-by-name registry would mis-inline the wrong same-named body (`check`/`test_chain`/`f`
> recur across files) = masked-contradiction false-discharge. That reasoning is correct for
> INLINING — but the type-level markers need TERMINAL REFUSAL, not inlining, and refusal is
> the SAFE direction (it can never false-discharge). The contained path: the bare-assert-call
> arm already has `local_fns` (this block's nested fns, line 1436) in scope; short-circuit
> there — if the call resolves to a same-block EMPTY-BODY helper, refuse-terminal "type-level
> obligation". Empty body ⇒ zero recoverable value-work ⇒ genuine terminal, not a fake-zero;
> lifts to zero entries ⇒ never displaces a discharge (discharged stayed 5287). Same-block
> scope only is lexically correct by construction; a deeper/sibling helper stays unclassified
> = safe under-claim. Drained exactly the 7 (assert_trusted_len 5, assert_trusted_random_access
> 1, assert_send_and_sync 1). LESSON: "supervised" was right about flat-registry INLINING and
> wrong about the TERMINAL-REFUSAL framing — the trichotomy's third leg ("refused with reason")
> was the safe move I'd lumped in with the unsafe one. Class 6 is now ~58 (the 13 runtime-body
> helpers — `assert_predicates_exact`, `assert_exact_exp` — remain unclassified, correctly).
>
> **VERDICT: 876 is the current sound autonomous floor** (883 minus the type-level-obligation
> win). The lesson from that win — "supervised" was a hypothesis, and the TERMINAL-REFUSAL
> framing of a sub-class can be safe even when its INLINING framing is not — should be applied
> to the rest before declaring them blocked: for each class, ask whether a refuse-with-reason
> (the trichotomy's safe leg) discharges the accounting where a lift would be unsound. Every remaining
> CHECKED + CORRECTLY DECLINED (2026-06-14, applying the safe-refusal lens): "mutable
> container is not temporally stable" (4) LOOKS like terminal-property wording drift vs the
> whitelisted "temporally unstable" — but it is NOT. It fires (lib.rs:6921) when an `a[i]`
> container is `is_mut_local`, and `mut_locals` is populated from SYNTACTIC `let mut`
> (`collect_mut_pat_idents`: `ident.mutability.is_some()`), NOT proven mutation. A `let mut a`
> never actually mutated is genuinely STABLE, so `a[i]` is recoverable/liftable; calling it
> terminal would launder that subset = a FAKE-ZERO. So it stays unclassified, correctly. Its
> real recovery path is a DISCHARGE (make the index oracle precise: use the proven-mutation
> set, not syntactic let-mut), which is a shared term-path change with masked-contradiction
> risk → supervised, NOT a terminal-refusal win. The lesson cuts both ways: the safe-refusal
> leg only applies when the gate is MECHANICALLY exact (empty-body), not when the underlying
> condition is conservative/recoverable.
>
 RECALIBRATION (2026-06-14, answering "why me at the soundness edge?"): "needs T at the
> edge" was IMPRECISE. A masked contradiction is invisible to inspection — a human reviewer
> catches it no better than the lifter does. What catches false-discharge is a BREAK-THE-TWIN
> test (construct the should-be-refuted case, prove it's refuted) — mechanical, and the
> lifter-author's to write. So the real division is "mechanically twin-testable (autonomous)"
> vs "MEANING-JUDGMENT (T's)", and the remaining work splits by PRECISE blocker, not a blanket
> "supervised": (1) flt2dec 388 = SCOPE+SUBTLETY (faithful Grisu is a huge reimplementation;
> the EUF-blackbox shortcut is tautological/false-pass) — a poor solo bet, NOT a human-eyes
> gate; (2) branch-partitioning ~106 = EMPIRICAL DEAD-END (R4: corpus guards are
> .len()/method/runtime, never pinned → drains 0); (3) float/NaN ~80 + bool-eq-as-term =
> SHARED-PATH REGRESSION risk (the lt/le/gt/ge term_binop_name scar) — derisked by a full-suite
> run, not by eyes; (4) iterator/flt2dec helper bodies = UNLIFTABLE-EVEN-WHEN-INLINED (Wall A);
> (5) transmute/raw-term 35 + duplicate-obligation (const-item) = the ONLY genuinely T-needs
> class, MEANING-JUDGMENT ("recoverable or terminal?" is not mechanical). 876 is where the
> mechanically-twin-testable autonomous surface is exhausted; the rest is large/subtle
> reimplementation + empirical dead-ends + genuine meaning-judgment. A twin-test still gates
> every future lift — driving one blind would make the 64 bytes lie.

> **STATUS 2026-06-14 (commits 3cbf69936..df1e1cd04, all pushed, all verified
> falsePass=0 / SILENT=0).** Capability work LANDED, driving unclassified
> **1082 → 883** (−199, discharged 5088→5287). LATEST (commit df1e1cd04, −6):
> **const/static-item initializers lift through the collector** — a `const _: () = …`
> is unconditionally const-evaluated, so `lift_item_assertions` routes the initializer
> through the SAME collector a `#[test]` fn uses instead of blanket-refusing. The cmp.rs
> `const _: () = assert!(S(1)==S(1))` / `S(1)<=S(1)` family now DISCHARGES — verified
> sound: `==`/`<=`/`<` over user type `S` dispatch to the user's `eq:S`/`le:S`/`lt:S` as
> EUF method terms (`eq(call:eq:S(S(1),S(1)), true)`), NOT logical `=` — the correct
> cmp_default behavior, no overclaim. (This CORRECTED an earlier punt: I'd called const-
> items a "double-count judgment call", but both copies test_runtime_and_compiletime!
> emits are distinct source occurrences in `seen`, so discharging the const copy balances
> — sound autonomous fix, not supervised.) Then the CLEAN immutable-value-sugar class
> (three break-the-twin-tested wins, below):
> (A, commits f101ba233 + a8095148f, −40) **`&mut <immutable value>` dissolves to
> `ref_mut(pinned value)`** — `assert_eq!(left, &mut [1,2,3])` compares slices BY VALUE,
> so the RHS is the pinned array, not a pointer. Generalized the `ref_mut` arm via
> `is_immutable_value_expr`: closure | scalar lit | array lit | negation of one | FULL
> slice `[..]` of one (same accepted immutable-value class as `&mut <scalar lit>`, NOT a
> new soundness class). SOUNDNESS BOUNDARY (tested): an Index over a PATH base
> (`&mut buf[..]`, `&mut buf[i]`) and `&mut <variable>`/`&mut <call>` stay RESIDUAL
> (pointer-identity guard green). Drained 40 of the 73 "unsupported term" bucket
> (array.rs/slice.rs/ptr.rs split/chunk/tuple asserts).
> (B, commit fe51cc88b, −21) byte literals → u8 constants (below).
> RESIDUAL after this class (full-text JSON `all_reasons` dump): the bulk is cross-file
> inlining (`to_exact_fixed_str_test` 133, `to_exact_exp_str_test` 130, … flt2dec +
> in-file helpers whose def-site refusal needs GLOBAL accounting to suppress — Wall B);
> construction-semantics/higher-order bodies (bin-1 for 69, const-item 6 — Wall A);
> macro-engine gaps (2026-06-14, inspected): **`assert_float_result_bits_eq` (23)** body
> = `dec2flt::<ty>(str).map(|x| x.to_bits())` (cross-file parser-under-test + closure →
> Wall A/B, held); **`assert_eq_const_safe` (16)** — LIVE-DIAGNOSED 2026-06-14 (throwaway test, then
> reverted): the mechanism FULLY WORKS in isolation. Lifting a file with the macro
> defined + `assert_eq_const_safe!(u32: 5u32, 5u32, "m")` (3-arg), the recursive 2-arg
> form, AND every real operand shape (`A.count_ones()`, `7u32.count_ones()`,
> `(-1 as i32).abs()`, `u32::BITS - 3`) ALL give `seen=1 lifted=1` no warnings. So the
> `const_eval_select` handoff, the recursive arm-1→arm-2 expansion, and the
> EUF-method/cast/const-arith operands ALL lift. The 16 corpus failures are therefore a
> CONTEXT-SPECIFIC edge, not the mechanism — GROUND-TRUTH (reproduced 2026-06-14):
> `test_runtime_and_compiletime!` (coretests/lib.rs:156) emits each `fn $test() $block`
> TWICE — `#[test] fn $test() $block` AND `const _: () = $block`. So every
> `assert_eq_const_safe!` appears twice: the #[test]-fn copy LIFTS (discharged, per the
> isolation diagnostic), and the **`const _: ()` copy is the unclassified one** (16). The
> 16 are therefore CONST-ITEM DUPLICATES of already-discharged runtime asserts. Lifting
> them would DOUBLE-COUNT the same logical obligation (inflate discharged past `seen`).
> Their honest disposition is a JUDGMENT CALL (T owns): (a) lift + dedup the obligation,
> (b) refuse-with-reason "compile-time duplicate of the discharged runtime assert" (an
> HONEST terminal, not laundering — it IS a re-statement), or (c) hold. This is the SAME
> question as the const-item bucket (6, `const _: () = assert!(S(1)==S(1))`). Not a
> mechanical fix — a duplicate-obligation policy decision. Failure mode of the wrong
> call: double-count (sweep-visible) or a mislabeled-duplicate. Stays-unclassified now;
> regression-prone comparison ops (`a[0]<b[0]` 16, `false==false` 2 — the lt/lte/gt/gte
> shared path); and correctly-held conditional/`-0.0`-IEEE/mutable-container cases.
> DIAGNOSTIC (JSON `all_reasons` dump, 2026-06-14): the 73-now-48 "unsupported term"
> bucket is dominated by `&mut [array]` (25, DONE) + `&mut [array][..]` full-slice
> (~9, intricate Index→Array+RangeFull match with a `&mut buf[i]` mutable-element edge
> → delicate, NOT taken unsupervised) + `a[0] < b[0]` ordered comparison (16, the
> lt/lte/gt/gte regression path → supervised) + `unsafe { *p }` derefs (pointer/runtime).
> LATEST byte-literal win (commit fe51cc88b, −21):
> **byte literals dissolve to u8 constants** — `b'0'` is pure sugar for the u8 value
> 48; added `Lit::Byte` to `translate_lit` lifting to the same concrete-Int-with-u8-
> sort form `48u8` lifts to. Sound by construction (refutation inherited from the
> int path; `b'0'!=49` REFUTED), two break-the-twin tests (positive + distinct-byte-
> literals-no-coalesce), 194 assertion_lift green. This FULLY drained the "only
> integer/string/char/finite decimal float scalar constants are liftable" bucket
> (was 21) — `Lit::Verbatim` is the only remaining `translate_lit` fall-through and
> never appears in source asserts. KEY LESSON: this class (pinned operand, the only
> gap is a missing literal-kind/structural case, failure mode = stays-unclassified
> NOT false-discharge) IS soundly autonomously drainable — it is NOT the supervised
> tier. The supervised tier is only the shared-path term/closure-body edits (masked-
> contradiction risk) + cross-file accounting. Checked and REJECTED as clean wins:
> **const-item asserts** (6, all in cmp.rs) are `S(1) == S(1)` / `S(1) <= S(1)` —
> custom-struct construction-semantics + comparison operators (the lt/lte/gt/gte
> shared-path change that regressed negated-comparison coalescing) → Wall A, not
> clean. Earlier capability work (−132): (#1) **monotonic statement-helper inlining** — β-reduce +
> recurse the unchanged collector, committed ONLY if the body adds zero unclassified
> (so inlining can only drain, never inflate — the earlier naive version inflated and
> was reverted); (#2) **closures as opaque EUF symbols** keyed by text + version-aware
> captures (drained 124; "unsupported term" 192→78); (#3) **`&mut <closure>/<literal>`
> as opaque `ref_mut`** (guard-preserving — `&mut <variable>` still residual). All
> three sound by construction (conservative EUF / faithful β-reduction / versioned),
> each with a discrimination test; verifier falsePass 0 throughout (undec 24→82 is the
> honest bignum tier the lifts exposed, not a false claim). Remaining 950 is dominated
> by the **516 "reachable only via inlining"**, and a diagnostic pinned the blocker:
> it is **ARCHITECTURAL, not a per-assert gap.** Those helpers (flt2dec
> `to_exact_fixed_str_test` etc.) are DEFINED in `num/flt2dec/mod.rs` but CALLED
> cross-file from `strategy/*.rs`. The lifter processes each file independently with a
> **per-file function registry** (`ReductionCtx.functions` is built from the current
> file's items; only MACROS have a cross-file `imported` registry). So at the
> definition site there is no in-file caller to inline against (Pass 2 refuses), and
> at the caller's site `reducer.function` can't see the cross-file helper's source.
> My within-file inline works (it drained the in-file helpers); the 516 need a
> **whole-program / cross-file function registry** (the analogue of the macro
> `imported` registry) threaded into `lift_file`, plus the cross-file
> inlining-inflation accounting. That is the supervised architectural step for this
> bucket — distinct from the per-assert opaque capabilities, which are done.
> CONFIRMED: the production RPC (`rust_test_assertions_rpc`) ALSO lifts per-file
> (`lift_file_with_options` per file, per-file `collect_fns`), so this is a REAL
> pipeline gap, not a sweep artifact. MEASURED (and reverted): I BUILT the cross-file
> `FnRegistry` (owned `Rc`, mirroring the macro `imported` registry; 82 corpus fns
> indexed) and wired it into `lift_file_with_imports` + the sweep — and it drained
> **0** (discharged unchanged). So a caller-side cross-file registry ALONE is
> insufficient: the "reachable only via inlining" refusal is emitted at the
> helper's DEFINITION-site Pass 2 (per-file), which persists regardless of whether a
> caller in another file could now inline it (double-count), AND no caller-inline
> fired (the gate/structural reason unpinned this deep). The real fix needs
> **global, call-site-aware accounting** — suppress the def-site refusal when the fn
> is inlined somewhere in the corpus — not just a definition registry. That is the
> supervised architectural step; the `FnRegistry` head-start is saved
> (`/tmp/capability-crossfile-fnregistry.patch`, 281 lines).
> Prior baseline line, for reference: discharged 5088 / refused 201 / unclassified
> 1082 / inactive 58. Sound progress landed: honest accounting
> (Inactive + temporally-unstable-terminal), and 2 of the 3 body-level capabilities
> the unclassified set bottoms out in — **statement-position helper inlining** and
> **pure let-substitution** — both tested. The headline is unchanged because the
> ~1071 remaining is gated on capability #1, **higher-order closure/generic-body
> inlining** (the 517 flt2dec helpers + ~150 term-position closures): a mis-lift
> there is a MASKED-CONTRADICTION falsePass the consistency sweep cannot catch. I
> BUILT #1 soundly anyway (β-reduction + collector-recurse, with a masked-contradiction
> guard test that PASSED — it does not forge) and MEASURED it: inlining ALONE moved
> unclassified 1082→**1094 (worse)** + doubled inflation, because each inlined body
> hits the NEXT gap (closure-adaptor→bin-1, `&mut`-closure) per callsite. Reverted
> (saved: `git stash` + `/tmp/capability1-inline-headstart.patch`). **Measured
> conclusion: #1 is necessary-not-sufficient — it must land WITH closure-adaptor
> lifting + `&mut`-as-opaque as ONE coordinated change**, gated on unclassified
> actually DROPPING. That is the supervised step. Below: the diagnosis, the plan, and
> the measured dead-ends (comparison-op + inline-alone) that bound it.



## The target (closure invariant)

For the stdlib (rust 1.96.0 coretests) corpus, drive **`unclassified = 0`**. Not
`refused = 0` (terminal refusals are earned and stay), not `discharged = 100%`
(some asserts genuinely refuse). The endgame is the **totally-classified ledger**:

```
total  =  discharged  ⊎  refused(terminal)  ⊎  inactive
          unclassified = 0          (no load-bearing AST node un-judged)
          unaccounted  = 0          (no silent drop; tighten the current -51)
```

A CID over that ledger is the closure artifact: every door labelled, no junk
drawer. Until `unclassified = 0`, the ledger CID certifies a completeness it does
not have.

## Terrain re-confirmation (2026-06-14) — per-bucket dead-end map

Re-measured (`coretests_sweep <toolchain>/library/coretests/tests --rustc-cfg`):
discharged 5220 / unclassified **950** / inactive 58, `genuinely unreached
(SILENT): 0` — the floor (no silent drop) is intact. Walked every top
unclassified bucket against the corpus + lifter source. **Every remaining bucket
routes through exactly one of three walls; none has a sound, mechanically-isolated,
autonomous-safe path to *discharge*. Logged here so the supervised campaign targets,
not re-surveys.**

**Wall A — higher-order / construction-semantics body (closures, constructor-method
chains, `format!`).** A
shared-path term/body change; a mis-lift here is a MASKED-CONTRADICTION the sweep
cannot catch (it only catches false-UNSAT + silent drops). Buckets:
- `38` *nested in an unlifted expression statement* — the `other` arm already
  recurses unconditional blocks + monotonic helper-inlines (lib.rs:1820-1930); the
  residue is `recv.method(|x| { assert..})` closure/method-chain forms.
- `73` *assert_eq!: unsupported term* (largest non-cross-file) — adding the missing
  term operator is the SAME shared-path edit that regressed `negated_call_result_…`
  when comparison-ops were added to `term_binop_name` (reverted). Regression-prone.
- `44`+`16`+`6`+`3` *for/adaptor over a literal range/array (bin-1)* — domain IS
  pinned (precondition met); body-by-body audit (2026-06-14) shows the bodies are
  **NOT** mostly `format!` (that is only the `fmt/num.rs:274` subset). The dominant
  shapes are: **(a) constructor-method-chains** — `Big::from_small(1).mul_pow2(i)
  .bit_length() == i + 1` (bignum.rs:202/220/224); RHS `i+1` IS pinned arithmetic
  over the loop var, only the LHS construction chain is the wall → **rung 3 /
  Voltron construction-semantics**, and `Big`/`Big32x40` are cross-file types so it
  is ALSO Wall B; **(b) cross-file helper calls** — `memrchr(needle, &data[start..])`
  (slice.rs:1825), `round_down_imprecise((i as f32).log10())` (int_log.rs:136) →
  Wall B; **(c) string-method chains** — `from_u32(i).unwrap().to_string()
  .to_ascii_lowercase()` (ascii.rs:40). So this bucket's supervised need is
  **construction-semantics + cross-file accounting**, NOT a formatter model —
  redirecting the earlier "format! output" characterization, which was wrong.

**Wall B — cross-file inlining (needs corpus-wide accounting, the M1 restructure).**
- `516` *reachable only via call-site inlining* — the architectural bucket (see
  STATUS header; def-site Pass-2 refusal is per-file, FnRegistry-alone drained 0).
- `22` `assert_almost_eq!` + `9` `assert_chunks!` *unsupported assertion macro* —
  NOT a registry-scan gap. Both macros are defined nested-in-fn
  (`num/flt2dec/estimator.rs:7`, `str_lossy.rs:3`). Even once expanded they
  dead-end: `assert_almost_eq!(estimate_scaling_factor(1,0), 0)` →
  `assert!(expected == actual || expected == actual+1)` where `actual` is an
  **unpinned cross-file fn call** (Wall B in disguise); `assert_chunks!` →
  `$string.utf8_chunks()` iterator over **runtime bytes** (bin-2). Expanding them
  relabels unclassified→unclassified, no discharge. **Do not chase the registry
  scan — it buys nothing.**

**Wall C — genuinely conditional / runtime (correctly held; refusing is right).**
- `32` *let-initializer expression* — the unconditional-block case already recurses
  (lib.rs:1453); these are genuinely conditional/closure inits.
- `30` while / `8` if / `7` match contexts — not unconditional point-wise.
- the bin-2 *opaque collection* refusals — runtime data, not source literals.

**Net:** no sound discharge win is isolable from (A) a regression-prone shared-path
term/closure-body change whose failure mode is an un-catchable masked contradiction,
or (B) the cross-file corpus-wide-accounting restructure. Both are the supervised
steps already named in the STATUS header. Holding at 950 rather than push an
unsupervised masked-contradiction risk to main — the 64 bytes must not lie.

## Progress log (2026-06-13 overnight, --rustc-cfg baseline)

Measured with `coretests_sweep --rustc-cfg` (the canonical config; without it 178
cfg-gated asserts read as ambiguous — a measurement artifact, now fixed).

- **Honest accounting** (commit 3cbf69936): `Disposition::Inactive` splits out
  cfg-disabled asserts (58 — not this target's universe, not work); `temporally
  unstable` joins the terminal whitelist (a source property). discharged 5088,
  refused 201, unclassified 1161→1082, inactive 58.
- **R7 statement-position helper inlining** (commit 8ace70802): bare `check(2);`
  calls to assert-bodied helpers inline per-callsite (β-reduction). Sound + tested.
  Fires for simple helper bodies; drained 0 on stdlib because the 517 here are the
  **complex flt2dec helpers** (`F: FnMut` closure params, nested fns) it correctly
  declines.
- **Comparison-ops in term position** — ATTEMPTED, REVERTED. Adding `<`/`<=`/`>`/
  `>=` to `term_binop_name` discharged +11 (`a[0] < b[0]`) but diverted
  `!(value() < 3)` off the comparison-ATOM path, breaking euf-coalescing of a
  negated comparison with its positive sibling (a guard test). Parked with an
  in-code NOTE; needs a fix that routes top-level/negated comparisons to atoms
  before the term ctor.

**MEASURED RESULT — capability #1 (inlining) ALONE is net-negative; it must land
WITH closure-adaptor lifting.** I built the sound, contained version (`substitute_stmts`
β-reduction + recurse the unchanged collector on the substituted body; masked-
contradiction guard test passed — inlining does NOT mask contradictions) and *measured*
it on stdlib rather than assume. Result: discharged 5088→5093 (+5), refused 201→235
(+34), **unclassified 1082→1094 (+12, WORSE)**, inlining-inflation 52→103 (doubled).
The inlined bodies hit downstream gaps PER CALLSITE — `check`'s `.all(closure)` over a
now-literal slice → bin-1 (still unclassified, ×callsites); flt2dec's `to_string(&mut f_,
…)` → `&mut`-closure residual. So inlining replaces each "reachable only via inlining"
refusal with MORE unclassified instances at the next gap. Reverted (the work is saved:
`git stash` "capability-1 inline head-start" + `/tmp/capability1-inline-headstart.patch`,
280 lines). **Conclusion: inline is necessary but not sufficient — it must be paired with
closure-adaptor lifting (`.all`/`.any`/`.map` over a literal/pinned collection → quantified
body) and `&mut`-as-opaque, landed together, or it multiplies the work.** That is the
shape of the supervised capability-#1 session: inline + closure-adaptor + &mut-opaque as
ONE coordinated change, gated on unclassified actually dropping (not just shifting) and
the masked-contradiction guard.

**UNIFYING FINDING — the 9 surface rungs collapse to ~3 body-level capabilities.**
The loop lifter (`try_lift_for_loop_forall`) already unrolls literal arrays /
quantifies ranges and substitutes the loop var; it refuses (→ bin-1) only when the
BODY hits `body_skipped` — i.e. the body contains a non-liftable term. Likewise the
helper-inline refuses when the body won't reduce, and the branch/let/nested buckets
are the same. So bin-1 loops (60), complex helpers (517), branch (45), nested (38)
are NOT independent rungs — they are **downstream consumers** that drain
automatically once the body-level gaps close. The whole ~1071 bottoms out in THREE
body-level lifting capabilities:
  1. **Higher-order inlining** (closures `|x| ..` as adapter args / helper params,
     generic+closure helper bodies) — the dominant mass (≈670), the hard core.
  2. **Term vocabulary** (non-closure `unsupported term`/operator — the genuinely
     missing lowerings, e.g. term-position comparisons done right).
  3. **let / nested-expr handling** in a reduced body (`let x = e;` substitution,
     asserts nested in expression statements).
Close those three at the BODY level and the surface rungs follow. All three are
shared-path, regression-prone (cf. the comparison-op revert), and a mis-lift here
is a MASKED-CONTRADICTION falsePass the consistency sweep does NOT catch (it catches
false-unsat, not false-discharge). So they must be done SUPERVISED, one capability
at a time, gated on the full guard-test suite — not forged unsupervised.

**Empirical finding — the remaining ~1071 is mostly HIGHER-ORDER, not micro-lowerings.**
The two biggest buckets (517 complex helpers + ~150 closures-in-term-position) are
the SAME core: lifting requires inlining closures / generic+closure helper bodies
(higher-order β-reduction, possibly iterator-comprehension lifting). That is real,
regression-prone work that must be done SUPERVISED with the consistency-sweep
falsePass net — not forged overnight. A chunk of the flt2dec 517 may further prove
**terminal (bin-2)** once inlinable, because their asserts are about *runtime
formatter output*, not source literals — but we cannot claim that reason honestly
until we can inline far enough to see it, so they correctly stay `unclassified`
(not refused) today. The moderate buckets (bin-1 loop bodies 60, let-init 32,
nested-expr 38, branch 45) are tractable but each risks the same kind of
keying/coalescing side-effect the comparison-op attempt hit; do them one at a time,
each gated on falsePass=0 + the full guard-test suite.

## Where we are (sweep, commit ef1bb4d7c)

```
discharged   4990   78.2%
refused       171    2.7%   (terminal: bin-2 runtime 103, ambiguous-temporal 49, bignum 19)
unclassified 1267   19.9%   <-- this document drains this to 0
unaccounted   -51           (no silent drops; inlining over-count, to be tightened to 0)
```

Each rung is a transformation φ (the homomorphism catalog) that moves a bucket OUT
of `unclassified` into `{discharged | refused(terminal) | inactive}` by its pinning
gate. Draining ≠ all-discharge: a rung splits its bucket — pinned inputs discharge,
genuinely runtime/effectful/dynamic residue becomes a *terminal* refusal.

## The rungs, by leverage (count drained, cumulative)

| # | drains | cum | rung | φ | gate → outcome |
|---|--------|-----|------|---|----------------|
| 1 | **521** | 41% | **R7 call-disappearance → queued dig** | `z=h(x); g(z)` keep `z=h(x), result=g(z)`, **queue h,g**; AST walk done when queue empty | helper body source-resolvable → discharge; dynamic-receiver dispatch / known effect → terminal refuse. (These are the `to_*_str_test` / `check` / `next` helpers "reachable only via call-site inlining" — pure TODO today.) |
| 2 | **258** | 62% | **TERM vocab** | teach the missing term/operator a lowering (incl. term-position macro results) | expressible op → discharge; genuinely non-FOL surface → terminal refuse. Per-operator grind, no single switch. |
| 3 | **178** | 76% | **CFG pin (static-env)** | supply the target triple; resolve `cfg!`/target-gated asserts | a missing INPUT, not a lifter feature — cheapest bang. Pinned cfg → discharge; truly target-divergent → per-target verdict. |
| 4 | **64** | 81% | **R4f loop finite-domain body** | `for x in <literal domain>` → `∀x.(guard ⇒ body)` (the forall lifter already exists; body not yet point-wise) | body lifts → discharge; opaque element data → terminal (bin-2). |
| 5 | **45** | 82% | **R4 branch partitioning** | `if g {A} else {B}` → `g ⇒ out=A ∧ ¬g ⇒ out=B`; with pinned `self.mode` the branch collapses at callsite | guard pinned → discharge; opaque-runtime guard → terminal refuse. |
| 6 | **39** | 86% | **R8 macro type/effect split** | classify `macro expanded to no liftable`: type-level → inactive; effectful → terminal | removes a mixed bucket; no value asserts lost. |
| 7 | **38** | 88% | **R1 nested-expr walk** | lift asserts nested in an expression statement (fluent pinning into the enclosing term) | sub-expression pinned → discharge. |
| 8 | **32** | 91% | **R5 let-init projection** | `let x = <expr>; ..x..` → bind/project `x` to its pinned term | pinned init → discharge; opaque/mutated → refuse. |
| 9 | **31** | 93% | **MAC teach** | lower the remaining assertion macros (`assert_almost_eq!`, `assert_chunks!`, ...) | one accounting unit per source macro. |
| — | **111** | 100% | **tail** | SRC resolve helper source (20, or prove terminal-external) · WALK totality-gap (11) · FLT float refine (9, several already ok) · R5p closure-predicate (8) · CON const-block (6) · PAT pattern (5) · R2 alias/SSA (4) | each small, mostly an existing rung's edge case. |

**Three rungs (R7 + TERM + CFG) = 76% of all remaining work.** R7 alone is 41% and
is the most mechanical — it's the queued-dig you already named.

## Order (leverage × tractability)

1. **CFG (178)** first — cheapest, it's an input not a feature; clears 14% by
   supplying a target triple and resolving cfg-gated asserts.
2. **R7 call-queueing (521)** — the dominant lever; build the dig worklist
   (resolve helper source → inline at callsite → lift body → recurse until queue
   empty), with dynamic dispatch as the terminal-refuse leaf.
3. **TERM (235)** — grind the operator vocabulary; each unsupported term either
   gets a lowering (discharge) or a "not expressible in FOL" terminal refusal.
4. **R4 family (110)** — branch partitioning + finite-domain loop bodies (one
   mechanism: `guard ⇒ out`, finite/non-quantified case of the forall lifter).
   **ATTEMPTED + REVERTED 2026-06-14 (empirical):** implemented the hard-gated
   `if <effect-free guard> { Pᵢ }` → `∧ implies(g, Pᵢ)` (no else, no if-let, pure
   guard, `implies`/IR support confirmed present). Result: **0 corpus drain** (the
   coretests if-guards are `.len()`/method/`cfg!`/runtime — all rejected by the
   effect-free gate or non-lifting) AND it broke `assert_in_if_branch_is_refused_not_lifted`,
   which encodes the intentional soundness judgment: a conditional whose guard is NOT
   pinned makes `implies(g, false)` VACUOUSLY SAT, hiding a false body-assert — a
   false-pass the consistency sweep CANNOT catch. So R4 is **empirically confirmed
   supervised**: it is sound only when the guard is provably PINNED (so `implies` either
   collapses to `Pᵢ` or to vacuous-true for a dead branch); a free/opaque guard is the
   sweep-blind false-pass. The supervised version must gate on guard-PINNEDNESS (not just
   effect-freedom) and prove the guard collapses. Reverted; floor stays 883.
5. **Tail (193)** — R8 split, R1 nested, R5 let-init, MAC, then the long edge cases.

## Done means

After every rung, re-run `coretests_sweep`. The milestone is met when it prints
`unclassified 0` with `unaccounted 0`, and `refused` is a *short, debunk-proof*
list of source-property reasons (runtime data, dynamic dispatch, values outside the
sort). At that point the ledger CID is a real closure artifact: 64 bytes over a
house with every door labelled.

> **AGENTS LANDED + VERIFIED (2026-06-14, pushed through `2a531a105`).** Both parallel drains merged onto
> `kit/rust-source-ledger`, then the metric was made reproducible and the deltas independently re-measured.
> *Reproducible* numbers (3/3 byte-identical runs after the reproducibility fix below):
>
> | tree | discharged | unclassified | dissolved | refused | SILENT | unaccounted |
> |---|---|---|---|---|---|---|
> | baseline `8b95e84b9` | 5831 | **332** | 261 | 208 | 0 | −52 |
> | integrated A+B+fix | 5884 | **279** | 261 | 208 | 0 | −52 |
>
> **The real, reproducible drain is −53, and it is ENTIRELY B's flt2dec lifter** (flt2dec bucket 105→52).
> `dissolved` is *unchanged* at 261 — so the −53 went via the symbolic LIFTER (real FOL), not evaluation.
> **A's call-site-inlining commit `3debf6070` drains 0 on the real corpus.** Its branch-reported "+13
> (332→319)" was an artifact of the *flaky* dissolved metric (jittered 261–293 before the fix); under the
> now-reproducible metric A contributes nothing. char.rs (A's apparent win) is identical baseline-vs-
> integrated (dissolved 28, unclassified 0) — it was already fully accounted, so it could not have
> drained. The corpus still has **128 [unclassified] "reachable only via call-site inlining"** asserts
> (emitted by the lifter at `lib.rs:938`); A's `collect_helper_call_inlinings` does NOT fire on them.
> A's machinery is sound + unit-tested + causes no regression (SILENT 0, unaccounted −52, CID conserved),
> but is presently 0-drain infra. RESOLVED (sample-traced via `--json` ledger): the 128-bucket is
> **legitimately excused, NOT a wiring gap.** Its members are `check` (iter/traits/iterator.rs) and
> `test_chain` (iter/adapters/chain.rs) — helpers that iterate OPAQUE/RUNTIME data and use the `Unfuse`
> user type + fn-pointer params. They are bin-2 universes (∀x over runtime values), not closed points;
> A's `helper_carryable` CORRECTLY refuses them. The only carryable-arg helpers (char.rs `lower`/`upper`)
> are already dissolved by the existing per-fn `collect_dissolvable` path, so call-site inlining has no
> incremental target in THIS corpus. A's commit is therefore sound-but-redundant infra. **Keep-or-revert
> is a judgment call left for T** (not reverted unilaterally overnight; no regression either way).
>
> **Reproducibility fix `2a531a105` (kept, real win for verification integrity):** the dissolve dir reused
> fixed harness filenames, so a sequential sweep hit ETXTBSY overwrite races → non-reproducible dissolved
> count (261–293). Fix = per-source-hash unique filenames + 3-try compile retry + cleanup. Count unchanged
> vs pre-fix integrated tree; jitter gone. SOUND: real `error[E####]` never retried; successful compile of
> exact source is ground truth; double-run guard intact. 276 tests green.
>
> **NEXT LEVERS (designed 2026-06-14 PM).**
> Floor now 279. Post-integration levers (all
> touch closed_eval -> serialize): (1) MACRO-CARRY — a local `macro_rules!` (e.g. estimator.rs
> `assert_almost_eq!` wrapping `estimate_scaling_factor(LIT,LIT)` + tolerance) is closed stdlib sugar;
> carry the macro_rules! def into the harness + dissolve (22). (2) USE-IMPORT-CARRY — carry the source
> file's top-level `use` items into the harness prelude (unblocks asserts needing imports like
> `core::num::imp::flt2dec::estimator::*`, `Ordering`). Genuinely TERMINAL (no lever): bin-2 [refused]
> ~107 = iterator/for over RUNTIME collections = universes over runtime values (can't run forall x).

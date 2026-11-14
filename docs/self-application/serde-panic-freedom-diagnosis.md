# Serde panic-freedom (D-lib) — full diagnosis, 2026-05-31

## HANDOFF — START HERE (ready-to-dispatch, ~1-2 hrs fresh)

State: branch `serde-finish`, clean tree. K (e2e panicSafe) = 0, honestly.
Root cause LOCATED, verification UNBLOCKED. Everything below is detail; this is the
executable plan.

THE BUG (single): the panic obligation for `f`'s `serde_json::to_string(v).unwrap()`
is built as `(producer_post) -> (consumer_pre)`. `consumer_pre = is_ok(_h0)` (correct,
result_unwrap pre). `producer_post` = the to_string BODY-EQ contract
`=(_h0, to_string(value))` instead of the serde_json_to_string_value TOTALITY
`is_ok(_h0)`. So the implication is `(_h0 = to_string(value)) -> is_ok(_h0)` -> z3
unsat. With the totality post it's `is_ok(_h0) -> is_ok(_h0)` = valid -> panic-safe.
Cause: `locate_producer_post` (sugar-verifier/src/handshake.rs:120) follows the
single `bridges_by_symbol[inner_name]` bridge to ONE target contract and takes its
`post`; the body-eq won the per-symbol slot. Suspect the free call
`serde_json::to_string` lifts under ctor `method:to_string`, keying the totality
bridge away from the lookup.

STEP 1 (diagnose, ~20 min, READ-ONLY): on battleaxe, `bash /tmp/serde_e2e2.sh`
re-mints stage3-serde fresh, then `sugar dump <proof> --json` + a script to print
EVERY entry of `bridges_by_symbol` (key) and its target contract's `post`. Confirm:
is there a bridge whose target post is `is_ok(result)` (the totality) for the
to_string producer, and under which key? (`to_string` vs `method:to_string` vs
`serde_json_to_string_value`.)

STEP 2 (fix, soundness-adjacent, ONE of):
  (a) KIT-SIDE (preferred, safer, "semantics in the kit"): if `serde_json::to_string`
      free call is mis-lifted as `method:to_string`, fix the lifter
      (sugar-walk/src/bin/walk_rpc.rs visit_expr_call vs visit_expr_method_call)
      so the free call keys where the totality bridge lives.
  (b) VERIFIER-SIDE: make `locate_producer_post` prefer, among the producer's
      bridges/contracts, the one whose post predicate unifies with the consumer
      pre's predicate family (is_ok) over a structural `=`.

STEP 3 (verify, NOW POSSIBLE — file/line surfaces in rows):
  `sugar mint --project examples/stage3-serde-totality-fixture --out examples/stage3-serde-totality-fixture`,
  then `sugar prove examples/stage3-serde-totality-fixture --json`
  (prove reads the fixture's root `.proof` and `.sugar/imports`; there is no `--with`)
  REQUIRE: row `file=src/lib.rs line=25` (f) -> status discharged/panicSafe;
           row `file=src/lib.rs line=38` (g, MyStruct) -> undecidable;
           global falsePass=0, silentlyDropped=0.
  ALSO run the panic-freedom-fixture (BREAK 2, syntactic guard) + the full
  sugar-verifier test suite (`bcargo test -p sugar-verifier`). If g flips or
  falsePass>0 or any suite test regresses -> REVERT.

DO NOT: rush this exhausted; specialize consumer_pre (empirically wrong, breaks the
forall build_implication needs); touch the shared non-panic discharge path.

---


Goal: f `serde_json::to_string(&Value).unwrap()` → PANIC-SAFE (K=1); g
`to_string(&MyStruct).unwrap()` → UNDECIDABLE; falsePass=0. Stalled 5 agents.

## Fixed today (committed on `serde-finish`, e13763201) — all verified at their layer

1. **Fixture manifest** `examples/stage3-serde-totality-fixture/.sugar/lift/rust-implications/manifest.toml`
   was missing `method = "sugar.plugin.lift_implications"` and `phase = "consumer"`.
   So `mint` ran `bind_lift`, the implication lifter (host of the RA oracle) NEVER ran.
   This was the actual 5-agent blocker. With it fixed, the oracle resolves both
   unwraps to `result_unwrap` and emits 3 bridges + 1 honest lift-gap (g's to_string).

2. **`mint_bridge` dropped the lifter's `callsite`** (`sugar-claim-envelope`). Added
   `BridgeCallsite` + carry it into the bridge header (NOT into `bridge_content_cid` —
   callsite is not bridge identity). Verifier now reads `panic_site=true`.

3. **prove path missing the D-lib injection.** `callee_post_guard_fact` (the
   is_ok-totality guard supply) lived only in `cmd_verify`; the `prove` path
   (`runner.rs::work_one`, which the scoreboard uses) never called it. Wired in.

## Phase-0 scaffolding (no-silent-failure)

- Plugin subprocess stderr now **inherits by default** (was `Stdio::null()` — the
  thing that hid all of the above for five investigations). `SUGAR_PLUGIN_STDERR=null` to silence.
- Always-on `warn!` when a `method:`-seam bridge reaches the verifier without
  callsite provenance (mint-drop smoke detector), `enumerate_callsites.rs`.
- All new diagnostics via `tracing`, not `eprintln`.

## The remaining layer (K still 0) — precisely located, NOT yet fixed

f's contract post is `=(result, method:unwrap(to_string(v)))`. `enumerate_callsites`
DOES create the unwrap callsite with `panic_site=true, arg_term=to_string(v)` (ctor) —
verified in logs (2 ctor-arg method:unwrap callsites: f and g). The 2 var-arg
method:unwrap obligations that reach the UNGUARDED panic path are the shim formals
(noise), not f.

f's ctor-arg callsite enters `runner.rs::work_one` and is consumed by the
**producer-consumer / implication-composition tier** (runner.rs ~1286-1340):
`consumer_pre = is_ok(arg)` (result_unwrap pre, instantiated), and
`producer_post = locate_producer_post(to_string(v))`. Tier-0c calls
`pool.can_implies(post_hash, pre_hash)`. That lookup fails (no implication memento
in the pool), the callsite falls through this tier, and never reaches the panic-guard
discharge (runner ~1493) where the D-lib `callee_post_guard_fact` injection lives.
So `callee_post_guard_fact` is never invoked for f (logs: it only ever sees the shim
ctors Some/Ok/Err, never `to_string`). Result: f stays undecidable, K=0.

### Likely sound fix (next focused PR — gate on the discrimination test)

For f, `producer_post` and `consumer_pre` are the SAME formula: `is_ok(to_string(v))`
(the to_string totality post) and `is_ok(to_string(v))` (the unwrap pre specialized
to the same receiver). So the implication `producer_post → consumer_pre` is the
reflexive `P → P`, trivially valid.

Candidate: in tier-0c (runner.rs ~1330), discharge when `post_hash == pre_hash`
(reflexive: the producer guarantees EXACTLY what the consumer requires). This is
sound (`P → P`), and it discriminates correctly: g's `to_string(&MyStruct)` has NO
totality post (generic, `is_ok || is_err` or none), so `producer_post != consumer_pre`,
no reflexive match → g stays undecidable, falsePass=0 preserved.

VERIFY FIRST (one instrumented run): log `producer_post` and `consumer_pre` for the
2 ctor-arg method:unwrap callsites. Confirm f's are byte-identical `is_ok(to_string(v))`
and g's differ/absent BEFORE implementing. If they are NOT identical, the fix is the
alternative: route the ctor-arg panic callsite to the panic-guard block (where the
D-lib injection already lives) instead of letting tier-0c swallow it.

### Hard gate for any attempt

Re-run the e2e (`/tmp/serde_e2e2.sh` on battleaxe): REQUIRE f → panicSafe, g →
undecidable, falsePass=0, silentlyDropped=0. If g flips or falsePass>0, REVERT — this
is the verifier soundness core.

## UPDATE — the discharge cascade is the real obstacle (deepest finding)

Instrumenting `work_one` further (a `panic_site` probe at runner.rs:1288, since
removed) showed it fires ZERO times even though `method:unwrap` panic obligations
are emitted and "routing to guard-discharge" logs for `target_has_pre=true`. So the
real panic callsites reach NEITHER the producer-consumer probe (1288) NOR the D-lib
injection added in commit e13763201 (~1493). `work_one` is a multi-path cascade with
several early returns (tier-0 hash, tier-0c implication-composition, the
`!target_has_pre` body-discharge branch via `extract_body_obligation`, the panic
block) and the real callsites are discharged/abandoned by one of the earlier paths.

**Consequence:** commit e13763201's runner D-lib injection is in a branch the actual
serde callsites do not traverse (harmless — refuse-floor intact, falsePass=0 — but
inert for K). Closing K>0 requires READING THE WHOLE `work_one` (runner.rs
~1131-1700) end to end, mapping which path the `panic_site=true, arg_term=ctor`
callsites actually take, and applying the D-lib guard fact (or the reflexive
`producer_post == consumer_pre` discharge) AT THAT PATH. This is a discharge-cascade
design task in the verifier soundness core, not a localized patch — do it on a fresh
head with the discrimination test as the hard gate, NOT exhausted.

The reflexive-discharge idea (sound `P -> P` when the producer's post is byte-identical
to the consumer's pre) is still the most promising mechanism; it just has to be wired
into the path the callsites actually reach.

## Phase-0 gap CLOSED: `doctor` now catches this footgun

DONE (committed): `sugar doctor` now HARD-fails (exit 2) when a kit's consumer
surface is mis-wired. walk_rpc's `initialize` capabilities self-declare
`consumer_surfaces: { "rust-implications": { method, phase } }` (semantics in the
kit, so doctor stays language-blind); doctor's Check 5 spawns each plugin, reads
that, and verifies the manifest's `method`/`phase` match. Verified on
stage3-serde-totality-fixture: broken manifest (method+phase removed) -> exit 2 with
"add both lines"; fixed -> exit 0. This catches the exact omission that cost five
agents a day, BEFORE a silent empty-set attestation.

### Original gap (now closed; kept for context)

## Phase-0 gap was: `doctor` did not catch this footgun

`sugar doctor --target <kit>` exists and runs, but its checks are: TOML parse,
plugin-command binary exists, imports count, oracle reachability. It does NOT catch
the exact footgun that cost five agents: a `lift` manifest that omits `method` and
`phase`, so a consumer surface (rust-implications) silently runs the default `lift`
producer method and the implication lifter never fires.

Catching the OMISSION case soundly AND language-blind needs `doctor` to spawn each
plugin's `sugar.plugin.describe` RPC and cross-check the manifest's effective
`(method, phase)` against the capabilities the plugin advertises for that surface —
e.g. "plugin advertises a consumer method for surface S but the manifest runs the
default producer `lift`" -> WARN/FAIL. A name/heuristic check (e.g. "*-implications")
would violate language-blindness or over-warn on legitimate producers.

CONFIRMED SHAPE: `describe` (walk_rpc `initialize_result`, ~line 2109) today returns
only `capabilities.authoring_surfaces = ["rust","rust-bind","rust-walk-contracts"]`.
It does NOT advertise the RPC methods the plugin dispatches (`lift`,
`sugar.plugin.lift_implications`, `sugar.plugin.recognize`, ...) nor which
surfaces are consumers. So the work is two-part: (1) extend `describe.capabilities`
to add e.g. `rpc_methods: [...]` and `consumer_surfaces: ["rust-implications", ...]`
(plugin self-reports; semantics stay in the kit); (2) `doctor` cross-checks each
manifest's effective `(method, phase)` against that. This is a scoped Phase-0
(scaffolding) task, independent of the K cascade work, with NO falsePass risk (it is
a CLI diagnostic).

## SYSTEMIC FINDING: e2e panic discharge is broken for syntactic guards too

The remaining cascade bug is NOT serde/D-lib specific. The canonical
`examples/panic-freedom-fixture` (`guarded_unwrap`: `if opt.is_some() { opt.unwrap() }`,
`unguarded_unwrap`: `opt.unwrap()`) is correctly wired (manifest has
method=lift_implications + phase=consumer), yet its end-to-end `prove` scoreboard is:

    {"panicSafe": 0, "reflexive": 28, "undecidable": 133, "falsePass": 0}

`panicSafe=0` -- the SYNTACTIC-guard case does not discharge panic-safe e2e either.
So the GOAL's "Mechanism proven on a fixture (guarded->panic-safe; deterministic test
green)" refers to the UNIT test (a hand-built `CallSite{panic_site:true, guard_facts}`
in cmd_verify/body_discharge), NOT the mint->prove pipeline. The whole e2e panic
discharge path (the `work_one` cascade) drops panic callsites before the guard
discharge for both the syntactic-guard and the D-lib paths. Fixing the cascade
(see above) should lift BOTH at once -- the fix is not serde-specific.

This is exactly the "green unit test, broken product" gap the three product surfaces
exist to expose. Update the on-main GOAL "NOW" line: e2e K=0 is systemic, unit-test-only.

## Golden snapshot: design tension (why it is not a clean now-win)

A golden of the panic-freedom scoreboard is GOAL Phase-0, but the clean target is the
per-site census (`self-check --json`), which is daemon-heavy (warm RA oracle) and not
CI-portable. The daemon-free alternative (raw `prove` on the fixture) is brittle: the
aggregate dischargeSplit mixes in shim-std's own callsites (undecidable=133 is mostly
shim noise) and `prove` rows carry file=None, so the fixture's two functions can't be
isolated for a stable pin. The robust golden therefore wants either (a) self-check
gaining a fixture-scoped per-site mode, or (b) prove rows carrying file/line so the
golden pins just the fixture's sites. Best built WITH the cascade fix so it pins a
meaningful panicSafe>0 delta. Pinning panicSafe=0 now is legitimate scaffolding but
low-value until the cascade lands.

## COMPLETE MECHANISM (work_one routing, runner.rs ~1412) — two distinct breaks

`work_one` routes on whether the panic arg has a producer:

    if (producer_post, consumer_pre) both Some  -> IMPLICATION branch (~1412):
        build_implication_obligation(producer_post -> consumer_pre), solve
    else                                        -> GUARD branch (~1479):
        instantiate::run(resolved, arg_term) THEN cs.guard_facts discharge
        (this is where the D-lib callee_post_guard_fact injection from e13763201 lives)

BREAK 1 -- serde / any panic site whose receiver is itself a call:
  arg = `to_string(v)` HAS a producer (the to_string totality bridge -> post
  `is_ok(result)`), so `producer_post = Some(is_ok(to_string(v)))` and the site
  takes the IMPLICATION branch. BUT `consumer_pre` there is the UN-specialized
  pre `is_ok(formal)` (instantiate only runs in the else branch). z3 sees
  `is_ok(to_string(v)) -> is_ok(formal)` over disjoint terms -> UNSAT. The D-lib
  injection never runs for f (f never reaches the else branch).

BREAK 2 -- syntactic guard (panic-freedom-fixture `if opt.is_some(){opt.unwrap()}`):
  arg = `opt` is a VAR (no producer) -> producer_post None -> takes the GUARD
  branch. But `cs.guard_facts` is EMPTY: the kit's `cf_guarded(is_some(opt), ...)`
  wrapper that enumerate_callsites threads into guard_facts (walk_term ~269) is
  not populating it e2e. Unguarded -> is_some(formal) -> undecidable.

SOUNDNESS-CORE RISK (why this is not a quick patch): the IMPLICATION branch
(~1412) is SHARED with the non-panic eq-discharge tiers. Specializing
`consumer_pre` to `arg_term` there perturbs obligation CIDs / hash-tier lookups
for ALL callsites (the code already warns about this re `instantiate::run`). So
BREAK 1's fix must specialize ONLY the panic-site implication (or route a
producer-post panic_site through the guard branch with the D-lib is_ok fact
instead of the implication branch) without touching the shared non-panic path.

FIX SKETCH (one focused PR, gate on discrimination test f->safe / g->undecidable /
falsePass=0 on BOTH stage3-serde AND panic-freedom fixtures):
  1. BREAK 1: for a `panic_site` callsite that has a producer_post, either
     (a) instantiate consumer_pre to arg_term before building the implication
     (panic-only, so no shared-path CID drift), or (b) skip the implication
     branch for panic sites and use the guard branch + D-lib fact.
  2. BREAK 2: fix cf_guarded -> guard_facts threading so the syntactic-guard
     panic site is GUARDED e2e (verify enumerate_callsites walk_term ~269
     actually receives the cf_guarded wrapper from the lifter output).
  Both lift e2e K together; both are sound-by-construction (specialization +
  syntactic guard are exact), gated by the discrimination test.

## SEQUENCING: #1717 (Phase-1 soundness) must precede the K cascade fix

BREAK 1's fix specializes the panic `consumer_pre` to the call arg, which puts a
`forall <arg-sort>. <pre>` into the SMT-emitted implication. When the arg sort is
OPAQUE (a non-primitive Rust sort), that is exactly the `forall x:<opaque>. ...`
shape #1717 flags: the SMT emitter collapses it to literal `true`, so the negated
obligation is `(not true)` = unsat = a FALSE "cannot panic" (latent false-pass).
The else/guard branch already defends against this with
`instantiate::strip_outer_forall`; the implication branch does NOT. So the K
cascade fix MUST either close #1717 first (encode the opaque `forall` soundly or
refuse, never collapse -- detector: `forall x:<opaque>. false` must be
undecidable) or carry the same strip-outer-forall guard. Per the GOAL's Phase-0 ->
Phase-1 -> Phase-2 order: close #1717 BEFORE turning K from 0 to N, or risk
manufacturing the precise false-pass this whole effort exists to prevent.

## #1717 implementation locator (Phase-1, do FIRST)

Site: `implementations/rust/sugar-ir-compiler-smt-lib/src/lib.rs`. Its
`supported_sorts` are only `Int/Bool/Real/String`; a `forall` quantifying an
OPAQUE (non-primitive) sort cannot be emitted soundly and currently collapses to
literal `true` (the latent false-pass: negated obligation `(not true)` = unsat =
false "cannot panic"). The opacity is already tracked in `OpacityManifest`.

Fix direction is REFUSE (sound-by-construction -- can ONLY remove false-passes,
never add one, so falsePass=0 is safe): when a `forall` body quantifies an opaque
sort, do NOT emit `true`; signal UNDECIDABLE. KEY CONSTRAINT: the refuse must
PROPAGATE emitter->runner as `ObligationVerdict::Undecidable`, not an inline SMT
`true` -- a local return is insufficient; the emit result type / the runner's
interpretation of it must carry the refusal. Detector test (from the GOAL):
`forall x:<opaque>. false` must come out UNDECIDABLE, not discharged.
Then re-run the verifier suite: any test that flips green->undecidable was relying
on the unsound collapse and should be updated to expect undecidable (that IS the
bug being closed). Only AFTER #1717 lands is the K cascade fix safe (BREAK 1
re-introduces an opaque-sorted forall).

## BREAK 1 fix-target REFINED (empirical: my specialization approach is wrong)

Attempted BREAK 1 as "specialize consumer_pre to the arg in the implication
branch" -- EMPIRICALLY WRONG. `build_implication_obligation` (runner.rs:1720)
REQUIRES both post_formula AND pre_formula to be `forall` (errors "pre is not a
forall" otherwise), renames BOTH bound vars to a shared `_h0`, and emits
`forall _h0. (post_body[_h0] -> pre_body[_h0])`. Stripping the forall to specialize
breaks it. And specialization is unnecessary: the builder ALREADY unifies the two
foralls via `_h0`.

So for f, the obligation SHOULD reduce to `forall _h0. (is_ok(_h0) -> is_ok(_h0))`
= trivially valid -> discharged. It is UNSATISFIED, which means
`post_body[_h0] != pre_body[_h0]` after renaming -- the producer post body and the
consumer pre body are NOT both `is_ok(_h0)`. The bug is therefore in ONE of:
  (a) `locate_producer_post` shapes the producer post body as something other than
      `is_ok(<bound>)` (e.g. carries the concrete arg term, or a different
      predicate/sort), OR
  (b) the producer-post and consumer-pre forall SORTS differ, so `_h0` is declared
      at incompatible sorts and `is_ok` is not the same uninterpreted relation, OR
  (c) the rename (`substitute_formula_pub` with post_name/pre_name -> `_h0`) misses
      a binder.

NEXT (fresh head): instrument `build_implication_obligation` to log
`post_body_renamed` and `pre_body_renamed` for a panic site on a CLEANLY re-minted
stage3-serde proof (the probe must run against the SAME proof the mint produced --
state drift across runs masked this tonight). The diff between those two bodies IS
the fix. This is a targeted equality/shape fix in the producer-post construction,
NOT a specialization and NOT touching the shared non-panic path.

## ROOT CAUSE LOCATED (build_implication body diff, fresh-mint instrumented)

Instrumented `build_implication_obligation` to log `post_body_renamed` vs
`pre_body_renamed` on a freshly-minted stage3-serde proof. The non-reflexive diff:

    post_body (producer): =(_h0, ctor "method:to_string"(value))   <- STRUCTURAL EQ
    pre_body  (consumer): is_ok(_h0)                                <- the unwrap pre

So the implication is `(_h0 = to_string(value)) -> is_ok(_h0)` -- z3 cannot prove
it. The producer post is the to_string BODY-EQ contract (`result == to_string(value)`,
a structural identity, useless for panic-freedom), NOT the
`serde_json_to_string_value` TOTALITY contract (`is_ok(result)`). With the totality
post the implication would be `is_ok(_h0) -> is_ok(_h0)` = reflexive = DISCHARGED.

ROOT CAUSE: `locate_producer_post` (handshake.rs:120) does
`bridges_by_symbol.get(inner_name)` -> follows that ONE bridge to its target
contract and takes `.post`. `bridges_by_symbol` holds ONE bridge per symbol; for
`method:to_string` the BODY-EQ bridge won over the disambiguated totality bridge,
so the producer post is the eq, not `is_ok`. (Caveat: the prove was contaminated by
138 shim callsites; confirm on a fixture-isolated run that this post is f's, and
note the arg lifted as `method:to_string` -- verify free-call `serde_json::to_string`
vs method `value.to_string()` lift shape.)

FIX (fresh head, soundness-adjacent, gate on discrimination + verifier suite):
`locate_producer_post` must prefer the producer contract whose post matches the
consumer's predicate family (here `is_ok`) -- i.e. the TOTALITY contract -- over a
structural body-eq. Options: (a) when multiple bridges/contracts exist for the
producer symbol, select the one whose post predicate unifies with the consumer
pre's predicate; (b) fix the bridge-collision so the disambiguated totality bridge
is the one keyed in `bridges_by_symbol` for a panic-relevant producer. g
(MyStruct) has NO totality contract -> no is_ok producer post -> stays undecidable
(refuse-floor preserved, falsePass=0). This supersedes the earlier
"specialize consumer_pre" and "two breaks" framings: the serde break is a single
producer-contract-selection bug in locate_producer_post.

## CORRECTIONS (verified against the current binary)

1. **`file`/`line` surfacing WORKS** (a stale belief earlier in this doc said it
   was dropping). With the callsite-carry fix (e13763201) the minted bridge
   carries `{file, start_line, panicSite}` and `prove --json` rows surface it:
   f's unwrap is `callee=method:unwrap | file=src/lib.rs | line=25`, g's is
   line=38. So per-site IDENTIFICATION for panic sites is in, and K-fix
   verification is UNBLOCKED -- f (line 25 -> must become panicSafe) and g
   (line 38 -> must stay undecidable) are cleanly distinguishable in the row
   output despite the 138-callsite shim contamination. (Per-site {category,
   tier-to-close} naming is still only partial: file/line yes, an explicit
   category+tier field no.)

2. **Refined lead on the producer-contract bug:** the unwrap's arg lifts as the
   ctor `method:to_string`, but f's source is the FREE call
   `serde_json::to_string(v)`, not a method `v.to_string()`. If the free call is
   mis-lifted under a `method:` ctor, the disambiguation-to-totality
   (`serde_json_to_string_value`) keys/targets a different symbol than the one
   `locate_producer_post` looks up (`method:to_string`), so it only finds the
   body-eq contract. NEXT: dump `bridges_by_symbol` keys + each target contract's
   post on a fresh mint; confirm whether a totality-post bridge exists for the
   `to_string` producer and under WHICH symbol. The fix is then either correct
   the free-call lift (drop the bogus `method:` prefix) so the totality bridge is
   keyed where `locate_producer_post` looks, OR have `locate_producer_post` prefer
   a totality-post contract among the producer's bridges. Both verifiable now via
   the line-25/line-38 discrimination.

## Reproduction

Warm-oracle e2e on battleaxe: `/tmp/serde_e2e2.sh` (mints shim-std + shim-serde deps,
warm-daemon mint of the fixture, prove). Debug: `RUST_LOG=warn,sugar_verifier::runner=debug,sugar_verifier::body_discharge=debug,sugar_verifier::enumerate_callsites=debug`.

## DEEPER ROOT (2026-05-31, two agents): line collapse + shared contract, NOT the verifier layer

Two Opus agents attempted the callsite-scoped producer fix. Both correctly refused
to ship unsoundness. Findings:

- Agent 1 (implication form): made f discharge but via the IMPLICATION branch
  (is_ok->is_ok, reflexive), discharge_method=solver-substantive -> report_fmt
  counted it falsePass=2 (panic site + method != panic-safe). Honest, not landable.
- Agent 2 (guard-fact form, the prescribed correction): rerouted to the guard
  branch (method=panic-safe), suite green + 4 discrimination tests. But the e2e
  showed panicSafe=2: g (line 38, to_string(&MyStruct)) ALSO discharged panic-safe
  -- an INVISIBLE false pass, because report_fmt's falsePass counter
  (`panic_site && method != "panic-safe"`) is structurally BLIND to a panic site
  WRONGLY TAGGED panic-safe. Strictly worse than agent 1. Reverted.

THE ACTUAL BLOCKER (upstream of the verifier guard-fact layer):
1. LINE COLLAPSE: `enumerate_callsites` assigns `line=25` to EVERY panic
   obligation -- it reads the line from the per-symbol `method:unwrap` bridge
   (bridges_by_symbol, one bridge) instead of each occurrence's own line. g's true
   site is line 38. So g's panic obligation arrives at the verifier byte-identical
   to f's: same bundle, collapsed line 25, same `to_string` arg ctor, same totality
   target contract. The callsite-scoped key (bundle,src/lib.rs,25,to_string)
   COLLIDES g onto f's totality bridge. NO verifier-side change keyed on the
   proof-as-fed can separate f from g.
2. SHARED TOTALITY CONTRACT: the fixture mint produced ONE `to_string` totality
   bridge (line 25, is_ok totality); there is no distinct non-totality contract for
   g's MyStruct case (the oracle disambiguation that the recipe assumes -- g's stem
   != "value" -> no totality -- did not produce a separate contract).

FIX (a DIFFERENT layer than the verifier guard-fact path):
- (a) Line attribution: each panic CallSite must carry its OWN source line, not the
  per-symbol bridge's line. This is in `enumerate_callsites` / how the
  `method:unwrap` obligation's provenance is threaded from the lifter. The IR term
  is abstract (no span), so the obligation/bridge must carry per-occurrence line and
  enumerate must use it (e.g. via bridges_by_callsite or per-occurrence provenance),
  not the collapsed per-symbol line.
- (b) With correct lines, g@38 resolves to ITS OWN producer (body-eq or none, no
  totality) -> no guard fact -> undecidable; f@25 -> totality -> panic-safe. Then
  re-apply agent 2's guard-fact rerouting (preserved approach).

ALSO A NO-SILENT-FAILURE GAP TO CLOSE: report_fmt's falsePass detector is blind to a
panic site wrongly tagged `panic-safe`. The structural rule trusts that
method=panic-safe is sound. Until line attribution is fixed, that trust is
misplaced. Consider a cross-check: the count of panic-safe sites must equal the
count of sites with a co-located totality producer, or the e2e must assert per-site
(f panic-safe, g undecidable), not just falsePass=0.

GATE for the next attempt: dischargeSplit panicSafe == 1 (f ONLY), g (line 38)
explicitly undecidable, falsePass=0, silentlyDropped=0, verifier suite green. The
falsePass=0 counter alone is INSUFFICIENT (see the blind spot above) -- assert g's
specific row.

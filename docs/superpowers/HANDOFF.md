# Sugar Fleet Coordinator — Durable Handoff

You are the coordinator (Kit) of a Codex worker fleet driving the Sugar/provekit issue board.
You think, dispatch, and merge fast; Codex generates. Read AGENTS.md (repo root) — the IDD
manifesto and the enforcement-ladder section — before doing anything. Then this.

## The one-paragraph model
Generation is cheap (Codex, parallel, relentless). Orientation is scarce (which crime matters,
whether a diff is sound, when a zero is real). Your entire job is converting orientation into
red instruments and detailed briefs fast enough that being wrong is loud and cheap. You do not
gate; you instrument, fire, merge at the measurement boundary, fix forward. Two standing asks
from T: **write the red instrument first; then follow its gravitational pull.**

## Ground truth — never trust your own summaries (learned the hard way this session)
- **CI**: merges outrun the acid suite, so main CI shows "cancelled by supersession" constantly.
  That is NOT green — it is unmeasured. Periodically arm a Monitor that waits for a COMPLETED
  run (`gh run list --branch main --limit 1 --json status,conclusion`) and treat its verdict as
  the real ΔR. A known baseline red existed this session (lifted_proof_loads_through_verifier,
  tracked in #3018) while everything got called "healthy." Don't do that.
- **Relayed verdicts are vendor claims.** Worker PR bodies carry red-first transcripts; they are
  probably honest but you did not run them. When a soundness-critical PR lands, spot-re-run one
  occasionally instead of trusting sixteen in a row.
- **The board is bigger than the crime list.** `gh issue list --state open` is truth. Review bots
  (CodeRabbit/Copilot) file findings on merged PRs — read them; some are real.

## How to drive Codex (this is the load-bearing part)
Codex workers run in iTerm via the codex-iterm MCP. They are spiky: savant code, near-zero
self-situation. Treat them accordingly.

**Tools**: `mcp__codex-iterm__{list_workers, read_worker, spawn_worker, dispatch}`. Load via
ToolSearch if deferred. Model is gpt-5.5 xhigh (their default).

**The dispatch loop:**
1. `list_workers` — read each window's tail. States: working / idle / queued.
2. For an idle worker whose last PR merged: give it the NEXT issue.
3. For a working worker: leave it. A queued message applies when it next stops — the queue IS
   the nudge; don't spam.

**Briefs must be COMPLETE and INLINE** (memory: `$(cat file)` does NOT survive the MCP boundary —
paste the whole thing). Every brief contains, in order:
- Reality sync: "PR #N merged, #issue closed" — spiky workers lose track; tell them where they are.
- Exact worktree path + branch + "verify with git rev-parse --show-toplevel".
- The doctrine (why this is a crime, one paragraph) — orientation they can't be assumed to hold.
- The defect with file:line and a code quote.
- Numbered fix steps naming the in-tree pattern to copy (e.g. "mirror ScalarFloorVisitor::visit_runtime").
- Red-first requirement: write the failing test, confirm it fails on main, then fix, keep transcripts.
- Build/test discipline: `cd <worktree>/implementations/rust && ../../bin/bcargo test -p <crate>` (real $?).
- Delivery: "commit as T Savo <evilgenius@nefariousplan.com>, push, self-PR with Closes #N + transcripts. Do NOT merge — coordinator merges."
- A "Do NOT" list fencing scope (workers wander into adjacent files and other agents' worktrees).
- The recurring gotchas: "never touch files you did not edit in /Users/tsavo/provekit (it holds
  T's pre-existing dirty state); gh 403 = wait ~10min, retry, don't spin."

**Worktrees**: one per issue, `git worktree add ~/provekit-wt/<name> origin/main -b codex/<name>`.
Workers self-PR now (they own commit/push/gh pr create). You merge + delete worktree + redispatch.
Cap ~3 concurrent workers (bcargo/battleaxe is one box; more contends).

## The merge cycle (per worker done)
1. Read PR body — soundness read of the diff (does it match the issue, any correctness risk).
2. `gh pr merge <N> -R TSavo/sugar --merge --admin --delete-branch` (admin-merge OK — CI is
   background telemetry, not a gate; known-red baseline is acceptable, fix forward).
3. `cd ~/provekit-wt/fresh-main-20260701 && git fetch origin main -q && git merge --ff-only origin/main -q`
4. Verify the issue closed (`Closes #N` in the PR does it; confirm).
5. Remove the worktree, add the next, dispatch.
- GitHub rate limit (5000/hr) trips on burst branch-deletes; deletions can lag a window — the
  fleet is unaffected (workers use SSH). Sweep stale `codex/*` branches when the window resets.

## Religion (T's hard law)
- **Everything tracked in GH.** Every finding, quarantine, deferral, campaign phase = an issue at
  decision time. A test marked #[ignore] needs a tracking issue in the same breath (see #3018).
  Plans get epic issues per phase. Close issues only with verification evidence in the comment.
- **The panic/red is sacred.** No softer red for "known debt," no green because a count improved.
  Red after a stable zero is a regression — the most valuable alarm.
- **Instrument before drain.** A frontier auditor lands RED with a pinned R vector; drains ratchet
  it down, deleting pinned rows in the same PR. Never sanction-comment your way to a lower R.

## Where things stand (update this section as you go)
- 2026-07-02 overnight run (T asleep, coordinator autonomous): ~25 PRs merged (#3067–#3162 range).
  ALL audit issues #2981–#3001 + #3010 CLOSED (#3010 spawned dedicated #3147–#3151; #3150 is
  ARCHITECT-GATED on T's mini-interpreter decision — do not dispatch).
- Silent-drop frontier: CLOSED AT ZERO. R 401→0 over 13 slices (#3022/#3023/#3024/#3139 all closed);
  stable-zero gate live in silent_drop_frontier.rs. That campaign is the template for all frontiers.
- Baseline reds: ALL cleared (#3018, #3071, #3085, #3129 verdicts). std-core-showcase GREEN
  end-to-end (first time), 515 vacuity refusals honestly accounted. Masking mechanism found and
  killed: cargo halts at first failing target — every-binary-summary + explicit bin-target runs
  now mandatory in briefs.
- assertion_lift frontier (#3142): instrument live, R 63→41; remaining 41 rows are ALL floor-gap
  classes = #3017 Phase-1 campaign work (item 1 GuardedReturn in flight on 85868).
- Ladder rungs closed: #3050 ObligationVerdict, #3051 AnchoredMember, #3052 MementoCid,
  #3053 SolverSeat, #3054 MemberKind (re-merge in flight after a merge-commit collision — LESSON:
  verify mergedAt non-null BEFORE branch-delete). #3160 (BridgePin) filed, open.
- MonoidFold/CarrierEmbedding design #3125: slices 1-2 landed (#3128/#3136); Duration proves vendor
  correct_sum; #3083 closed.
- Perf: #3039/#3040/#3081 closed — RSS floor ARMED in CI (ref 33096 KiB, self-hosted Linux).
  #3041 (typed pool) gates met; plan-doc-first PR in flight on 85870.
- Py-kit campaign: numpy+pandas audit done (R=27,606), 35 issues #3090–#3124 filed. #3090 opacity
  instrument closed; constant floors #3091–#3094 in flight on 85873. Debts #3147–#3151 from #3010.
- Codex usage limits: fleet stalled ~01:30–02:09 PDT once; on "usage limit" tails, note reset time
  and re-dispatch full briefs after it.
- CI: acid runs on main have NEVER completed tonight (merge-train supersession) — verdict monitor
  armed; treat main as unmeasured until one lands.
- KB: memory_lint.py live, honestly red at dangling:92 (41 never-written memories; top target
  red_gate_is_not_a_gate ×10). T's call: write top 8 or strip. 2026-07-02: T explicitly PAUSED
  this — leave as-is until he has focus; do not draft or strip autonomously.

## LIVE FLEET MAP (2026-07-02 ~11:35 PDT — the state git/gh does NOT hold; re-list_workers to confirm)
- 85870 → worktree ~/provekit-wt/typed-pool-3, branch codex/pydantic-loss-record → #3147 (pydantic is_required loss record — LAST #3010 debt not yet merged). Lane history: #3041 typed-pool CLOSED w/ evidence (S1-S7, three stable-zero gates), #3160 BridgePin, irterm S1 #3242 (byte-drift harness tools/irterm-boundary/byte-compat.sh; 14 sites pinned), #3148 dig-universe. Lane after: #3122 value-pin floors / #3123 Enum pin, or vocab S1 #3232 when T blesses.
- 85868 → worktree ~/provekit-wt/boundvar-floor, branch codex/irterm-s2 → #3192 irterm Slice 2 (THE RISKY ONE: promote algebra crate out of sugar-lift-rust-tests + term_boundary.rs; byte-drift=0 bar; instructed to STOP and report if the crate graph fights). #3017 PHASE 1 COMPLETE — all 10 items landed (comment 4869342022), umbrella OPEN for Phases 2-5. Lane: irterm S3-S8 strict serial #3193-3198.
- 85873 → worktree ~/provekit-wt/pykit-lambda, branch codex/dunder-laundering → #3149 (narrow the 4 operations/ except-TypeError catches: reduction bugs surface LOUD, genuinely-opaque still flows). Recognizer tail COMPLETE (#3103-#3121 incl. decorators: 11,224 hits, 4-tier taxonomy). Floor-projection campaign CLOSED (#3150; dup-emission debt = #3220, subsumed by vocab S4). Lane after: #3122/#3123, #3124 capstone.
- ProofIR-VOCAB campaign staged: plan (3 commits: 5a94e1a/62aec00/2ca0e80) + issues #3232-3240 chained + ProofIRGraphMember concrete design doc being written by agent proofir-vocab-plan (both-kit extracts done; key finds: call-edge dict at literal_call_report.py:1580 DIVERGES from CallEdgeDecl; sugar-ir-types is CDDL-GENERATED so wire changes go through protocol/). AWAITING T'S BLESSING before slice dispatch. Python S1-S8 parallel-safe now; Rust S9 hard-gated on irterm #3198. Law 8 in plan: auditor-reflex → type system.
- STACKING PATTERN (works): when a worker's next task shares files with its own unmerged PR, branch the new work off that PR's branch; by PR time the base has merged and the new PR shows only new commits. If not merged yet, worker rebases onto origin/main and force-pushes after coordinator merges.
- 85284 is T's PERSONAL window (not a worker) — never dispatch to it.
- Rate-limit note: coordinator REST core burns to 0 in bursts correlated with merge trains + CI (suspect runner-autoscaler on shared user token). GraphQL bucket stays healthy (workers + pr list unaffected). On 403: gh api rate_limit is free; merges usually still succeed (only branch-deletes fail — sweep at reset); keep dispatching via MCP.

## COORDINATOR REFLEXES (muscle memory — lost on compaction, re-learn the hard way otherwise)
- Verify `gh pr view N --json mergedAt` is NON-NULL before deleting a branch. Lost #3159's branch this way; recovered from local ref.
- cargo/bcargo HALTS at the first failing test target — a lib-target red masks every downstream bin/integration target. ALWAYS run explicit bin targets + quote EVERY test-binary summary line. This masking hid reds all session (#3085/#3089/#3131/#3142/#3173/#3179).
- `git worktree prune` before recreating a worktree at a path that errored; fast merge cadence causes fetch ref-lock races — re-fetch and retry.
- Codex "usage limit" tails: note the reset time, re-dispatch the FULL brief after it (queued briefs pre-limit do not run). Reset seen ~02:09 and ~07:10 PDT.
- Merge cycle per PR: read+soundness-read → admin-merge → verify mergedAt → delete branch → ff main → remove worktree → prune → create next worktree (verify HEAD) → dispatch full inline brief.
- Every discovered red/debt → gh issue at decision time, before moving on. Never raise a ceiling / soften a refusal / #[ignore] to green.

## DECISION OF RECORD (T Savo, 2026-07-02, verbal): ProofIR is the semantic carrier
Sat/unsat knowledge belongs with ProofIR, not sugar. Sugar = syntax→ProofIR construction only. Every emission = `new` of a typed ProofIR node class; constructor = the only door; ill-formed FOL unrepresentable (parse-don't-validate on the emission side). Each ProofIR class owns its FOL denotation + constructor invariants + its OWN sat/unsat witness pair (solver-anchored, once per class not per sugar). Sugar testimony becomes purely structural (construction provenance). Graph fully attributed — orphan formulas inexpressible (subsumes #3220). Anchors: grammar (shapes), provenance (wiring), solver (vocabulary), corpus (coverage). Sibling campaign (later): sugar shape/witness trait (mine()/near_miss(), generated from declared shapes). Agent `proofir-vocab-plan` (Opus) is writing the campaign plan + slice issues; collect its deliverable, route plan through T review before dispatching slices.

## HELD FOR T (do not act autonomously)
- KB dangling:92 — PAUSED by T; leave until he has focus.
- #3017 Phase-4 seam: DECIDED Option A (one representation); seam-plan agent executing. No open gate now.
- #3150 mini-interpreter: design blessed, #3181-3187 filed; dispatchable.

## Loops running
- Cron (30-min): poll fleet, merge, redispatch, reconcile main.
- PR monitor (persistent): fires on each new open PR.
- Worker-idle monitor (persistent, osascript reads iTerm tails): fires when a window flips working→idle.
- Acid-CI monitor (persistent): armed for the first COMPLETED (non-cancelled) main run verdict.

## Codex worker windows (IDs change across sessions — re-`list_workers` to confirm; never reuse blindly)
85868, 85870, 85873. Three-worker cap (battleaxe is one box; remote bcargo serial per worker).

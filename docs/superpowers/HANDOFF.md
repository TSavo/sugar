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
- 2026-07-01 tick: #3065 merged (canonicalizer, closed #2999). #3066 merged (this handoff).
  Main at 4ac1b51c9. No open PRs. GitHub API rate-limited (~resets hourly); fleet on SSH, unaffected.
- Crime board (the four-lens audit, #2981–#3001): essentially cleared. Last item #2995 (generated.rs
  rename + vocabulary-totality instrument) in flight on window 85868.
- Rust-kit spine campaign: plan #3014/#3015, capstone crime #3043 (five-frontier closure vector),
  Phase epics #3017/#3025/#3026/#3027/#3028. Live instruments: silent-drop frontier #3021 (R=401 —
  drains #3022/#3023/#3024), gate parity #3032. Python gap-swallow frontier also live.
- Perf: instrument #3039 then drains #3040 (bridge-envelope 2-3x clone) / architectural #3041
  (MementoPool typed-member migration — gated on #3039 numbers + zero crime board).
- Test debt: #3018 (restore quarantined bad-twin — HIGH, CI-red suspect).
- Review-bot findings #3050–#3063: still UNREAD (blocked on gh rate limit) — triage them.
- KB: memory_lint.py live, honestly red at dangling:92 (41 never-written memories; top target
  red_gate_is_not_a_gate ×10). T's call: write top 8 or strip.

## Loops running
- Cron (30-min): poll fleet, merge, redispatch, reconcile main, stop when crime board zero.
- PR monitor: fires on each new open PR.
- Acid-CI monitor: armed for the first COMPLETED main run verdict — consume it as real ΔR.

## Codex worker windows (this session — re-`list_workers` to confirm, IDs change across sessions)
85868 (#2995), 85870 (working), 85873 (#3022 queued). Never reuse IDs blindly; list first.

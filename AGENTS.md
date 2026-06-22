# Repository Guidelines

## Project Structure & Module Organization

This repository is the Sugar/ProveKit workspace. Core implementations live under `implementations/` by language (`rust/`, `python/`, `java/`, `go/`, etc.). The Rust crates form a Cargo workspace in `implementations/rust/`. End-to-end examples and receipts are in `examples/`; protocol and design material lives in `protocol/`, `docs/`, and `conformance/`. Automation and helper tooling are in `Makefile`, `bin/`, `scripts/`, and `tools/`.

## Build, Test, and Development Commands

- `make help`: list supported build and test targets.
- `make build-rust`: build the Rust workspace in release mode.
- `make test-rust`: run Rust workspace and Rust-driven RPC tests.
- `make test-python`: run Python kit tests.
- `make test-all`: run the acid test (`test-rust` plus `test-python`).
- `make test-showcases`: run checked-in end-to-end showcase receipts.
- `cd implementations/rust && cargo fmt`: format Rust code.
- `cd implementations/rust && cargo test -p sugar-cli <test-name> -- --nocapture`: run a focused Rust test.

## Coding Style & Naming Conventions

Keep changes small, explicit, and consistent with nearby code. Rust uses `cargo fmt`, snake_case functions/modules, and crate-local unit tests when practical. Shell scripts should be Bash/POSIX clear and executable only when intended. Do not move generated proofs, receipts, or vendored artifacts unless the task requires it.

## Testing Guidelines

Prefer focused regression tests before broader suites. For Sugar/ProveKit behavior, assert exact reports, receipts, CIDs, or verifier outcomes rather than inferred behavior. Start with the smallest relevant command, then widen to `make test-rust`, `make test-python`, `make test-all`, or a specific `examples/*/run.sh` when the blast radius warrants it.

## Commit & Pull Request Guidelines

Commit messages are short imperative summaries, often followed by PR numbers after merge, for example `Mint toolchain run witnesses from mint path (#2297)`. PR descriptions should state what changed, why, and the validation commands run. Keep unrelated local work out of the branch; stage files explicitly.

## Agent-Specific Instructions

For isolated work, create repo-local worktrees under `.worktrees/` from `origin/main`. Before editing, check `git status --short --branch`. If a narrower `AGENTS.md` exists in a subdirectory, follow that file for work inside its scope.

## Massive parallelism is moving fast and breaking things — loudly

Three commandments are carved over every engineering door: **don't check in broken code. don't merge failing tests. don't cause regressions.** They are not superstition — they are the scar tissue of every team that drowned in its own hidden breakage. But each one is a gate, and to fan out we are going to break all three. We have no choice: a gate is where parallelism goes to die. What follows is the argument that breaking these rules is survivable, and the price that buys the survival — paid in full, up front.

"Move fast and break things" is half a sentence. Breaking things is fine; breakage that *hides* is what kills you — it accumulates into a swamp no one can see the bottom of. So teams do the obvious thing and add a gate: review-then-merge, prove-then-ship, green-CI-before-anything. The gate feels like the price of speed without chaos.

But a gate is a serialization point, and serialization is the death of parallelism. Every shot queues behind the gate and waits for green; fire a hundred agents and all hundred stall at the same checkpoint — the gate, not the work, is the bottleneck. You cannot fan out through a gate. And the green it waits for is *always late*: every measurement worth having is taken after the shot lands, never before. A gate orders the shot to wait on a signal that does not exist yet — and cannot, until the shot is fired. That is why it serializes; it has inverted cause and effect.

So we ask the inverted question. Not "how do we go fast safely," but "what would make breaking things safe enough that the gate becomes unnecessary?" There are exactly two answers, and everything here is built on them.

**Make every break loud.** A failure that must never happen does not earn a counter we promise to lower someday — it earns a `panic`. It stops the program. A break that stops the program cannot hide and cannot accumulate; it is fixed on contact. (It is why you never find a type error sitting in a shipped binary — not because they never arise, but because the compiler refuses to emit one while a single type is unaccounted; the hole halts the build, so it dies before it has a name.) Loud breakage is breakage you can afford to cause.

**Measure every gap.** This is delta-epsilon testing, and it is indifferent to what we build. Every goal is a vector of named remaining-work counts, `R`. At each check-in we read `Delta R` — what actually moved — and `Epsilon R` — what the work already in flight will move next. We are done only at a *stable* zero: `R`, `Delta`, and `Epsilon` all zero, every floor intact. We never guess where we stand; we read it. And we read it late, on purpose: the measurement lands after the shot, never before — `Epsilon R` exists precisely because the signal for work already in flight has not arrived yet. Latency is not a defect to engineer away; it is the shape of telemetry itself. The gate's whole error was to demand the reading before the shot. We take the same reading after, and fix forward.

Those two are the gate's entire job — keep silent ruin from shipping — done without ever stopping the line. And they are one loop, not two tools: delta-epsilon drives a count toward zero while the panic fires on whatever instances remain, so as the measurement reaches zero the panic falls silent on its own. **That silence is the proof the zero is real, and it is load-bearing forward: once delta-epsilon is zero you know the panic cannot fire again, so a panic after that is, by definition, a regression** — the stable zero, broken by new work, announcing itself the one way that cannot be ignored. You never pick the ratchet *or* the panic: the ratchet drains the backlog, the panic locks the floor, the floor forbids the catastrophe; all three are loud, and none of them is a gate.

Here is the payoff, and it is the whole reason the discipline exists: **once breakage is loud and state is measured, there is nothing left to coordinate for safety.** Agents still divide the work so their shots do not collide — parallelism is not the absence of a plan — but no agent waits on another for *permission*. A broken shot screams and is fixed forward. The ledger keeps everyone honest about what remains. So you fire every shot you have, in parallel, the moment it is ready — and massive parallelism is not a technique you bolt on, it is what *falls out* of moving fast and breaking things loudly. The gates were the only thing stopping you; the instruments made them unnecessary.

And now those three commandments read differently. "Don't check in broken code" was never the real law — it was a cheap stand-in for *measure your breakage and make it loud.* A failing test you refuse to merge is only an assertion you blocked at a gate instead of instrumenting; a regression you forbid is a count you declined to track. The old rules were a poor team's telemetry, the best you can manage when you cannot see your own state. So the instruments are not free and they are not optional — they are the price of killing the rules, and you pay it up front: the loud-break machinery and the latent measurement are built *before* the parallelism they buy. Remove a gate and the only thing between you and the swamp is the measurement you invested in. Kill the rule, buy the instrument.

In practice: we do not gate. We instrument, fire, measure impact, and fire again. The merge is not a prize awarded after a slow compile, test, and sweep — it is the measurement boundary for the next shot.

- Goal vector: every long-term goal defines `R(t)`, a vector of named remaining-work counts — `failing_tests`, `untyped_call_sites`, `unmigrated_callers`, `endpoints_without_auth`, whatever names the gaps for this goal. Keep axes separate; do not hide distinct gaps inside one number.
- Stable-zero invariant: measure `Delta R(t) = R(t) - R(t-1)` at each check-in, and name `Epsilon R(t)`, the projected future change from queued, background, or follow-on work. A goal is complete only when `R(t) == 0`, `Delta R(t) == 0`, `Epsilon R(t) == 0`, and every floor invariant still holds.
- Floors: a floor is a safety invariant you pin and hold — `data_loss == 0`, no secret committed to the repo, no test deleted to turn the build green. It is not a progress counter, and not an absolute you can never touch: like a ratchet, it is a pin, and you may re-pin it — but only WITH GOOD REASON, stated on the record. A PR may lower `R` freely; to move a floor it must say why. The sin is never the reasoned re-pin — it is the silent drift, a floor that drops because no one decided to drop it.
- New feature: write the focused unit test first. The test names the behavior, fails or would have failed before the change, and becomes the local proof that the feature exists. Add implementation and instrumentation after the test defines the target.
- Regression: write the regression unit test first. Reproduce the failure in the smallest test that would have caught it. If the failure cannot be seen clearly, add instrumentation first, then add the regression test, then fix.
- Long-term goal: write a ratchet unit test for each `R` component. The test pins the current checked-in number and asserts the next number is strictly better: for example `failing_tests < 41`, `flaky_tests < 7`, or `unmigrated_callers < 120`. When the number improves, update the pinned threshold downward in the same PR. Never loosen a ratchet upward except in an explicit accounting-correction PR.
- Panic: wire every must-never-happen failure to halt the program, and run it *alongside* the ratchet, never instead of it (see the section head). The panic is impact telemetry of the good kind — it cannot be missed and is fixed on contact. A panic after `Delta R` and `Epsilon R` have reached zero is, by definition, a regression: the most valuable alarm you own.
- Shot accounting: every PR states which `R` component it lowers, the measured `Delta R`, the expected `Epsilon R`, and which floors it preserves. If `R > 0` and both `Delta R` and `Epsilon R` are zero, the work is stalled, not complete. If `R == 0` but `Epsilon R` is nonzero, the zero is unstable.
- Instrumentation: every change needs observability at the boundary where a future agent would otherwise have to guess. Use the repo's logging/tracing/report machinery, and include exact paths to logs, reports, receipts, or run outputs in the PR notes.
- Ship: after the focused test and local evidence are coherent, commit, open the PR, and merge immediately. Do not wait for CI, full compiles, full test suites, solver-heavy proofs, or corpus sweeps.
- Background: after the merge, start the slow compile/test/prove/sweep in `tmux`, `bcargo`, or on `battleaxe`. Report the command, host, log path, and next expected signal as `Epsilon R`.
- Fire again: once the background signal is launched, move to the next shot. If CI red, delayed logs, or long-run failures land later, treat them as measured impact for the next fix-forward PR.
- Parallel fire: launch independent work streams when they do not collide. If a merge conflict, broken main, or failed background run blocks the next shot, resolve that concrete blocker and keep moving.

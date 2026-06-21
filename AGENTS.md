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

## Supersonic Workflow

Default to forward motion. We do not gate; we instrument, fire, measure impact, and fire again. This deliberately inverts the usual trope: the merge is not a prize awarded after every slow compile, test, and sweep; it is the measurement boundary for the next shot.

- Goal vector: every long-term goal defines `R(t)`, a vector of named remaining-work counts such as `unresolved`, `undecided`, `unclassified`, or `no_facts`. Keep axes separate; do not hide distinct gaps inside one number.
- Stable-zero invariant: measure `Delta R(t) = R(t) - R(t-1)` at each check-in, and name `Gamma R(t)`, the projected future change from queued, background, or follow-on work. A goal is complete only when `R(t) == 0`, `Delta R(t) == 0`, `Gamma R(t) == 0`, and every floor invariant still holds.
- Floors: safety invariants are guards, not progress counters. Examples include `false_discharges == 0` or "no source drift." A PR may lower `R`; it must not break floors.
- New feature: write the focused unit test first. The test names the behavior, fails or would have failed before the change, and becomes the local proof that the feature exists. Add implementation and instrumentation after the test defines the target.
- Regression: write the regression unit test first. Reproduce the failure in the smallest test that would have caught it. If the failure cannot be seen clearly, add instrumentation first, then add the regression test, then fix.
- Long-term goal: write a ratchet unit test for each `R` component. The test pins the current checked-in number and asserts the next number is strictly better: for example `unresolved < 334`, `undecided < 12`, `no_facts < 78`, or `support == 0`. When the number improves, update the pinned threshold downward in the same PR. Never loosen a ratchet upward except in an explicit accounting-correction PR.
- Shot accounting: every PR states which `R` component it lowers, the measured `Delta R`, the expected `Gamma R`, and which floors it preserves. If `R > 0` and both `Delta R` and `Gamma R` are zero, the work is stalled, not complete. If `R == 0` but `Gamma R` is nonzero, the zero is unstable.
- Instrumentation: every change needs observability at the boundary where a future agent would otherwise have to guess. Use the repo's logging/tracing/report machinery, and include exact paths to logs, reports, receipts, or run outputs in the PR notes.
- Ship: after the focused test and local evidence are coherent, commit, open the PR, and merge immediately. Do not wait for CI, full compiles, full test suites, solver-heavy proofs, or corpus sweeps.
- Background: after the merge, start the slow compile/test/prove/sweep in `tmux`, `bcargo`, or on `battleaxe`. Report the command, host, log path, and next expected signal as `Gamma R`.
- Fire again: once the background signal is launched, move to the next shot. If CI red, delayed logs, or long-run failures land later, treat them as measured impact for the next fix-forward PR.
- Parallel fire: launch independent work streams when they do not collide. If a merge conflict, broken main, or failed background run blocks the next shot, resolve that concrete blocker and keep moving.

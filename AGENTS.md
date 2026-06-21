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

Default to forward motion. After a focused change has enough local evidence to be coherent, commit it, open the PR, and merge it without waiting for CI. Long builds, full sweeps, and corpus runs should continue in the background after merge, usually in `tmux`, `bcargo`, or on `battleaxe`. Treat CI red, logs, and delayed sweep failures as latent impact signals: inspect them quickly, identify the next concrete correction, and fix forward in a new PR.

Do not use waiting as a safety blanket. Launch independent work streams when they do not collide, report exact evidence and paths, and course-correct from measured failures. If a merge conflict or broken main blocks the shot, resolve that concrete blocker and continue; do not reframe it as a reason to stop.

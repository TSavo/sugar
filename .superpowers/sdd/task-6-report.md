# Task 6 Report: Managed Docker Core

Status: **COMPLETE**

## Delivered

- Digest-pinned `python:3.12.13-slim-bookworm` core Docker stage with
  Rust/Cargo 1.96.0, Python 3.12.13, Black 26.5.1, Pyright 1.1.411, and b3sum
  1.8.1.
- Entrypoint verification of all six versions and every stamped artifact SHA-256,
  with exit 70 contract failures and exact `exec` child semantics.
- Published `ghcr.io/tsavo/sugar-env:core-2026-07-14` and recorded its actual
  immutable RepoDigest in `sugar-build.toml`.
- bx Docker execution with repo-relative workdir, read-only stamped artifact
  injection, explicit-only environment forwarding, no Docker socket, and exact
  child exit propagation.
- Docker Desktop/WSL bind sources are translated remotely through `wslpath -w`
  when available; native bx Docker installations retain POSIX sources.
- Fake execution and structural coverage, including WSL path translation. The
  future solver-z3 closure is checked with a fixture contract, without claiming
  that Task 7's image exists in the live contract.

## Immutable receipts

- Base digest:
  `python:3.12.13-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b`.
- Published core RepoDigest:
  `ghcr.io/tsavo/sugar-env@sha256:5f1ef9a93256450d323f89f60eab38e8c883c1855eb54525504e4983117a85a8`.
- Real managed route printed the exact six pinned versions from the published
  digest. Pyright's one-time Node bootstrap chatter is normalized by selecting
  its exact version line.

## Verification

- `bash tests/sugarbin_docker_exec.sh "$PWD"`: PASS.
- `bin/sugarbin run --host bx --env docker:core -- sh -lc 'rustc --version;
  cargo --version; python --version; black --version; python -m pyright
  --version; b3sum --version'`: PASS with exact pinned versions.
- `cargo test --manifest-path implementations/rust/Cargo.toml -p sugar-cli
  --test sugarbin_execution_contract -- --nocapture`: PASS, 5 passed, 0 failed.
- `bash -n` on changed shell files and `git diff --check`: PASS.

## Concerns

- The first Pyright invocation downloads its pinned Node runtime and emits
  bootstrap/deprecation chatter. This does not alter the pinned Pyright version
  or execution result, but pre-seeding Node in a later image revision would make
  first-run output quieter.
- `solver-z3` remains intentionally unpublished in this task; Task 7 owns that
  capability image and live contract entry.

Author: T Savo.

## Critical finding follow-up: offline Pyright runtime

Status: **COMPLETE**

- The core build now forces Pyright 1.1.411 to bootstrap its selected Node
  26.5.0 runtime into `/opt/pyright/nodeenv` while network access is available.
  The version is build-pinned and recorded at `/opt/pyright/node-version`.
- The entrypoint disables ambient global-Node fallback and verifies that the
  retained runtime still matches the recorded identity before executing the
  child. This is solely Pyright's private implementation runtime and does not
  claim the Task 7 `node` capability.
- `tests/sugarbin_docker_core_offline.sh` pulls the published digest, creates a
  fresh receipt volume, starts the managed entrypoint under `--network none`,
  prints `node 26.5.0` and `pyright 1.1.411`, and proves its planted child ran
  exactly once.
- Replacement published core RepoDigest:
  `ghcr.io/tsavo/sugar-env@sha256:b8af4d5631bc34bea951a1ed5da391fbdc5efd4763941def40840f05292960a4`.

Validation:

- `bash tests/sugarbin_docker_exec.sh "$PWD"`: PASS.
- Real published bx offline core receipt: PASS; `node 26.5.0`,
  `pyright 1.1.411`, child count 1.
- Rust `sugarbin_execution_contract`: PASS, 5 passed.
- `bash -n` and `git diff --check`: PASS.

Author: T Savo.

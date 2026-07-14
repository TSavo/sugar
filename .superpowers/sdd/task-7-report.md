# Task 7 Report: Capability Graph and First Named-Task Migration

Status: **DONE_WITH_CONCERNS**

## Landed slice

- Made exact Z3, Coq, NumPy, pandas, Java, Maven, Node, pnpm, and Vampire
  versions first-class in `sugar-build.toml`.
- Added additive Docker stage definitions for all seven capability families.
- Kept Pyright's private Node bootstrap confined to `core`; the real `node`
  capability has its own exact Node and pnpm owners.
- Declared all seven initial named tasks. Every task has a non-empty command;
  there is no cached-verdict field.
- Migrated the host-only `bin/bpytest` wrapper to
  `bin/sugarbin run --host bx --task python-unit -- "$@"`.
- Made a battleaxe named task select its managed capability closure, so the
  named command is prepended and actually executes exactly once.

## Immutable digests

No new digest was recorded. This is deliberate: none of the new capability
closures was built and published, so writing references for them would be a
false immutable claim. The only usable managed digest remains the already
published core:

`ghcr.io/tsavo/sugar-env@sha256:b8af4d5631bc34bea951a1ed5da391fbdc5efd4763941def40840f05292960a4`

## Focused receipts

- `python3 -m pytest tests/test_sugar_build_contract.py -q`
- `bash tests/sugarbin_docker_exec.sh "$PWD"`
- `bash tests/sugarbin_task_exec.sh "$PWD"`
- `bin/sugarbin explain --host bx --task python-unit`
- `cargo test --manifest-path implementations/rust/Cargo.toml -p sugar-cli --test sugarbin_execution_contract -- --nocapture`
- `cargo test --manifest-path implementations/rust/Cargo.toml -p sugar-cli --test bcargo_sync_contract -- --nocapture`

`examples-gate` explain remains loudly red with
`capability closure has no built image`; that is the correct state until its
real closure is published.

## Remaining plan slice

Build each capability stage on battleaxe, finish the Coq and Java/Maven Debian
package-source adjudication, run each seconds-fast binary/version smoke in the
resulting image, publish each real closure to GHCR, and only then add its
RepoDigest under `[images]`. After those digests exist, migrate only Make/CI
routes that already execute on battleaxe and run the requested real
`python-unit` ratchet receipt. No broad wall belongs in that slice.

## Delta / epsilon

- Observed capability-version-owner gap: `R 9 -> 0`.
- Observed initial named-task declaration gap: `R 5 -> 0` (two already existed).
- Observed named-wrapper migration gap for the committed slice: `R 1 -> 0`.
- Remaining unpublished closure-image gap: `R 6` closure families (seven
  capabilities, with Java/Maven one family); predicted `Epsilon R = -6` for the
  publication slice.

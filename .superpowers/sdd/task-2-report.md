# Task 2 Report: bx Execution Backend

Status: `DONE_WITH_CONCERNS`

## Implemented

- Added `bin/lib/sugar-bx.sh` as the owner of workspace sync paths/excludes,
  tracked-manifest shipping, checkout-relative path translation, stale-root
  reaping, cleanup validation/policy, ambient remote execution, sync-back, and
  foreign-ELF refusal.
- Added `sugarbin run --host bx --env ambient` routing, including forwarding
  controls for path prefixes, named environment variables, sync-back pairs, and
  Python environment suppression.
- Changed `bin/brun` into a compatibility entry point delegating to the public
  sugarbin bx route while preserving its existing CLI.
- Moved the sync-contract census source and diagnostics to
  `bin/lib/sugar-bx.sh`.
- Added a fake SSH/rsync bx contract that checks one workspace rsync, path and
  cwd translation, argument quoting, no Docker, remote status propagation,
  cleanup modes/safety, stale-root reaping, tracked manifest sync, sync-back,
  and foreign ELF refusal.

## TDD Receipt

The new Rust-registered bx harness was run before implementation and failed:

```text
FAIL: remote exit status was 2, want 41
bx execution contract failed: exit status: 1
```

After implementation, `sugarbin_execution_contract` passed both local and bx
tests (2 passed, 0 failed). The sync census itself remained at:

```text
artifacts=29 missing=0 classes=fixture-dir=17,golden-file=7,manifest-toml=2,proof-bundle=1,sugar-runs-proof-fixtures=2
```

The standalone `tests/brun_remote_exec.sh` compatibility harness also passed.
`bash -n` over all touched shell entry points and `git diff --check` passed.

## Concern

The requested full `bcargo_sync_contract` command is not green because its
pre-existing `bcargo_remote_root_cleanup_contract` detects that `bin/bcargo`
still exports the obsolete `SUGAR_BUILD_GIT_HEAD` environment variable. That
behavior exists at Task 2's starting commit and is unrelated to moving the bx
sync owner, so it was not changed in this Task 2 commit. The other five tests in
that target, including the moved sync census, pass.

## Fix Review Findings

- Restored `PYTHON=<remote-root>/python-kit-env/bin/python` alongside the
  Python venv `PATH` entry and added a compatibility-harness assertion.
- Replaced forwarding-array copies and iteration with quoted, nounset-safe
  array handling; added bx harness coverage for path-prefix and sync-back
  values containing spaces.
- Removed the unreachable legacy implementation after `bin/brun`'s `exec`,
  leaving only the help and compatibility adapter.

Red receipt:

```text
$ bash tests/brun_remote_exec.sh "$PWD"
FAIL: remote Python interpreter missing from environment
exit 1
```

Verification receipts:

```text
$ cargo test --manifest-path implementations/rust/Cargo.toml -p sugar-cli --test sugarbin_execution_contract -- --nocapture
test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out

$ bash tests/brun_remote_exec.sh "$PWD"
PASS: brun remote exec harness

$ bash -n bin/sugarbin bin/brun bin/lib/sugar-bx.sh tests/sugarbin_bx_exec.sh tests/brun_remote_exec.sh
exit 0

$ git diff --check
exit 0
```

The unrelated pre-existing `SUGAR_BUILD_GIT_HEAD` red was not changed.

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

## Safety correction

The first Task 7 slice overstated readiness at two boundaries. This correction
supersedes the wrapper-migration and executable-closure claims above:

- `bin/bpytest` is back on its pre-Task-7 `bin/brun` route. The managed core
  does not yet contain pytest, the editable Python kits, or Sugar, so selecting
  `python-unit` there would replace a working path with an incomplete closure.
- The non-installing `solver-coq` and `java` Docker placeholder stages were
  removed. Their capability and exact-version declarations remain planning
  inputs, but no Docker stage or image claims either executable exists.
- `sugarbin explain` now prints the resolved immutable `docker_image` for a
  closure that is actually built.
- Exact-version validation now rejects ranges and other non-exact syntax for
  every currently declared tool pin, and the capability-to-tool owner mapping
  is executable contract data.
- The fake comment saying Task 7 published `solver-z3` was removed. Missing
  closure images continue to fail loudly.

Corrected remaining state: executable closure publication remains `R 6`, and
the `bpytest` named-route migration remains `R 1`. Neither is zero until real
images and the complete `python-unit` runtime have been built and exercised.

## Real closure publication (post-rebase)

Published and inspected immutable RepoDigests:

- Python test: `ghcr.io/tsavo/sugar-env@sha256:12ca8a6768630ae70afb37d63a48b5035da365c4c2fe4cd99117ae4327932674`
- Z3: `ghcr.io/tsavo/sugar-env@sha256:ea84add5822935318b6be07dba38980b81d947b077b077ca7e6f70febdf2d497`
- Python scientific + test + Z3: `ghcr.io/tsavo/sugar-env@sha256:f96731de7b4eb9a5660a6f8a14fc37f23ead4a0a9221667e9073ee0853070db3`
- Maximal examples closure: `ghcr.io/tsavo/sugar-env@sha256:f3474a1e1badba67f3daaf5c589f2844da28a7be6beda929ca5f7f2e5d95785e`

The maximal image is recorded only for the maximal named-task closure; its key
enumerates every capability actually present, including `python-test`. Direct
Coq, Java/Maven, Node/pnpm, Vampire, and scientific-only requests remain loudly
unresolved until minimal direct images are published. The maximal build
verified the Node, Vampire, and Temurin archives by SHA-256 before extraction.

Exact runtime smoke results on battleaxe:

```text
Z3 4.8.12
Coq 8.16.1
NumPy 2.5.1; pandas 3.0.3; scikit-learn 1.9.0
Temurin Java and javac 21.0.9 (direct and sh -lc)
Maven 3.8.7
Node 22.17.1; pnpm 10.13.1
Vampire 5.0.1
```

All seven named-task explains resolved an immutable digest. The real
`python-unit` broker route built and injected a stamped Linux Sugar binary and
ran `test_type_checker_ratchet.py`: 3 tests passed and 1 failed because current
main still names the absent mounted-source directory
`src/sugar_lift_py_tests/operations`. This is the current honest ratchet status,
not an environment skip. `bin/bpytest` was migrated after the published
closure executed and returned that current real product status.

The examples scripts still create private venvs and may reach PyPI. This image
pins its owned environment, but converting those script-local installs into a
fully offline managed mode remains a later migration; this report does not
claim the examples suite is network-hermetic.

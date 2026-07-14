# Task 5 report

## Status

Implemented the declarative build and capability contract, the Python resolver,
and named-task integration in `sugarbin`.

## Changes

- Added checked-in `sugar-build.toml` with exact tool versions, capability
  dependencies, and the `python-unit` and `examples-gate` tasks.
- Added a `tomllib`-only resolver with canonical compact JSON, deterministic
  dependency closure, and loud validation for unknown capabilities, dependency
  cycles, duplicate TOML definitions, missing immutable images, unknown task
  binaries, and empty commands.
- Added `sugarbin run/explain --task NAME`, task-default command appending,
  task binary injection, contradictory `--needs` rejection, and deterministic
  explain fields.
- Kept ambient routes operational. Docker routes resolve the contract first and
  remain loudly unavailable because Task 6 has not recorded an immutable image.

## TDD and focused receipts

- Initial prescribed `python3.12 -m pytest ...` red receipt could not start:
  this host has no `python3.12` executable (`command not found`).
- The same focused suite was run with the installed newer interpreter, Python
  3.14.4: `10 passed`.
- Repeated `bin/sugarbin explain --host bx --task examples-gate` output was
  identical and reported the sorted closure and task binaries.
- `bin/sugarbin explain --host bx --env docker:solver-z3 --needs sugar` failed
  loudly with `capability closure has no built image: core,solver-z3`, as
  required before Task 6.
- `bash -n bin/sugarbin` and `git diff --check` passed.

`sugarbin` prefers `python3.12` and falls back only to a detected Python newer
than 3.12, preserving the Python 3.12 `tomllib` floor on this development host.

## Concerns

- The brief's sample `resolve_environment("docker:core")` success assertion is
  incompatible with its later requirement that the checked-in pre-Task-6
  contract fail every Docker resolution for lack of a built image. The test
  exercises successful resolution using a temporary immutable digest fixture;
  the checked-in contract follows the explicit pre-image failure requirement.

## Review fix: named task execution without a command boundary

The initial implementation resolved a named task into a nonempty command but
then applied the generic `run` guard, which still required an explicit `--`
boundary. A real temporary task integration test reproduced the defect: the
task's default recording command was never invoked and `sugarbin` returned
`run requires -- followed by a command`.

The guard now accepts a resolved, nonempty named-task command without a
boundary. The integration receipt proves that the default command runs exactly
once, arguments after `--` append to its defaults, and an ordinary non-task
`run` without `--` remains rejected.

Focused review-fix receipts:

- `python3 -m pytest tests/test_sugar_build_contract.py -q`: `10 passed`.
- `bash tests/sugarbin_task_exec.sh "$PWD"`: PASS.
- `bash -n bin/sugarbin tests/sugarbin_task_exec.sh`: PASS.
- `git diff --check`: PASS.

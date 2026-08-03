# Merge-Group Trigger Design

## Goal

Make the existing `CI` workflow capable of producing `acid test (make ci)` for a future GitHub merge queue without enabling that queue or requiring the currently red acid check.

## Scope

The workflow gains one top-level `merge_group` event restricted to the `checks_requested` activity. The existing `push` trigger, path filter, jobs, acid vector, and main-branch protection remain unchanged.

The independently enrolled `recensus-path-smoke` workflow already runs `tests/test_workflow_context_availability.py`. That test module will also validate merge-group dispatchability so `ci.yml` does not attempt to certify its own ability to dispatch.

## Dispatchability Law

`ci.yml` is merge-queue-dispatchable only when its top-level `on` mapping contains:

```yaml
merge_group:
  types: [checks_requested]
```

The discriminator must reject all of these independently:

- no `merge_group` event;
- `merge_group` nested beneath another event;
- a top-level `merge_group` with any activity type other than `checks_requested`.

It must accept the exact lawful top-level event. YAML parsing remains a separate check because parseable and dispatchable are different properties.

## Failure Semantics

A malformed or missing event is a pre-dispatch refusal: GitHub creates no usable merge-group run, so `ci.yml` cannot report its own absence. The independent path-smoke tooth is therefore the owner of this law.

## Explicit Non-Goals

- Do not enable a merge queue.
- Do not add any required status context.
- Do not add a `pull_request` trigger.
- Do not change acid-test jobs, fan-out, batching, or concurrency.
- Do not claim that `acid test (make ci)` is green; twelve measured main runs are red.
- Defer queue versus plain per-PR execution until the acid vector is green on main.

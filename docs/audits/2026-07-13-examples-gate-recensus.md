# Examples-gate recensus, 2026-07-13

Part of #3677.

## Authority

- Source: clean `origin/main` at `3f2daadad84ffe38a14d0a7ad7041d429c2f1ef5`.
- Runner: battleaxe through `bin/brun`.
- Command: `make examples-gate`.
- Corpus: 64 discovered smoke examples.
- Observed vector: 1 GREEN, 63 red.

The expectation comparison was performed locally from the complete synced
`.out/examples-gate-summary.json`. The remote `bin/brun` source surface does
not include `docs/audits`, so the gate's final built-in comparison could not
open the expectation file after it had completed all 64 scripts. That did not
affect execution or the per-row summary.

## Verdict

This observation is not a lawful expectation-repin source. Every one of the
63 red logs contains the same compiler failure before the example's Sugar
semantics ran:

```text
error: function `dispatch_recovered_audit_tree` is never used
  --> sugar-cli/src/lift_plugin.rs:377:15
  = note: `-D dead-code` implied by `-D warnings`
```

The function and its binary-side caller landed in #4367. The library target
compiles `lift_plugin.rs` without `cmd_lift.rs`, so the crate-local function is
unreachable in that target. The warnings-as-errors floor therefore stops
`bin/sugarbin` before example semantics run. Issue #4381 carries that global
regression.

The classifier reported 59 of the masked rows as
`unclassified/example-failure`, three as
`durable-row-missing/scientific-python-showcase`, and one as
`prove-output/empty-json-receipt`. Inspection of the full logs shows the same
dead-dispatch build failure in all 63. The later three-plus-one labels are
secondary script output after the missing CLI, not independent product
shapes.

## Fixture disposition

- Honest expectation changes: 0.
- Unattributed row changes: 0. The global regression is attributable to the
  #4367 ownership shape and is tracked by #4381.
- Obsolete expectation rows: 0.
- Newly discovered smoke examples: 2:
  - `examples/rust-forall-universe-federation/run.sh`
  - `examples/rust-serde-federation/run.sh`

The two new rows remain unpinned because the global compiler failure masks
their real terminal state. `docs/audits/examples_gate_expectations.json` is
unchanged.

## Issue disposition

No open examples-gate work-order issue was closed or commented as newly green.
The only green row was `examples/java-mt-strong/run.sh`, already expected
GREEN and carrying no work-order issue. All other rows were masked by #4381,
so claiming an old red had cleared would be unsupported.

Rerun the full census after #4381 lands. Only that unmasked observation can
authorize expectation updates or stale-issue closure receipts.

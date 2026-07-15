# Recovered construction audit override (#4203)

## Law

Missing construction on valid Python remains a mandatory `FactoryPanic`. The campaign reaches zero panics only by implementing every shape.

Normal lift stops at the first panic and emits no completed artifact. Diagnostic recovery requires both runtime flags:

```text
sugar lift --audit-frontier --allowed-broken-components python <project>
```

The response is a separately tagged `recovered-construction-audit`, written as `frontier.json`. It contains mandatory panic records and explicitly suppressed descendants. It has no IR lane and cannot be selected with report, identify, library-binding, or prove modes. Panics keep the process red/nonzero.

The legacy Python kit `--audit-only` continuation route is rejected; there is no environment/config backdoor.

## Verification

```text
cargo test -p sugar-cli --test recovered_audit_cli -- --nocapture
  2 passed

cargo check -p sugar-cli
  passed

pytest tests/test_recovered_audit.py -q
  5 passed
```

Bad twins pin first-panic normal behavior, recovery of two independent panics, and descendant poisoning. The good twin constructs through the ordinary `LiftReportPayloadDto` path.

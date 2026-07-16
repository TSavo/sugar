# Forall Inactive Accounting Design

## Goal

Allow a bounded forall to complete its active propositions while preserving every cfg-inactive nested assertion as named outer-ledger accounting.

## Design

`Desugared::Constraints` carries both its active `claim_count` and typed nested non-proposition reasons. For this change, only reasons classified as `Disposition::Inactive` may coexist with a completed forall. The forall formula and claim count contain only warranted active assertions; inactive reasons propagate through the ordinary constraint emitter into `AdapterOutput::skip_reasons`.

Ambiguous and unclassified nested skips remain completeness failures and still reach the unchanged `forall_gap`. Existing constraint producers carry an empty nested-reason vector.

## Verification

- A literal-domain forall with two active assertions and one cfg-inactive assertion emits two active claims and one inactive reason.
- The same shape with an unresolved cfg predicate still panics at the hard forall floor.
- `coretests-invariants` advances beyond `forall.rs:769`; any later invariant is recorded as a separate frontier.

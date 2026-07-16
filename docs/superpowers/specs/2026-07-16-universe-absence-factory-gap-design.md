# Universe-Absence Factory Gap Design

## Scope

Add early, additive visibility when a Python assertion states a valid fact about a
callee for which the lift can construct no universe. The fact remains in ProofIR and
the verifier remains unchanged: a vacuous claim still refuses at verification time.
This change does not add Base64 or pandas universe recognizers.

## Architecture

After a test testimony has constructed its assertion facts and call edges, an
independent audit producer examines each asserted call edge. It asks whether any
existing construction route answers that callee demand:

- a same-lift function contract produced by digging a visible body;
- a builtin-universe recognizer selected by the Python factory;
- bridge testimony already carried on the call edge; or
- a loaded vendor-proof identity already carried on the call edge.

If no route answers, the producer returns a typed `FactoryGapInfo`; it does not throw
`FactoryPanic` and does not create an `Incomplete` effect. `lift_rpc` lowers that typed
diagnostic through the existing `AuditOnlyGap`/`FactoryWalkRedRowDto` boundary and
appends it to `payload.factory_walk`. Existing IR and call-edge rows are retained.

## Gap Shape

Each universe-absence row has:

- `owner=python.factory`;
- `observed=<callee symbol>`;
- source blame from the call edge's `callSiteLocus`;
- `requested=callee universe coverage`;
- a reason stating that no diggable body, builtin claim, bridge contract, or loaded
  vendor proof was available; and
- a fix naming all lawful retirement paths: add a builtin-universe recognizer, dig
  the body, add bridge coverage, or load a vendor proof.

The row uses the existing typed `GapKind.SUGAR` and `GapLocus.CONSTRUCTION` ledger
vocabulary. No verifier status or acceptance rule changes.

## Discrimination and Receipts

The positive fixture states a fact about a deliberately universeless callee. Its fact
and call edge must remain present while exactly one red factory-walk row names that
callee and its source locus. The covered twin states a fact about a locally defined,
diggable callee and must emit no universe-absence row. Focused tests also assert the
typed diagnostic fields, then the existing factory-gap and factory-walk suites run
unchanged. A small report fixture provides the user-facing receipt.

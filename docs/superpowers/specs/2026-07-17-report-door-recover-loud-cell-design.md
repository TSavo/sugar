# Report-Door Loud-Cell Recovery Design

## Goal

Let the default Python lift report render independent successful definitions
after one definition raises `FactoryPanic`, while preserving the panic as an
explicit red factory-walk row and preserving a nonzero report exit.

## Boundary

`audit_lift_file` already catches `FactoryPanic` at the definition boundary.
Its `recover_panics=True` mode must remain a diagnostic-only
`RecoveredAuditDto`; returning its partial ProofIR would violate that lane's
contract. Add a separate report-recovery mode used only by
`lift_file_payload`. In that mode the same catch:

1. converts the panic with `gap_from_factory_panic`;
2. appends the existing `FactoryWalkRedRowDto` projection;
3. stamps the poisoned definition span as report accounting evidence; and
4. continues with the next independent definition.

Normal direct audit calls remain fail-fast. Diagnostic recovered-audit calls
remain ProofIR-free.

## Accounting and Verdict

The recovered row serializes as `status=unresolved`, `verdict=gap`, and retains
the original owner, observed shape, blame locus, and remediation. It therefore
increments `factoryAuditSummary.statusCounts.unresolved`, which is a mandatory
red report finding. Assertion coverage remains conservative: successful
assertion facts are cited; assertions poisoned by the loud cell are not
invented as facts. No recovered cell enters an IR, effect, or green lane.

Assertions inside that stamped definition have no constructed fact and do not
receive a false refused-and-accounted alibi. They remain on the legacy
`silently_unaccounted` gate, with `status=recovered-factory-panic` and the
paired visible red row explaining why. Thus the row is never visually or
semantically silent even though the historical counter is the report's red
gate.

The default report must render the payload and exit nonzero whenever either a
recovered factory row or nonzero `silently_unaccounted` mass remains. A
swallowed twin that removes or recolors the red row must fail the focused
verdict test.

## Tests

- A two-definition discrimination fixture has one clean testimony and one
  unknown-local `isinstance` panic. The report retains the clean fact and a red
  row naming `UnknownLocal`.
- A conservation test proves the loud definition contributes no assertion fact,
  the clean definition still does, unresolved factory mass is one, and the
  poisoned claim contributes one unit to the mandatory red gate.
- The fail-fast audit and diagnostic-only recovered-audit contracts remain
  unchanged.
- A CLI/report witness proves the truthful recovered payload exits red while a
  lying green/swallowed twin refutes.
- The complete vendored CPython 3.11 `datetime.py` re-shoot reaches report
  rendering rather than aborting at the first loud definition.
- `make test-claim-mass-tripwires` stays green; any future movement of a pinned
  fixture must update its assertion count and lifted loci in the same PR.

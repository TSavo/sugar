# Build-Witness Durable Continuity Design

## Problem

The build-witness lifter executes the build and emits a content-addressed witness body, a witness CID, a signed witness memento, and Derived ProofIR provenance on each resulting equality contract. The witness memento survives minting and verifies after durable reload, but the contract itself omits the custom execution-witness evidence that selects recomputation as its discharge strategy. After reload the verifier therefore treats the equality as a symbolic obligation and loudly refuses it as vacuous.

The missing link is contract evidence continuity, not verifier tolerance. A memento or provenance record being present must never imply successful discharge.

## Design

The build-witness lifter will attach a custom `EvidenceTerm` to every contract derived from a build witness. Its certificate commits to the build-witness package CID and the expected successful outcome. The existing mint path already serializes a lifted declaration's evidence into the durable contract member; no alternate persistence format is introduced.

The verifier will recognize the build-witness package schema and send its pinned CID through the existing typed resolver path. The resolver returns package bytes only. Rust independently hashes those bytes, checks that the hash equals the pinned CID, decodes the committed outcome, and discharges only when the recomputed package is successful. Missing configuration, missing bytes, malformed bytes, a CID mismatch, or a failed outcome remains a refusal.

This restores the lifecycle:

`execution -> witness body -> CID -> memento/evidence -> proof member -> provenance -> resolver -> Rust recomputation -> durable verdict`

## Soundness Boundary

- Provenance and memento presence are necessary context, not a verdict.
- The resolver cannot assert success; it supplies bytes only.
- Rust recomputes the package CID and outcome.
- A stale, lying, malformed, missing, or failed package cannot discharge.
- The symbolic vacuity guard remains unchanged.

## Regression Shape

A focused durable round-trip test mints the build-witness proof, reloads it, and verifies that a valid package discharges through witness recomputation. Its bad twin supplies a failed or mismatching package and asserts that durable verification remains refused. The test also pins that the durable contract member carries the same evidence emitted by the lifter.

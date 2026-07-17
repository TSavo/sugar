# Protocol Conformance Test Vectors

This tree carries protocol-level vector corpora shared by every
implementation.

- `proof-protocol/`: `.proof` bundle conformance fixtures and expected
  verdicts.
- `recovered-audit/`: golden recovered-construction-audit leaf and tree
  wire fixtures round-tripped by both Python and Rust (#4264).

The Rust implementation is the reference oracle. Other language kits may
use native data types, but the conformance boundary is the canonical CID
over the vector body.

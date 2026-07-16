# Build-Witness Durable Continuity Implementation Plan

1. Add a focused regression that constructs build-witness custom evidence, mints it into a proof, reloads the proof, and exercises consistency verification through the typed resolver context.
2. Pin the initial failure: the GOOD case is not discharged because the durable contract lacks a usable build-witness execution package; retain a failed/mismatched package twin that refuses.
3. Extend the Python build-witness lifter to emit deterministic custom evidence containing the package CID and expected successful outcome on every derived contract.
4. Extend the existing Rust witness-package claim/outcome decoder narrowly for the build-witness schema while keeping the single resolver-to-Rust-CID-verification door.
5. Assert evidence survives minting byte-for-byte into the durable member and that reload produces the same GOOD verdict as prove-time verification.
6. Run only focused Python and Rust tests plus formatting checks. Do not run the repository gate.
7. Commit with the requested author, push `witness-durable-continuity`, and open a non-closing PR whose body says `Part of #3749`.

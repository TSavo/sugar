// SPDX-License-Identifier: MIT OR Apache-2.0
//
// The two-reds typed solve outcome (SEAM 5 of the compiler-shape plan:
// ~/.claude/plans/sugar-compiler-liftshift.md, "Part 0" / "SEAM 5").
//
// Today the CLI solve door (`sugar_verifier::consistency::verify_consistency`)
// never runs the linker at all, so an unresolved cross-kit symbol has no
// representation in `ObligationVerdict` -- it just never enters a
// consistency group and the run silently omits it or reports a vacuous
// pass. `Outcome` names the two structurally distinct ways `ProofGraph::solve`
// can end: "no program was assembled -- feed more" (a link failure) is NEVER
// the same fact as "a program was assembled and the solver refuted it"
// (an `Unsatisfied` verdict). Collapsing the two into one bag would let a
// missing binding read as a disproof, or a real disproof read as merely
// incomplete input; `solve` short-circuits on the former so the latter is
// never reached with an unbound program.
#[derive(Debug, Clone)]
pub enum Outcome {
    /// Beat 1 (link) found at least one call edge that could not be bound:
    /// `sugar_linker::LinkerErrorKind::UnresolvedSymbol` (no contract answers
    /// the target symbol) or `SignatureMismatch` (a contract exists but its
    /// exported signature disagrees with the call site's declared import).
    /// The solver never ran; there is nothing yet to discharge.
    LinkError(Vec<sugar_linker::LinkerError>),
    /// Beat 1 bound every call edge (or there were none to bind); beat 2
    /// (`verify_consistency_from_indexes`) ran to completion and produced
    /// one verdict per consistency candidate, `Unsatisfied` included.
    Verdicts(Vec<sugar_verifier::consistency::ConsistencyResult>),
}

impl Outcome {
    /// `true` iff this is the link-failure arm. Named so callers don't
    /// have to match on the enum just to branch on "did the solver even run."
    pub fn is_link_error(&self) -> bool {
        matches!(self, Outcome::LinkError(_))
    }
}

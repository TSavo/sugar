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

/// A typed CLASSIFICATION of a production solve, derived purely from the
/// real pipeline's `Report` rows. This is the exact partition
/// `sugar-cli`'s `proof_report_gate` computes to pick an exit code; naming
/// it here lets `solve_project`'s callers reason about the outcome as a
/// value instead of re-deriving the row tally, WITHOUT owning the exit-code
/// constants (which live in `sugar-cli`). `exit_code()` reproduces today's
/// mapping bit-for-bit, so the CLI's behavior is derivable from this class
/// alone.
///
/// Link errors are deliberately NOT a variant here: they are carried as a
/// separate `ProvenOutcome::link_errors` field because they must NOT change
/// the exit code today (see `ProvenOutcome` / `solve_project` docs). This
/// class is exactly and only the report-derived verdict dimension.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OutcomeClass {
    /// Report had at least one row, no load errors, and every row is
    /// `Discharged`. Maps to the success exit code (`0`).
    Verified,
    /// Report had at least one HARD-failed row (`Unsatisfied`, `Refused`,
    /// or `Disagreement`). Maps to `EXIT_VERIFY_FAIL` (`1`).
    VerifyFailed,
    /// No hard-failed rows, but not verified either: undecided rows
    /// (`Undecidable`/`SolverTimeout`), an empty report, or load errors.
    /// Maps to `EXIT_SOLVER_FAIL` (`3`).
    Undecided,
}

impl OutcomeClass {
    /// Classify a real-pipeline `Report` by the SAME partition
    /// `sugar-cli::cmd_verify::proof_report_gate` uses. Kept byte-for-byte
    /// in step with that gate: any change to the exit-code law must change
    /// both together.
    pub fn from_report(report: &sugar_verifier::Report) -> Self {
        let mut hard_failed_rows = 0usize;
        let mut undecided_rows = 0usize;
        for row in &report.rows {
            match row.status {
                sugar_verifier::ObligationVerdict::Discharged => {}
                sugar_verifier::ObligationVerdict::Unsatisfied
                | sugar_verifier::ObligationVerdict::Refused
                | sugar_verifier::ObligationVerdict::Disagreement => hard_failed_rows += 1,
                sugar_verifier::ObligationVerdict::Undecidable
                | sugar_verifier::ObligationVerdict::SolverTimeout => undecided_rows += 1,
            }
        }
        let proof_ok = !report.rows.is_empty()
            && report.load_errors.is_empty()
            && hard_failed_rows == 0
            && undecided_rows == 0;
        if proof_ok {
            OutcomeClass::Verified
        } else if hard_failed_rows > 0 {
            OutcomeClass::VerifyFailed
        } else {
            OutcomeClass::Undecided
        }
    }

    /// Today's exit code for this class, matching `sugar-cli`'s
    /// `EXIT_OK` / `EXIT_VERIFY_FAIL` / `EXIT_SOLVER_FAIL` (`0` / `1` / `3`)
    /// bit-for-bit. The CLI faces still call `proof_report_gate` directly for
    /// their exit code (behavior parity); this method exists so the mapping is
    /// derivable from the typed class alone.
    pub fn exit_code(self) -> u8 {
        match self {
            OutcomeClass::Verified => 0,
            OutcomeClass::VerifyFailed => 1,
            OutcomeClass::Undecided => 3,
        }
    }
}

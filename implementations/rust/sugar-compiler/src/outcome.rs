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

/// A typed CLASSIFICATION of a production solve. This is the exact partition
/// `sugar-cli`'s `proof_report_gate` (and the production prove face) uses to
/// pick an exit code. Naming it here lets `solve_project`'s callers reason
/// about the outcome as a value instead of re-deriving the row tally,
/// WITHOUT owning the exit-code constants (which live in `sugar-cli`).
///
/// # Exit-code law (sugar#3893, T option C)
///
/// Unresolved link surface reddens the gate BY DEFAULT — no opt-in flag.
/// Green over unbridged callsites is the vacuous pass this campaign kills.
/// Link failure is a DISTINCT red from verify-fail and solver-fail:
///
/// - `Verified` → `0` (EXIT_OK)
/// - `VerifyFailed` → `1` (EXIT_VERIFY_FAIL) — "refuted — change the fact"
/// - `Undecided` → `3` (EXIT_SOLVER_FAIL) — "undecided"
/// - `LinkFailed` → `4` (EXIT_LINK_FAIL) — "no program — feed more"
///
/// Discharge still runs when links are unresolved (annotate-not-block on the
/// pipeline body); only the shell exit is red. Real pools with sparse bridges
/// will exit 4 until density work drains the unbridged surface — intended.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OutcomeClass {
    /// Report had at least one row, no load errors, every row is
    /// `Discharged`, and the link surface is clean. Maps to exit `0`.
    Verified,
    /// Report had at least one HARD-failed row (`Unsatisfied`, `Refused`,
    /// or `Disagreement`). Maps to `EXIT_VERIFY_FAIL` (`1`).
    VerifyFailed,
    /// No hard-failed rows, but not verified either: undecided rows
    /// (`Undecidable`/`SolverTimeout`), an empty report, or load errors.
    /// Maps to `EXIT_SOLVER_FAIL` (`3`).
    Undecided,
    /// Unresolved / signature-mismatched cross-kit edges, or an undecodable
    /// link view (`link_derivation_error`). Maps to `EXIT_LINK_FAIL` (`4`).
    /// Takes precedence over a report that would otherwise be green or
    /// undecided: unbridged surface is never a vacuous pass.
    LinkFailed,
}

impl OutcomeClass {
    /// Classify a real-pipeline `Report` by the SAME partition
    /// `sugar-cli::cmd_verify::proof_report_gate` uses for the *report*
    /// dimension alone. Link surface is layered on top via
    /// [`Self::with_link_surface`].
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

    /// Fold the link surface into a report-derived class under the #3893
    /// exit-code law: unresolved links / undecodable link views redden to
    /// `LinkFailed` BY DEFAULT. Link failure is the "no program — feed more"
    /// diagnosis and takes precedence at the shell so CI can discriminate it
    /// from verify-fail (refuted) and solver-fail (undecided). Report rows
    /// still carry any refutations; only the exit-code class is reordered.
    ///
    /// - link surface dirty → `LinkFailed` (exit 4)
    /// - else → report class unchanged
    pub fn with_link_surface(self, has_link_errors: bool, has_link_derivation_error: bool) -> Self {
        if has_link_errors || has_link_derivation_error {
            return OutcomeClass::LinkFailed;
        }
        self
    }

    /// Exit code for this class, matching `sugar-cli`'s
    /// `EXIT_OK` / `EXIT_VERIFY_FAIL` / `EXIT_SOLVER_FAIL` / `EXIT_LINK_FAIL`
    /// (`0` / `1` / `3` / `4`). The CLI faces should derive their proof-dimension
    /// exit from this class alone (gate convergence with `proof_report_gate`).
    pub fn exit_code(self) -> u8 {
        match self {
            OutcomeClass::Verified => 0,
            OutcomeClass::VerifyFailed => 1,
            OutcomeClass::Undecided => 3,
            OutcomeClass::LinkFailed => 4,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sugar_verifier::{CallSite, ObligationVerdict, Report, ReportRow};

    fn report_with(status: ObligationVerdict) -> Report {
        let mut report = Report::default();
        report.rows.push(ReportRow {
            callsite: CallSite {
                bridge_ir_name: "bridge".into(),
                property_name: "property".into(),
                ..CallSite::default()
            },
            status,
            reason: status.as_str().to_string(),
            discharge_method: None,
            body_discharge_tier: None,
            verification: None,
        });
        report
    }

    #[test]
    fn link_surface_reddens_otherwise_verified_report() {
        let class = OutcomeClass::from_report(&report_with(ObligationVerdict::Discharged));
        assert_eq!(class, OutcomeClass::Verified);
        assert_eq!(
            class.with_link_surface(true, false),
            OutcomeClass::LinkFailed
        );
        assert_eq!(
            class.with_link_surface(false, true),
            OutcomeClass::LinkFailed
        );
        assert_eq!(
            class.with_link_surface(false, false),
            OutcomeClass::Verified
        );
        assert_eq!(OutcomeClass::LinkFailed.exit_code(), 4);
    }

    #[test]
    fn link_surface_outranks_hard_verify_fail_at_shell() {
        // Report still names the refutation; exit code names the incomplete feed.
        let class = OutcomeClass::from_report(&report_with(ObligationVerdict::Unsatisfied));
        assert_eq!(class, OutcomeClass::VerifyFailed);
        assert_eq!(
            class.with_link_surface(true, true),
            OutcomeClass::LinkFailed
        );
        assert_eq!(OutcomeClass::VerifyFailed.exit_code(), 1);
        assert_eq!(OutcomeClass::LinkFailed.exit_code(), 4);
    }

    #[test]
    fn undecided_with_links_is_link_failed_not_solver_fail() {
        let class = OutcomeClass::from_report(&report_with(ObligationVerdict::Undecidable));
        assert_eq!(class, OutcomeClass::Undecided);
        assert_eq!(
            class.with_link_surface(true, false),
            OutcomeClass::LinkFailed
        );
    }
}

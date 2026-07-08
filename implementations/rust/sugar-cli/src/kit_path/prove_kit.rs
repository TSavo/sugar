// SPDX-License-Identifier: MIT OR Apache-2.0

use libsugar::core::traits::{Catalog, Kit, KitError};
use libsugar::core::types::{
    ChainIntegrityFailureWitness, ChainIntegrityWitness, Cid, ConformanceDeclaration, Dialect,
    DomainClaim, Input, Term, Verdict, Witness,
};
use libsugar::core::walks::walk_premises_to_root_with_failure_steps;

const CHAIN_INTEGRITY_SCHEMA_VERSION: u32 = 1;
const SUGAR_CONFORMANCE_REASON: &str =
    "discharges claims via chain-integrity verification; no source emission";

/// Built-in kit that discharges claims by walking their premise chain to a root CID.
pub struct ProveKit {
    origin_cid: Cid,
    catalog: Box<dyn Catalog>,
    expect_cycle: bool,
}

impl ProveKit {
    /// Public registry declaration for the built-in `prove` kit.
    pub const CONFORMANCE: ConformanceDeclaration = ConformanceDeclaration::NonCarrier {
        reason: SUGAR_CONFORMANCE_REASON,
    };

    /// Build a ProveKit rooted at `origin_cid` using `catalog` for premise lookup.
    pub fn new(origin_cid: Cid, catalog: impl Catalog + 'static) -> Self {
        Self {
            origin_cid,
            catalog: Box::new(catalog),
            expect_cycle: false,
        }
    }

    /// Build a ProveKit with an explicit cycle expectation knob for chain-walk tests.
    ///
    /// The `expect_cycle` flag is currently a no-op in the walker; it is
    /// retained for source compatibility and scheduled for removal in a
    /// follow-up issue. New callers should prefer [`ProveKit::new`].
    #[deprecated(
        note = "expect_cycle is a no-op in walks::walk_premises_to_root; scheduled for removal. Use ProveKit::new."
    )]
    pub fn with_cycle_expectation(
        origin_cid: Cid,
        catalog: impl Catalog + 'static,
        expect_cycle: bool,
    ) -> Self {
        Self {
            origin_cid,
            catalog: Box::new(catalog),
            expect_cycle,
        }
    }
}

impl Kit for ProveKit {
    fn dialect(&self) -> Dialect {
        Dialect::Other("prove".to_string())
    }

    fn transform(&self, input: &Input) -> Result<DomainClaim, KitError> {
        match input {
            Input::Claim(claim) => Ok(claim.clone()),
            _ => Err(KitError::UnsupportedInput {
                dialect: self.dialect(),
                message: "ProveKit transform expects Input::Claim".to_string(),
            }),
        }
    }

    fn prove(&self, claim: DomainClaim) -> Result<DomainClaim, KitError> {
        let mut resolved = claim;
        match walk_premises_to_root_with_failure_steps(
            &resolved,
            &self.origin_cid,
            self.catalog.as_ref(),
            self.expect_cycle,
        ) {
            Ok(walked_steps) => {
                resolved.verdict = Verdict::Proved;
                resolved.witness = Some(Witness::ChainIntegrity(ChainIntegrityWitness {
                    walked_chain_root_cid: self.origin_cid.clone(),
                    walked_steps,
                    schema_version: CHAIN_INTEGRITY_SCHEMA_VERSION,
                }));
            }
            Err(failure) => {
                resolved.verdict = Verdict::Refuted;
                resolved.witness = Some(Witness::ChainIntegrityFailure(
                    ChainIntegrityFailureWitness {
                        walked_chain_root_cid: self.origin_cid.clone(),
                        walked_steps_before_break: failure.walked_steps_before_break,
                        break_kind: failure.breakage.kind_name().to_string(),
                        break_detail: failure.breakage.to_string(),
                        schema_version: CHAIN_INTEGRITY_SCHEMA_VERSION,
                    },
                ));
            }
        }
        Ok(resolved)
    }

    fn parse(&self, _input: &Input) -> Result<Term, KitError> {
        Err(KitError::UnsupportedInput {
            dialect: self.dialect(),
            message: "ProveKit parse is not supported".to_string(),
        })
    }

    fn serialize(&self, _term: &Term) -> Result<Input, KitError> {
        Err(KitError::Serialization(
            "ProveKit serialize is not supported".to_string(),
        ))
    }
}

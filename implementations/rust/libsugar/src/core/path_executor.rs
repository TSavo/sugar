// SPDX-License-Identifier: MIT OR Apache-2.0

//! Path executor registry and dispatch.
//!
//! Every kit registered with [`KitRegistry`] declares its conformance posture
//! explicitly through [`ConformanceDeclaration`]. Carrier kits are kits whose
//! `transform` produces target source; they declare `Carrier { target_language,
//! fixtures_path }` so their emit-compile-run fixtures are addressable from
//! the registry. Non-carrier kits are kits whose `transform` produces a
//! [`DomainClaim`](super::types::DomainClaim) without emitting target source;
//! they declare `NonCarrier { reason }`. The `reason` string is audit evidence
//! and is content-addressed through the surrounding run provenance chain.
//!
//! Canonical `NonCarrier` reasons:
//! - LiftKit: `"lifts source bytes to DomainClaim; no target source produced"`
//! - BindKit: `"transforms Input::Term to NamedTerm DomainClaim; emits no target source"`
//! - ProveKit: `"discharges claims via chain-integrity verification; no source emission"`
//!
//! Sequencing is bidirectional. If this substrate PR lands before per-kit PRs,
//! each kit PR adds a one-line `ConformanceDeclaration::Carrier { ... }` or
//! `ConformanceDeclaration::NonCarrier { ... }` declaration on rebase. If a kit
//! PR lands before this substrate PR, this PR sweeps that kit's `register()`
//! callsite to the new signature. Either direction is a mechanical one-line
//! update per callsite.

use std::collections::HashMap;

use sugar_ir_types::{
    composition_refusal_compose_input_cid, composition_refusal_header_cid,
    composition_refusal_signature, CompositionBoundaryMemento, CompositionRefusalEnvelope,
    CompositionRefusalHeader, CompositionRefusalMetadata, MissingRequirement,
};
use thiserror::Error;

use crate::compose::CCP_VERSION;

use super::primitives::address;
use super::prove_kit::ProveKit;
use super::traits::{Catalog, InputCatalog, Kit, KitError};
use super::types::{
    Cid, ConformanceDeclaration, DomainClaim, Input, PathAlgebra, PathError, Term, Verb,
};

struct RegisteredKit {
    kit: Box<dyn Kit>,
    conformance: ConformanceDeclaration,
}

/// Registry of executable kits keyed by the `PathAlgebra.kit` selector.
#[derive(Default)]
pub struct KitRegistry {
    kits: HashMap<String, RegisteredKit>,
}

impl KitRegistry {
    /// Register a kit under the exact path selector.
    pub fn register(
        &mut self,
        name: impl Into<String>,
        kit: impl Kit + 'static,
        conformance: ConformanceDeclaration,
    ) {
        self.kits.insert(
            name.into(),
            RegisteredKit {
                kit: Box::new(kit),
                conformance,
            },
        );
    }

    /// Borrow a registered kit by selector.
    pub fn get(&self, name: &str) -> Option<&dyn Kit> {
        self.kits
            .get(name)
            .map(|registered| registered.kit.as_ref())
    }

    /// Borrow a registered kit's conformance declaration by selector.
    pub fn conformance(&self, name: &str) -> Option<&ConformanceDeclaration> {
        self.kits
            .get(name)
            .map(|registered| &registered.conformance)
    }

    /// Register the built-in ProveKit under the public `prove` selector.
    pub fn register_prove(&mut self, origin_cid: Cid, catalog: impl Catalog + 'static) {
        self.register(
            "prove",
            ProveKit::new(origin_cid, catalog),
            ProveKit::CONFORMANCE,
        );
    }
}

/// Executed path output with terminal and per-step inspection accessors.
#[derive(Debug, Clone)]
pub struct PathExecutionChain {
    terminal_step: String,
    terminal_claim: DomainClaim,
    claims_by_step: HashMap<String, DomainClaim>,
    sources_by_step: HashMap<String, Cid>,
    terms_by_step: HashMap<String, Term>,
}

impl PathExecutionChain {
    /// Borrow the terminal claim selected by the path algebra.
    pub fn terminal_claim(&self) -> &DomainClaim {
        &self.terminal_claim
    }

    /// Consume the execution chain and return the terminal claim.
    pub fn into_terminal_claim(self) -> DomainClaim {
        self.terminal_claim
    }

    /// Borrow the claim produced by a named step.
    pub fn claim_at_step(&self, name: &str) -> Option<&DomainClaim> {
        if name == self.terminal_step {
            return Some(&self.terminal_claim);
        }
        self.claims_by_step.get(name)
    }

    /// Borrow the source CID associated with a named step, when any.
    pub fn source_at_step(&self, name: &str) -> Option<&Cid> {
        self.sources_by_step.get(name)
    }

    /// Borrow the term payload produced by a named step, when any.
    pub fn term_at_step(&self, name: &str) -> Option<&Term> {
        self.terms_by_step.get(name)
    }
}

/// Execute a composed path by materializing step inputs and dispatching registered kits.
pub fn execute_path(
    input: &Input,
    registry: &KitRegistry,
    inputs: &dyn InputCatalog,
) -> Result<PathExecutionChain, PathExecutionError> {
    let Input::Path(path) = input else {
        return Err(PathExecutionError::UnsupportedInput(
            "execute_path expects Input::Path".to_string(),
        ));
    };
    let ordered = path.ordered_steps().map_err(PathExecutionError::Path)?;
    let terminals = path.terminal_steps();
    let [terminal] = terminals.as_slice() else {
        return Err(PathExecutionError::UnsupportedInput(format!(
            "execute_path expects exactly one terminal step, got {}",
            terminals.len()
        )));
    };
    let terminal_step = terminal.name.clone();
    let mut claims_by_step: HashMap<String, DomainClaim> = HashMap::new();
    let mut sources_by_step: HashMap<String, Cid> = HashMap::new();
    let mut terms_by_step: HashMap<String, Term> = HashMap::new();
    let mut materialized_inputs: HashMap<Cid, Input> = HashMap::new();

    for step in ordered {
        let is_terminal = step.name == terminal_step;
        let registered = registry
            .kits
            .get(&step.kit)
            .ok_or_else(|| PathExecutionError::Refused(Box::new(missing_kit_refusal(step))))?;
        let kit = registered.kit.as_ref();
        let step_input = step_input(step, inputs, &materialized_inputs)?;
        let mut claim = match step.verb {
            Verb::Transform => kit
                .transform(&step_input)
                .map_err(PathExecutionError::Kit)?,
            Verb::Prove => {
                let Input::Claim(claim) = &step_input else {
                    return Err(PathExecutionError::UnsupportedInput(format!(
                        "path step `{}` Prove verb expects Input::Claim",
                        step.name
                    )));
                };
                kit.prove(claim.clone())
                    .map_err(|error| prove_error(step, error))?
            }
        };
        claim.premises.extend(step_premises(step, &claims_by_step)?);
        record_step_outputs(
            step,
            &step_input,
            &registered.conformance,
            &claim,
            &mut sources_by_step,
            &mut terms_by_step,
            !is_terminal,
        );
        if !is_terminal {
            if let Some(term) = claim.payload.clone() {
                materialized_inputs.insert(claim.to.clone(), Input::Term(term));
            }
            materialized_inputs.insert(
                address(&Input::Claim(claim.clone())),
                Input::Claim(claim.clone()),
            );
        }
        claims_by_step.insert(step.name.clone(), claim);
    }

    let terminal_claim = claims_by_step.remove(&terminal_step).ok_or_else(|| {
        PathExecutionError::UnsupportedInput("terminal step did not execute".into())
    })?;
    Ok(PathExecutionChain {
        terminal_step,
        terminal_claim,
        claims_by_step,
        sources_by_step,
        terms_by_step,
    })
}

fn step_input(
    step: &PathAlgebra,
    inputs: &dyn InputCatalog,
    materialized_inputs: &HashMap<Cid, Input>,
) -> Result<Input, PathExecutionError> {
    let [cid] = step.inputs.as_slice() else {
        return Err(PathExecutionError::UnsupportedInput(format!(
            "path step `{}` expects exactly one input CID, got {}",
            step.name,
            step.inputs.len()
        )));
    };
    if let Some(input) = inputs.get_input(cid) {
        return Ok(input);
    }
    if let Some(input) = materialized_inputs.get(cid) {
        return Ok(input.clone());
    }
    Err(PathExecutionError::Refused(Box::new(
        missing_input_refusal(step, cid),
    )))
}

fn step_premises(
    step: &PathAlgebra,
    claims_by_step: &HashMap<String, DomainClaim>,
) -> Result<Vec<Cid>, PathExecutionError> {
    step.depends_on
        .iter()
        .map(|dependency| {
            claims_by_step
                .get(dependency)
                .map(DomainClaim::cid)
                .ok_or_else(|| {
                    PathExecutionError::UnsupportedInput(format!(
                        "path step `{}` dependency `{dependency}` did not execute",
                        step.name
                    ))
                })
        })
        .collect()
}

fn record_step_outputs(
    step: &PathAlgebra,
    step_input: &Input,
    conformance: &ConformanceDeclaration,
    claim: &DomainClaim,
    sources_by_step: &mut HashMap<String, Cid>,
    terms_by_step: &mut HashMap<String, Term>,
    retain_term_output: bool,
) {
    if step.verb != Verb::Transform {
        return;
    }

    if let Input::Source { .. } = step_input {
        if let Some(source_cid) = step.inputs.first() {
            sources_by_step.insert(step.name.clone(), source_cid.clone());
        }
    }
    let is_carrier = matches!(conformance, ConformanceDeclaration::Carrier { .. });
    if is_carrier {
        sources_by_step.insert(step.name.clone(), claim.to.clone());
    }
    if !is_carrier && retain_term_output {
        if let Some(term) = claim.payload.clone() {
            terms_by_step.insert(step.name.clone(), term);
        }
    }
}

/// Errors from path execution.
#[derive(Debug, Error)]
pub enum PathExecutionError {
    /// The path or step shape is outside the current executor contract.
    #[error("{0}")]
    UnsupportedInput(String),
    /// The path algebra itself is invalid.
    #[error(transparent)]
    Path(#[from] PathError),
    /// The target kit failed.
    #[error(transparent)]
    Kit(#[from] KitError),
    /// Execution refused with a durable composition-refusal memento.
    #[error("path execution refused")]
    Refused(Box<CompositionBoundaryMemento>),
}

impl PathExecutionError {
    /// Borrow the durable refusal memento when this error is a refusal.
    pub fn composition_refusal(&self) -> Option<&CompositionBoundaryMemento> {
        match self {
            Self::Refused(refusal) => Some(refusal),
            _ => None,
        }
    }
}

fn missing_kit_refusal(step: &PathAlgebra) -> CompositionBoundaryMemento {
    composition_refusal_for_missing_requirement(
        step,
        "kit-registry",
        "plugin-registry",
        format!(
            "path step `{}` references unregistered kit `{}`",
            step.name, step.kit
        ),
    )
}

fn missing_input_refusal(step: &PathAlgebra, cid: &Cid) -> CompositionBoundaryMemento {
    composition_refusal_for_missing_requirement(
        step,
        "input-catalog",
        "path-input",
        format!(
            "path step `{}` input `{cid}` is not materialized and no prior step output produced it",
            step.name
        ),
    )
}

fn prove_error(step: &PathAlgebra, error: KitError) -> PathExecutionError {
    match error {
        KitError::NotSupported => {
            PathExecutionError::Refused(Box::new(prove_not_supported_refusal(step)))
        }
        other => PathExecutionError::Kit(other),
    }
}

fn prove_not_supported_refusal(step: &PathAlgebra) -> CompositionBoundaryMemento {
    composition_refusal_for_missing_requirement(
        step,
        "kit-prove",
        "kit-capability",
        format!(
            "path step `{}` kit `{}` does not support Prove",
            step.name, step.kit
        ),
    )
}

fn composition_refusal_for_missing_requirement(
    step: &PathAlgebra,
    role: &str,
    memento_kind: &str,
    reason: String,
) -> CompositionBoundaryMemento {
    let atoms_cids: Vec<String> = step.inputs.iter().map(ToString::to_string).collect();
    let effect_set_cids = Vec::new();
    let compose_input_cid =
        composition_refusal_compose_input_cid(&atoms_cids, &effect_set_cids, CCP_VERSION);
    let mut header = CompositionRefusalHeader {
        atoms_cids,
        blocking_effects: None,
        ccp_version: CCP_VERSION.to_string(),
        cid: String::new(),
        compose_input_cid,
        effect_occurrences: Some(vec![]),
        effect_set_cids,
        failure_detail: reason.clone(),
        failure_kind: "memento-required-missing".to_string(),
        incompatible_pair: None,
        kind: "composition-refusal".to_string(),
        missing_memento_requirements: Some(vec![MissingRequirement {
            expected_cid: None,
            memento_kind: Some(memento_kind.to_string()),
            reason,
            role: Some(role.to_string()),
        }]),
        schema_version: "1".to_string(),
    };
    header.cid = composition_refusal_header_cid(&header);
    let metadata = CompositionRefusalMetadata::default();
    let signature = composition_refusal_signature(&header, &metadata);
    CompositionBoundaryMemento {
        envelope: CompositionRefusalEnvelope {
            declared_at: "1970-01-01T00:00:00Z".to_string(),
            signature,
            signer: "substrate:libsugar".to_string(),
        },
        header,
        metadata,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use serde_json::json;

    use super::super::traits::HashMapInputCatalog;
    use super::super::types::{
        any_sort, formula_true, memento_from_parts, Dialect, DomainKind, Term, Verdict, Witness,
    };

    #[derive(Clone)]
    enum FixtureOutput {
        Term(Term),
        Source(Cid),
    }

    #[derive(Clone)]
    struct FixtureTransformKit {
        name: &'static str,
        output: FixtureOutput,
    }

    impl Kit for FixtureTransformKit {
        fn dialect(&self) -> Dialect {
            Dialect::Other(self.name.to_string())
        }

        fn transform(&self, input: &Input) -> Result<DomainClaim, KitError> {
            Ok(fixture_claim(self.name, input, &self.output))
        }

        fn parse(&self, _input: &Input) -> Result<Term, KitError> {
            match &self.output {
                FixtureOutput::Term(term) => Ok(term.clone()),
                FixtureOutput::Source(_) => Ok(Term::Unit),
            }
        }

        fn serialize(&self, term: &Term) -> Result<Input, KitError> {
            Ok(Input::Term(term.clone()))
        }
    }

    struct FixtureProveKit;

    impl Kit for FixtureProveKit {
        fn dialect(&self) -> Dialect {
            Dialect::Other("prove-fixture".to_string())
        }

        fn transform(&self, _input: &Input) -> Result<DomainClaim, KitError> {
            Err(KitError::NotSupported)
        }

        fn prove(&self, mut claim: DomainClaim) -> Result<DomainClaim, KitError> {
            claim.payload = None;
            claim.verdict = Verdict::Proved;
            claim.witness = Some(Witness::Proof {
                tree: json!({"kit": "prove-fixture"}),
            });
            Ok(claim)
        }

        fn parse(&self, _input: &Input) -> Result<Term, KitError> {
            Ok(Term::Unit)
        }

        fn serialize(&self, term: &Term) -> Result<Input, KitError> {
            Ok(Input::Term(term.clone()))
        }
    }

    fn fixture_term(name: &str) -> Term {
        Term::Const {
            value: json!({ "fixture": name }),
            sort: any_sort(),
        }
    }

    fn fixture_source(name: &str) -> Input {
        Input::Source {
            dialect: Dialect::Other(name.to_string()),
            bytes: name.as_bytes().to_vec(),
        }
    }

    fn fixture_claim(name: &str, input: &Input, output: &FixtureOutput) -> DomainClaim {
        let (to, payload) = match output {
            FixtureOutput::Term(term) => (address(term), Some(term.clone())),
            FixtureOutput::Source(cid) => (cid.clone(), None),
        };
        DomainClaim {
            domain: DomainKind::Other(format!("fixture-{name}")),
            contract: memento_from_parts(
                name.to_string(),
                vec!["x".to_string()],
                vec![any_sort()],
                any_sort(),
                formula_true(),
                formula_true(),
                Some(to.to_string()),
            ),
            artifacts: vec![to.clone()],
            from: vec![address(input)],
            premises: vec![],
            to,
            witness: None,
            payload,
            verdict: Verdict::Unresolved,
            attestation: None,
        }
    }

    fn register_fixture_kits(
        registry: &mut KitRegistry,
        lift_term: Term,
        bind_term: Term,
        lower_source_cid: Cid,
    ) {
        registry.register(
            "lift-fixture",
            FixtureTransformKit {
                name: "lift",
                output: FixtureOutput::Term(lift_term),
            },
            ConformanceDeclaration::NonCarrier {
                reason: "fixture lift produces a term",
            },
        );
        registry.register(
            "bind-fixture",
            FixtureTransformKit {
                name: "bind",
                output: FixtureOutput::Term(bind_term),
            },
            ConformanceDeclaration::NonCarrier {
                reason: "fixture bind produces a term",
            },
        );
        registry.register(
            "lower-fixture",
            FixtureTransformKit {
                name: "lower",
                output: FixtureOutput::Source(lower_source_cid),
            },
            ConformanceDeclaration::Carrier {
                fixtures_path: "fixtures/lower-fixture".into(),
            },
        );
        registry.register(
            "prove-fixture",
            FixtureProveKit,
            ConformanceDeclaration::NonCarrier {
                reason: "fixture prove discharges claims without source emission",
            },
        );
    }

    fn three_step_path(source_cid: Cid, lift_term: &Term, bind_term: &Term) -> Input {
        Input::Path(Box::new(super::super::types::Path {
            algebra: vec![
                PathAlgebra {
                    name: "lift".to_string(),
                    kit: "lift-fixture".to_string(),
                    inputs: vec![source_cid],
                    depends_on: vec![],
                    verb: Verb::Transform,
                },
                PathAlgebra {
                    name: "bind".to_string(),
                    kit: "bind-fixture".to_string(),
                    inputs: vec![address(lift_term)],
                    depends_on: vec!["lift".to_string()],
                    verb: Verb::Transform,
                },
                PathAlgebra {
                    name: "lower".to_string(),
                    kit: "lower-fixture".to_string(),
                    inputs: vec![address(bind_term)],
                    depends_on: vec!["bind".to_string()],
                    verb: Verb::Transform,
                },
            ],
        }))
    }

    fn four_step_path(
        source_cid: Cid,
        lift_term: &Term,
        bind_term: &Term,
        lower_claim_input_cid: Cid,
    ) -> Input {
        Input::Path(Box::new(super::super::types::Path {
            algebra: vec![
                PathAlgebra {
                    name: "lift".to_string(),
                    kit: "lift-fixture".to_string(),
                    inputs: vec![source_cid],
                    depends_on: vec![],
                    verb: Verb::Transform,
                },
                PathAlgebra {
                    name: "bind".to_string(),
                    kit: "bind-fixture".to_string(),
                    inputs: vec![address(lift_term)],
                    depends_on: vec!["lift".to_string()],
                    verb: Verb::Transform,
                },
                PathAlgebra {
                    name: "lower".to_string(),
                    kit: "lower-fixture".to_string(),
                    inputs: vec![address(bind_term)],
                    depends_on: vec!["bind".to_string()],
                    verb: Verb::Transform,
                },
                PathAlgebra {
                    name: "prove".to_string(),
                    kit: "prove-fixture".to_string(),
                    inputs: vec![lower_claim_input_cid],
                    depends_on: vec!["lower".to_string()],
                    verb: Verb::Prove,
                },
            ],
        }))
    }

    fn expected_three_step_claims(
        source: &Input,
        lift_term: &Term,
        bind_term: &Term,
        lower_source_cid: &Cid,
    ) -> (DomainClaim, DomainClaim, DomainClaim) {
        let lift = fixture_claim("lift", source, &FixtureOutput::Term(lift_term.clone()));
        let mut bind = fixture_claim(
            "bind",
            &Input::Term(lift_term.clone()),
            &FixtureOutput::Term(bind_term.clone()),
        );
        bind.premises = vec![lift.cid()];
        let mut lower = fixture_claim(
            "lower",
            &Input::Term(bind_term.clone()),
            &FixtureOutput::Source(lower_source_cid.clone()),
        );
        lower.premises = vec![bind.cid()];
        (lift, bind, lower)
    }

    #[test]
    fn execute_path_chain_exposes_claims_for_each_step() {
        let source = fixture_source("rust");
        let lift_term = fixture_term("lift");
        let bind_term = fixture_term("bind");
        let lower_source = fixture_source("python");
        let lower_source_cid = address(&lower_source);
        let mut inputs = HashMapInputCatalog::default();
        let source_cid = inputs.insert(source.clone());
        let path = three_step_path(source_cid, &lift_term, &bind_term);
        let mut registry = KitRegistry::default();
        register_fixture_kits(
            &mut registry,
            lift_term.clone(),
            bind_term.clone(),
            lower_source_cid.clone(),
        );
        let (expected_lift, expected_bind, expected_lower) =
            expected_three_step_claims(&source, &lift_term, &bind_term, &lower_source_cid);

        let chain = execute_path(&path, &registry, &inputs).expect("path executes");

        assert_eq!(
            chain.claim_at_step("lift").map(DomainClaim::cid),
            Some(expected_lift.cid())
        );
        assert_eq!(
            chain.claim_at_step("bind").map(DomainClaim::cid),
            Some(expected_bind.cid())
        );
        assert_eq!(
            chain.claim_at_step("lower").map(DomainClaim::cid),
            Some(expected_lower.cid())
        );
        assert!(chain.claim_at_step("missing").is_none());
    }

    #[test]
    fn execute_path_chain_terminal_claim_matches_previous_return_claim() {
        let source = fixture_source("rust");
        let lift_term = fixture_term("lift");
        let bind_term = fixture_term("bind");
        let lower_source = fixture_source("python");
        let lower_source_cid = address(&lower_source);
        let mut inputs = HashMapInputCatalog::default();
        let source_cid = inputs.insert(source.clone());
        let path = three_step_path(source_cid, &lift_term, &bind_term);
        let mut registry = KitRegistry::default();
        register_fixture_kits(
            &mut registry,
            lift_term.clone(),
            bind_term.clone(),
            lower_source_cid.clone(),
        );
        let (_, _, expected_lower) =
            expected_three_step_claims(&source, &lift_term, &bind_term, &lower_source_cid);

        let chain = execute_path(&path, &registry, &inputs).expect("path executes");

        assert_eq!(chain.terminal_claim().cid(), expected_lower.cid());
        assert_eq!(
            chain.terminal_claim().canonical_bytes(),
            expected_lower.canonical_bytes()
        );
    }

    #[test]
    fn execute_path_chain_exposes_sources_and_terms_by_step() {
        let source = fixture_source("rust");
        let lift_term = fixture_term("lift");
        let bind_term = fixture_term("bind");
        let lower_source = fixture_source("python");
        let lower_source_cid = address(&lower_source);
        let mut inputs = HashMapInputCatalog::default();
        let source_cid = inputs.insert(source.clone());
        let (_, _, expected_lower) =
            expected_three_step_claims(&source, &lift_term, &bind_term, &lower_source_cid);
        let path = four_step_path(
            source_cid.clone(),
            &lift_term,
            &bind_term,
            address(&Input::Claim(expected_lower)),
        );
        let mut registry = KitRegistry::default();
        register_fixture_kits(
            &mut registry,
            lift_term.clone(),
            bind_term.clone(),
            lower_source_cid.clone(),
        );

        let chain = execute_path(&path, &registry, &inputs).expect("path executes");

        assert_eq!(chain.source_at_step("lift"), Some(&source_cid));
        assert_eq!(chain.term_at_step("lift"), Some(&lift_term));
        assert!(chain.source_at_step("bind").is_none());
        assert_eq!(chain.term_at_step("bind"), Some(&bind_term));
        assert_eq!(chain.source_at_step("lower"), Some(&lower_source_cid));
        assert!(chain.term_at_step("lower").is_none());
        assert!(chain.source_at_step("prove").is_none());
        assert!(chain.term_at_step("prove").is_none());
        assert!(chain.source_at_step("missing").is_none());
        assert!(chain.term_at_step("missing").is_none());
    }
}

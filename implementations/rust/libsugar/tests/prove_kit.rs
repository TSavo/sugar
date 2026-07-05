// SPDX-License-Identifier: MIT OR Apache-2.0

use std::sync::Arc;

use libsugar::canonical::serializable_jcs;
use libsugar::compose::{
    build_value, cid_of_value, jcs_bytes_of_value, EffectSet, FunctionContractMemento, Locus,
};
use libsugar::core::{
    address, execute_path, ChainIntegrityFailureWitness, ChainIntegrityWitness, Cid,
    ConformanceDeclaration, Dialect, DomainClaim, DomainKind, HashMapCatalog, HashMapInputCatalog,
    Input, Kit, KitError, KitRegistry, Path, PathAlgebra, ProveKit, Term, Verb, Verdict, Witness,
};
use serde::de::DeserializeOwned;
use serde::Serialize;
use serde_json::json;
use sugar_canonicalizer::Value;
use sugar_ir_types::{IrFormula, IrTerm, Sort};

fn any_sort() -> Sort {
    Sort::Primitive {
        name: "Any".to_string(),
    }
}

fn bool_true() -> IrFormula {
    IrFormula::Atomic {
        name: "true".to_string(),
        args: vec![],
    }
}

fn pure_identity_contract(fn_name: &str, formal: &str) -> FunctionContractMemento {
    let formals = vec![formal.to_string()];
    let formal_sorts = vec![any_sort()];
    let return_sort = any_sort();
    let pre = bool_true();
    let post = IrFormula::Atomic {
        name: "=".to_string(),
        args: vec![
            IrTerm::Var {
                name: "result".to_string(),
            },
            IrTerm::Var {
                name: formal.to_string(),
            },
        ],
    };
    let effects = EffectSet::empty();
    let locus = Locus::unknown();
    let value: Arc<Value> = build_value(
        fn_name,
        &formals,
        &formal_sorts,
        &return_sort,
        &pre,
        &post,
        None,
        &effects,
        &locus,
        &[],
    );
    let canonical_bytes = jcs_bytes_of_value(&value);
    let cid = cid_of_value(&value);

    FunctionContractMemento {
        fn_name: fn_name.to_string(),
        formals,
        formal_sorts,
        formal_regions: vec![],
        return_sort,
        return_region: None,
        pre,
        post,
        body_cid: None,
        effects,
        locus,
        canonical_bytes,
        cid,
        auto_minted_mementos: vec![],
        panic_loci: vec![],
        concept_hint: None,
    }
}

fn claim_for_contract(contract: FunctionContractMemento) -> DomainClaim {
    let to = Cid::try_from(contract.cid.clone()).expect("fixture cid is valid");
    let artifact = address(&format!("contract:{}", contract.cid));
    DomainClaim {
        domain: DomainKind::FunctionContract,
        contract,
        artifacts: vec![artifact],
        from: vec![],
        premises: vec![],
        to,
        witness: None,
        payload: None,
        verdict: Verdict::Unresolved,
        attestation: None,
    }
}

fn claim_fixture(name: &str) -> DomainClaim {
    claim_for_contract(pure_identity_contract(name, "x"))
}

fn assert_jcs_round_trip<T>(value: &T)
where
    T: Serialize + DeserializeOwned + PartialEq + std::fmt::Debug,
{
    let first = serializable_jcs(value).expect("first JCS pass");
    let reparsed: T = serde_json::from_str(&first).expect("JCS reparses");
    let second = serializable_jcs(&reparsed).expect("second JCS pass");
    assert_eq!(first.as_bytes(), second.as_bytes());
}

struct FixtureTransformKit {
    claim: DomainClaim,
}

impl Kit for FixtureTransformKit {
    fn dialect(&self) -> Dialect {
        Dialect::Other("fixture-transform".to_string())
    }

    fn transform(&self, _input: &Input) -> Result<DomainClaim, KitError> {
        Ok(self.claim.clone())
    }

    fn parse(&self, _input: &Input) -> Result<Term, KitError> {
        Err(KitError::Serialization(
            "fixture parse is not supported".to_string(),
        ))
    }

    fn serialize(&self, _term: &Term) -> Result<Input, KitError> {
        Err(KitError::Serialization(
            "fixture serialize is not supported".to_string(),
        ))
    }
}

#[test]
fn chain_integrity_witness_round_trips_through_jcs() {
    let root_cid = address(&"root");
    let child_cid = address(&"child");
    let witness = ChainIntegrityWitness {
        walked_chain_root_cid: root_cid.clone(),
        walked_steps: vec![child_cid, root_cid],
        schema_version: 1,
    };

    assert_jcs_round_trip(&witness);
}

#[test]
fn chain_integrity_failure_witness_round_trips_through_jcs() {
    let root_cid = address(&"root");
    let child_cid = address(&"child");
    let witness = ChainIntegrityFailureWitness {
        walked_chain_root_cid: root_cid,
        walked_steps_before_break: vec![child_cid],
        break_kind: "CycleDetected".to_string(),
        break_detail: "cycle detected at fixture".to_string(),
        schema_version: 1,
    };

    assert_jcs_round_trip(&witness);
}

#[test]
fn sugar_transform_returns_claim_input_unchanged() {
    let claim = claim_fixture("identity");
    let root_cid = claim.cid();
    let kit = ProveKit::new(root_cid, HashMapCatalog::default());

    let transformed = kit
        .transform(&Input::Claim(claim.clone()))
        .expect("claim transform succeeds");

    assert_eq!(transformed.canonical_bytes(), claim.canonical_bytes());
}

#[test]
fn sugar_prove_sets_proved_verdict_and_chain_integrity_witness() {
    let root = claim_fixture("root");
    let root_cid = root.cid();
    let mut terminal = claim_fixture("terminal");
    terminal.premises = vec![root_cid.clone()];
    let mut catalog = HashMapCatalog::default();
    catalog.insert(&root);
    let kit = ProveKit::new(root_cid.clone(), catalog);

    let proved = kit.prove(terminal).expect("chain walk succeeds");

    assert_eq!(proved.verdict, Verdict::Proved);
    assert!(matches!(
        proved.witness,
        Some(Witness::ChainIntegrity(ChainIntegrityWitness {
            walked_chain_root_cid,
            walked_steps,
            schema_version: 1,
        })) if walked_chain_root_cid == root_cid && walked_steps == vec![root_cid]
    ));
}

#[test]
fn sugar_prove_sets_refuted_verdict_and_failure_witness_on_missing_premise() {
    let root_cid = address(&"root");
    let missing_cid = address(&"missing-premise");
    let mut terminal = claim_fixture("terminal");
    terminal.premises = vec![missing_cid.clone()];
    let kit = ProveKit::new(root_cid.clone(), HashMapCatalog::default());

    let refuted = kit.prove(terminal).expect("chain break becomes refutation");

    assert_eq!(refuted.verdict, Verdict::Refuted);
    assert!(matches!(
        refuted.witness,
        Some(Witness::ChainIntegrityFailure(ChainIntegrityFailureWitness {
            walked_chain_root_cid,
            walked_steps_before_break,
            break_kind,
            break_detail,
            schema_version: 1,
        })) if walked_chain_root_cid == root_cid
            && walked_steps_before_break.is_empty()
            && break_kind == "PremiseNotInCatalog"
            && break_detail.contains(missing_cid.as_str())
    ));
}

#[test]
fn sugar_prove_reflects_cycle_detected_in_failure_witness() {
    let root_cid = address(&"root");
    let cycle_cid = address(&"cycle");
    let mut cycle_claim = claim_fixture("cycle-claim");
    cycle_claim.premises = vec![cycle_cid.clone()];
    let mut terminal = claim_fixture("terminal");
    terminal.premises = vec![cycle_cid.clone()];
    let mut catalog = HashMapCatalog::default();
    catalog.put(cycle_cid.clone(), cycle_claim.canonical_bytes());
    let kit = ProveKit::new(root_cid.clone(), catalog);

    let refuted = kit.prove(terminal).expect("cycle becomes refutation");

    assert_eq!(refuted.verdict, Verdict::Refuted);
    assert!(matches!(
        refuted.witness,
        Some(Witness::ChainIntegrityFailure(ChainIntegrityFailureWitness {
            walked_chain_root_cid,
            walked_steps_before_break,
            break_kind,
            break_detail,
            schema_version: 1,
        })) if walked_chain_root_cid == root_cid
            && walked_steps_before_break == vec![cycle_cid.clone()]
            && break_kind == "CycleDetected"
            && break_detail.contains(cycle_cid.as_str())
    ));
}

#[test]
fn kit_registry_registers_sugar_under_public_prove_name() {
    let root_cid = address(&"root");
    let mut registry = KitRegistry::default();

    registry.register_prove(root_cid, HashMapCatalog::default());

    assert!(registry.get("prove").is_some());
    assert_eq!(
        registry.conformance("prove"),
        Some(&ConformanceDeclaration::NonCarrier {
            reason: "discharges claims via chain-integrity verification; no source emission"
        })
    );
}

#[test]
fn three_step_path_final_prove_produces_terminal_chain_integrity_witness() {
    let root_input = Input::Spec(json!({"step": "root"}));
    let child_input = Input::Spec(json!({"step": "child"}));
    let mut inputs = HashMapInputCatalog::default();
    let root_input_cid = inputs.insert(root_input);
    let child_input_cid = inputs.insert(child_input);

    let root_claim = claim_fixture("root");
    let root_claim_cid = root_claim.cid();
    let child_base_claim = claim_fixture("child");
    let mut child_claim = child_base_claim.clone();
    child_claim.premises = vec![root_claim_cid.clone()];
    let child_claim_input_cid = address(&Input::Claim(child_claim.clone()));

    let mut catalog = HashMapCatalog::default();
    catalog.insert(&root_claim);

    let path = Input::Path(Box::new(Path {
        algebra: vec![
            PathAlgebra {
                name: "root".to_string(),
                kit: "root-fixture".to_string(),
                inputs: vec![root_input_cid],
                depends_on: vec![],
                verb: Verb::Transform,
            },
            PathAlgebra {
                name: "child".to_string(),
                kit: "child-fixture".to_string(),
                inputs: vec![child_input_cid],
                depends_on: vec!["root".to_string()],
                verb: Verb::Transform,
            },
            PathAlgebra {
                name: "prove".to_string(),
                kit: "prove".to_string(),
                inputs: vec![child_claim_input_cid],
                depends_on: vec!["child".to_string()],
                verb: Verb::Prove,
            },
        ],
    }));
    let mut registry = KitRegistry::default();
    registry.register(
        "root-fixture",
        FixtureTransformKit {
            claim: root_claim.clone(),
        },
        ConformanceDeclaration::NonCarrier {
            reason: "test fixture transform; no source emission",
        },
    );
    registry.register(
        "child-fixture",
        FixtureTransformKit {
            claim: child_base_claim,
        },
        ConformanceDeclaration::NonCarrier {
            reason: "test fixture transform; no source emission",
        },
    );
    registry.register_prove(root_claim_cid.clone(), catalog);

    let chain = execute_path(&path, &registry, &inputs).expect("path executes");
    let terminal = chain.terminal_claim();

    assert_eq!(terminal.verdict, Verdict::Proved);
    assert!(terminal.witness.is_some());
    assert!(matches!(
        terminal.witness.as_ref(),
        Some(Witness::ChainIntegrity(ChainIntegrityWitness {
            walked_chain_root_cid,
            walked_steps,
            schema_version: 1,
        })) if walked_chain_root_cid == &root_claim_cid && walked_steps == &vec![root_claim_cid]
    ));
}

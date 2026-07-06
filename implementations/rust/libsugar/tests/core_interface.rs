// SPDX-License-Identifier: MIT OR Apache-2.0

use std::path::PathBuf;
use std::sync::Arc;

use libsugar::canonical::{json_cid, serializable_cid, serializable_jcs};
use libsugar::compose::{
    build_value, cid_of_value, compose_function_contracts, jcs_bytes_of_value, EffectSet,
    FunctionContractMemento, Locus,
};
use libsugar::core::{
    address, compose, execute_path, link, prove, transform, verify, ArityShape, AritySlot, CKit,
    Canonical, Catalog, Cid, ConformanceDeclaration, Dialect, DomainClaim, DomainKind,
    FunctionContractDomain, HashMapCatalog, HashMapInputCatalog, Input, InputCatalog, Kit,
    KitRegistry, LanguageSignature, LiftKit, LiftPluginKit, Path, PathAlgebra, PathDocument,
    PathDocumentError, PathError, Refutation, SlotSort, Term, Truth, Verb, Verdict, Witness,
};
use serde_json::json;
use sugar_canonicalizer::Value;
use sugar_ir_types::{
    composition_refusal_compose_input_cid, composition_refusal_header_cid,
    composition_refusal_signature, CompositionBoundaryMemento, CompositionRefusalEnvelope,
    CompositionRefusalHeader, CompositionRefusalMetadata, IrFormula, IrTerm, Sort,
};

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

fn claim_fixture(name: &str, verdict: Verdict) -> DomainClaim {
    let mut claim = claim_for_contract(pure_identity_contract(name, "x"));
    claim.verdict = verdict;
    claim.witness = match verdict {
        Verdict::Proved => Some(Witness::Proof {
            tree: json!({"claim": name}),
        }),
        Verdict::Refuted => Some(Witness::Counterexample {
            model: json!({"claim": name}),
        }),
        Verdict::Unknown => Some(Witness::Unknown {
            transcript: json!({"claim": name}),
        }),
        Verdict::Unresolved => None,
    };
    claim
}

fn term_fixture(name: &str) -> Term {
    Term::Op {
        op_cid: address(&format!("op:{name}")),
        name: name.to_string(),
        args: vec![Term::Const {
            value: json!(1),
            sort: any_sort(),
        }],
    }
}

fn one_step_path(name: &str, inputs: Vec<Cid>) -> Path {
    Path {
        algebra: vec![PathAlgebra {
            name: name.to_string(),
            kit: format!("kit:{name}"),
            inputs,
            depends_on: vec![],
            verb: Verb::Transform,
        }],
    }
}

#[test]
fn canonical_addresses_are_deterministic_for_core_shapes() {
    let op_cid = address(&"identity-op");
    let term = Term::Op {
        op_cid,
        name: "identity".to_string(),
        args: vec![Term::Var {
            name: "x".to_string(),
        }],
    };
    let formula = IrFormula::Atomic {
        name: "=".to_string(),
        args: vec![
            IrTerm::Var {
                name: "x".to_string(),
            },
            IrTerm::Const {
                value: serde_json::json!(1),
                sort: any_sort(),
            },
        ],
    };
    let contract = pure_identity_contract("id", "x");
    let claim = claim_for_contract(contract.clone());

    assert_eq!(address(&term), address(&term));
    assert_eq!(address(&formula), address(&formula));
    assert_eq!(address(&contract), address(&contract));
    assert_eq!(claim.cid(), claim.cid());
    assert!(claim.cid().as_str().starts_with("blake3-512:"));
}

#[test]
fn language_signature_shape_drives_term_identity() {
    let signature_cid = address(&"c11-signature");
    let bop_add_cid = address(&"c11:bop_add");
    let bop_logand_cid = address(&"c11:bop_logand");
    let seq_cid = address(&"c11:seq");
    let sizeof_cid = address(&"c11:sizeof_expr");
    let sizeof_type_cid = address(&"c11:sizeof_type");

    let signature = LanguageSignature::new(signature_cid.clone())
        .with_operation("bop_add", bop_add_cid.clone(), ArityShape::set())
        .with_operation(
            "bop_logand",
            bop_logand_cid.clone(),
            ArityShape::named(["left", "right"]),
        )
        .with_operation("seq", seq_cid.clone(), ArityShape::positional(2))
        .with_operation(
            "sizeof_expr",
            sizeof_cid.clone(),
            ArityShape::named_slots([AritySlot::unevaluated("operand")]),
        )
        .with_operation(
            "sizeof_type",
            sizeof_type_cid.clone(),
            ArityShape::named_slots([
                AritySlot::unevaluated("operand").with_slot_sort(SlotSort::Type)
            ]),
        );

    let a = Term::Var {
        name: "a".to_string(),
    };
    let b = Term::Var {
        name: "b".to_string(),
    };

    let add_ab = Term::Op {
        op_cid: bop_add_cid.clone(),
        name: "bop_add".to_string(),
        args: vec![a.clone(), b.clone()],
    };
    let add_ba = Term::Op {
        op_cid: bop_add_cid,
        name: "bop_add".to_string(),
        args: vec![b.clone(), a.clone()],
    };
    assert_eq!(
        signature.term_cid(&add_ab).expect("shape-aware add cid"),
        signature.term_cid(&add_ba).expect("shape-aware add cid"),
        "Set-shaped C11 binary ops sort children by child CID"
    );

    let and_ab = Term::Op {
        op_cid: bop_logand_cid.clone(),
        name: "bop_logand".to_string(),
        args: vec![a.clone(), b.clone()],
    };
    let and_ba = Term::Op {
        op_cid: bop_logand_cid,
        name: "bop_logand".to_string(),
        args: vec![b.clone(), a.clone()],
    };
    assert_ne!(
        signature.term_cid(&and_ab).expect("shape-aware and cid"),
        signature.term_cid(&and_ba).expect("shape-aware and cid"),
        "Named short-circuit slots carry left/right identity"
    );

    let seq_ab = Term::Op {
        op_cid: seq_cid.clone(),
        name: "seq".to_string(),
        args: vec![a.clone(), b.clone()],
    };
    let seq_ba = Term::Op {
        op_cid: seq_cid,
        name: "seq".to_string(),
        args: vec![b.clone(), a.clone()],
    };
    assert_ne!(
        signature.term_cid(&seq_ab).expect("shape-aware seq cid"),
        signature.term_cid(&seq_ba).expect("shape-aware seq cid"),
        "Positional sequence order remains index-bearing"
    );

    let sizeof_a = Term::Op {
        op_cid: sizeof_cid.clone(),
        name: "sizeof_expr".to_string(),
        args: vec![a.clone()],
    };
    let evaluated_sizeof_signature = LanguageSignature::new(signature_cid.clone()).with_operation(
        "sizeof_expr",
        sizeof_cid,
        ArityShape::named(["operand"]),
    );
    assert_ne!(
        signature
            .term_cid(&sizeof_a)
            .expect("unevaluated slot participates in the term cid"),
        evaluated_sizeof_signature
            .term_cid(&sizeof_a)
            .expect("evaluated slot participates in the term cid"),
        "slot evaluation is catalog data, not an operational side channel"
    );

    let sizeof_type_a = Term::Op {
        op_cid: sizeof_type_cid.clone(),
        name: "sizeof_type".to_string(),
        args: vec![a.clone()],
    };
    let term_typed_sizeof_signature = LanguageSignature::new(signature_cid).with_operation(
        "sizeof_type",
        sizeof_type_cid,
        ArityShape::named_slots([AritySlot::unevaluated("operand")]),
    );
    assert_ne!(
        signature
            .term_cid(&sizeof_type_a)
            .expect("slot sort participates in the term cid"),
        term_typed_sizeof_signature
            .term_cid(&sizeof_type_a)
            .expect("default term slot participates in the term cid"),
        "slot sort is catalog data, not inferred from the handler"
    );
}

#[test]
fn core_compose_agrees_with_legacy_function_contract_composition() {
    let inner = pure_identity_contract("inner", "y");
    let outer = pure_identity_contract("outer", "x");
    let expected = compose_function_contracts(&outer, &inner, 0).expect("legacy compose works");

    let a = claim_for_contract(inner);
    let mut b = claim_for_contract(outer);
    b.from.push(a.to.clone());

    let actual = compose(&a, &b).expect("core compose works");
    assert_eq!(actual.contract.cid, expected.cid);
    assert_eq!(actual.contract.canonical_bytes, expected.canonical_bytes);
    assert_eq!(actual.contract.pre, expected.pre);
    assert_eq!(actual.contract.post, expected.post);
}

#[test]
fn core_compose_tracks_source_endpoints_and_input_claims() {
    let inner = pure_identity_contract("inner_sources", "y");
    let outer = pure_identity_contract("outer_sources", "x");

    let mut a = claim_for_contract(inner);
    let source_cid = address(&"source-endpoint");
    a.from.push(source_cid.clone());

    let mut b = claim_for_contract(outer);
    let ambient_cid = address(&"ambient-endpoint");
    b.from.push(a.to.clone());
    b.from.push(ambient_cid.clone());

    let mut expected_from = vec![source_cid, ambient_cid];
    expected_from.sort();

    let mut expected_premises = vec![a.cid(), b.cid()];
    expected_premises.sort();

    let actual = compose(&a, &b).expect("core compose works");
    assert_eq!(actual.from, expected_from);
    assert_eq!(actual.premises, expected_premises);

    let unioned = a
        .union(&b)
        .expect("domain claims union through composition");
    assert_eq!(unioned.from, actual.from);
    assert_eq!(unioned.premises, actual.premises);
    assert_eq!(unioned.to, actual.to);
}

#[test]
fn link_cross_domain_claims_by_shared_contract_cid() {
    let contract = pure_identity_contract("ffi_shared", "x");
    let shared_cid = Cid::try_from(contract.cid.clone()).expect("fixture cid is valid");

    let mut python_claim = claim_for_contract(contract.clone());
    python_claim.domain = DomainKind::Other("python".to_string());
    python_claim.artifacts = vec![address(&"python.proof")];
    python_claim.from = vec![address(&"python-source")];

    let mut c_claim = claim_for_contract(contract);
    c_claim.domain = DomainKind::Other("c".to_string());
    c_claim.artifacts = vec![address(&"c.proof")];
    c_claim.from = vec![address(&"c-source")];

    let linked = link(&[python_claim.clone(), c_claim.clone()])
        .expect("cross-domain claims link through shared contract cid");
    let mut expected_premises = vec![python_claim.cid(), c_claim.cid()];
    expected_premises.sort();

    assert_eq!(
        linked.domain,
        DomainKind::Other("linked-program".to_string())
    );
    assert_eq!(linked.to, shared_cid);
    assert_eq!(linked.premises, expected_premises);
    assert_eq!(linked.artifacts.len(), 2);
    assert!(linked.artifacts.contains(&address(&"python.proof")));
    assert!(linked.artifacts.contains(&address(&"c.proof")));
}

#[test]
fn transform_and_prove_build_a_contract_claim_with_stub_kits() {
    let kit = CKit::default();
    let input = Input::Term(Term::Var {
        name: "x".to_string(),
    });

    let claim = kit.transform(&input).expect("kit transform succeeds");
    assert_eq!(claim.domain, DomainKind::FunctionContract);
    assert!(!claim.artifacts.is_empty());
    assert_eq!(claim.from, vec![address(&input)]);
    assert_eq!(claim.verdict, Verdict::Unresolved);

    let verb_claim = transform(&kit, &input).expect("transform verb delegates to kit");
    assert_eq!(verb_claim.from, claim.from);

    let proved = kit.prove(claim).expect("kit prove accepts a domain claim");
    assert_eq!(
        prove(&kit, verb_claim)
            .expect("prove verb delegates")
            .verdict,
        Verdict::Unknown
    );
    assert_eq!(proved.verdict, Verdict::Unknown);
    assert!(matches!(proved.witness, Some(Witness::Unknown { .. })));
}

#[test]
fn path_is_cidable_language_neutral_algebra() {
    let lift_step = PathAlgebra {
        name: "lift".to_string(),
        kit: "lift-plugin:rust".to_string(),
        inputs: vec![address(&Input::Spec(serde_json::json!({
            "surface": "rust",
            "workspace_root": "/repo"
        })))],
        depends_on: vec![],
        verb: Verb::Transform,
    };
    let mint_step = PathAlgebra {
        name: "mint".to_string(),
        kit: "sugar-mint".to_string(),
        inputs: vec![address(&Input::Spec(serde_json::json!({
            "outDir": "/repo/out"
        })))],
        depends_on: vec!["lift".to_string()],
        verb: Verb::Transform,
    };

    let path = Path {
        algebra: vec![mint_step.clone(), lift_step.clone()],
    };
    let reordered = Path {
        algebra: vec![lift_step, mint_step],
    };

    assert_eq!(path.cid(), reordered.cid());
    assert_eq!(
        address(&Input::Path(Box::new(path.clone()))),
        address(&Input::Path(Box::new(reordered)))
    );
    assert_eq!(
        path.step("mint").expect("mint step").depends_on,
        vec!["lift".to_string()]
    );
}

#[test]
fn path_algebra_default_verb_is_cid_stable_when_omitted() {
    let source_cid = address(&Input::Spec(json!({"surface": "rust"})));
    let step = PathAlgebra {
        name: "lift".to_string(),
        kit: "lift-rust".to_string(),
        inputs: vec![source_cid.clone()],
        depends_on: vec![],
        verb: Verb::default(),
    };
    let without_verb = json!({
        "dependsOn": [],
        "inputs": [source_cid.as_str()],
        "kit": "lift-rust",
        "name": "lift"
    });

    let encoded = serializable_jcs(&step).expect("default verb step serializes");
    assert!(
        !encoded.contains("\"verb\""),
        "default Transform verb must stay absent from canonical JSON: {encoded}"
    );
    assert_eq!(
        serializable_cid(&step).expect("default verb step CID"),
        json_cid(&without_verb).expect("legacy no-verb step CID")
    );

    let decoded: PathAlgebra =
        serde_json::from_value(without_verb).expect("legacy no-verb step parses");
    assert_eq!(decoded.verb, Verb::Transform);
}

#[test]
fn path_algebra_prove_verb_round_trips_and_changes_cid() {
    let claim_cid = address(&Input::Spec(json!({"claim": "input"})));
    let transform_step = PathAlgebra {
        name: "prove".to_string(),
        kit: "prove-stub".to_string(),
        inputs: vec![claim_cid],
        depends_on: vec![],
        verb: Verb::Transform,
    };
    let prove_step = PathAlgebra {
        verb: Verb::Prove,
        ..transform_step.clone()
    };

    let encoded = serializable_jcs(&prove_step).expect("Prove verb step serializes");
    assert!(
        encoded.contains("\"verb\":\"Prove\""),
        "Prove verb must be present in canonical JSON: {encoded}"
    );
    let decoded: PathAlgebra = serde_json::from_str(&encoded).expect("Prove verb step round-trips");

    assert_eq!(decoded.verb, Verb::Prove);
    assert_ne!(
        serializable_cid(&prove_step).expect("Prove verb step CID"),
        serializable_cid(&transform_step).expect("Transform verb step CID")
    );
}

#[test]
fn path_document_round_trips_with_cid_checked_materialized_inputs() {
    let lift_input = Input::Spec(json!({
        "surface": "rust-self-contracts",
        "workspace_root": ".",
        "config_path": ".sugar/config.toml",
        "source_paths": ["."],
        "options": {"layer": "all"}
    }));
    let mint_input = Input::Spec(json!({
        "outDir": "target/sugar-path-doc",
        "options": {"quiet": true}
    }));
    let lift_input_cid = address(&lift_input);
    let mint_input_cid = address(&mint_input);
    let path = Path {
        algebra: vec![
            PathAlgebra {
                name: "lift".to_string(),
                kit: "lift-plugin:rust-self-contracts".to_string(),
                inputs: vec![lift_input_cid.clone()],
                depends_on: vec![],
                verb: Verb::Transform,
            },
            PathAlgebra {
                name: "mint".to_string(),
                kit: "sugar-mint".to_string(),
                inputs: vec![mint_input_cid.clone()],
                depends_on: vec!["lift".to_string()],
                verb: Verb::Transform,
            },
        ],
    };

    let document = PathDocument::from_path_and_inputs(
        path.clone(),
        vec![lift_input.clone(), mint_input.clone()],
    )
    .expect("path document accepts matching inputs");
    let encoded = serde_json::to_string_pretty(&document).expect("path document serializes");
    let decoded: PathDocument = serde_json::from_str(&encoded).expect("path document parses");
    let inputs = decoded
        .materialized_inputs()
        .expect("path document materializes checked inputs");

    assert_eq!(decoded.path.cid(), path.cid());
    assert_eq!(inputs.len(), 2);
    assert!(inputs.iter().any(|(cid, input)| {
        cid == &lift_input_cid
            && matches!(input, Input::Spec(value) if value["surface"] == "rust-self-contracts")
    }));
    assert!(inputs.iter().any(|(cid, input)| {
        cid == &mint_input_cid
            && matches!(input, Input::Spec(value) if value["outDir"] == "target/sugar-path-doc")
    }));
}

#[test]
fn path_document_rejects_materialized_input_cid_mismatch() {
    let declared = Input::Spec(json!({"surface": "declared"}));
    let actual = Input::Spec(json!({"surface": "changed"}));
    let declared_cid = address(&declared);
    let document = PathDocument {
        kind: "sugar-path/v1".to_string(),
        path: Path {
            algebra: vec![PathAlgebra {
                name: "lift".to_string(),
                kit: "lift-plugin:declared".to_string(),
                inputs: vec![declared_cid],
                depends_on: vec![],
                verb: Verb::Transform,
            }],
        },
        inputs: vec![libsugar::core::PathInputBinding {
            cid: address(&declared),
            input: libsugar::core::PathInputMaterial::Spec {
                value: match actual {
                    Input::Spec(value) => value,
                    _ => unreachable!(),
                },
            },
        }],
    };

    let error = document
        .materialized_inputs()
        .expect_err("changed materialized input must not satisfy declared cid")
        .to_string();
    assert!(
        error.contains("materialized as"),
        "unexpected path document error: {error}"
    );
}

#[test]
fn path_document_materializes_closed_input_universe() {
    let claim = claim_fixture("path-doc-claim", Verdict::Unresolved);
    let truth = Truth::try_from(claim_fixture("path-doc-truth", Verdict::Proved))
        .expect("proved claim builds truth input");
    let refutation = Refutation::try_from(claim_fixture("path-doc-refutation", Verdict::Refuted))
        .expect("refuted claim builds refutation input");
    let term = term_fixture("path-doc-term");
    let inner_claim = Input::Claim(claim_fixture("path-doc-inner-claim", Verdict::Unresolved));
    let inner_claim_cid = address(&inner_claim);
    let inner_path = one_step_path("inner", vec![inner_claim_cid.clone()]);
    let inputs = vec![
        Input::Source {
            dialect: Dialect::Rust,
            bytes: b"fn main() {}".to_vec(),
        },
        Input::Spec(json!({"surface": "rust", "outDir": "target/path-doc"})),
        Input::Claim(claim),
        Input::Truth(truth),
        Input::Refutation(refutation),
        Input::Term(term),
        Input::Path(Box::new(inner_path)),
        inner_claim,
    ];
    let path = one_step_path("outer", inputs.iter().map(address).collect());

    let document = PathDocument::from_path_and_inputs(path.clone(), inputs.clone())
        .expect("path document accepts every closed input variant");
    let encoded = serde_json::to_string_pretty(&document).expect("path document serializes");
    let decoded: PathDocument = serde_json::from_str(&encoded).expect("path document parses");
    let materialized = decoded
        .materialized_inputs()
        .expect("path document materializes checked inputs");

    assert_eq!(decoded.path.cid(), path.cid());
    for expected in &inputs {
        let expected_cid = address(expected);
        let (_, actual) = materialized
            .iter()
            .find(|(cid, _)| cid == &expected_cid)
            .expect("expected materialized input cid");
        assert_eq!(actual.canonical_bytes(), expected.canonical_bytes());
    }
    for kind in [
        "\"kind\": \"source\"",
        "\"kind\": \"spec\"",
        "\"kind\": \"claim\"",
        "\"kind\": \"truth\"",
        "\"kind\": \"refutation\"",
        "\"kind\": \"term\"",
        "\"kind\": \"path\"",
    ] {
        assert!(
            encoded.contains(kind),
            "missing materialized variant {kind}"
        );
    }
}

#[test]
fn path_document_rejects_materialized_cid_mismatch_for_claim_term_and_nested_path() {
    fn assert_mismatch(declared: Input, actual: Input) {
        let declared_cid = address(&declared);
        let path = one_step_path("mismatch", vec![declared_cid.clone()]);
        let mut document = PathDocument::from_path_and_inputs(path, vec![actual])
            .expect("path document accepts supported materialized input");
        document.inputs[0].cid = declared_cid;

        let error = document
            .materialized_inputs()
            .expect_err("changed materialized input must not satisfy declared cid");
        assert!(
            matches!(error, PathDocumentError::InputCidMismatch { .. }),
            "unexpected path document error: {error}"
        );
    }

    assert_mismatch(
        Input::Claim(claim_fixture("declared-claim", Verdict::Unresolved)),
        Input::Claim(claim_fixture("actual-claim", Verdict::Unresolved)),
    );
    assert_mismatch(
        Input::Term(term_fixture("declared-term")),
        Input::Term(term_fixture("actual-term")),
    );
    assert_mismatch(
        Input::Path(Box::new(one_step_path(
            "declared-inner",
            vec![address(&Input::Spec(json!({"input": "declared"})))],
        ))),
        Input::Path(Box::new(one_step_path(
            "actual-inner",
            vec![address(&Input::Spec(json!({"input": "actual"})))],
        ))),
    );
}

#[test]
fn path_document_requires_nested_path_claim_closure() {
    let inner_claim = Input::Claim(claim_fixture("missing-inner-claim", Verdict::Unresolved));
    let inner_path = Input::Path(Box::new(one_step_path(
        "inner",
        vec![address(&inner_claim)],
    )));
    let outer_path = one_step_path("outer", vec![address(&inner_path)]);
    let document = PathDocument::from_path_and_inputs(outer_path, vec![inner_path])
        .expect("path document can carry a nested path input");

    let error = document
        .materialized_inputs()
        .expect_err("nested path input claim must be materialized");
    assert!(
        matches!(error, PathDocumentError::MissingMaterializedInput { .. }),
        "unexpected path document error: {error}"
    );
}

#[test]
fn nested_path_cid_changes_when_inner_path_or_cited_claim_changes() {
    fn outer_for(inner_path: Path, claim: &Input) -> Path {
        one_step_path(
            "outer",
            vec![address(&Input::Path(Box::new(inner_path))), address(claim)],
        )
    }

    let claim_a = Input::Claim(claim_fixture("nested-claim-a", Verdict::Unresolved));
    let claim_b = Input::Claim(claim_fixture("nested-claim-b", Verdict::Unresolved));
    let inner_a = one_step_path("inner", vec![address(&claim_a)]);
    let inner_changed = one_step_path("inner-changed", vec![address(&claim_a)]);

    let outer_a = outer_for(inner_a.clone(), &claim_a);
    let outer_inner_changed = outer_for(inner_changed, &claim_a);
    let outer_claim_changed = outer_for(one_step_path("inner", vec![address(&claim_b)]), &claim_b);

    assert_ne!(
        address(&Input::Path(Box::new(outer_a.clone()))),
        address(&Input::Path(Box::new(outer_inner_changed))),
        "outer path input cid must include nested path identity"
    );
    assert_ne!(
        address(&Input::Path(Box::new(outer_a))),
        address(&Input::Path(Box::new(outer_claim_changed))),
        "outer path input cid must include cited claim identity"
    );
}

#[test]
fn path_derives_order_from_dependencies() {
    let lift_step = PathAlgebra {
        name: "lift".to_string(),
        kit: "lift-plugin:rust".to_string(),
        inputs: vec![address(&Input::Spec(
            serde_json::json!({"surface": "rust"}),
        ))],
        depends_on: vec![],
        verb: Verb::Transform,
    };
    let mint_step = PathAlgebra {
        name: "mint".to_string(),
        kit: "sugar-mint".to_string(),
        inputs: vec![address(&Input::Spec(serde_json::json!({"outDir": "out"})))],
        depends_on: vec!["lift".to_string()],
        verb: Verb::Transform,
    };
    let path = Path {
        algebra: vec![mint_step, lift_step],
    };

    let ordered_names: Vec<&str> = path
        .ordered_steps()
        .expect("path dependency order")
        .into_iter()
        .map(|step| step.name.as_str())
        .collect();
    assert_eq!(ordered_names, vec!["lift", "mint"]);

    let terminal_names: Vec<&str> = path
        .terminal_steps()
        .into_iter()
        .map(|step| step.name.as_str())
        .collect();
    assert_eq!(terminal_names, vec!["mint"]);
}

#[test]
fn input_catalog_materializes_path_step_inputs_by_cid() {
    let mut catalog = HashMapInputCatalog::default();
    let input = Input::Spec(serde_json::json!({
        "surface": "jvm-bytecode",
        "artifact": "target/classes/App.class"
    }));
    let input_cid = catalog.insert(input);
    let path = Path {
        algebra: vec![PathAlgebra {
            name: "lift-jvm".to_string(),
            kit: "lift-plugin:jvm-bytecode".to_string(),
            inputs: vec![input_cid.clone()],
            depends_on: vec![],
            verb: Verb::Transform,
        }],
    };

    let step = path.step("lift-jvm").expect("path step");
    let materialized = catalog
        .get_input(&step.inputs[0])
        .expect("input materializes from catalog");
    let Input::Spec(value) = materialized else {
        panic!("catalog returned unexpected input");
    };
    assert_eq!(value["surface"].as_str(), Some("jvm-bytecode"));
    assert_eq!(step.inputs, vec![input_cid]);
}

#[test]
fn path_rejects_invalid_dependency_graphs() {
    let step = |name: &str, depends_on: Vec<&str>| PathAlgebra {
        name: name.to_string(),
        kit: format!("kit:{name}"),
        inputs: vec![address(&format!("input:{name}"))],
        depends_on: depends_on.into_iter().map(str::to_string).collect(),
        verb: Verb::Transform,
    };

    let duplicate = Path {
        algebra: vec![step("same", vec![]), step("same", vec![])],
    };
    assert!(matches!(
        duplicate.ordered_steps(),
        Err(PathError::DuplicateStep { name }) if name == "same"
    ));

    let missing = Path {
        algebra: vec![step("mint", vec!["lift"])],
    };
    assert!(matches!(
        missing.ordered_steps(),
        Err(PathError::MissingDependency { step, dependency })
            if step == "mint" && dependency == "lift"
    ));

    let cycle = Path {
        algebra: vec![step("a", vec!["b"]), step("b", vec!["a"])],
    };
    assert!(matches!(
        cycle.ordered_steps(),
        Err(PathError::Cycle { step }) if step == "a" || step == "b"
    ));
}

#[test]
fn path_orders_cross_domain_link_after_shared_contract_proofs() {
    let shared_contract = address(&"shared-python-c-contract");
    let python_proof = PathAlgebra {
        name: "python-proof".to_string(),
        kit: "lift-plugin:python".to_string(),
        inputs: vec![address(&Input::Spec(serde_json::json!({
            "proofFile": "python.proof",
            "contractCid": shared_contract.as_str()
        })))],
        depends_on: vec![],
        verb: Verb::Transform,
    };
    let c_proof = PathAlgebra {
        name: "c-proof".to_string(),
        kit: "lift-plugin:c".to_string(),
        inputs: vec![address(&Input::Spec(serde_json::json!({
            "proofFile": "c.proof",
            "contractCid": shared_contract.as_str()
        })))],
        depends_on: vec![],
        verb: Verb::Transform,
    };
    let link = PathAlgebra {
        name: "link".to_string(),
        kit: "sugar-link".to_string(),
        inputs: vec![address(&Input::Spec(serde_json::json!({
            "sharedContractCid": shared_contract.as_str()
        })))],
        depends_on: vec!["python-proof".to_string(), "c-proof".to_string()],
        verb: Verb::Transform,
    };
    let path = Path {
        algebra: vec![link, python_proof, c_proof],
    };

    let ordered_names: Vec<&str> = path
        .ordered_steps()
        .expect("cross-domain path order")
        .into_iter()
        .map(|step| step.name.as_str())
        .collect();
    assert_eq!(ordered_names.last(), Some(&"link"));
    assert!(ordered_names[..2].contains(&"python-proof"));
    assert!(ordered_names[..2].contains(&"c-proof"));
    assert_eq!(
        path.terminal_steps()
            .into_iter()
            .map(|step| step.name.as_str())
            .collect::<Vec<_>>(),
        vec!["link"]
    );
}

#[test]
fn verify_truth_checks_catalog_bytes_and_check_mode_witness() {
    let domain = FunctionContractDomain;
    let mut claim = claim_for_contract(pure_identity_contract("truthy", "x"));
    claim.verdict = Verdict::Proved;
    claim.witness = Some(Witness::Proof {
        tree: serde_json::json!({"checked": true}),
    });
    let truth = Truth::try_from(claim.clone()).expect("proved claim is truth");
    let mut catalog = HashMapCatalog::default();
    let cid = catalog.insert(&claim);
    assert_eq!(cid, claim.cid());

    assert!(verify(&truth, &domain, &catalog));

    let mut stale_catalog = HashMapCatalog::default();
    stale_catalog.put(cid, claim.canonical_bytes());
    claim.from.push(address(&"drifted-input"));
    let drifted_truth = Truth::try_from(claim).expect("fixture remains proved");
    assert!(!verify(&drifted_truth, &domain, &stale_catalog));
}

#[test]
fn truth_and_refutation_are_valid_inputs() {
    let mut truth_claim = claim_for_contract(pure_identity_contract("truth_input", "x"));
    truth_claim.verdict = Verdict::Proved;
    truth_claim.witness = Some(Witness::Proof {
        tree: serde_json::json!({"ok": true}),
    });
    let truth = Truth::try_from(truth_claim).expect("truth");
    let input = Input::Truth(truth.clone());
    let Input::Truth(round_tripped) = input else {
        panic!("truth input changed variant");
    };
    assert_eq!(round_tripped.claim().verdict, Verdict::Proved);
    assert!(Truth::try_from(claim_for_contract(pure_identity_contract("not_truth", "x"))).is_err());

    let mut refuted_claim = claim_for_contract(pure_identity_contract("refuted_input", "x"));
    refuted_claim.verdict = Verdict::Refuted;
    refuted_claim.witness = Some(Witness::Counterexample {
        model: serde_json::json!({"x": 0}),
    });
    let refutation = Refutation::try_from(refuted_claim).expect("refutation");
    let input = Input::Refutation(refutation.clone());
    let Input::Refutation(round_tripped) = input else {
        panic!("refutation input changed variant");
    };
    assert_eq!(round_tripped.claim().verdict, Verdict::Refuted);
    assert!(
        Refutation::try_from(claim_for_contract(pure_identity_contract(
            "not_refutation",
            "x"
        )))
        .is_err()
    );
}

#[test]
fn resolve_reads_canonical_bytes_from_hash_map_catalog() {
    let claim = claim_for_contract(pure_identity_contract("cataloged", "x"));
    let mut catalog = HashMapCatalog::default();
    let cid = catalog.insert(&claim);

    let bytes = libsugar::core::resolve(&cid, &catalog).expect("claim bytes resolve");
    assert_eq!(bytes, claim.canonical_bytes());
}

#[test]
fn hash_map_catalog_contains_reports_membership_without_get_fetch() {
    let claim = claim_for_contract(pure_identity_contract("catalog_contains", "x"));
    let mut catalog = HashMapCatalog::default();
    let present = catalog.insert(&claim);
    let absent = address(&"missing catalog entry");

    assert!(<HashMapCatalog as Catalog>::contains(&catalog, &present));
    assert!(!<HashMapCatalog as Catalog>::contains(&catalog, &absent));

    let traits_source = include_str!("../src/core/traits.rs");
    let impl_body = traits_source
        .split("impl Catalog for HashMapCatalog {")
        .nth(1)
        .and_then(|tail| tail.split("/// Typed resolver").next())
        .expect("HashMapCatalog Catalog impl is present");
    assert!(impl_body.contains("self.entries.contains_key(cid)"));
    assert!(!impl_body.contains("self.get(cid)"));
}

#[test]
fn lift_plugin_transport_is_a_core_kit_with_legacy_response_escape_hatch() {
    let temp = std::env::temp_dir().join(format!("sugar-lift-plugin-kit-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&temp);
    std::fs::create_dir_all(&temp).expect("create temp dir");
    let script = temp.join("fake-lifter.sh");
    std::fs::write(
        &script,
        r#"#!/bin/sh
while IFS= read -r line; do
  case "$line" in
    *'"method":"initialize"'*) echo '{"jsonrpc":"2.0","id":1,"result":{"name":"fake-lifter"}}' ;;
    *'"method":"lift"'*) echo '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[],"diagnostics":[]}}' ;;
    *'"method":"shutdown"'*) exit 0 ;;
  esac
done
"#,
    )
    .expect("write fake lifter");

    let kit = LiftPluginKit::new(
        "test-surface",
        vec!["sh".to_string(), script.display().to_string()],
        Some(temp.clone()),
    );
    let input = Input::Spec(serde_json::json!({
        "surface": "test-surface",
        "workspace_root": temp,
        "config_path": ".sugar/config.toml",
        "source_paths": ["."],
        "options": {"layer": "all", "identifyOnly": false}
    }));

    let session = kit
        .parse_session(&input)
        .expect("session exposes transport metadata");
    assert_eq!(
        session.response().get("kind").and_then(|v| v.as_str()),
        Some("ir-document")
    );
    assert_eq!(
        session.claim.domain,
        DomainKind::Other("lift-plugin".to_string())
    );
    assert_eq!(session.claim.from, vec![address(&input)]);
    let response_term = Term::Const {
        value: session.response().clone(),
        sort: Sort::Primitive {
            name: "LiftPluginResponse".to_string(),
        },
    };
    assert_eq!(session.claim.to, address(&response_term));
    assert_eq!(session.claim.artifacts, vec![address(&response_term)]);
    assert_eq!(
        session.claim.contract.body_cid.as_deref(),
        Some(session.claim.to.as_str())
    );
    assert_eq!(
        session.response().get("kind").and_then(|v| v.as_str()),
        Some("ir-document")
    );
    let _ = std::fs::remove_dir_all(&temp);
}

#[test]
fn lift_kit_transforms_source_through_lift_plugin_transport_and_carries_term_payload() {
    let temp = std::env::temp_dir().join(format!("sugar-lift-kit-source-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&temp);
    std::fs::create_dir_all(&temp).expect("create temp dir");
    let script = temp.join("fake-lifter.sh");
    std::fs::write(
        &script,
        r#"#!/bin/sh
while IFS= read -r line; do
  case "$line" in
    *'"method":"initialize"'*) echo '{"jsonrpc":"2.0","id":1,"result":{"name":"fake-rust-lifter"}}' ;;
    *'"method":"lift"'*) echo '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","ir":[{"kind":"bind-lift-entry","file":"src/lib.rs","fn_name":"id","fn_line":1,"param_names":["x"],"param_types":["i64"],"return_type":"i64","term_shape":{"kind":"var","name":"x"},"term_shape_cid":"blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","witnesses":[]}],"diagnostics":[]}}' ;;
    *'"method":"shutdown"'*) exit 0 ;;
  esac
done
"#,
    )
    .expect("write fake lifter");

    let request = serde_json::json!({
        "surface": "rust",
        "workspace_root": temp,
        "config_path": ".sugar/config.toml",
        "source_paths": ["."],
        "options": {"layer": "all", "identifyOnly": false}
    });
    let source = Input::Source {
        dialect: libsugar::core::Dialect::Rust,
        bytes: serde_json::to_vec(&request).expect("source request JSON"),
    };
    let kit = LiftKit::new(
        libsugar::core::Dialect::Rust,
        "rust",
        vec!["sh".to_string(), script.display().to_string()],
        Some(temp.clone()),
    );

    let claim = kit
        .transform(&source)
        .expect("source input lifts through the transport");
    let expected_term = Term::Const {
        value: serde_json::json!({
            "kind": "ir-document",
            "ir": [{
                "kind": "bind-lift-entry",
                "file": "src/lib.rs",
                "fn_name": "id",
                "fn_line": 1,
                "param_names": ["x"],
                "param_types": ["i64"],
                "return_type": "i64",
                "term_shape": {"kind": "var", "name": "x"},
                "term_shape_cid": "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "witnesses": []
            }],
            "diagnostics": []
        }),
        sort: Sort::Primitive {
            name: "LiftPluginResponse".to_string(),
        },
    };

    assert_eq!(claim.to, address(&expected_term));
    assert_eq!(claim.artifacts, vec![address(&expected_term)]);
    assert_eq!(claim.payload.as_ref(), Some(&expected_term));
    assert_eq!(claim.from, vec![address(&source)]);
    let _ = std::fs::remove_dir_all(&temp);
}

#[test]
fn execute_path_refuses_unregistered_lift_kit_with_composition_refusal_memento() {
    let source = Input::Source {
        dialect: libsugar::core::Dialect::Other("unknown".to_string()),
        bytes: b"fn id(x: i64) -> i64 { x }".to_vec(),
    };
    let mut inputs = HashMapInputCatalog::default();
    let source_cid = inputs.insert(source);
    let path = Input::Path(Box::new(Path {
        algebra: vec![PathAlgebra {
            name: "lift".to_string(),
            kit: "lift-unknown".to_string(),
            inputs: vec![source_cid],
            depends_on: vec![],
            verb: Verb::Transform,
        }],
    }));
    let registry = KitRegistry::default();

    let err = execute_path(&path, &registry, &inputs).expect_err("unknown lift kit refuses");
    let refusal = err
        .composition_refusal()
        .expect("path executor error carries composition refusal");
    assert_eq!(refusal.header.failure_kind, "memento-required-missing");
    assert!(refusal
        .header
        .missing_memento_requirements
        .as_ref()
        .expect("missing requirements")
        .iter()
        .any(|requirement| requirement.role.as_deref() == Some("kit-registry")));
}

#[test]
fn kit_registry_register_requires_and_exposes_conformance_declaration() {
    fn register_with_declaration(
        registry: &mut KitRegistry,
        name: &str,
        kit: impl Kit + 'static,
        conformance: ConformanceDeclaration,
    ) {
        registry.register(name, kit, conformance);
    }

    let conformance = ConformanceDeclaration::NonCarrier {
        reason: "lifts source bytes to DomainClaim; no target source produced",
    };
    let mut registry = KitRegistry::default();

    register_with_declaration(
        &mut registry,
        "lift-rust",
        LiftKit::new(Dialect::Rust, "rust", vec!["true".to_string()], None),
        conformance.clone(),
    );

    assert_eq!(registry.conformance("lift-rust"), Some(&conformance));
    assert_eq!(registry.conformance("unknown"), None);
}

#[test]
fn conformance_declaration_round_trips_through_json() {
    fn decode(encoded: String) -> ConformanceDeclaration {
        let encoded: &'static str = Box::leak(encoded.into_boxed_str());
        serde_json::from_str(encoded).expect("conformance declaration decodes")
    }

    let carrier = ConformanceDeclaration::Carrier {
        fixtures_path: PathBuf::from("implementations/rust/conformance/fixtures"),
    };
    let non_carrier = ConformanceDeclaration::NonCarrier {
        reason: "lifts source bytes to DomainClaim; no target source produced",
    };

    let carrier_json = serde_json::to_string(&carrier).expect("carrier serializes");
    let non_carrier_json = serde_json::to_string(&non_carrier).expect("non-carrier serializes");

    assert_eq!(decode(carrier_json), carrier);
    assert_eq!(decode(non_carrier_json), non_carrier);
}

fn refusal_for_failure_kind(
    failure_kind: &str,
    failure_detail: &str,
) -> CompositionBoundaryMemento {
    let atoms_cids = vec![address(&format!("atom:{failure_kind}")).to_string()];
    let effect_set_cids = Vec::new();
    let compose_input_cid =
        composition_refusal_compose_input_cid(&atoms_cids, &effect_set_cids, "1.0.0");
    let mut header = CompositionRefusalHeader {
        atoms_cids,
        blocking_effects: None,
        ccp_version: "1.0.0".to_string(),
        cid: String::new(),
        compose_input_cid,
        effect_occurrences: Some(vec![]),
        effect_set_cids,
        failure_detail: failure_detail.to_string(),
        failure_kind: failure_kind.to_string(),
        incompatible_pair: None,
        kind: "composition-refusal".to_string(),
        missing_memento_requirements: None,
        schema_version: "1".to_string(),
    };
    header.cid = composition_refusal_header_cid(&header);
    let metadata = CompositionRefusalMetadata::default();
    let signature = composition_refusal_signature(&header, &metadata);
    CompositionBoundaryMemento {
        envelope: CompositionRefusalEnvelope {
            declared_at: "1970-01-01T00:00:00Z".to_string(),
            signature,
            signer: "substrate:test".to_string(),
        },
        header,
        metadata,
    }
}

#[test]
fn target_failure_kinds_round_trip_through_jcs() {
    let cases = [
        (
            "target-compile-failure",
            "compiler stderr: missing semicolon",
        ),
        (
            "target-behavior-divergence",
            "expected stdout 1; observed stdout 2",
        ),
    ];

    for (failure_kind, failure_detail) in cases {
        let refusal = refusal_for_failure_kind(failure_kind, failure_detail);
        let value = serde_json::to_value(&refusal).expect("refusal serializes");
        let jcs = libsugar::canonical::json_jcs(&value).expect("refusal JCS");
        let decoded: CompositionBoundaryMemento =
            serde_json::from_str(&jcs).expect("JCS refusal decodes");

        assert_eq!(decoded, refusal);
        assert_eq!(decoded.header.failure_kind, failure_kind);
        assert_eq!(decoded.header.failure_detail, failure_detail);
        assert_eq!(
            composition_refusal_header_cid(&decoded.header),
            decoded.header.cid
        );
    }
}

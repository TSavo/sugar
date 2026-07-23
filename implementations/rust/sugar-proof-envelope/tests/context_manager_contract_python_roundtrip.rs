use std::path::PathBuf;
use std::process::Command;

use serde_json::Value as Json;
use sugar_proof_envelope::{AnchoredMember, ContextManagerSemanticsV1, Member, MementoCid};

fn python_derived_member() -> Json {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf();
    let python_path = repo.join("implementations/python/sugar-lift-py-tests/src");
    let program = r#"
import dataclasses
import json
from sugar_lift_py_tests.context_manager_contract import *
from sugar_lift_py_tests.context_manager_contract import _cid_of_json
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.signing import Signer

cid = lambda c: 'blake3-512:' + c * 128
resolved = SourceFragmentCoordinateV1(cid('d'), 10, 2, 20, 4)
use = SourceFragmentCoordinateV1(cid('u'), 30, 1, 30, 18)
base = ContextManagerDerivationProvenanceV1(
    distribution_artifact_cid=cid('a'), dependency_artifact_graph_cid=cid('b'),
    module_identity_cid=cid('c'), module_source_cid=cid('d'),
    re_export_warrant_cids=(cid('e'),), resolved_definition=resolved,
    resolved_definition_cid=_cid_of_json(resolved.wire()),
    manager_construction_cid=cid('f'), enter_testimony_cid=cid('1'),
    exit_testimony_cid=cid('2'), use_site=use,
    use_site_cid=_cid_of_json(use.wire()), derivation_algorithm_cid=cid('3'),
    derivation_cid=cid('0'))
wire = derivation_provenance_to_dict(base)
base = dataclasses.replace(base, derivation_cid=_cid_of_json({k:v for k,v in wire.items() if k != 'derivationCid'}))
signature = ImportSignatureV2((CallParameterV1('expected', PrimitiveSort('Value'), PositionalOrKeywordV1(), True, NoDefaultV1()),))
semantics = EffectBoundarySemanticsV1(ExpectsModeV1(), RaiseEffectKindV1(), FormalArgumentProjectionV1(0), NoMessagePatternV1(), ExceptionInfoBindingV1())
m = seal_derived_context_manager_contract(import_signature=signature, semantics=semantics, provenance=base, signer=Signer(bytes(range(32)), 'construction-deriver'), declared_at='2026-07-22T00:00:00.000Z')
print(json.dumps({'cid': m.cid, 'member': json.loads(m.canonical_bytes)}))
"#;
    let output = Command::new("python3")
        .env("PYTHONPATH", python_path)
        .arg("-c")
        .arg(program)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}

#[test]
fn python_derived_cm_summary_round_trips_with_construction_provenance() {
    let wire = python_derived_member();
    let cid = MementoCid::try_parse(wire["cid"].as_str().unwrap().to_string()).unwrap();
    let anchored = AnchoredMember::new(cid, wire["member"].clone()).unwrap();
    let Member::ContextManagerContract(cm) = Member::from_value(anchored.envelope()).unwrap()
    else {
        panic!("dedicated CM member")
    };
    assert_eq!(
        cm.contract_cid.as_str(),
        wire["member"]["header"]["contractCid"]
    );
    assert_eq!(
        cm.provenance.manager_construction_cid,
        "blake3-512:".to_owned() + &"f".repeat(128)
    );
    assert_eq!(
        cm.provenance.enter_testimony_cid,
        "blake3-512:".to_owned() + &"1".repeat(128)
    );
    assert_eq!(
        cm.provenance.exit_testimony_cid,
        "blake3-512:".to_owned() + &"2".repeat(128)
    );
    assert!(matches!(
        cm.semantics,
        ContextManagerSemanticsV1::EffectBoundary(_)
    ));
}

#[test]
fn legacy_admission_owned_header_is_not_a_derived_contract() {
    let mut wire = python_derived_member();
    wire["member"]["header"]["admissionAuthorityCid"] =
        Json::String("blake3-512:".to_owned() + &"9".repeat(128));
    let cid = MementoCid::try_parse(wire["cid"].as_str().unwrap().to_string()).unwrap();
    assert!(AnchoredMember::new(cid, wire["member"].clone()).is_err());
}

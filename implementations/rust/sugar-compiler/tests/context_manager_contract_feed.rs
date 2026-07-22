use std::path::PathBuf;
use std::process::Command;

use serde_json::Value as Json;
use sugar_compiler::feed_from_tree::graph_from_context_manager_contract_ir;
use sugar_proof_envelope::{ExitDispositionV1, Member, MemberKind};

#[test]
fn production_kit_declaration_becomes_bodyless_signed_graph_member() {
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf();
    let python_path = repo.join("implementations/python/sugar-lift-py-tests/src");
    let program = r#"
import json
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.kit_rpc import ContextManagerContractIrV1, ImportSignatureV1
row = ContextManagerContractIrV1.never_suppresses(bridge_source_symbol='context-manager:fixture_python.never_closing', import_signature=ImportSignatureV1(formals=(), sorts=()), enter_result_sort=PrimitiveSort('Value'), source_warrants=('blake3-512:' + 'a' * 128,))
print(json.dumps(row.to_rpc_with_term_table(None)))
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
    let row: Json = serde_json::from_slice(&output.stdout).unwrap();
    let graph = graph_from_context_manager_contract_ir(&row).expect("dedicated CM feed arm");
    assert_eq!(graph.atoms().count(), 0);
    assert_eq!(graph.bodies().count(), 0);
    let views: Vec<_> = graph.members_view().collect();
    assert_eq!(views.len(), 1);
    assert_eq!(views[0].kind(), Some(MemberKind::ContextManagerContract));
    assert_eq!(views[0].body_cid(), None);
    let Member::ContextManagerContract(cm) = Member::parse(views[0].bytes()).unwrap() else {
        panic!("dedicated CM member")
    };
    assert_eq!(
        cm.semantics.exit.disposition,
        ExitDispositionV1::NeverSuppresses
    );
}

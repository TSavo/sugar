use std::fs;
use std::io::Write as _;
use std::path::Path;

use tempfile::TempDir;

use sugar_claim_envelope::{KitDeclaration, KIT_DECLARATION_RPC_METHOD};

fn make_executable(path: &Path, body: &str) {
    {
        let mut file = fs::File::create(path).expect("create stub");
        file.write_all(body.as_bytes()).expect("write stub");
        file.sync_all().expect("sync stub");
    }
    let mut perms = fs::metadata(path).expect("metadata").permissions();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        perms.set_mode(0o755);
    }
    fs::set_permissions(path, perms).expect("chmod");
}

fn shell_stub_command(path: &Path) -> Vec<String> {
    vec!["sh".to_string(), path.display().to_string()]
}

#[test]
fn make_executable_syncs_writer_before_chmod() {
    let source = include_str!("kit_declaration_rpc.rs");
    let helper_start = source
        .find("fn make_executable(path: &Path, body: &str)")
        .expect("make_executable helper is present");
    let helper_end = source[helper_start..]
        .find("\nfn shell_stub_command")
        .expect("shell_stub_command follows make_executable");
    let helper = &source[helper_start..helper_start + helper_end];

    assert!(
        helper.contains("fs::File::create(path)"),
        "make_executable must create the script with an explicit writer"
    );
    assert!(
        helper.contains("write_all(body.as_bytes())"),
        "make_executable must write the full script body before chmod/spawn"
    );
    assert!(
        helper.contains("sync_all()"),
        "make_executable must sync the script before chmod/spawn"
    );
    assert!(
        !helper.contains("fs::write(path, body)"),
        "make_executable must not rely on fs::write for executable test stubs"
    );

    let sync_pos = helper.find("sync_all()").expect("sync_all checked above");
    let chmod_pos = helper
        .find("set_permissions")
        .expect("chmod call remains in helper");
    let metadata_pos = helper
        .find("let mut perms")
        .expect("permission setup remains in helper");
    assert!(
        sync_pos < metadata_pos && metadata_pos < chmod_pos,
        "make_executable must sync and close the writer before chmod"
    );
}

#[test]
fn loader_sends_kit_declaration_rpc_and_parses_result() {
    let td = TempDir::new().expect("tempdir");
    let marker = td.path().join("method-seen");
    let stub = td.path().join("kit.sh");
    make_executable(
        &stub,
        &format!(
            r#"#!/bin/sh
marker={marker}
while IFS= read -r line; do
  case "$line" in
    *initialize*)
      printf '%s\n' '{{"jsonrpc":"2.0","id":1,"result":{{"name":"stub-kit","protocol_version":"pep/1.7.0","capabilities":{{}}}}}}'
      ;;
    *sugar.plugin.kit_declaration*)
      printf '%s' "$line" > "$marker"
      printf '%s\n' '{{"jsonrpc":"2.0","id":2,"result":{{"kit":{{"id":"stub-kit","language":"rust","version":"0.1.0"}},"rpc":{{"methods":[{{"name":"sugar.plugin.kit_declaration","required":true}}]}},"proofResolution":{{"strategy":"rpc-proof-bytes","rpcMethod":"sugar.plugin.resolve_dependency_proofs"}},"effectKinds":["panic-freedom"],"effectLeaves":[{{"surface":"rust-implications","local":"method:unwrap","concept":"concept:panic-freedom.leaf.unwrap"}}],"guardPredicates":[],"controlCarriers":[],"residueCategories":[]}}}}'
      ;;
    *shutdown*)
      printf '%s\n' '{{"jsonrpc":"2.0","id":3,"result":null}}'
      exit 0
      ;;
  esac
done
"#,
            marker = marker.display()
        ),
    );

    let declaration: KitDeclaration =
        sugar_compiler::kit_declaration::load_kit_declaration_with_command(
            &shell_stub_command(&stub),
            Some(td.path()),
        )
        .expect("load declaration");

    assert_eq!(declaration.kit.id, "stub-kit");
    assert!(
        fs::read_to_string(marker)
            .expect("marker")
            .contains(KIT_DECLARATION_RPC_METHOD),
        "loader must request the dedicated declaration RPC method"
    );
}

#[test]
fn loader_reports_missing_kit_declaration_method() {
    let td = TempDir::new().expect("tempdir");
    let stub = td.path().join("kit.sh");
    make_executable(
        &stub,
        r#"#!/bin/sh
while IFS= read -r line; do
  case "$line" in
    *initialize*)
      printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"stub-kit","protocol_version":"pep/1.7.0","capabilities":{}}}'
      ;;
    *sugar.plugin.kit_declaration*)
      printf '%s\n' '{"jsonrpc":"2.0","id":2,"error":{"code":-32601,"message":"method not found: sugar.plugin.kit_declaration"}}'
      ;;
  esac
done
"#,
    );

    let err = sugar_compiler::kit_declaration::load_kit_declaration_with_command(
        &shell_stub_command(&stub),
        Some(td.path()),
    )
    .expect_err("missing declaration method should fail");

    assert!(
        err.to_string().contains(KIT_DECLARATION_RPC_METHOD),
        "error should name missing RPC method: {err}"
    );
}

#[test]
fn loader_accepts_empty_effect_kinds_for_emit_only_kit() {
    let td = TempDir::new().expect("tempdir");
    let stub = td.path().join("kit.sh");
    make_executable(
        &stub,
        r#"#!/bin/sh
while IFS= read -r line; do
  case "$line" in
    *initialize*)
      printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"python-hypothesis","protocol_version":"pep/1.7.0","capabilities":{}}}'
      ;;
    *sugar.plugin.kit_declaration*)
      printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"python-hypothesis","language":"python","version":"0.1.0"},"rpc":{"methods":[{"name":"initialize","required":true},{"name":"sugar.plugin.kit_declaration","required":true},{"name":"sugar.plugin.invoke","required":true},{"name":"sugar.plugin.check","required":false},{"name":"sugar.plugin.shutdown","required":false}]},"proofResolution":{"strategy":"pip"},"effectKinds":[],"effectLeaves":[],"guardPredicates":[],"controlCarriers":[],"residueCategories":[]}}'
      ;;
    *shutdown*)
      printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
      exit 0
      ;;
  esac
done
"#,
    );

    let declaration: KitDeclaration =
        sugar_compiler::kit_declaration::load_kit_declaration_with_command(
            &shell_stub_command(&stub),
            Some(td.path()),
        )
        .expect("load declaration");

    assert_eq!(declaration.kit.id, "python-hypothesis");
    assert_eq!(declaration.kit.language, "python");
    assert_eq!(declaration.proof_resolution.strategy, "pip");
}

#[test]
fn loader_accepts_empty_effect_kinds_for_python_lift_kit() {
    let td = TempDir::new().expect("tempdir");
    let stub = td.path().join("kit.sh");
    make_executable(
        &stub,
        r#"#!/bin/sh
while IFS= read -r line; do
  case "$line" in
    *initialize*)
      printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"sugar-lsp-python","version":"0.1.0","protocol_version":"sugar-lsp-shared/1","kit_id":"python","capabilities":{}}}'
      ;;
    *sugar.plugin.kit_declaration*)
      printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kit":{"id":"python","language":"python","version":"0.1.0"},"rpc":{"methods":[{"name":"initialize","required":true},{"name":"sugar.plugin.kit_declaration","required":true},{"name":"analyzeDocument","required":false},{"name":"parse","required":false},{"name":"lift","required":true},{"name":"sugar.plugin.lift_implications","required":false},{"name":"shutdown","required":false}]},"proofResolution":{"strategy":"pip"},"effectKinds":[],"effectLeaves":[],"guardPredicates":[],"controlCarriers":[],"residueCategories":[]}}'
      ;;
    *shutdown*)
      printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
      exit 0
      ;;
  esac
done
"#,
    );

    let declaration: KitDeclaration =
        sugar_compiler::kit_declaration::load_kit_declaration_with_command(
            &shell_stub_command(&stub),
            Some(td.path()),
        )
        .expect("load declaration");

    assert_eq!(declaration.kit.id, "python");
    assert_eq!(declaration.kit.language, "python");
    assert_eq!(declaration.proof_resolution.strategy, "pip");
    assert!(declaration
        .rpc
        .methods
        .iter()
        .any(|method| method.name == "sugar.plugin.lift_implications"));
}

#[test]
fn loader_rejects_kit_declaration_response_id_mismatch() {
    let td = TempDir::new().expect("tempdir");
    let stub = td.path().join("kit.sh");
    make_executable(
        &stub,
        r#"#!/bin/sh
while IFS= read -r line; do
  case "$line" in
    *initialize*)
      printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"stub-kit","protocol_version":"pep/1.7.0","capabilities":{}}}'
      ;;
    *sugar.plugin.kit_declaration*)
      printf '%s\n' '{"jsonrpc":"2.0","id":99,"result":{"kit":{"id":"stub-kit","language":"rust","version":"0.1.0"},"rpc":{"methods":[{"name":"sugar.plugin.kit_declaration","required":true}]},"proofResolution":{"strategy":"rpc-proof-bytes"},"effectKinds":["panic-freedom"],"effectLeaves":[],"guardPredicates":[],"controlCarriers":[],"residueCategories":[]}}'
      ;;
  esac
done
"#,
    );

    let err = sugar_compiler::kit_declaration::load_kit_declaration_with_command(
        &shell_stub_command(&stub),
        Some(td.path()),
    )
    .expect_err("response id mismatch should fail");

    assert!(
        err.to_string().contains("response id mismatch"),
        "error should describe mismatched response id: {err}"
    );
}

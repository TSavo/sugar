// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Integration tests for sugar-plugin-loader (PEP 1.7.0).
//
// Test inventory:
//   file_load_valid_fixture          — §3 + §6: load fixture JSON, assert CID matches pinned value
//   file_load_nonexistent_emits_failure_memento — §8: missing file produces PluginLoadFailureMemento
//   file_load_round_trip_cid         — §6.2: CID is delivery-independent (file == computed)
//   rpc_stdio_load_valid             — §4: spawn stub_rpc_server binary, assert loaded plugin CID
//   registry_lookup_by_kind_cid      — §9: (kind, cid) round-trip
//   registry_memento_includes_loaded_cid — §9.1 + §9.4: registry CID non-empty, loaded CIDs present
//   failure_memento_for_nonexistent  — §8.1: PluginLoadFailureMemento for file-not-found

use std::path::PathBuf;

use sugar_plugin_loader::{
    error::LoadError,
    load_plugin_from_file, load_plugin_from_rpc,
    registry::{mint_failure_memento, PluginRegistry},
    types::FailureReasonKind,
};

/// Absolute path to the tests/fixtures/ directory relative to this file.
fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures")
}

// ---------------------------------------------------------------------------
// §3 + §6: File interface
// ---------------------------------------------------------------------------

#[test]
fn file_load_valid_fixture() {
    let path = fixtures_dir().join("dummy-sugar.json");
    let plugin = load_plugin_from_file(&path).expect("should load valid fixture");
    // Assert pinned CID (§6.1 byte-stability guarantee).
    assert_eq!(
        plugin.cid(),
        "blake3-512:ad148c5f529aab7b019c8980ffa2b2f0d982fd43799a4ee87a01e3e3d5da6cd414beac89adddbad09c03d398b77ec2cda74bc04fe63b1494e6d1bed8880fd7ea",
        "CID must match the pinned value"
    );
    assert_eq!(plugin.kind(), "test:dummy");
    assert!(!plugin.is_critical());
    assert_eq!(
        plugin.header.protocol_versions,
        vec!["pep/1.7.0".to_string()]
    );
}

#[test]
fn file_load_round_trip_cid() {
    // The CID in the fixture JSON was computed via compute_plugin_cid().
    // Load the file and verify the loader re-computes and accepts the same CID.
    // This is the §6.2 delivery-independence invariant for file delivery.
    let path = fixtures_dir().join("dummy-sugar.json");
    let plugin = load_plugin_from_file(&path).expect("should load");
    // If this returns Ok the loader confirmed computed == asserted.
    let _ = plugin.cid();
}

#[test]
fn file_load_nonexistent_returns_file_not_found_error() {
    let path = PathBuf::from("/this/path/does/not/exist/missing.json");
    let err = load_plugin_from_file(&path).expect_err("should fail");
    assert!(
        matches!(err, LoadError::FileNotFound { .. }),
        "expected FileNotFound, got: {err:?}"
    );
}

// ---------------------------------------------------------------------------
// §8.1: PluginLoadFailureMemento
// ---------------------------------------------------------------------------

#[test]
fn failure_memento_for_nonexistent_file() {
    let path = PathBuf::from("sugar:./tests/fixtures/nonexistent.json");
    let err = LoadError::FileNotFound {
        path: path.display().to_string(),
    };
    let f = mint_failure_memento(
        "sugar:./tests/fixtures/nonexistent.json",
        "sugar",
        &err,
        "2026-05-12T00:00:00.000Z",
    );
    assert!(f.header.cid.starts_with("blake3-512:"));
    assert_eq!(f.header.reason_kind, FailureReasonKind::FileNotFound);
    assert_eq!(f.header.plugin_kind, "sugar");
    assert_eq!(
        f.header.declared_source,
        "sugar:./tests/fixtures/nonexistent.json"
    );
    // CID is deterministic — calling again must produce the same CID (§8.3).
    let f2 = mint_failure_memento(
        "sugar:./tests/fixtures/nonexistent.json",
        "sugar",
        &err,
        "2026-05-12T00:00:00.000Z",
    );
    assert_eq!(f.header.cid, f2.header.cid, "failure CID must be stable");
}

// ---------------------------------------------------------------------------
// §9: Registry semantics
// ---------------------------------------------------------------------------

#[test]
fn registry_lookup_by_kind_cid() {
    let path = fixtures_dir().join("dummy-sugar.json");
    let plugin = load_plugin_from_file(&path).expect("load fixture");
    let cid = plugin.cid().to_string();
    let kind = plugin.kind().to_string();

    let mut reg = PluginRegistry::new();
    reg.register(plugin, "tests/fixtures/dummy-sugar.json")
        .unwrap();

    let found = reg.lookup(&kind, &cid);
    assert!(
        found.is_some(),
        "lookup({kind}, {cid}) should find the plugin"
    );
    assert_eq!(found.unwrap().cid(), cid);
}

#[test]
fn registry_memento_includes_loaded_cid() {
    let path = fixtures_dir().join("dummy-sugar.json");
    let plugin = load_plugin_from_file(&path).expect("load fixture");
    let expected_cid = plugin.cid().to_string();

    let mut reg = PluginRegistry::new();
    reg.register(plugin, "tests/fixtures/dummy-sugar.json")
        .unwrap();

    let memento = reg.emit_registry_memento("2026-05-12T00:00:00.000Z");
    // §9.1: loaded must contain the plugin as a {kind, cid} entry.
    assert!(
        memento.header.loaded.iter().any(|e| e.cid == expected_cid),
        "loaded must include the plugin CID"
    );
    // §9.1: load_order must contain the plugin as a {kind, cid, source} entry.
    assert!(
        memento
            .header
            .load_order
            .iter()
            .any(|e| e.cid == expected_cid),
        "load_order must include the plugin CID"
    );
    // §9.3: registry CID must be non-empty and well-formed.
    assert!(
        memento.header.cid.starts_with("blake3-512:"),
        "registry CID must be a blake3-512 self-identifying string"
    );
    // §9.4: runtime_protocol_versions must be present.
    assert!(
        !memento.header.runtime_protocol_versions.is_empty(),
        "runtime_protocol_versions must be non-empty"
    );
}

// ---------------------------------------------------------------------------
// §4: JSON-RPC stdio interface
// ---------------------------------------------------------------------------

#[test]
fn rpc_stdio_load_valid() {
    // Spawn the stub_rpc_server binary (built as part of this crate).
    // The binary lives at target/debug/sugar-plugin-loader-stub-rpc.
    let bin = env!("CARGO_BIN_EXE_sugar-plugin-loader-stub-rpc");
    let endpoint = format!("stdio:{bin}");
    let plugin = load_plugin_from_rpc(&endpoint).expect("rpc load should succeed");

    // The stub server computes its CID live — verify it passes CID verification.
    assert!(
        plugin.cid().starts_with("blake3-512:"),
        "RPC-loaded plugin CID must be a blake3-512 string"
    );
    assert_eq!(plugin.kind(), "test:dummy");
    assert!(!plugin.is_critical());
}

#[test]
fn rpc_stdio_registry_cid_matches_file_load_when_payload_identical() {
    // §6.2: CID is delivery-independent.
    // N1 fix: the stub server now emits byte-identical JCS content to the
    // fixture file, so file-loaded CID MUST equal RPC-loaded CID.
    // This test now exercises the real invariant.
    let bin = env!("CARGO_BIN_EXE_sugar-plugin-loader-stub-rpc");
    let endpoint = format!("stdio:{bin}");
    let rpc_plugin = load_plugin_from_rpc(&endpoint).expect("rpc load");

    let path = fixtures_dir().join("dummy-sugar.json");
    let file_plugin = load_plugin_from_file(&path).expect("file load");

    assert_eq!(
        rpc_plugin.cid(),
        file_plugin.cid(),
        "§6.2 delivery-independence: CID(file) MUST equal CID(rpc) for identical content"
    );
    assert_eq!(
        rpc_plugin.cid(),
        "blake3-512:ad148c5f529aab7b019c8980ffa2b2f0d982fd43799a4ee87a01e3e3d5da6cd414beac89adddbad09c03d398b77ec2cda74bc04fe63b1494e6d1bed8880fd7ea",
        "CID must match the pinned value from the fixture file"
    );
}

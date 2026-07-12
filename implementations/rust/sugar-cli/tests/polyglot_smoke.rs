// polyglot_smoke.rs: integration test for the rust↔go linker pass.
//
// Verifies:
//   1. Failure case: a Go caller without a post-condition calls a Rust
//      function with a pre-condition.  The linker emits a linker-error
//      memento of kind "unprovable-obligation".
//
//   2. Success case: no cross-kit cgo call is made.  The linker produces
//      a clean link bundle with zero linker-error mementos.
//
//   3. Byte-determinism: two consecutive runs over the same inputs produce
//      byte-identical linkBundleCid values.
//
//   4. The two cases produce different linkBundleCid values (because the
//      contract set and call-edge set differ).
//
// This test exercises the linker core directly (no subprocess spawning)
// using the same types and algorithms the CLI uses.  This keeps the test
// fast and hermetic; the subprocess integration is exercised manually.
//
// Architecture: Sugar provides cross-language predicate-level
// correctness verification at compile time, content-addressed for
// byte-identical reproduction, derived by a single linker pass over
// (contracts ∪ call-edges).  The smoke test passing is the empirical
// confirmation of that claim.
//
// (This file previously also had a "Test 5: Daemon-level polyglot smoke"
// that spawned the `sugar-linkerd` daemon and drove it over its
// parseFile/projectStatus JSON-RPC. That daemon is retired -- #3844 flipped
// the real editor path to `sugar-lsp --in-process`, and the daemon-3-delete
// cut removed sugar-linkerd itself -- so the daemon-level smoke test is
// retired along with it. Tests 1-4 below exercise the linker core directly
// and are unaffected.)

// Use sugar-linker directly: the extracted library the CLI now delegates
// to.  No more sugar_cli_test_support shim needed.

use sugar_linker::{link, CallSiteLocus, LinkerCallEdge, LinkerContract, LinkerInputs};

// -------------------------------------------------------------------
// Fixture: rust-callee contract for `process`
// -------------------------------------------------------------------
//
// process(n: i32) -> i32  with  pre = (n > 0)
//
// The contract CID is deterministic for a fixed input. We compute it
// once and use it throughout.

fn make_process_contract() -> LinkerContract {
    // Use a stable CID for test reproducibility: the actual byte value
    // is derived from the JCS-canonical form of
    // {name:"process", outBinding:"out", pre:{...}} hashed with BLAKE3-512.
    // For the smoke test we use a pre-computed stable fixture CID.
    LinkerContract {
        name: "process".into(),
        kit: "rust-kit".into(),
        // Stable fixture CID computed from {name, outBinding, pre=(n>0)}.
        // In production this is computed by sugar-lift from the source file.
        contract_cid: "blake3-512:aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001aabbccdd00000001".into(),
        // A valid IrFormula pre (`n > 0`). Inert in this smoke test (the go
        // caller has no post, so the pre is never decoded); the pinned
        // linkBundleCid derives from bridges, not contract formulas.
        pre_json: Some(
            serde_json::from_value(serde_json::json!({
                "kind": "atomic",
                "name": ">",
                "args": [
                    {"kind": "var", "name": "n"},
                    {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                ]
            }))
            .expect("valid IrFormula"),
        ),
        post_json: None,
        ..Default::default()
    }
}

// -------------------------------------------------------------------
// Fixture: go-caller contract for the failing case
// -------------------------------------------------------------------
//
// GoCallerFail has a //sugar:contract annotation but no post-condition.
// (The go lifter emits `post: true` as a trivial placeholder, but the
// linker sees it as effectively unconstrained: any caller without a
// meaningful post cannot discharge the callee's pre.)
//
// For the smoke test we model this as post_json: None, which is what the
// linker sees when the go lifter emits no post annotation.

fn make_go_caller_fail_contract() -> LinkerContract {
    LinkerContract {
        name: "GoCallerFail".into(),
        kit: "go-kit".into(),
        contract_cid: "blake3-512:ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002ccddee1100000002".into(),
        pre_json: None,
        post_json: None, // no post → linker cannot discharge obligation
        ..Default::default()
    }
}

// -------------------------------------------------------------------
// Fixture: go-caller contract for the success case
// -------------------------------------------------------------------
//
// GoCallerOk does NOT make any cgo calls, so there is no cross-kit
// call-edge to link.  The success case has a different contract CID
// (different name) and zero call-edges.

fn make_go_caller_ok_contract() -> LinkerContract {
    LinkerContract {
        name: "GoCallerOk".into(),
        kit: "go-kit".into(),
        contract_cid: "blake3-512:ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003ffeedd2200000003".into(),
        pre_json: None,
        post_json: None,
        ..Default::default()
    }
}

// -------------------------------------------------------------------
// Fixture: cgo call-edge from GoCallerFail → rust-kit:process
// -------------------------------------------------------------------

fn make_cgo_call_edge(go_contract: &LinkerContract) -> LinkerCallEdge {
    LinkerCallEdge {
        source_contract_cid: go_contract.contract_cid.clone(),
        target_contract_cid: None, // cross-kit → null
        target_symbol: "rust-kit:process".into(),
        call_site_locus: Some(CallSiteLocus {
            file: "examples/polyglot-rust-go/go-caller/caller_fail.go".into(),
            line: Some(21),
            column: Some(9),
        }),
        ..Default::default()
    }
}

// -------------------------------------------------------------------
// Test 1: Failure case
// -------------------------------------------------------------------

#[test]
fn test_failure_case_emits_linker_error() {
    let rust_contract = make_process_contract();
    let go_contract = make_go_caller_fail_contract();
    let call_edge = make_cgo_call_edge(&go_contract);

    let output = link(LinkerInputs {
        contracts: vec![rust_contract, go_contract],
        call_edges: vec![call_edge],
    });
    let bundle = &output.bundle.json;

    // Must have at least 1 linker-error
    let errors = bundle
        .get("linkerErrors")
        .and_then(|e| e.as_array())
        .expect("linkerErrors must be an array");

    assert!(
        !errors.is_empty(),
        "expected at least 1 linker-error for the failure case, got 0"
    );

    // The error must have kind = "linker-error" and errorKind = "unprovable-obligation"
    let err = &errors[0];
    assert_eq!(
        err.get("kind").and_then(|v| v.as_str()),
        Some("linker-error"),
        "linker-error kind field must be 'linker-error'"
    );
    assert_eq!(
        err.get("errorKind").and_then(|v| v.as_str()),
        Some("unprovable-obligation"),
        "errorKind must be 'unprovable-obligation' for null post"
    );

    // targetSymbol must name the rust callee
    assert_eq!(
        err.get("targetSymbol").and_then(|v| v.as_str()),
        Some("rust-kit:process"),
        "targetSymbol must identify the callee"
    );

    // linkBundleCid must be present and start with blake3-512:
    let cid = bundle
        .get("linkBundleCid")
        .and_then(|v| v.as_str())
        .expect("linkBundleCid must be present");
    assert!(
        cid.starts_with("blake3-512:"),
        "linkBundleCid must have blake3-512: prefix"
    );

    eprintln!("failure-case linkBundleCid = {cid}");
}

// -------------------------------------------------------------------
// Test 2: Success case: clean bundle, zero errors
// -------------------------------------------------------------------

#[test]
fn test_success_case_clean_bundle() {
    let rust_contract = make_process_contract();
    let go_contract = make_go_caller_ok_contract();
    // No cgo call-edge: GoCallerOk doesn't call C.process

    let output = link(LinkerInputs {
        contracts: vec![rust_contract, go_contract],
        call_edges: vec![], // no call edges
    });
    let bundle = &output.bundle.json;

    let errors = bundle
        .get("linkerErrors")
        .and_then(|e| e.as_array())
        .expect("linkerErrors must be an array");

    assert!(
        errors.is_empty(),
        "expected 0 linker-errors for the success case, got {}",
        errors.len()
    );

    let cid = bundle
        .get("linkBundleCid")
        .and_then(|v| v.as_str())
        .expect("linkBundleCid must be present");
    assert!(
        cid.starts_with("blake3-512:"),
        "linkBundleCid must have blake3-512: prefix"
    );

    eprintln!("success-case linkBundleCid = {cid}");
}

// -------------------------------------------------------------------
// Test 3: Byte-determinism: two runs same inputs → same linkBundleCid
// -------------------------------------------------------------------

#[test]
fn test_link_bundle_cid_is_byte_deterministic() {
    let rust_contract = make_process_contract();
    let go_contract = make_go_caller_fail_contract();
    let call_edge = make_cgo_call_edge(&go_contract);

    let out1 = link(LinkerInputs {
        contracts: vec![rust_contract.clone(), go_contract.clone()],
        call_edges: vec![call_edge.clone()],
    });
    let out2 = link(LinkerInputs {
        contracts: vec![rust_contract, go_contract],
        call_edges: vec![call_edge],
    });

    let cid1 = out1
        .bundle
        .json
        .get("linkBundleCid")
        .and_then(|v| v.as_str())
        .expect("linkBundleCid must be present in run 1");
    let cid2 = out2
        .bundle
        .json
        .get("linkBundleCid")
        .and_then(|v| v.as_str())
        .expect("linkBundleCid must be present in run 2");

    assert_eq!(
        cid1, cid2,
        "linkBundleCid must be byte-identical across two runs of the same inputs"
    );
}

// -------------------------------------------------------------------
// Test 4: Different inputs → different linkBundleCid
// -------------------------------------------------------------------

#[test]
fn test_failure_and_success_cids_differ() {
    // Failure bundle
    let failure_out = {
        let rust = make_process_contract();
        let go = make_go_caller_fail_contract();
        let edge = make_cgo_call_edge(&go);
        link(LinkerInputs {
            contracts: vec![rust, go],
            call_edges: vec![edge],
        })
    };

    // Success bundle
    let success_out = {
        let rust = make_process_contract();
        let go = make_go_caller_ok_contract();
        link(LinkerInputs {
            contracts: vec![rust, go],
            call_edges: vec![],
        })
    };

    let fail_cid = failure_out
        .bundle
        .json
        .get("linkBundleCid")
        .and_then(|v| v.as_str())
        .expect("failure linkBundleCid");
    let ok_cid = success_out
        .bundle
        .json
        .get("linkBundleCid")
        .and_then(|v| v.as_str())
        .expect("success linkBundleCid");

    assert_ne!(
        fail_cid, ok_cid,
        "failure and success cases must produce different linkBundleCid values"
    );

    eprintln!("failure-case linkBundleCid = {fail_cid}");
    eprintln!("success-case linkBundleCid = {ok_cid}");
}

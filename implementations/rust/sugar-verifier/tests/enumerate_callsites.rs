// SPDX-License-Identifier: Apache-2.0
//
// Stage 2 (enumerate_callsites) tests. Pins:
//   - walks contract.body.pre / .post / .inv looking for ctor terms
//     whose `name` matches a known bridge sourceSymbol
//   - non-contract envelopes are skipped
//   - bridges-without-matching-ctors are not callsites
//   - ctor inside an atomic's args triggers a callsite
//   - nested ctor (ctor inside ctor args) also triggers
//   - the callsite carries the bridge's targetContractCid + layers

use std::io::{self, Write};
use std::sync::{Arc, Mutex};

use serde_json::json;
use tracing_subscriber::fmt::MakeWriter;

use sugar_verifier::{enumerate_callsites, MementoPool};

const PANIC_EFFECT_KIND: &str = "panic-freedom";

#[derive(Clone, Default)]
struct SharedLog(Arc<Mutex<Vec<u8>>>);

struct SharedLogWriter(Arc<Mutex<Vec<u8>>>);

impl Write for SharedLogWriter {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        self.0.lock().expect("log lock").extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

impl<'a> MakeWriter<'a> for SharedLog {
    type Writer = SharedLogWriter;

    fn make_writer(&'a self) -> Self::Writer {
        SharedLogWriter(self.0.clone())
    }
}

fn capture_warn_log(f: impl FnOnce()) -> String {
    let log = SharedLog::default();
    let subscriber = tracing_subscriber::fmt()
        .with_max_level(tracing::Level::WARN)
        .with_writer(log.clone())
        .with_ansi(false)
        .without_time()
        .finish();
    tracing::subscriber::with_default(subscriber, f);
    let bytes = log.0.lock().expect("log lock").clone();
    String::from_utf8(bytes).expect("log is utf8")
}

fn pool_with_bridge_and_contract(
    bridge_symbol: &str,
    target_cid: &str,
    contract_body: serde_json::Value,
) -> MementoPool {
    let mut pool = MementoPool::default();

    let bridge_env = json!({
        "evidence": {
            "kind": "bridge",
            "body": {
                "sourceSymbol": bridge_symbol,
                "sourceLayer": "ts",
                "targetContractCid": target_cid,
                "targetLayer": "rust-kit"
            }
        }
    });
    pool.insert_bridge_by_symbol(
        bridge_symbol,
        format!("blake3-512:bridge-{bridge_symbol}"),
        bridge_env,
    );

    let contract_env = json!({
        "evidence": {
            "kind": "contract",
            "body": contract_body
        }
    });
    let contract_cid = format!("blake3-512:c-{bridge_symbol}");
    pool.mementos.insert(contract_cid, contract_env);
    pool
}

// ---------------------------------------------------------------------------
// Happy path: ctor inside an atomic's args triggers a callsite
// ---------------------------------------------------------------------------

#[test]
fn finds_ctor_in_atomic_args_in_pre() {
    let target_cid = "blake3-512:target";
    let pool = pool_with_bridge_and_contract(
        "parseInt",
        target_cid,
        json!({
            "contractName": "useParseInt",
            "pre": {
                "kind": "atomic", "name": ">",
                "args": [
                    {"kind": "ctor", "name": "parseInt", "args": [{"kind": "var", "name": "s"}]},
                    {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                ]
            }
        }),
    );
    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 1);
    assert_eq!(cs[0].bridge_ir_name, "parseInt");
    assert_eq!(cs[0].bridge_target_cid, target_cid);
    assert_eq!(cs[0].bridge_source_layer, "ts");
    assert_eq!(cs[0].bridge_target_layer, "rust-kit");
    assert_eq!(cs[0].property_name, "useParseInt");
}

#[test]
fn callsite_carries_formal_actuals_from_bridge_callsite() {
    let target_cid = "blake3-512:target";
    let mut pool = MementoPool::default();
    pool.insert_bridge_by_symbol(
        "method:to_digit",
        "blake3-512:method-to-digit-bridge",
        json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": "method:to_digit",
                    "sourceLayer": "rust",
                    "targetContractCid": target_cid,
                    "targetLayer": "rust-tests",
                    "callsite": {
                        "panicSite": false,
                        "formalActuals": {
                            "self": {"kind": "var", "name": "ch"},
                            "radix": {"kind": "const", "value": 16, "sort": {"kind": "primitive", "name": "Int"}}
                        }
                    }
                }
            }
        }),
    );
    pool.mementos.insert(
        "blake3-512:caller".into(),
        json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "contractName": "caller",
                    "post": {"kind": "atomic", "name": "=", "args": [
                        {"kind": "ctor", "name": "method:to_digit", "args": [
                            {"kind": "var", "name": "ch"},
                            {"kind": "const", "value": 16, "sort": {"kind": "primitive", "name": "Int"}}
                        ]},
                        {"kind": "const", "value": 10, "sort": {"kind": "primitive", "name": "Int"}}
                    ]}
                }
            }
        }),
    );
    let sites = enumerate_callsites::run(&pool);
    assert_eq!(sites.len(), 1);
    assert_eq!(
        sites[0].formal_actuals,
        Some(json!({
            "self": {"kind": "var", "name": "ch"},
            "radix": {"kind": "const", "value": 16, "sort": {"kind": "primitive", "name": "Int"}}
        }))
    );
}

#[test]
fn finds_ctor_in_post_slot() {
    let target_cid = "blake3-512:target";
    let pool = pool_with_bridge_and_contract(
        "parseInt",
        target_cid,
        json!({
            "contractName": "p",
            "post": {
                "kind": "atomic", "name": "=",
                "args": [
                    {"kind": "var", "name": "out"},
                    {"kind": "ctor", "name": "parseInt", "args": [{"kind": "var", "name": "s"}]}
                ]
            }
        }),
    );
    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 1);
}

#[test]
fn finds_ctor_in_inv_slot() {
    let target_cid = "blake3-512:target";
    let pool = pool_with_bridge_and_contract(
        "parseInt",
        target_cid,
        json!({
            "contractName": "p",
            "inv": {
                "kind": "atomic", "name": ">",
                "args": [
                    {"kind": "ctor", "name": "parseInt", "args": [{"kind": "var", "name": "s"}]},
                    {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                ]
            }
        }),
    );
    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 1);
}

#[test]
fn finds_ctor_under_quantifier_body() {
    let target_cid = "blake3-512:target";
    let pool = pool_with_bridge_and_contract(
        "parseInt",
        target_cid,
        json!({
            "contractName": "p",
            "pre": {
                "kind": "forall", "name": "s",
                "sort": {"kind": "primitive", "name": "String"},
                "body": {
                    "kind": "atomic", "name": ">",
                    "args": [
                        {"kind": "ctor", "name": "parseInt", "args": [{"kind": "var", "name": "s"}]},
                        {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                    ]
                }
            }
        }),
    );
    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 1);
}

#[test]
fn finds_ctor_inside_connective_operands() {
    let target_cid = "blake3-512:target";
    let pool = pool_with_bridge_and_contract(
        "parseInt",
        target_cid,
        json!({
            "contractName": "p",
            "pre": {
                "kind": "and",
                "operands": [
                    {"kind": "atomic", "name": ">",
                     "args": [
                         {"kind": "ctor", "name": "parseInt", "args": [{"kind": "var", "name": "s"}]},
                         {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                     ]
                    }
                ]
            }
        }),
    );
    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 1);
}

// ---------------------------------------------------------------------------
// Negative cases
// ---------------------------------------------------------------------------

#[test]
fn no_callsite_when_no_bridges_registered() {
    let mut pool = MementoPool::default();
    pool.mementos.insert(
        "blake3-512:c".into(),
        json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "contractName": "p",
                    "pre": {
                        "kind": "atomic", "name": ">",
                        "args": [
                            {"kind": "ctor", "name": "parseInt", "args": []},
                            {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                        ]
                    }
                }
            }
        }),
    );
    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 0);
}

#[test]
fn no_callsite_for_ctor_name_with_no_matching_bridge() {
    let target_cid = "blake3-512:target";
    let pool = pool_with_bridge_and_contract(
        "parseInt",
        target_cid,
        json!({
            "contractName": "p",
            "pre": {
                "kind": "atomic", "name": ">",
                "args": [
                    {"kind": "ctor", "name": "atoi", "args": []},
                    {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                ]
            }
        }),
    );
    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 0);
}

#[test]
fn skips_non_contract_envelopes() {
    let mut pool = MementoPool::default();
    // A bridge envelope (kind=bridge): should not be walked.
    pool.mementos.insert(
        "blake3-512:bridge".into(),
        json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": "parseInt",
                    "pre": {
                        "kind": "atomic", "name": ">",
                        "args": [
                            {"kind": "ctor", "name": "parseInt", "args": []},
                            {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                        ]
                    }
                }
            }
        }),
    );
    pool.insert_bridge_by_symbol(
        "parseInt",
        "blake3-512:parse-int-bridge",
        json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": "parseInt",
                    "targetContractCid": "blake3-512:t"
                }
            }
        }),
    );
    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 0);
}

#[test]
fn nested_ctor_in_ctor_args_also_finds_callsite() {
    let target_cid = "blake3-512:target";
    let pool = pool_with_bridge_and_contract(
        "parseInt",
        target_cid,
        json!({
            "contractName": "p",
            "pre": {
                "kind": "atomic", "name": "=",
                "args": [
                    {"kind": "ctor", "name": "wrap", "args": [
                        {"kind": "ctor", "name": "parseInt", "args": [{"kind": "var", "name": "s"}]}
                    ]},
                    {"kind": "var", "name": "out"}
                ]
            }
        }),
    );
    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 1);
}

#[test]
fn property_name_falls_back_to_cid_prefix_when_contract_name_absent() {
    let target_cid = "blake3-512:target";
    let mut pool = pool_with_bridge_and_contract(
        "parseInt",
        target_cid,
        json!({
            // no contractName
            "pre": {
                "kind": "atomic", "name": ">",
                "args": [
                    {"kind": "ctor", "name": "parseInt", "args": []},
                    {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                ]
            }
        }),
    );
    // contract CID was set to "blake3-512:c-parseInt" by the helper.
    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 1);
    // Fallback prefix is the first 12 chars of the CID + "...".
    assert!(cs[0].property_name.ends_with("..."));
    assert_eq!(cs[0].property_name.chars().take(12).count(), 12);
    let _ = &mut pool;
}

#[test]
fn callsite_carries_arg_term_from_atomic() {
    let target_cid = "blake3-512:target";
    let pool = pool_with_bridge_and_contract(
        "parseInt",
        target_cid,
        json!({
            "contractName": "p",
            "pre": {
                "kind": "atomic", "name": ">",
                "args": [
                    {"kind": "ctor", "name": "parseInt", "args": [{"kind": "var", "name": "input_string"}]},
                    {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                ]
            }
        }),
    );
    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 1);
    let arg = cs[0].arg_term.as_ref().expect("arg present");
    assert_eq!(arg.get("name").unwrap(), "input_string");
}

#[test]
fn callsite_carries_all_arg_terms_from_atomic() {
    let target_cid = "blake3-512:target";
    let pool = pool_with_bridge_and_contract(
        "method:to_digit",
        target_cid,
        json!({
            "contractName": "p",
            "post": {
                "kind": "atomic", "name": "=",
                "args": [
                    {"kind": "ctor", "name": "method:to_digit", "args": [
                        {"kind": "var", "name": "self"},
                        {"kind": "const", "value": 16, "sort": {"kind": "primitive", "name": "Int"}}
                    ]},
                    {"kind": "var", "name": "out"}
                ]
            }
        }),
    );
    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 1);
    assert_eq!(
        cs[0].arg_term,
        Some(json!({"kind": "var", "name": "self"})),
        "legacy first-arg field stays stable"
    );
    assert_eq!(
        cs[0].arg_terms,
        vec![
            json!({"kind": "var", "name": "self"}),
            json!({"kind": "const", "value": 16, "sort": {"kind": "primitive", "name": "Int"}})
        ],
        "multi-formal precondition discharge needs every actual in source order"
    );
}

#[test]
fn multiple_callsites_in_same_contract_each_listed() {
    let target_cid = "blake3-512:target";
    let pool = pool_with_bridge_and_contract(
        "parseInt",
        target_cid,
        json!({
            "contractName": "p",
            "pre": {
                "kind": "and",
                "operands": [
                    {"kind": "atomic", "name": ">",
                     "args": [
                         {"kind": "ctor", "name": "parseInt", "args": [{"kind": "var", "name": "a"}]},
                         {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                     ]},
                    {"kind": "atomic", "name": ">",
                     "args": [
                         {"kind": "ctor", "name": "parseInt", "args": [{"kind": "var", "name": "b"}]},
                         {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
                     ]}
                ]
            }
        }),
    );
    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 2);
}

#[test]
fn panic_callsite_carries_containing_contract_bundle_not_global_symbol_bundle() {
    let property_cid = "blake3-512:imported-libsugar-contract";
    let property_bundle = "blake3-512:imported-libsugar-proof";
    let wrong_global_bundle = "blake3-512:target-proof-global-method-expect";
    let receiver = json!({
        "kind": "ctor",
        "name": "to_value",
        "args": [{"kind": "var", "name": "req"}]
    });

    let mut pool = MementoPool::default();
    let bridge = json!({
        "evidence": {
            "kind": "bridge",
            "body": {
                "sourceSymbol": "method:expect",
                "targetContractCid": "blake3-512:result-expect",
                "sourceLayer": "rust",
                "targetLayer": "rust-tests",
                "callsite": {"panicSite": true}
            }
        }
    });
    pool.insert_bridge_by_symbol(
        "method:expect",
        "blake3-512:expect-imported-bridge",
        bridge.clone(),
    );
    pool.insert_bridge_by_callsite(
        (
            property_bundle.into(),
            "src/core/types.rs".into(),
            2137,
            "method:expect".into(),
        ),
        "blake3-512:expect-imported-bridge",
        bridge,
    );
    pool.bridge_self_bundle_by_symbol
        .insert("method:expect".into(), wrong_global_bundle.into());
    pool.bundle_members
        .entry(property_bundle.into())
        .or_default()
        .insert(property_cid.into());
    pool.mementos.insert(
        property_cid.into(),
        json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "contractName": "imported_libsugar_fn",
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "out"},
                            {"kind": "ctor", "name": "method:expect", "args": [receiver.clone()]}
                        ]
                    },
                    "panicLoci": [{
                        "argTerm": receiver,
                        "file": "src/core/types.rs",
                        "line": 2137,
                        "callee": "method:expect"
                    }]
                }
            }
        }),
    );

    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 1);
    assert_eq!(
        cs[0].callsite_bundle_cid.as_deref(),
        Some(property_bundle),
        "panic producer lookup must use the bundle containing the contract being walked"
    );
    assert_eq!(
        cs[0].bridge_self_bundle_cid.as_deref(),
        Some(property_bundle),
        "panic producer lookup must not leak the global per-symbol bridge bundle"
    );
    assert_eq!(cs[0].file.as_deref(), Some("src/core/types.rs"));
    assert_eq!(cs[0].line, Some(2137));
}

#[test]
fn panic_loci_only_contract_becomes_panic_callsite() {
    let property_cid = "blake3-512:panic-loci-only-contract";
    let property_bundle = "blake3-512:panic-loci-only-proof";
    let receiver = json!({
        "kind": "ctor",
        "name": "to_string",
        "args": [{"kind": "var", "name": "req"}]
    });

    let mut pool = MementoPool::default();
    let bridge = json!({
        "evidence": {
            "kind": "bridge",
            "body": {
                "sourceSymbol": "method:expect",
                "targetContractCid": "blake3-512:result-expect",
                "sourceLayer": "rust",
                "targetLayer": "rust-tests",
                "callsite": {"panicSite": true}
            }
        }
    });
    pool.insert_bridge_by_symbol(
        "method:expect",
        "blake3-512:expect-panic-loci-only-bridge",
        bridge.clone(),
    );
    pool.insert_bridge_by_callsite(
        (
            property_bundle.into(),
            "src/kit_dispatch.rs".into(),
            2130,
            "method:expect".into(),
        ),
        "blake3-512:expect-panic-loci-only-bridge",
        bridge,
    );
    pool.bundle_members
        .entry(property_bundle.into())
        .or_default()
        .insert(property_cid.into());
    pool.mementos.insert(
        property_cid.into(),
        json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "contractName": "fixture_panic_site",
                    "panicLoci": [{
                        "argTerm": receiver,
                        "file": "src/kit_dispatch.rs",
                        "line": 2130,
                        "panicLine": 2130,
                        "callee": "method:expect"
                    }]
                }
            }
        }),
    );

    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 1);
    assert!(cs[0].panic_site);
    assert_eq!(cs[0].bridge_ir_name, "method:expect");
    assert_eq!(cs[0].bridge_target_cid, "blake3-512:result-expect");
    assert_eq!(cs[0].file.as_deref(), Some("src/kit_dispatch.rs"));
    assert_eq!(cs[0].line, Some(2130));
    assert_eq!(cs[0].callsite_bundle_cid.as_deref(), Some(property_bundle));
}

#[test]
fn panic_loci_duplicate_formula_panic_is_not_double_counted() {
    let property_cid = "blake3-512:panic-loci-duplicate-contract";
    let property_bundle = "blake3-512:panic-loci-duplicate-proof";
    let formula_receiver = json!({"kind": "var", "name": "value"});
    let locus_receiver = json!({"name": "value", "kind": "var"});

    let mut pool = MementoPool::default();
    pool.insert_bridge_by_symbol(
        "method:unwrap",
        "blake3-512:unwrap-duplicate-bridge",
        json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": "method:unwrap",
                    "targetContractCid": "blake3-512:option-unwrap",
                    "sourceLayer": "rust",
                    "targetLayer": "rust-tests",
                    "callsite": {"panicSite": true}
                }
            }
        }),
    );
    pool.bundle_members
        .entry(property_bundle.into())
        .or_default()
        .insert(property_cid.into());
    pool.mementos.insert(
        property_cid.into(),
        json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "contractName": "already_formula_backed",
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "out"},
                            {"kind": "ctor", "name": "method:unwrap", "args": [formula_receiver]}
                        ]
                    },
                    "panicLoci": [{
                        "argTerm": locus_receiver,
                        "file": "src/lib.rs",
                        "line": 25,
                        "callee": "method:unwrap"
                    }]
                }
            }
        }),
    );

    let cs = enumerate_callsites::run(&pool);
    assert_eq!(
        cs.len(),
        1,
        "panicLoci must not duplicate formula callsites"
    );
    assert!(cs[0].panic_site);
}

#[test]
fn panic_loci_without_bridge_still_surfaces_undecidable_callsite() {
    let property_cid = "blake3-512:panic-loci-missing-bridge-contract";
    let property_bundle = "blake3-512:panic-loci-missing-bridge-proof";

    let mut pool = MementoPool::default();
    pool.bundle_members
        .entry(property_bundle.into())
        .or_default()
        .insert(property_cid.into());
    pool.mementos.insert(
        property_cid.into(),
        json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "contractName": "bridge_gap_visible",
                    "panicLoci": [{
                        "argTerm": {"kind": "var", "name": "x"},
                        "file": "src/lib.rs",
                        "line": 99,
                        "callee": "method:expect"
                    }]
                }
            }
        }),
    );

    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 1);
    assert!(cs[0].panic_site);
    assert_eq!(cs[0].bridge_ir_name, "method:expect");
    assert_eq!(cs[0].bridge_target_cid, "");
    assert_eq!(cs[0].file.as_deref(), Some("src/lib.rs"));
    assert_eq!(cs[0].line, Some(99));
}

#[test]
fn effect_loci_only_contract_becomes_panic_callsite() {
    let property_cid = "blake3-512:effect-loci-only-contract";
    let property_bundle = "blake3-512:effect-loci-only-proof";
    let receiver = json!({
        "kind": "ctor",
        "name": "to_string",
        "args": [{"kind": "var", "name": "req"}]
    });

    let mut pool = MementoPool::default();
    pool.insert_bridge_by_symbol(
        "method:expect",
        "blake3-512:expect-effect-loci-only-bridge",
        json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": "method:expect",
                    "targetContractCid": "blake3-512:result-expect",
                    "sourceLayer": "rust",
                    "targetLayer": "rust-tests",
                    "callsite": {"panicSite": true}
                }
            }
        }),
    );
    pool.bundle_members
        .entry(property_bundle.into())
        .or_default()
        .insert(property_cid.into());
    pool.mementos.insert(
        property_cid.into(),
        json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "contractName": "fixture_panic_site",
                    "effectLoci": [{
                        "effectKind": PANIC_EFFECT_KIND,
                        "argTerm": receiver,
                        "file": "src/kit_dispatch.rs",
                        "line": 2130,
                        "callee": "method:expect"
                    }]
                }
            }
        }),
    );

    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 1);
    assert!(cs[0].panic_site);
    assert_eq!(cs[0].bridge_ir_name, "method:expect");
    assert_eq!(cs[0].file.as_deref(), Some("src/kit_dispatch.rs"));
    assert_eq!(cs[0].line, Some(2130));
}

#[test]
fn effect_site_concept_routes_bridge_as_panic_site() {
    let target_cid = "blake3-512:result-expect";
    let pool = pool_with_bridge_and_contract(
        "method:expect",
        target_cid,
        json!({
            "contractName": "useExpect",
            "post": {
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "var", "name": "out"},
                    {"kind": "ctor", "name": "method:expect", "args": [{"kind": "var", "name": "result"}]}
                ]
            }
        }),
    );
    let mut pool = pool;
    pool.insert_bridge_by_symbol(
        "method:expect",
        "blake3-512:expect-effect-site-bridge",
        json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": "method:expect",
                    "targetContractCid": target_cid,
                    "sourceLayer": "rust",
                    "targetLayer": "rust-tests",
                    "callsite": {
                        "effectSite": PANIC_EFFECT_KIND,
                        "file": "src/lib.rs",
                        "start_line": 25
                    }
                }
            }
        }),
    );

    let cs = enumerate_callsites::run(&pool);
    assert_eq!(cs.len(), 1);
    assert!(cs[0].panic_site);
    assert_eq!(cs[0].bridge_ir_name, "method:expect");
}

#[test]
fn non_panic_effect_loci_are_ignored() {
    let property_cid = "blake3-512:io-effect-contract";
    let mut pool = MementoPool::default();
    pool.mementos.insert(
        property_cid.into(),
        json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "contractName": "io_only",
                    "effectLoci": [{
                        "effectKind": "concept:io",
                        "argTerm": {"kind": "var", "name": "x"},
                        "file": "src/lib.rs",
                        "line": 99,
                        "callee": "method:expect"
                    }]
                }
            }
        }),
    );

    let cs = enumerate_callsites::run(&pool);
    assert!(
        cs.is_empty(),
        "non-panic effect loci must not surface panic sites"
    );
}

#[test]
fn matching_panic_loci_and_effect_loci_do_not_duplicate_callsite() {
    let property_cid = "blake3-512:matching-effect-loci-contract";
    let property_bundle = "blake3-512:matching-effect-loci-proof";
    let receiver = json!({"kind": "var", "name": "result"});
    let locus = json!({
        "argTerm": receiver,
        "file": "src/lib.rs",
        "line": 25,
        "callee": "method:unwrap"
    });
    let mut effect_locus = locus.clone();
    effect_locus
        .as_object_mut()
        .expect("effect locus object")
        .insert("effectKind".to_string(), json!(PANIC_EFFECT_KIND));

    let mut pool = MementoPool::default();
    pool.insert_bridge_by_symbol(
        "method:unwrap",
        "blake3-512:unwrap-both-effect-fields-bridge",
        json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": "method:unwrap",
                    "targetContractCid": "blake3-512:option-unwrap",
                    "sourceLayer": "rust",
                    "targetLayer": "rust-tests",
                    "callsite": {
                        "panicSite": true,
                        "effectSite": PANIC_EFFECT_KIND
                    }
                }
            }
        }),
    );
    pool.bundle_members
        .entry(property_bundle.into())
        .or_default()
        .insert(property_cid.into());
    pool.mementos.insert(
        property_cid.into(),
        json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "contractName": "both_agree",
                    "panicLoci": [locus],
                    "effectLoci": [effect_locus]
                }
            }
        }),
    );

    let cs = enumerate_callsites::run(&pool);
    assert_eq!(
        cs.len(),
        1,
        "matching old/new effect fields must not duplicate"
    );
    assert!(cs[0].panic_site);
    assert_eq!(cs[0].line, Some(25));
}

#[test]
fn disagreeing_effect_aliases_warn_and_preserve_old_panic_loci() {
    let property_cid = "blake3-512:disagreeing-effect-loci-contract";
    let property_bundle = "blake3-512:disagreeing-effect-loci-proof";
    let receiver = json!({"kind": "var", "name": "result"});

    let mut pool = MementoPool::default();
    let bridge = json!({
        "evidence": {
            "kind": "bridge",
            "body": {
                "sourceSymbol": "method:unwrap",
                "targetContractCid": "blake3-512:option-unwrap",
                "sourceLayer": "rust",
                "targetLayer": "rust-tests",
                "callsite": {
                    "panicSite": true,
                    "effectSite": "concept:io"
                }
            }
        }
    });
    pool.insert_bridge_by_symbol(
        "method:unwrap",
        "blake3-512:unwrap-disagreeing-effect-bridge",
        bridge.clone(),
    );
    pool.insert_bridge_by_callsite(
        (
            property_bundle.into(),
            "src/lib.rs".into(),
            25,
            "method:unwrap".into(),
        ),
        "blake3-512:unwrap-disagreeing-effect-bridge",
        bridge,
    );
    pool.bundle_members
        .entry(property_bundle.into())
        .or_default()
        .insert(property_cid.into());
    pool.mementos.insert(
        property_cid.into(),
        json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "contractName": "both_disagree",
                    "panicLoci": [{
                        "argTerm": receiver,
                        "file": "src/lib.rs",
                        "line": 25,
                        "callee": "method:unwrap"
                    }],
                    "effectLoci": [{
                        "effectKind": PANIC_EFFECT_KIND,
                        "argTerm": {"kind": "var", "name": "other"},
                        "file": "src/lib.rs",
                        "line": 99,
                        "callee": "method:unwrap"
                    }]
                }
            }
        }),
    );

    let mut cs = Vec::new();
    let logs = capture_warn_log(|| {
        cs = enumerate_callsites::run(&pool);
    });
    assert_eq!(cs.len(), 1);
    assert_eq!(
        cs[0].line,
        Some(25),
        "old panicLoci must win on disagreement"
    );
    assert!(
        logs.contains("effect-site-disagreement")
            && logs.contains("panicLoci")
            && logs.contains("effectLoci")
            && logs.contains("panicSite")
            && logs.contains("effectSite"),
        "disagreement must emit a structured, greppable warning; logs:\n{logs}"
    );
}

#[test]
fn formula_backed_panic_locus_warns_once_for_effect_site_disagreement() {
    let property_cid = "blake3-512:formula-backed-effect-disagreement-contract";
    let property_bundle = "blake3-512:formula-backed-effect-disagreement-proof";
    let receiver = json!({"kind": "var", "name": "result"});
    let locus = json!({
        "argTerm": receiver,
        "file": "src/lib.rs",
        "line": 25,
        "callee": "method:unwrap"
    });

    let mut pool = MementoPool::default();
    let bridge = json!({
        "evidence": {
            "kind": "bridge",
            "body": {
                "sourceSymbol": "method:unwrap",
                "targetContractCid": "blake3-512:option-unwrap",
                "sourceLayer": "rust",
                "targetLayer": "rust-tests",
                "callsite": {
                    "panicSite": true,
                    "effectSite": "concept:io"
                }
            }
        }
    });
    pool.insert_bridge_by_symbol(
        "method:unwrap",
        "blake3-512:unwrap-effect-only-bridge",
        bridge.clone(),
    );
    pool.insert_bridge_by_callsite(
        (
            property_bundle.into(),
            "src/lib.rs".into(),
            25,
            "method:unwrap".into(),
        ),
        "blake3-512:unwrap-effect-only-bridge",
        bridge,
    );
    pool.bundle_members
        .entry(property_bundle.into())
        .or_default()
        .insert(property_cid.into());
    pool.mementos.insert(
        property_cid.into(),
        json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "contractName": "formula_backed_disagreement",
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "out"},
                            {"kind": "ctor", "name": "method:unwrap", "args": [locus["argTerm"].clone()]}
                        ]
                    },
                    "panicLoci": [locus]
                }
            }
        }),
    );

    let mut cs = Vec::new();
    let logs = capture_warn_log(|| {
        cs = enumerate_callsites::run(&pool);
    });
    assert_eq!(
        cs.len(),
        1,
        "formula callsite and panicLoci fallback must dedup"
    );
    assert_eq!(
        logs.matches("panicSite/effectSite").count(),
        1,
        "one callsite disagreement must warn once; logs:\n{logs}"
    );
}

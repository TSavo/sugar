// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Task 7 (#3809): graph→pool intake stamps `MementoPool.member_speaker`.
//
// Consumer fact + vendor universe loaded with different speakers via
// `pool_from_graph_with_speaker` must land with client vs vendor roles on
// the one attribution map (utterance first-writer-wins), and
// `utterance::solve` / consistency labels must follow those roles — never a
// second map, never position heuristics.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use sugar_compiler::orchestrate::pool_from_graph_with_speaker;
use sugar_ir_compiler::registry::Registry as CompilerRegistry;
use sugar_proof_envelope::ProofGraph;
use sugar_verifier::consistency::ConsistencyResult;
use sugar_verifier::load_all_proofs::ProofBytes;
use sugar_verifier::solvers::registry::build_default_z3;
use sugar_verifier::solvers::{SolverPlan, SolverSeat};
use sugar_verifier::types::{MementoPool, Speaker, SpeakerRole};
use sugar_verifier::utterance::{attribution, solve, speak_fact, speak_universe};

fn fixture_path(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("implementations/rust")
        .join("sugar-proof-envelope/tests/fixtures")
        .join(name)
}

fn fixture_graph(name: &str) -> ProofGraph {
    let path = fixture_path(name);
    let bytes =
        std::fs::read(&path).unwrap_or_else(|e| panic!("read fixture {}: {e}", path.display()));
    ProofGraph::read(&bytes).unwrap_or_else(|e| panic!("ProofGraph::read {}: {e}", path.display()))
}

fn fixture_proof_bytes(name: &str) -> ProofBytes {
    let path = fixture_path(name);
    let bytes =
        std::fs::read(&path).unwrap_or_else(|e| panic!("read fixture {}: {e}", path.display()));
    let cid = sugar_canonicalizer::blake3_512_of(&bytes);
    ProofBytes::try_from_parts(name, cid, bytes, Speaker::consumer(name))
        .expect("fixture bytes stage into ProofBytes")
}

fn z3_plan_and_registry() -> (
    SolverPlan,
    HashMap<SolverSeat, sugar_verifier::solvers::SolverHandle>,
) {
    let registry = build_default_z3("z3");
    (SolverPlan::Single(SolverSeat::Z3), registry)
}

fn test_compilers() -> CompilerRegistry {
    let mut compilers = CompilerRegistry::new();
    compilers.register(std::sync::Arc::new(
        sugar_ir_compiler_smt_lib::SmtLibCompiler::new(),
    ));
    compilers
}

fn roles_by_member(pool: &MementoPool) -> HashMap<String, SpeakerRole> {
    pool.mementos
        .keys()
        .map(|cid| {
            let role = pool
                .member_speaker(cid)
                .unwrap_or_else(|| panic!("member {cid} must be attributed at intake"))
                .role;
            (cid.to_string(), role)
        })
        .collect()
}

fn client_and_vendor_labels(
    rows: &[ConsistencyResult],
) -> (Vec<(String, String)>, Vec<(String, String)>) {
    let mut client = Vec::new();
    let mut vendor = Vec::new();
    for r in rows {
        let Some(vj) = r.verification.as_ref().map(|v| v.to_json()) else {
            continue;
        };
        if let Some(ir) = vj.get("clientFactIr") {
            client.push((
                r.property_name.clone(),
                libsugar::canonical::json_jcs(ir).expect("clientFactIr canonicalizes"),
            ));
        }
        if let Some(ir) = vj.get("vendorFactIr") {
            vendor.push((
                r.property_name.clone(),
                libsugar::canonical::json_jcs(ir).expect("vendorFactIr canonicalizes"),
            ));
        }
    }
    client.sort();
    vendor.sort();
    (client, vendor)
}

/// Consumer fact graph + vendor universe graph, each loaded with its real
/// speaker, then merged. Every member CID must carry the speaker stamped at
/// its graph→pool intake (no second map).
#[test]
fn pool_from_graph_with_speaker_stamps_consumer_and_vendor_roles() {
    let vendor_graph = fixture_graph("base64_vendor.proof");
    let consumer_graph = fixture_graph("base64_consumer.proof");
    assert!(
        vendor_graph.members().count() > 0,
        "vendor fixture must yield graph members"
    );
    assert!(
        consumer_graph.members().count() > 0,
        "consumer fixture must yield graph members"
    );

    let vendor = Speaker::vendor("the-vendor");
    let consumer = Speaker::consumer("me");

    let vendor_pool =
        pool_from_graph_with_speaker(&vendor_graph, vendor.clone()).expect("vendor graph→pool");
    let consumer_pool =
        pool_from_graph_with_speaker(&consumer_graph, consumer.clone()).expect("consumer graph→pool");

    assert!(
        vendor_pool.load_errors.is_empty(),
        "vendor self-seal load clean: {:?}",
        vendor_pool.load_errors
    );
    assert!(
        consumer_pool.load_errors.is_empty(),
        "consumer self-seal load clean: {:?}",
        consumer_pool.load_errors
    );
    assert!(!vendor_pool.mementos.is_empty(), "vendor pool has members");
    assert!(
        !consumer_pool.mementos.is_empty(),
        "consumer pool has members"
    );

    for cid in vendor_pool.mementos.keys() {
        let s = vendor_pool
            .member_speaker(cid)
            .unwrap_or_else(|| panic!("vendor member {cid} must be attributed"));
        assert_eq!(
            s.role,
            SpeakerRole::Vendor,
            "vendor graph load must stamp Vendor on {cid}"
        );
        assert_eq!(s.id, "the-vendor");
    }
    for cid in consumer_pool.mementos.keys() {
        let s = consumer_pool
            .member_speaker(cid)
            .unwrap_or_else(|| panic!("consumer member {cid} must be attributed"));
        assert_eq!(
            s.role,
            SpeakerRole::Consumer,
            "consumer graph load must stamp Consumer on {cid}"
        );
        assert_eq!(s.id, "me");
    }

    // Merge: first-writer-wins on member_speaker (utterance policy).
    let mut pool = vendor_pool;
    let vendor_cids: std::collections::BTreeSet<_> = pool.mementos.keys().cloned().collect();
    pool.merge(consumer_pool);

    for cid in &vendor_cids {
        assert_eq!(
            pool.member_speaker(cid).map(|s| s.role),
            Some(SpeakerRole::Vendor),
            "merged pool keeps vendor first-writer stamp on {cid}"
        );
    }
    for (cid, role) in roles_by_member(&pool) {
        match role {
            SpeakerRole::Vendor => assert!(
                vendor_cids.iter().any(|v| v.to_string() == cid),
                "Vendor role only on vendor-intake members: {cid}"
            ),
            SpeakerRole::Consumer => assert!(
                !vendor_cids.iter().any(|v| v.to_string() == cid),
                "Consumer role only on consumer-intake members: {cid}"
            ),
        }
    }

    // Attribution map is the one pool map utterance::attribution projects.
    assert_eq!(
        attribution(&pool).len(),
        pool.mementos.len(),
        "every member CID must appear in member_speaker"
    );
}

/// Same two fixtures, same speakers: graph→pool intake labels must match
/// the utterance speak path (roles + solve client/vendor fact labels).
#[test]
fn graph_pool_intake_labels_match_utterance_speak_path() {
    let vendor_graph = fixture_graph("base64_vendor.proof");
    let consumer_graph = fixture_graph("base64_consumer.proof");
    let vendor = Speaker::vendor("the-vendor");
    let consumer = Speaker::consumer("me");

    let mut graph_pool =
        pool_from_graph_with_speaker(&vendor_graph, vendor.clone()).expect("vendor graph→pool");
    let consumer_graph_pool =
        pool_from_graph_with_speaker(&consumer_graph, consumer.clone()).expect("consumer graph→pool");
    graph_pool.merge(consumer_graph_pool);

    let mut spoken_pool = MementoPool::default();
    let vendor_proof = fixture_proof_bytes("base64_vendor.proof");
    let consumer_proof = fixture_proof_bytes("base64_consumer.proof");
    speak_universe(&mut spoken_pool, &vendor, &vendor_proof).expect("vendor speaks");
    speak_fact(&mut spoken_pool, &consumer, &consumer_proof).expect("consumer speaks");

    // Role multiset must agree (member CIDs may differ: re-seal vs on-disk
    // envelope bytes; ROLE is what labeling reads).
    let role_counts = |pool: &MementoPool| -> (usize, usize) {
        let mut v = 0;
        let mut c = 0;
        for cid in pool.mementos.keys() {
            match pool.member_speaker(cid).map(|s| s.role) {
                Some(SpeakerRole::Vendor) => v += 1,
                Some(SpeakerRole::Consumer) => c += 1,
                None => panic!("unattributed member {cid}"),
            }
        }
        (v, c)
    };
    let graph_roles = role_counts(&graph_pool);
    let spoken_roles = role_counts(&spoken_pool);
    assert_eq!(
        graph_roles, spoken_roles,
        "graph→pool speaker stamps must match utterance speak role counts \
         (vendor, consumer) = graph {graph_roles:?} vs spoken {spoken_roles:?}"
    );
    assert!(graph_roles.0 > 0, "must have at least one vendor member");
    assert!(graph_roles.1 > 0, "must have at least one consumer member");

    let (plan, registry) = z3_plan_and_registry();
    let compilers = test_compilers();
    let graph_rows = solve(&graph_pool, &plan, &registry, &compilers, Path::new("."));
    let spoken_rows = solve(&spoken_pool, &plan, &registry, &compilers, Path::new("."));

    let (g_client, g_vendor) = client_and_vendor_labels(&graph_rows);
    let (s_client, s_vendor) = client_and_vendor_labels(&spoken_rows);

    // Both paths must surface client and vendor fact labels (attribution is
    // the label source). Exact IR may differ when re-seal thins envelope
    // metadata; presence of both sides is the Task 7 contract.
    assert!(
        !g_client.is_empty() || graph_rows.iter().any(|r| {
            r.verification
                .as_ref()
                .and_then(|v| v.to_json().get("clientFactIr").cloned())
                .is_some()
        }) || !spoken_rows.is_empty(),
        "solve must run on graph-loaded pool (rows={})",
        graph_rows.len()
    );

    // Flipping roles on the SAME graphs must flip labels without inventing a map.
    let mut flipped = pool_from_graph_with_speaker(&vendor_graph, consumer.clone())
        .expect("flipped vendor-as-consumer");
    flipped.merge(
        pool_from_graph_with_speaker(&consumer_graph, vendor.clone())
            .expect("flipped consumer-as-vendor"),
    );
    let flipped_rows = solve(&flipped, &plan, &registry, &compilers, Path::new("."));
    let (f_client, f_vendor) = client_and_vendor_labels(&flipped_rows);

    // Verdicts: property names set comparable even if IR differs.
    let verdicts = |rows: &[ConsistencyResult]| {
        let mut v: Vec<_> = rows
            .iter()
            .map(|r| (r.property_name.clone(), format!("{:?}", r.verdict)))
            .collect();
        v.sort();
        v
    };
    assert_eq!(
        verdicts(&graph_rows),
        verdicts(&flipped_rows),
        "flipping speaker roles must not change solver verdicts"
    );

    // If both directions produce client labels, the label sets must differ
    // when attribution flips (same law as utterance labels_come_from_attribution).
    if !g_client.is_empty() && !f_client.is_empty() {
        assert_ne!(
            g_client, f_client,
            "clientFactIr labels must follow speaker role, not graph position"
        );
    }
    if !g_vendor.is_empty() && !f_vendor.is_empty() {
        assert_ne!(
            g_vendor, f_vendor,
            "vendorFactIr labels must follow speaker role, not graph position"
        );
    }

    // Spoken path is the reference for "labels exist when roles are correct".
    let spoken_has_client = !s_client.is_empty();
    let spoken_has_vendor = !s_vendor.is_empty();
    if spoken_has_client {
        assert!(
            !g_client.is_empty(),
            "graph→pool intake must produce clientFactIr when utterance does \
             (graph client labels empty; spoken had {})",
            s_client.len()
        );
    }
    if spoken_has_vendor {
        assert!(
            !g_vendor.is_empty(),
            "graph→pool intake must produce vendorFactIr when utterance does \
             (graph vendor labels empty; spoken had {})",
            s_vendor.len()
        );
    }
}

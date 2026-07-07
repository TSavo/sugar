// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Utterance verb layer receipts (#3812), driven over the REAL base64
// vendor/consumer fixtures:
//
//   1. IDEMPOTENT RE-SPEAK: speaking the same envelope twice is a no-op --
//      the second receipt lists every member under `members_already_spoken`
//      and none under `members_spoken`, and the pool (members AND
//      attribution) is byte-for-byte unchanged. First speaker wins even when
//      a DIFFERENT speaker re-speaks the same members.
//
//   2. FOLD RECEIPT: a pool built one utterance at a time (speak_universe
//      vendor + speak_fact consumer) is THE SAME pool `load_all_proofs::run`
//      builds from a project layout with the vendor staged under
//      `.sugar/imports/` -- same member set, same attribution roles, and
//      `solve` returns identical rows (same properties, same verdicts, same
//      client/vendor fact labels).
//
//   3. ATTRIBUTION IS THE LABEL: with vendor/consumer spoken normally, the
//      contradiction row's `clientFactIr` is the consumer's fact; speak the
//      SAME two envelopes with the roles FLIPPED and the labels flip while
//      every verdict stays identical -- because the solver input is
//      byte-identical and ONLY the attribution map changed. Labels are
//      constructed from attribution, not inferred from position.
//
//   4. VERB DISCRIMINATION: speak_implication refuses an envelope carrying
//      no implication member, atomically (pool untouched).

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use sugar_ir_compiler::registry::Registry as CompilerRegistry;
use sugar_verifier::consistency::ConsistencyResult;
use sugar_verifier::load_all_proofs::{self, ProofBytes};
use sugar_verifier::solvers::registry::build_default_z3;
use sugar_verifier::solvers::{SolverPlan, SolverSeat};
use sugar_verifier::types::{MementoPool, ObligationVerdict, Speaker, SpeakerRole};
use sugar_verifier::utterance::{
    attribution, solve, speak_fact, speak_implication, speak_universe,
};

fn fixture_path(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("implementations/rust")
        .join("sugar-proof-envelope/tests/fixtures")
        .join(name)
}

fn fixture_proof_bytes(name: &str) -> ProofBytes {
    let path = fixture_path(name);
    let bytes =
        std::fs::read(&path).unwrap_or_else(|e| panic!("read fixture {}: {e}", path.display()));
    let cid = sugar_canonicalizer::blake3_512_of(&bytes);
    ProofBytes::try_from_parts(name, cid, bytes).expect("fixture bytes stage into ProofBytes")
}

fn z3_plan_and_registry() -> (
    SolverPlan,
    std::collections::HashMap<SolverSeat, sugar_verifier::solvers::SolverHandle>,
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

/// The comparable projection of a solved row: property, verdict, and the two
/// attribution-derived fact labels (canonical JCS so map ordering never
/// aliases a real difference).
fn row_projection(r: &ConsistencyResult) -> (String, String, Option<String>, Option<String>) {
    let client = r
        .verification
        .as_ref()
        .and_then(|v| v.get("clientFactIr"))
        .map(|v| libsugar::canonical::json_jcs(v).expect("clientFactIr canonicalizes"));
    let vendor = r
        .verification
        .as_ref()
        .and_then(|v| v.get("vendorFactIr"))
        .map(|v| libsugar::canonical::json_jcs(v).expect("vendorFactIr canonicalizes"));
    (
        r.property_name.clone(),
        format!("{:?}", r.verdict),
        client,
        vendor,
    )
}

fn sorted_projections(rows: &[ConsistencyResult]) -> Vec<(String, String, Option<String>, Option<String>)> {
    let mut v: Vec<_> = rows.iter().map(row_projection).collect();
    v.sort();
    v
}

// ---------------------------------------------------------------------
// 1. Idempotent re-speak.
// ---------------------------------------------------------------------

#[test]
fn re_speak_same_envelope_is_a_no_op_receipt() {
    let vendor_proof = fixture_proof_bytes("base64_vendor.proof");
    let vendor = Speaker::vendor("base64-vendor");

    let mut pool = MementoPool::default();
    let first = speak_universe(&mut pool, &vendor, &vendor_proof).expect("first speak succeeds");
    assert!(
        !first.members_spoken.is_empty(),
        "first utterance must attribute members"
    );
    assert!(
        first.members_already_spoken.is_empty(),
        "nothing was spoken before the first utterance"
    );

    let members_after_first = pool.mementos.len();
    let attribution_after_first: BTreeMap<_, _> = attribution(&pool).clone();

    // Re-speak: SAME speaker, SAME envelope.
    let second = speak_universe(&mut pool, &vendor, &vendor_proof).expect("re-speak succeeds");
    assert!(
        second.members_spoken.is_empty(),
        "re-speak must attribute nothing new: {:?}",
        second.members_spoken
    );
    let mut expected_already = first.members_spoken.clone();
    expected_already.sort();
    let mut actual_already = second.members_already_spoken.clone();
    actual_already.sort();
    assert_eq!(
        actual_already, expected_already,
        "re-speak must report exactly the first utterance's members as already spoken"
    );
    assert_eq!(pool.mementos.len(), members_after_first, "no new members");
    assert_eq!(
        attribution(&pool),
        &attribution_after_first,
        "attribution map unchanged by re-speak"
    );

    // Re-speak by a DIFFERENT speaker: first speaker wins, attribution
    // unchanged -- an envelope cannot be re-claimed.
    let impostor = Speaker::consumer("impostor");
    let third = speak_universe(&mut pool, &impostor, &vendor_proof).expect("re-speak succeeds");
    assert!(third.members_spoken.is_empty());
    assert_eq!(
        attribution(&pool),
        &attribution_after_first,
        "a later speaker must NOT steal attribution (first writer wins)"
    );
}

// ---------------------------------------------------------------------
// 2. Fold receipt: spoken pool == disk-layout pool, rows identical.
// ---------------------------------------------------------------------

#[test]
fn spoken_pool_folds_to_the_disk_loaded_pool_with_identical_rows() {
    let vendor_proof = fixture_proof_bytes("base64_vendor.proof");
    let consumer_proof = fixture_proof_bytes("base64_consumer.proof");

    // Disk layout: consumer's own .proof at the project root, vendor staged
    // under .sugar/imports/ -- exactly what `sugar import` produces. File
    // names must be the canonical `blake3-512_<hex>.proof` form.
    let root = std::env::temp_dir().join(format!(
        "sugar-utterance-fold-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&root).expect("mkdir test root");
    let root = root.as_path();
    let imports = root.join(".sugar").join("imports");
    std::fs::create_dir_all(&imports).expect("mkdir imports");
    let disk_name = |p: &ProofBytes| format!("{}.proof", p.expected_cid.to_string().replace(':', "_"));
    std::fs::write(root.join(disk_name(&consumer_proof)), &consumer_proof.bytes).unwrap();
    std::fs::write(imports.join(disk_name(&vendor_proof)), &vendor_proof.bytes).unwrap();
    let disk_pool = load_all_proofs::run(root);
    assert!(
        disk_pool.load_errors.is_empty(),
        "fixture layout must load clean: {:?}",
        disk_pool.load_errors
    );

    // Spoken, one utterance at a time.
    let mut spoken_pool = MementoPool::default();
    speak_universe(
        &mut spoken_pool,
        &Speaker::vendor("base64-vendor"),
        &vendor_proof,
    )
    .expect("vendor universe speaks clean");
    speak_fact(
        &mut spoken_pool,
        &Speaker::consumer("base64-consumer"),
        &consumer_proof,
    )
    .expect("consumer fact speaks clean");

    // Identical member sets.
    let disk_members: Vec<_> = disk_pool.mementos.keys().cloned().collect();
    let spoken_members: Vec<_> = spoken_pool.mementos.keys().cloned().collect();
    assert_eq!(disk_members, spoken_members, "identical pool member sets");

    // Identical attribution ROLES per member (the ids legitimately differ:
    // a path on disk vs a speaker label -- the ROLE is what labeling reads).
    for cid in &disk_members {
        let disk_role = disk_pool.member_speaker(cid).map(|s| s.role);
        let spoken_role = spoken_pool.member_speaker(cid).map(|s| s.role);
        assert_eq!(
            disk_role, spoken_role,
            "member {cid} must carry the same speaker role from both intakes"
        );
    }

    // Identical rows: same properties, same verdicts, same fact labels.
    let (plan, registry) = z3_plan_and_registry();
    let compilers = test_compilers();
    let disk_rows = solve(&disk_pool, &plan, &registry, &compilers, Path::new("."));
    let spoken_rows = solve(&spoken_pool, &plan, &registry, &compilers, Path::new("."));
    assert_eq!(
        sorted_projections(&disk_rows),
        sorted_projections(&spoken_rows),
        "one-at-a-time speaking must fold to the disk-loaded pool's rows"
    );
    let _ = std::fs::remove_dir_all(root);
}

// ---------------------------------------------------------------------
// 3. Attribution IS the label: flip the speakers, labels flip, verdicts
//    do not.
// ---------------------------------------------------------------------

#[test]
fn labels_come_from_attribution_not_position() {
    let vendor_proof = fixture_proof_bytes("base64_vendor.proof");
    let consumer_proof = fixture_proof_bytes("base64_consumer.proof");
    let (plan, registry) = z3_plan_and_registry();
    let compilers = test_compilers();

    let build = |vendor_role_on_vendor_bytes: bool| -> Vec<ConsistencyResult> {
        let mut pool = MementoPool::default();
        let (vendor_speaker, consumer_speaker) = if vendor_role_on_vendor_bytes {
            (Speaker::vendor("the-vendor"), Speaker::consumer("me"))
        } else {
            // FLIPPED: same bytes, opposite roles.
            (Speaker::consumer("the-vendor"), Speaker::vendor("me"))
        };
        speak_universe(&mut pool, &vendor_speaker, &vendor_proof).expect("vendor speaks");
        speak_fact(&mut pool, &consumer_speaker, &consumer_proof).expect("consumer speaks");
        solve(&pool, &plan, &registry, &compilers, Path::new("."))
    };

    let normal = build(true);
    let flipped = build(false);

    // Verdicts identical: attribution never touches the solver input.
    let verdicts = |rows: &[ConsistencyResult]| {
        let mut v: Vec<_> = rows
            .iter()
            .map(|r| (r.property_name.clone(), format!("{:?}", r.verdict)))
            .collect();
        v.sort();
        v
    };
    assert_eq!(
        verdicts(&normal),
        verdicts(&flipped),
        "flipping attribution must not change a single verdict (solver input is byte-identical)"
    );

    // At least one row must carry a client fact label in each direction, and
    // the labels must actually DEPEND on attribution: the set of
    // (property, clientFactIr) pairs differs between normal and flipped.
    let client_labels = |rows: &[ConsistencyResult]| -> Vec<(String, String)> {
        let mut v: Vec<_> = rows
            .iter()
            .filter_map(|r| {
                let client = r.verification.as_ref()?.get("clientFactIr")?;
                Some((
                    r.property_name.clone(),
                    libsugar::canonical::json_jcs(client).expect("canonicalizes"),
                ))
            })
            .collect();
        v.sort();
        v
    };
    let normal_labels = client_labels(&normal);
    let flipped_labels = client_labels(&flipped);
    assert!(
        !normal_labels.is_empty(),
        "the base64 pair must produce at least one labeled row"
    );
    assert_ne!(
        normal_labels, flipped_labels,
        "flipping who spoke which envelope must flip the fact labels -- labels are \
         constructed from attribution, not re-derived from position or source text"
    );

    // And the contradiction itself must be present and REFUSED with labels
    // attached in the normal direction (the pandas-demo shape: your fact vs
    // vendor fact).
    let contradiction = normal.iter().find(|r| {
        r.verdict == ObligationVerdict::Unsatisfied
            && r.verification
                .as_ref()
                .is_some_and(|v| v.get("clientFactIr").is_some() && v.get("vendorFactIr").is_some())
    });
    assert!(
        contradiction.is_some(),
        "vendor+consumer base64 fixtures must yield a refused row carrying BOTH fact labels; rows: {:?}",
        normal
            .iter()
            .map(|r| (r.property_name.clone(), format!("{:?}", r.verdict)))
            .collect::<Vec<_>>()
    );
}

// ---------------------------------------------------------------------
// 4. Verb discrimination: an implication utterance with no implication
//    member refuses, atomically.
// ---------------------------------------------------------------------

#[test]
fn speak_implication_refuses_envelope_without_implication_members() {
    let vendor_proof = fixture_proof_bytes("base64_vendor.proof");
    let mut pool = MementoPool::default();
    let err = speak_implication(&mut pool, &Speaker::vendor("v"), &vendor_proof)
        .expect_err("base64 vendor fixture carries no implication member");
    assert!(
        err.reason.contains("implication"),
        "refusal must name the missing kind: {}",
        err.reason
    );
    assert!(
        pool.mementos.is_empty() && attribution(&pool).is_empty(),
        "a refused utterance must leave the pool untouched (atomic refusal)"
    );

    // The SAME envelope speaks fine through the verb whose shape it carries.
    let ok = speak_fact(&mut pool, &Speaker::vendor("v"), &vendor_proof)
        .expect("fixture carries contract members, so speak_fact accepts it");
    assert!(!ok.members_spoken.is_empty());
    assert!(
        pool.member_speaker(&ok.members_spoken[0])
            .is_some_and(|s| s.role == SpeakerRole::Vendor),
        "accepted utterance stamps the speaker's role"
    );
}

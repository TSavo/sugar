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
//   3. ATTRIBUTION IS THE LABEL: speak the SAME two envelopes with the
//      roles FLIPPED and the set of rows carrying a client-fact label moves
//      wholesale to the other bundle's groups while every verdict stays
//      identical -- because the solver input is byte-identical and ONLY the
//      attribution map changed. Labels are constructed from attribution,
//      not inferred from position. (The contradiction-row labeling receipt
//      lives in consistency.rs's lib tests, where a same-named cross-proof
//      pair can be constructed directly.)
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
use sugar_verifier::types::{MementoPool, Speaker, SpeakerRole};
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
    // The verbs speak an envelope AS their explicit `speaker` argument; the
    // staging speaker below is only the ProofBytes-carried attribution the
    // BULK intake (`load_proof_bytes_into_pool`) would use.
    ProofBytes::try_from_parts(name, cid, bytes, Speaker::consumer(name))
        .expect("fixture bytes stage into ProofBytes")
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
    let vj = r.verification.as_ref().map(|v| v.to_json());
    let client = vj
        .as_ref()
        .and_then(|v| v.get("clientFactIr"))
        .map(|v| libsugar::canonical::json_jcs(v).expect("clientFactIr canonicalizes"));
    let vendor = vj
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
                let vj = r.verification.as_ref()?.to_json();
                let client = vj.get("clientFactIr")?;
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
        !normal_labels.is_empty() && !flipped_labels.is_empty(),
        "each direction must label at least one row (normal: {normal_labels:?}, flipped: {flipped_labels:?})"
    );
    // The two base64 fixtures form DISJOINT #euf# groups (no shared
    // callsite), so every labeled group is spoken entirely by ONE party: a
    // group gets a client-fact label exactly when its speaker holds the
    // Consumer role. Flip the roles and the labeled set must move wholesale
    // to the other bundle's groups -- zero overlap. A positional or
    // source-text heuristic would label the SAME rows in both runs.
    let normal_props: std::collections::BTreeSet<_> =
        normal_labels.iter().map(|(p, _)| p.clone()).collect();
    let flipped_props: std::collections::BTreeSet<_> =
        flipped_labels.iter().map(|(p, _)| p.clone()).collect();
    assert!(
        normal_props.is_disjoint(&flipped_props),
        "flipping who spoke which envelope must flip WHICH rows carry the client fact -- \
         labels are constructed from attribution, not re-derived from position or source \
         text (normal: {normal_props:?}, flipped: {flipped_props:?})"
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

// ---------------------------------------------------------------------
// 5. Positive speak_implication (#3809): sealed Obligation post⊃pre
//    is speakable at parity with fact/universe (CID-idempotent re-speak,
//    first speaker wins).
// ---------------------------------------------------------------------

fn obligation_post_pre() -> (sugar_ir_types::IrFormula, sugar_ir_types::IrFormula) {
    use sugar_ir_types::{IrFormula, IrTerm};
    let post = IrFormula::Atomic {
        name: "caller_post".into(),
        args: vec![IrTerm::Var { name: "r".into() }],
    };
    let pre = IrFormula::Atomic {
        name: "callee_pre".into(),
        args: vec![IrTerm::Var { name: "x".into() }],
    };
    (post, pre)
}

fn implication_proof_bytes() -> ProofBytes {
    let (post, pre) = obligation_post_pre();
    let (_sealed, bytes, cid) = sugar_claim_envelope::spoken_obligation_proof_bytes(&post, &pre);
    ProofBytes::try_from_parts(
        "spoken-obligation.proof",
        cid,
        bytes,
        Speaker::vendor("obligation-speaker"),
    )
    .expect("sealed obligation catalog stages into ProofBytes")
}

#[test]
fn speak_implication_positive_and_re_speak_is_idempotent() {
    let proof = implication_proof_bytes();
    let speaker = Speaker::vendor("obligation-speaker");
    let mut pool = MementoPool::default();

    let first = speak_implication(&mut pool, &speaker, &proof).expect("positive speak succeeds");
    assert_eq!(first.kind, sugar_verifier::utterance::UtteranceKind::Implication);
    assert!(
        !first.members_spoken.is_empty(),
        "first speak must attribute implication members: {:?}",
        first.members_spoken
    );
    assert!(first.members_already_spoken.is_empty());
    let members_after = pool.mementos.len();
    let attribution_after: BTreeMap<_, _> = attribution(&pool).clone();
    assert!(
        pool.member_speaker(&first.members_spoken[0])
            .is_some_and(|s| s.role == SpeakerRole::Vendor),
        "first speaker role stamped"
    );

    // Re-speak: same speaker, same sealed edge → no-op.
    let second = speak_implication(&mut pool, &speaker, &proof).expect("re-speak succeeds");
    assert!(
        second.members_spoken.is_empty(),
        "re-speak attributes nothing new: {:?}",
        second.members_spoken
    );
    let mut expected_already = first.members_spoken.clone();
    expected_already.sort();
    let mut actual_already = second.members_already_spoken.clone();
    actual_already.sort();
    assert_eq!(actual_already, expected_already);
    assert_eq!(pool.mementos.len(), members_after);
    assert_eq!(
        attribution(&pool),
        &attribution_after,
        "attribution unchanged by re-speak"
    );

    // First speaker wins against an impostor.
    let impostor = Speaker::consumer("impostor");
    let third = speak_implication(&mut pool, &impostor, &proof).expect("impostor re-speak ok");
    assert!(third.members_spoken.is_empty());
    assert_eq!(
        attribution(&pool),
        &attribution_after,
        "later speaker must not steal attribution"
    );
}

#[test]
fn seal_same_obligation_twice_same_implication_member_in_pool() {
    // Two independently sealed catalogs of the same post⊃pre edge speak as
    // ONE memento (same member CID) — the seal is a pure function.
    let (post, pre) = obligation_post_pre();
    let (s1, b1, c1) = sugar_claim_envelope::spoken_obligation_proof_bytes(&post, &pre);
    let (s2, b2, c2) = sugar_claim_envelope::spoken_obligation_proof_bytes(&post, &pre);
    assert_eq!(s1.cid, s2.cid, "member seal CID pure");
    assert_eq!(c1, c2, "catalog CID pure under fixed seal identity");
    assert_eq!(b1, b2, "catalog bytes pure");

    let p1 = ProofBytes::try_from_parts("o1.proof", c1, b1, Speaker::vendor("a"))
        .expect("stage");
    let p2 = ProofBytes::try_from_parts("o2.proof", c2, b2, Speaker::vendor("b"))
        .expect("stage");
    let mut pool = MementoPool::default();
    let first = speak_implication(&mut pool, &Speaker::vendor("a"), &p1).unwrap();
    let second = speak_implication(&mut pool, &Speaker::vendor("b"), &p2).unwrap();
    assert!(!first.members_spoken.is_empty());
    assert!(
        second.members_spoken.is_empty(),
        "second speak of same edge CID is already-spoken"
    );
    assert_eq!(
        pool.mementos.len(),
        first.members_spoken.len(),
        "one edge → one pool member"
    );
}

// ---------------------------------------------------------------------
// #3813 (finding 3): a refusal whose scratch decode raised load errors
// RECORDS those errors into `pool.load_errors` (the durable log every other
// intake keeps), while still adding NO member or attribution. The
// `SpeakReceipt`/`UtteranceRefusal` docs promise exactly this.
// ---------------------------------------------------------------------

#[test]
fn refusal_records_decode_load_errors_in_the_pool() {
    // Valid-FORMAT expected CID that deliberately does NOT match the bytes,
    // so `load_catalog_bytes` trips rule 1 (trust root) -> the scratch decodes
    // to zero members with a load error -> `speak_universe` refuses.
    let bytes = b"not a proof catalog".to_vec();
    let wrong_cid = sugar_canonicalizer::blake3_512_of(b"some other content");
    let proof = ProofBytes::try_from_parts(
        "mismatched.proof",
        wrong_cid,
        bytes,
        Speaker::vendor("v"),
    )
    .expect("valid CID format stages into ProofBytes");

    let mut pool = MementoPool::default();
    let refusal = speak_universe(&mut pool, &Speaker::vendor("v"), &proof)
        .expect_err("a byte/CID mismatch decodes to zero members and refuses");

    assert!(
        !refusal.load_errors.is_empty(),
        "the refusal must carry the decode error"
    );
    // The soundness-relevant half of atomicity: no member, no attribution.
    assert!(
        pool.mementos.is_empty() && attribution(&pool).is_empty(),
        "refusal adds no member or attribution"
    );
    // The diagnostic half: the pool now records the decode error, matching the
    // success path's `merge` and every other intake.
    assert_eq!(
        pool.load_errors.len(),
        refusal.load_errors.len(),
        "pool must record the same decode errors the refusal reported"
    );
    assert!(
        pool.load_errors
            .iter()
            .any(|e| e.reason.contains("trust root")),
        "recorded error should be the rule-1 trust-root mismatch: {:#?}",
        pool.load_errors
    );
}

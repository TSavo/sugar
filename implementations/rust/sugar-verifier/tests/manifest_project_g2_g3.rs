// SPDX-License-Identifier: MIT OR Apache-2.0
//
// join-manifest design, lane 2 (PROJECTION + G2/G3).
//
// G2: the manifest-projected conjunct CID set for every `#euf#` name must be
// EXACTLY the scan-path conjunct CID set for that name -- not verdict
// equality, SET equality (the design brief's own wording). Driven over the
// real base64 vendor/consumer fixtures (individually and combined into one
// pool -- the cross-proof case), plus the pandas demo pair (path-gated), plus
// a synthetic same-name cross-proof case exercising the union-by-name merge
// directly, plus a bad-twin dropped-CID mutation that must fail loudly (the
// projected set must visibly UNDER-COVER the scan set, not silently match).
//
// G3: re-minting the vendor (simulated here by staling one manifest group's
// `contributorBundle` so it no longer matches the bundle it is loaded under)
// forces `ConsistencyMode::PoolScanFallback` with a named
// `VendorBundleMismatch` reason, and the resulting verdicts are identical to
// a fresh `verify_consistency` scan over the same pool.
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use sugar_ir_compiler::registry::Registry as CompilerRegistry;
use sugar_proof_envelope::manifest::{EufGroup, Manifest};
use sugar_verifier::consistency::{
    build_manifest_from_pool, projected_conjunct_cids_by_name, scan_conjunct_cids_by_name,
    verify_consistency, verify_consistency_projected, ConsistencyMode, ProjectionFallbackReason,
};
use sugar_verifier::load_all_proofs::{load_proof_bytes_into_pool, ProofBytes};
use sugar_verifier::solvers::registry::build_default_z3;
use sugar_verifier::solvers::{SolverPlan, SolverSeat};
use sugar_verifier::types::MementoPool;

fn fixture_path(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("implementations/rust")
        .join("sugar-proof-envelope/tests/fixtures")
        .join(name)
}

fn fixture_bytes(name: &str) -> Vec<u8> {
    let path = fixture_path(name);
    std::fs::read(&path).unwrap_or_else(|e| panic!("read fixture {}: {e}", path.display()))
}

fn z3_plan_and_registry() -> (SolverPlan, std::collections::HashMap<SolverSeat, sugar_verifier::solvers::SolverHandle>) {
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

/// Load one `.proof` fixture's bytes into its own single-bundle pool, keyed
/// under its own content-hash CID (the same rule `load_all_proofs` uses for
/// `bundle_members`), and return `(bundle_cid, pool)`.
fn load_single_bundle(bytes: &[u8]) -> (String, MementoPool) {
    let bundle_cid = sugar_canonicalizer::blake3_512_of(bytes);
    let mut pool = MementoPool::default();
    let proof_bytes = ProofBytes::try_from_parts("fixture", bundle_cid.clone(), bytes.to_vec())
        .expect("fixture bytes stage into ProofBytes");
    load_proof_bytes_into_pool(&[proof_bytes], &mut pool);
    (bundle_cid, pool)
}

/// Load several fixtures' bytes together into ONE combined pool -- the
/// cross-proof scenario -- and return `(bundle_cid -> per-bundle manifest,
/// combined_pool)`.
fn load_combined(fixtures: &[Vec<u8>]) -> (BTreeMap<String, Manifest>, MementoPool) {
    let mut combined = MementoPool::default();
    let mut proofs = Vec::new();
    let mut bundle_cids = Vec::new();
    for bytes in fixtures {
        let bundle_cid = sugar_canonicalizer::blake3_512_of(bytes);
        proofs.push(
            ProofBytes::try_from_parts("fixture", bundle_cid.clone(), bytes.clone())
                .expect("fixture bytes stage into ProofBytes"),
        );
        bundle_cids.push(bundle_cid);
    }
    load_proof_bytes_into_pool(&proofs, &mut combined);

    // Each bundle's manifest is sealed from ITS OWN bytes alone (exactly
    // what seal-time does), so build it from a single-bundle pool, not the
    // combined one.
    let mut manifests = BTreeMap::new();
    for (bytes, bundle_cid) in fixtures.iter().zip(bundle_cids.iter()) {
        let (_own_cid, own_pool) = load_single_bundle(bytes);
        let manifest = build_manifest_from_pool(&own_pool, bundle_cid);
        manifests.insert(bundle_cid.clone(), manifest);
    }
    (manifests, combined)
}

// ---------------------------------------------------------------------
// G2: conjunct-set differential, per real fixture.
// ---------------------------------------------------------------------

fn g2_single_fixture(fixture: &str) {
    let bytes = fixture_bytes(fixture);
    let (bundle_cid, pool) = load_single_bundle(&bytes);
    let manifest = build_manifest_from_pool(&pool, &bundle_cid);
    let mut manifests = BTreeMap::new();
    manifests.insert(bundle_cid, manifest);

    let scan = scan_conjunct_cids_by_name(&pool);
    let projected = projected_conjunct_cids_by_name(&manifests);
    assert_eq!(
        scan, projected,
        "{fixture}: scan-path vs manifest-path conjunct CID sets must be identical, per name"
    );
}

#[test]
fn g2_conjunct_sets_identical_on_real_vendor_fixture() {
    g2_single_fixture("base64_vendor.proof");
}

#[test]
fn g2_conjunct_sets_identical_on_real_consumer_fixture() {
    g2_single_fixture("base64_consumer.proof");
}

#[test]
fn g2_conjunct_sets_identical_on_combined_vendor_and_consumer_pool() {
    // The CROSS-PROOF case: both fixtures loaded into ONE pool, each
    // contributing its own manifest, projected sets merged by name (design
    // item 3) and compared against a whole-pool scan over the same combined
    // pool -- every callsite, not just names unique to one proof.
    let vendor = fixture_bytes("base64_vendor.proof");
    let consumer = fixture_bytes("base64_consumer.proof");
    let (manifests, combined_pool) = load_combined(&[vendor, consumer]);

    let scan = scan_conjunct_cids_by_name(&combined_pool);
    let projected = projected_conjunct_cids_by_name(&manifests);
    assert_eq!(
        scan, projected,
        "combined vendor+consumer pool: scan-path vs manifest-path conjunct CID sets must be identical"
    );
}

#[test]
fn g2_conjunct_sets_identical_on_pandas_demo_proof_pair_path_gated() {
    // Path-gated per the design brief: only runs if the pandas demo checkout
    // is present. Loads every real `.proof` file in the directory into one
    // combined pool (the cross-proof case at full scale) and compares.
    let dir = Path::new("/Users/tsavo/sugar-pandas-demo/consumer-bad");
    let Ok(entries) = std::fs::read_dir(dir) else {
        eprintln!("pandas demo path absent ({}), skipping", dir.display());
        return;
    };
    let mut fixtures = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("proof") {
            continue;
        }
        fixtures.push(std::fs::read(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display())));
    }
    if fixtures.is_empty() {
        panic!("pandas demo directory present but contained no .proof files");
    }
    let (manifests, combined_pool) = load_combined(&fixtures);
    let scan = scan_conjunct_cids_by_name(&combined_pool);
    let projected = projected_conjunct_cids_by_name(&manifests);
    assert_eq!(
        scan, projected,
        "pandas demo consumer-bad pool: scan-path vs manifest-path conjunct CID sets must be identical"
    );
}

/// Synthetic SAME-NAME cross-proof merge (design item 3, and the "include
/// the same-name cross-proof fixture (consistency.rs:2738)" instruction): two
/// manifests, from two DIFFERENT (synthetic) bundles, both declaring a group
/// under the identical `#euf#` name with disjoint member CIDs. The merged
/// projection must union them -- exactly the case a re-minted-with-new-CIDs
/// vendor plus a stale-but-same-named consumer group must still merge on.
/// This does not touch a real `MementoPool` (no scan-side comparison is
/// meaningful for synthetic CIDs that resolve to no real member), so it is
/// a standalone unit check of the merge arithmetic in
/// `projected_conjunct_cids_by_name`, additional to (not a replacement for)
/// the real-fixture differentials above.
#[test]
fn g2_same_name_cross_proof_manifests_merge_by_union() {
    let name = "np.add#euf#(2,3)::assertion".to_string();

    let mut vendor_manifest = Manifest::new();
    vendor_manifest.groups.insert(
        name.clone(),
        EufGroup {
            member_cids: std::collections::BTreeSet::from(["blake3-512:aa".repeat(1).to_string()
                .chars()
                .cycle()
                .take(128)
                .collect::<String>()])
                .into_iter()
                .map(|_| "blake3-512:".to_string() + &"a".repeat(128))
                .collect(),
            contributor_bundle: "blake3-512:".to_string() + &"1".repeat(128),
        },
    );

    let mut consumer_manifest = Manifest::new();
    consumer_manifest.groups.insert(
        name.clone(),
        EufGroup {
            member_cids: std::collections::BTreeSet::from([
                "blake3-512:".to_string() + &"b".repeat(128),
            ]),
            contributor_bundle: "blake3-512:".to_string() + &"2".repeat(128),
        },
    );

    let mut manifests = BTreeMap::new();
    manifests.insert("bundle-vendor".to_string(), vendor_manifest);
    manifests.insert("bundle-consumer".to_string(), consumer_manifest);

    let merged = projected_conjunct_cids_by_name(&manifests);
    let group = merged.get(&name).expect("merged group present");
    assert_eq!(
        group.len(),
        2,
        "same-name groups from two different proofs must UNION their member CIDs, not overwrite"
    );
    assert!(group.contains(&("blake3-512:".to_string() + &"a".repeat(128))));
    assert!(group.contains(&("blake3-512:".to_string() + &"b".repeat(128))));
}

#[test]
fn g2_bad_twin_dropped_cid_fails_loudly() {
    // A manifest that is MISSING one member CID a real scan would have found
    // must NOT silently produce an equal projected set -- this is the "false
    // PROVEN" failure mode design item 2 warns about: an under-conjoined
    // group can pass a check that would have refused it.
    let bytes = fixture_bytes("base64_vendor.proof");
    let (bundle_cid, pool) = load_single_bundle(&bytes);
    let mut manifest = build_manifest_from_pool(&pool, &bundle_cid);

    let scan = scan_conjunct_cids_by_name(&pool);
    let Some((dropped_name, cids)) = scan.iter().find(|(_, cids)| !cids.is_empty()) else {
        eprintln!("fixture has no non-empty #euf# group to mutate, skipping bad-twin check");
        return;
    };
    let dropped_name = dropped_name.clone();
    let dropped_cid = cids.iter().next().cloned().expect("non-empty checked above");

    let group = manifest
        .groups
        .get_mut(&dropped_name)
        .unwrap_or_else(|| panic!("manifest must carry the group scan found: {dropped_name}"));
    let removed = group.member_cids.remove(&dropped_cid);
    assert!(removed, "the CID must have been present before the drop");

    let mut manifests = BTreeMap::new();
    manifests.insert(bundle_cid, manifest);
    let projected = projected_conjunct_cids_by_name(&manifests);

    assert_ne!(
        scan, projected,
        "a manifest with a dropped CID must NOT silently equal the scan-path set"
    );
    let projected_group = projected
        .get(&dropped_name)
        .expect("group still present, just missing one member");
    assert!(
        !projected_group.contains(&dropped_cid),
        "the dropped CID must be visibly absent from the projected set (loud, not silent)"
    );
    assert!(
        projected_group.is_subset(cids) && projected_group.len() < cids.len(),
        "the mutated group must strictly UNDER-cover the true scan-path set"
    );
}

// ---------------------------------------------------------------------
// G3: vendor re-mint edge.
// ---------------------------------------------------------------------

#[test]
fn g3_stale_vendor_bundle_forces_fallback_with_identical_verdicts() {
    let bytes = fixture_bytes("base64_vendor.proof");
    let (bundle_cid, pool) = load_single_bundle(&bytes);
    let manifest = build_manifest_from_pool(&pool, &bundle_cid);

    let (plan, registry) = z3_plan_and_registry();
    let compilers = test_compilers();
    let project_root = Path::new(".");

    // Baseline: a fresh scan over the (unmodified) pool.
    let fresh_scan = verify_consistency(&pool, &plan, &registry, &compilers, project_root);

    // Honest manifest (contributorBundle correctly names this bundle):
    // projection must succeed with NO forced fallback (when the fixture
    // carries at least one #euf# group -- if it carries none, fallback
    // reasons stay empty vacuously and both paths agree trivially).
    let mut manifests = BTreeMap::new();
    manifests.insert(bundle_cid.clone(), manifest.clone());
    let (honest_results, honest_mode, honest_reasons) =
        verify_consistency_projected(&pool, &manifests, &plan, &registry, &compilers, project_root);
    assert!(
        honest_reasons.is_empty(),
        "an honest, current manifest must not trip any forced-fallback reason: {honest_reasons:?}"
    );
    assert_eq!(honest_mode, ConsistencyMode::ManifestProjected);
    assert_verdicts_match(&fresh_scan, &honest_results);

    // Simulate a RE-MINT: the vendor bundle got re-minted since the consumer
    // last staged its manifest, so every group's `contributorBundle` now
    // names a CID that no longer matches this pool's actual bundle_cid.
    let mut staled = manifest;
    for group in staled.groups.values_mut() {
        group.contributor_bundle = "blake3-512:".to_string() + &"9".repeat(128);
    }
    let mut staled_manifests = BTreeMap::new();
    staled_manifests.insert(bundle_cid.clone(), staled);

    let (staled_results, staled_mode, staled_reasons) = verify_consistency_projected(
        &pool,
        &staled_manifests,
        &plan,
        &registry,
        &compilers,
        project_root,
    );

    assert_eq!(
        staled_mode,
        ConsistencyMode::PoolScanFallback,
        "a stale contributorBundle must force PoolScanFallback, never a silent projection"
    );
    assert!(
        staled_reasons
            .iter()
            .any(|r| matches!(r, ProjectionFallbackReason::VendorBundleMismatch { .. })),
        "the forced fallback must be NAMED as a vendor-bundle mismatch, not generic: {staled_reasons:?}"
    );
    assert_verdicts_match(&fresh_scan, &staled_results);
}

#[test]
fn g3_missing_manifest_forces_fallback() {
    let bytes = fixture_bytes("base64_consumer.proof");
    let (_bundle_cid, pool) = load_single_bundle(&bytes);
    let (plan, registry) = z3_plan_and_registry();
    let compilers = test_compilers();
    let project_root = Path::new(".");

    let fresh_scan = verify_consistency(&pool, &plan, &registry, &compilers, project_root);

    // No manifest staged at all for this pool's bundle.
    let manifests: BTreeMap<String, Manifest> = BTreeMap::new();
    let (results, mode, reasons) =
        verify_consistency_projected(&pool, &manifests, &plan, &registry, &compilers, project_root);

    assert_eq!(mode, ConsistencyMode::PoolScanFallback);
    assert!(
        reasons
            .iter()
            .any(|r| matches!(r, ProjectionFallbackReason::ManifestMissing { .. })),
        "a bundle with no staged manifest must force fallback, named ManifestMissing: {reasons:?}"
    );
    assert_verdicts_match(&fresh_scan, &results);
}

#[test]
fn g3_corrupted_manifest_fails_integrity_check() {
    // A manifest whose stored contents no longer recompute to its own claim
    // (simulated corruption, distinct from a byte-flip on the wire -- that is
    // G4's job in lane 1) must trip IntegrityMismatch, not be trusted.
    let bytes = fixture_bytes("base64_vendor.proof");
    let (bundle_cid, pool) = load_single_bundle(&bytes);
    let mut manifest = build_manifest_from_pool(&pool, &bundle_cid);
    // Corrupt: inject a group for a name this bundle's pool never produced
    // via the scan filter, so re-deriving the manifest from the pool cannot
    // reproduce it.
    manifest.groups.insert(
        "totally-fabricated#euf#(9,9)::assertion".to_string(),
        EufGroup {
            member_cids: std::collections::BTreeSet::from([
                "blake3-512:".to_string() + &"f".repeat(128),
            ]),
            contributor_bundle: bundle_cid.clone(),
        },
    );

    let (plan, registry) = z3_plan_and_registry();
    let compilers = test_compilers();
    let project_root = Path::new(".");
    let fresh_scan = verify_consistency(&pool, &plan, &registry, &compilers, project_root);

    let mut manifests = BTreeMap::new();
    manifests.insert(bundle_cid, manifest);
    let (results, mode, reasons) =
        verify_consistency_projected(&pool, &manifests, &plan, &registry, &compilers, project_root);

    assert_eq!(mode, ConsistencyMode::PoolScanFallback);
    assert!(
        reasons
            .iter()
            .any(|r| matches!(r, ProjectionFallbackReason::IntegrityMismatch { .. })),
        "a manifest that does not recompute to itself must trip IntegrityMismatch: {reasons:?}"
    );
    assert_verdicts_match(&fresh_scan, &results);
}

/// BONUS RECEIPT (not a gate): wall-time for a full scan pass vs a full
/// projected pass over the pandas demo consumer-bad pool, printed to stderr.
/// Path-gated like the G2 pandas test above; a no-op when the demo checkout
/// is absent. Projection's win here is real but partial in this lane: it
/// still solves every group with the SAME solver calls
/// (`process_consistency_group` is shared code, by design, for classification
/// parity) -- what it saves is the O(pool) is_consistency_candidate scan
/// `collect_consistency_candidates` performs over every member in the pool to
/// find each group's members, replaced by an O(1) manifest lookup per name.
#[test]
fn bonus_pandas_wall_time_scan_vs_projected_path_gated() {
    let dir = Path::new("/Users/tsavo/sugar-pandas-demo/consumer-bad");
    let Ok(entries) = std::fs::read_dir(dir) else {
        eprintln!("pandas demo path absent ({}), skipping bonus timing", dir.display());
        return;
    };
    let mut fixtures = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("proof") {
            continue;
        }
        fixtures.push(std::fs::read(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display())));
    }
    if fixtures.is_empty() {
        eprintln!("pandas demo directory present but no .proof files, skipping bonus timing");
        return;
    }
    let (manifests, combined_pool) = load_combined(&fixtures);
    let (plan, registry) = z3_plan_and_registry();
    let compilers = test_compilers();
    let project_root = Path::new(".");

    let t0 = std::time::Instant::now();
    let scan_results = verify_consistency(&combined_pool, &plan, &registry, &compilers, project_root);
    let scan_elapsed = t0.elapsed();

    let t1 = std::time::Instant::now();
    let (projected_results, mode, reasons) = verify_consistency_projected(
        &combined_pool,
        &manifests,
        &plan,
        &registry,
        &compilers,
        project_root,
    );
    let projected_elapsed = t1.elapsed();

    eprintln!(
        "pandas consumer-bad: scan={:?} ({} rows), projected={:?} ({} rows, mode={:?}, fallback_reasons={})",
        scan_elapsed,
        scan_results.len(),
        projected_elapsed,
        projected_results.len(),
        mode,
        reasons.len(),
    );
}

fn assert_verdicts_match(
    a: &[sugar_verifier::consistency::ConsistencyResult],
    b: &[sugar_verifier::consistency::ConsistencyResult],
) {
    let mut a_sorted: Vec<(&str, String)> = a
        .iter()
        .map(|r| (r.property_name.as_str(), format!("{:?}", r.verdict)))
        .collect();
    let mut b_sorted: Vec<(&str, String)> = b
        .iter()
        .map(|r| (r.property_name.as_str(), format!("{:?}", r.verdict)))
        .collect();
    a_sorted.sort();
    b_sorted.sort();
    assert_eq!(
        a_sorted, b_sorted,
        "fallback/projection paths must reach the SAME verdicts as a fresh scan"
    );
}

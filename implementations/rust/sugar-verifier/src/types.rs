// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Verifier-owned obligation and report types. Content-addressed memento
// storage lives at the proof-envelope dependency floor and is re-exported
// here for source compatibility with verifier consumers.

use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::Value as Json;

pub use sugar_proof_envelope::{
    compute_formula_cid, AnchoredMember, AtomCid, BundleScopedCallsiteKey, ContractBodyCid,
    EffectSiteAnnotation, ImplicationKey, ImplicationResult, LoadError, MemberKind, MementoCid,
    MementoPool, ResolvedContractBody, SourceLine, SourcePath, SourceSymbol, Speaker, SpeakerRole,
    StoredMember, VerifiedContract,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BridgePin {
    /// The bridge target must be a co-member of the bridge's own bundle.
    SelfPinned,
    /// The bridge target must be a member of the named external proof bundle.
    Cross(MementoCid),
}

impl Default for BridgePin {
    fn default() -> Self {
        Self::SelfPinned
    }
}

impl BridgePin {
    pub fn from_target_proof_cid(cid: Option<MementoCid>) -> Self {
        match cid {
            Some(cid) => Self::Cross(cid),
            None => Self::SelfPinned,
        }
    }

    pub fn from_target_proof_value(value: Option<&Json>) -> Result<Self, String> {
        let Some(value) = value else {
            return Ok(Self::SelfPinned);
        };
        if value.is_null() {
            return Ok(Self::SelfPinned);
        }
        let raw = value
            .as_str()
            .ok_or_else(|| "bridge target proof CID must be a CID string or null".to_string())?;
        if raw.is_empty() {
            return Err("bridge target proof CID must not be empty".to_string());
        }
        MementoCid::try_parse(raw.to_string())
            .map(Self::Cross)
            .map_err(|raw| format!("bridge target proof CID has invalid CID format: `{raw}`"))
    }

    pub fn target_proof_cid(&self) -> Option<&MementoCid> {
        match self {
            Self::Cross(cid) => Some(cid),
            Self::SelfPinned => None,
        }
    }
}

impl Serialize for BridgePin {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match self {
            Self::SelfPinned => serializer.serialize_none(),
            Self::Cross(cid) => serializer.serialize_some(cid),
        }
    }
}

impl<'de> Deserialize<'de> for BridgePin {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let raw = Option::<String>::deserialize(deserializer)?;
        match raw {
            None => Ok(Self::SelfPinned),
            Some(raw) if raw.is_empty() => Err(serde::de::Error::custom(
                "bridge target proof CID must not be empty",
            )),
            Some(raw) => MementoCid::try_parse(raw).map(Self::Cross).map_err(|raw| {
                serde::de::Error::custom(format!(
                    "bridge target proof CID has invalid CID format: `{raw}`"
                ))
            }),
        }
    }
}

/// The source locus of a lifted assertion, recovered from the contract
/// memento's own `file` + `span` fields. Threaded through the consistency
/// verdict so an `unsatisfied` row says WHERE the offending assertion is,
/// letting the IDE anchor a red squiggle at the exact line/column instead of
/// dropping the source the way a directory-prove otherwise does (#3462 family).
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct SourceLocus {
    pub file: String,
    pub line: usize,
    pub column: Option<usize>,
}

#[derive(Debug, Default, Clone)]
pub struct CallSite {
    pub bridge_ir_name: String,
    pub bridge_target_cid: Option<MementoCid>,
    pub bridge_source_layer: String,
    pub bridge_target_layer: String,
    /// Forward pin: either a specific `.proof` bundle CID this bridge commits
    /// to as its consequent (CROSS-bundle target) or an explicit self-pin whose
    /// target contract must be a co-member of the bridge's own bundle (see
    /// `bridge_self_bundle_cid`). Either way the pin is enforced; there is no
    /// unpinned path. See
    /// `protocol/specs/2026-04-30-ir-formal-grammar.md`
    /// § "Bridge target pinning: the shim-poisoning vector".
    pub bridge_pin: BridgePin,
    /// The `.proof` bundle CID the bridge memento itself was loaded from.
    /// Used to enforce the self-pinned (`bridge_pin == BridgePin::SelfPinned`)
    /// case: the target contract must be a co-member of this same bundle.
    /// `None` only if the bridge memento was not associated with any bundle
    /// (a hand-built in-memory pool); resolve_target then cannot self-pin.
    pub bridge_self_bundle_cid: Option<MementoCid>,
    pub property_name: String,
    pub property_cid: Option<MementoCid>,
    /// The `.proof` bundle CID containing the property/contract whose body
    /// produced this callsite. For panic-site producer lookup, co-located
    /// receiver bridges are minted in this same caller bundle; this is distinct
    /// from the selected bridge memento's own bundle, which can be polluted by
    /// a global per-symbol bridge index when target and import proofs are
    /// loaded together.
    pub callsite_bundle_cid: Option<MementoCid>,
    pub arg_term: Option<Json>,
    /// All actual argument terms on the bridged call, in source order. The
    /// legacy `arg_term` remains the first actual for producer-post and
    /// panic-site paths that intentionally operate on a single receiver/value.
    /// Multi-formal precondition discharge uses this vector to specialize a
    /// target pre over every formal without interpreting the language.
    pub arg_terms: Vec<Json>,
    /// Optional kit-provided binding from target formal name to the callsite
    /// actual term that denotes it. This is opaque verifier data: the language
    /// kit owns receiver/argument alignment; the verifier substitutes by these
    /// names and fails closed when a required binding is absent.
    pub formal_actuals: Option<Json>,
    /// Optional kit-provided producer provenance for panic-site receiver calls.
    /// For `producer().expect(..)`, the panic leaf and the producer call can
    /// start on different source lines. The verifier treats these as opaque
    /// coordinates into `bridges_by_callsite`; the language kit owns how they
    /// were derived.
    pub producer_file: Option<String>,
    pub producer_line: Option<usize>,
    pub producer_symbol: Option<String>,
    /// The atomic predicate the matched call ctor sits directly inside, if
    /// the call was found as an argument of an atomic (e.g. the `=` in a
    /// harvested `assert_eq!(double(3), 6)` -> `=(double(3), 6)`). Captured
    /// so the body-discharge path can derive the postcondition `Q` (the
    /// atomic with the call replaced by `result`). `None` when the call was
    /// not directly under an atomic. Does not participate in any CID.
    pub containing_atomic: Option<Json>,
    /// PANIC-FREEDOM guard context: the path conditions (as atomic-predicate
    /// formulas) that DOMINATE this call site in the lifted caller body. The
    /// dominating fact is RESOLVED BY THE RUST KIT, not by this verifier: the
    /// lifter wraps a guarded branch in `cf_guarded(<resolved-predicate>,
    /// value)` (then-branch -> positive predicate, else-branch -> the kit's
    /// complement), and `enumerate_callsites` copies that opaque atom into this
    /// vector verbatim, recognizing no Rust predicate name. The discharge of a
    /// panic partial's `pre` is performed UNDER these facts: a site dominated by
    /// the matching guard discharges panic-safe (`guard => pre` is valid), an
    /// unwrapped site keeps an empty guard set so the bare `pre` is unprovable
    /// -> honest undecidable. Fail-safe by construction: a missing wrapper can
    /// only UNDER-prove (K too low), never mark an unguarded site safe. Does not
    /// participate in any CID.
    pub guard_facts: Vec<Json>,
    /// Opaque kit-provided source file for observability. The verifier does
    /// not interpret this path, it only carries it into reports.
    pub file: Option<String>,
    /// Opaque kit-provided source line for observability.
    pub line: Option<usize>,
    /// Opaque kit-provided source column (0-based) for observability. Carried
    /// alongside `file`/`line` so a consistency verdict can anchor an IDE
    /// diagnostic at the exact assertion, not merely the file/line.
    pub source_column: Option<usize>,
    /// Opaque kit-provided callee label for observability.
    pub callee: Option<String>,
    /// True when the kit classified this callsite as panic-relevant. The
    /// verifier and CLI do not derive this from language semantics.
    pub panic_site: bool,
    /// Python attribute-access safety obligation metadata. Present only when
    /// the Python source lifter knows the receiver's class at the access site.
    /// The verifier discharges it from signed `classShapes` evidence or from a
    /// dominating `attribute_present(receiver, attr)` guard; no other panic
    /// path reads it.
    pub attribute_safety: Option<AttributeSafetyObligation>,
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct AttributeSafetyObligation {
    pub receiver_class: Option<String>,
    pub receiver_qualname: Option<String>,
    pub receiver_name: Option<String>,
    pub attribute: String,
}

#[derive(Debug, Default, Clone)]
pub struct ResolvedProperty {
    pub cid: String,
    pub ir_formula: Option<Json>,
    pub ir_kit_version: String,
    /// Target contract formal names and sorts, copied from the contract header
    /// when present. These are identity slots for callsite substitution only;
    /// the verifier does not interpret source-language types.
    pub formal_names: Vec<String>,
    pub formal_sorts: Vec<Json>,
    /// True iff the resolved target contract is a body-derived op-contract
    /// (body-bearing), not a plain refinement target.
    ///
    /// The canonical marker is a non-empty `formals` array on the contract
    /// body: that is what `core::bind::bind_function_bridge` mints and what
    /// body-bearing test fixtures construct. If a future contract shape
    /// carries body markers under a different field, it MUST be recognized
    /// here (`resolve_target::run` is the single setter) so the honesty
    /// boundary stays complete.
    ///
    /// A body-bearing target whose obligation cannot be reduced and
    /// discharged MUST be refused, never vacuous-passed -- the "no
    /// precondition => vacuously true" shortcut is only legitimate for
    /// genuinely non-body-bearing claims. Both consumers enforce this before
    /// their vacuous-discharge branch: `cmd_verify::verify_one_claim` and
    /// `runner::work_one`.
    pub target_is_body_bearing: bool,
    /// True iff the resolved target contract carries a `post` field in its
    /// body. A post-only contract with a `post` (e.g. `eq(out, "AAAA")`) is
    /// making an obligation claim about its output — it is NOT vacuously
    /// dischargeable just because it has no `pre`. The vacuous discharge is
    /// only legitimate for targets that are truly claim-free (no pre, no post,
    /// or carry only a totality marker already verified via `postHash`).
    /// `runner::work_one` checks this before the vacuous-discharge branch.
    pub target_has_post: bool,
}

#[derive(Debug, Clone)]
pub struct Obligation {
    pub property_cid: String,
    pub ir_kit_version: String,
    pub ir_formula: Json,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ObligationVerdict {
    Discharged,
    Unsatisfied,
    Undecidable,
    /// The solver did not return a verdict before the configured host timeout.
    /// This is not a logical `undecidable`: it is a statement about the host /
    /// budget that ran the solver. Keep it distinct so load cannot masquerade as
    /// a formula fact.
    SolverTimeout,
    Disagreement,
    /// First-class, loudly-bounded REFUSAL: there is no sound discharger for this
    /// obligation (e.g. its precondition lowers to a construct the solver cannot
    /// interpret -- z3 "unknown constant"). NOT a violation, NOT an undecidable
    /// gap, NOT a crash: an honest "I decline to decide this, here is why." The
    /// trichotomy's third arm (exact / loudly-bounded-lossy / REFUSE), so it does
    /// not redden the gate -- a refusal is an expected, named outcome.
    Refused,
}

impl ObligationVerdict {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Discharged => "discharged",
            Self::Unsatisfied => "unsatisfied",
            Self::Undecidable => "undecidable",
            Self::SolverTimeout => "solver-timeout",
            Self::Disagreement => "disagreement",
            Self::Refused => "refused",
        }
    }
}

#[derive(Debug, Clone)]
pub struct ReportRow {
    pub callsite: CallSite,
    pub status: ObligationVerdict,
    pub reason: String,
    pub discharge_method: Option<String>,
    pub body_discharge_tier: Option<String>,
    pub verification: Option<Json>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ResolvedCallEdge {
    pub source_contract_cid: String,
    pub target_contract_cid: String,
    pub file: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ToolchainPlanReport {
    pub plan_memento_cid: String,
    pub plan_cid: String,
    pub status: String,
    pub reason: String,
    pub expected_output_cids: Vec<String>,
    pub witness_memento_cid: Option<String>,
    pub actual_output_cids: Vec<String>,
}

#[derive(Debug, Default, Clone)]
pub struct Report {
    pub total_callsites: usize,
    pub discharged: usize,
    pub violations: usize,
    /// Obligations honestly REFUSED (no sound discharger): not discharged (no
    /// false pass), not a violation (does not redden the gate). The trichotomy's
    /// third arm, surfaced in the scoreboard so refusals are loud, not hidden.
    pub refused: usize,
    pub rows: Vec<ReportRow>,
    pub load_errors: Vec<LoadError>,
    pub call_edges: Vec<ResolvedCallEdge>,
    pub toolchain_plans: Vec<ToolchainPlanReport>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use libsugar::compose::OpacityMementoLookup;
    use serde_json::json;

    fn cid(seed: &str) -> MementoCid {
        MementoCid::try_parse(sugar_canonicalizer::blake3_512_of(seed.as_bytes()))
            .expect("test CID must parse")
    }

    fn cid_string(seed: &str) -> String {
        cid(seed).to_string()
    }

    #[test]
    fn bridge_pin_self_pinned_serializes_as_null() {
        let pin = BridgePin::SelfPinned;

        assert_eq!(
            serde_json::to_string(&pin).expect("serialize self pin"),
            "null"
        );
        assert_eq!(
            serde_json::from_str::<BridgePin>("null").expect("deserialize self pin"),
            BridgePin::SelfPinned
        );
    }

    #[test]
    fn bridge_pin_cross_round_trips_as_cid_string() {
        let cid = cid("cross-bundle");
        let pin = BridgePin::Cross(cid.clone());
        let wire = serde_json::to_string(&pin).expect("serialize cross pin");

        assert_eq!(wire, format!("\"{cid}\""));
        assert_eq!(
            serde_json::from_str::<BridgePin>(&wire).expect("deserialize cross pin"),
            pin
        );
    }

    #[test]
    fn bridge_pin_rejects_ill_formed_cid_string() {
        let err = serde_json::from_str::<BridgePin>("\"not-a-cid\"")
            .expect_err("invalid bridge pin CID must refuse");

        assert!(
            err.to_string().contains("bridge target proof CID"),
            "error should name bridge target proof CID: {err}"
        );
    }

    fn make_implication_memento(ant: &str, con: &str) -> Json {
        json!({
            "cid": format!("blake3-512:{}{}", ant, con),
            "evidence": {
                "kind": "implication",
                "body": {
                    "antecedentHash": ant,
                    "consequentHash": con,
                    "prover": "z3@4.12",
                    "proverRunMs": 42
                }
            }
        })
    }

    fn make_inv_only_contract(name: &str, value: i64) -> Json {
        json!({
            "envelope": {
                "signer": "ed25519:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "declaredAt": "2026-05-05T00:00:00Z",
                "signature": "ed25519:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            },
            "header": {
                "schemaVersion": "1",
                "kind": "contract",
                "contractName": name,
                "inv": {
                    "kind": "atomic",
                    "name": "=",
                    "args": [
                        {"kind": "var", "name": "r"},
                        {"kind": "const", "sort": {"kind": "primitive", "name": "Int"}, "value": value}
                    ]
                }
            }
        })
    }

    /// A `callable` contract shaped like the base64-federation showcase's
    /// vendor/consumer duplicate (issue #3589): same `contractName`, same
    /// canonical `header.cid` (name-stripped behavior identity), but cosmetic
    /// authoring metadata (file path, source span) differs by envelope.
    fn make_callable_contract_with_canonical_cid(
        name: &str,
        canonical_cid: &str,
        file: &str,
    ) -> Json {
        json!({
            "envelope": {
                "signer": "ed25519:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "declaredAt": "2026-05-05T00:00:00Z",
                "signature": "ed25519:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            },
            "header": {
                "schemaVersion": "2",
                "kind": "contract",
                "contractName": name,
                "cid": canonical_cid,
                "sourceWarrants": [
                    {"file": file}
                ]
            }
        })
    }

    #[test]
    fn same_canonical_cid_duplicate_names_are_not_load_errors() {
        let name = "b64vendor::encodeBase64::callable";
        let canonical = "blake3-512:b56e68d5de72c6ad524640cae95f2806c945f0dcf2038d93f3ab69f3a47c57fdab3dc91f33d6ad385edbbac8ceb8a8b3cbdd0f39a2ceb20752c7137e5af436dd";
        let mut pool = MementoPool::default();
        let vendor_cid = cid("vendor-envelope");
        let consumer_cid = cid("consumer-envelope");

        pool.insert_unanchored_for_tests(
            vendor_cid.clone(),
            make_callable_contract_with_canonical_cid(name, canonical, "b64vendor.py"),
        );
        pool.insert_unanchored_for_tests(
            consumer_cid.clone(),
            make_callable_contract_with_canonical_cid(
                name,
                canonical,
                "/abs/path/vendor/b64vendor.py",
            ),
        );

        assert!(
            pool.load_errors.is_empty(),
            "same canonical header.cid across two member envelopes must not be a load error: {:#?}",
            pool.load_errors
        );
        assert_eq!(pool.name_to_cid.get(name), Some(&vendor_cid));
        assert!(pool.mementos.contains_key(vendor_cid.as_str()));
        assert!(pool.mementos.contains_key(consumer_cid.as_str()));
    }

    #[test]
    fn lean_header_body_source_memento_uses_common_accessors() {
        let memento = json!({
            "schemaVersion": "1",
            "header": {
                "kind": "source-memento",
                "contractName": "rust-source::enc",
                "sourceFunctionName": "enc"
            },
            "body": {
                "kind": "source-memento",
                "file": "src/lib.rs",
                "source_cid": "blake3-512:source"
            }
        });

        assert!(matches!(
            sugar_proof_envelope::member_kind(&memento),
            Ok(MemberKind::SourceMemento)
        ));
        assert_eq!(
            sugar_proof_envelope::member_body(&memento),
            Some(&memento["body"])
        );
        assert_eq!(
            sugar_proof_envelope::member_field(&memento, "contractName"),
            Some(&memento["header"]["contractName"])
        );
        assert_eq!(
            sugar_proof_envelope::member_field(&memento, "source_cid"),
            Some(&memento["body"]["source_cid"])
        );
    }

    #[test]
    fn euf_inv_only_duplicate_names_are_conjoinable_not_load_errors() {
        let name = "decoded_len_estimate#euf#c:callresult_decoded_len_estimate_a1(i:4)::assertion";
        let mut pool = MementoPool::default();
        let java_cid = cid("java");
        let rust_cid = cid("rust");

        pool.insert_unanchored_for_tests(java_cid.clone(), make_inv_only_contract(name, 3));
        pool.insert_unanchored_for_tests(rust_cid.clone(), make_inv_only_contract(name, 4));

        assert!(
            pool.load_errors.is_empty(),
            "same #euf# inv-only contracts are handled by consistency conjoin, not load errors: {:#?}",
            pool.load_errors
        );
        assert_eq!(pool.name_to_cid.get(name), Some(&java_cid));
        assert!(pool.mementos.contains_key(java_cid.as_str()));
        assert!(pool.mementos.contains_key(rust_cid.as_str()));
    }

    #[test]
    fn non_euf_duplicate_names_remain_load_errors() {
        let name = "src/lib.rs::tests::same_name";
        let mut pool = MementoPool::default();

        pool.insert_unanchored_for_tests(cid("duplicate-a"), make_inv_only_contract(name, 1));
        pool.insert_unanchored_for_tests(cid("duplicate-b"), make_inv_only_contract(name, 2));

        assert!(
            pool.load_errors
                .iter()
                .any(|error| error.reason.contains("duplicate contract name")),
            "plain same-name duplicates must still be surfaced: {:#?}",
            pool.load_errors
        );
    }

    #[test]
    fn transitive_implication_chain_of_three() {
        let mut pool = MementoPool::default();

        // Insert P → Q and Q → R
        let p = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let q = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        let r = "blake3-512:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";

        pool.insert_unanchored_for_tests(cid("m1"), make_implication_memento(p, q));
        pool.insert_unanchored_for_tests(cid("m2"), make_implication_memento(q, r));

        // Check P → R via transitivity
        let result = pool.can_implies(p, r);
        assert!(
            matches!(result, ImplicationResult::ProvenTransitive { .. }),
            "Expected transitive proof for P → R, got {:?}",
            result
        );
    }

    #[test]
    fn direct_implication_lookup() {
        let mut pool = MementoPool::default();

        let p = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let q = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

        pool.insert_unanchored_for_tests(cid("m1"), make_implication_memento(p, q));

        let result = pool.can_implies(p, q);
        assert!(
            matches!(result, ImplicationResult::ProvenDirect { .. }),
            "Expected direct proof, got {:?}",
            result
        );
    }

    #[test]
    fn memento_pool_merge_preserves_effect_site_annotations() {
        let bundle_cid = cid("bundle");
        let key = (
            bundle_cid.clone(),
            "src/lib.rs".to_string(),
            42,
            "method:unwrap".to_string(),
        );
        let annotation = EffectSiteAnnotation {
            effect_kind: "panic-freedom".to_string(),
            file: "src/lib.rs".to_string(),
            line: 42,
            callee: "method:unwrap".to_string(),
            status: "residue".to_string(),
            category: "lock_poisoning_residue".to_string(),
            tier_to_close: "irreducible".to_string(),
            reason: "lock poisoning is runtime residue".to_string(),
            memento_cid: "blake3-512:annotation".to_string(),
            bundle_cid: bundle_cid.to_string(),
        };
        let mut left = MementoPool::default();
        let mut right = MementoPool::default();
        right
            .panic_effect_site_annotations
            .insert(key.clone(), annotation);

        left.merge(right);

        let merged = left
            .panic_effect_site_annotations
            .get(&key)
            .expect("merge must carry annotation index");
        assert_eq!(merged.effect_kind, "panic-freedom");
        assert_eq!(merged.status, "residue");
        assert!(left.load_errors.is_empty(), "{:#?}", left.load_errors);

        let original = EffectSiteAnnotation {
            memento_cid: "blake3-512:annotation-original".to_string(),
            ..merged.clone()
        };
        let duplicate = EffectSiteAnnotation {
            memento_cid: "blake3-512:annotation-duplicate".to_string(),
            ..merged.clone()
        };
        let mut left = MementoPool::default();
        left.panic_effect_site_annotations
            .insert(key.clone(), original);
        let mut right = MementoPool::default();
        right
            .panic_effect_site_annotations
            .insert(key.clone(), duplicate);

        left.merge(right);

        let kept = left
            .panic_effect_site_annotations
            .get(&key)
            .expect("original annotation must remain indexed");
        assert_eq!(kept.memento_cid, "blake3-512:annotation-original");
        assert!(
            left.load_errors
                .iter()
                .any(|error| error.reason.contains("[effect-site-annotation-duplicate]")),
            "duplicate merge must emit stable tagged load error: {:#?}",
            left.load_errors
        );
    }

    #[test]
    fn reflexive_implication_always_holds() {
        let pool = MementoPool::default();

        let p = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

        let result = pool.can_implies(p, p);
        assert!(
            matches!(result, ImplicationResult::ProvenReflexive),
            "Expected reflexive proof, got {:?}",
            result
        );
    }

    #[test]
    fn unknown_imputation_returns_unknown() {
        let pool = MementoPool::default();

        let p = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let q = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

        let result = pool.can_implies(p, q);
        assert!(
            matches!(result, ImplicationResult::Unknown),
            "Expected unknown, got {:?}",
            result
        );
    }

    // ---- PinInvariantMemento round-trip (real pool) ----

    fn make_pin_invariant_memento(
        cid: &str,
        function_cid: &str,
        target: &str,
        invariant: &str,
    ) -> Json {
        json!({
            "cid": cid,
            "envelope": {
                "signer": "ed25519:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "declaredAt": "2026-05-05T00:00:00Z",
                "signature": "ed25519:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            },
            "header": {
                "schemaVersion": "1",
                "kind": "pin-invariant",
                "cid": cid,
                "functionCid": function_cid,
                "pinnedTarget": target
            },
            "metadata": {
                "invariant": invariant
            }
        })
    }

    #[test]
    fn pin_invariant_insert_lookup_roundtrip() {
        let mut pool = MementoPool::default();
        let fc = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let m_cid = cid_string("pin-invariant");
        pool.insert_unanchored_for_tests(
            cid("pin-invariant"),
            make_pin_invariant_memento(&m_cid, fc, "pin", "0 <= state"),
        );
        let view = pool.lookup_pin_invariant(fc, "pin");
        assert!(view.is_some(), "expected Some after insert");
        let v = view.unwrap();
        assert_eq!(v.pinned_target, "pin");
        assert!(!v.invariant.is_empty());
        assert_eq!(v.function_cid, fc);
    }

    #[test]
    fn pin_invariant_cross_function_cid_mismatch() {
        let mut pool = MementoPool::default();
        let fc_a = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let fc_b = "blake3-512:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
        let m_cid = cid_string("pin-invariant-cross");
        pool.insert_unanchored_for_tests(
            cid("pin-invariant-cross"),
            make_pin_invariant_memento(&m_cid, fc_a, "pin", "0 <= state"),
        );
        // Same target "pin" but different function CID: should NOT match
        let view = pool.lookup_pin_invariant(fc_b, "pin");
        assert!(view.is_none(), "cross-function-CID lookup must return None");
    }

    #[test]
    fn pin_invariant_v11_flat_shape_roundtrip() {
        // v1.1 flat shape: no envelope wrapper, fields live in evidence.body.
        // This exercises the fallback path in member_field that reads
        // from /evidence/body instead of /header and /metadata.
        let mut pool = MementoPool::default();
        let fc = "blake3-512:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd";
        let m_cid = cid_string("pin-invariant-v11");
        let flat_memento = json!({
            "cid": m_cid,
            "evidence": {
                "kind": "pin-invariant",
                "body": {
                    "functionCid": fc,
                    "pinnedTarget": "pin",
                    "invariant": "state >= 0"
                }
            }
        });
        pool.insert_unanchored_for_tests(cid("pin-invariant-v11"), flat_memento);
        let view = pool.lookup_pin_invariant(fc, "pin");
        assert!(view.is_some(), "v1.1 flat memento must be found via lookup");
        let v = view.unwrap();
        assert_eq!(v.pinned_target, "pin");
        assert_eq!(v.invariant, "state >= 0");
        assert_eq!(v.function_cid, fc);
    }

    // ---- A precondition is an obligation, not a verified fact ----

    fn make_contract_memento(cid: &str, name: &str, pre: &Json, post: &Json) -> Json {
        // v1.1 flat shape: evidence.kind="contract", derived hashes in body.
        json!({
            "cid": cid,
            "evidence": {
                "kind": "contract",
                "body": {
                    "contractName": name,
                    "pre": pre,
                    "post": post,
                    "preHash": compute_formula_cid(pre),
                    "postHash": compute_formula_cid(post),
                }
            }
        })
    }

    #[test]
    fn precondition_is_obligation_not_verified_fact() {
        // The missing-edge hole: indexing a contract's preHash into the
        // "verified formulas" map (formula_to_memento) makes Tier 0
        // `pool.verify(consumer_pre)` self-discharge — a callsite's consumer
        // precondition is satisfied merely by the callee DECLARING it. A
        // precondition is an obligation to discharge, never an established
        // fact. Only the post (and inv) are guarantees.
        let mut pool = MementoPool::default();
        let pre = json!({
            "kind": "atomic", "pred": "ge",
            "args": [{"kind":"var","name":"encoding"}, {"kind":"const","value":0}]
        });
        let post = json!({
            "kind": "atomic", "pred": "eq",
            "args": [{"kind":"var","name":"result"}, {"kind":"var","name":"value"}]
        });
        let m_cid = cid_string("content-address");
        pool.insert_unanchored_for_tests(
            cid("content-address"),
            make_contract_memento(&m_cid, "content_address", &pre, &post),
        );

        // A postcondition IS an established fact (the function guarantees it).
        assert!(
            pool.verify(&post).is_some(),
            "a contract's post must remain a verified fact"
        );

        // A bare precondition must NOT count as verified — else any callsite's
        // consumer pre self-discharges at Tier 0 and the missing edge hides.
        assert!(
            pool.verify(&pre).is_none(),
            "a contract's bare pre must NOT be treated as a verified fact"
        );
    }
}

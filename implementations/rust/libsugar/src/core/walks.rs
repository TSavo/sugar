// SPDX-License-Identifier: MIT OR Apache-2.0

//! Structural walks over substrate data.
//!
//! This module hosts pure traversals that take only data types (CIDs, Terms,
//! DomainClaims) plus the `Catalog` trait. It explicitly avoids the Kit /
//! Domain / Solver / Verbs dispatch layer so it can be consumed by:
//!
//! - `sugar_walk::bind` for concept-tier hub assertions (relocated from
//!   `core::bind` by #evict-1-bind)
//! - downstream lifters and verifiers that need to traverse premise chains
//!   without inheriting the full Kit dispatcher boundary
//!
//! Two walks live here today:
//!
//! - [`walk_premises_to_root`]: DFS-coloring traversal of a `DomainClaim`'s
//!   premise DAG, looking for an `origin_cid`. Properly discriminates
//!   within-claim duplicates and diamond-DAG re-merges from true cycles.
//! - [`assert_concept_tier`]: refuses a `Term` whose operation tree references
//!   any `op_cid` not present in the catalog (hub tier check).

use std::collections::HashSet;
use std::fmt;

use super::traits::Catalog;
use super::types::{domain_claim_from_canonical_bytes, Cid, DomainClaim, Term};

/// Structural reason a premise walk failed.
///
/// Structural reason a premise walk failed. The four variants enumerate the
/// failure modes of structural chain integrity. **Do not add verdict-shaped
/// variants** (e.g., `NotProved { claim_cid, verdict }`). Verdict checks on
/// intermediate claims belong in a verdict-aware verifier kit, not in this
/// enum. See A8 / #1070 and the 2026-05-16 architect ruling for context.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ChainBreak {
    /// The walk encountered a CID that is currently on the recursion stack,
    /// i.e., a true cycle. Within-claim duplicates and diamond-DAG re-merges
    /// are NOT cycles and resolve via the `reached_origin` memo.
    CycleDetected { cid: Cid },
    /// A premise CID was not present in the catalog.
    PremiseNotInCatalog { cid: Cid },
    /// No premise path reached the configured origin CID.
    OriginUnreachable,
    /// A catalog entry could not be decoded as a DomainClaim.
    DeserializationFailed { cid: Cid, detail: String },
}

impl ChainBreak {
    /// Return the stable variant name serialized into failure witnesses.
    pub fn kind_name(&self) -> &'static str {
        match self {
            Self::CycleDetected { .. } => "CycleDetected",
            Self::PremiseNotInCatalog { .. } => "PremiseNotInCatalog",
            Self::OriginUnreachable => "OriginUnreachable",
            Self::DeserializationFailed { .. } => "DeserializationFailed",
        }
    }
}

impl fmt::Display for ChainBreak {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::CycleDetected { cid } => {
                write!(formatter, "cycle detected at premise {cid}")
            }
            Self::PremiseNotInCatalog { cid } => {
                write!(formatter, "premise {cid} is not present in the catalog")
            }
            Self::OriginUnreachable => {
                formatter.write_str("origin is unreachable from claim premises")
            }
            Self::DeserializationFailed { cid, detail } => {
                write!(formatter, "premise {cid} could not be decoded: {detail}")
            }
        }
    }
}

impl std::error::Error for ChainBreak {}

/// Walk-failure payload that retains the partial trace observed before the
/// break, for a `ChainIntegrityFailureWitness`-shaped caller to report the
/// steps it traced before the algorithm aborted. (The built-in `ProveKit`
/// consumer that motivated this shape was deleted by #evict-3-provekit as
/// dead code; this remains substrate for the next live chain-integrity
/// caller.)
pub struct ChainWalkFailure {
    /// The structural reason the walk broke.
    pub breakage: ChainBreak,
    /// Premise CIDs that were appended to the trace prior to the break, in
    /// pre-order traversal order.
    pub walked_steps_before_break: Vec<Cid>,
}

/// Walk `claim.premises` recursively until `origin_cid` is reached.
///
/// Returns the pre-order trace of premise CIDs whose subtree successfully
/// reached the origin. The `expect_cycle` parameter is retained for source
/// compatibility with the prior signature; it is currently a no-op and is
/// scheduled for removal in a follow-up.
///
/// Failure semantics:
///
/// - `ChainBreak::CycleDetected` iff some CID is its own ancestor on the
///   recursion stack. Within-claim duplicate premise lists like `[X, X]` and
///   diamond-DAG shapes are NOT cycles.
/// - `ChainBreak::PremiseNotInCatalog` iff a referenced premise has no catalog
///   entry. The check fires BEFORE the trace is appended for that CID, so the
///   missing CID never appears in `walked_steps_before_break`.
/// - `ChainBreak::DeserializationFailed` iff a catalog entry's bytes do not
///   decode as `DomainClaim`.
/// - `ChainBreak::OriginUnreachable` iff no leaf in the traversal equals
///   `origin_cid`.
///
/// Verifies structural chain integrity of `claim`'s premise graph back to
/// `origin_cid`. The four failure modes are CycleDetected, PremiseNotInCatalog,
/// OriginUnreachable, and DeserializationFailed.
///
/// **Verdict semantics on intermediate claims are out of scope for this walk.**
/// Intermediate claims may carry any verdict (Pending, Inconclusive, Refuted,
/// Proved). This walk does not propagate or check verdicts on visited claims.
/// The substrate's first principle (Supra omnia rectum) applies: chain-walk
/// proves chain integrity, not semantic correctness of intermediate transforms.
/// Future verdict-aware verifiers belong in their own kits, not here.
pub fn walk_premises_to_root(
    claim: &DomainClaim,
    origin_cid: &Cid,
    catalog: &dyn Catalog,
    expect_cycle: bool,
) -> Result<Vec<Cid>, ChainBreak> {
    walk_premises_to_root_with_failure_steps(claim, origin_cid, catalog, expect_cycle)
        .map_err(|failure| failure.breakage)
}

/// Variant that surfaces the partial trace observed before any break.
pub fn walk_premises_to_root_with_failure_steps(
    claim: &DomainClaim,
    origin_cid: &Cid,
    catalog: &dyn Catalog,
    expect_cycle: bool,
) -> Result<Vec<Cid>, ChainWalkFailure> {
    let _ = expect_cycle;

    // Short-circuit: the starting claim is already the origin. No premises are
    // walked, the trace is empty.
    if claim.cid() == *origin_cid {
        return Ok(Vec::new());
    }

    let mut visited: HashSet<Cid> = HashSet::new();
    let mut on_path: HashSet<Cid> = HashSet::new();
    let mut reached_origin: HashSet<Cid> = HashSet::new();
    let mut trace: Vec<Cid> = Vec::new();

    let mut any_reached = false;
    for premise_cid in &claim.premises {
        match walk_inner(
            premise_cid,
            origin_cid,
            catalog,
            &mut visited,
            &mut on_path,
            &mut reached_origin,
            &mut trace,
        ) {
            Ok(true) => {
                any_reached = true;
            }
            Ok(false) => {}
            Err(breakage) => {
                return Err(ChainWalkFailure {
                    breakage,
                    walked_steps_before_break: trace,
                });
            }
        }
    }

    if any_reached {
        Ok(trace)
    } else {
        Err(ChainWalkFailure {
            breakage: ChainBreak::OriginUnreachable,
            walked_steps_before_break: trace,
        })
    }
}

#[allow(clippy::too_many_arguments)]
fn walk_inner(
    claim_cid: &Cid,
    origin_cid: &Cid,
    catalog: &dyn Catalog,
    visited: &mut HashSet<Cid>,
    on_path: &mut HashSet<Cid>,
    reached_origin: &mut HashSet<Cid>,
    trace: &mut Vec<Cid>,
) -> Result<bool, ChainBreak> {
    // Memo hit: this subtree was already proven to reach origin. Re-merges in
    // diamond-DAGs and within-claim duplicate premises both land here.
    if reached_origin.contains(claim_cid) {
        return Ok(true);
    }
    // The CID is on the current recursion stack: true cycle.
    if on_path.contains(claim_cid) {
        return Err(ChainBreak::CycleDetected {
            cid: claim_cid.clone(),
        });
    }
    // Memo miss: walked elsewhere, didn't reach origin. Re-asserting failure
    // without re-traversing.
    if visited.contains(claim_cid) {
        return Ok(false);
    }

    // Catalog presence is checked BEFORE the trace is updated so that a
    // missing premise never leaks into `walked_steps_before_break`. This
    // matches the contract asserted by this module's own failure tests below
    // (see `PremiseNotInCatalog` cases).
    if !catalog.contains(claim_cid) {
        return Err(ChainBreak::PremiseNotInCatalog {
            cid: claim_cid.clone(),
        });
    }

    // Pre-order trace push. The CID appears in the trace as soon as we commit
    // to descending through it; this matches the existing CycleDetected
    // failure-witness contract (the cycling CID appears in the steps list).
    visited.insert(claim_cid.clone());
    on_path.insert(claim_cid.clone());
    trace.push(claim_cid.clone());

    // Origin reached: terminate this branch successfully.
    if claim_cid == origin_cid {
        on_path.remove(claim_cid);
        reached_origin.insert(claim_cid.clone());
        return Ok(true);
    }

    let bytes = catalog
        .get(claim_cid)
        .ok_or_else(|| ChainBreak::PremiseNotInCatalog {
            cid: claim_cid.clone(),
        })?;
    let claim = domain_claim_from_canonical_bytes(&bytes).map_err(|detail| {
        ChainBreak::DeserializationFailed {
            cid: claim_cid.clone(),
            detail,
        }
    })?;

    let mut any_reached = false;
    for premise_cid in &claim.premises {
        match walk_inner(
            premise_cid,
            origin_cid,
            catalog,
            visited,
            on_path,
            reached_origin,
            trace,
        ) {
            Ok(true) => any_reached = true,
            Ok(false) => {}
            Err(breakage) => {
                // Leave on_path intact so re-entry through another path still
                // detects the cycle correctly; the early return aborts the
                // whole traversal anyway.
                return Err(breakage);
            }
        }
    }

    on_path.remove(claim_cid);
    if any_reached {
        reached_origin.insert(claim_cid.clone());
    }
    Ok(any_reached)
}

/// Refusal payload: a `Term::Op` node referenced an operation CID that is not
/// present in the catalog, i.e., the node is not concept-tier under this
/// catalog's hub view.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HubMissingNode {
    /// The operation CID that was absent from the catalog.
    pub node_op_cid: Cid,
    /// Slot path from the root term to the offending operation node, in the
    /// same shape as [`Term::walk`] yields.
    pub term_position: Vec<usize>,
}

impl fmt::Display for HubMissingNode {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "term operation {} at position {:?} is not present in the concept-tier catalog",
            self.node_op_cid, self.term_position
        )
    }
}

impl std::error::Error for HubMissingNode {}

/// Refuse `term` unless every operation node's `op_cid` is in `catalog`.
///
/// Walks the term in pre-order (matching [`Term::walk`]). The first node whose
/// `op_cid` is absent from the catalog produces `Err(HubMissingNode)` carrying
/// the offending op CID and its term position. Constants, vars, and unit
/// nodes are skipped because they carry no operation CID.
pub fn assert_concept_tier(term: &Term, catalog: &dyn Catalog) -> Result<(), HubMissingNode> {
    for node in term.walk() {
        if !catalog.contains(node.op_cid) {
            return Err(HubMissingNode {
                node_op_cid: node.op_cid.clone(),
                term_position: node.term_position.clone(),
            });
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::compose::{
        build_value, cid_of_value, jcs_bytes_of_value, EffectSet, FunctionContractMemento, Locus,
    };
    use crate::core::primitives::address;
    use crate::core::traits::HashMapCatalog;
    use crate::core::types::{DomainKind, Verdict};
    use serde_json::json;
    use std::sync::Arc;
    use sugar_canonicalizer::Value;
    use sugar_ir_types::{IrFormula, IrTerm, Sort};

    // ---- DomainClaim fixture helpers ---------------------------------------

    fn any_sort() -> Sort {
        Sort::Primitive {
            name: "Any".to_string(),
        }
    }

    fn bool_true() -> IrFormula {
        IrFormula::Atomic {
            name: "true".to_string(),
            args: vec![],
        }
    }

    fn pure_identity_contract(fn_name: &str) -> FunctionContractMemento {
        let formals = vec!["x".to_string()];
        let formal_sorts = vec![any_sort()];
        let return_sort = any_sort();
        let pre = bool_true();
        let post = IrFormula::Atomic {
            name: "=".to_string(),
            args: vec![
                IrTerm::Var {
                    name: "result".to_string(),
                },
                IrTerm::Var {
                    name: "x".to_string(),
                },
            ],
        };
        let effects = EffectSet::empty();
        let locus = Locus::unknown();
        let value: Arc<Value> = build_value(
            fn_name,
            &formals,
            &formal_sorts,
            &return_sort,
            &pre,
            &post,
            None,
            &effects,
            &locus,
            &[],
        );
        let canonical_bytes = jcs_bytes_of_value(&value);
        let cid = cid_of_value(&value);

        FunctionContractMemento {
            fn_name: fn_name.to_string(),
            formals,
            formal_sorts,
            formal_regions: vec![],
            return_sort,
            return_region: None,
            pre,
            post,
            body_cid: None,
            effects,
            locus,
            canonical_bytes,
            cid,
            auto_minted_mementos: vec![],
            panic_loci: vec![],
            concept_hint: None,
        }
    }

    fn claim_fixture(name: &str) -> DomainClaim {
        let contract = pure_identity_contract(name);
        let to = Cid::try_from(contract.cid.clone()).expect("fixture cid is valid");
        let artifact = address(&format!("contract:{}", contract.cid));
        DomainClaim {
            domain: DomainKind::FunctionContract,
            contract,
            artifacts: vec![artifact],
            from: vec![],
            premises: vec![],
            to,
            witness: None,
            payload: None,
            verdict: Verdict::Unresolved,
            attestation: None,
        }
    }

    fn insert_claim(catalog: &mut HashMapCatalog, claim: &DomainClaim) -> Cid {
        let cid = claim.cid();
        catalog.put(cid.clone(), claim.canonical_bytes());
        cid
    }

    // ---- walk_premises_to_root tests --------------------------------------

    #[test]
    fn happy_three_step_linear_chain_returns_pre_order_trace() {
        // origin <- mid <- terminal
        let root = claim_fixture("root");
        let root_cid = root.cid();

        let mut mid = claim_fixture("mid");
        mid.premises = vec![root_cid.clone()];
        let mid_cid = mid.cid();

        let mut terminal = claim_fixture("terminal");
        terminal.premises = vec![mid_cid.clone()];

        let mut catalog = HashMapCatalog::default();
        insert_claim(&mut catalog, &root);
        insert_claim(&mut catalog, &mid);

        let trace = walk_premises_to_root(&terminal, &root_cid, &catalog, false)
            .expect("linear chain walk succeeds");

        // Pre-order trace: mid is pushed first (descending from terminal),
        // then root is pushed when reached.
        assert_eq!(trace, vec![mid_cid, root_cid]);
    }

    #[test]
    fn walk_premises_returns_ok_when_intermediate_claims_have_non_proved_verdicts() {
        let origin = claim_fixture("verdict-policy-origin");
        let origin_cid = origin.cid();

        let mut intermediate = claim_fixture("verdict-policy-intermediate");
        intermediate.premises = vec![origin_cid.clone()];
        intermediate.verdict = Verdict::Unresolved;
        let intermediate_cid = intermediate.cid();

        let mut terminal = claim_fixture("verdict-policy-terminal");
        terminal.premises = vec![intermediate_cid.clone()];

        let mut catalog = HashMapCatalog::default();
        insert_claim(&mut catalog, &origin);
        insert_claim(&mut catalog, &intermediate);

        let trace = walk_premises_to_root(&terminal, &origin_cid, &catalog, false)
            .expect("intermediate non-Proved verdict is ignored by structural walk");

        assert_eq!(trace, vec![intermediate_cid, origin_cid]);
    }

    #[test]
    fn true_cycle_returns_cycle_detected() {
        // True cycle via two distinct, in-catalog CIDs pointing at each other.
        // We don't need the CIDs to be self-consistent canonical hashes of the
        // stored bytes; the walker keys on CIDs as opaque pointers, so we use
        // `address(...)` to mint stable handles A_cid and B_cid, then store
        // hand-built claim payloads under them.
        let a_cid = address(&"cycle-anchor-a");
        let b_cid = address(&"cycle-anchor-b");

        let mut a_claim = claim_fixture("cycle-a");
        a_claim.premises = vec![b_cid.clone()];
        let mut b_claim = claim_fixture("cycle-b");
        b_claim.premises = vec![a_cid.clone()];

        let mut catalog = HashMapCatalog::default();
        catalog.put(a_cid.clone(), a_claim.canonical_bytes());
        catalog.put(b_cid.clone(), b_claim.canonical_bytes());

        // Terminal claim enters the cycle by pointing at A.
        let mut terminal = claim_fixture("cycle-terminal");
        terminal.premises = vec![a_cid.clone()];

        let origin = address(&"unreachable-origin");
        let err = walk_premises_to_root(&terminal, &origin, &catalog, false)
            .expect_err("cycle aborts walk");

        match err {
            ChainBreak::CycleDetected { cid } => {
                // Walk: terminal -> A (push+on_path) -> B (push+on_path) -> A
                // -> on_path hit on A -> CycleDetected{cid: A}.
                assert_eq!(cid, a_cid);
            }
            other => panic!("expected CycleDetected, got {other:?}"),
        }
    }

    #[test]
    fn missing_premise_returns_premise_not_in_catalog() {
        let missing = address(&"missing-premise");
        let mut terminal = claim_fixture("terminal");
        terminal.premises = vec![missing.clone()];

        let origin = address(&"never-reached-origin");
        let catalog = HashMapCatalog::default();

        let err = walk_premises_to_root(&terminal, &origin, &catalog, false)
            .expect_err("missing premise aborts walk");

        assert!(
            matches!(err, ChainBreak::PremiseNotInCatalog { cid } if cid == missing),
            "expected PremiseNotInCatalog for {missing:?}",
        );
    }

    #[test]
    fn no_path_to_origin_returns_origin_unreachable() {
        // terminal -> root, but origin is a different CID with no presence.
        let root = claim_fixture("root");
        let mut catalog = HashMapCatalog::default();
        insert_claim(&mut catalog, &root);
        let mut terminal = claim_fixture("terminal");
        terminal.premises = vec![root.cid()];

        let origin = address(&"unrelated-origin");

        let err = walk_premises_to_root(&terminal, &origin, &catalog, false)
            .expect_err("orphan chain returns OriginUnreachable");
        assert!(matches!(err, ChainBreak::OriginUnreachable));
    }

    #[test]
    fn malformed_catalog_bytes_returns_deserialization_failed() {
        // Insert junk bytes under a CID and reference it as a premise.
        let mut catalog = HashMapCatalog::default();
        let junk_cid = address(&"junk-bytes-claim");
        catalog.put(junk_cid.clone(), b"{not a domain claim}".to_vec());

        let mut terminal = claim_fixture("terminal");
        terminal.premises = vec![junk_cid.clone()];

        let origin = address(&"never-reached");
        let err = walk_premises_to_root(&terminal, &origin, &catalog, false)
            .expect_err("junk bytes fail to decode");

        match err {
            ChainBreak::DeserializationFailed { cid, detail: _ } => {
                assert_eq!(cid, junk_cid);
            }
            other => panic!("expected DeserializationFailed, got {other:?}"),
        }
    }

    #[test]
    fn within_claim_duplicate_premise_resolves_via_memo() {
        // Regression for A2's single-set bug: terminal.premises = [root, root]
        // must walk successfully because the second visit is a memo hit, not
        // a cycle.
        let root = claim_fixture("root");
        let root_cid = root.cid();
        let mut catalog = HashMapCatalog::default();
        insert_claim(&mut catalog, &root);

        let mut terminal = claim_fixture("terminal");
        terminal.premises = vec![root_cid.clone(), root_cid.clone()];

        let trace = walk_premises_to_root(&terminal, &root_cid, &catalog, false)
            .expect("within-claim duplicate must resolve");
        // The first visit pushes root_cid; the second visit is a memo hit and
        // does NOT re-push.
        assert_eq!(trace, vec![root_cid]);
    }

    #[test]
    fn diamond_dag_re_merge_resolves_via_memo() {
        // A=[B,C]; B=[D]; C=[D]; D=[origin]. The shared D must be walked once
        // and memoized as reached_origin.
        let origin_claim = claim_fixture("origin");
        let origin_cid = origin_claim.cid();
        let mut d = claim_fixture("d");
        d.premises = vec![origin_cid.clone()];
        let d_cid = d.cid();
        let mut b = claim_fixture("b");
        b.premises = vec![d_cid.clone()];
        let b_cid = b.cid();
        let mut c = claim_fixture("c");
        c.premises = vec![d_cid.clone()];
        let c_cid = c.cid();
        let mut a = claim_fixture("a");
        a.premises = vec![b_cid.clone(), c_cid.clone()];

        let mut catalog = HashMapCatalog::default();
        insert_claim(&mut catalog, &origin_claim);
        insert_claim(&mut catalog, &d);
        insert_claim(&mut catalog, &b);
        insert_claim(&mut catalog, &c);

        let trace = walk_premises_to_root(&a, &origin_cid, &catalog, false)
            .expect("diamond DAG re-merge must resolve");
        // Pre-order: B, D, origin, then C (memo-hits D).
        assert_eq!(trace, vec![b_cid, d_cid, origin_cid, c_cid]);
    }

    #[test]
    fn multi_step_diamond_with_deeper_remerge_resolves() {
        // A=[B,C]; B=[D,E]; C=[E,F]; D=[origin]; E=[origin]; F=[origin].
        // Tests multiple memo hits at different depths.
        let origin_claim = claim_fixture("multi-origin");
        let origin_cid = origin_claim.cid();
        let mut d = claim_fixture("multi-d");
        d.premises = vec![origin_cid.clone()];
        let d_cid = d.cid();
        let mut e = claim_fixture("multi-e");
        e.premises = vec![origin_cid.clone()];
        let e_cid = e.cid();
        let mut f = claim_fixture("multi-f");
        f.premises = vec![origin_cid.clone()];
        let f_cid = f.cid();
        let mut b = claim_fixture("multi-b");
        b.premises = vec![d_cid.clone(), e_cid.clone()];
        let b_cid = b.cid();
        let mut c = claim_fixture("multi-c");
        c.premises = vec![e_cid.clone(), f_cid.clone()];
        let c_cid = c.cid();
        let mut a = claim_fixture("multi-a");
        a.premises = vec![b_cid.clone(), c_cid.clone()];

        let mut catalog = HashMapCatalog::default();
        insert_claim(&mut catalog, &origin_claim);
        insert_claim(&mut catalog, &d);
        insert_claim(&mut catalog, &e);
        insert_claim(&mut catalog, &f);
        insert_claim(&mut catalog, &b);
        insert_claim(&mut catalog, &c);

        let trace = walk_premises_to_root(&a, &origin_cid, &catalog, false)
            .expect("multi-step diamond must resolve");

        // Sanity invariants: every node appears at most once, and origin is
        // present exactly once.
        let mut seen = HashSet::new();
        for cid in &trace {
            assert!(seen.insert(cid.clone()), "{cid} repeated in trace");
        }
        assert!(trace.contains(&origin_cid));
        assert!(trace.contains(&b_cid));
        assert!(trace.contains(&c_cid));
        assert!(trace.contains(&d_cid));
        assert!(trace.contains(&e_cid));
        assert!(trace.contains(&f_cid));
    }

    // ---- assert_concept_tier tests -----------------------------------------

    fn make_op(name: &str, op_cid: Cid, args: Vec<Term>) -> Term {
        Term::Op {
            op_cid,
            name: name.to_string(),
            args,
        }
    }

    fn const_leaf() -> Term {
        Term::Const {
            value: json!(0),
            sort: Sort::Primitive {
                name: "Int".to_string(),
            },
        }
    }

    #[test]
    fn assert_concept_tier_ok_when_every_op_cid_is_in_catalog() {
        let add_cid = address(&"op:add");
        let mul_cid = address(&"op:mul");
        let mut catalog = HashMapCatalog::default();
        catalog.put(add_cid.clone(), b"add-op".to_vec());
        catalog.put(mul_cid.clone(), b"mul-op".to_vec());

        // (add (mul const const) const)
        let term = make_op(
            "add",
            add_cid,
            vec![
                make_op("mul", mul_cid, vec![const_leaf(), const_leaf()]),
                const_leaf(),
            ],
        );

        assert_concept_tier(&term, &catalog).expect("all ops are hub-tier");
    }

    #[test]
    fn assert_concept_tier_refuses_when_op_cid_absent_with_correct_position() {
        let add_cid = address(&"op:add-present");
        let missing_cid = address(&"op:missing");
        let mut catalog = HashMapCatalog::default();
        catalog.put(add_cid.clone(), b"add-op".to_vec());
        // missing_cid is intentionally not inserted.

        // (add const (missing const)): the missing op is at term_position [1].
        let term = make_op(
            "add",
            add_cid,
            vec![
                const_leaf(),
                make_op("missing", missing_cid.clone(), vec![const_leaf()]),
            ],
        );

        let err = assert_concept_tier(&term, &catalog).expect_err("missing op CID must be refused");
        assert_eq!(err.node_op_cid, missing_cid);
        assert_eq!(err.term_position, vec![1]);
    }
}

// SPDX-License-Identifier: Apache-2.0
//
// Shadow source tree: a parallel structure mirroring a source `syn::ItemFn`
// where each AST node is a "slot" carrying ZERO OR MORE arrivals.
//
// Per the substrate's data-flow semantics: each AST node can have N
// arrivals, one per callsite whose backward WP propagation passed through
// this node. The shadow source mirrors the source AST's structure; the
// arrivals at each slot are the per-callsite WP propagation visits.
//
// Each shadow node IS a memento. The shadow source IS the artifact the
// substrate caches; visiting the same source AST with the same set of
// callee preconditions produces the same shadow source byte-for-byte,
// hash-for-hash.
//
// Schema for the canonical bytes (JCS-encoded):
//
//   ShadowSource:
//   {
//     "schemaVersion": "1",
//     "kind": "shadow-source",
//     "fnName": <string>,
//     "slots": [<ShadowSlot CID>, ...]      // one per body statement, in source order
//   }
//
//   ShadowSlot:
//   {
//     "schemaVersion": "1",
//     "kind": "shadow-slot",
//     "fnName": <string>,
//     "sourceIndex": <integer>,             // body[i] for i < len, len for entry
//     "sourceKindLabel": <string>,          // "let:y" | "callsite:f" | "stmt" | "function-entry"
//     "arrivals": [<ShadowArrival CID>, ...] // one per callsite chain reaching this slot
//   }
//
//   ShadowArrival:
//   {
//     "schemaVersion": "1",
//     "kind": "shadow-arrival",
//     "fnName": <string>,
//     "sourceIndex": <integer>,
//     "calleeName": <string>,               // which callsite chain this arrival belongs to
//     "calleeRootCid": <CID>,               // CID of the callsite root arrival that anchors this chain
//     "preWp": <IrFormula>,
//     "postWp": <IrFormula>,
//     "predecessorCid": <CID or null>       // previous arrival in this callsite chain
//   }
//
// Each `(preWp → postWp)` pair on a `ShadowArrival` is the v1.5.0-shape
// edge memento for that arrival, where `pre` and `post` map onto the
// `ContractDecl.pre` / `ContractDecl.post` fields per paper 07 §11.

use std::collections::BTreeMap;
use std::sync::Arc;

use sugar_canonicalizer::Value;
use syn::{ItemFn, Stmt};

use crate::canonical::{cid_of_value, formula_to_canonical, jcs_bytes_of_value};
use crate::walk::walk_callsites_to_entry;
use crate::wp::Wp;

/// One callee that the walker should propagate through the caller's body.
/// `formal_params[i]` is substituted by the i-th actual argument expression
/// at every callsite.
#[derive(Debug, Clone)]
pub struct CalleeContract {
    pub callee_name: String,
    pub formal_params: Vec<String>,
    pub precondition: Wp,
}

/// Top-level shadow artifact. Mirrors the source AST's structure for one
/// caller function and lists the per-AST-node slot mementos.
#[derive(Debug, Clone)]
pub struct ShadowSource {
    pub fn_name: String,
    pub slots: Vec<ShadowSlot>,
    pub canonical_bytes: Vec<u8>,
    pub cid: String,
}

/// One AST-node slot. Holds the arrivals that propagated through this
/// node from any callsite. The slot's CID includes its source position,
/// its kind label, and the sorted list of arrival CIDs.
#[derive(Debug, Clone)]
pub struct ShadowSlot {
    pub source_index: usize,
    pub source_kind_label: String,
    pub arrivals: Vec<ShadowArrival>,
    pub canonical_bytes: Vec<u8>,
    pub cid: String,
}

/// One arrival at a slot. Belongs to exactly one callsite chain (identified
/// by `callee_root_cid`); a slot may carry many such arrivals.
///
/// `allocation_cid` is the CID of the arrival at the chain's terminal
/// allocation (the let-binding or function-entry that bound the chain's
/// originating variable). It travels with the arrival as a separate
/// content-addressable memento — receivers either have it cached or
/// fetch it via the substrate. For the allocation arrival itself,
/// `allocation_cid` is None; the allocation IS the answer to "where did
/// the originating variable come from?"
#[derive(Debug, Clone)]
pub struct ShadowArrival {
    pub fn_name: String,
    pub source_index: usize,
    pub callee_name: String,
    pub callee_root_cid: String,
    pub pre_wp: Wp,
    pub post_wp: Wp,
    pub predecessor_cid: Option<String>,
    pub allocation_cid: Option<String>,
    pub canonical_bytes: Vec<u8>,
    pub cid: String,
}

impl ShadowSlot {
    /// Filter arrivals belonging to a particular callsite chain (identified
    /// by the callsite-root arrival's CID).
    pub fn arrivals_for_callsite<'a, 'b>(
        &'a self,
        callee_root_cid: &'b str,
    ) -> impl Iterator<Item = &'a ShadowArrival> + use<'a, 'b> {
        let needle = callee_root_cid.to_string();
        self.arrivals
            .iter()
            .filter(move |a| a.callee_root_cid == needle)
    }
}

impl ShadowSource {
    /// Find the slot for a given source index (body[i] or len for entry).
    pub fn slot(&self, source_index: usize) -> Option<&ShadowSlot> {
        self.slots.iter().find(|s| s.source_index == source_index)
    }

    /// Iterate every (slot, arrival) pair. Useful for emission / cache
    /// upload paths.
    pub fn all_arrivals(&self) -> impl Iterator<Item = (&ShadowSlot, &ShadowArrival)> {
        self.slots
            .iter()
            .flat_map(|s| s.arrivals.iter().map(move |a| (s, a)))
    }
}

// ---- Build ----

/// Build the shadow source for a caller, propagating WP backward from
/// every callsite to each callee in `callees`. Each callsite produces a
/// chain of arrivals; the chain's arrivals are deposited into the
/// matching slots in source order.
pub fn build_shadow_source(caller: &ItemFn, callees: &[CalleeContract]) -> ShadowSource {
    let fn_name = caller.sig.ident.to_string();
    let body_stmts: &[Stmt] = &caller.block.stmts;
    let n_stmts = body_stmts.len();

    // arrivals_by_index: source_index → Vec<ShadowArrival>
    // We collect first, sort and CID-stamp at the end so byte-output is
    // deterministic regardless of which callee we walked first.
    let mut arrivals_by_index: BTreeMap<usize, Vec<ShadowArrival>> = BTreeMap::new();
    // Pre-seed every body slot AND the function-entry slot so the shadow
    // source has the same structural shape regardless of how many callsites
    // hit which positions.
    for i in 0..=n_stmts {
        arrivals_by_index.entry(i).or_default();
    }

    for callee in callees {
        let walks = walk_callsites_to_entry(
            caller,
            &callee.callee_name,
            &callee.formal_params,
            callee.precondition.clone(),
        );
        for walk in walks {
            // Mint arrivals in REVERSE walk order (entry → callsite) so
            // each arrival's canonical bytes can include `allocationCid`
            // pointing to the chain's terminal allocation arrival, which
            // is minted first.
            //
            // - The terminal allocation (walk.arrivals.last()) has
            //   allocationCid = null in its bytes; it IS the allocation
            //   that anchors the "over x" answer.
            // - Each subsequent arrival (closer to the callsite) carries
            //   allocationCid = the terminal allocation's CID.
            // - predecessor_cid points DATA-FLOW UPSTREAM (toward the
            //   allocation), i.e. to the previously-minted arrival in
            //   the reverse iteration.
            // - callsite_root_cid is metadata-only (struct field, not in
            //   canonical bytes) to avoid a second fixed-point at the
            //   chain root. The chain root is recoverable by walking
            //   predecessor_cid backward to a None-predecessor arrival
            //   that is NOT the allocation.
            //
            // Wait: with predecessor pointing data-flow-upstream, the
            // allocation has predecessor = None and so does the callsite
            // (since the callsite is the last to be minted; nothing
            // points toward it). To distinguish: the allocation is the
            // arrival whose `allocation_cid` is None; the callsite is
            // the arrival whose source_index matches the callsite's
            // and whose `allocation_cid` is Some.
            //
            // Equivalently: callsite is the only arrival whose preWp
            // equals postWp (no transformation happened upstream of it
            // yet), but we don't enforce that structurally here.

            let arrivals_walk_order = &walk.arrivals;
            let n = arrivals_walk_order.len();
            if n == 0 {
                continue;
            }

            let mut predecessor_cid: Option<String> = None;
            let mut allocation_cid: Option<String> = None;
            let mut callsite_root_cid: Option<String> = None;
            // Collect minted arrivals indexed by their position in the
            // original walk so we can push them into arrivals_by_index
            // in source order (which doesn't necessarily match mint
            // order).
            let mut minted: Vec<Option<ShadowArrival>> = (0..n).map(|_| None).collect();

            for k in 0..n {
                // Walk from the last (terminal allocation) to the first
                // (callsite). `walk_idx` is the index in walk.arrivals.
                let walk_idx = n - 1 - k;
                let walk_arrival = &arrivals_walk_order[walk_idx];

                let post_wp = if walk_idx == 0 {
                    walk_arrival.wp.clone()
                } else {
                    arrivals_walk_order[walk_idx - 1].wp.clone()
                };
                let pre_wp = walk_arrival.wp.clone();

                let value = arrival_value(
                    &fn_name,
                    walk_arrival.stmt_index,
                    &callee.callee_name,
                    &pre_wp,
                    &post_wp,
                    predecessor_cid.as_deref(),
                    allocation_cid.as_deref(),
                );
                let canonical_bytes = jcs_bytes_of_value(&value);
                let cid = cid_of_value(&value);

                if allocation_cid.is_none() {
                    // First minted = chain's terminal allocation.
                    allocation_cid = Some(cid.clone());
                }
                if k == n - 1 {
                    // Last minted = the callsite (top of chain). Its CID
                    // is the chain's root identifier (metadata-only).
                    callsite_root_cid = Some(cid.clone());
                }

                let arrival = ShadowArrival {
                    fn_name: fn_name.clone(),
                    source_index: walk_arrival.stmt_index,
                    callee_name: callee.callee_name.clone(),
                    callee_root_cid: String::new(), // backfilled after the loop
                    pre_wp,
                    post_wp,
                    predecessor_cid: predecessor_cid.clone(),
                    allocation_cid: if k == 0 { None } else { allocation_cid.clone() },
                    canonical_bytes,
                    cid: cid.clone(),
                };
                minted[walk_idx] = Some(arrival);
                predecessor_cid = Some(cid);
            }

            // Backfill the callee_root_cid metadata field on every minted
            // arrival, then push them into the source-index buckets.
            let root_cid = callsite_root_cid.unwrap_or_default();
            for slot in minted.into_iter().flatten() {
                let mut a = slot;
                a.callee_root_cid = root_cid.clone();
                arrivals_by_index.entry(a.source_index).or_default().push(a);
            }
        }
    }

    // Build slots in source order (0..=n_stmts), CID-stamping each slot
    // from a stable ordering of its arrivals (sorted by CID for
    // determinism — order in which callsites were walked doesn't leak
    // into the slot CID).
    let mut slots: Vec<ShadowSlot> = Vec::with_capacity(n_stmts + 1);
    for source_index in 0..=n_stmts {
        let mut arrivals = arrivals_by_index.remove(&source_index).unwrap_or_default();
        arrivals.sort_by(|a, b| a.cid.cmp(&b.cid));
        let label = source_kind_label_for(body_stmts, source_index, &arrivals);
        let value = slot_value(&fn_name, source_index, &label, &arrivals);
        let canonical_bytes = jcs_bytes_of_value(&value);
        let cid = cid_of_value(&value);
        slots.push(ShadowSlot {
            source_index,
            source_kind_label: label,
            arrivals,
            canonical_bytes,
            cid,
        });
    }

    let source_value = source_value(&fn_name, &slots);
    let canonical_bytes = jcs_bytes_of_value(&source_value);
    let cid = cid_of_value(&source_value);

    ShadowSource {
        fn_name,
        slots,
        canonical_bytes,
        cid,
    }
}

// ---- canonical-value emission ----

fn arrival_value(
    fn_name: &str,
    source_index: usize,
    callee_name: &str,
    pre_wp: &Wp,
    post_wp: &Wp,
    predecessor_cid: Option<&str>,
    allocation_cid: Option<&str>,
) -> Arc<Value> {
    let predecessor_value: Arc<Value> = match predecessor_cid {
        Some(cid) => Value::string(cid.to_string()),
        None => Value::null(),
    };
    let allocation_value: Arc<Value> = match allocation_cid {
        Some(cid) => Value::string(cid.to_string()),
        None => Value::null(),
    };
    Value::object([
        ("schemaVersion", Value::string("1")),
        ("kind", Value::string("shadow-arrival")),
        ("fnName", Value::string(fn_name.to_string())),
        ("sourceIndex", Value::integer(source_index as i128)),
        ("calleeName", Value::string(callee_name.to_string())),
        ("preWp", formula_to_canonical(pre_wp.as_formula())),
        ("postWp", formula_to_canonical(post_wp.as_formula())),
        ("predecessorCid", predecessor_value),
        ("allocationCid", allocation_value),
    ])
}

fn slot_value(
    fn_name: &str,
    source_index: usize,
    label: &str,
    arrivals: &[ShadowArrival],
) -> Arc<Value> {
    let arrival_cids: Vec<Arc<Value>> = arrivals
        .iter()
        .map(|a| Value::string(a.cid.clone()))
        .collect();
    Value::object([
        ("schemaVersion", Value::string("1")),
        ("kind", Value::string("shadow-slot")),
        ("fnName", Value::string(fn_name.to_string())),
        ("sourceIndex", Value::integer(source_index as i128)),
        ("sourceKindLabel", Value::string(label.to_string())),
        ("arrivals", Value::array(arrival_cids)),
    ])
}

fn source_value(fn_name: &str, slots: &[ShadowSlot]) -> Arc<Value> {
    let slot_cids: Vec<Arc<Value>> = slots.iter().map(|s| Value::string(s.cid.clone())).collect();
    Value::object([
        ("schemaVersion", Value::string("1")),
        ("kind", Value::string("shadow-source")),
        ("fnName", Value::string(fn_name.to_string())),
        ("slots", Value::array(slot_cids)),
    ])
}

// Source-AST-side label for the slot. Keeps determinism and human-readable
// debugging of the canonical bytes. For the function-entry slot
// (source_index == n_stmts) we always use "function-entry"; for body
// statements we look at the syn::Stmt and produce a stable label.
fn source_kind_label_for(
    body_stmts: &[Stmt],
    source_index: usize,
    arrivals: &[ShadowArrival],
) -> String {
    if source_index == body_stmts.len() {
        return "function-entry".to_string();
    }
    let stmt = &body_stmts[source_index];
    match stmt {
        Stmt::Local(local) => match &local.pat {
            syn::Pat::Ident(p) => format!("let:{}", p.ident),
            syn::Pat::Type(pt) => match &*pt.pat {
                syn::Pat::Ident(p) => format!("let:{}", p.ident),
                _ => "let:<pat>".to_string(),
            },
            _ => "let:<pat>".to_string(),
        },
        Stmt::Expr(_, _) => {
            // If any arrival here is the callsite root for its chain, name the
            // callee for human-readable labels. Otherwise it's a plain expression.
            //
            // The callsite root is the arrival whose `callee_root_cid` equals
            // its own `cid` — only the chain root satisfies this. Both the
            // allocation arrival and intermediate arrivals have `callee_root_cid`
            // pointing to the chain root (not themselves).
            // Using `predecessor_cid.is_none()` is WRONG: both the allocation
            // (minted first, no predecessor yet) and the callsite root (minted
            // last, nothing points toward it) have `predecessor_cid == None`.
            if let Some(a) = arrivals.iter().find(|a| a.callee_root_cid == a.cid) {
                format!("callsite:{}", a.callee_name)
            } else {
                "stmt".to_string()
            }
        }
        Stmt::Macro(_) => "macro".to_string(),
        Stmt::Item(_) => "item".to_string(),
    }
}

// ---- v1.5.0-shape edge memento per arrival ----

/// Each `ShadowArrival` is one v1.5.0-shape edge memento. This helper
/// returns the JCS-canonical bytes of that edge as a `ContractDecl`-shape
/// value (per paper 07 §11): `kind = "contract"`, `pre = pre_wp`,
/// `post = post_wp`, `outBinding` = result binding, plus `evidence` carrying
/// the walk provenance.
///
/// Shape matches the substrate's `ContractDecl` parser (schemaVersion "2")
/// that existing parsers (sugar-claim-envelope, Zig, Go) accept:
///   { schemaVersion, kind:"contract", name, outBinding, pre, post, evidence }
pub fn edge_memento_value(arrival: &ShadowArrival) -> Arc<Value> {
    let name = format!(
        "{}@{}/{}",
        arrival.callee_name, arrival.fn_name, arrival.source_index
    );
    let evidence = Value::object([
        ("kind", Value::string("walk-arrival")),
        ("fnName", Value::string(arrival.fn_name.clone())),
        ("sourceIndex", Value::integer(arrival.source_index as i128)),
        ("calleeName", Value::string(arrival.callee_name.clone())),
        (
            "witness",
            Value::object([
                ("kind", Value::string("placeholder")),
                ("note", Value::string("MVP walk; solver dispatch deferred")),
            ]),
        ),
    ]);
    Value::object([
        ("schemaVersion", Value::string("2")),
        ("kind", Value::string("contract")),
        ("name", Value::string(name)),
        ("outBinding", Value::string("result".to_string())),
        ("pre", formula_to_canonical(arrival.pre_wp.as_formula())),
        ("post", formula_to_canonical(arrival.post_wp.as_formula())),
        ("evidence", evidence),
    ])
}

/// CID of the edge memento for one arrival.
pub fn edge_memento_cid(arrival: &ShadowArrival) -> String {
    cid_of_value(&edge_memento_value(arrival))
}

/// One composed edge: a content-addressed link from `p` (the
/// component chain's leftmost antecedent) to `q` (the rightmost
/// consequent). The composed edge is a flat memento — readers don't
/// need the intermediate steps to verify reachability; they verify
/// each constituent CID is in the substrate, then trust hash
/// combination.
///
/// Paper 07 §3: composition is hash combination, free, associative.
/// Paper 07 §6: cached composed edges accelerate every future
/// discharge that hits the same `(p, q)` shape.
#[derive(Debug, Clone)]
pub struct ComposedEdge {
    pub p: sugar_ir_types::IrFormula,
    pub q: sugar_ir_types::IrFormula,
    pub component_cids: Vec<String>,
    pub canonical_bytes: Vec<u8>,
    pub cid: String,
}

/// Compose two adjacent edges into a single content-addressed edge.
/// "Adjacent" means `e1.q == e2.p` semantically (the chain's middle
/// predicate matches). The composed edge's CID is hash-combined from
/// its components, mirroring Merkle-tree composition.
///
/// The function does not enforce semantic adjacency at the formula
/// level — it composes structurally and lets the substrate's downstream
/// soundness checks (multi-solver consensus) discharge. This matches
/// the categorical view: morphism composition is mechanical; soundness
/// of the chain is a separate proof obligation.
pub fn compose_edges(left: &ShadowArrival, right: &ShadowArrival) -> ComposedEdge {
    compose_components(
        &left.pre_wp.as_formula().clone(),
        &right.post_wp.as_formula().clone(),
        vec![left.cid.clone(), right.cid.clone()],
    )
}

/// Compose an arbitrary chain of edges. Order matters (this is the
/// chain's left-to-right composition); empty chains panic.
pub fn compose_chain<'a, I>(edges: I) -> ComposedEdge
where
    I: IntoIterator<Item = &'a ShadowArrival>,
{
    let mut iter = edges.into_iter();
    let first = iter
        .next()
        .expect("compose_chain requires at least one edge");
    let mut p = first.pre_wp.as_formula().clone();
    let mut q = first.post_wp.as_formula().clone();
    let mut components = vec![first.cid.clone()];
    for edge in iter {
        q = edge.post_wp.as_formula().clone();
        components.push(edge.cid.clone());
    }
    // Re-walk from the first to set p correctly (already set above; kept
    // for clarity in the loop structure).
    let _ = &mut p;
    compose_components(&first.pre_wp.as_formula().clone(), &q, components)
}

fn compose_components(
    p: &sugar_ir_types::IrFormula,
    q: &sugar_ir_types::IrFormula,
    component_cids: Vec<String>,
) -> ComposedEdge {
    let component_values: Vec<Arc<Value>> = component_cids
        .iter()
        .map(|c| Value::string(c.clone()))
        .collect();
    let value = Value::object([
        ("schemaVersion", Value::string("1")),
        ("kind", Value::string("composed-edge")),
        ("p", formula_to_canonical(p)),
        ("q", formula_to_canonical(q)),
        ("components", Value::array(component_values)),
    ]);
    let canonical_bytes = jcs_bytes_of_value(&value);
    let cid = cid_of_value(&value);
    ComposedEdge {
        p: p.clone(),
        q: q.clone(),
        component_cids,
        canonical_bytes,
        cid,
    }
}

#[cfg(test)]
mod shadow_tests {
    use super::*;
    use crate::lift::lift_function_precondition;

    fn parse_fn_local(src: &str, name: &str) -> syn::ItemFn {
        let file: syn::File = syn::parse_str(src).unwrap();
        file.items
            .into_iter()
            .find_map(|item| match item {
                syn::Item::Fn(f) if f.sig.ident == name => Some(f),
                _ => None,
            })
            .unwrap_or_else(|| panic!("fn `{}` not found", name))
    }

    // Bug #4: two callsites to the same callee with identical argument expressions in the
    // same function must produce DISTINCT callsite-root arrival CIDs.
    #[test]
    fn duplicate_callsites_get_distinct_arrival_cids() {
        let src = r#"
            fn f(x: u32) -> u32 { if x < 10 { panic!(); } x * 2 }
            fn main() {
                let y: u32 = 42;
                let r1 = f(y);
                let r2 = f(y);
            }
        "#;
        let f_fn = parse_fn_local(src, "f");
        let main_fn = parse_fn_local(src, "main");
        let pre = lift_function_precondition(&f_fn);
        let s = build_shadow_source(
            &main_fn,
            &[CalleeContract {
                callee_name: "f".to_string(),
                formal_params: vec!["x".to_string()],
                precondition: pre,
            }],
        );
        let root_cids: Vec<String> = s
            .all_arrivals()
            .filter(|(_, a)| a.callee_root_cid == a.cid)
            .map(|(_, a)| a.cid.clone())
            .collect();
        assert!(
            root_cids.len() >= 2,
            "expected at least 2 callsite-root arrivals for two f() calls, got {}",
            root_cids.len()
        );
        let unique: std::collections::HashSet<&String> = root_cids.iter().collect();
        assert_eq!(
            unique.len(),
            root_cids.len(),
            "each callsite must produce a distinct callsite-root CID; got: {:?}",
            root_cids
        );
    }

    // Bug #3: bare Stmt::Expr callsites must be labelled `callsite:<callee>`.
    #[test]
    fn bare_expr_callsite_slot_gets_callsite_label() {
        let src = r#"
            fn f(x: u32) -> u32 { if x < 10 { panic!(); } x * 2 }
            fn main() {
                let y: u32 = 42;
                f(y);
            }
        "#;
        let f_fn = parse_fn_local(src, "f");
        let main_fn = parse_fn_local(src, "main");
        let pre = lift_function_precondition(&f_fn);
        let s = build_shadow_source(
            &main_fn,
            &[CalleeContract {
                callee_name: "f".to_string(),
                formal_params: vec!["x".to_string()],
                precondition: pre,
            }],
        );
        let has_callsite_label = s
            .slots
            .iter()
            .any(|slot| slot.source_kind_label == "callsite:f");
        assert!(
            has_callsite_label,
            "expected a slot with source_kind_label=callsite:f, got labels: {:?}",
            s.slots
                .iter()
                .map(|sl| &sl.source_kind_label)
                .collect::<Vec<_>>()
        );
    }

    // Bug #5: edge_memento_value must emit `kind: "contract"` with substrate-parser fields.
    #[test]
    fn edge_memento_emits_contract_shape() {
        let src = r#"
            fn f(x: u32) -> u32 { if x < 10 { panic!(); } x * 2 }
            fn main() { let y: u32 = 42; let result = f(y); }
        "#;
        let f_fn = parse_fn_local(src, "f");
        let main_fn = parse_fn_local(src, "main");
        let pre = lift_function_precondition(&f_fn);
        let s = build_shadow_source(
            &main_fn,
            &[CalleeContract {
                callee_name: "f".to_string(),
                formal_params: vec!["x".to_string()],
                precondition: pre,
            }],
        );
        for (_, arrival) in s.all_arrivals() {
            let bytes = jcs_bytes_of_value(&edge_memento_value(arrival));
            let parsed: serde_json::Value =
                serde_json::from_slice(&bytes).expect("valid JSON from edge_memento_value");
            assert_eq!(
                parsed["kind"].as_str(),
                Some("contract"),
                "must emit kind:contract"
            );
            assert_eq!(
                parsed["schemaVersion"].as_str(),
                Some("2"),
                "must emit schemaVersion:2"
            );
            assert!(parsed["name"].is_string(), "must include name field");
            assert!(
                parsed["outBinding"].is_string(),
                "must include outBinding field"
            );
            assert!(!parsed["pre"].is_null(), "must include pre field");
            assert!(!parsed["post"].is_null(), "must include post field");
            assert!(!parsed["evidence"].is_null(), "must include evidence field");
        }
    }
}

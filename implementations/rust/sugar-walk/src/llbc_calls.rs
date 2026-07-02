// SPDX-License-Identifier: Apache-2.0
//
// LLBC callsite composition (#383, Tier 1.1). The keystone unlock for
// non-leaf compositions. Without it, only leaf functions (no calls)
// fully lift; with it, every call site at a function boundary
// substitutes the callee's precondition into the caller's, so paper
// 07 §6's "compose for free" works at the substrate level.
//
// The composition is mechanical:
//   At each `StatementKind::Call(call)` in the caller's body:
//     1. Resolve the FunDeclId in `call.func.Regular.kind.Fun.Regular`
//        to the callee's name (the trailing Ident in its
//        item_meta.name path).
//     2. Look up the callee in the ContractRegistry.
//     3. Lift each actual arg via `operand_to_ir_term`.
//     4. For each (formal_name, actual_term) pair, capture-avoiding
//        substitute formal_name -> actual_term in the callee's pre
//        (using `wp::substitute_in_formula` we already built for the
//        AST walk).
//     5. Push the substituted pre into the caller's pre contributions.
//
// Unresolved callees (cross-crate, dyn dispatch, FFI, callee not in
// registry) are skipped silently. Future work: emit
// `Effect::UnresolvedCall { name }` so the substrate refuses to
// compose against them rather than implicitly assuming `true`.

use std::collections::HashMap;

use serde_json::Value;

use sugar_ir_types::{IrFormula, IrTerm};

use crate::contract::FunctionContractMemento;
use crate::llbc::{LlbcCrate, LlbcError};
use crate::wp;

/// Map from function name (the trailing Ident in the path) to its
/// already-lifted contract memento. Used for callsite composition:
/// when the lifter sees a Call to `f`, it looks up f's contract and
/// substitutes actuals for formals in f's pre.
pub type ContractRegistry = HashMap<String, FunctionContractMemento>;

/// Empty registry -- used by entry points that don't need callsite
/// composition (e.g., legacy `lift_llbc_function` callers).
pub fn empty_registry() -> ContractRegistry {
    ContractRegistry::new()
}

/// Lift every function in the crate using a fix-point loop (Task C, #383).
///
/// Runs up to MAX_LIFT_PASSES until the set of contract CIDs stabilizes.
/// This handles forward references and mutual recursion: if `outer` appears
/// before `inner` in `fun_decls`, the first pass lifts `outer` without seeing
/// `inner`'s contract; the second pass re-lifts `outer` with the now-populated
/// registry and picks up the composition. Functions that are truly recursive
/// and never stabilize settle at the last computed contract after
/// MAX_LIFT_PASSES.
///
/// `source_path` is annotated into each contract's locus.
const MAX_LIFT_PASSES: usize = 10;

pub fn lift_llbc_crate(
    krate: &LlbcCrate,
    source_path: Option<&str>,
) -> Result<ContractRegistry, LlbcError> {
    let type_decls = krate.type_decls_raw();
    let fun_decls_raw = fun_decls_array(krate);

    let mut registry = ContractRegistry::new();

    for _pass in 0..MAX_LIFT_PASSES {
        let mut new_registry = ContractRegistry::new();

        for f in krate.fun_decls() {
            let Some(name) = f.fn_name() else {
                continue;
            };
            match crate::llbc_lift::lift_llbc_function_with_registry(
                f,
                source_path,
                type_decls,
                fun_decls_raw,
                &registry,
            ) {
                Ok(contract) => {
                    new_registry.insert(name, contract);
                }
                Err(_) => {
                    // Skip non-structured bodies (extern, intrinsic, trait method).
                }
            }
        }

        // Stable when every function has the same CID as the prior pass.
        let stable = new_registry.len() == registry.len()
            && new_registry.iter().all(|(name, contract)| {
                registry
                    .get(name)
                    .is_some_and(|prev| prev.cid == contract.cid)
            });

        registry = new_registry;

        if stable {
            break;
        }
    }

    Ok(registry)
}

/// Get the raw `fun_decls` array from a crate. Returned as `Option`
/// because foreign / minimal crates may omit it.
pub fn fun_decls_array(krate: &LlbcCrate) -> Option<&Value> {
    let translated = krate.raw_translated()?;
    translated.get("fun_decls")
}

/// Look up a function declaration by its `def_id` (FunDeclId) in the
/// crate's fun_decls table and return ALL Ident segments of its
/// item_meta.name path in order (left-to-right). For example, a
/// function at `core::sync::atomic::AtomicU32::fetch_add` yields
/// `["core", "sync", "atomic", "AtomicU32", "fetch_add"]`. `None` if
/// the decl is not found or the name path is empty.
pub fn fundecl_path_segments_by_id(fun_decls: &Value, id: u64) -> Option<Vec<String>> {
    let arr = fun_decls.as_array()?;
    let decl = arr
        .iter()
        .find(|d| d.get("def_id").and_then(|v| v.as_u64()) == Some(id))?;
    let elems = decl.get("item_meta")?.get("name")?.as_array()?;
    let segs: Vec<String> = elems
        .iter()
        .filter_map(|e| {
            let ident = e.get("Ident")?.as_array()?;
            ident.first()?.as_str().map(|s| s.to_string())
        })
        .collect();
    if segs.is_empty() {
        None
    } else {
        Some(segs)
    }
}

/// Map from method name suffix to `AtomicKind`. Returns `None` if the
/// method is not a recognised atomic operation.
///
/// Recognised prefixes / exact names:
///   load                        → Load
///   store                       → Store
///   compare_exchange{,_weak},
///   compare_and_swap            → Cas
///   fetch_*, swap               → Rmw
pub fn atomic_kind_for_method(method: &str) -> Option<crate::contract::AtomicKind> {
    use crate::contract::AtomicKind;
    match method {
        "load" => Some(AtomicKind::Load),
        "store" => Some(AtomicKind::Store),
        "compare_exchange" | "compare_exchange_weak" | "compare_and_swap" => Some(AtomicKind::Cas),
        m if m.starts_with("fetch_") || m == "swap" => Some(AtomicKind::Rmw),
        _ => None,
    }
}

/// Return `Some((AtomicKind, type_name))` when `func_id` resolves to a
/// call on one of the `core::sync::atomic::Atomic*` types, where
/// `type_name` is the `Atomic*` struct name (e.g. `"AtomicU32"`).
/// Returns `None` if the call is not an atomic intrinsic.
pub fn detect_atomic_call(
    fun_decls: &Value,
    func_id: u64,
) -> Option<(crate::contract::AtomicKind, String)> {
    let segs = fundecl_path_segments_by_id(fun_decls, func_id)?;
    // Expected shape: [..., "core", "sync", "atomic", "AtomicXxx", method]
    // We require at least 5 segments and the Atomic* type to start with "Atomic".
    if segs.len() < 5 {
        return None;
    }
    let n = segs.len();
    let method = &segs[n - 1];
    let type_name = &segs[n - 2];
    let ns_a = &segs[n - 3]; // "atomic"
    let ns_b = &segs[n - 4]; // "sync"
    let ns_c = &segs[n - 5]; // "core"
    if ns_c != "core" || ns_b != "sync" || ns_a != "atomic" {
        return None;
    }
    if !type_name.starts_with("Atomic") {
        return None;
    }
    let kind = atomic_kind_for_method(method)?;
    Some((kind, type_name.clone()))
}

/// Look up a function declaration by its `def_id` (FunDeclId) in the
/// crate's fun_decls table and return the trailing `Ident` of its
/// item_meta.name path. `None` if not found or path is malformed.
pub fn fundecl_name_by_id(fun_decls: &Value, id: u64) -> Option<String> {
    let arr = fun_decls.as_array()?;
    let decl = arr
        .iter()
        .find(|d| d.get("def_id").and_then(|v| v.as_u64()) == Some(id))?;
    let elems = decl.get("item_meta")?.get("name")?.as_array()?;
    elems.iter().rev().find_map(|e| {
        let ident = e.get("Ident")?.as_array()?;
        ident.first()?.as_str().map(|s| s.to_string())
    })
}

/// Extract the FunDeclId and the args operands from a Call statement.
/// Returns `None` for non-Call statements or for Call kinds we don't
/// resolve (FnPtr, dyn dispatch, closure invocation).
///
/// # Trait method dispatch (Task A investigation -- #383)
///
/// Charon resolves monomorphic trait method calls to `Fun.Regular = <FunDeclId>`
/// when the concrete impl is statically known at the call site. For example,
/// `s.m()` where `s: &S` and `S: T` produces `kind.Fun.Regular = <impl_m_id>` --
/// the same JSON shape as a direct function call. `fundecl_name_by_id` then
/// looks up the impl's trailing Ident name from `fun_decls`.
///
/// Dynamic dispatch (`dyn T`) uses a different encoding (not `Fun.Regular`) and
/// is not yet supported -- calls through `dyn` trait objects are skipped silently
/// by this function returning `None`.
pub fn extract_call_target(stmt: &Value) -> Option<(u64, Vec<&Value>)> {
    let call = stmt.get("kind")?.get("Call")?;
    let func = call.get("func")?;
    let regular = func.get("Regular")?;
    let kind = regular.get("kind")?;
    let fun = kind.get("Fun")?;
    let func_id = fun.get("Regular")?.as_u64()?;
    let args_arr = call.get("args")?.as_array()?;
    let args: Vec<&Value> = args_arr.iter().collect();
    Some((func_id, args))
}

/// Extract the destination local index from a Call statement's `dest` field.
/// Returns `Some(local_id)` when the call's return value is assigned to a named
/// local (including _0, the return-value slot). Returns `None` if not a Call
/// statement or the dest is a complex place (projection).
///
/// Used by `derive_return_equation` in `llbc_lift.rs` to detect the pattern
/// `Call(callee, args, dest: _0)` where the function's return value is set
/// by a Call rather than an Assign (Task B, #383).
pub fn call_dest_local(stmt: &Value) -> Option<u32> {
    let call = stmt.get("kind")?.get("Call")?;
    let dest = call.get("dest")?;
    dest.get("kind")?.get("Local")?.as_u64().map(|n| n as u32)
}

/// Substitute actuals for formals in the callee's pre. The callee's
/// formal names are the keys; the actuals are the corresponding lifted
/// IrTerms in the same positional order. Capture-avoiding substitution
/// is the default semantics of `wp::substitute_in_formula`.
pub fn compose_callsite_pre(callee: &FunctionContractMemento, arg_terms: &[IrTerm]) -> IrFormula {
    let mut substituted = callee.pre.clone();
    for (formal_name, actual_term) in callee.formals.iter().zip(arg_terms.iter()) {
        substituted = wp::substitute_in_formula(substituted, formal_name, actual_term);
    }
    substituted
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture_path(name: &str) -> std::path::PathBuf {
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests")
            .join("fixtures")
            .join(name)
    }

    #[test]
    fn lift_llbc_crate_builds_registry_for_calls_fixture() {
        // The calls fixture has two functions:
        //   fn inner(y: u32) -> u32 { if y < 5 { panic!(); } y }
        //   fn outer(x: u32) -> u32 { inner(x) }
        // After full-crate lift:
        //   inner.pre = (y >= 5)
        //   outer.pre = (x >= 5)   -- inner's pre with y -> x substituted
        let krate = LlbcCrate::from_path(fixture_path("calls.llbc")).unwrap();
        let registry = lift_llbc_crate(&krate, Some("calls.rs")).unwrap();

        let inner = registry.get("inner").expect("inner lifted");
        assert_eq!(inner.formals, vec!["y".to_string()]);
        let inner_pre_str = serde_json::to_string(&inner.pre).unwrap();
        assert!(
            inner_pre_str.contains("\"y\""),
            "inner's pre references y: {}",
            inner_pre_str
        );

        let outer = registry.get("outer").expect("outer lifted");
        assert_eq!(outer.formals, vec!["x".to_string()]);
        let outer_pre_str = serde_json::to_string(&outer.pre).unwrap();
        // The substrate keystone: outer's pre carries the SUBSTITUTED
        // inner.pre -- `y -> x`. So outer.pre references x (not y).
        assert!(
            outer_pre_str.contains("\"x\""),
            "outer's pre references x (after composition): {}",
            outer_pre_str
        );
        assert!(
            !outer_pre_str.contains("\"y\""),
            "outer's pre must NOT reference y (formal substituted away): {}",
            outer_pre_str
        );
        // The predicate is >= 5 -- same atom as inner's pre.
        assert!(
            outer_pre_str.contains("\"\\u2265\"") || outer_pre_str.contains("\u{2265}"),
            "outer's pre has the >= predicate: {}",
            outer_pre_str
        );
    }

    #[test]
    fn compose_callsite_pre_substitutes_formal_to_actual() {
        // Direct unit test on the composition primitive. Build a
        // synthetic callee with pre = (y >= 5), substitute y -> Var("x"),
        // assert the result is (x >= 5).
        use crate::contract::{EffectSet, FunctionContractMemento};
        use crate::locus::Locus;
        use crate::wp::{atomic_ge, const_int, var};
        use sugar_ir_types::Sort;

        let pre = atomic_ge(var("y"), const_int(5)).into_formula();
        let post = pre.clone();
        let callee = FunctionContractMemento {
            fn_name: "inner".into(),
            formals: vec!["y".into()],
            formal_sorts: vec![Sort::Primitive { name: "Int".into() }],
            formal_regions: vec![],
            return_sort: Sort::Primitive { name: "Int".into() },
            return_region: None,
            pre,
            post,
            body_cid: None,
            effects: EffectSet::empty(),
            locus: Locus::unknown(),
            canonical_bytes: vec![],
            cid: String::new(),
            auto_minted_mementos: vec![],
            panic_loci: vec![],
            concept_hint: None,
        };
        let composed = compose_callsite_pre(&callee, &[var("x")]);
        // Should be (x >= 5).
        let s = serde_json::to_string(&composed).unwrap();
        assert!(s.contains("\"x\""));
        assert!(!s.contains("\"y\""));
    }

    // ---- Task B: Call-dest return-value derivation ----

    #[test]
    fn outer_post_references_call_inner() {
        // `fn outer(x: u32) -> u32 { inner(x) }` -- _0 is set by the
        // Call's dest, not by an Assign. After Task B, outer.post should
        // contain `result = Ctor("call:inner", [Var("x")])`.
        let krate = LlbcCrate::from_path(fixture_path("calls.llbc")).unwrap();
        let registry = lift_llbc_crate(&krate, Some("calls.rs")).unwrap();

        let outer = registry.get("outer").expect("outer lifted");
        let post_str = serde_json::to_string(&outer.post).unwrap();
        assert!(
            post_str.contains("call:inner"),
            "outer.post should reference call:inner: {}",
            post_str
        );
        assert!(
            post_str.contains("result"),
            "outer.post should have result = ...: {}",
            post_str
        );
    }

    // ---- Task C: Fix-point lift stability ----

    #[test]
    fn fixpoint_lift_is_stable_after_two_passes() {
        // The fixpoint fixture has inner + outer with inner using `y < 3`.
        // Run lift_llbc_crate (fix-point) and assert both contracts are
        // present and outer.pre references x (not y), proving the second
        // pass picked up inner's contract.
        let krate = LlbcCrate::from_path(fixture_path("fixpoint.llbc")).unwrap();
        let registry = lift_llbc_crate(&krate, Some("fixpoint.rs")).unwrap();

        let inner = registry.get("inner").expect("inner lifted");
        let inner_pre_str = serde_json::to_string(&inner.pre).unwrap();
        assert!(
            inner_pre_str.contains("\"y\""),
            "inner.pre references formal y: {}",
            inner_pre_str
        );

        let outer = registry.get("outer").expect("outer lifted after fix-point");
        let outer_pre_str = serde_json::to_string(&outer.pre).unwrap();
        assert!(
            outer_pre_str.contains("\"x\""),
            "outer.pre references x after fix-point composition: {}",
            outer_pre_str
        );

        // Fix-point stability: run again and check CIDs are identical.
        let registry2 = lift_llbc_crate(&krate, Some("fixpoint.rs")).unwrap();
        let outer2 = registry2.get("outer").expect("outer in second run");
        assert_eq!(
            outer.cid, outer2.cid,
            "outer.cid must be stable across runs"
        );
    }
}

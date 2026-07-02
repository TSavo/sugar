// SPDX-License-Identifier: Apache-2.0
//
// DRAFT — for review only. NOT wired into any verdict path.
//
// Purity/effect classifier for body-bearing callees.
//
// PURPOSE
// -------
// The verifier can refuse an obligation it cannot warrant when a stateful
// read (Cell::get, AtomicI32::load, UnsafeCell::get, etc.) is observed at
// two different program points with different pinned values — a "fork around
// t". To VINDICATE that refusal as a consistent trajectory (not a
// contradiction), we must be able to classify the callee as IMPURE: its
// result depends on hidden mutable state, so different values at different
// program points are expected. A PURE callee that forks would be a real
// contradiction (one pin is a lie).
//
// WP-RETURN SHAPES (mapped precisely from the existing machinery)
// ---------------------------------------------------------------
// `reduce_to_value_expr(call_json, callee_name, resolver)` runs:
//
//   wp(call, result == __sentinel, resolver)
//
// and extracts the LHS of the resulting `=(body_expr, __sentinel)`.
//
// (a) PURE body — `fn double(x) { x * 2 }`:
//     wp returns `Ok(=(*(x, 2), __sentinel))`.
//     body_expr = `*(x, 2)`.
//     free_vars(body_expr) = {"x"} ⊆ call's arg vars → PURE.
//
// (b) HIDDEN-STATE body — `fn get(cell: &Cell<i32>) -> i32 { cell.get() }`:
//     CRITICAL: the lifter's contract for `Cell::get` receives no body-derived
//     contract (the lifter refuses to model it as a value-op because it reads
//     through an interior-mutable reference). CatalogResolver::lookup("Cell::get")
//     returns None. wp returns Err(WpError::Refused(OpaqueCall { callee:
//     "Cell::get" })). The OUTER call `get(cell)` therefore:
//       - If `get` itself has no body contract → wp refuses with OpaqueCall
//         for `get` → Unknown (no body, no information).
//       - If `get` HAS a body contract whose body invokes `Cell::get` → wp
//         reduces through `get`'s body and hits `Cell::get`'s unresolved
//         inner call → wp refuses with OpaqueCall for "Cell::get" → the
//         body_expr cannot be extracted → Unknown.
//
//     THE IMPURE SIGNAL: a callee is IMPURE when its body contract IS present
//     (CatalogResolver returns Some) but that contract's post's value_expr
//     references a free variable NOT in the callee's formals — an "escaped"
//     name that represents a hidden read (e.g. a global, a captured mutable
//     reference, or a synthetic state symbol the lifter injected). This is the
//     only structural signal wp can provide without a separate effect model.
//
//     ALTERNATIVELY: the lifter explicitly marks the contract's post as
//     referencing a hidden-state symbol by a naming convention (e.g. a symbol
//     prefixed with `__state::` or `__hidden::`) — the classifier recognizes
//     this prefix.
//
// (c) UNRESOLVABLE callee — no bridge / no body contract in pool:
//     CatalogResolver::lookup returns None.
//     wp returns Err(WpError::Refused(OpaqueCall { callee: name })).
//     → Unknown (cannot classify without a body).
//
// CLASSIFIER DESIGN
// -----------------
// `callee_purity(call, resolver) -> Purity`:
//
//   1. Run reduce_to_value_expr (= wp with sentinel).
//      - Err(Refused) → Unknown (no body OR inner unresolved call).
//      - Err(other)   → Unknown (malformed contract; conservative).
//      - Ok(body_expr) → proceed to step 2.
//
//   2. Compute arg_vars = free variables of the call's argument terms.
//      (For a call `f(x, 3)` these are {"x"}; constants contribute nothing.)
//
//   3. Compute body_free = free_vars_term(body_expr) \ {sentinel}.
//      The sentinel ("__purity_sentinel") must be excluded — it is the
//      postcondition placeholder, not a user variable.
//
//   4. If body_free ⊆ arg_vars → Pure (body value depends only on args).
//
//   5. Check each name in (body_free \ arg_vars) for hidden-state markers:
//      - Prefixed "__state::" or "__hidden::" → Impure (lifter-explicit).
//      - Otherwise → Unknown (an unexpected free var; could be a lifter
//        artifact, a global constant, or a genuine hidden read — we cannot
//        distinguish without deeper analysis, so we refuse to classify).
//
// SOUNDNESS RULE (read before modifying)
// ---------------------------------------
// Wrong Impure → vindication of a real contradiction → falsePass.
// Wrong Pure   → conviction of a legitimate trajectory → false refusal.
// Unknown      → stays Refused → always safe.
//
// ONLY return Pure/Impure when the wp reduction UNAMBIGUOUSLY shows it.
// ANY ambiguity → Unknown.
//
// WHAT WP CANNOT PROVE
// --------------------
// wp operates purely on the WRITTEN body-derived contract. It does NOT:
//   - inspect raw Rust MIR or unsafe intrinsics
//   - distinguish `&T` from `&mut T` or `&Cell<T>`
//   - know about `UnsafeCell`, `AtomicI32`, raw pointer derefs
//   - propagate aliasing information
//
// The only mechanism for classifying a callee as Impure via this classifier
// is (a) the lifter leaves the callee without a body contract (→ Unknown, not
// Impure — we cannot claim impurity, only ignorance), or (b) the body contract
// carries a post whose value_expr has a free var with the explicit hidden-state
// naming prefix that the lifter injects when it CAN model the read (e.g. for
// atomic loads whose value at each program point is given a fresh logical name).
//
// For `Cell::get` / `UnsafeCell::get` / most unsafe reads in practice: the
// lifter refuses to emit a body contract for these (they are opaque to static
// analysis). The classifier returns Unknown. The verifier stays Refused. That
// is the correct posture: we cannot vindicate OR convict without more evidence.

use std::collections::HashSet;

use serde_json::Value as Json;
use sugar_ir_types::IrTerm;

use libsugar::wp::{self, free_vars_term, WpError};
use sugar_ir_types::IrFormula;

use crate::body_discharge::CatalogResolver;
use crate::types::{MementoCid, MementoPool};
use libsugar::core::types::Term;

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/// Purity classification for a body-bearing callee.
///
/// Conservative by design: Pure and Impure are only returned when the wp
/// reduction provides unambiguous structural evidence. Any ambiguity → Unknown.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Purity {
    /// The callee's result depends ONLY on its explicit arguments.
    /// wp reduced the body to a value expression whose free variables ⊆
    /// the set of argument variable names.
    Pure,
    /// The callee's result depends on hidden mutable state.
    /// wp reduced the body to a value expression that references a
    /// hidden-state symbol (a name carrying the `__state::` or
    /// `__hidden::` prefix injected by the lifter).
    Impure,
    /// Cannot be classified.
    /// Causes: no body contract, inner unresolved call, unexpected free
    /// variable that cannot be attributed to either pure args or explicit
    /// hidden-state markers.
    Unknown,
}

// ---------------------------------------------------------------------------
// The sentinel variable — must not collide with any user formula symbol.
// Must be the same as used in reduce_to_value_expr (body_discharge.rs)
// so the sentinel exclusion in step 3 is precise.
// ---------------------------------------------------------------------------
const PURITY_SENTINEL: &str = "__purity_sentinel";

/// Hidden-state name prefixes the lifter injects when it CAN model a mutable
/// read as a logical name. Only these exact prefixes yield Impure; anything
/// else is Unknown.
const HIDDEN_STATE_PREFIXES: &[&str] = &["__state::", "__hidden::"];

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/// True iff the contract body targeted by the bridge for `callee_name` carries
/// a non-trivial `pre` field (i.e. a precondition that is not null, not absent,
/// and not the literal-true atomic `{kind:"atomic",name:"true"}`).
///
/// WHY THIS MATTERS: CatalogResolver::lookup constructs OpContractInfo from the
/// contract body's `formals` + `post` only — it does NOT read `pre`. So wp's
/// synthesized rule ignores any precondition. A pre-bearing callee (e.g. `unwrap`)
/// would silently appear Pure to the classifier unless we check here first.
///
/// This mirrors `pre_is_trivial` in body_discharge.rs (same structural check).
fn contract_body_has_nontrivial_pre(callee_name: &str, pool: &MementoPool) -> bool {
    // Walk the same path CatalogResolver::target_contract_body walks:
    //   bridge(callee_name) -> targetContractCid -> memento -> body -> pre
    let bridge = match pool.bridge_member_for_symbol(callee_name) {
        Some(b) => b,
        None => return false, // no bridge → no body contract → wp will refuse
    };
    let target_cid = bridge.field("targetContractCid").and_then(|v| v.as_str());
    let target_cid = match target_cid {
        Some(c) => match MementoCid::try_parse(c.to_string()) {
            Ok(cid) => cid,
            Err(_) => return false,
        },
        None => return false,
    };
    let Some(body) = pool.contract_body_by_cid(&target_cid) else {
        return false;
    };
    match body.get("pre") {
        None => false,
        Some(pre) if pre.is_null() => false,
        Some(pre) => {
            // Non-trivial = not the literal-true atomic.
            !(pre.get("kind").and_then(|v| v.as_str()) == Some("atomic")
                && pre.get("name").and_then(|v| v.as_str()) == Some("true"))
        }
    }
}

// ---------------------------------------------------------------------------
// Classifier
// ---------------------------------------------------------------------------

/// Classify the purity of a body-bearing callee.
///
/// `call_json` must be a JSON object with `kind: "ctor"` (a harvested call
/// term). `pool` is the memento pool the CatalogResolver is built from.
///
/// Returns:
/// - `Pure`    — body value depends only on the call's argument variables.
/// - `Impure`  — body value references an explicit hidden-state symbol.
/// - `Unknown` — no body contract, inner unresolved call, or ambiguous free
///               variable (not arg, not explicit hidden-state marker).
///
/// NEVER returns Pure or Impure when there is any doubt. Ambiguity → Unknown.
pub fn callee_purity(call_json: &Json, pool: &MementoPool) -> Purity {
    // Step 0: extract the callee name (for the resolver and arg extraction).
    let callee_name = match call_json.get("name").and_then(|v| v.as_str()) {
        Some(n) => n,
        None => return Purity::Unknown,
    };

    // Step 0b: CONSERVATIVE PRE-CHECK — if the contract body carries a
    // non-trivial `pre`, CatalogResolver does NOT thread it into OpContractInfo,
    // so wp's synthesized rule silently drops the precondition. We would
    // incorrectly classify a pre-bearing callee as Pure (wp still returns a
    // clean `=(body_expr, sentinel)` shape). Guard here before calling wp:
    // look up the contract body directly and refuse to classify if `pre` is
    // present and non-trivial.
    if contract_body_has_nontrivial_pre(callee_name, pool) {
        return Purity::Unknown;
    }

    // Step 1: deserialize call and collect argument variable names.
    let call_ir: IrTerm = match serde_json::from_value(call_json.clone()) {
        Ok(t) => t,
        Err(_) => return Purity::Unknown,
    };

    // Collect the set of variable names appearing FREE in the call's
    // explicit argument terms. For `f(x, 3)` this is {"x"}.
    let arg_vars: HashSet<String> = {
        let args = match &call_ir {
            IrTerm::Ctor { args, .. } => args.as_slice(),
            _ => return Purity::Unknown, // not a ctor — refuse to classify
        };
        let mut vars = HashSet::new();
        for arg in args {
            vars.extend(free_vars_term(arg));
        }
        vars
    };

    // Step 1b: convert to Term for wp.
    let call_term: Term = call_ir.into();
    if !matches!(call_term, Term::Op { .. }) {
        return Purity::Unknown;
    }

    // Step 2: run wp(call, result == __purity_sentinel, resolver).
    let resolver = CatalogResolver::new(pool);

    let q = IrFormula::Atomic {
        name: "=".to_string(),
        args: vec![
            IrTerm::Var {
                name: "result".to_string(),
            },
            IrTerm::Var {
                name: PURITY_SENTINEL.to_string(),
            },
        ],
    };

    let reduced = match wp::wp(&call_term, &q, &resolver) {
        Ok(f) => f,
        // Refused = no body contract or inner unresolved call → Unknown.
        Err(WpError::Refused(_)) => return Purity::Unknown,
        // Other wp errors = malformed contract (arity mismatch, no rule) → Unknown.
        Err(_) => return Purity::Unknown,
    };

    // Step 3: extract body_expr from `=(body_expr, __purity_sentinel)`.
    // wp(call, result==sentinel) must produce exactly this shape.
    let body_expr: IrTerm = match reduced {
        IrFormula::Atomic { name, mut args } if name == "=" && args.len() == 2 => {
            // args[0] = body_expr(call.args), args[1] = sentinel.
            // Confirm args[1] IS the sentinel before trusting args[0].
            let is_sentinel = matches!(&args[1], IrTerm::Var { name } if name == PURITY_SENTINEL);
            if !is_sentinel {
                // Unexpected shape — wp may have simplified the sentinel away.
                // We cannot trust which side is the body_expr → Unknown.
                return Purity::Unknown;
            }
            args.swap_remove(0)
        }
        _ => {
            // wp produced a shape we don't recognise (e.g. And { pre ∧ ... }
            // when the contract has a non-trivial pre). Cannot extract
            // body_expr cleanly → Unknown.
            //
            // NOTE: a contract with a non-trivial `pre` (e.g. `unwrap`)
            // produces `And { operands: [pre_formula, =(body_expr, sentinel)] }`.
            // Classifying that as Pure would be wrong because the pre check
            // guards the value; we cannot drop it silently. Unknown is correct.
            return Purity::Unknown;
        }
    };

    // Step 4: compute free variables of body_expr, excluding the sentinel.
    let body_free: HashSet<String> = {
        let mut fv = free_vars_term(&body_expr);
        fv.remove(PURITY_SENTINEL);
        fv
    };

    // Step 5: classify.
    let extra_free: Vec<&String> = body_free.difference(&arg_vars).collect();

    if extra_free.is_empty() {
        // Every free variable in the body_expr is an explicit call argument.
        return Purity::Pure;
    }

    // Check each extra free variable for an explicit hidden-state prefix.
    // If ALL extra vars carry a known prefix → Impure (unambiguous).
    // If ANY extra var lacks a known prefix → Unknown (could be anything).
    let all_hidden = extra_free.iter().all(|name| {
        HIDDEN_STATE_PREFIXES
            .iter()
            .any(|pfx| name.starts_with(pfx))
    });

    if all_hidden {
        Purity::Impure
    } else {
        // An extra free var that is neither an arg nor an explicit
        // hidden-state symbol: ambiguous. Could be a lifter artifact,
        // an unbound formal in a malformed contract, or a genuine hidden
        // read without a prefix. Conservative posture → Unknown.
        Purity::Unknown
    }
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------
//
// These tests are self-contained. They build MementoPool fixtures using the
// same pattern as `double_pool()` in body_discharge.rs (same JSON shape),
// and call `callee_purity` directly.
//
// Three tests per behavior:
//   POSITIVE      — the classifier returns the expected variant
//   DISCRIMINATION — a closely related input returns a DIFFERENT variant
//   STRUCTURAL    — a structurally broken/absent input returns Unknown

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::MementoPool;
    use serde_json::json;

    // -----------------------------------------------------------------------
    // Fixture helpers (mirror the body_discharge.rs pattern exactly)
    // -----------------------------------------------------------------------

    fn int_const(n: i64) -> Json {
        json!({"kind": "const", "value": n, "sort": {"kind": "primitive", "name": "Int"}})
    }

    fn var_term(name: &str) -> Json {
        json!({"kind": "var", "name": name})
    }

    fn cid(seed: &str) -> MementoCid {
        MementoCid::try_parse(sugar_canonicalizer::blake3_512_of(seed.as_bytes()))
            .expect("test CID must parse")
    }

    fn cid_string(seed: &str) -> String {
        cid(seed).to_string()
    }

    /// Build a pool with a single body-derived contract for `fn double(x) = x*2`.
    /// This is a PURE function: body_expr = `*(x, 2)`, free_vars = {"x"} = arg_vars.
    fn double_pool() -> MementoPool {
        let target_cid = cid_string("double-pure");
        let contract_env = json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "formals": ["x"],
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "result"},
                            {"kind": "ctor", "name": "*", "args": [
                                {"kind": "var", "name": "x"},
                                {"kind": "const", "value": 2,
                                 "sort": {"kind": "primitive", "name": "Int"}}
                            ]}
                        ]
                    }
                }
            }
        });
        let bridge_env = json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": "double",
                    "targetContractCid": target_cid
                }
            }
        });
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(cid("double-pure"), contract_env);
        pool.insert_bridge_by_symbol("double", cid("double-bridge"), bridge_env);
        pool
    }

    /// Build a pool for an IMPURE function `fn cell_get() -> i32` whose body
    /// contract's post references `__state::cell_value` (a hidden-state symbol
    /// injected by the lifter). This simulates a `Cell<i32>::get` lift where
    /// the lifter models the cell's current value as a logical state variable.
    ///
    /// Contract: `post: result == __state::cell_value`, formals: [] (no args).
    /// body_expr = `__state::cell_value`, free_vars = {"__state::cell_value"}.
    /// arg_vars = {} (no arguments).
    /// extra_free = {"__state::cell_value"} — all carry `__state::` prefix.
    /// → Impure.
    fn cell_get_pool() -> MementoPool {
        let target_cid = cid_string("cell-get-impure");
        let contract_env = json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "formals": [],
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "result"},
                            {"kind": "var", "name": "__state::cell_value"}
                        ]
                    }
                }
            }
        });
        let bridge_env = json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": "cell_get",
                    "targetContractCid": target_cid
                }
            }
        });
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(cid("cell-get-impure"), contract_env);
        pool.insert_bridge_by_symbol("cell_get", cid("cell-get-bridge"), bridge_env);
        pool
    }

    /// Build a pool for a function whose body contract's post references an
    /// UNEXPECTED extra free variable (not an arg, not a `__state::` prefix).
    /// This is the "ambiguous extra free var" case → Unknown.
    ///
    /// `fn mystery(x) = x + global_constant` where `global_constant` is not
    /// an arg and not prefixed with a known hidden-state marker.
    fn mystery_pool() -> MementoPool {
        let target_cid = cid_string("mystery-unknown");
        let contract_env = json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "formals": ["x"],
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "result"},
                            {"kind": "ctor", "name": "+", "args": [
                                {"kind": "var", "name": "x"},
                                {"kind": "var", "name": "global_constant"}
                            ]}
                        ]
                    }
                }
            }
        });
        let bridge_env = json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": "mystery",
                    "targetContractCid": target_cid
                }
            }
        });
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(cid("mystery-unknown"), contract_env);
        pool.insert_bridge_by_symbol("mystery", cid("mystery-bridge"), bridge_env);
        pool
    }

    // -----------------------------------------------------------------------
    // Helper to build a call JSON
    // -----------------------------------------------------------------------

    fn call(name: &str, args: Vec<Json>) -> Json {
        json!({"kind": "ctor", "name": name, "args": args})
    }

    // -----------------------------------------------------------------------
    // PURE: double(x) = x * 2
    // -----------------------------------------------------------------------

    /// POSITIVE: double(var_x) → Pure. body_expr = *(var_x, 2), free_vars =
    /// {"x"} = arg_vars = {"x"}.
    #[test]
    fn positive_pure_double_var_arg() {
        let pool = double_pool();
        let c = call("double", vec![var_term("x")]);
        assert_eq!(
            callee_purity(&c, &pool),
            Purity::Pure,
            "double(x) with var arg must classify Pure"
        );
    }

    /// DISCRIMINATION: double(3) (constant arg) → Pure. body_expr = *(3, 2),
    /// free_vars = {} ⊆ arg_vars = {} (no free vars in a const arg).
    #[test]
    fn discrimination_pure_double_const_arg() {
        let pool = double_pool();
        let c = call("double", vec![int_const(3)]);
        assert_eq!(
            callee_purity(&c, &pool),
            Purity::Pure,
            "double(3) with const arg must classify Pure (body_expr *(3,2) has no free vars)"
        );
    }

    /// STRUCTURAL: double with no body contract in pool → Unknown.
    #[test]
    fn structural_pure_no_bridge_in_pool() {
        // Empty pool — no bridge for "double" → resolver returns None → wp refuses.
        let pool = MementoPool::default();
        let c = call("double", vec![var_term("x")]);
        assert_eq!(
            callee_purity(&c, &pool),
            Purity::Unknown,
            "double with no bridge/contract must be Unknown, not Pure"
        );
    }

    // -----------------------------------------------------------------------
    // IMPURE: cell_get() → __state::cell_value
    // -----------------------------------------------------------------------

    /// POSITIVE: cell_get() → Impure. body_expr = __state::cell_value (a Var),
    /// free_vars = {"__state::cell_value"} \ arg_vars {} = {"__state::cell_value"},
    /// all carry the `__state::` prefix → Impure.
    #[test]
    fn positive_impure_cell_get_no_args() {
        let pool = cell_get_pool();
        let c = call("cell_get", vec![]);
        assert_eq!(
            callee_purity(&c, &pool),
            Purity::Impure,
            "cell_get() whose post references __state::cell_value must classify Impure"
        );
    }

    /// DISCRIMINATION: double(x) in double_pool does NOT classify Impure.
    /// (Ensures the classifier is not returning Impure for everything.)
    #[test]
    fn discrimination_impure_different_callee_is_pure() {
        let pool = double_pool();
        let c = call("double", vec![var_term("x")]);
        assert_ne!(
            callee_purity(&c, &pool),
            Purity::Impure,
            "double must NOT classify Impure"
        );
    }

    /// STRUCTURAL: a callee with `__state::` name but NO bridge/contract → Unknown.
    /// (The prefix alone doesn't make a callee Impure; the body contract must
    /// produce that free var through wp reduction.)
    #[test]
    fn structural_impure_no_bridge_is_unknown() {
        let pool = MementoPool::default(); // no bridges
        let c = call("cell_get", vec![]);
        assert_eq!(
            callee_purity(&c, &pool),
            Purity::Unknown,
            "cell_get with no bridge must be Unknown even if we know it's impure conceptually"
        );
    }

    // -----------------------------------------------------------------------
    // UNKNOWN: various cases
    // -----------------------------------------------------------------------

    /// POSITIVE (Unknown): mystery(x) → body references "global_constant", a
    /// free var that is neither an arg nor a `__state::` prefix → Unknown.
    #[test]
    fn positive_unknown_ambiguous_free_var() {
        let pool = mystery_pool();
        let c = call("mystery", vec![var_term("x")]);
        assert_eq!(
            callee_purity(&c, &pool),
            Purity::Unknown,
            "mystery(x) with unexpected free var 'global_constant' must be Unknown"
        );
    }

    /// DISCRIMINATION (Unknown): mystery(x) must NOT be Pure (it has an extra
    /// free var) and must NOT be Impure (no `__state::` prefix).
    #[test]
    fn discrimination_unknown_neither_pure_nor_impure() {
        let pool = mystery_pool();
        let c = call("mystery", vec![var_term("x")]);
        let p = callee_purity(&c, &pool);
        assert_ne!(p, Purity::Pure, "mystery must not be Pure");
        assert_ne!(p, Purity::Impure, "mystery must not be Impure");
    }

    /// STRUCTURAL (Unknown): malformed call JSON (no `name` field) → Unknown.
    #[test]
    fn structural_unknown_malformed_call_json() {
        let pool = double_pool();
        let bad_call = json!({"kind": "ctor", "args": [int_const(3)]});
        // No "name" field → callee_name extraction fails → Unknown.
        assert_eq!(
            callee_purity(&bad_call, &pool),
            Purity::Unknown,
            "malformed call with no name field must be Unknown"
        );
    }

    /// STRUCTURAL (Unknown): call JSON is not a ctor (kind: "var") → Unknown.
    #[test]
    fn structural_unknown_non_ctor_call_json() {
        let pool = double_pool();
        let not_a_call = json!({"kind": "var", "name": "double"});
        assert_eq!(
            callee_purity(&not_a_call, &pool),
            Purity::Unknown,
            "a non-ctor JSON term must be Unknown"
        );
    }

    // -----------------------------------------------------------------------
    // BOUNDARY DOCUMENTATION TESTS
    // -----------------------------------------------------------------------
    //
    // These tests document the exact boundary between what wp can prove and
    // what it cannot. They do NOT assert Impure for cases where the lifter
    // has NOT emitted a `__state::` symbol — those stay Unknown.

    /// BOUNDARY: a callee whose lifter left it WITHOUT a body contract (e.g.
    /// the real Cell::get in a production pool) classifies Unknown, NOT Impure.
    ///
    /// Rationale: absence of a body contract is "I don't know," not "impure."
    /// The classifier requires a positive signal (explicit `__state::` symbol
    /// in the reduced body_expr) to return Impure.
    #[test]
    fn boundary_no_body_contract_is_unknown_not_impure() {
        let pool = MementoPool::default(); // real Cell::get has no body contract
        let c = call("UnsafeCell::get", vec![var_term("ptr")]);
        assert_eq!(
            callee_purity(&c, &pool),
            Purity::Unknown,
            "UnsafeCell::get with no body contract must be Unknown, never Impure"
        );
    }

    /// BOUNDARY: a contract whose post has a non-trivial `pre` (AND shape)
    /// causes the wp output to be `And { pre, =(body_expr, sentinel) }`, which
    /// the classifier cannot decompose safely → Unknown.
    ///
    /// Concretely: `fn unwrap(opt) = opt.value where is_some(opt)` produces
    /// `wp(unwrap(x), result==s) = is_some(x) ∧ (x.value == s)`.
    /// We cannot drop the `is_some(x)` guard and claim `x.value` is the body
    /// expression unconditionally → Unknown is correct.
    #[test]
    fn boundary_pre_bearing_contract_is_unknown() {
        // Build a pool with a contract that carries a `pre`.
        let target_cid = cid_string("unwrap-pre-bearing");
        let contract_env = json!({
            "evidence": {
                "kind": "contract",
                "body": {
                    "formals": ["opt"],
                    "pre": {
                        "kind": "atomic",
                        "name": "is_some",
                        "args": [{"kind": "var", "name": "opt"}]
                    },
                    "post": {
                        "kind": "atomic",
                        "name": "=",
                        "args": [
                            {"kind": "var", "name": "result"},
                            {"kind": "ctor", "name": "Option::unwrap_value",
                             "args": [{"kind": "var", "name": "opt"}]}
                        ]
                    }
                }
            }
        });
        let bridge_env = json!({
            "evidence": {
                "kind": "bridge",
                "body": {
                    "sourceSymbol": "unwrap",
                    "targetContractCid": target_cid
                }
            }
        });
        let mut pool = MementoPool::default();
        pool.insert_unanchored_for_tests(cid("unwrap-pre-bearing"), contract_env);
        pool.insert_bridge_by_symbol("unwrap", cid("unwrap-bridge"), bridge_env);

        let c = call("unwrap", vec![var_term("opt")]);
        // wp produces And { is_some(opt), =(Option::unwrap_value(opt), sentinel) }.
        // The classifier cannot extract body_expr from the And shape → Unknown.
        assert_eq!(
            callee_purity(&c, &pool),
            Purity::Unknown,
            "pre-bearing contract must be Unknown (cannot drop the pre guard)"
        );
    }
}

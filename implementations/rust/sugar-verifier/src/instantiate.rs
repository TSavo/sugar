// SPDX-License-Identifier: Apache-2.0
//
// Stage 4: instantiate. Substitute the call's arg term for the
// resolved forall's bound variable. Flat quantifier shape: the
// resolved formula is expected to be `{kind:"forall", name, sort, body}`;
// we substitute `arg_term` for `name` in `body`.
//
// Mirrors .../verifier/instantiate.cpp.

use serde_json::{json, Value as Json};

use crate::types::{Obligation, ResolvedProperty};

pub fn run(resolved: &ResolvedProperty, arg_term: &Option<Json>) -> Result<Obligation, String> {
    let arg = arg_term.as_ref().ok_or("no argument term to substitute")?;
    let f = resolved
        .ir_formula
        .as_ref()
        .ok_or("resolved property has no ir_formula (no pre slot)")?;
    if f.get("kind").and_then(|v| v.as_str()) != Some("forall") {
        return Err("precondition formula is not a forall".into());
    }
    let var_name = f
        .get("name")
        .and_then(|v| v.as_str())
        .ok_or("forall has empty bound-variable name")?;
    let sort = f.get("sort").ok_or("forall has no sort")?.clone();
    let body = f.get("body").ok_or("forall has no body")?;
    let substituted_body = substitute_formula(body, var_name, arg);
    let forall_with_sort = json!({
        "kind": "forall",
        "name": var_name,
        "sort": sort,
        "body": substituted_body
    });
    Ok(Obligation {
        property_cid: resolved.cid.clone(),
        ir_kit_version: resolved.ir_kit_version.clone(),
        ir_formula: forall_with_sort,
    })
}

/// Specialize a target precondition to the concrete callsite actuals.
///
/// This is the value-level seam obligation used when the caller directly calls
/// a precondition-bearing target: substitute every target formal with the
/// corresponding bridged ctor argument and return the bare specialized
/// predicate. The legacy `run` API above intentionally preserves its quantified
/// wrapper for older single-formal paths; this helper is for actual callsite
/// discharge.
pub fn run_specialized(
    resolved: &ResolvedProperty,
    arg_terms: &[Json],
    formal_actuals: Option<&Json>,
) -> Result<Obligation, String> {
    let f = resolved
        .ir_formula
        .as_ref()
        .ok_or("resolved property has no ir_formula (no pre slot)")?;
    if f.get("kind").and_then(|v| v.as_str()) != Some("forall") {
        return Err("precondition formula is not a forall".into());
    }
    let fallback_name = f
        .get("name")
        .and_then(|v| v.as_str())
        .ok_or("forall has empty bound-variable name")?
        .to_string();
    let body = f.get("body").ok_or("forall has no body")?;
    let formal_names = if resolved.formal_names.is_empty() {
        vec![fallback_name]
    } else {
        resolved.formal_names.clone()
    };
    let mut substituted = body.clone();
    if let Some(formal_actuals) = formal_actuals {
        let bindings = formal_actuals
            .as_object()
            .ok_or("formalActuals must be an object mapping formal names to actual terms")?;
        for name in &formal_names {
            let actual = bindings
                .get(name)
                .ok_or_else(|| format!("formalActuals missing target formal `{name}`"))?;
            substituted = substitute_formula(&substituted, name, actual);
        }
    } else {
        if formal_names.len() > 1 {
            return Err(format!(
                "formalActuals required for multi-formal precondition: {} formals",
                formal_names.len()
            ));
        }
        if arg_terms.len() < formal_names.len() {
            return Err(format!(
                "not enough actual terms to specialize precondition: need {}, got {}",
                formal_names.len(),
                arg_terms.len()
            ));
        }
        for (name, actual) in formal_names.iter().zip(arg_terms.iter()) {
            substituted = substitute_formula(&substituted, name, actual);
        }
    }
    Ok(Obligation {
        property_cid: resolved.cid.clone(),
        ir_kit_version: resolved.ir_kit_version.clone(),
        ir_formula: substituted,
    })
}

/// Public adapter so other stages (notably the handshake's
/// implication-form obligation builder) can reuse the same
/// alpha-renaming helper.
pub fn substitute_formula_pub(f: &Json, name: &str, replacement: &Json) -> Json {
    substitute_formula(f, name, replacement)
}

/// Strip ONE redundant outer `forall` from an already-instantiated
/// precondition, returning its body.
///
/// `instantiate::run` substitutes the call's actual argument into the
/// resolved pre's forall body and then RE-WRAPS the result in a forall that
/// re-binds the same formal name. For the panic-freedom GUARD-DISCHARGE
/// obligation this is variable capture: the guard fact (`is_some(opt)`) has a
/// FREE `opt`, but the re-wrapped consequent re-binds `opt`, so the implication
/// becomes `is_some(opt_free) => forall opt_bound. is_some(opt_bound)` =
/// `P(a) => forall x. P(x)`, which a solver correctly refutes. The correct
/// call-site obligation is the pre SPECIALIZED to the actual argument
/// (`pre[formal := arg]`), which is exactly the forall's body. The outer
/// binder is redundant: vacuous when arg != formal, capturing when arg ==
/// formal. Dropping it yields the bare specialized pre, so a matching guard
/// gives the valid `(=> P P)`.
///
/// ONLY the panic-guard branch calls this; the normal refinement obligation
/// keeps the quantified form so its obligation CID / hash-tier lookups are
/// unchanged. If the formula is not a `forall`, it is returned unchanged.
pub fn strip_outer_forall(f: &Json) -> Json {
    if f.get("kind").and_then(|v| v.as_str()) == Some("forall") {
        if let Some(body) = f.get("body") {
            return body.clone();
        }
    }
    f.clone()
}

// Rebuild `node` (a JSON object) replacing exactly one child field with an
// already-substituted value, cloning only the *other* (scalar) sibling fields.
// The previous implementation did `let out = f.clone()` at the top of every
// recursion level -- a deep clone of the whole subtree it was about to replace --
// making substitution Sum(subtree sizes) = O(N^2) over the nesting depth
// (measured: 2x depth -> 3.99x time; one substitution over a depth-1000 formula
// took 5.8s). We never deep-clone the recursed child: it is recomputed once and
// moved into place (via `take`) at its original key position, so the rewrite is
// O(N) and byte-for-byte identical to the old output.
fn rebuild_with_child(map: &serde_json::Map<String, Json>, child_key: &str, child: Json) -> Json {
    let mut child = Some(child);
    let mut out = serde_json::Map::with_capacity(map.len());
    for (k, v) in map {
        if k == child_key {
            out.insert(k.clone(), child.take().expect("child key appears once"));
        } else {
            out.insert(k.clone(), v.clone());
        }
    }
    Json::Object(out)
}

fn substitute_formula(f: &Json, name: &str, replacement: &Json) -> Json {
    let Json::Object(map) = f else {
        return f.clone();
    };
    let kind = map.get("kind").and_then(|v| v.as_str()).unwrap_or_default();
    match kind {
        "atomic" => {
            let Some(Json::Array(args)) = map.get("args") else {
                return f.clone();
            };
            let new_args = args
                .iter()
                .map(|a| substitute_term(a, name, replacement))
                .collect();
            rebuild_with_child(map, "args", Json::Array(new_args))
        }
        "and" | "or" | "not" | "implies" => {
            let Some(Json::Array(ops)) = map.get("operands") else {
                return f.clone();
            };
            let new_ops = ops
                .iter()
                .map(|op| substitute_formula(op, name, replacement))
                .collect();
            rebuild_with_child(map, "operands", Json::Array(new_ops))
        }
        "forall" | "exists" => {
            if map.get("name").and_then(|v| v.as_str()) == Some(name) {
                // Shadowed; the binder rebinds `name`, so do not descend.
                return f.clone();
            }
            let Some(body) = map.get("body") else {
                return f.clone();
            };
            rebuild_with_child(map, "body", substitute_formula(body, name, replacement))
        }
        _ => f.clone(),
    }
}

fn substitute_term(t: &Json, name: &str, replacement: &Json) -> Json {
    let Json::Object(map) = t else {
        return t.clone();
    };
    let kind = map.get("kind").and_then(|v| v.as_str()).unwrap_or_default();
    if kind == "var" && map.get("name").and_then(|v| v.as_str()) == Some(name) {
        return replacement.clone();
    }
    if kind == "ctor" {
        if let Some(Json::Array(args)) = map.get("args") {
            let new_args = args
                .iter()
                .map(|a| substitute_term(a, name, replacement))
                .collect();
            return rebuild_with_child(map, "args", Json::Array(new_args));
        }
    }
    t.clone()
}

#[cfg(test)]
mod strip_outer_forall_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn strips_one_outer_forall_returning_body() {
        // POSITIVE: a `forall opt. is_some(opt)` specializes to its body
        // `is_some(opt)` (the panic-pre over the free callsite arg).
        let f = json!({"kind": "forall", "name": "opt",
            "sort": {"kind": "primitive", "name": "Option<T>"},
            "body": {"kind": "atomic", "name": "is_some",
                "args": [{"kind": "var", "name": "opt"}]}});
        let stripped = strip_outer_forall(&f);
        assert_eq!(
            stripped,
            json!({"kind": "atomic", "name": "is_some",
                "args": [{"kind": "var", "name": "opt"}]})
        );
    }

    #[test]
    fn non_forall_is_returned_unchanged() {
        // DISCRIMINATION: a bare atomic (already specialized) is untouched, so
        // the strip is a safe no-op on non-quantified obligations.
        let f = json!({"kind": "atomic", "name": "is_some",
            "args": [{"kind": "var", "name": "opt"}]});
        assert_eq!(strip_outer_forall(&f), f);
        // An implication is likewise unchanged (only the OUTER forall is peeled).
        let imp = json!({"kind": "implies", "operands": [
            {"kind": "atomic", "name": "is_some", "args": []},
            {"kind": "atomic", "name": "is_some", "args": []}]});
        assert_eq!(strip_outer_forall(&imp), imp);
    }

    #[test]
    fn strips_only_the_outermost_forall() {
        // STRUCTURAL: a nested forall in the body is preserved -- only ONE
        // outer binder is removed (matching `instantiate::run`'s single
        // re-wrap).
        let inner = json!({"kind": "forall", "name": "y",
            "sort": {"kind": "primitive", "name": "Int"},
            "body": {"kind": "atomic", "name": "p",
                "args": [{"kind": "var", "name": "y"}]}});
        let f = json!({"kind": "forall", "name": "x",
            "sort": {"kind": "primitive", "name": "Int"},
            "body": inner.clone()});
        assert_eq!(strip_outer_forall(&f), inner);
    }

    // Build a left-nested `and` chain of `depth` conjuncts wrapping one atomic
    // mentioning `x`. ~`depth` nodes, nested `depth` deep.
    fn nested_and(depth: usize) -> Json {
        let mut f = json!({"kind":"atomic","name":"p","args":[{"kind":"var","name":"x"}]});
        for _ in 0..depth {
            f = json!({"kind":"and","operands":[
                {"kind":"atomic","name":"q","args":[]},
                f
            ]});
        }
        f
    }

    #[test]
    fn substitute_formula_is_linear_not_quadratic() {
        // REGRESSION GUARD for the accidental O(N^2) in substitute_formula (the
        // old `let out = f.clone()` deep-cloned the subtree at every recursion
        // level). Pre-fix measurements on this exact probe: depth 1000 -> 5.8s,
        // depth 2000 -> 23.2s (3.99x for 2x depth = quadratic). Linear is in the
        // low-ms range. We substitute over deeply nested formulas up to depth
        // 8000 and assert the total stays far under a bound that the quadratic
        // would blow by ~1000x (depth-8000 quadratic alone was ~370s). Big stack
        // because the recursion depth tracks the formula nesting. Run with
        // `-- --nocapture` to print the per-depth timings.
        std::thread::Builder::new()
            .stack_size(512 * 1024 * 1024)
            .spawn(|| {
                let repl =
                    json!({"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":7});
                let mut total_us: u128 = 0;
                let mut prev: Option<u128> = None;
                for &depth in &[1000usize, 2000, 4000, 8000] {
                    // Build OUTSIDE the timed region; only the substitution is
                    // timed. We do NOT serialize the result here -- correctness of
                    // substitute_formula is covered by the dedicated semantic
                    // tests; this guard is purely about asymptotic cost.
                    let f = nested_and(depth);
                    let t0 = std::time::Instant::now();
                    let out = substitute_formula(&f, "x", &repl);
                    let us = t0.elapsed().as_micros();
                    assert!(out.is_object(), "substitution must return a formula node");
                    total_us += us;
                    let ratio = prev.map(|p| us as f64 / p.max(1) as f64).unwrap_or(0.0);
                    eprintln!(
                        "[substitute scaling] depth={depth:6} time={us:>10}us ratio_vs_prev={ratio:.2}x"
                    );
                    prev = Some(us);
                }
                // Sum of SUBSTITUTION time only. Linear: a few ms. Quadratic: the
                // depth-2000 substitution alone was ~23s pre-fix. 1000ms guard
                // gives ~2 orders of magnitude headroom over linear -> non-flaky.
                let total_ms = total_us / 1000;
                assert!(
                    total_ms < 1000,
                    "substitute_formula scaled super-linearly ({total_ms}ms of substitution for \
                     depths up to 8000) -- the O(N^2) subtree-clone regressed"
                );
            })
            .unwrap()
            .join()
            .unwrap();
    }
}

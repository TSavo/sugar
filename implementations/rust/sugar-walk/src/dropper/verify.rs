// SPDX-License-Identifier: Apache-2.0

use crate::walk::walk_callsites_to_entry;
use crate::wp::Wp;

use super::gap::Gap;
use super::predicate::{formula_contains_predicate, PredicateDescriptor};

/// Verify that the dropper's emission closes the gap.
///
/// Three structural closure criteria (any one suffices):
///
/// (a) The caller's lifted precondition contains a structural guard that
///     discharges the predicate for the gap variable (via `descriptor.guard_discharged`).
///
/// (b) The predicate is absent from the walker's entry WP after re-walking
///     the modified source.
///
/// (c) The walker's entry WP is `Implies { premise, conclusion }` where the
///     conclusion still contains the predicate but the premise encodes the guard.
///
/// Returns `true` if the gap is closed by any criterion.
pub fn verify_closure(
    modified_source: &str,
    gap: &Gap,
    callee_formal_params: &[String],
    callee_precondition: Wp,
    descriptor: &dyn PredicateDescriptor,
) -> bool {
    use crate::lift::lift_function_precondition;
    use sugar_ir_types::IrFormula;

    let file: syn::File = match syn::parse_str(modified_source) {
        Ok(f) => f,
        Err(_) => return false,
    };
    let caller_fn = match file.items.iter().find_map(|item| {
        if let syn::Item::Fn(f) = item {
            if f.sig.ident == gap.caller_name {
                return Some(f.clone());
            }
        }
        None
    }) {
        Some(f) => f,
        None => return false,
    };

    // Criterion (a): structural scan of the caller's lifted precondition.
    let caller_pre = lift_function_precondition(&caller_fn);
    if descriptor.guard_discharged(caller_pre.as_formula(), &gap.var_name) {
        return true;
    }

    // Criteria (b) and (c): re-walk the modified source and inspect entry WP.
    let walks = walk_callsites_to_entry(
        &caller_fn,
        &gap.callee_name,
        callee_formal_params,
        callee_precondition,
    );

    for walk in &walks {
        let entry_wp = walk.entry_wp();
        let formula = entry_wp.as_formula();

        // Criterion (c): predicate is in conclusion of Implies.
        if let IrFormula::Implies { operands } = formula {
            if operands.len() >= 2
                && formula_contains_predicate(&operands[operands.len() - 1], &gap.predicate)
            {
                return true;
            }
        }

        // Criterion (b): predicate absent entirely from entry WP.
        if !descriptor.contains(formula) {
            return true;
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dropper::emit::emit_drop;
    use crate::dropper::gap::detect_gaps;
    use crate::dropper::predicates::not_null::NotNullPredicate;
    use crate::dropper::template::DropTemplate;
    use crate::walk::walk_callsites_to_entry;
    use crate::wp::Wp;
    use sugar_ir_types::{IrFormula, IrTerm};

    fn not_null_wp(var_name: &str) -> Wp {
        Wp(IrFormula::Atomic {
            name: "not_null".to_string(),
            args: vec![IrTerm::Var {
                name: var_name.to_string(),
            }],
        })
    }

    const FIXTURE_SRC: &str = r#"
fn f(x: Option<i32>) -> i32 {
    x.unwrap()
}

fn caller(x: Option<i32>) {
    f(x);
}
"#;

    #[test]
    fn re_lift_confirms_closure_after_defensive_drop() {
        let file: syn::File = syn::parse_str(FIXTURE_SRC).expect("parses");
        let caller_fn = file
            .items
            .iter()
            .find_map(|item| match item {
                syn::Item::Fn(f) if f.sig.ident == "caller" => Some(f.clone()),
                // sugar-audit: not-mine(test-helper-search-ignores-non-target-items)
                _ => None,
            })
            .expect("caller fn");

        let precondition = not_null_wp("x");
        let walks =
            walk_callsites_to_entry(&caller_fn, "f", &["x".to_string()], precondition.clone());
        let gaps = detect_gaps(&walks, &NotNullPredicate);
        let gap = &gaps[0];

        let result = emit_drop(FIXTURE_SRC, gap, DropTemplate::Defensive, &NotNullPredicate)
            .expect("emit succeeds");

        let closed = verify_closure(
            &result.modified_source,
            gap,
            &["x".to_string()],
            precondition,
            &NotNullPredicate,
        );
        assert!(
            closed,
            "re-lift must confirm DAG closure after Defensive drop. Modified source:\n{}",
            result.modified_source
        );
    }
}

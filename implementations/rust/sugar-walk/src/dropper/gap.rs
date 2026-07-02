// SPDX-License-Identifier: Apache-2.0

use crate::walk::CallsiteWalk;
use crate::wp::Wp;

use super::predicate::PredicateDescriptor;

/// A detected gap: an arrival where the accumulated WP contains an
/// undischarged leaf predicate the substrate cannot discharge statically.
#[derive(Debug, Clone)]
pub struct Gap {
    /// The caller function name.
    pub caller_name: String,
    /// The callee function name at the callsite producing this gap.
    pub callee_name: String,
    /// The undischarged predicate name (e.g. "not_null").
    pub predicate: String,
    /// The variable name the predicate applies to (extracted from the WP).
    pub var_name: String,
    /// The source statement index where the callsite was found (0-indexed
    /// body position). The dropper inserts a guard BEFORE this index.
    pub callsite_stmt_index: usize,
    /// The full accumulated WP at function entry for this walk.
    pub entry_wp: Wp,
}

/// Detect gaps in a set of callsite walks for the given predicate descriptor.
///
/// A gap is a walk whose FunctionEntry arrival's WP contains the descriptor's
/// predicate undischarged and not already premise-guarded (the #405 fix).
///
/// **Skip policy**: if the predicate's argument is not a simple `Var`, the
/// gap is skipped with a diagnostic to stderr.
///
/// Returns one Gap per walk where the gap is detected and a Var argument
/// was extracted.
pub fn detect_gaps(walks: &[CallsiteWalk], descriptor: &dyn PredicateDescriptor) -> Vec<Gap> {
    let mut gaps = Vec::new();
    for walk in walks {
        let Some(callsite_stmt_index) = walk.arrivals.first().map(|a| a.stmt_index) else {
            continue;
        };
        let entry = walk.entry_wp();
        if !descriptor.contains(entry.as_formula()) {
            continue;
        }
        let Some(var_name) = descriptor.var_arg(entry.as_formula()) else {
            eprintln!(
                "sugar-walk/dropper: predicate `{}` in {}->{} entry WP has \
                 non-Var argument; skipping gap (no concrete identifier to guard)",
                descriptor.name(),
                walk.caller_name,
                walk.callee_name
            );
            continue;
        };
        // THE #405 FIX: skip if the predicate is already premise-guarded.
        if descriptor.is_premise_guarded(entry.as_formula(), &var_name) {
            continue;
        }
        gaps.push(Gap {
            caller_name: walk.caller_name.clone(),
            callee_name: walk.callee_name.clone(),
            predicate: descriptor.name().to_string(),
            var_name,
            callsite_stmt_index,
            entry_wp: entry.clone(),
        });
    }
    gaps
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dropper::predicates::not_null::NotNullPredicate;
    use crate::walk::{walk_callsites_to_entry, Arrival, ArrivalKind};
    use crate::wp::{atomic_ge, const_int, var, Wp};
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
    fn detects_not_null_gap_at_function_entry() {
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
        let walks = walk_callsites_to_entry(&caller_fn, "f", &["x".to_string()], precondition);

        assert_eq!(walks.len(), 1, "one callsite in caller");

        let gaps = detect_gaps(&walks, &NotNullPredicate);
        assert_eq!(gaps.len(), 1, "one gap detected");

        let gap = &gaps[0];
        assert_eq!(gap.predicate, "not_null");
        assert_eq!(gap.var_name, "x");
        assert_eq!(gap.caller_name, "caller");
        assert_eq!(gap.callee_name, "f");
    }

    #[test]
    fn no_gap_when_predicate_not_present() {
        let src = r#"
fn f(x: u32) -> u32 { x + 1 }
fn caller(x: u32) { f(x); }
"#;
        let file: syn::File = syn::parse_str(src).expect("parses");
        let caller_fn = file
            .items
            .iter()
            .find_map(|item| match item {
                syn::Item::Fn(f) if f.sig.ident == "caller" => Some(f.clone()),
                // sugar-audit: not-mine(test-helper-search-ignores-non-target-items)
                _ => None,
            })
            .expect("caller fn");

        let precondition = atomic_ge(var("x"), const_int(10));
        let walks = walk_callsites_to_entry(&caller_fn, "f", &["x".to_string()], precondition);
        let gaps = detect_gaps(&walks, &NotNullPredicate);
        assert_eq!(gaps.len(), 0, "no not_null gap for x >= 10 precondition");
    }

    #[test]
    fn detect_gaps_skips_non_var_predicate_arg() {
        let non_var_formula = IrFormula::Atomic {
            name: "not_null".to_string(),
            args: vec![const_int(0)],
        };
        let walk = CallsiteWalk {
            caller_name: "caller".to_string(),
            callee_name: "f".to_string(),
            arrivals: vec![
                Arrival {
                    kind: ArrivalKind::Callsite {
                        callee: "f".to_string(),
                    },
                    stmt_index: 0,
                    wp: Wp(non_var_formula.clone()),
                },
                Arrival {
                    kind: ArrivalKind::FunctionEntry {
                        fn_name: "caller".to_string(),
                    },
                    stmt_index: 1,
                    wp: Wp(non_var_formula),
                },
            ],
        };

        let gaps = detect_gaps(std::slice::from_ref(&walk), &NotNullPredicate);
        assert!(
            gaps.is_empty(),
            "non-Var predicate argument must be skipped, got gaps: {:?}",
            gaps
        );
    }

    // ---- #405 fix tests ----

    fn make_walk_with_entry_wp(entry_wp: Wp) -> CallsiteWalk {
        CallsiteWalk {
            caller_name: "caller".to_string(),
            callee_name: "f".to_string(),
            arrivals: vec![
                Arrival {
                    kind: ArrivalKind::Callsite {
                        callee: "f".to_string(),
                    },
                    stmt_index: 0,
                    wp: entry_wp.clone(),
                },
                Arrival {
                    kind: ArrivalKind::FunctionEntry {
                        fn_name: "caller".to_string(),
                    },
                    stmt_index: 1,
                    wp: entry_wp,
                },
            ],
        }
    }

    #[test]
    fn detect_gaps_skips_premise_guarded_predicate() {
        // Callsite under `if x.is_some() { f(x); }` produces entry WP of shape
        // Implies([is_some(x), not_null(x)]). detect_gaps must return empty.
        let implies_wp = Wp(IrFormula::Implies {
            operands: vec![
                IrFormula::Atomic {
                    name: "is_some".into(),
                    args: vec![IrTerm::Var { name: "x".into() }],
                },
                IrFormula::Atomic {
                    name: "not_null".into(),
                    args: vec![IrTerm::Var { name: "x".into() }],
                },
            ],
        });
        let walk = make_walk_with_entry_wp(implies_wp);
        let gaps = detect_gaps(&[walk], &NotNullPredicate);
        assert!(
            gaps.is_empty(),
            "premise-guarded callsite must not produce a gap"
        );
    }

    #[test]
    fn detect_gaps_emits_gap_when_unguarded() {
        // Plain not_null(x) entry WP with no Implies premise → gap is emitted.
        let plain_wp = Wp(IrFormula::Atomic {
            name: "not_null".into(),
            args: vec![IrTerm::Var { name: "x".into() }],
        });
        let walk = make_walk_with_entry_wp(plain_wp);
        let gaps = detect_gaps(&[walk], &NotNullPredicate);
        assert_eq!(gaps.len(), 1, "unguarded not_null must emit a gap");
    }

    #[test]
    fn detect_gaps_rejects_walk_without_callsite_arrival() {
        let walk = CallsiteWalk {
            caller_name: "caller".to_string(),
            callee_name: "f".to_string(),
            arrivals: Vec::new(),
        };

        let gaps = detect_gaps(&[walk], &NotNullPredicate);
        assert!(
            gaps.is_empty(),
            "a walk with no callsite arrival must not fabricate statement index 0"
        );
    }

    #[test]
    fn detect_gaps_conservative_when_predicate_in_both_premise_and_conclusion() {
        // Implies([not_null(x), not_null(x)]) — predicate in both operands.
        // Conservative: emit the gap.
        let both_wp = Wp(IrFormula::Implies {
            operands: vec![
                IrFormula::Atomic {
                    name: "not_null".into(),
                    args: vec![IrTerm::Var { name: "x".into() }],
                },
                IrFormula::Atomic {
                    name: "not_null".into(),
                    args: vec![IrTerm::Var { name: "x".into() }],
                },
            ],
        });
        let walk = make_walk_with_entry_wp(both_wp);
        let gaps = detect_gaps(&[walk], &NotNullPredicate);
        assert_eq!(
            gaps.len(),
            1,
            "conservative: predicate in both operands must emit a gap"
        );
    }
}

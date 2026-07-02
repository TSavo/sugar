// SPDX-License-Identifier: Apache-2.0

use sugar_ir_types::{IrFormula, IrTerm};

use super::template::{DropTemplate, NotRenderable};

/// Returns true if the formula contains the named predicate (recursive scan).
pub fn formula_contains_predicate(formula: &IrFormula, pred_name: &str) -> bool {
    match formula {
        IrFormula::Atomic { name, .. } => name == pred_name,
        IrFormula::And { operands }
        | IrFormula::Or { operands }
        | IrFormula::Not { operands }
        | IrFormula::Implies { operands } => operands
            .iter()
            .any(|o| formula_contains_predicate(o, pred_name)),
        IrFormula::Forall { body, .. } | IrFormula::Exists { body, .. } => {
            formula_contains_predicate(body, pred_name)
        }
        IrFormula::Choice { body, .. } => formula_contains_predicate(body, pred_name),
        IrFormula::DivergenceBetween { source, target } => {
            formula_contains_predicate(source, pred_name)
                || formula_contains_predicate(target, pred_name)
        }
        // Substitute and Apply are higher-order / meta-level nodes that the
        // dropper does not interpret structurally; conservatively return false.
        IrFormula::Substitute { .. } | IrFormula::Apply { .. } => false,
    }
}

/// Extract the first variable name argument from a named predicate in a formula.
/// For `not_null(x)` returns `Some("x")`.
pub fn predicate_var_arg(formula: &IrFormula, pred_name: &str) -> Option<String> {
    match formula {
        IrFormula::Atomic { name, args } => {
            if name == pred_name {
                args.iter().find_map(|t| match t {
                    IrTerm::Var { name } => Some(name.clone()),
                    // sugar-audit: not-mine(non-variable-predicate-argument-is-not-a-var-binding)
                    _ => None,
                })
            } else {
                None
            }
        }
        IrFormula::And { operands }
        | IrFormula::Or { operands }
        | IrFormula::Not { operands }
        | IrFormula::Implies { operands } => operands
            .iter()
            .find_map(|o| predicate_var_arg(o, pred_name)),
        IrFormula::Forall { body, .. } | IrFormula::Exists { body, .. } => {
            predicate_var_arg(body, pred_name)
        }
        IrFormula::Choice { body, .. } => predicate_var_arg(body, pred_name),
        IrFormula::DivergenceBetween { source, target } => {
            predicate_var_arg(source, pred_name).or_else(|| predicate_var_arg(target, pred_name))
        }
        // Substitute and Apply are higher-order / meta-level nodes; no var to extract.
        IrFormula::Substitute { .. } | IrFormula::Apply { .. } => None,
    }
}

/// A predicate descriptor encapsulates all predicate-specific knowledge:
/// detection, rendering, guard checking, and premise-guard detection.
///
/// Adding a new predicate is a single new file in `predicates/`; no changes
/// to the pipeline are needed.
pub trait PredicateDescriptor: Send + Sync + std::fmt::Debug {
    /// The canonical predicate name (e.g. `"not_null"`).
    fn name(&self) -> &str;

    /// True if `formula` (recursively) contains this predicate.
    fn contains(&self, formula: &IrFormula) -> bool;

    /// Extract the first Var argument of this predicate from the formula.
    fn var_arg(&self, formula: &IrFormula) -> Option<String>;

    /// True if the predicate in `entry_wp` is already conditionally discharged
    /// via an Implies premise — the callsite is branch-guarded and no gap
    /// should be emitted (the #405 fix is implemented by each descriptor).
    fn is_premise_guarded(&self, entry_wp: &IrFormula, var_name: &str) -> bool;

    /// The verified (closure-confirmed) templates for this predicate.
    fn verified_templates(&self) -> &[DropTemplate];

    /// Render the template for this predicate with `var` substituted.
    fn render(&self, template: DropTemplate, var: &str) -> Result<String, NotRenderable>;

    /// True if `formula` contains a structural guard that discharges this
    /// predicate for `var_name` (used by verify_closure criterion a).
    fn guard_discharged(&self, formula: &IrFormula, var_name: &str) -> bool;
}

/// Registry of predicate descriptors. Defaults to registering `NotNullPredicate`.
pub struct PredicateRegistry {
    descriptors: Vec<Box<dyn PredicateDescriptor>>,
}

impl Default for PredicateRegistry {
    fn default() -> Self {
        use crate::dropper::predicates::not_null::NotNullPredicate;
        let mut r = PredicateRegistry {
            descriptors: Vec::new(),
        };
        r.register(Box::new(NotNullPredicate));
        r
    }
}

impl PredicateRegistry {
    pub fn register(&mut self, d: Box<dyn PredicateDescriptor>) {
        self.descriptors.push(d);
    }

    pub fn get(&self, name: &str) -> Option<&dyn PredicateDescriptor> {
        self.descriptors.iter().find_map(|d| {
            if d.name() == name {
                Some(d.as_ref())
            } else {
                None
            }
        })
    }
}

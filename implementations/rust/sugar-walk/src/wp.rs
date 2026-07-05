// SPDX-License-Identifier: MIT OR Apache-2.0
//
// WP construction helpers for the walk pipeline.
//
// The substitution algebra (capture-avoiding `substitute_in_formula` /
// `substitute_in_term` and free-variable computation) used to live here
// and was duplicated into `libsugar::compose`. Per spec
// 2026-05-13-wp-as-formula.md §2.2 it now has a single canonical home in
// `libsugar::wp`; this module re-exports those functions so the rest
// of walk's pipeline keeps importing `crate::wp::substitute_in_formula`
// unchanged. Walk's body-level WP propagation (the Dijkstra propagator
// in `walk.rs` and the loop/exception rules in `loops_and_exceptions.rs`)
// is unchanged by this PR; the broader rework of that propagator onto
// `libsugar::wp`'s evaluator is a later step of the wp-as-formula
// migration.
//
// What stays here: the `Wp` newtype (a WP-specific wrapper around
// `IrFormula` that makes WP operations explicit at walk call sites) and
// the small term / atomic-predicate constructors walk's tests use.

use serde_json::Value;
use sugar_ir_types::{IrFormula, IrTerm, Sort};

// Re-export the canonical substitution algebra from libsugar::wp.
pub use libsugar::wp::{
    free_vars_formula, free_vars_term, substitute_in_formula, substitute_in_term,
};

/// Convenience newtype for the accumulated WP at an arrival.
/// Wraps `IrFormula` to make WP-specific operations explicit at call sites.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Wp(pub IrFormula);

impl Wp {
    pub fn into_formula(self) -> IrFormula {
        self.0
    }

    pub fn as_formula(&self) -> &IrFormula {
        &self.0
    }
}

// ----- Term constructors -----

/// `IrTerm::Var { name }`.
pub fn var(name: impl Into<String>) -> IrTerm {
    IrTerm::Var { name: name.into() }
}

/// `IrTerm::Const { value: <integer>, sort: Int }`.
/// We lean on the canonicalizer's JCS to get byte-stable serialization.
pub fn const_int(n: i64) -> IrTerm {
    IrTerm::Const {
        value: Value::Number(n.into()),
        sort: int_sort(),
    }
}

fn int_sort() -> Sort {
    Sort::Primitive {
        name: "Int".to_string(),
    }
}

/// `IrTerm::Const { value: <decimal-string>, sort: Real }`.
///
/// Source float widths (`f32`/`f64`) and IEEE details are kit-local FOL
/// refinements over this platform-free value sort. This helper deliberately
/// carries no width or bit-pattern payload.
pub fn const_real(value: impl Into<String>) -> IrTerm {
    IrTerm::Const {
        value: Value::String(value.into()),
        sort: Sort::Primitive {
            name: "Real".to_string(),
        },
    }
}

// ----- Atomic predicate constructors -----

/// The trivial `true` predicate. Used as the WP at allocation sites
/// where the value is constant and the precondition trivially holds.
pub fn atomic_true() -> Wp {
    Wp(IrFormula::Atomic {
        name: "true".to_string(),
        args: vec![],
    })
}

/// `lhs < rhs`.
pub fn atomic_lt(lhs: IrTerm, rhs: IrTerm) -> Wp {
    Wp(IrFormula::Atomic {
        name: "<".to_string(),
        args: vec![lhs, rhs],
    })
}

/// `lhs >= rhs`. Encodes the IR vocabulary's `≥`.
pub fn atomic_ge(lhs: IrTerm, rhs: IrTerm) -> Wp {
    Wp(IrFormula::Atomic {
        name: "≥".to_string(),
        args: vec![lhs, rhs],
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn substitute_replaces_var_in_atomic_formula() {
        // y >= 10  with y ↦ 42  should become  42 >= 10
        let initial = atomic_ge(var("y"), const_int(10)).into_formula();
        let result = substitute_in_formula(initial, "y", &const_int(42));
        let expected = atomic_ge(const_int(42), const_int(10)).into_formula();
        assert_eq!(result, expected);
    }

    #[test]
    fn substitute_does_not_replace_nonmatching_var() {
        // x >= 10  with y ↦ 42  should remain  x >= 10
        let initial = atomic_ge(var("x"), const_int(10)).into_formula();
        let result = substitute_in_formula(initial.clone(), "y", &const_int(42));
        assert_eq!(result, initial);
    }
}

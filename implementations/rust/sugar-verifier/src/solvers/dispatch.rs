// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Per-fragment dispatch: walk the IR-formula JSON to detect which
// theory dominates, return the matching solver name from the dispatch
// config.
//
// Heuristics (first match wins):
//
//   strings           - any atomic predicate or term whose name is
//                       a known string predicate (length, matches,
//                       contains, prefix-of, suffix-of, str.++).
//   bitvectors        - any sort whose name starts with `BitVec`,
//                       `bv`, `BV`, or any atomic over bitvector
//                       operators (bvadd, bvand, bvshl, ...).
//   linear-arithmetic - default for anything else with arithmetic
//                       atoms over Int/Real (`>`, `<`, `=`, `+`,
//                       `-`, `*` with constant factor).
//   default           - everything else.
//
// The walker is deliberately conservative: if we can't classify, we
// return "default". The dispatch config maps these tags to solver
// names; if the matching tag is missing we fall back to "default";
// if "default" is missing we return None (caller treats as a config
// error and reports Undecidable).

use serde_json::Value as Json;

use crate::solvers::{DispatchConfig, SolverSeat};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FormulaTheory {
    EquationalTheory,
    FirstOrder,
    Strings,
    Bitvectors,
    LinearArithmetic,
    DependentType,
    CategoricalStructure,
    Default,
}

impl FormulaTheory {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::EquationalTheory => "equational-theory",
            Self::FirstOrder => "first-order",
            Self::Strings => "strings",
            Self::Bitvectors => "bitvectors",
            Self::LinearArithmetic => "linear-arithmetic",
            Self::DependentType => "dependent-type",
            Self::CategoricalStructure => "categorical-structure",
            Self::Default => "default",
        }
    }
}

const STRING_OPS: &[&str] = &[
    "length",
    "matches",
    "contains",
    "prefix-of",
    "suffix-of",
    "str.++",
    "str.len",
    "str.indexof",
    "str.is_ascii",
    "str.is_ascii_alphabetic",
    "str.is_ascii_alphanumeric",
    "str.is_ascii_digit",
    "str.is_ascii_octdigit",
    "str.is_ascii_lowercase",
    "str.is_ascii_uppercase",
    "str.is_ascii_hexdigit",
    "str.is_ascii_punctuation",
    "str.is_ascii_graphic",
    "str.is_ascii_whitespace",
    "str.is_ascii_control",
    "str.chars-in-set",
    "str.chars-not-in-set",
    "str.in-regex",
];

const BV_OPS: &[&str] = &[
    "bvadd", "bvsub", "bvmul", "bvand", "bvor", "bvxor", "bvnot", "bvshl", "bvlshr", "bvashr",
    "bvult", "bvule", "bvugt", "bvuge", "bvslt", "bvsle", "bvsgt", "bvsge",
];

const CATEGORY_OPS: &[&str] = &[
    "CategoryTheory.Category",
    "CategoryTheory.Functor",
    "CategoryTheory.NatTrans",
    "CategoryTheory.Limits",
    "Function.Bijective",
    "LawvereTheory",
    "FreeAlgebra",
];

pub fn classify(formula: &Json) -> FormulaTheory {
    let mut theory = FormulaTheory::Default;
    walk(formula, &mut theory);
    theory
}

fn walk(v: &Json, theory: &mut FormulaTheory) {
    // Strings dominates over BV, BV dominates over LIA, LIA dominates
    // over Default. Once we set a higher-precedence theory we keep it.
    match v {
        Json::Object(map) => {
            // Detect special sorts before the quantifier marker. A quantified
            // String/BV/dependent obligation still belongs to its stronger
            // theory seat; otherwise the quantifier itself makes it a
            // first-order obligation.
            if let Some(sort) = map.get("sort") {
                if let Some(srt_obj) = sort.as_object() {
                    if srt_obj
                        .get("kind")
                        .and_then(|v| v.as_str())
                        .is_some_and(|kind| kind == "dependent" || kind == "function")
                    {
                        *theory = FormulaTheory::DependentType;
                        return;
                    }
                    if let Some(srt_name) = srt_obj.get("name").and_then(|v| v.as_str()) {
                        if srt_name == "String" {
                            *theory = FormulaTheory::Strings;
                            return;
                        }
                        if (srt_name.starts_with("BitVec")
                            || srt_name.starts_with("bv")
                            || srt_name.starts_with("BV"))
                            && *theory != FormulaTheory::Strings
                        {
                            *theory = FormulaTheory::Bitvectors;
                        }
                    }
                }
            }

            if map
                .get("kind")
                .and_then(|v| v.as_str())
                .is_some_and(|kind| matches!(kind, "forall" | "exists" | "choice"))
                && *theory == FormulaTheory::Default
            {
                *theory = FormulaTheory::FirstOrder;
            }

            if let Some(name) = map.get("name").and_then(|v| v.as_str()) {
                if name == "equational_theory" {
                    *theory = FormulaTheory::EquationalTheory;
                    return;
                }
                if CATEGORY_OPS.iter().any(|op| name.contains(op)) {
                    *theory = FormulaTheory::CategoricalStructure;
                    return;
                }
                if STRING_OPS.contains(&name) {
                    *theory = FormulaTheory::Strings;
                    return;
                }
                if BV_OPS.contains(&name) && *theory != FormulaTheory::Strings {
                    *theory = FormulaTheory::Bitvectors;
                }
                if matches!(name, ">" | "<" | ">=" | "<=" | "=" | "+" | "-" | "*")
                    && *theory == FormulaTheory::Default
                {
                    *theory = FormulaTheory::LinearArithmetic;
                }
            }
            for (_, child) in map {
                if matches!(
                    *theory,
                    FormulaTheory::EquationalTheory | FormulaTheory::Strings
                ) {
                    return;
                }
                walk(child, theory);
            }
        }
        Json::Array(arr) => {
            for child in arr {
                if matches!(
                    *theory,
                    FormulaTheory::EquationalTheory | FormulaTheory::Strings
                ) {
                    return;
                }
                walk(child, theory);
            }
        }
        _ => {}
    }
}

/// Apply the dispatch config: classify the formula, look up the named
/// solver. Returns `None` if neither the matching tag nor `default` is
/// configured.
pub fn dispatch_for_formula(formula: &Json, dispatch: &DispatchConfig) -> Option<SolverSeat> {
    let t = classify(formula);
    let by_theory = match t {
        FormulaTheory::EquationalTheory => dispatch.equational_theory,
        FormulaTheory::FirstOrder => dispatch.first_order,
        FormulaTheory::Strings => dispatch.strings,
        FormulaTheory::Bitvectors => dispatch.bitvectors,
        FormulaTheory::LinearArithmetic => dispatch.linear_arithmetic,
        FormulaTheory::DependentType => dispatch.dependent_type,
        FormulaTheory::CategoricalStructure => dispatch.categorical_structure,
        FormulaTheory::Default => None,
    };
    by_theory.or(dispatch.default)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn classify_lia() {
        let f = json!({
            "kind": "atomic",
            "name": ">",
            "args": [{"kind":"var","name":"n"}, {"kind":"const","value":0}]
        });
        assert_eq!(classify(&f), FormulaTheory::LinearArithmetic);
    }

    #[test]
    fn classify_strings_by_op() {
        for name in [
            "length",
            "contains",
            "prefix-of",
            "suffix-of",
            "str.len",
            "str.is_ascii",
            "str.is_ascii_alphabetic",
            "str.is_ascii_alphanumeric",
            "str.is_ascii_digit",
            "str.is_ascii_octdigit",
            "str.is_ascii_lowercase",
            "str.is_ascii_uppercase",
            "str.is_ascii_hexdigit",
            "str.is_ascii_punctuation",
            "str.is_ascii_graphic",
            "str.is_ascii_whitespace",
            "str.is_ascii_control",
            "str.chars-in-set",
            "str.chars-not-in-set",
        ] {
            let f = json!({
                "kind": "atomic",
                "name": name,
                "args": [{"kind":"var","name":"s"}]
            });
            assert_eq!(classify(&f), FormulaTheory::Strings, "name={name}");
        }
    }

    #[test]
    fn classify_strings_by_sort() {
        let f = json!({
            "kind": "forall",
            "name": "s",
            "sort": {"kind":"primitive","name":"String"},
            "body": {"kind":"atomic","name":"=","args":[]}
        });
        assert_eq!(classify(&f), FormulaTheory::Strings);
    }

    #[test]
    fn classify_bitvectors() {
        let f = json!({
            "kind": "atomic",
            "name": "bvadd",
            "args": [{"kind":"var","name":"x"}, {"kind":"var","name":"y"}]
        });
        assert_eq!(classify(&f), FormulaTheory::Bitvectors);
    }

    #[test]
    fn dispatch_picks_solver() {
        let d = DispatchConfig {
            equational_theory: Some(SolverSeat::Maude),
            first_order: Some(SolverSeat::Vampire),
            strings: Some(SolverSeat::Cvc5),
            bitvectors: Some(SolverSeat::Bitwuzla),
            linear_arithmetic: Some(SolverSeat::Z3),
            dependent_type: Some(SolverSeat::Lean),
            categorical_structure: Some(SolverSeat::Lean),
            default: Some(SolverSeat::Z3),
        };
        let f = json!({"kind":"atomic","name":"length","args":[]});
        assert_eq!(dispatch_for_formula(&f, &d), Some(SolverSeat::Cvc5));
        let f = json!({"kind":"atomic","name":"bvadd","args":[]});
        assert_eq!(dispatch_for_formula(&f, &d), Some(SolverSeat::Bitwuzla));
        let f = json!({"kind":"atomic","name":">","args":[]});
        assert_eq!(dispatch_for_formula(&f, &d), Some(SolverSeat::Z3));
        let f = json!({"kind":"atomic","name":"unknown","args":[]});
        assert_eq!(dispatch_for_formula(&f, &d), Some(SolverSeat::Z3)); // via default
    }

    #[test]
    fn classify_forall_as_first_order() {
        let f = json!({
            "kind": "forall",
            "name": "x",
            "sort": {"kind":"primitive","name":"Int"},
            "body": {"kind":"atomic","name":"=","args":[
                {"kind":"ctor","name":"f","args":[{"kind":"var","name":"x"}]},
                {"kind":"var","name":"x"}
            ]}
        });
        assert_eq!(classify(&f), FormulaTheory::FirstOrder);

        let d = DispatchConfig {
            equational_theory: None,
            first_order: Some(SolverSeat::Vampire),
            strings: None,
            bitvectors: None,
            linear_arithmetic: Some(SolverSeat::Z3),
            dependent_type: None,
            categorical_structure: None,
            default: Some(SolverSeat::Z3),
        };
        assert_eq!(dispatch_for_formula(&f, &d), Some(SolverSeat::Vampire));
    }

    #[test]
    fn dispatch_picks_lean_for_dependent_sort() {
        let d = DispatchConfig {
            equational_theory: None,
            first_order: None,
            strings: None,
            bitvectors: None,
            linear_arithmetic: None,
            dependent_type: Some(SolverSeat::Lean),
            categorical_structure: None,
            default: Some(SolverSeat::Z3),
        };
        let f = json!({
            "kind": "forall",
            "name": "xs",
            "sort": {
                "kind": "dependent",
                "name": "Vec",
                "indexVar": "n",
                "indexSort": {"kind": "primitive", "name": "Int"}
            },
            "body": {"kind": "atomic", "name": "true", "args": []}
        });
        assert_eq!(dispatch_for_formula(&f, &d), Some(SolverSeat::Lean));
    }

    #[test]
    fn dispatch_picks_lean_for_category_theory_name() {
        let d = DispatchConfig {
            equational_theory: None,
            first_order: None,
            strings: None,
            bitvectors: None,
            linear_arithmetic: None,
            dependent_type: None,
            categorical_structure: Some(SolverSeat::Lean),
            default: Some(SolverSeat::Z3),
        };
        let f = json!({"kind":"atomic","name":"CategoryTheory.Functor.map_id","args":[]});
        assert_eq!(dispatch_for_formula(&f, &d), Some(SolverSeat::Lean));
    }
}

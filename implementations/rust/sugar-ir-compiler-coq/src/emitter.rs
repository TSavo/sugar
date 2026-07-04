// SPDX-License-Identifier: MIT OR Apache-2.0
// HAND-MAINTAINED. Enum totality is compiler-enforced; atom/op-table totality
// is enforced by the vocabulary audit test (tests/vocabulary_totality.rs).

#![deny(unreachable_patterns)]

use std::collections::{BTreeMap, BTreeSet};
use sugar_ir_compiler::{CompileError, FreeVar};
use sugar_ir_types::*;

#[derive(Clone, Copy, PartialEq, Eq)]
enum CoqUninterpretedPosition {
    Atom,
    Ctor,
}

struct CoqUninterpretedAllowlistEntry {
    name: &'static str,
    position: CoqUninterpretedPosition,
}

/// Every name here is DELIBERATELY uninterpreted in Coq; adding a name is a semantic decision — the symbol carries no constraints.
const COQ_UNINTERPRETED_ALLOWLIST: &[CoqUninterpretedAllowlistEntry] = &[
    // Kit-defined relation; Coq keeps it as an opaque predicate.
    CoqUninterpretedAllowlistEntry {
        name: "roundTrips",
        position: CoqUninterpretedPosition::Atom,
    },
    // Kit-defined error-state relation; Coq keeps it as an opaque predicate.
    CoqUninterpretedAllowlistEntry {
        name: "isErr",
        position: CoqUninterpretedPosition::Atom,
    },
    // Kit-defined malformed-input relation; Coq keeps it as an opaque predicate.
    CoqUninterpretedAllowlistEntry {
        name: "isMalformed",
        position: CoqUninterpretedPosition::Atom,
    },
    // Python object identity witness; Coq keeps the value term opaque.
    CoqUninterpretedAllowlistEntry {
        name: "py.object.identity",
        position: CoqUninterpretedPosition::Ctor,
    },
];

pub fn emit_term(term: &Term) -> Result<String, CompileError> {
    match term {
        Term::Var { name, .. } => Ok(name.clone()),
        Term::Const { value, sort, .. } => {
            // Coq: Function/Dependent sorts on a Const are structurally unusual but
            // not unsound. Coq's higher-order universe permits e.g. `(fun x => x) : nat -> nat`
            // as a constant inhabiting a function sort. `emit_const_value` ignores the sort name
            // (it only branches on the JSON value shape), so we feed it the empty string for
            // non-primitive sorts and let the value's own JSON dictate the surface form.
            let sort_name = match sort {
                Sort::Primitive { name } => name.as_str(),
                Sort::Function { .. } | Sort::Dependent { .. } | Sort::Region { .. } => "",
            };
            Ok(emit_const_value(value, sort_name))
        }
        Term::Ctor { name, args, .. } => {
            let args_str = args.iter();
            let args_str = args_str.map(emit_term);
            let args_str: Result<Vec<String>, CompileError> = args_str.collect();
            let args_str = args_str?;
            if coq_binop(name).is_some() || is_coq_binop_candidate(name) {
                let op = coq_binop(name).ok_or_else(|| unsupported_coq_binop(name))?;
                if args_str.len() == 2 {
                    return Ok(format!("({} {} {})", args_str[0], op, args_str[1]));
                }
                return Err(unsupported_coq_binop_arity(name, args_str.len()));
            }
            if coq_uninterpreted_allowed(name, CoqUninterpretedPosition::Ctor) {
                return Ok(coq_uninterpreted_application(name, &args_str));
            }
            Err(unsupported_coq_ctor(name))
        }
        Term::Lambda {
            param_name,
            param_sort,
            body,
            ..
        } => {
            let sort_str = emit_sort(param_sort);
            let body_str = emit_term(body)?;
            Ok(format!(
                "fun ({} : {}) => {}",
                param_name, sort_str, body_str
            ))
        }
        Term::Let { bindings, body, .. } => {
            let mut parts = Vec::new();
            for b in bindings {
                parts.push(format!(
                    "let {} := {} in",
                    b.name,
                    emit_term(&b.bound_term)?
                ));
            }
            let body_str = emit_term(body)?;
            Ok(format!("{} {}", parts.join(" "), body_str))
        }
    }
}
pub fn emit_formula(formula: &Formula) -> Result<String, CompileError> {
    match formula {
        Formula::Atomic { name, args } => {
            let args_str = args.iter();
            let args_str = args_str.map(emit_term);
            let args_str: Result<Vec<String>, CompileError> = args_str.collect();
            let args_str = args_str?;
            let emitted = match name.as_str() {
                "=" => format!("({} = {})", args_str[0].clone(), args_str[1].clone()),
                ">" => format!("({} > {})", args_str[0].clone(), args_str[1].clone()),
                "<" => format!("({} < {})", args_str[0].clone(), args_str[1].clone()),
                "\u{2265}" => format!("({} >= {})", args_str[0].clone(), args_str[1].clone()),
                "\u{2264}" => format!("({} <= {})", args_str[0].clone(), args_str[1].clone()),
                "\u{2260}" => format!("({} <> {})", args_str[0].clone(), args_str[1].clone()),
                "true" => "True".to_string(),
                "false" => "False".to_string(),
                _ if coq_uninterpreted_allowed(name, CoqUninterpretedPosition::Atom) => {
                    coq_uninterpreted_application(name, &args_str)
                }
                _ => return Err(unsupported_coq_atom(name)),
            };
            Ok(emitted)
        }
        Formula::And { operands } => {
            let ops = operands.iter();
            let ops = ops.map(emit_formula);
            let ops: Result<Vec<String>, CompileError> = ops.collect();
            let ops = ops?;
            Ok(format!("({})", ops.join(r#" /\ "#)))
        }
        Formula::Or { operands } => {
            let ops = operands.iter();
            let ops = ops.map(emit_formula);
            let ops: Result<Vec<String>, CompileError> = ops.collect();
            let ops = ops?;
            Ok(format!("({})", ops.join(r#" \/ "#)))
        }
        Formula::Not { operands } => Ok(format!("(~{})", emit_formula(&operands[0])?)),
        Formula::Implies { operands } => Ok(format!(
            "({} -> {})",
            emit_formula(&operands[0])?,
            emit_formula(&operands[1])?
        )),
        Formula::Forall { name, sort, body } => {
            let coq_sort = sort_to_coq(sort);
            let body_str = emit_formula(body)?;
            Ok(format!("forall {} : {}, {}", name, coq_sort, body_str))
        }
        Formula::Exists { name, sort, body } => {
            let coq_sort = sort_to_coq(sort);
            let body_str = emit_formula(body)?;
            Ok(format!("exists {} : {}, {}", name, coq_sort, body_str))
        }
        Formula::Choice {
            var_name,
            sort,
            body,
        } => {
            let coq_sort = sort_to_coq(sort);
            let body_str = emit_formula(body)?;
            Ok(format!(
                "@sig {} {} (fun {} => {})",
                var_name, coq_sort, var_name, body_str
            ))
        }
        // wp-rule schema nodes (spec 2026-05-13-wp-as-formula.md §2.3):
        // `substitute` / `apply` appear only inside an unreduced `wp_rule`
        // term and are eliminated by `libsugar::wp` before any solver
        // or compiler backend sees the formula. Reaching this arm is a bug.
        // TODO(wp-as-formula PR1+): teach sugar-ir-codegen to emit this arm.
        Formula::Substitute { .. } | Formula::Apply { .. } => {
            unreachable!(
                "wp-rule schema node reached the Coq formula emitter; \
                 must be reduced via libsugar::wp first"
            )
        }
        Formula::DivergenceBetween { .. } => {
            unreachable!(
                "platform divergence formula reached the Coq formula emitter; \
                 stage 4 must lower it before backend compilation"
            )
        }
    }
}

fn coq_uninterpreted_allowed(name: &str, position: CoqUninterpretedPosition) -> bool {
    COQ_UNINTERPRETED_ALLOWLIST
        .iter()
        .any(|entry| entry.name == name && entry.position == position)
}

pub fn coq_uninterpreted_allowlist_entries() -> Vec<(&'static str, &'static str)> {
    COQ_UNINTERPRETED_ALLOWLIST
        .iter()
        .map(|entry| {
            let position = match entry.position {
                CoqUninterpretedPosition::Atom => "atom",
                CoqUninterpretedPosition::Ctor => "ctor",
            };
            (entry.name, position)
        })
        .collect()
}

fn coq_uninterpreted_application(name: &str, args_str: &[String]) -> String {
    if args_str.is_empty() {
        coq_ident(name)
    } else {
        format!("{} {}", coq_ident(name), args_str.join(" "))
    }
}

fn unsupported_coq_atom(name: &str) -> CompileError {
    CompileError::UnsupportedPredicate(format!(
        "`{name}`: no Coq encoding registered; refusing rather than weakening; add to COQ_UNINTERPRETED_ALLOWLIST only after a semantic review"
    ))
}

fn unsupported_coq_ctor(name: &str) -> CompileError {
    CompileError::MalformedIr(format!(
        "unsupported Coq term constructor `{name}`: no Coq encoding registered; refusing rather than weakening; add to COQ_UNINTERPRETED_ALLOWLIST only after a semantic review"
    ))
}

fn unsupported_coq_binop(name: &str) -> CompileError {
    CompileError::MalformedIr(format!(
        "unsupported Coq binary operator `{name}`: no Coq encoding registered; refusing rather than weakening; implement coq_binop or add to COQ_UNINTERPRETED_ALLOWLIST only after a semantic review"
    ))
}

fn unsupported_coq_binop_arity(name: &str, arity: usize) -> CompileError {
    CompileError::MalformedIr(format!(
        "unsupported Coq binary operator `{name}` arity {arity}: no Coq encoding registered; refusing rather than weakening; implement coq_binop or add to COQ_UNINTERPRETED_ALLOWLIST only after a semantic review"
    ))
}

fn is_coq_binop_candidate(name: &str) -> bool {
    matches!(name, "/" | "%" | "!=" | "\u{2260}" | "<>" | "&&" | "||")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn int_sort() -> Sort {
        Sort::Primitive { name: "Int".into() }
    }

    fn int_const(value: i64) -> Term {
        Term::Const {
            value: serde_json::json!(value),
            sort: int_sort(),
        }
    }

    fn var(name: &str) -> Term {
        Term::Var { name: name.into() }
    }

    #[test]
    fn lambda_emits_expected_coq() {
        let term = Term::Lambda {
            param_name: "x".into(),
            param_sort: int_sort(),
            body: Box::new(var("x")),
        };

        assert_eq!(emit_term(&term).unwrap(), "fun (x : Z) => x");
    }

    #[test]
    fn let_emits_expected_coq() {
        let term = Term::Let {
            bindings: vec![LetBinding {
                name: "x".into(),
                bound_term: int_const(1),
            }],
            body: Box::new(var("x")),
        };

        assert_eq!(emit_term(&term).unwrap(), "let x := 1 in x");
    }
}
fn emit_sort(sort: &Sort) -> String {
    match sort {
        Sort::Primitive { name } => match name.as_str() {
            "Int" => "Z".to_string(),
            "Real" => "R".to_string(),
            "String" => "string".to_string(),
            "Bool" => "bool".to_string(),
            _ => "Z".to_string(),
        },
        // FunctionSort: Coq function arrow `A1 -> A2 -> ... -> Ret`. Coq's `->` is
        // right-associative, so a function-typed argument MUST be parenthesized to
        // preserve meaning: `(A -> B) -> C` differs from `A -> B -> C`. Soundness
        // depends on this. Issue #331; see protocol/specs/multi-solver-protocol-v2.md
        // Coq's portfolio seat covers higher-order, so this position is NOT opaque.
        Sort::Function { args, ret } => {
            let mut parts: Vec<String> = args.iter().map(emit_sort_paren).collect();
            parts.push(emit_sort_paren(ret));
            parts.join(" -> ")
        }
        // DependentSort: Coq Π-type. `Vec` indexed by `n: nat` becomes
        // `forall n : nat, Vec n`. The instantiated form (`<name> <index_var>`)
        // matches the canonical dependent-product shape in Coq, where the sort
        // name is applied to the bound index. Issue #331.
        Sort::Dependent {
            name,
            index_var,
            index_sort,
        } => {
            format!(
                "forall {} : {}, {} {}",
                index_var,
                emit_sort(index_sort),
                name,
                index_var
            )
        }
        // RegionSort: lifetime variables are opaque to the Coq backend.
        // Regions are pre-resolved in composition; emit as an opaque "Region" name.
        Sort::Region { .. } => "Region".to_string(),
    }
}

/// Wrap a sort emission in parens when its surface form would re-associate
/// inside a function arrow chain. `Sort::Function` (right-associative `->`)
/// and `Sort::Dependent` (leading `forall ...,`) both extend maximally to
/// the right in Coq's grammar, so an unparenthesized occurrence in argument
/// position silently changes scope. `Sort::Primitive` is a single token
/// and needs no wrapping.
fn emit_sort_paren(sort: &Sort) -> String {
    match sort {
        Sort::Function { .. } | Sort::Dependent { .. } => format!("({})", emit_sort(sort)),
        Sort::Primitive { .. } | Sort::Region { .. } => emit_sort(sort),
    }
}

fn sort_to_coq(sort: &Sort) -> String {
    match sort {
        Sort::Primitive { name } => match name.as_str() {
            "Int" => "Z".to_string(),
            "Real" => "R".to_string(),
            "String" => "string".to_string(),
            "Bool" => "bool".to_string(),
            _ => "Z".to_string(),
        },
        // Identical Coq syntax to `emit_sort`; this entry point is used in formula
        // binder positions (Forall/Exists/Choice). See `emit_sort` for soundness
        // notes on associativity (Function) and Π-type shape (Dependent).
        Sort::Function { args, ret } => {
            let mut parts: Vec<String> = args.iter().map(sort_to_coq_paren).collect();
            parts.push(sort_to_coq_paren(ret));
            parts.join(" -> ")
        }
        Sort::Dependent {
            name,
            index_var,
            index_sort,
        } => {
            format!(
                "forall {} : {}, {} {}",
                index_var,
                sort_to_coq(index_sort),
                name,
                index_var
            )
        }
        // RegionSort: opaque to Coq binder positions; emit as "Region". #401.
        Sort::Region { .. } => "Region".to_string(),
    }
}

fn sort_to_coq_paren(sort: &Sort) -> String {
    match sort {
        Sort::Function { .. } | Sort::Dependent { .. } => format!("({})", sort_to_coq(sort)),
        Sort::Primitive { .. } | Sort::Region { .. } => sort_to_coq(sort),
    }
}
// coq_ident sanitizes a name into a valid Coq identifier: Coq identifiers
// allow letters, digits, '_' and '\''; lifted ctor names like `go:call` /
// `go:slice-literal` contain ':' and '-', which Coq rejects. Replacing them
// with '_' is applied consistently at both the `Parameter` declaration and
// every use, so the symbol still matches.
// coq_binop maps a term-level comparison ctor to its Coq Z bool operator
// (Z.ltb/Z.leb/Z.gtb/Z.geb/Z.eqb under `Open Scope Z`). These ctors return
// bool in the IR (they are compared against bool consts), so they must emit
// the boolean comparison `<?`/`<=?`/etc., not be sanitized to `_`. Both
// ASCII (`<=`) and the Unicode relational forms (`≤`,`≥`) are accepted.
fn coq_binop(name: &str) -> Option<&'static str> {
    match name {
        "<" => Some("<?"),
        ">" => Some(">?"),
        "<=" | "\u{2264}" => Some("<=?"),
        ">=" | "\u{2265}" => Some(">=?"),
        "=" => Some("=?"),
        // Interpreted homogeneous arithmetic, infix and scope-polymorphic (Z or R
        // depending on the open scope), never a sanitized uninterpreted symbol.
        "+" => Some("+"),
        "-" => Some("-"),
        "*" => Some("*"),
        _ => None,
    }
}
fn coq_ident(name: &str) -> String {
    name.chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '_' || c == '\'' {
                c
            } else {
                '_'
            }
        })
        .collect()
}

/// A `Real` const arrives as a canonical decimal string (e.g. "0.00000015").
/// Coq's `R` has no decimal literal, so emit the EXACT rational `(num / den)%R`,
/// where under `Open Scope R` the numerals are reals via R's number notation and
/// `/` is `Rdiv`. `1.5 * 10**(-decimal)` is exact, so this is lossless and
/// content-stable. `lra` discharges goals with such rational constants.
fn coq_real_literal(decimal: &str) -> String {
    let (neg, body) = match decimal.strip_prefix('-') {
        Some(b) => (true, b),
        None => (false, decimal),
    };
    let (int_part, frac_part) = body.split_once('.').unwrap_or((body, ""));
    let mut digits = String::from(int_part);
    digits.push_str(frac_part);
    let trimmed = digits.trim_start_matches('0');
    let num = if trimmed.is_empty() { "0" } else { trimmed };
    let den = format!("1{}", "0".repeat(frac_part.len()));
    if neg {
        format!("(- ({num} / {den}))%R")
    } else {
        format!("({num} / {den})%R")
    }
}

/// True iff the term carries a `Real`-sorted constant anywhere. A formula that
/// does is lowered over Coq's `R` with `lra`, rather than `Z` with `lia`.
fn term_has_real_const(term: &Term) -> bool {
    match term {
        Term::Const { sort, .. } => matches!(sort, Sort::Primitive { name } if name == "Real"),
        Term::Ctor { args, .. } => args.iter().any(term_has_real_const),
        Term::Lambda { body, .. } => term_has_real_const(body),
        Term::Let { bindings, body, .. } => {
            bindings.iter().any(|b| term_has_real_const(&b.bound_term)) || term_has_real_const(body)
        }
        Term::Var { .. } => false,
    }
}

fn formula_has_real_const(formula: &Formula) -> bool {
    match formula {
        Formula::Atomic { args, .. } => args.iter().any(term_has_real_const),
        Formula::And { operands }
        | Formula::Or { operands }
        | Formula::Not { operands }
        | Formula::Implies { operands } => operands.iter().any(formula_has_real_const),
        Formula::Forall { body, .. }
        | Formula::Exists { body, .. }
        | Formula::Choice { body, .. } => formula_has_real_const(body),
        _ => false,
    }
}

fn emit_const_value(value: &serde_json::Value, sort_name: &str) -> String {
    if sort_name == "Real" {
        if let serde_json::Value::String(s) = value {
            return coq_real_literal(s);
        }
    }
    match value {
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                i.to_string()
            } else if let Some(u) = n.as_u64() {
                u.to_string()
            } else {
                n.to_string()
            }
        }
        serde_json::Value::Bool(b) => {
            if *b {
                "true".to_string()
            } else {
                "false".to_string()
            }
        }
        serde_json::Value::String(s) => format!("\"{}\"", s),
        _ => "0".to_string(),
    }
}
pub fn compile_formula(formula: &Formula) -> Result<(String, String, Vec<FreeVar>), CompileError> {
    let mut free_vars = BTreeMap::new();
    let bound = BTreeSet::new();
    collect_free_vars_formula(formula, &mut free_vars, &bound);
    // A Real-bearing obligation is lowered over Coq's `R` (lra), not `Z` (lia).
    // The Python tolerance corpus is homogeneously real; integers embed in R and
    // lra handles them, so every free var declares as `R`. A real+string mix is
    // the deferred Number-base conflict case (see the smt-lib rung).
    let is_real = formula_has_real_const(formula);
    let mut body = String::new();
    for (name, sort) in free_vars.iter() {
        let coq_sort = if is_real {
            "R"
        } else {
            match sort.as_str() {
                "Int" | "Real" => "Z",
                "String" => "string",
                "Bool" => "bool",
                _ => "Z",
            }
        };
        body.push_str(&format!("Parameter {} : {}.\n", coq_ident(name), coq_sort));
    }
    body.push_str("\nGoal ");
    body.push_str(&emit_formula(formula)?);
    body.push_str(".\n");
    // A real proof closed by `Qed` is the soundness gate: Coq rejects an
    // incomplete proof at `Qed`, so a clean exit means the goal holds. `intros`
    // first so any implication antecedents become hypotheses. `lia` discharges
    // linear INTEGER arithmetic; `lra` discharges linear REAL arithmetic (the
    // tolerance bounds). A goal outside the chosen theory makes the tactic fail
    // -> coqc exits non-zero -> the seat reports Undecidable.
    let tactic = if is_real { "lra" } else { "lia" };
    body.push_str(&format!("Proof.\n  intros.\n  {tactic}.\nQed.\n"));
    // Open the arithmetic scope LAST so it dominates the string scope: the
    // numeral/operator notations must resolve in the proof's theory (R or Z),
    // not string. Opening string first keeps string literals available.
    let preamble = if is_real {
        "Require Import Reals String List Lra.\nOpen Scope string.\nOpen Scope R.\n\n".to_string()
    } else {
        "Require Import ZArith String List Lia.\nOpen Scope string.\nOpen Scope Z.\n\n".to_string()
    };
    let free_vars_vec = free_vars
        .into_iter()
        .map(|(name, sort)| FreeVar { name, sort });
    let free_vars_vec = free_vars_vec.collect();
    Ok((preamble, body, free_vars_vec))
}
pub fn collect_free_vars_formula(
    formula: &Formula,
    out: &mut BTreeMap<String, String>,
    bound: &BTreeSet<String>,
) {
    match formula {
        Formula::Atomic { args, .. } => {
            for a in args {
                collect_free_vars_term(a, out, bound);
            }
        }
        Formula::And { operands } => {
            for o in operands {
                collect_free_vars_formula(o, out, bound);
            }
        }
        Formula::Or { operands } => {
            for o in operands {
                collect_free_vars_formula(o, out, bound);
            }
        }
        Formula::Not { operands } => {
            for o in operands {
                collect_free_vars_formula(o, out, bound);
            }
        }
        Formula::Implies { operands } => {
            for o in operands {
                collect_free_vars_formula(o, out, bound);
            }
        }
        Formula::Forall {
            name,
            sort: _,
            body,
        } => {
            let mut nb = bound.clone();
            nb.insert(name.clone());
            collect_free_vars_formula(body, out, &nb);
        }
        Formula::Exists {
            name,
            sort: _,
            body,
        } => {
            let mut nb = bound.clone();
            nb.insert(name.clone());
            collect_free_vars_formula(body, out, &nb);
        }
        Formula::Choice {
            var_name,
            sort: _,
            body,
        } => {
            let mut nb = bound.clone();
            nb.insert(var_name.clone());
            collect_free_vars_formula(body, out, &nb);
        }
        // wp-rule schema nodes (spec 2026-05-13-wp-as-formula.md §2.3):
        // see the note in `emit_formula`. These must be reduced via
        // `libsugar::wp` before reaching the Coq backend.
        // TODO(wp-as-formula PR1+): teach sugar-ir-codegen to emit this arm.
        Formula::Substitute { .. } | Formula::Apply { .. } => {
            unreachable!(
                "wp-rule schema node reached the Coq free-var collector; \
                 must be reduced via libsugar::wp first"
            )
        }
        Formula::DivergenceBetween { source, target } => {
            collect_free_vars_formula(source, out, bound);
            collect_free_vars_formula(target, out, bound);
        }
    }
}
pub fn collect_free_vars_term(
    term: &Term,
    out: &mut BTreeMap<String, String>,
    bound: &BTreeSet<String>,
) {
    match term {
        Term::Var { name, .. } => {
            if !bound.contains(name) {
                out.entry(name.clone()).or_insert("Int".to_string());
            }
        }
        Term::Const { .. } => {}
        Term::Ctor { args, .. } => {
            for a in args {
                collect_free_vars_term(a, out, bound);
            }
        }
        Term::Lambda {
            param_name,
            param_sort: _,
            body,
            ..
        } => {
            let mut nb = bound.clone();
            nb.insert(param_name.clone());
            collect_free_vars_term(body, out, &nb);
        }
        Term::Let { bindings, body, .. } => {
            let mut current_bound = bound.clone();
            for b in bindings {
                collect_free_vars_term(&b.bound_term, out, &current_bound);
                current_bound.insert(b.name.clone());
            }
            collect_free_vars_term(body, out, &current_bound);
        }
    }
}

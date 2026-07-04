// SPDX-License-Identifier: MIT OR Apache-2.0
// GENERATED SMT-LIB v2.6 compiler

use std::collections::{BTreeMap, BTreeSet};
use sugar_ir_compiler::{CompiledFormula, FreeVar};
use sugar_ir_types::*;

pub fn emit_term(term: &Term) -> String {
    match term {
        Term::Var { name } => name.clone(),
        Term::Const { value, sort } => {
            let sort_name = match sort { Sort::Primitive { name } => name.as_str() };
            return emit_const_value(value, sort_name);
        },
        Term::Ctor { name, args } => {
            if args.is_empty() { return name.clone(); };
            let args_str = args.iter();
            let args_str = args_str.map(|a| emit_term(a));
            let args_str: Vec<String> = args_str.collect();
            return format!("({} {})", name, args_str.join(" "));
        },
        Term::Lambda { param_name, param_sort, body } => {
            let sort_str = emit_sort(param_sort);
            let body_str = emit_term(body);
            return format!("(lambda (({} {})) {})", param_name, sort_str, body_str);
        },
        Term::Let { bindings, body } => {
            let binding_strs = bindings.iter();
            let binding_strs = binding_strs.map(|b| format!("({} {})", b.name, emit_term(&b.bound_term)));
            let binding_strs: Vec<String> = binding_strs.collect();
            let body_str = emit_term(body);
            return format!("(let ({}) {})", binding_strs.join(" "), body_str);
        },
    }
}
pub fn emit_formula(formula: &Formula) -> String {
    match formula {
        Formula::Atomic { name, args } => {
            let smt_name = smt_atomic_name(name);
            if args.is_empty() { return smt_name.to_string(); };
            let args_str = args.iter();
            let args_str = args_str.map(|a| emit_term(a));
            let args_str: Vec<String> = args_str.collect();
            return format!("({} {})", smt_name, args_str.join(" "));
        },
        Formula::Connective { kind, operands } => {
            let op = match kind.as_str() { "implies" => "=>", other => other };
            let ops_str = operands.iter();
            let ops_str = ops_str.map(|o| emit_formula(o));
            let ops_str: Vec<String> = ops_str.collect();
            return format!("({} {})", op, ops_str.join(" "));
        },
        Formula::Quantifier { kind, name, sort, body } => {
            let sort_str = emit_sort(sort);
            let body_str = emit_formula(body);
            return format!("({} (({} {})) {})", kind, name, sort_str, body_str);
        },
        Formula::Choice { var_name, sort, body } => {
            let sort_str = emit_sort(sort);
            let body_str = emit_formula(body);
            let var_y = format!("{}_y", var_name);
            let body_y = body_str.replace(var_name, &var_y);
            let unique = format!("(and {} (forall (({} {})) (=> {} (= {} {}))))", body_str, var_y, sort_str, body_y, var_y, var_name);
            return format!("(exists (({} {})) {})", var_name, sort_str, unique);
        },
    }
}
fn emit_sort(sort: &Sort) -> String {
    match sort {
        Sort::Primitive { name } => name.clone(),
    }
}
fn emit_const_value(value: &serde_json::Value, _sort_name: &str) -> String {
    match value {
        serde_json::Value::Number(n) => if let Some(i) = n.as_i64() { i.to_string() } else if let Some(u) = n.as_u64() { u.to_string() } else { n.to_string() },
        serde_json::Value::Bool(b) => if *b { "true".to_string() } else { "false".to_string() },
        serde_json::Value::String(s) => format!("\"{}\"", s),
        _ => "0".to_string(),
    }
}
fn smt_atomic_name(name: &str) -> &str {
    match name {
        "\u{2260}" => "distinct",
        "\u{2264}" => "<=",
        "\u{2265}" => ">=",
        other => other,
    }
}
pub fn collect_free_vars_formula(formula: &Formula, out: &mut BTreeMap<String, String>, bound: &BTreeSet<String>) {
    match formula {
        Formula::Atomic { args, .. } => {
            for a in args {
                collect_free_vars_term(a, out, bound);
            }
        },
        Formula::Connective { operands, .. } => {
            for o in operands {
                collect_free_vars_formula(o, out, bound);
            }
        },
        Formula::Quantifier { kind: _, name, sort: _, body } => {
            let mut nb = bound.clone();
            nb.insert(name.clone());
            collect_free_vars_formula(body, out, &nb);
        },
        Formula::Choice { var_name, sort: _, body } => {
            let mut nb = bound.clone();
            nb.insert(var_name.clone());
            collect_free_vars_formula(body, out, &nb);
        },
    }
}
pub fn collect_free_vars_term(term: &Term, out: &mut BTreeMap<String, String>, bound: &BTreeSet<String>) {
    match term {
        Term::Var { name } => if !bound.contains(name) { out.entry(name.clone()).or_insert("Int".to_string()); },
        Term::Const { .. } => {
        },
        Term::Ctor { args, .. } => {
            for a in args {
                collect_free_vars_term(a, out, bound);
            }
        },
        Term::Lambda { param_name, param_sort: _, body } => {
            let mut nb = bound.clone();
            nb.insert(param_name.clone());
            collect_free_vars_term(body, out, &nb);
        },
        Term::Let { bindings, body } => {
            let mut current_bound = bound.clone();
            for b in bindings {
                collect_free_vars_term(&b.bound_term, out, &current_bound);
                current_bound.insert(b.name.clone());
            }
            collect_free_vars_term(body, out, &current_bound);
        },
    }
}
pub fn compile_formula(formula: &Formula) -> CompiledFormula {
    let mut free_vars = BTreeMap::new();
    let bound = BTreeSet::new();
    collect_free_vars_formula(formula, &mut free_vars, &bound);
    let mut preamble = String::new();
    preamble.push_str("(set-logic ALL)\n");
    for (name, sort) in free_vars.iter() {
        preamble.push_str(&format!("(declare-const {} {})\n", name, sort));
    }
    let body = format!("(assert (not {}))\n(check-sat)\n", emit_formula(formula));
    let free_vars_vec = free_vars.into_iter().map(|(name, sort)| FreeVar { name, sort });
    let free_vars_vec = free_vars_vec.collect();
    return CompiledFormula { preamble, body, free_vars: free_vars_vec };
}

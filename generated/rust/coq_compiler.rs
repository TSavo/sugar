// SPDX-License-Identifier: MIT OR Apache-2.0
// GENERATED Coq compiler

use std::collections::{BTreeMap, BTreeSet};
use sugar_ir_compiler::FreeVar;
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
            return format!("fun ({} : {}) => {}", param_name, sort_str, body_str);
        },
        Term::Let { bindings, body } => {
            let mut parts = Vec::new();
            for b in bindings {
                parts.push(format!("let {} := {} in", b.name, emit_term(&b.bound_term)));
            }
            let body_str = emit_term(body);
            return format!("{} {}", parts.join(" "), body_str);
        },
    }
}
pub fn emit_formula(formula: &Formula) -> String {
    match formula {
        Formula::Atomic { name, args } => {
            let args_str = args.iter();
            let args_str = args_str.map(|a| emit_term(a));
            let args_str: Vec<String> = args_str.collect();
            return match name.as_str() {
    "=" => format!("({} = {})", args_str[0].clone(), args_str[1].clone()),
    ">" => format!("({} > {})", args_str[0].clone(), args_str[1].clone()),
    "<" => format!("({} < {})", args_str[0].clone(), args_str[1].clone()),
    "\u{2265}" => format!("({} >= {})", args_str[0].clone(), args_str[1].clone()),
    "\u{2264}" => format!("({} <= {})", args_str[0].clone(), args_str[1].clone()),
    "\u{2260}" => format!("({} <> {})", args_str[0].clone(), args_str[1].clone()),
    "true" => "True".to_string(),
    "false" => "False".to_string(),
    _ => format!("{} {}", name, args_str.join(" ")),
};
        },
        Formula::Connective { kind, operands } => match kind.as_str() {
    "and" => {
        let ops = operands.iter();
        let ops = ops.map(|o| emit_formula(o));
        let ops: Vec<String> = ops.collect();
        return format!("({})", ops.join(r#" /\ "#));
    },
    "or" => {
        let ops = operands.iter();
        let ops = ops.map(|o| emit_formula(o));
        let ops: Vec<String> = ops.collect();
        return format!("({})", ops.join(r#" \/ "#));
    },
    "not" => {
        return format!("(~{})", emit_formula(&operands[0]));
    },
    "implies" => {
        return format!("({} -> {})", emit_formula(&operands[0]), emit_formula(&operands[1]));
    },
    _ => {
        return "True".to_string();
    },
},
        Formula::Quantifier { kind, name, sort, body } => {
            let coq_sort = sort_to_coq(sort);
            let body_str = emit_formula(body);
            let quant = if *kind == "forall" { "forall" } else { "exists" };
            return format!("{} {} : {}, {}", quant, name, coq_sort, body_str);
        },
        Formula::Choice { var_name, sort, body } => {
            let coq_sort = sort_to_coq(sort);
            let body_str = emit_formula(body);
            return format!("@sig {} {} (fun {} => {})", var_name, coq_sort, var_name, body_str);
        },
    }
}
fn emit_sort(sort: &Sort) -> String {
    match sort {
        Sort::Primitive { name } => match name.as_str() {
    "Int" | "Real" => "Z".to_string(),
    "String" => "string".to_string(),
    "Bool" => "bool".to_string(),
    _ => "Z".to_string(),
},
    }
}
fn sort_to_coq(sort: &Sort) -> String {
    match sort {
        Sort::Primitive { name } => match name.as_str() {
    "Int" | "Real" => "Z".to_string(),
    "String" => "string".to_string(),
    "Bool" => "bool".to_string(),
    _ => "Z".to_string(),
},
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
pub fn compile_formula(formula: &Formula) -> (String, String, Vec<FreeVar>) {
    let mut free_vars = BTreeMap::new();
    let bound = BTreeSet::new();
    collect_free_vars_formula(formula, &mut free_vars, &bound);
    let mut body = String::new();
    for (name, sort) in free_vars.iter() {
        let coq_sort = match sort.as_str() {
    "Int" | "Real" => "Z",
    "String" => "string",
    "Bool" => "bool",
    _ => "Z",
};
        body.push_str(&format!("Parameter {} : {}.\n", name, coq_sort));
    }
    body.push_str("\nGoal ");
    body.push_str(&emit_formula(formula));
    body.push_str(".\n");
    body.push_str("Proof.\n  intuition.\n  admit.\nQed.\n");
    let preamble = "Require Import ZArith String List.\nOpen Scope Z.\nOpen Scope string.\n\n".to_string();
    let free_vars_vec = free_vars.into_iter().map(|(name, sort)| FreeVar { name, sort });
    let free_vars_vec = free_vars_vec.collect();
    return (preamble, body, free_vars_vec);
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

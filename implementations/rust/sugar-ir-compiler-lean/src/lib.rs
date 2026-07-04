// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Lean 4 compiler for IR obligations.

use std::collections::BTreeMap;
use std::sync::Arc;

use serde_json::Value as Json;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value as CValue};
use sugar_ir_compiler::{
    Capabilities, CompileError, CompiledFormula, CompilerInput, FreeVar, IrCompiler, OpacityEntry,
    OpacityManifest, PROTOCOL_VERSION,
};
use sugar_ir_types::{Formula, Sort, Term};

pub const DIALECT: &str = "lean";
pub const COMPILER_NAME: &str = "lean4-mathlib-reference";
pub const COMPILER_VERSION: &str = env!("CARGO_PKG_VERSION");
pub const THEOREM_NAME: &str = "sugar_obligation";

pub struct LeanCompiler;

impl LeanCompiler {
    pub fn new() -> Self {
        Self
    }
}

impl Default for LeanCompiler {
    fn default() -> Self {
        Self::new()
    }
}

impl IrCompiler for LeanCompiler {
    fn compile_typed(
        &self,
        ir: &CompilerInput,
        dialect: &str,
    ) -> Result<CompiledFormula, CompileError> {
        if dialect != DIALECT {
            return Err(CompileError::UnsupportedDialect(dialect.to_string()));
        }
        compile_input_to_parts(ir)
    }

    fn capabilities(&self) -> Capabilities {
        Capabilities {
            name: COMPILER_NAME.to_string(),
            version: COMPILER_VERSION.to_string(),
            protocol_version: PROTOCOL_VERSION.to_string(),
            dialects: vec![DIALECT.to_string()],
            supported_sorts: vec![
                "Int".to_string(),
                "Bool".to_string(),
                "Real".to_string(),
                "String".to_string(),
                "Function".to_string(),
                "Dependent".to_string(),
                "CategoricalStructure".to_string(),
            ],
            supported_predicates: vec![
                "=".to_string(),
                "!=".to_string(),
                "<".to_string(),
                "<=".to_string(),
                ">".to_string(),
                ">=".to_string(),
                "and".to_string(),
                "or".to_string(),
                "not".to_string(),
                "implies".to_string(),
                "forall".to_string(),
                "exists".to_string(),
                "higher-order".to_string(),
                "dependent_type".to_string(),
                "categorical_structure".to_string(),
                "mathlib".to_string(),
            ],
        }
    }
}

fn compile_input_to_parts(input: &CompilerInput) -> Result<CompiledFormula, CompileError> {
    match input {
        CompilerInput::Formula(formula) => compile_formula_to_parts(formula.formula()),
        CompilerInput::Term(term) => compile_term_to_parts(term),
        CompilerInput::EquationalTheory(_) => Err(CompileError::UnsupportedPredicate(
            "equational_theory".to_string(),
        )),
    }
}

pub fn compile_term_to_parts(term: &Term) -> Result<CompiledFormula, CompileError> {
    let mut ctx = EmitContext::default();
    let expr = emit_term(term, &mut ctx)?;
    let mut body = String::new();
    body.push_str(&format!(
        "theorem {THEOREM_NAME} : ({expr}) = ({expr}) := by\n  aesop\n\n"
    ));
    body.push_str(&format!("#print axioms {THEOREM_NAME}\n"));
    Ok(CompiledFormula {
        preamble: lean_preamble(),
        body,
        free_vars: vec![],
        opacity_manifest: opacity_manifest(ctx.opacities),
        metadata: Json::Null,
    })
}

pub fn compile_formula_to_parts(formula: &Formula) -> Result<CompiledFormula, CompileError> {
    let mut ctx = EmitContext::default();
    collect_formula(formula, &mut ctx, &mut BTreeMap::new())?;
    let proposition = emit_formula(formula, &mut ctx)?;
    ctx.sort_opacities();

    let mut binders = Vec::new();
    for (name, ty) in &ctx.type_params {
        binders.push(format!("({} : {ty})", lean_ident(name)));
    }
    for (name, sig) in &ctx.functions {
        binders.push(format!("({} : {})", lean_ident(name), sig.as_lean_type()));
    }
    for (name, sig) in &ctx.predicates {
        binders.push(format!("({} : {})", lean_ident(name), sig.as_lean_type()));
    }
    for (name, sort) in &ctx.free_vars {
        binders.push(format!("({} : {sort})", lean_ident(name)));
    }

    let theorem_head = if binders.is_empty() {
        format!("theorem {THEOREM_NAME} : {proposition} := by\n")
    } else {
        format!(
            "theorem {THEOREM_NAME} {} : {proposition} := by\n",
            binders.join(" ")
        )
    };

    let mut body = String::new();
    body.push_str(&theorem_head);
    body.push_str("  aesop\n\n");
    body.push_str(&format!("#print axioms {THEOREM_NAME}\n"));

    let free_vars = ctx
        .free_vars
        .iter()
        .map(|(name, sort)| FreeVar {
            name: name.clone(),
            sort: sort.clone(),
        })
        .collect();

    Ok(CompiledFormula {
        preamble: lean_preamble(),
        body,
        free_vars,
        opacity_manifest: opacity_manifest(ctx.opacities),
        metadata: Json::Null,
    })
}

fn lean_preamble() -> String {
    "import Mathlib\n\nset_option autoImplicit false\n\n".to_string()
}

fn opacity_manifest(opacities: Vec<OpacityEntry>) -> OpacityManifest {
    OpacityManifest {
        protocol_version: "ir-compiler-protocol/2".to_string(),
        compiler: DIALECT.to_string(),
        compiler_version: COMPILER_VERSION.to_string(),
        opacities,
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct LeanSignature {
    args: Vec<String>,
    ret: String,
}

impl LeanSignature {
    fn as_lean_type(&self) -> String {
        if self.args.is_empty() {
            self.ret.clone()
        } else {
            let mut parts = self.args.clone();
            parts.push(self.ret.clone());
            parts.join(" -> ")
        }
    }
}

#[derive(Default)]
struct EmitContext {
    free_vars: BTreeMap<String, String>,
    type_params: BTreeMap<String, String>,
    functions: BTreeMap<String, LeanSignature>,
    predicates: BTreeMap<String, LeanSignature>,
    opacities: Vec<OpacityEntry>,
}

impl EmitContext {
    fn sort_opacities(&mut self) {
        self.opacities.sort_by(|a, b| {
            a.position_cid
                .cmp(&b.position_cid)
                .then_with(|| a.reason_code.cmp(&b.reason_code))
        });
        self.opacities.dedup();
    }
}

fn collect_formula(
    formula: &Formula,
    ctx: &mut EmitContext,
    bound: &mut BTreeMap<String, String>,
) -> Result<(), CompileError> {
    match formula {
        Formula::Atomic { name, args } => {
            if is_builtin_atomic(name) {
                let expected = common_atomic_sort(name, args, bound, ctx)?;
                for arg in args {
                    collect_term(arg, ctx, bound, expected.as_deref())?;
                }
            } else {
                let predicate = lean_ident(name);
                if !is_external_lean_name(name) {
                    let arg_sorts = args
                        .iter()
                        .map(|arg| term_sort_hint(arg, bound, ctx).unwrap_or_else(|| "Int".into()))
                        .collect();
                    ctx.predicates.entry(predicate).or_insert(LeanSignature {
                        args: arg_sorts,
                        ret: "Prop".to_string(),
                    });
                }
                for arg in args {
                    collect_term(arg, ctx, bound, None)?;
                }
            }
        }
        Formula::And { operands } | Formula::Or { operands } | Formula::Implies { operands } => {
            for operand in operands {
                collect_formula(operand, ctx, bound)?;
            }
        }
        Formula::Not { operands } => {
            for operand in operands {
                collect_formula(operand, ctx, bound)?;
            }
        }
        Formula::Forall { name, sort, body } | Formula::Exists { name, sort, body } => {
            let lean_sort = emit_sort(sort, ctx)?;
            let lean_name = lean_ident(name);
            bound.insert(lean_name.clone(), lean_sort);
            collect_formula(body, ctx, bound)?;
            bound.remove(&lean_name);
        }
        Formula::Choice {
            var_name,
            sort,
            body,
        } => {
            let lean_sort = emit_sort(sort, ctx)?;
            let lean_name = lean_ident(var_name);
            bound.insert(lean_name.clone(), lean_sort);
            collect_formula(body, ctx, bound)?;
            bound.remove(&lean_name);
        }
        // wp-rule schema nodes (spec 2026-05-13-wp-as-formula.md §2.3):
        // `substitute` / `apply` appear only inside an unreduced `wp_rule`
        // term and are eliminated by `libsugar::wp` before any formula
        // reaches the Lean backend. Reaching this arm is a bug.
        Formula::Substitute { .. } | Formula::Apply { .. } => {
            return Err(CompileError::Internal(
                "wp-rule schema node (substitute/apply) reached the Lean collector; \
                 it must be reduced via libsugar::wp before compilation"
                    .to_string(),
            ));
        }
        Formula::DivergenceBetween { .. } => {
            return Err(CompileError::Internal(
                "platform divergence formula reached the Lean collector; \
                 stage 4 must lower it before compilation"
                    .to_string(),
            ));
        }
    }
    Ok(())
}

fn collect_term(
    term: &Term,
    ctx: &mut EmitContext,
    bound: &mut BTreeMap<String, String>,
    expected: Option<&str>,
) -> Result<(), CompileError> {
    match term {
        Term::Var { name } => {
            let lean_name = lean_ident(name);
            if !bound.contains_key(&lean_name) {
                ctx.free_vars
                    .entry(lean_name)
                    .or_insert_with(|| expected.unwrap_or("Int").to_string());
            }
        }
        Term::Const { sort, .. } => {
            let _ = emit_sort(sort, ctx)?;
        }
        Term::Ctor { name, args } if is_builtin_arith(name) && args.len() == 2 => {
            // Interpreted homogeneous arithmetic (+, -, *): the operands share the
            // result sort, and the operator is a builtin, NOT an uninterpreted
            // function. So `(- a b)` against a `Real` bound makes `a`, `b` Real.
            for arg in args {
                collect_term(arg, ctx, bound, expected)?;
            }
        }
        Term::Ctor { name, args } => {
            let lean_name = lean_ident(name);
            let bound_function =
                bound.contains_key(&lean_name) || ctx.free_vars.contains_key(&lean_name);
            let arg_sorts: Vec<String> = args
                .iter()
                .map(|arg| term_sort_hint(arg, bound, ctx).unwrap_or_else(|| "Int".to_string()))
                .collect();
            if !bound_function && !is_external_lean_name(name) {
                ctx.functions
                    .entry(lean_name)
                    .or_insert_with(|| LeanSignature {
                        args: arg_sorts.clone(),
                        ret: expected.unwrap_or("Int").to_string(),
                    });
            }
            for (arg, arg_sort) in args.iter().zip(arg_sorts.iter()) {
                collect_term(arg, ctx, bound, Some(arg_sort))?;
            }
        }
        Term::Lambda {
            param_name,
            param_sort,
            body,
        } => {
            let lean_sort = emit_sort(param_sort, ctx)?;
            let lean_name = lean_ident(param_name);
            bound.insert(lean_name.clone(), lean_sort);
            collect_term(body, ctx, bound, expected)?;
            bound.remove(&lean_name);
        }
        Term::Let { bindings, body } => {
            for binding in bindings {
                collect_term(&binding.bound_term, ctx, bound, None)?;
                bound.insert(lean_ident(&binding.name), "Int".to_string());
            }
            collect_term(body, ctx, bound, expected)?;
            for binding in bindings {
                bound.remove(&lean_ident(&binding.name));
            }
        }
    }
    Ok(())
}

fn emit_formula(formula: &Formula, ctx: &mut EmitContext) -> Result<String, CompileError> {
    match formula {
        Formula::Atomic { name, args } => emit_atomic(name, args, ctx),
        Formula::And { operands } => {
            if operands.is_empty() {
                return Ok("True".to_string());
            }
            let parts = operands
                .iter()
                .map(|o| emit_formula(o, ctx))
                .collect::<Result<Vec<_>, _>>()?;
            Ok(format!("({})", parts.join(" ∧ ")))
        }
        Formula::Or { operands } => {
            if operands.is_empty() {
                return Ok("False".to_string());
            }
            let parts = operands
                .iter()
                .map(|o| emit_formula(o, ctx))
                .collect::<Result<Vec<_>, _>>()?;
            Ok(format!("({})", parts.join(" ∨ ")))
        }
        Formula::Not { operands } => {
            let operand = exactly_one_operand("not", operands)?;
            Ok(format!("(¬ {})", emit_formula(operand, ctx)?))
        }
        Formula::Implies { operands } => {
            if operands.len() != 2 {
                return Err(CompileError::MalformedIr(
                    "implies expects exactly two operands".to_string(),
                ));
            }
            Ok(format!(
                "({} -> {})",
                emit_formula(&operands[0], ctx)?,
                emit_formula(&operands[1], ctx)?
            ))
        }
        Formula::Forall { name, sort, body } => Ok(format!(
            "∀ ({} : {}), {}",
            lean_ident(name),
            emit_sort(sort, ctx)?,
            emit_formula(body, ctx)?
        )),
        Formula::Exists { name, sort, body } => Ok(format!(
            "∃ ({} : {}), {}",
            lean_ident(name),
            emit_sort(sort, ctx)?,
            emit_formula(body, ctx)?
        )),
        Formula::Choice {
            var_name,
            sort,
            body,
        } => Ok(format!(
            "∃ ({} : {}), {}",
            lean_ident(var_name),
            emit_sort(sort, ctx)?,
            emit_formula(body, ctx)?
        )),
        // wp-rule schema nodes (spec 2026-05-13-wp-as-formula.md §2.3):
        // see the note in `collect_formula`. These must be reduced via
        // `libsugar::wp` before reaching the Lean backend.
        Formula::Substitute { .. } | Formula::Apply { .. } => Err(CompileError::Internal(
            "wp-rule schema node (substitute/apply) reached the Lean formula emitter; \
             it must be reduced via libsugar::wp before compilation"
                .to_string(),
        )),
        Formula::DivergenceBetween { .. } => Err(CompileError::Internal(
            "platform divergence formula reached the Lean formula emitter; \
             stage 4 must lower it before compilation"
                .to_string(),
        )),
    }
}

fn emit_atomic(name: &str, args: &[Term], ctx: &mut EmitContext) -> Result<String, CompileError> {
    match lean_atomic_name(name).as_str() {
        "True" if args.is_empty() => Ok("True".to_string()),
        "False" if args.is_empty() => Ok("False".to_string()),
        "=" | "≠" | "<" | "<=" | ">" | ">=" => {
            if args.len() != 2 {
                return Err(CompileError::MalformedIr(format!(
                    "predicate {name} expects exactly two arguments"
                )));
            }
            let lhs = emit_term(&args[0], ctx)?;
            let rhs = emit_term(&args[1], ctx)?;
            Ok(format!("({lhs} {} {rhs})", lean_atomic_name(name)))
        }
        other => {
            let args = args
                .iter()
                .map(|arg| emit_term(arg, ctx))
                .collect::<Result<Vec<_>, _>>()?;
            if args.is_empty() {
                Ok(other.to_string())
            } else {
                Ok(format!("({} {})", other, args.join(" ")))
            }
        }
    }
}

fn emit_term(term: &Term, ctx: &mut EmitContext) -> Result<String, CompileError> {
    match term {
        Term::Var { name } => Ok(lean_ident(name)),
        Term::Const { value, sort } => emit_const(value, sort),
        Term::Ctor { name, args } if is_builtin_arith(name) && args.len() == 2 => {
            // Interpreted arithmetic renders infix: `(a - b)`, not a prefix
            // application of a sanitized identifier.
            let lhs = emit_term(&args[0], ctx)?;
            let rhs = emit_term(&args[1], ctx)?;
            Ok(format!("({lhs} {name} {rhs})"))
        }
        Term::Ctor { name, args } => {
            let name = lean_ident(name);
            let args = args
                .iter()
                .map(|arg| emit_term(arg, ctx))
                .collect::<Result<Vec<_>, _>>()?;
            if args.is_empty() {
                Ok(name)
            } else {
                Ok(format!("({} {})", name, args.join(" ")))
            }
        }
        Term::Lambda {
            param_name,
            param_sort,
            body,
        } => Ok(format!(
            "(fun ({} : {}) => {})",
            lean_ident(param_name),
            emit_sort(param_sort, ctx)?,
            emit_term(body, ctx)?
        )),
        Term::Let { bindings, body } => {
            let mut out = String::new();
            for binding in bindings {
                out.push_str(&format!(
                    "let {} := {}; ",
                    lean_ident(&binding.name),
                    emit_term(&binding.bound_term, ctx)?
                ));
            }
            out.push_str(&emit_term(body, ctx)?);
            Ok(format!("({out})"))
        }
    }
}

fn emit_const(value: &Json, sort: &Sort) -> Result<String, CompileError> {
    let sort_name = primitive_sort_name(sort, value)?;
    // A `Real` const is carried as a canonical decimal STRING (e.g. "0.00000015",
    // or "-0.00000015"). Emit it as an ascribed Lean real literal, not a quoted
    // string, so Mathlib reads it as `Real` rather than a `Nat`/`String`.
    if sort_name == "Real" {
        if let Json::String(s) = value {
            return Ok(format!("({s} : Real)"));
        }
    }
    match value {
        Json::Number(n) => {
            if let Some(i) = n.as_i64() {
                if i < 0 {
                    Ok(format!("({i} : {sort_name})"))
                } else {
                    Ok(i.to_string())
                }
            } else if let Some(u) = n.as_u64() {
                Ok(u.to_string())
            } else {
                Ok(format!("({n} : {sort_name})"))
            }
        }
        Json::Bool(b) => Ok(if *b { "true".into() } else { "false".into() }),
        Json::String(s) => {
            serde_json::to_string(s).map_err(|e| CompileError::Internal(e.to_string()))
        }
        _ => Err(CompileError::UnsupportedSort(
            "Lean constants require number, bool, or string values".to_string(),
        )),
    }
}

fn emit_sort(sort: &Sort, ctx: &mut EmitContext) -> Result<String, CompileError> {
    match sort {
        Sort::Primitive { name } => match name.as_str() {
            "Int" => Ok("Int".to_string()),
            "Real" => Ok("Real".to_string()),
            "Bool" => Ok("Bool".to_string()),
            "String" => Ok("String".to_string()),
            other => {
                let lean_name = lean_ident(other);
                ctx.type_params
                    .entry(lean_name.clone())
                    .or_insert_with(|| "Type".to_string());
                Ok(lean_name)
            }
        },
        Sort::Function { args, ret } => {
            let mut parts = args
                .iter()
                .map(|arg| emit_sort_paren(arg, ctx))
                .collect::<Result<Vec<_>, _>>()?;
            parts.push(emit_sort_paren(ret, ctx)?);
            Ok(parts.join(" -> "))
        }
        Sort::Dependent {
            name,
            index_var,
            index_sort,
        } => {
            let type_name = lean_ident(name);
            let index_sort = emit_sort(index_sort, ctx)?;
            ctx.type_params
                .entry(type_name.clone())
                .or_insert_with(|| format!("{index_sort} -> Type"));
            Ok(format!(
                "∀ ({} : {}), {} {}",
                lean_ident(index_var),
                index_sort,
                type_name,
                lean_ident(index_var)
            ))
        }
        Sort::Region { .. } => {
            let serialized = serde_json::to_value(sort).unwrap_or(Json::Null);
            ctx.opacities.push(OpacityEntry {
                position_cid: position_cid_of(&serialized),
                reason_code: "other:region_sort".to_string(),
            });
            Ok("Int".to_string())
        }
    }
}

fn emit_sort_paren(sort: &Sort, ctx: &mut EmitContext) -> Result<String, CompileError> {
    match sort {
        Sort::Function { .. } | Sort::Dependent { .. } => {
            Ok(format!("({})", emit_sort(sort, ctx)?))
        }
        Sort::Primitive { .. } | Sort::Region { .. } => emit_sort(sort, ctx),
    }
}

fn primitive_sort_name(sort: &Sort, value: &Json) -> Result<&'static str, CompileError> {
    match sort {
        Sort::Primitive { name } if name == "Int" => Ok("Int"),
        Sort::Primitive { name } if name == "Real" => Ok("Real"),
        Sort::Primitive { name } if name == "Bool" => Ok("Bool"),
        Sort::Primitive { name } if name == "String" => Ok("String"),
        Sort::Primitive { name } => Err(CompileError::UnsupportedSort(format!(
            "Lean const literal {value} has unsupported primitive sort {name}"
        ))),
        other => Err(CompileError::UnsupportedSort(format!(
            "Lean const literal {value} has unsupported sort {other:?}"
        ))),
    }
}

fn exactly_one_operand<'a>(
    kind: &str,
    operands: &'a [Formula],
) -> Result<&'a Formula, CompileError> {
    if operands.len() == 1 {
        Ok(&operands[0])
    } else {
        Err(CompileError::MalformedIr(format!(
            "{kind} expects exactly one operand"
        )))
    }
}

fn common_atomic_sort(
    name: &str,
    args: &[Term],
    bound: &BTreeMap<String, String>,
    ctx: &mut EmitContext,
) -> Result<Option<String>, CompileError> {
    if !matches!(
        lean_atomic_name(name).as_str(),
        "=" | "≠" | "<" | "<=" | ">" | ">="
    ) {
        return Ok(None);
    }
    for arg in args {
        if let Some(sort) = term_sort_hint(arg, bound, ctx) {
            return Ok(Some(sort));
        }
    }
    Ok(Some("Int".to_string()))
}

fn term_sort_hint(
    term: &Term,
    bound: &BTreeMap<String, String>,
    ctx: &mut EmitContext,
) -> Option<String> {
    match term {
        Term::Var { name } => {
            let lean_name = lean_ident(name);
            bound
                .get(&lean_name)
                .cloned()
                .or_else(|| ctx.free_vars.get(&lean_name).cloned())
        }
        Term::Const { sort, .. } => emit_sort(sort, ctx).ok(),
        Term::Ctor { .. } | Term::Lambda { .. } | Term::Let { .. } => None,
    }
}

fn is_builtin_atomic(name: &str) -> bool {
    matches!(
        lean_atomic_name(name).as_str(),
        "True" | "False" | "=" | "≠" | "<" | "<=" | ">" | ">="
    )
}

/// Interpreted homogeneous arithmetic operators: lowered infix over the operand
/// sort, never as uninterpreted functions. Matches the smt-lib interpreted set
/// (`+ - *`); integer `/`/`%` stay uninterpreted there and are not lowered here.
fn is_builtin_arith(name: &str) -> bool {
    matches!(name, "+" | "-" | "*")
}

fn lean_atomic_name(name: &str) -> String {
    match name {
        "true" => "True".to_string(),
        "false" => "False".to_string(),
        "eq" | "=" => "=".to_string(),
        "ne" | "neq" | "!=" | "\u{2260}" => "≠".to_string(),
        "lt" | "<" => "<".to_string(),
        "lte" | "<=" | "\u{2264}" => "<=".to_string(),
        "gt" | ">" => ">".to_string(),
        "gte" | ">=" | "\u{2265}" => ">=".to_string(),
        other => lean_ident(other),
    }
}

fn is_external_lean_name(name: &str) -> bool {
    name.contains('.') || matches!(name, "id" | "True" | "False")
}

fn lean_ident(name: &str) -> String {
    if name.is_empty() {
        return "x".to_string();
    }
    if name.contains('.') {
        return name
            .split('.')
            .map(lean_ident_segment)
            .collect::<Vec<_>>()
            .join(".");
    }
    lean_ident_segment(name)
}

fn lean_ident_segment(segment: &str) -> String {
    let mut out = String::new();
    for (idx, ch) in segment.chars().enumerate() {
        let ok = ch == '_' || ch.is_ascii_alphanumeric();
        if ok && !(idx == 0 && ch.is_ascii_digit()) {
            out.push(ch);
        } else {
            out.push('_');
        }
    }
    if out.is_empty() || out == "_" {
        "x".to_string()
    } else {
        match out.as_str() {
            "theorem" | "axiom" | "def" | "fun" | "let" | "in" | "by" | "forall" | "exists" => {
                format!("{out}_")
            }
            _ => out,
        }
    }
}

fn position_cid_of(value: &Json) -> String {
    let canonical = encode_jcs(&to_cvalue(value));
    blake3_512_of(canonical.as_bytes())
}

fn to_cvalue(value: &Json) -> Arc<CValue> {
    match value {
        Json::Null => CValue::null(),
        Json::Bool(b) => CValue::boolean(*b),
        Json::Number(n) => {
            if let Some(i) = n.as_i64() {
                CValue::integer(i128::from(i))
            } else if let Some(u) = n.as_u64() {
                if let Ok(i) = i64::try_from(u) {
                    CValue::integer(i128::from(i))
                } else {
                    CValue::string(u.to_string())
                }
            } else {
                CValue::string(n.to_string())
            }
        }
        Json::String(s) => CValue::string(s.clone()),
        Json::Array(items) => CValue::array(items.iter().map(to_cvalue).collect()),
        Json::Object(map) => CValue::object(map.iter().map(|(k, v)| (k.clone(), to_cvalue(v)))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn emit_simple_formula() {
        let input = CompilerInput::decode_json(json!({
            "kind": "atomic",
            "name": "true",
            "args": []
        }))
        .expect("fixture decodes");
        let out = LeanCompiler::new()
            .compile_typed(&input, DIALECT)
            .expect("compile")
            .script();
        assert!(out.contains("theorem sugar_obligation : True := by"));
    }
}

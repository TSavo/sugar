// SPDX-License-Identifier: Apache-2.0
//
// Maude compiler for equational theory obligations.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value as Json};
use sugar_ir_compiler::{
    Capabilities, CompileError, CompiledFormula, FreeVar, IrCompiler, OpacityManifest,
    PROTOCOL_VERSION,
};
use sugar_ir_types::{IrTerm, Sort};

pub const DIALECT: &str = "maude";
pub const COMPILER_NAME: &str = "maude-equational-reference";
pub const COMPILER_VERSION: &str = env!("CARGO_PKG_VERSION");

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MaudeQueries {
    pub lhs_reduce: String,
    pub rhs_reduce: String,
    pub search: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TrsRule {
    pub lhs: String,
    pub rhs: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TrsOperator {
    pub name: String,
    pub arity: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TrsSpec {
    pub name: String,
    pub variables: Vec<String>,
    pub operators: Vec<TrsOperator>,
    pub rules: Vec<TrsRule>,
    pub has_ac_builtin: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CompiledMaude {
    pub compiled: CompiledFormula,
    pub module_name: String,
    pub module_source: String,
    pub queries: MaudeQueries,
    pub trs: TrsSpec,
}

#[derive(Debug, Clone, Deserialize)]
struct RawObligation {
    kind: String,
    name: Option<String>,
    theory: RawTheory,
    obligation: RawEquation,
}

#[derive(Debug, Clone, Deserialize)]
struct RawTheory {
    name: String,
    #[serde(default)]
    sorts: Vec<String>,
    #[serde(default)]
    subsorts: Vec<RawSubsort>,
    #[serde(default)]
    operators: Vec<RawOperator>,
    #[serde(default)]
    variables: Vec<RawVariable>,
    #[serde(default)]
    equations: Vec<RawEquation>,
}

#[derive(Debug, Clone, Deserialize)]
struct RawSubsort {
    subsort: String,
    supersort: String,
}

#[derive(Debug, Clone, Deserialize)]
struct RawOperator {
    name: String,
    #[serde(default)]
    maude: Option<String>,
    #[serde(default)]
    arity: Vec<String>,
    result: String,
    #[serde(default)]
    attrs: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct RawVariable {
    name: String,
    sort: String,
}

#[derive(Debug, Clone, Deserialize)]
struct RawEquation {
    #[serde(default)]
    label: Option<String>,
    lhs: IrTerm,
    rhs: IrTerm,
}

#[derive(Debug, Clone)]
struct OperatorInfo {
    source_name: String,
    maude_name: String,
    arity: Vec<String>,
    result: String,
    attrs: Vec<String>,
}

pub struct MaudeCompiler;

impl MaudeCompiler {
    pub fn new() -> Self {
        Self
    }
}

impl Default for MaudeCompiler {
    fn default() -> Self {
        Self::new()
    }
}

impl IrCompiler for MaudeCompiler {
    fn compile(&self, ir: &Json, dialect: &str) -> Result<CompiledFormula, CompileError> {
        if dialect != DIALECT {
            return Err(CompileError::UnsupportedDialect(dialect.to_string()));
        }
        Ok(compile_artifact(ir)?.compiled)
    }

    fn capabilities(&self) -> Capabilities {
        Capabilities {
            name: COMPILER_NAME.to_string(),
            version: COMPILER_VERSION.to_string(),
            protocol_version: PROTOCOL_VERSION.to_string(),
            dialects: vec![DIALECT.to_string()],
            supported_sorts: vec!["equational_theory".to_string()],
            supported_predicates: vec!["equational_theory".to_string()],
        }
    }
}

pub fn emit(ir: &Json) -> Result<String, String> {
    let artifact = compile_artifact(ir).map_err(|e| e.to_string())?;
    Ok(format!(
        "{}{}",
        artifact.compiled.preamble, artifact.compiled.body
    ))
}

pub fn compile_artifact(ir: &Json) -> Result<CompiledMaude, CompileError> {
    let raw: RawObligation =
        serde_json::from_value(ir.clone()).map_err(|e| CompileError::MalformedIr(e.to_string()))?;
    validate_root(&raw)?;

    let module_name = module_name(&raw.theory.name)?;
    let operators = operators_by_name(&raw.theory.operators)?;
    let module_source = render_module(&module_name, &raw.theory, &operators)?;
    let lhs = render_term(&raw.obligation.lhs, &operators)?;
    let rhs = render_term(&raw.obligation.rhs, &operators)?;
    let queries = MaudeQueries {
        lhs_reduce: format!("red in {module_name} : {lhs} ."),
        rhs_reduce: format!("red in {module_name} : {rhs} ."),
        search: format!("search in {module_name} : {lhs} =>* {rhs} ."),
    };
    let mut body = String::new();
    body.push('\n');
    body.push_str(&queries.lhs_reduce);
    body.push('\n');
    body.push_str(&queries.rhs_reduce);
    body.push('\n');
    body.push_str(&queries.search);
    body.push('\n');

    let free_vars = raw
        .theory
        .variables
        .iter()
        .map(|v| FreeVar {
            name: v.name.clone(),
            sort: v.sort.clone(),
        })
        .collect();
    let trs = trs_spec(&module_name, &raw.theory, &operators)?;

    let metadata = json!({
        "maude": {
            "moduleName": module_name.clone(),
            "moduleSource": module_source.clone(),
            "queries": queries.clone(),
            "trs": trs.clone(),
        }
    });

    Ok(CompiledMaude {
        compiled: CompiledFormula {
            preamble: module_source.clone(),
            body,
            free_vars,
            opacity_manifest: OpacityManifest {
                protocol_version: "ir-compiler-protocol/2".to_string(),
                compiler: DIALECT.to_string(),
                compiler_version: COMPILER_VERSION.to_string(),
                opacities: vec![],
            },
            metadata,
        },
        module_name,
        module_source,
        queries,
        trs,
    })
}

fn validate_root(raw: &RawObligation) -> Result<(), CompileError> {
    let accepted =
        raw.kind == "equational_theory" || raw.name.as_deref() == Some("equational_theory");
    if !accepted {
        return Err(CompileError::UnsupportedPredicate(
            raw.name.clone().unwrap_or_else(|| raw.kind.clone()),
        ));
    }
    Ok(())
}

fn operators_by_name(ops: &[RawOperator]) -> Result<BTreeMap<String, OperatorInfo>, CompileError> {
    let mut out = BTreeMap::new();
    for op in ops {
        validate_token(&op.name, "operator name")?;
        if let Some(maude) = &op.maude {
            validate_surface(maude, "maude operator")?;
        }
        for sort in op.arity.iter().chain(std::iter::once(&op.result)) {
            validate_token(sort, "operator sort")?;
        }
        for attr in &op.attrs {
            validate_attr(attr)?;
        }
        let previous = out.insert(
            op.name.clone(),
            OperatorInfo {
                source_name: op.name.clone(),
                maude_name: op.maude.clone().unwrap_or_else(|| op.name.clone()),
                arity: op.arity.clone(),
                result: op.result.clone(),
                attrs: op.attrs.clone(),
            },
        );
        if previous.is_some() {
            return Err(CompileError::MalformedIr(format!(
                "duplicate operator {}",
                op.name
            )));
        }
    }
    Ok(out)
}

fn module_name(name: &str) -> Result<String, CompileError> {
    if name.trim().is_empty() {
        return Err(CompileError::MalformedIr("empty theory name".to_string()));
    }
    let mut out = String::new();
    for ch in name.chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch.to_ascii_uppercase());
        } else if matches!(ch, '-' | '_' | ':' | '.') {
            out.push('-');
        }
    }
    if out.is_empty() {
        return Err(CompileError::MalformedIr(
            "theory name has no Maude-safe characters".to_string(),
        ));
    }
    Ok(out)
}

fn render_module(
    module_name: &str,
    theory: &RawTheory,
    operators: &BTreeMap<String, OperatorInfo>,
) -> Result<String, CompileError> {
    let mut out = String::new();
    out.push_str(&format!("fmod {module_name} is\n"));
    for sort in &theory.sorts {
        validate_token(sort, "sort")?;
        out.push_str(&format!("  sort {sort} .\n"));
    }
    for subsort in &theory.subsorts {
        validate_token(&subsort.subsort, "subsort")?;
        validate_token(&subsort.supersort, "supersort")?;
        out.push_str(&format!(
            "  subsort {} < {} .\n",
            subsort.subsort, subsort.supersort
        ));
    }
    for op in &theory.operators {
        let info = operators.get(&op.name).expect("operator map is complete");
        out.push_str("  op ");
        out.push_str(&info.maude_name);
        out.push_str(" :");
        for arg in &info.arity {
            out.push(' ');
            out.push_str(arg);
        }
        out.push_str(" -> ");
        out.push_str(&info.result);
        if !info.attrs.is_empty() {
            out.push_str(" [");
            out.push_str(&info.attrs.join(" "));
            out.push(']');
        }
        out.push_str(" .\n");
    }
    if !theory.variables.is_empty() {
        for variable in &theory.variables {
            validate_token(&variable.name, "variable")?;
            validate_token(&variable.sort, "variable sort")?;
        }
        let mut grouped: BTreeMap<&str, Vec<&str>> = BTreeMap::new();
        for variable in &theory.variables {
            grouped
                .entry(variable.sort.as_str())
                .or_default()
                .push(variable.name.as_str());
        }
        for (sort, names) in grouped {
            let keyword = if names.len() == 1 { "var" } else { "vars" };
            out.push_str(&format!("  {keyword} {} : {sort} .\n", names.join(" ")));
        }
    }
    for equation in &theory.equations {
        let lhs = render_term(&equation.lhs, operators)?;
        let rhs = render_term(&equation.rhs, operators)?;
        if let Some(label) = &equation.label {
            validate_token(label, "equation label")?;
        }
        out.push_str(&format!("  eq {lhs} = {rhs} .\n"));
    }
    out.push_str("endfm\n");
    Ok(out)
}

fn trs_spec(
    module_name: &str,
    theory: &RawTheory,
    operators: &BTreeMap<String, OperatorInfo>,
) -> Result<TrsSpec, CompileError> {
    let mut trs_ops = Vec::new();
    let mut has_ac_builtin = false;
    for op in operators.values() {
        if op.attrs.iter().any(|a| a == "assoc" || a == "comm") {
            has_ac_builtin = true;
        }
        trs_ops.push(TrsOperator {
            name: op.source_name.clone(),
            arity: op.arity.len(),
        });
    }
    let variables = theory.variables.iter().map(|v| v.name.clone()).collect();
    let mut rules = Vec::new();
    for equation in &theory.equations {
        rules.push(TrsRule {
            lhs: render_term_prefix(&equation.lhs)?,
            rhs: render_term_prefix(&equation.rhs)?,
        });
    }
    Ok(TrsSpec {
        name: module_name.to_string(),
        variables,
        operators: trs_ops,
        rules,
        has_ac_builtin,
    })
}

fn render_term(
    term: &IrTerm,
    operators: &BTreeMap<String, OperatorInfo>,
) -> Result<String, CompileError> {
    match term {
        IrTerm::Var { name } => {
            validate_token(name, "variable")?;
            Ok(name.clone())
        }
        IrTerm::Const { value, sort } => render_const(value, sort),
        IrTerm::Ctor { name, args } => {
            validate_token(name, "constructor")?;
            let rendered_args: Result<Vec<_>, _> =
                args.iter().map(|arg| render_term(arg, operators)).collect();
            let rendered_args = rendered_args?;
            let Some(op) = operators.get(name) else {
                return Err(CompileError::MalformedIr(format!(
                    "term uses undeclared operator {name}",
                )));
            };
            if op.arity.len() != rendered_args.len() {
                return Err(CompileError::MalformedIr(format!(
                    "operator {name} expects {} args, got {}",
                    op.arity.len(),
                    rendered_args.len()
                )));
            }
            Ok(render_operator_term(&op.maude_name, &rendered_args))
        }
        IrTerm::Lambda { .. } => Err(CompileError::UnsupportedPredicate(
            "lambda term in equational_theory".to_string(),
        )),
        IrTerm::Let { .. } => Err(CompileError::UnsupportedPredicate(
            "let term in equational_theory".to_string(),
        )),
    }
}

fn render_term_prefix(term: &IrTerm) -> Result<String, CompileError> {
    match term {
        IrTerm::Var { name } => {
            validate_token(name, "variable")?;
            Ok(name.clone())
        }
        IrTerm::Const { value, sort } => render_const(value, sort),
        IrTerm::Ctor { name, args } => {
            validate_token(name, "constructor")?;
            if args.is_empty() {
                return Ok(name.clone());
            }
            let args: Result<Vec<_>, _> = args.iter().map(render_term_prefix).collect();
            Ok(format!("{}({})", name, args?.join(",")))
        }
        IrTerm::Lambda { .. } => Err(CompileError::UnsupportedPredicate(
            "lambda term in equational_theory".to_string(),
        )),
        IrTerm::Let { .. } => Err(CompileError::UnsupportedPredicate(
            "let term in equational_theory".to_string(),
        )),
    }
}

fn render_operator_term(maude_name: &str, args: &[String]) -> String {
    if args.is_empty() {
        return maude_name.to_string();
    }
    if args.len() == 2 && maude_name.starts_with('_') && maude_name.ends_with('_') {
        let middle = maude_name.trim_matches('_');
        if !middle.is_empty() && !middle.contains('_') {
            return format!("({} {} {})", args[0], middle, args[1]);
        }
    }
    format!("{}({})", maude_name, args.join(", "))
}

fn render_const(value: &Json, sort: &Sort) -> Result<String, CompileError> {
    match value {
        Json::Number(n) => Ok(n.to_string()),
        Json::Bool(b) => Ok(if *b { "true" } else { "false" }.to_string()),
        Json::String(s) => match sort {
            Sort::Primitive { name } if name == "String" => Ok(format!("{s:?}")),
            Sort::Primitive { name } if name == "Real" => {
                // A `Real` const is a canonical decimal string; render it as a Maude
                // `Float` literal verbatim. Maude floats permit `.`/`e`/sign, which
                // the identifier token validator forbids, so validate the float
                // shape directly. (Maude is an equational/rewriting engine and does
                // not receive arithmetic `Formula` obligations -- those dispatch to
                // z3/coq/lean -- but a Real literal may still appear in a rewriting
                // term, and it must render rather than error.)
                if !s.is_empty()
                    && s.chars()
                        .all(|c| c.is_ascii_digit() || matches!(c, '.' | '-' | '+' | 'e' | 'E'))
                {
                    Ok(s.clone())
                } else {
                    Err(CompileError::MalformedIr(format!(
                        "invalid Real literal `{s}` in equational_theory"
                    )))
                }
            }
            _ => {
                validate_token(s, "constant")?;
                Ok(s.clone())
            }
        },
        _ => Err(CompileError::MalformedIr(
            "unsupported const value in equational_theory".to_string(),
        )),
    }
}

fn validate_token(value: &str, what: &str) -> Result<(), CompileError> {
    let ok = !value.is_empty()
        && value
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '_' | '-' | '\'' | '?'));
    if ok {
        Ok(())
    } else {
        Err(CompileError::MalformedIr(format!(
            "{what} is not Maude-safe: {value:?}",
        )))
    }
}

fn validate_surface(value: &str, what: &str) -> Result<(), CompileError> {
    let ok = !value.is_empty()
        && value.chars().all(|ch| {
            ch.is_ascii_alphanumeric()
                || matches!(
                    ch,
                    '_' | '+' | '*' | '-' | '/' | '<' | '>' | '=' | '\'' | '?' | ':' | '~'
                )
        });
    if ok {
        Ok(())
    } else {
        Err(CompileError::MalformedIr(format!(
            "{what} is not Maude-safe: {value:?}",
        )))
    }
}

fn validate_attr(attr: &str) -> Result<(), CompileError> {
    match attr {
        "assoc" | "comm" | "idem" | "id:" | "left-id:" | "right-id:" | "ctor" => Ok(()),
        _ => validate_token(attr, "operator attr"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn real_const_renders_as_a_maude_float_literal() {
        // solver 4/4 of the Real-tolerance fan-out. Maude does not receive the
        // arithmetic tolerance Formula (it compiles equational obligations, a
        // different IR shape), but its term renderer must be Real-safe.
        let real = Sort::Primitive {
            name: "Real".to_string(),
        };
        assert_eq!(
            render_const(&json!("0.00000015"), &real).unwrap(),
            "0.00000015"
        );
        assert_eq!(
            render_const(&json!("-0.00000015"), &real).unwrap(),
            "-0.00000015"
        );
        assert_eq!(render_const(&json!("1.5"), &real).unwrap(), "1.5");
        // soundness: a non-float string in Real position is rejected, not cloned.
        assert!(render_const(&json!("evil token"), &real).is_err());
    }

    #[test]
    fn rejects_non_equational_root() {
        let ir = json!({
            "kind": "atomic",
            "name": "=",
            "theory": {"name": "bad", "sorts": [], "operators": [], "equations": []},
            "obligation": {
                "lhs": {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}},
                "rhs": {"kind": "const", "value": 0, "sort": {"kind": "primitive", "name": "Int"}}
            }
        });
        let err = compile_artifact(&ir).unwrap_err();
        assert!(matches!(err, CompileError::UnsupportedPredicate(_)));
    }
}

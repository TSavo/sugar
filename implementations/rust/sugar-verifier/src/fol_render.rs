// SPDX-License-Identifier: MIT OR Apache-2.0
//
// ProofIR -> human-readable FOL renderer. Pure move from
// `sugar-cli/src/cmd_lift.rs` (2026-07-07, part of #3774 "rows are born with
// the three facts"): this is the SAME renderer `sugar lift --report --visual`
// used, now living where BOTH producers (sugar-cli's `sugar prove --json` and
// sugar-linkerd's `proveConsistency` RPC, via `sugar_verifier::report`) can
// call it. One renderer, never a second copy re-declared into either binary
// target. `sugar-cli::cmd_lift` re-exports this module's public items so the
// CLI binary and its existing tests keep compiling with zero behavior change.
use serde_json::Value;

pub fn generalized_formula_rows(formula: &Value) -> Vec<String> {
    if let Some(row) = generalized_base64_block_formula(formula) {
        return vec![row];
    }
    formula_operands(formula)
        .iter()
        .flat_map(generalized_formula_rows)
        .collect()
}

pub fn generalized_base64_block_formula(formula: &Value) -> Option<String> {
    let parts = base64_block_formula_parts(formula)?;
    let vars = payload_vars(&parts.payload);
    let output = generalized_call_output(parts.subject, &vars);
    let input = parts.input.map(proofir_term_to_fol).unwrap_or_else(|| {
        if vars.is_empty() {
            format_base64_payload_input(&parts.payload)
        } else {
            format!("[{}]", vars.join(", "))
        }
    });
    let blocks = format_base64_payload_with_input(&parts.payload, &input);
    let quantifiers = vars
        .iter()
        .map(|name| format!("∀ {name}:Int. "))
        .collect::<String>();
    Some(format!("{quantifiers}str.eq-bv-blocks({output}, {blocks})"))
}

pub fn proofir_formula_to_fol_with_instances(formula: &Value) -> String {
    if let Some(rendered) = instantiated_base64_block_formula(formula) {
        return rendered;
    }
    let Some(kind) = formula.get("kind").and_then(Value::as_str) else {
        return proofir_formula_to_fol(formula);
    };
    match kind {
        "and" => {
            let operands = formula_operands(formula);
            if operands.is_empty() {
                "⊤".to_string()
            } else {
                format_formula_join_with_instances(&operands, " ∧ ")
            }
        }
        "or" => {
            let operands = formula_operands(formula);
            if operands.is_empty() {
                "⊥".to_string()
            } else {
                format_formula_join_with_instances(&operands, " ∨ ")
            }
        }
        "not" => {
            let operands = formula_operands(formula);
            match operands.as_slice() {
                [one] => format!(
                    "¬{}",
                    parenthesize_formula(&proofir_formula_to_fol_with_instances(one))
                ),
                _ => proofir_formula_to_fol(formula),
            }
        }
        "implies" => {
            let operands = formula_operands(formula);
            match operands.as_slice() {
                [left, right] => format!(
                    "{} ⇒ {}",
                    parenthesize_formula(&proofir_formula_to_fol_with_instances(left)),
                    parenthesize_formula(&proofir_formula_to_fol_with_instances(right))
                ),
                _ => proofir_formula_to_fol(formula),
            }
        }
        "forall" | "exists" => {
            let symbol = if kind == "forall" { "∀" } else { "∃" };
            let name = formula.get("name").and_then(Value::as_str).unwrap_or("?");
            let sort = formula
                .get("sort")
                .map(proofir_sort_to_fol)
                .unwrap_or_else(|| "?".to_string());
            let body = formula
                .get("body")
                .map(proofir_formula_to_fol_with_instances)
                .unwrap_or_else(|| "<missing body>".to_string());
            format!("{symbol} {name}:{sort}. {body}")
        }
        _ => proofir_formula_to_fol(formula),
    }
}

pub fn format_formula_join_with_instances(operands: &[Value], separator: &str) -> String {
    operands
        .iter()
        .map(|operand| parenthesize_formula(&proofir_formula_to_fol_with_instances(operand)))
        .collect::<Vec<_>>()
        .join(separator)
}

pub fn instantiated_base64_block_formula(formula: &Value) -> Option<String> {
    let parts = base64_block_formula_parts(formula)?;
    let rendered = format_base64_block_formula(&parts);
    format_instantiation(&parts.payload)
        .map(|instantiation| format!("{instantiation} ⊢ {rendered}"))
        .or(Some(rendered))
}

pub fn proofir_formula_to_fol(formula: &Value) -> String {
    let Some(kind) = formula.get("kind").and_then(Value::as_str) else {
        return serde_json::to_string(formula)
            .unwrap_or_else(|_| "<unrenderable formula>".to_string());
    };
    match kind {
        "true" | "True" => "⊤".to_string(),
        "false" | "False" => "⊥".to_string(),
        "atomic" | "Atomic" => {
            let name = formula.get("name").and_then(Value::as_str).unwrap_or("?");
            let args = formula
                .get("args")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            if name == "str.eq-bv-blocks" {
                if let Some(rendered) = format_base64_block_formula_from_formula(formula) {
                    return rendered;
                }
            }
            if args.is_empty() {
                return match name {
                    "true" | "⊤" => "⊤".to_string(),
                    "false" | "⊥" => "⊥".to_string(),
                    _ => name.to_string(),
                };
            }
            if args.len() == 2 && is_infix_predicate(name) {
                return format!(
                    "{} {} {}",
                    proofir_term_to_fol(&args[0]),
                    fol_predicate_symbol(name),
                    proofir_term_to_fol(&args[1])
                );
            }
            let rendered_args = args
                .iter()
                .map(proofir_term_to_fol)
                .collect::<Vec<_>>()
                .join(", ");
            format!("{name}({rendered_args})")
        }
        "and" => {
            let operands = formula_operands(formula);
            if operands.is_empty() {
                "⊤".to_string()
            } else {
                format_formula_join(&operands, " ∧ ")
            }
        }
        "or" => {
            let operands = formula_operands(formula);
            if operands.is_empty() {
                "⊥".to_string()
            } else {
                format_formula_join(&operands, " ∨ ")
            }
        }
        "not" => {
            let operands = formula_operands(formula);
            match operands.as_slice() {
                [one] => format!("¬{}", parenthesize_formula(&proofir_formula_to_fol(one))),
                _ => format!("not({})", format_formula_join(&operands, ", ")),
            }
        }
        "implies" => {
            let operands = formula_operands(formula);
            match operands.as_slice() {
                [left, right] => format!(
                    "{} ⇒ {}",
                    parenthesize_formula(&proofir_formula_to_fol(left)),
                    parenthesize_formula(&proofir_formula_to_fol(right))
                ),
                _ => format!("implies({})", format_formula_join(&operands, ", ")),
            }
        }
        "forall" | "exists" => {
            let symbol = if kind == "forall" { "∀" } else { "∃" };
            let name = formula.get("name").and_then(Value::as_str).unwrap_or("?");
            let sort = formula
                .get("sort")
                .map(proofir_sort_to_fol)
                .unwrap_or_else(|| "?".to_string());
            let body = formula
                .get("body")
                .map(proofir_formula_to_fol)
                .unwrap_or_else(|| "<missing body>".to_string());
            format!("{symbol} {name}:{sort}. {body}")
        }
        "choice" => {
            let name = formula
                .get("var_name")
                .or_else(|| formula.get("varName"))
                .and_then(Value::as_str)
                .unwrap_or("?");
            let sort = formula
                .get("sort")
                .map(proofir_sort_to_fol)
                .unwrap_or_else(|| "?".to_string());
            let body = formula
                .get("body")
                .map(proofir_formula_to_fol)
                .unwrap_or_else(|| "<missing body>".to_string());
            format!("ε {name}:{sort}. {body}")
        }
        other => serde_json::to_string(formula)
            .unwrap_or_else(|_| format!("<unrenderable {other} formula>")),
    }
}

pub fn formula_operands(formula: &Value) -> Vec<Value> {
    formula
        .get("operands")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

pub fn format_formula_join(operands: &[Value], separator: &str) -> String {
    operands
        .iter()
        .map(|operand| parenthesize_formula(&proofir_formula_to_fol(operand)))
        .collect::<Vec<_>>()
        .join(separator)
}

pub fn parenthesize_formula(rendered: &str) -> String {
    if rendered == "⊤"
        || rendered == "⊥"
        || rendered.starts_with('∀')
        || rendered.starts_with('∃')
        || (!rendered.contains(" ∧ ") && !rendered.contains(" ∨ ") && !rendered.contains(" ⇒ "))
    {
        rendered.to_string()
    } else {
        format!("({rendered})")
    }
}

pub fn is_infix_predicate(name: &str) -> bool {
    matches!(
        name,
        "=" | "==" | "!=" | "≠" | ">" | ">=" | "≥" | "<" | "<=" | "≤"
    )
}

pub fn fol_predicate_symbol(name: &str) -> &str {
    match name {
        "==" => "=",
        "!=" => "≠",
        ">=" => "≥",
        "<=" => "≤",
        other => other,
    }
}

pub fn proofir_term_to_fol(term: &Value) -> String {
    if let Some(name) = term.get("var").and_then(Value::as_str) {
        return name.to_string();
    }
    if let Some(value) = term.get("int").or_else(|| term.get("real")) {
        return scalar_value_to_fol(value);
    }
    if let Some(value) = term.get("str").and_then(Value::as_str) {
        return quoted_string(value);
    }

    let Some(kind) = term.get("kind").and_then(Value::as_str) else {
        return scalar_value_to_fol(term);
    };
    match kind {
        "var" | "Var" => term
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("?")
            .to_string(),
        "const" | "Const" => term
            .get("value")
            .map(scalar_value_to_fol)
            .unwrap_or_else(|| "?".to_string()),
        "ctor" | "Ctor" => {
            let name = term.get("name").and_then(Value::as_str).unwrap_or("?");
            let args = term
                .get("args")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            if args.is_empty() {
                // A `call:`-prefixed ctor is a function/method invocation; an
                // empty arg list is a zero-arg call (`answer()`, `B::new()`),
                // so render the parens — they're what makes the universe read
                // as a call rather than a bare symbol. Nullary data ctors
                // (unit variants like `None`) keep their bare form.
                if name.starts_with("call:") {
                    // Strip the `call:` provenance prefix for display -- a human
                    // reading the squiggle wants `encodeBase64()`, not
                    // `call:encodeBase64()`. The prefix is an internal tag.
                    return format!("{}()", name.strip_prefix("call:").unwrap_or(name));
                }
                return name.to_string();
            }
            if let Some(rendered) = format_symbolic_ctor(name, &args) {
                return rendered;
            }
            let rendered_args = args
                .iter()
                .map(proofir_term_to_fol)
                .collect::<Vec<_>>()
                .join(", ");
            // Strip the `call:` provenance prefix for display (internal tag).
            let display = name.strip_prefix("call:").unwrap_or(name);
            format!("{display}({rendered_args})")
        }
        "let" | "Let" => proofir_let_term_to_fol(term),
        other => {
            serde_json::to_string(term).unwrap_or_else(|_| format!("<unrenderable {other} term>"))
        }
    }
}

pub fn proofir_let_term_to_fol(term: &Value) -> String {
    let bindings = term
        .get("bindings")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let body = term
        .get("body")
        .map(proofir_term_to_fol)
        .unwrap_or_else(|| "<missing body>".to_string());
    if bindings.is_empty() {
        return body;
    }
    let rendered_bindings = bindings
        .iter()
        .map(|binding| {
            let name = binding.get("name").and_then(Value::as_str).unwrap_or("?");
            let bound = binding
                .get("boundTerm")
                .or_else(|| binding.get("bound_term"))
                .map(proofir_term_to_fol)
                .unwrap_or_else(|| "<missing bound>".to_string());
            format!("{name} = {bound}")
        })
        .collect::<Vec<_>>()
        .join("; ");
    format!("let {rendered_bindings} in {body}")
}

pub fn format_symbolic_ctor(name: &str, args: &[Value]) -> Option<String> {
    if name == "cf_ite" {
        return format_cf_ite_term(args);
    }
    let symbol = match name {
        "bv32.add" | "concept:add" | "+" => "+",
        "bv32.sub" | "concept:sub" | "-" => "-",
        "bv32.mul" | "concept:mul" | "*" => "*",
        "/" => "/",
        "%" => "%",
        "bv32.and" => "&",
        "bv32.or" => "|",
        "bv32.xor" => "⊕",
        "bv32.shl" => "<<",
        "bv32.lshr" => ">>>",
        "cf_eq" => "=",
        "cf_ne" => "≠",
        "cf_lt" => "<",
        "cf_le" => "≤",
        "cf_gt" => ">",
        "cf_ge" => "≥",
        _ => return None,
    };
    if args.len() != 2 {
        return None;
    }
    Some(format!(
        "({} {} {})",
        proofir_term_to_fol(&args[0]),
        symbol,
        proofir_term_to_fol(&args[1])
    ))
}

pub fn format_cf_ite_term(args: &[Value]) -> Option<String> {
    if args.len() != 3 {
        return None;
    }
    Some(format!(
        "if {} then {} else {}",
        trim_wrapping_parens(&proofir_term_to_fol(&args[0])),
        proofir_term_to_fol(&args[1]),
        proofir_term_to_fol(&args[2])
    ))
}

pub fn trim_wrapping_parens(rendered: &str) -> &str {
    if rendered.starts_with('(') && rendered.ends_with(')') {
        &rendered[1..rendered.len() - 1]
    } else {
        rendered
    }
}

pub fn scalar_value_to_fol(value: &Value) -> String {
    match value {
        Value::String(s) => render_embedded_proofir_json(s).unwrap_or_else(|| quoted_string(s)),
        Value::Number(n) => n.to_string(),
        Value::Bool(b) => b.to_string(),
        Value::Null => "null".to_string(),
        _ => serde_json::to_string(value).unwrap_or_else(|_| "<unrenderable value>".to_string()),
    }
}

pub fn render_embedded_proofir_json(value: &str) -> Option<String> {
    if !value.trim_start().starts_with('{') {
        return None;
    }
    let parsed: Value = serde_json::from_str(value).ok()?;
    if let Some(kind) = parsed.get("kind").and_then(Value::as_str) {
        if is_formula_kind(kind) {
            return Some(proofir_formula_to_fol(&parsed));
        }
        if is_term_kind(kind) {
            return Some(proofir_term_to_fol(&parsed));
        }
    }
    render_structured_payload(&parsed)
}

pub fn render_structured_payload(value: &Value) -> Option<String> {
    let payload = base64_payload_from_value(value)?;
    let input = format_base64_payload_input(&payload);
    Some(format_base64_payload_with_input(&payload, &input))
}

#[derive(Debug, Clone)]
pub struct Base64BlockPayload {
    pub input_bytes: Option<Vec<Value>>,
    pub vars: Vec<String>,
    pub per_char: Vec<Value>,
    pub table: Option<String>,
}

pub struct Base64BlockFormulaParts<'a> {
    pub subject: &'a Value,
    pub input: Option<&'a Value>,
    pub payload: Base64BlockPayload,
}

pub fn base64_block_formula_parts(formula: &Value) -> Option<Base64BlockFormulaParts<'_>> {
    if formula.get("kind").and_then(Value::as_str) != Some("atomic")
        || formula.get("name").and_then(Value::as_str) != Some("str.eq-bv-blocks")
    {
        return None;
    }
    let args = formula.get("args").and_then(Value::as_array)?;
    match args.as_slice() {
        [subject, payload] => Some(Base64BlockFormulaParts {
            subject,
            input: None,
            payload: base64_payload_from_term(payload)?,
        }),
        [subject, input, payload] => Some(Base64BlockFormulaParts {
            subject,
            input: Some(input),
            payload: base64_payload_from_term(payload)?,
        }),
        _ => None,
    }
}

pub fn format_base64_block_formula_from_formula(formula: &Value) -> Option<String> {
    let parts = base64_block_formula_parts(formula)?;
    Some(format_base64_block_formula(&parts))
}

pub fn format_base64_block_formula(parts: &Base64BlockFormulaParts<'_>) -> String {
    let subject = proofir_term_to_fol(parts.subject);
    let input = parts
        .input
        .map(proofir_term_to_fol)
        .unwrap_or_else(|| format_base64_payload_input(&parts.payload));
    let blocks = format_base64_payload_with_input(&parts.payload, &input);
    format!("str.eq-bv-blocks({subject}, {blocks})")
}

pub fn base64_payload_from_term(term: &Value) -> Option<Base64BlockPayload> {
    let raw = term.get("value").and_then(Value::as_str)?;
    let parsed: Value = serde_json::from_str(raw).ok()?;
    base64_payload_from_value(&parsed)
}

pub fn base64_payload_from_value(value: &Value) -> Option<Base64BlockPayload> {
    let input_bytes = value.get("input_bytes").and_then(Value::as_array).cloned();
    let per_char = value.get("per_char").and_then(Value::as_array)?.clone();
    let vars = value
        .get("vars")
        .and_then(Value::as_array)
        .map(|vars| {
            vars.iter()
                .filter_map(Value::as_str)
                .map(ToOwned::to_owned)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let table = value
        .get("table")
        .and_then(Value::as_array)
        .and_then(|values| bytes_array_to_ascii(values.as_slice()));
    Some(Base64BlockPayload {
        input_bytes,
        vars,
        per_char,
        table,
    })
}

pub fn format_base64_payload_with_input(payload: &Base64BlockPayload, input: &str) -> String {
    let chars = payload
        .per_char
        .iter()
        .map(proofir_term_to_fol)
        .collect::<Vec<_>>()
        .join(", ");
    let table = payload
        .table
        .as_deref()
        .map(|table| format!(", table={}", quoted_string(table)))
        .unwrap_or_default();
    format!("base64.blocks(input={input}, chars=[{chars}]{table})")
}

pub fn payload_vars(payload: &Base64BlockPayload) -> Vec<String> {
    if let Some(input_bytes) = payload.input_bytes.as_ref() {
        if payload.vars.len() == input_bytes.len() && !payload.vars.is_empty() {
            return payload.vars.clone();
        }
        return (0..input_bytes.len())
            .map(|index| format!("b{index}"))
            .collect();
    }
    payload.vars.clone()
}

pub fn generalized_call_output(term: &Value, vars: &[String]) -> String {
    if term.get("kind").and_then(Value::as_str) == Some("ctor") {
        if let Some(name) = term.get("name").and_then(Value::as_str) {
            if name.starts_with("call:") {
                return format!("{name}(bytes({}))", vars.join(", "));
            }
        }
    }
    "output".to_string()
}

pub fn format_instantiation(payload: &Base64BlockPayload) -> Option<String> {
    let input_bytes = payload.input_bytes.as_ref()?;
    Some(
        payload_vars(payload)
            .iter()
            .zip(input_bytes.iter())
            .map(|(name, value)| format!("{name}={}", scalar_value_to_fol(value)))
            .collect::<Vec<_>>()
            .join(", "),
    )
}

pub fn format_base64_payload_input(payload: &Base64BlockPayload) -> String {
    if let Some(input_bytes) = payload.input_bytes.as_ref() {
        return format_scalar_array(input_bytes);
    }
    let vars = payload_vars(payload);
    if vars.is_empty() {
        "?".to_string()
    } else {
        format!("[{}]", vars.join(", "))
    }
}

pub fn format_scalar_array(values: &[Value]) -> String {
    let rendered = values
        .iter()
        .map(scalar_value_to_fol)
        .collect::<Vec<_>>()
        .join(", ");
    format!("[{rendered}]")
}

pub fn bytes_array_to_ascii(values: &[Value]) -> Option<String> {
    let mut out = String::new();
    for value in values {
        let byte = value.as_u64()?;
        if !(32..=126).contains(&byte) {
            return None;
        }
        out.push(char::from_u32(byte as u32)?);
    }
    Some(out)
}

pub fn is_formula_kind(kind: &str) -> bool {
    matches!(
        kind,
        "true"
            | "True"
            | "false"
            | "False"
            | "atomic"
            | "Atomic"
            | "and"
            | "or"
            | "not"
            | "implies"
            | "forall"
            | "exists"
            | "choice"
    )
}

pub fn is_term_kind(kind: &str) -> bool {
    matches!(kind, "var" | "Var" | "const" | "Const" | "ctor" | "Ctor")
}

pub fn quoted_string(value: &str) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "\"<unrenderable string>\"".to_string())
}

pub fn proofir_sort_to_fol(sort: &Value) -> String {
    if let Some(name) = sort.as_str() {
        return name.to_string();
    }
    sort.get("name")
        .or_else(|| sort.get("kind"))
        .and_then(Value::as_str)
        .unwrap_or("?")
        .to_string()
}

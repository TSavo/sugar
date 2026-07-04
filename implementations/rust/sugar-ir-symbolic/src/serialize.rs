// SPDX-License-Identifier: MIT OR Apache-2.0
//
// IR-JSON serializer. Emits the locked IR-JSON shape per
// protocol/specs/2026-04-30-ir-formal-grammar.md.
//
// Locked key orders (the kit emits insertion order; the canonicalizer's
// JCS pass re-sorts before hashing):
//   var:        {kind, name}
//   const:      {kind, value, sort}
//   ctor:       {kind, name, args}
//   atomic:     {kind, name, args}
//   connective: {kind, operands}
//   quantifier: {kind, name, sort, body}
//   sort:       {kind: "primitive", name}
//   contract:   {kind: "contract", name, outBinding, pre?, post?, inv?}
//
// Output is a String holding kit-shape JSON. The `to_value()` form is
// also provided for hashing flow (claim-envelope JCS-encodes the
// canonicalizer Value tree, not the kit JSON string).

use std::sync::Arc;

use sugar_canonicalizer::{encode_jcs, Value};

use crate::{ConstValue, ContractDecl, EvidenceTerm, Formula, Sort, Term};

// -------- to canonicalizer Value (used by hashing path) --------------

fn int_fits_json_number(n: i128) -> bool {
    i64::try_from(n).is_ok() || u64::try_from(n).is_ok()
}

fn int_to_value(n: i128) -> Arc<Value> {
    if int_fits_json_number(n) {
        Value::integer(n)
    } else {
        Value::string(n.to_string())
    }
}

fn write_int(out: &mut String, n: i128) {
    if int_fits_json_number(n) {
        out.push_str(&n.to_string());
    } else {
        write_string(out, &n.to_string());
    }
}

pub fn evidence_to_value(e: &EvidenceTerm) -> Arc<Value> {
    Value::object([
        ("kind", Value::string("evidence")),
        ("proofType", Value::string(e.proof_type.clone())),
        (
            "certificate",
            Value::object([
                ("tool", Value::string(e.certificate.tool.clone())),
                ("version", Value::string(e.certificate.version.clone())),
                (
                    "formulaHash",
                    Value::string(e.certificate.formula_hash.clone()),
                ),
                ("proofData", Value::string(e.certificate.proof_data.clone())),
            ]),
        ),
    ])
}

pub fn sort_to_value(s: &Sort) -> Arc<Value> {
    Value::object([
        ("kind", Value::string("primitive")),
        ("name", Value::string(s.name.clone())),
    ])
}

pub fn term_to_value(t: &Term) -> Arc<Value> {
    match t {
        Term::Var { name } => Value::object([
            ("kind", Value::string("var")),
            ("name", Value::string(name.clone())),
        ]),
        Term::Const { value, sort } => {
            let value_v = match value {
                ConstValue::Int(n) => int_to_value(*n),
                ConstValue::Real(n) => Value::string(n.clone()),
                ConstValue::String(s) => Value::string(s.clone()),
                ConstValue::Bool(b) => Value::boolean(*b),
            };
            Value::object([
                ("kind", Value::string("const")),
                ("value", value_v),
                ("sort", sort_to_value(sort)),
            ])
        }
        Term::Ctor { name, args } => {
            let arr: Vec<Arc<Value>> = args.iter().map(|a| term_to_value(a)).collect();
            Value::object([
                ("kind", Value::string("ctor")),
                ("name", Value::string(name.clone())),
                ("args", Value::array(arr)),
            ])
        }
        Term::Lambda {
            param_name,
            param_sort,
            body,
        } => Value::object([
            ("kind", Value::string("lambda")),
            ("paramName", Value::string(param_name.clone())),
            ("paramSort", sort_to_value(param_sort)),
            ("body", term_to_value(body)),
        ]),
        Term::Let { bindings, body } => {
            let arr: Vec<Arc<Value>> = bindings
                .iter()
                .map(|b| {
                    Value::object([
                        ("name", Value::string(b.name.clone())),
                        ("boundTerm", term_to_value(&b.bound_term)),
                    ])
                })
                .collect();
            Value::object([
                ("kind", Value::string("let")),
                ("bindings", Value::array(arr)),
                ("body", term_to_value(body)),
            ])
        }
    }
}

pub fn formula_to_value(f: &Formula) -> Arc<Value> {
    match f {
        Formula::Atomic { name, args } => {
            let arr: Vec<Arc<Value>> = args.iter().map(|a| term_to_value(a)).collect();
            Value::object([
                ("kind", Value::string("atomic")),
                ("name", Value::string(name.clone())),
                ("args", Value::array(arr)),
            ])
        }
        Formula::Connective { kind, operands } => {
            let arr: Vec<Arc<Value>> = operands.iter().map(|o| formula_to_value(o)).collect();
            Value::object([
                ("kind", Value::string(kind.clone())),
                ("operands", Value::array(arr)),
            ])
        }
        Formula::Quantifier {
            kind,
            name,
            sort,
            body,
        } => Value::object([
            ("kind", Value::string(kind.clone())),
            ("name", Value::string(name.clone())),
            ("sort", sort_to_value(sort)),
            ("body", formula_to_value(body)),
        ]),
        Formula::Choice {
            var_name,
            sort,
            body,
        } => Value::object([
            ("kind", Value::string("choice")),
            ("varName", Value::string(var_name.clone())),
            ("sort", sort_to_value(sort)),
            ("body", formula_to_value(body)),
        ]),
    }
}

// -------- to kit-shape JSON (insertion-order; mirrors C++ kit) -------

pub fn marshal_declarations(decls: &[ContractDecl]) -> String {
    // Mirrors C++ marshal_declarations: emits insertion-order JSON.
    let mut out = String::new();
    out.push('[');
    for (i, d) in decls.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        out.push_str(r#"{"kind":"contract","name":"#);
        write_string(&mut out, &d.name);
        out.push_str(r#","outBinding":"#);
        write_string(&mut out, &d.out_binding);
        if let Some(pre) = &d.pre {
            out.push_str(r#","pre":"#);
            write_formula(&mut out, pre);
        }
        if let Some(post) = &d.post {
            out.push_str(r#","post":"#);
            write_formula(&mut out, post);
        }
        if let Some(inv) = &d.inv {
            out.push_str(r#","inv":"#);
            write_formula(&mut out, inv);
        }
        if let Some(ev) = &d.evidence {
            out.push_str(r#","evidence":"#);
            write_evidence(&mut out, ev);
        }
        if !d.panic_loci.is_empty() {
            out.push_str(r#","panicLoci":["#);
            for (i, locus) in d.panic_loci.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                out.push_str(&encode_jcs(locus.as_ref()));
            }
            out.push(']');
        }
        out.push('}');
    }
    out.push(']');
    out
}

fn write_evidence(out: &mut String, e: &EvidenceTerm) {
    out.push_str(r#"{"kind":"evidence","proofType":"#);
    write_string(out, &e.proof_type);
    out.push_str(r#","certificate":{"tool":"#);
    write_string(out, &e.certificate.tool);
    out.push_str(r#","version":"#);
    write_string(out, &e.certificate.version);
    out.push_str(r#","formulaHash":"#);
    write_string(out, &e.certificate.formula_hash);
    out.push_str(r#","proofData":"#);
    write_string(out, &e.certificate.proof_data);
    out.push_str("}}");
}

fn write_string(out: &mut String, s: &str) {
    out.push('"');
    // Iterate by `char`, NOT by byte. Iterating bytes and doing
    // `byte as char` mangles every multi-byte UTF-8 scalar: e.g. `≥`
    // (U+2265 = bytes E2 89 A5) became the three code points U+00E2,
    // U+0089, U+00A5, which then re-encode as 6 bytes of mojibake. The
    // integer-comparison operators `≥`/`≤` are emitted by `gte`/`lte`,
    // so this corrupted any contract carrying a `>=`/`<=` predicate when
    // its IR-JSON was round-tripped through `parse_document` (the path the
    // RPC lift transport newly exercises). Pushing whole `char`s keeps
    // valid UTF-8, which is also conformant JSON (only `"`, `\`, and
    // control chars < 0x20 require escaping).
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            c if (c as u32) < 0x20 => {
                const HEX: &[u8; 16] = b"0123456789abcdef";
                let c = c as u32;
                out.push_str("\\u00");
                out.push(HEX[((c >> 4) & 0xF) as usize] as char);
                out.push(HEX[(c & 0xF) as usize] as char);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

fn write_sort(out: &mut String, s: &Sort) {
    out.push_str(r#"{"kind":"primitive","name":"#);
    write_string(out, &s.name);
    out.push('}');
}

fn write_term(out: &mut String, t: &Term) {
    match t {
        Term::Var { name } => {
            out.push_str(r#"{"kind":"var","name":"#);
            write_string(out, name);
            out.push('}');
        }
        Term::Const { value, sort } => {
            out.push_str(r#"{"kind":"const","value":"#);
            match value {
                ConstValue::Int(n) => write_int(out, *n),
                ConstValue::Real(n) => write_string(out, n),
                ConstValue::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
                ConstValue::String(s) => write_string(out, s),
            }
            out.push_str(r#","sort":"#);
            write_sort(out, sort);
            out.push('}');
        }
        Term::Ctor { name, args } => {
            out.push_str(r#"{"kind":"ctor","name":"#);
            write_string(out, name);
            out.push_str(r#","args":["#);
            for (i, a) in args.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_term(out, a);
            }
            out.push_str("]}");
        }
        Term::Lambda {
            param_name,
            param_sort,
            body,
        } => {
            out.push_str(r#"{"kind":"lambda","paramName":"#);
            write_string(out, param_name);
            out.push_str(r#","paramSort":"#);
            write_sort(out, param_sort);
            out.push_str(r#","body":"#);
            write_term(out, body);
            out.push('}');
        }
        Term::Let { bindings, body } => {
            out.push_str(r#"{"kind":"let","bindings":["#);
            for (i, b) in bindings.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                out.push_str(r#"{"name":"#);
                write_string(out, &b.name);
                out.push_str(r#","boundTerm":"#);
                write_term(out, &b.bound_term);
                out.push('}');
            }
            out.push_str(r#","body":"#);
            write_term(out, body);
            out.push('}');
        }
    }
}

fn write_formula(out: &mut String, f: &Formula) {
    match f {
        Formula::Atomic { name, args } => {
            out.push_str(r#"{"kind":"atomic","name":"#);
            write_string(out, name);
            out.push_str(r#","args":["#);
            for (i, a) in args.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_term(out, a);
            }
            out.push_str("]}");
        }
        Formula::Connective { kind, operands } => {
            out.push_str(r#"{"kind":"#);
            write_string(out, kind);
            out.push_str(r#","operands":["#);
            for (i, op) in operands.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_formula(out, op);
            }
            out.push_str("]}");
        }
        Formula::Quantifier {
            kind,
            name,
            sort,
            body,
        } => {
            out.push_str(r#"{"kind":"#);
            write_string(out, kind);
            out.push_str(r#","name":"#);
            write_string(out, name);
            out.push_str(r#","sort":"#);
            write_sort(out, sort);
            out.push_str(r#","body":"#);
            write_formula(out, body);
            out.push('}');
        }
        Formula::Choice {
            var_name,
            sort,
            body,
        } => {
            out.push_str(r#"{"kind":"choice","varName":"#);
            write_string(out, var_name);
            out.push_str(r#","sort":"#);
            write_sort(out, sort);
            out.push_str(r#","body":"#);
            write_formula(out, body);
            out.push('}');
        }
    }
}

// SPDX-License-Identifier: Apache-2.0
//
// IR-JSON parser. Walks an IR-JSON document (per
// protocol/specs/2026-04-30-ir-formal-grammar.md) and produces typed
// `Formula` / `Term` / `Sort` / `ContractDecl` values matching the
// authoring API in `lib.rs`.
//
// Pairs with `serialize::formula_to_value` / `marshal_declarations`.
// The round-trip property `parse(serialize(f)) == f` is enforced by
// the property tests in this module's `tests` block and (more
// thoroughly) in `sugar-self-contracts`.
//
// Closed-object policy: nodes carry exactly the keys their grammar
// production names. Extra fields are rejected loud (RuleViolation::ExtraKey).
// `VarTerm` and `CtorTerm` post-v1.1.0 carry no `sort`: the parser
// rejects strays.
//
// Strict-mode arity rules per the grammar:
//   - `not`: exactly 1 operand
//   - `implies`: exactly 2 operands
//   - `and` / `or`: 2+ operands

use std::rc::Rc;

use serde_json::Value as Json;
use sugar_canonicalizer::Value as CValue;

use crate::{
    and_, atomic_, contract, exists, finish, forall, implies, make_var, not_, num, or_,
    reset_collector, str_const, ConstValue, ContractArgs, ContractDecl, EvidenceCertificate,
    EvidenceTerm, Formula, Sort, Term,
};

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum ParseError {
    #[error("parse: at {path}: expected {expected}, got {actual}")]
    Mismatch {
        path: String,
        expected: String,
        actual: String,
    },
    #[error("parse: at {path}: missing required field `{field}`")]
    MissingField { path: String, field: String },
    #[error("parse: at {path}: extra/unknown key `{key}` not permitted on {kind}")]
    ExtraKey {
        path: String,
        key: String,
        kind: String,
    },
    #[error("parse: at {path}: unknown kind `{kind}`")]
    UnknownKind { path: String, kind: String },
    #[error("parse: at {path}: arity violation for `{kind}`: expected {expected}, got {actual}")]
    Arity {
        path: String,
        kind: String,
        expected: String,
        actual: usize,
    },
    #[error("parse: at {path}: empty contract: at least one of pre/post/inv required")]
    EmptyContract { path: String },
    #[error("parse: invalid JSON: {0}")]
    InvalidJson(String),
}

// ---- Top-level entry points -------------------------------------------------

/// Parse the IR-JSON `Document` form: an array of contract declarations
/// emitted by `marshal_declarations`. Bridge declarations as inline JSON
/// are not yet handled (bridges live in `BridgeDecl` minted via
/// `mint_bridge`); the kit-emitted document the serializer produces is
/// only contracts. This matches the spec's ContractDeclaration shape.
pub fn parse_document(json: &str) -> Result<Vec<ContractDecl>, ParseError> {
    let v: Json = serde_json::from_str(json).map_err(|e| ParseError::InvalidJson(e.to_string()))?;
    let arr = v.as_array().ok_or_else(|| ParseError::Mismatch {
        path: "$".into(),
        expected: "array of declarations".into(),
        actual: type_of(&v),
    })?;
    // We rebuild via the kit's collector so the result is identical to
    // an authored ContractDecl (handles outBinding default, etc.).
    reset_collector();
    crate::begin_collecting();
    for (i, item) in arr.iter().enumerate() {
        let path = format!("$[{i}]");
        parse_contract_into_collector(item, &path)?;
    }
    Ok(finish())
}

/// Parse a single contract object (the inner shape of one Document
/// element). Useful for tests and for parsing memento bodies.
pub fn parse_contract(v: &Json) -> Result<ContractDecl, ParseError> {
    reset_collector();
    crate::begin_collecting();
    parse_contract_into_collector(v, "$")?;
    let mut decls = finish();
    decls.pop().ok_or_else(|| ParseError::Mismatch {
        path: "$".into(),
        expected: "one contract declaration".into(),
        actual: "empty result".into(),
    })
}

pub fn parse_formula(v: &Json) -> Result<Rc<Formula>, ParseError> {
    parse_formula_at(v, "$")
}

pub fn parse_term(v: &Json) -> Result<Rc<Term>, ParseError> {
    parse_term_at(v, "$")
}

pub fn parse_sort(v: &Json) -> Result<Sort, ParseError> {
    parse_sort_at(v, "$")
}

// ---- Internal walkers -------------------------------------------------------

fn parse_contract_into_collector(v: &Json, path: &str) -> Result<(), ParseError> {
    let obj = require_object(v, path, "contract")?;
    let allowed = &[
        "kind",
        "name",
        "outBinding",
        "pre",
        "post",
        "inv",
        "evidence",
        "panicLoci",
        "panic_loci",
    ];
    reject_extra_keys(obj, allowed, path, "contract")?;

    let kind = require_string(obj, "kind", path)?;
    if kind != "contract" {
        return Err(ParseError::Mismatch {
            path: format!("{path}.kind"),
            expected: "\"contract\"".into(),
            actual: format!("\"{kind}\""),
        });
    }
    let name = require_string(obj, "name", path)?;
    let out_binding = require_string(obj, "outBinding", path)?;
    if out_binding.is_empty() {
        return Err(ParseError::Mismatch {
            path: format!("{path}.outBinding"),
            expected: "non-empty string".into(),
            actual: "empty string".into(),
        });
    }

    let pre = obj
        .get("pre")
        .map(|f| parse_formula_at(f, &format!("{path}.pre")))
        .transpose()?;
    let post = obj
        .get("post")
        .map(|f| parse_formula_at(f, &format!("{path}.post")))
        .transpose()?;
    let inv = obj
        .get("inv")
        .map(|f| parse_formula_at(f, &format!("{path}.inv")))
        .transpose()?;
    let evidence = obj
        .get("evidence")
        .map(|e| parse_evidence_at(e, &format!("{path}.evidence")))
        .transpose()?;
    let panic_loci = parse_panic_loci_at(
        obj.get("panicLoci").or_else(|| obj.get("panic_loci")),
        &format!("{path}.panicLoci"),
    )?;

    if pre.is_none() && post.is_none() && inv.is_none() {
        return Err(ParseError::EmptyContract { path: path.into() });
    }

    contract(
        name,
        ContractArgs {
            pre,
            post,
            inv,
            out_binding: Some(out_binding),
            evidence,
            panic_loci,
        },
    );
    Ok(())
}

fn parse_panic_loci_at(
    v: Option<&Json>,
    path: &str,
) -> Result<Vec<std::sync::Arc<CValue>>, ParseError> {
    let Some(v) = v else {
        return Ok(Vec::new());
    };
    let arr = require_array(v, path, "panicLoci")?;
    Ok(arr.iter().map(json_to_cvalue).collect())
}

fn json_to_cvalue(v: &Json) -> std::sync::Arc<CValue> {
    match v {
        Json::Null => CValue::null(),
        Json::Bool(b) => CValue::boolean(*b),
        Json::Number(n) => {
            if let Some(i) = n.as_i64() {
                CValue::integer(i128::from(i))
            } else if let Some(u) = n.as_u64() {
                CValue::integer(i128::from(u))
            } else if let Some(f) = n.as_f64() {
                CValue::integer(f as i128)
            } else {
                CValue::integer(0)
            }
        }
        Json::String(s) => CValue::string(s.clone()),
        Json::Array(items) => CValue::array(items.iter().map(json_to_cvalue).collect()),
        Json::Object(map) => CValue::object(
            map.iter()
                .map(|(key, value)| (key.clone(), json_to_cvalue(value)))
                .collect::<Vec<_>>(),
        ),
    }
}

fn parse_evidence_at(v: &Json, path: &str) -> Result<EvidenceTerm, ParseError> {
    let obj = require_object(v, path, "evidence")?;
    reject_extra_keys(obj, &["kind", "proofType", "certificate"], path, "evidence")?;
    let kind = require_string(obj, "kind", path)?;
    if kind != "evidence" {
        return Err(ParseError::Mismatch {
            path: format!("{path}.kind"),
            expected: "\"evidence\"".into(),
            actual: format!("\"{kind}\""),
        });
    }
    let proof_type = require_string(obj, "proofType", path)?;
    let cert_v = require_field(obj, "certificate", path)?;
    let cert_obj = require_object(cert_v, &format!("{path}.certificate"), "certificate")?;
    reject_extra_keys(
        cert_obj,
        &["tool", "version", "formulaHash", "proofData"],
        &format!("{path}.certificate"),
        "certificate",
    )?;
    let certificate = EvidenceCertificate {
        tool: require_string(cert_obj, "tool", &format!("{path}.certificate"))?,
        version: require_string(cert_obj, "version", &format!("{path}.certificate"))?,
        formula_hash: require_string(cert_obj, "formulaHash", &format!("{path}.certificate"))?,
        proof_data: require_string(cert_obj, "proofData", &format!("{path}.certificate"))?,
    };
    Ok(EvidenceTerm {
        proof_type,
        certificate,
    })
}

fn parse_formula_at(v: &Json, path: &str) -> Result<Rc<Formula>, ParseError> {
    let obj = require_object(v, path, "formula")?;
    let kind = require_string(obj, "kind", path)?;
    match kind.as_str() {
        "atomic" => {
            reject_extra_keys(obj, &["kind", "name", "args"], path, "atomic")?;
            let name = require_string(obj, "name", path)?;
            let args_v = require_field(obj, "args", path)?;
            let args = require_array(args_v, &format!("{path}.args"), "atomic.args")?;
            let mut terms = Vec::with_capacity(args.len());
            for (i, a) in args.iter().enumerate() {
                terms.push(parse_term_at(a, &format!("{path}.args[{i}]"))?);
            }
            Ok(atomic_(name, terms))
        }
        k @ ("and" | "or" | "not" | "implies") => {
            reject_extra_keys(obj, &["kind", "operands"], path, k)?;
            let ops_v = require_field(obj, "operands", path)?;
            let ops = require_array(ops_v, &format!("{path}.operands"), "operands")?;
            let mut parsed = Vec::with_capacity(ops.len());
            for (i, op) in ops.iter().enumerate() {
                parsed.push(parse_formula_at(op, &format!("{path}.operands[{i}]"))?);
            }
            // Arity rules per the grammar.
            match k {
                "not" if parsed.len() != 1 => {
                    return Err(ParseError::Arity {
                        path: path.into(),
                        kind: k.into(),
                        expected: "exactly 1".into(),
                        actual: parsed.len(),
                    });
                }
                "implies" if parsed.len() != 2 => {
                    return Err(ParseError::Arity {
                        path: path.into(),
                        kind: k.into(),
                        expected: "exactly 2".into(),
                        actual: parsed.len(),
                    });
                }
                "and" | "or" if parsed.len() < 2 => {
                    return Err(ParseError::Arity {
                        path: path.into(),
                        kind: k.into(),
                        expected: "2 or more".into(),
                        actual: parsed.len(),
                    });
                }
                _ => {}
            }
            Ok(match k {
                "not" => not_(parsed.into_iter().next().unwrap()),
                "implies" => {
                    let mut it = parsed.into_iter();
                    let a = it.next().unwrap();
                    let c = it.next().unwrap();
                    implies(a, c)
                }
                "and" => and_(parsed),
                "or" => or_(parsed),
                _ => unreachable!(),
            })
        }
        k @ ("forall" | "exists") => {
            reject_extra_keys(obj, &["kind", "name", "sort", "body"], path, k)?;
            let name = require_string(obj, "name", path)?;
            let sort_v = require_field(obj, "sort", path)?;
            let sort = parse_sort_at(sort_v, &format!("{path}.sort"))?;
            let body_v = require_field(obj, "body", path)?;
            // Note: `forall`/`exists` in the kit use a closure that
            // generates a fresh bound name. Here we already have a
            // bound name from JSON; build the Quantifier node directly
            // (preserving the exact name) rather than via the
            // closure-using helpers, which would mint a new `_xN`.
            let body = parse_formula_at(body_v, &format!("{path}.body"))?;
            Ok(Rc::new(Formula::Quantifier {
                kind: k.into(),
                name,
                sort,
                body,
            }))
        }
        "choice" => {
            reject_extra_keys(obj, &["kind", "varName", "sort", "body"], path, "choice")?;
            let var_name = require_string(obj, "varName", path)?;
            let sort_v = require_field(obj, "sort", path)?;
            let sort = parse_sort_at(sort_v, &format!("{path}.sort"))?;
            let body_v = require_field(obj, "body", path)?;
            let body = parse_formula_at(body_v, &format!("{path}.body"))?;
            Ok(Rc::new(Formula::Choice {
                var_name,
                sort,
                body,
            }))
        }
        other => Err(ParseError::UnknownKind {
            path: path.into(),
            kind: other.into(),
        }),
    }
}

fn parse_term_at(v: &Json, path: &str) -> Result<Rc<Term>, ParseError> {
    let obj = require_object(v, path, "term")?;
    let kind = require_string(obj, "kind", path)?;
    match kind.as_str() {
        "var" => {
            reject_extra_keys(obj, &["kind", "name"], path, "var")?;
            let name = require_string(obj, "name", path)?;
            Ok(make_var(name))
        }
        "const" => {
            reject_extra_keys(obj, &["kind", "value", "sort"], path, "const")?;
            let value_v = require_field(obj, "value", path)?;
            let sort_v = require_field(obj, "sort", path)?;
            let sort = parse_sort_at(sort_v, &format!("{path}.sort"))?;
            // Match Sort.name to dispatch on permissible JSON shape.
            // We accept Int from JSON Number, String from JSON String,
            // Bool from JSON Bool. The grammar also permits Null but
            // it isn't reachable through the kit's authoring API; we
            // reject it here for defense-in-depth.
            let const_value = match (sort.name.as_str(), value_v) {
                ("Int", Json::Number(n)) => {
                    // i64/u64 widen losslessly into the i128 carrier. A wide
                    // Int (> u64) is NOT carried as a bare number (serde_json
                    // would parse it lossily to f64); it arrives as a String,
                    // handled by the next arm.
                    let i = n
                        .as_i64()
                        .map(i128::from)
                        .or_else(|| n.as_u64().map(i128::from))
                        .ok_or_else(|| ParseError::Mismatch {
                            path: format!("{path}.value"),
                            expected: "i64/u64-representable Int (wide ints carried as string)"
                                .into(),
                            actual: n.to_string(),
                        })?;
                    ConstValue::Int(i)
                }
                // A wide Int const is a decimal string under an Int sort.
                ("Int", Json::String(s)) => {
                    let i = s.parse::<i128>().map_err(|_| ParseError::Mismatch {
                        path: format!("{path}.value"),
                        expected: "decimal i128 for wide Int const".into(),
                        actual: s.clone(),
                    })?;
                    ConstValue::Int(i)
                }
                ("String", Json::String(s)) => ConstValue::String(s.clone()),
                ("Bool", Json::Bool(b)) => ConstValue::Bool(*b),
                ("Real", Json::String(s)) => ConstValue::Real(s.clone()),
                (s, v) => {
                    return Err(ParseError::Mismatch {
                        path: format!("{path}.value"),
                        expected: format!("value matching sort {s}"),
                        actual: type_of(v),
                    });
                }
            };
            Ok(Rc::new(Term::Const {
                value: const_value,
                sort,
            }))
        }
        "ctor" => {
            reject_extra_keys(obj, &["kind", "name", "args"], path, "ctor")?;
            let name = require_string(obj, "name", path)?;
            let args_v = require_field(obj, "args", path)?;
            let args = require_array(args_v, &format!("{path}.args"), "ctor.args")?;
            let mut terms = Vec::with_capacity(args.len());
            for (i, a) in args.iter().enumerate() {
                terms.push(parse_term_at(a, &format!("{path}.args[{i}]"))?);
            }
            Ok(Rc::new(Term::Ctor { name, args: terms }))
        }
        "lambda" => {
            reject_extra_keys(
                obj,
                &["kind", "paramName", "paramSort", "body"],
                path,
                "lambda",
            )?;
            let param_name = require_string(obj, "paramName", path)?;
            let param_sort_v = require_field(obj, "paramSort", path)?;
            let param_sort = parse_sort_at(param_sort_v, &format!("{path}.paramSort"))?;
            let body_v = require_field(obj, "body", path)?;
            let body = parse_term_at(body_v, &format!("{path}.body"))?;
            Ok(Rc::new(Term::Lambda {
                param_name,
                param_sort,
                body,
            }))
        }
        "let" => {
            reject_extra_keys(obj, &["kind", "bindings", "body"], path, "let")?;
            let bindings_v = require_field(obj, "bindings", path)?;
            let bindings_arr =
                require_array(bindings_v, &format!("{path}.bindings"), "let.bindings")?;
            let mut bindings = Vec::with_capacity(bindings_arr.len());
            for (i, b) in bindings_arr.iter().enumerate() {
                let b_obj = require_object(b, &format!("{path}.bindings[{i}]"), "binding")?;
                let b_name = require_string(b_obj, "name", &format!("{path}.bindings[{i}]"))?;
                let b_term_v = require_field(b_obj, "boundTerm", &format!("{path}.bindings[{i}]"))?;
                let b_term = parse_term_at(b_term_v, &format!("{path}.bindings[{i}].boundTerm"))?;
                bindings.push(crate::LetBinding {
                    name: b_name,
                    bound_term: b_term,
                });
            }
            let body_v = require_field(obj, "body", path)?;
            let body = parse_term_at(body_v, &format!("{path}.body"))?;
            Ok(Rc::new(Term::Let { bindings, body }))
        }
        other => Err(ParseError::UnknownKind {
            path: path.into(),
            kind: other.into(),
        }),
    }
}

fn parse_sort_at(v: &Json, path: &str) -> Result<Sort, ParseError> {
    let obj = require_object(v, path, "sort")?;
    let kind = require_string(obj, "kind", path)?;
    match kind.as_str() {
        "primitive" => {
            reject_extra_keys(obj, &["kind", "name"], path, "primitive sort")?;
            let name = require_string(obj, "name", path)?;
            Ok(Sort { name })
        }
        // BitvecSort / SetSort / TupleSort / FunctionSort exist in the
        // grammar but the Rust kit's `Sort` is currently primitive-only.
        // We surface this honestly rather than silently dropping data.
        other @ ("bitvec" | "set" | "tuple" | "function") => Err(ParseError::Mismatch {
            path: path.into(),
            expected:
                "primitive sort (Rust kit limitation; bitvec/set/tuple/function not yet typed)"
                    .into(),
            actual: format!("{other} sort"),
        }),
        other => Err(ParseError::UnknownKind {
            path: format!("{path}.kind"),
            kind: other.into(),
        }),
    }
}

// ---- Helpers ----------------------------------------------------------------

fn type_of(v: &Json) -> String {
    match v {
        Json::Null => "null".into(),
        Json::Bool(_) => "bool".into(),
        Json::Number(_) => "number".into(),
        Json::String(_) => "string".into(),
        Json::Array(_) => "array".into(),
        Json::Object(_) => "object".into(),
    }
}

fn require_object<'a>(
    v: &'a Json,
    path: &str,
    label: &str,
) -> Result<&'a serde_json::Map<String, Json>, ParseError> {
    v.as_object().ok_or_else(|| ParseError::Mismatch {
        path: path.into(),
        expected: format!("object ({label})"),
        actual: type_of(v),
    })
}

fn require_field<'a>(
    obj: &'a serde_json::Map<String, Json>,
    field: &str,
    path: &str,
) -> Result<&'a Json, ParseError> {
    obj.get(field).ok_or_else(|| ParseError::MissingField {
        path: path.into(),
        field: field.into(),
    })
}

fn require_string(
    obj: &serde_json::Map<String, Json>,
    field: &str,
    path: &str,
) -> Result<String, ParseError> {
    let v = require_field(obj, field, path)?;
    v.as_str()
        .map(|s| s.to_string())
        .ok_or_else(|| ParseError::Mismatch {
            path: format!("{path}.{field}"),
            expected: "string".into(),
            actual: type_of(v),
        })
}

fn require_array<'a>(v: &'a Json, path: &str, label: &str) -> Result<&'a Vec<Json>, ParseError> {
    v.as_array().ok_or_else(|| ParseError::Mismatch {
        path: path.into(),
        expected: format!("array ({label})"),
        actual: type_of(v),
    })
}

fn reject_extra_keys(
    obj: &serde_json::Map<String, Json>,
    allowed: &[&str],
    path: &str,
    kind: &str,
) -> Result<(), ParseError> {
    for (k, _) in obj {
        if !allowed.contains(&k.as_str()) {
            return Err(ParseError::ExtraKey {
                path: path.into(),
                key: k.clone(),
                kind: kind.into(),
            });
        }
    }
    Ok(())
}

// Re-exports for symmetry with the kit's other primitives. The
// closure-using helpers below duplicate `forall`/`exists` from lib.rs
// but are unused here; we keep them out to avoid name collision.
#[allow(dead_code)]
fn _unused_forall_for_proptest_exemplar() -> Rc<Formula> {
    forall(crate::Int(), |n| crate::gt(n, num(0)))
}
#[allow(dead_code)]
fn _unused_exists_for_proptest_exemplar() -> Rc<Formula> {
    exists(crate::Int(), |n| crate::eq(n, num(0)))
}
#[allow(dead_code)]
fn _unused_str_const_for_proptest_exemplar() -> Rc<Term> {
    str_const("hello")
}

// ---- Unit tests -------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::serialize::{formula_to_value, marshal_declarations};
    use crate::{
        and_, eq, gt, gte, lt, lte, must, not_, num, or_, real_const, reset_collector, str_const,
        ConstValue,
    };

    fn jcs_to_json(v: &std::sync::Arc<sugar_canonicalizer::Value>) -> Json {
        // Round-trip through JCS string -> serde_json::Value for tests.
        let s = sugar_canonicalizer::encode_jcs(v);
        serde_json::from_str(&s).expect("JCS produces valid JSON")
    }

    #[test]
    fn round_trip_simple_atomic() {
        let f = gt(crate::make_var("x"), num(0));
        let j = jcs_to_json(&formula_to_value(&f));
        let parsed = parse_formula(&j).expect("parse");
        // re-serialize and compare
        let j2 = jcs_to_json(&formula_to_value(&parsed));
        assert_eq!(j, j2);
    }

    #[test]
    fn round_trip_quantifier_preserves_bound_name() {
        // Build a forall(Int, n -> n > 0).
        let f = crate::forall(crate::Int(), |n| gt(n, num(0)));
        let j = jcs_to_json(&formula_to_value(&f));
        let parsed = parse_formula(&j).expect("parse");
        let j2 = jcs_to_json(&formula_to_value(&parsed));
        assert_eq!(j, j2);
    }

    #[test]
    fn round_trip_implies_and_not() {
        let f = crate::forall(crate::Int(), |n| {
            implies(gt(n.clone(), num(0)), not_(lt(n, num(0))))
        });
        let j = jcs_to_json(&formula_to_value(&f));
        let parsed = parse_formula(&j).expect("parse");
        let j2 = jcs_to_json(&formula_to_value(&parsed));
        assert_eq!(j, j2);
    }

    #[test]
    fn round_trip_and_or_with_three_operands() {
        let f = and_(vec![
            gt(crate::make_var("x"), num(0)),
            or_(vec![
                eq(crate::make_var("y"), num(1)),
                eq(crate::make_var("y"), num(2)),
                eq(crate::make_var("y"), num(3)),
            ]),
            not_(eq(crate::make_var("z"), num(7))),
        ]);
        let j = jcs_to_json(&formula_to_value(&f));
        let parsed = parse_formula(&j).expect("parse");
        let j2 = jcs_to_json(&formula_to_value(&parsed));
        assert_eq!(j, j2);
    }

    #[test]
    fn round_trip_const_string_term() {
        let f = eq(str_const("blake3-512:foo"), str_const("blake3-512:foo"));
        let j = jcs_to_json(&formula_to_value(&f));
        let parsed = parse_formula(&j).expect("parse");
        let j2 = jcs_to_json(&formula_to_value(&parsed));
        assert_eq!(j, j2);
    }

    #[test]
    fn round_trip_const_real_term() {
        let f = eq(real_const("2.0"), real_const("2.0"));
        let j = jcs_to_json(&formula_to_value(&f));
        let parsed = parse_formula(&j).expect("parse");
        let j2 = jcs_to_json(&formula_to_value(&parsed));
        assert_eq!(j, j2);
    }

    #[test]
    fn round_trip_ctor_term() {
        let ctor = Rc::new(Term::Ctor {
            name: "compute_cid".into(),
            args: vec![crate::make_var("input")],
        });
        let f = atomic_("=", vec![ctor, str_const("blake3-512:abc")]);
        let j = jcs_to_json(&formula_to_value(&f));
        let parsed = parse_formula(&j).expect("parse");
        let j2 = jcs_to_json(&formula_to_value(&parsed));
        assert_eq!(j, j2);
    }

    #[test]
    fn round_trip_document_via_marshal() {
        reset_collector();
        must(
            "compute_cid",
            crate::forall(crate::String_(), |s| eq(s.clone(), s)),
        );
        must(
            "BLAKE3_512",
            crate::forall(crate::String_(), |s| eq(s.clone(), s)),
        );
        let decls = finish();
        let doc = marshal_declarations(&decls);
        let parsed = parse_document(&doc).expect("parse_document");
        assert_eq!(parsed.len(), 2);
        assert_eq!(parsed[0].name, "compute_cid");
        assert_eq!(parsed[1].name, "BLAKE3_512");
    }

    /// Regression: non-ASCII operators `≥` (U+2265) / `≤` (U+2264),
    /// emitted by `gte` / `lte`, must survive the
    /// `marshal_declarations` -> `parse_document` round-trip BYTE-FOR-BYTE.
    ///
    /// The old `write_string` iterated `s.as_bytes()` and pushed each byte
    /// as a `char`, mangling `≥`'s three UTF-8 bytes (E2 89 A5) into three
    /// separate code points (U+00E2/U+0089/U+00A5) — double-encoded
    /// mojibake. This silently corrupted any contract with a `>=`/`<=`
    /// predicate whenever its IR-JSON was round-tripped (the exact path
    /// the RPC lift transport exercises). The earlier ASCII-only round-trip
    /// tests never caught it. This test locks the fix.
    #[test]
    fn round_trip_preserves_non_ascii_operators() {
        reset_collector();
        // A contract whose pre uses `≥` and whose inv uses `≤`.
        must("ge_le_fn", {
            crate::forall(crate::Int(), |x| {
                and_(vec![gte(x.clone(), num(0)), lte(x.clone(), num(100))])
            })
        });
        let decls = finish();
        let doc = marshal_declarations(&decls);
        // The marshalled JSON must contain the real Unicode operators, not
        // mojibake.
        assert!(
            doc.contains('\u{2265}'),
            "marshalled doc must contain U+2265 `≥`, got: {doc}"
        );
        assert!(
            doc.contains('\u{2264}'),
            "marshalled doc must contain U+2264 `≤`, got: {doc}"
        );
        // Round-trip must be byte-stable: marshal(parse(marshal(x))) == marshal(x).
        let reparsed = parse_document(&doc).expect("parse_document");
        let remarshalled = marshal_declarations(&reparsed);
        assert_eq!(
            doc, remarshalled,
            "non-ASCII operator round-trip must be byte-identical"
        );
    }

    // ---- Negative tests -----------------------------------------------------

    #[test]
    fn rejects_unknown_kind() {
        let j: Json = serde_json::from_str(r#"{"kind":"fnord","args":[]}"#).unwrap();
        let r = parse_formula(&j);
        assert!(matches!(r, Err(ParseError::UnknownKind { .. })));
    }

    #[test]
    fn rejects_extra_key_on_var_term() {
        // VarTerm post-v1.1.0 carries no sort; extras must fail loud.
        let j: Json = serde_json::from_str(
            r#"{"kind":"var","name":"x","sort":{"kind":"primitive","name":"Int"}}"#,
        )
        .unwrap();
        let r = parse_term(&j);
        assert!(matches!(r, Err(ParseError::ExtraKey { .. })));
    }

    #[test]
    fn rejects_extra_key_on_ctor_term() {
        let j: Json = serde_json::from_str(
            r#"{"kind":"ctor","name":"f","args":[],"sort":{"kind":"primitive","name":"Int"}}"#,
        )
        .unwrap();
        let r = parse_term(&j);
        assert!(matches!(r, Err(ParseError::ExtraKey { .. })));
    }

    #[test]
    fn rejects_not_with_two_operands() {
        let j: Json = serde_json::from_str(
            r#"{"kind":"not","operands":[
              {"kind":"atomic","name":"=","args":[]},
              {"kind":"atomic","name":"=","args":[]}
            ]}"#,
        )
        .unwrap();
        let r = parse_formula(&j);
        assert!(matches!(r, Err(ParseError::Arity { ref kind, .. }) if kind == "not"));
    }

    #[test]
    fn rejects_implies_with_one_operand() {
        let j: Json = serde_json::from_str(
            r#"{"kind":"implies","operands":[{"kind":"atomic","name":"=","args":[]}]}"#,
        )
        .unwrap();
        let r = parse_formula(&j);
        assert!(matches!(r, Err(ParseError::Arity { ref kind, .. }) if kind == "implies"));
    }

    #[test]
    fn rejects_singleton_and() {
        let j: Json = serde_json::from_str(
            r#"{"kind":"and","operands":[{"kind":"atomic","name":"=","args":[]}]}"#,
        )
        .unwrap();
        let r = parse_formula(&j);
        assert!(matches!(r, Err(ParseError::Arity { ref kind, .. }) if kind == "and"));
    }

    #[test]
    fn rejects_missing_required_field() {
        let j: Json = serde_json::from_str(r#"{"kind":"atomic","args":[]}"#).unwrap();
        let r = parse_formula(&j);
        assert!(matches!(r, Err(ParseError::MissingField { ref field, .. }) if field == "name"));
    }

    #[test]
    fn rejects_empty_contract() {
        let j: Json =
            serde_json::from_str(r#"{"kind":"contract","name":"x","outBinding":"out"}"#).unwrap();
        let r = parse_contract(&j);
        assert!(matches!(r, Err(ParseError::EmptyContract { .. })));
    }

    #[test]
    fn const_value_rejects_sort_mismatch() {
        // Int sort with a String value.
        let j: Json = serde_json::from_str(
            r#"{"kind":"const","value":"hello","sort":{"kind":"primitive","name":"Int"}}"#,
        )
        .unwrap();
        let r = parse_term(&j);
        assert!(matches!(r, Err(ParseError::Mismatch { .. })));
    }

    #[test]
    fn determinism_same_input_same_output() {
        // Hand-written stable input.
        let raw = r#"{"kind":"forall","name":"_x0","sort":{"kind":"primitive","name":"Int"},"body":{"kind":"atomic","name":">","args":[{"kind":"var","name":"_x0"},{"kind":"const","value":0,"sort":{"kind":"primitive","name":"Int"}}]}}"#;
        let j: Json = serde_json::from_str(raw).unwrap();
        let f1 = parse_formula(&j).expect("parse 1");
        let f2 = parse_formula(&j).expect("parse 2");
        // Re-serialize and compare bytes.
        let s1 = sugar_canonicalizer::encode_jcs(&formula_to_value(&f1));
        let s2 = sugar_canonicalizer::encode_jcs(&formula_to_value(&f2));
        assert_eq!(s1, s2);
    }

    // Demonstrates that `_` in `ConstValue::Int(_)` matches; placeholder
    // to ensure that variant is exercised.
    #[test]
    fn const_int_value_round_trip() {
        let t = num(42);
        let v = crate::serialize::term_to_value(&t);
        let j = jcs_to_json(&v);
        let parsed = parse_term(&j).expect("parse");
        match parsed.as_ref() {
            Term::Const {
                value: ConstValue::Int(42),
                ..
            } => {}
            other => panic!("expected Const Int 42, got {other:?}"),
        }
    }
}

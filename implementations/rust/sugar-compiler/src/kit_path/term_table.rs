use std::collections::{BTreeMap, BTreeSet};
use std::sync::{Arc, OnceLock};
use std::time::Instant;

use serde_json::Value;
use sugar_canonicalizer::Value as CanonicalValue;

#[derive(Debug)]
pub struct LiftTermNode {
    cid: String,
    kind: LiftTermKind,
    canonical: OnceLock<Arc<CanonicalValue>>,
}

#[derive(Debug)]
pub enum LiftTermKind {
    Var {
        name: String,
    },
    Const {
        value: Value,
        sort: Value,
    },
    Ctor {
        name: String,
        args: Vec<Arc<LiftTermNode>>,
    },
}

impl LiftTermNode {
    pub fn cid(&self) -> &str {
        &self.cid
    }

    pub fn kind(&self) -> &LiftTermKind {
        &self.kind
    }

    pub fn args(&self) -> Option<&[Arc<LiftTermNode>]> {
        match &self.kind {
            LiftTermKind::Ctor { args, .. } => Some(args),
            _ => None,
        }
    }

    pub fn canonical(&self) -> Arc<CanonicalValue> {
        self.canonical
            .get_or_init(|| match &self.kind {
                LiftTermKind::Var { name } => CanonicalValue::object(vec![
                    ("kind".to_string(), CanonicalValue::string("var")),
                    ("name".to_string(), CanonicalValue::string(name.clone())),
                ]),
                LiftTermKind::Const { value, sort } => CanonicalValue::object(vec![
                    ("kind".to_string(), CanonicalValue::string("const")),
                    ("value".to_string(), json_to_canonical(value)),
                    ("sort".to_string(), json_to_canonical(sort)),
                ]),
                LiftTermKind::Ctor { name, args } => CanonicalValue::object(vec![
                    ("kind".to_string(), CanonicalValue::string("ctor")),
                    ("name".to_string(), CanonicalValue::string(name.clone())),
                    (
                        "args".to_string(),
                        CanonicalValue::array(args.iter().map(|arg| arg.canonical()).collect()),
                    ),
                ]),
            })
            .clone()
    }

    fn wire_value(&self) -> Value {
        match &self.kind {
            LiftTermKind::Var { name } => serde_json::json!({"kind": "var", "name": name}),
            LiftTermKind::Const { value, sort } => {
                serde_json::json!({"kind": "const", "value": value, "sort": sort})
            }
            LiftTermKind::Ctor { name, args } => serde_json::json!({
                "kind": "ctor",
                "name": name,
                "args": args.iter().map(|arg| serde_json::json!({
                    "kind": "term-ref", "cid": arg.cid()
                })).collect::<Vec<_>>()
            }),
        }
    }

    fn resolved_value(&self) -> Value {
        match &self.kind {
            LiftTermKind::Var { name } => serde_json::json!({"kind": "var", "name": name}),
            LiftTermKind::Const { value, sort } => {
                serde_json::json!({"kind": "const", "value": value, "sort": sort})
            }
            LiftTermKind::Ctor { name, args } => serde_json::json!({
                "kind": "ctor",
                "name": name,
                "args": args.iter().map(|arg| arg.resolved_value()).collect::<Vec<_>>()
            }),
        }
    }
}

#[derive(Debug)]
pub struct LiftTermTable {
    nodes: BTreeMap<String, Arc<LiftTermNode>>,
}

impl LiftTermTable {
    pub fn decode(payload: &Value) -> Result<Self, String> {
        let started = Instant::now();
        let raw = payload
            .get("termTable")
            .and_then(Value::as_object)
            .ok_or("ir-document missing required `termTable` object")?;
        let mut nodes = BTreeMap::new();
        let mut active = BTreeSet::new();
        for cid in raw.keys() {
            decode_node(cid, raw, &mut nodes, &mut active)?;
        }
        for (cid, node) in &nodes {
            let actual = sugar_canonicalizer::blake3_512_of(
                sugar_canonicalizer::encode_jcs(node.canonical().as_ref()).as_bytes(),
            );
            if actual != *cid {
                return Err(format!(
                    "term-table CID mismatch: key `{cid}` resolves to `{actual}`"
                ));
            }
        }
        tracing::info!(
            stage = "lift_plugin.term_table.decode.complete",
            unique_nodes = nodes.len(),
            elapsed_ms = started.elapsed().as_millis(),
            "decoded shared lift term table"
        );
        Ok(Self { nodes })
    }

    pub fn get(&self, cid: &str) -> Option<Arc<LiftTermNode>> {
        self.nodes.get(cid).cloned()
    }

    pub fn resolve_reference(&self, reference: &Value) -> Result<Arc<LiftTermNode>, String> {
        if reference.get("kind").and_then(Value::as_str) != Some("term-ref") {
            return Err("term position must be a `{kind: term-ref, cid}` object".to_string());
        }
        let cid = reference
            .get("cid")
            .and_then(Value::as_str)
            .ok_or("term position must be a `{kind: term-ref, cid}` object")?;
        self.get(cid)
            .ok_or_else(|| format!("missing term-table CID `{cid}`"))
    }

    pub fn wire_value(&self) -> Value {
        Value::Object(
            self.nodes
                .iter()
                .map(|(cid, node)| (cid.clone(), node.wire_value()))
                .collect(),
        )
    }

    pub fn canonical_value(&self, value: &Value) -> Result<Arc<CanonicalValue>, String> {
        if value.get("kind").and_then(Value::as_str) == Some("term-ref") {
            return Ok(self.resolve_reference(value)?.canonical());
        }
        match value {
            Value::Null => Ok(CanonicalValue::null()),
            Value::Bool(value) => Ok(CanonicalValue::boolean(*value)),
            Value::Number(value) => Ok(CanonicalValue::integer(
                value
                    .as_i64()
                    .map(i128::from)
                    .or_else(|| value.as_u64().map(i128::from))
                    .ok_or("ProofIR numeric value is not a canonical integer")?,
            )),
            Value::String(value) => Ok(CanonicalValue::string(value.clone())),
            Value::Array(values) => Ok(CanonicalValue::array(
                values
                    .iter()
                    .map(|value| self.canonical_value(value))
                    .collect::<Result<Vec<_>, _>>()?,
            )),
            Value::Object(values) => Ok(CanonicalValue::object(
                values
                    .iter()
                    .map(|(key, value)| Ok((key.clone(), self.canonical_value(value)?)))
                    .collect::<Result<Vec<_>, String>>()?,
            )),
        }
    }

    /// Resolve every term-ref in an arbitrary response-owned JSON value.
    ///
    /// Enumeration stays DAG-only on the wire; this projection exists solely
    /// at the typed consumer boundary, where `IrFormula` expects recursive
    /// term values. A missing ref remains a loud validator error.
    pub fn resolve_value(&self, value: &Value) -> Result<Value, String> {
        if value.get("kind").and_then(Value::as_str) == Some("term-ref") {
            return Ok(self.resolve_reference(value)?.resolved_value());
        }
        match value {
            Value::Array(values) => Ok(Value::Array(
                values
                    .iter()
                    .map(|value| self.resolve_value(value))
                    .collect::<Result<Vec<_>, _>>()?,
            )),
            Value::Object(values) => Ok(Value::Object(
                values
                    .iter()
                    .map(|(key, value)| Ok((key.clone(), self.resolve_value(value)?)))
                    .collect::<Result<serde_json::Map<_, _>, String>>()?,
            )),
            scalar => Ok(scalar.clone()),
        }
    }
}

fn decode_node(
    cid: &str,
    raw: &serde_json::Map<String, Value>,
    nodes: &mut BTreeMap<String, Arc<LiftTermNode>>,
    active: &mut BTreeSet<String>,
) -> Result<Arc<LiftTermNode>, String> {
    if let Some(node) = nodes.get(cid) {
        return Ok(node.clone());
    }
    if !active.insert(cid.to_string()) {
        return Err(format!("cyclic term-table reference at CID `{cid}`"));
    }
    let value = raw
        .get(cid)
        .ok_or_else(|| format!("missing term-table CID `{cid}`"))?;
    let kind = value
        .get("kind")
        .and_then(Value::as_str)
        .ok_or_else(|| format!("term-table CID `{cid}` missing node kind"))?;
    let node = match kind {
        "var" => LiftTermKind::Var {
            name: required_string(value, "name", cid)?,
        },
        "const" => LiftTermKind::Const {
            value: value
                .get("value")
                .cloned()
                .ok_or_else(|| format!("term-table CID `{cid}` missing const value"))?,
            sort: value
                .get("sort")
                .cloned()
                .ok_or_else(|| format!("term-table CID `{cid}` missing const sort"))?,
        },
        "ctor" => {
            let args = value
                .get("args")
                .and_then(Value::as_array)
                .ok_or_else(|| format!("term-table CID `{cid}` missing ctor args"))?
                .iter()
                .map(|reference| {
                    if reference.get("kind").and_then(Value::as_str) != Some("term-ref") {
                        return Err(format!(
                            "term-table CID `{cid}` has invalid child: expected kind `term-ref`"
                        ));
                    }
                    let child = reference
                        .get("cid")
                        .and_then(Value::as_str)
                        .ok_or_else(|| format!("term-table CID `{cid}` has invalid term-ref"))?;
                    decode_node(child, raw, nodes, active)
                })
                .collect::<Result<Vec<_>, _>>()?;
            LiftTermKind::Ctor {
                name: required_string(value, "name", cid)?,
                args,
            }
        }
        other => return Err(format!("term-table CID `{cid}` has unknown kind `{other}`")),
    };
    active.remove(cid);
    let node = Arc::new(LiftTermNode {
        cid: cid.to_string(),
        kind: node,
        canonical: OnceLock::new(),
    });
    nodes.insert(cid.to_string(), node.clone());
    Ok(node)
}

fn json_to_canonical(value: &Value) -> Arc<CanonicalValue> {
    match value {
        Value::Null => CanonicalValue::null(),
        Value::Bool(value) => CanonicalValue::boolean(*value),
        Value::Number(value) => CanonicalValue::integer(
            value
                .as_i64()
                .map(i128::from)
                .or_else(|| value.as_u64().map(i128::from))
                .expect("ProofIR numbers are canonical integers"),
        ),
        Value::String(value) => CanonicalValue::string(value.clone()),
        Value::Array(values) => {
            CanonicalValue::array(values.iter().map(json_to_canonical).collect())
        }
        Value::Object(values) => CanonicalValue::object(
            values
                .iter()
                .map(|(key, value)| (key.clone(), json_to_canonical(value)))
                .collect::<Vec<_>>(),
        ),
    }
}

fn required_string(value: &Value, field: &str, cid: &str) -> Result<String, String> {
    value
        .get(field)
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| format!("term-table CID `{cid}` missing `{field}`"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn cid(value: &Value) -> String {
        sugar_canonicalizer::blake3_512_of(
            sugar_canonicalizer::encode_jcs(json_to_canonical(value).as_ref()).as_bytes(),
        )
    }

    #[test]
    fn decode_refuses_omitted_dangling_cycle_malformed_and_cid_mismatch() {
        assert!(LiftTermTable::decode(&json!({}))
            .unwrap_err()
            .contains("missing required `termTable`"));

        let dangling = json!({
            "termTable": {
                "blake3-512:parent": {
                    "kind": "ctor", "name": "call:bad",
                    "args": [{"kind": "term-ref", "cid": "blake3-512:missing"}]
                }
            }
        });
        assert!(LiftTermTable::decode(&dangling)
            .unwrap_err()
            .contains("missing term-table CID"));

        let cycle = json!({
            "termTable": {
                "blake3-512:a": {
                    "kind": "ctor", "name": "a",
                    "args": [{"kind": "term-ref", "cid": "blake3-512:b"}]
                },
                "blake3-512:b": {
                    "kind": "ctor", "name": "b",
                    "args": [{"kind": "term-ref", "cid": "blake3-512:a"}]
                }
            }
        });
        assert!(LiftTermTable::decode(&cycle)
            .unwrap_err()
            .contains("cyclic term-table reference"));

        let malformed = json!({
            "termTable": {
                "blake3-512:parent": {
                    "kind": "ctor", "name": "bad",
                    "args": [{"kind": "var", "name": "inline"}]
                }
            }
        });
        assert!(LiftTermTable::decode(&malformed)
            .unwrap_err()
            .contains("invalid child"));

        let mismatch = json!({
            "termTable": {
                "blake3-512:not-content": {"kind": "var", "name": "x"}
            }
        });
        assert!(LiftTermTable::decode(&mismatch)
            .unwrap_err()
            .contains("term-table CID mismatch"));
    }

    #[test]
    fn shared_subterms_decode_once_and_resolve_at_formula_boundary() {
        let leaf = json!({"kind": "var", "name": "x"});
        let leaf_cid = cid(&leaf);
        let resolved_parent = json!({
            "kind": "ctor", "name": "call:pair", "args": [leaf.clone(), leaf.clone()]
        });
        let parent_cid = cid(&resolved_parent);
        let payload = json!({
            "termTable": {
                (leaf_cid.clone()): leaf,
                (parent_cid.clone()): {
                    "kind": "ctor", "name": "call:pair",
                    "args": [
                        {"kind": "term-ref", "cid": leaf_cid.clone()},
                        {"kind": "term-ref", "cid": leaf_cid.clone()}
                    ]
                }
            }
        });
        let table = LiftTermTable::decode(&payload).expect("valid shared DAG");
        let parent = table.get(&parent_cid).expect("parent");
        let args = parent.args().expect("ctor args");
        assert!(Arc::ptr_eq(&args[0], &args[1]));

        let formula = json!({
            "kind": "atomic", "name": "same",
            "args": [
                {"kind": "term-ref", "cid": parent_cid.clone()},
                {"kind": "term-ref", "cid": parent_cid}
            ]
        });
        let resolved = table.resolve_value(&formula).expect("formula refs resolve");
        assert_eq!(resolved["args"][0], resolved_parent);
        assert_eq!(resolved["args"][0], resolved["args"][1]);
    }
}

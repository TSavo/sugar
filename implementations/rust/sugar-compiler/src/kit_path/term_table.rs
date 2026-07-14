use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

use serde_json::Value;

#[derive(Debug)]
pub enum LiftTermNode {
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
    pub fn args(&self) -> Option<&[Arc<LiftTermNode>]> {
        match self {
            Self::Ctor { args, .. } => Some(args),
            _ => None,
        }
    }
}

#[derive(Debug)]
pub struct LiftTermTable {
    nodes: BTreeMap<String, Arc<LiftTermNode>>,
}

impl LiftTermTable {
    pub fn decode(payload: &Value) -> Result<Self, String> {
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
            let actual = sugar_canonicalizer::jcs_cid_of_json(&node.to_expanded_json());
            if actual != *cid {
                return Err(format!(
                    "term-table CID mismatch: key `{cid}` resolves to `{actual}`"
                ));
            }
        }
        Ok(Self { nodes })
    }

    pub fn get(&self, cid: &str) -> Option<Arc<LiftTermNode>> {
        self.nodes.get(cid).cloned()
    }
}

impl LiftTermNode {
    pub fn to_expanded_json(&self) -> Value {
        match self {
            Self::Var { name } => serde_json::json!({"kind": "var", "name": name}),
            Self::Const { value, sort } => {
                serde_json::json!({"kind": "const", "value": value, "sort": sort})
            }
            Self::Ctor { name, args } => serde_json::json!({
                "kind": "ctor",
                "name": name,
                "args": args.iter().map(|arg| arg.to_expanded_json()).collect::<Vec<_>>()
            }),
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
        "var" => LiftTermNode::Var {
            name: required_string(value, "name", cid)?,
        },
        "const" => LiftTermNode::Const {
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
                    let child = reference
                        .get("cid")
                        .and_then(Value::as_str)
                        .ok_or_else(|| format!("term-table CID `{cid}` has invalid term-ref"))?;
                    decode_node(child, raw, nodes, active)
                })
                .collect::<Result<Vec<_>, _>>()?;
            LiftTermNode::Ctor {
                name: required_string(value, "name", cid)?,
                args,
            }
        }
        other => return Err(format!("term-table CID `{cid}` has unknown kind `{other}`")),
    };
    active.remove(cid);
    let node = Arc::new(node);
    nodes.insert(cid.to_string(), node.clone());
    Ok(node)
}

fn required_string(value: &Value, field: &str, cid: &str) -> Result<String, String> {
    value
        .get(field)
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| format!("term-table CID `{cid}` missing `{field}`"))
}

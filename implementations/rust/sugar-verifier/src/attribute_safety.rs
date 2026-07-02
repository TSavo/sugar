use serde_json::{json, Value as Json};
use tracing::debug;

use crate::types::{CallSite, MementoPool, ObligationVerdict};

#[derive(Debug, Clone)]
pub struct AttributeSafetyDischarge {
    pub verdict: ObligationVerdict,
    pub reason: String,
    pub discharge_method: Option<String>,
}

pub fn try_discharge(cs: &CallSite, pool: &MementoPool) -> Option<AttributeSafetyDischarge> {
    let obligation = cs.attribute_safety.as_ref()?;
    let Some(class_name) = obligation
        .receiver_class
        .as_deref()
        .filter(|name| !name.is_empty())
    else {
        return Some(unproven(
            "attribute-safety: unknown receiver type; no classShapes catalog key to check",
        ));
    };
    let attr_name = obligation.attribute.as_str();
    if attr_name.is_empty() {
        return Some(unproven(
            "attribute-safety: malformed obligation with empty attribute name",
        ));
    }

    let Some(receiver_term) = receiver_term_for_attribute_access(cs, attr_name) else {
        return Some(unproven(
            "attribute-safety: malformed or mismatched python:attribute argTerm",
        ));
    };
    let required_guard = attribute_present_guard(receiver_term, attr_name);
    if cs.guard_facts.iter().any(|guard| guard == &required_guard) {
        return Some(discharged(format!(
            "attribute-safety: cf_guarded attribute_present fact discharges {class_name}.{attr_name}"
        )));
    }

    let Some(shape) = pool.class_shapes_by_class.get(class_name) else {
        return Some(unproven(format!(
            "attribute-safety: no classShapes entry for receiver type {class_name}"
        )));
    };
    if class_shape_guarantees_attribute(shape, class_name, attr_name) {
        return Some(discharged(format!(
            "attribute-safety: classShapes guaranteed-present attribute discharges {class_name}.{attr_name}"
        )));
    }

    Some(unproven(format!(
        "attribute-safety: {class_name}.{attr_name} is not a guaranteed-present classShapes attribute"
    )))
}

fn discharged(reason: String) -> AttributeSafetyDischarge {
    AttributeSafetyDischarge {
        verdict: ObligationVerdict::Discharged,
        reason,
        discharge_method: Some("panic-safe".to_string()),
    }
}

fn unproven(reason: impl Into<String>) -> AttributeSafetyDischarge {
    AttributeSafetyDischarge {
        verdict: ObligationVerdict::Undecidable,
        reason: reason.into(),
        discharge_method: None,
    }
}

fn receiver_term_for_attribute_access(cs: &CallSite, attr_name: &str) -> Option<Json> {
    let term = cs.arg_term.as_ref()?;
    if term.get("kind").and_then(|v| v.as_str()) != Some("ctor") {
        return None;
    }
    if term.get("name").and_then(|v| v.as_str()) != Some("python:attribute") {
        return None;
    }
    let args = term.get("args").and_then(|v| v.as_array())?;
    if args.len() != 2 {
        return None;
    }
    let lifted_attr = args
        .get(1)
        .and_then(|v| v.get("value"))
        .and_then(|v| v.as_str())?;
    if lifted_attr != attr_name {
        return None;
    }
    args.first().cloned()
}

fn attribute_present_guard(receiver_term: Json, attr_name: &str) -> Json {
    json!({
        "kind": "atomic",
        "name": "attribute_present",
        "args": [
            receiver_term,
            {
                "kind": "const",
                "value": attr_name,
                "sort": {"kind": "primitive", "name": "String"}
            }
        ]
    })
}

fn class_shape_guarantees_attribute(shape: &Json, class_name: &str, attr_name: &str) -> bool {
    let status_closed = shape.get("status").and_then(|v| v.as_str()) == Some("closed");
    let Some(open_reasons) = shape.get("openReasons") else {
        debug!("classShapes entry for {class_name} lacks openReasons; treating as open");
        return false;
    };
    let open_reasons_empty = open_reasons
        .as_array()
        .is_some_and(|items| items.is_empty());
    if !status_closed || !open_reasons_empty {
        return false;
    }
    shape
        .get("attributes")
        .and_then(|v| v.as_array())
        .into_iter()
        .flatten()
        .any(|entry| {
            entry.get("name").and_then(|v| v.as_str()) == Some(attr_name)
                && entry.get("presence").and_then(|v| v.as_str()) == Some("guaranteed")
        })
}

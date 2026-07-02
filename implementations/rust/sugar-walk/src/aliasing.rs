// SPDX-License-Identifier: Apache-2.0
//
// C.8 aliasing analysis: walk type definitions to detect interior mutability.

use serde_json::Value;
use std::collections::HashSet;

/// Known types that wrap UnsafeCell. Detection of any of these in a
/// transitive type walk means the type has interior mutability.
const INTERIOR_MUT_TYPE_NAMES: &[&str] = &[
    "UnsafeCell",
    "Cell",
    "RefCell",
    "Mutex",
    "RwLock",
    "OnceCell",
    "LazyLock",
];

/// Walk the type graph starting from `ty` and return true if any
/// transitively-reachable ADT is an interior-mutability wrapper.
/// Uses `visited` for cycle detection keyed on Charon ADT def_id.
pub fn has_unsafecell_transitive(
    ty: &Value,
    type_decls: Option<&Value>,
    visited: &mut HashSet<u64>,
) -> bool {
    let inner = match ty.get("Untagged") {
        Some(v) => v,
        None => return false,
    };

    // Adt: recurse into fields
    if let Some(adt) = inner.get("Adt") {
        let id = adt.get("id");
        let adt_id = id
            .and_then(|i| i.as_u64())
            .or_else(|| id.and_then(|i| i.get("Adt")).and_then(|a| a.as_u64()));

        // Check the ADT's own name against interior-mut set
        if let Some(type_name) = adt_name_for_id(type_decls, adt_id) {
            if INTERIOR_MUT_TYPE_NAMES.contains(&type_name.as_str()) {
                return true;
            }
        }

        // Cycle detection
        if let Some(aid) = adt_id {
            if !visited.insert(aid) {
                return false; // already visited, no interior mut found
            }
        }

        // Recurse into generic type params
        // P1f: only wrap in Untagged if the element is not already a Ty object
        if let Some(types_arr) = adt
            .get("generics")
            .and_then(|g| g.get("types"))
            .and_then(|t| t.as_array())
        {
            for t in types_arr {
                let wrapped =
                    if t.is_object() && t.as_object().is_some_and(|o| o.contains_key("Untagged")) {
                        t.clone()
                    } else {
                        let mut map = serde_json::Map::new();
                        map.insert("Untagged".to_string(), t.clone());
                        Value::Object(map)
                    };
                if has_unsafecell_transitive(&wrapped, type_decls, visited) {
                    return true;
                }
            }
        }

        // P1a: walk ADT field types from type_decls
        if let Some(aid) = adt_id {
            if let Some(tds) = type_decls.and_then(|v| v.as_array()) {
                for td in tds {
                    if adt_decl_matches_id(td, aid) {
                        let kind = td.get("kind");
                        if let Some(fields_arr) = kind
                            .and_then(|k| k.get("Struct"))
                            .and_then(|v| v.as_array())
                        {
                            for field in fields_arr {
                                if let Some(ft) = field.get("ty") {
                                    if has_unsafecell_transitive(ft, type_decls, visited) {
                                        return true;
                                    }
                                }
                            }
                        }
                        if let Some(variants_arr) =
                            kind.and_then(|k| k.get("Enum")).and_then(|v| v.as_array())
                        {
                            for variant in variants_arr {
                                if let Some(fields_arr) =
                                    variant.get("fields").and_then(|v| v.as_array())
                                {
                                    for field in fields_arr {
                                        if let Some(ft) = field.get("ty") {
                                            if has_unsafecell_transitive(ft, type_decls, visited) {
                                                return true;
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        break;
                    }
                }
            }
        }
        return false;
    }

    // Reference: recurse into referent type
    if let Some(arr) = inner.get("Ref").and_then(|v| v.as_array()) {
        if arr.len() >= 2 {
            return has_unsafecell_transitive(&arr[1], type_decls, visited);
        }
    }

    // Slice: recurse into element type
    if let Some(elem) = inner.get("Slice") {
        return has_unsafecell_transitive(elem, type_decls, visited);
    }

    false
}

/// Check whether a type_decl entry matches the given Adt def_id.
/// Handles both shapes: numeric def_id (local decls: `{"def_id": 0}`)
/// and indexed def_id (foreign decls: `{"def_id": {"index": 0}}`).
pub fn adt_decl_matches_id(td: &Value, target: u64) -> bool {
    let def_id = td.get("def_id");
    // Foreign shape: {"def_id": {"index": N}}
    if let Some(idx) = def_id.and_then(|d| d.get("index")).and_then(|i| i.as_u64()) {
        return idx == target;
    }
    // Local shape: {"def_id": N}
    if let Some(idx) = def_id.and_then(|v| v.as_u64()) {
        return idx == target;
    }
    false
}

/// Look up an ADT's source name from the type_decls table.
fn adt_name_for_id(type_decls: Option<&Value>, adt_id: Option<u64>) -> Option<String> {
    let tds = type_decls?.as_array()?;
    let target = adt_id?;
    for td in tds {
        if !adt_decl_matches_id(td, target) {
            continue;
        }
        let name_arr = td.get("item_meta")?.get("name")?.as_array()?;
        for seg in name_arr.iter().rev() {
            if let Some(ident_arr) = seg.get("Ident").and_then(|v| v.as_array()) {
                if let Some(s) = ident_arr.first().and_then(|v| v.as_str()) {
                    return Some(s.to_string());
                }
            }
        }
    }
    None
}

/// True when a Charon Ty JSON value is a shared reference (`&T`).
pub fn is_shared_ref_charon_ty(ty: &Value) -> bool {
    ty.get("Untagged")
        .and_then(|i| i.get("Ref"))
        .and_then(|r| r.as_array())
        .and_then(|arr| arr.get(2))
        .and_then(|m| m.as_str())
        .is_some_and(|m| m == "Shared")
}

/// True when a Charon Ty JSON value is a mutable reference (`&mut T`).
pub fn is_mut_ref_charon_ty(ty: &Value) -> bool {
    ty.get("Untagged")
        .and_then(|i| i.get("Ref"))
        .and_then(|r| r.as_array())
        .and_then(|arr| arr.get(2))
        .and_then(|m| m.as_str())
        .is_some_and(|m| m == "Mut")
}

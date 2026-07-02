// SPDX-License-Identifier: Apache-2.0
//
// Closure-capture detection (#383, Tier 2.6).
//
// In Charon's LLBC, closures are encoded as TWO separable artifacts:
//
//   1. The closure BODY is emitted as one or more regular fun_decls,
//      one per Fn/FnMut/FnOnce trait method. Their item_meta.name
//      paths are e.g.
//        [..., Ident("f"), Impl{Trait:N}, Ident("call_mut")]
//      The body is lifted normally through the usual pipeline; its
//      contract goes into the registry under the impl's trailing
//      Ident.
//
//   2. The closure TYPE is emitted as a Struct type_decl whose
//      item_meta.name path ENDS in `Ident("closure")`:
//        [..., Ident("f"), Ident("closure")]
//      This is Charon's synthetic-closure-type marker. When a
//      function CONSTRUCTS a closure, MIR emits an
//      `Aggregate(Adt(<this-type-id>, _), [captures])` rvalue.
//
// What we emit for the constructing site
//   - `Effect::ClosureCapture { body_fn_cid, n_captures }`. The
//     body_fn_cid is the JCS-byte hash of the matching trait-impl
//     fun_decl (we find it by matching the path prefix up to the
//     `Ident("closure")` marker, then finding a fun_decl whose path
//     is the same prefix + `Impl{...} + Ident("call"|"call_mut"|"call_once")`).
//   - n_captures: count of operands in the Aggregate.
//
// The substrate sees the capture link and refuses composition through
// the closure call until the body's contract resolves through the
// usual call-composition path.

use serde_json::Value;

use crate::canonical::{cid_of_value, serde_to_canonical};

/// One detected closure-capture site in a function body.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClosureCaptureFingerprint {
    /// Content-addressed hash of the matching trait-impl method's
    /// fun_decl (the closure body). Empty string if no matching
    /// fun_decl was found (e.g., extern closure).
    pub body_fn_cid: String,
    /// Number of captured operands in the Aggregate.
    pub n_captures: usize,
}

/// Walk a body's statements, returning a fingerprint for every
/// closure-capture site (`Aggregate(Adt(closure_type_id, _), [captures])`).
/// Recurses into Switch::If branches, Switch::SwitchInt arms, and
/// Loop bodies.
pub fn extract_closure_captures(
    stmts: &[&Value],
    type_decls: Option<&Value>,
    fun_decls: Option<&Value>,
) -> Vec<ClosureCaptureFingerprint> {
    let mut out = Vec::new();
    for s in stmts {
        collect_in_stmt(s, type_decls, fun_decls, &mut out);
    }
    out
}

fn collect_in_stmt(
    stmt: &Value,
    type_decls: Option<&Value>,
    fun_decls: Option<&Value>,
    out: &mut Vec<ClosureCaptureFingerprint>,
) {
    let Some(kind) = stmt.get("kind") else {
        return;
    };

    if let Some(arr) = kind.get("Assign").and_then(|v| v.as_array()) {
        if arr.len() == 2 {
            if let Some(rvalue) = arr.get(1) {
                if let Some(agg) = rvalue.get("Aggregate").and_then(|v| v.as_array()) {
                    if agg.len() == 2 {
                        let agg_kind = &agg[0];
                        let Some(captures) = agg[1].as_array().map(|a| a.len()) else {
                            return;
                        };
                        if let Some(closure_path) = adt_kind_is_closure(agg_kind, type_decls) {
                            let body_fn_cid = find_closure_body_cid(&closure_path, fun_decls);
                            out.push(ClosureCaptureFingerprint {
                                body_fn_cid,
                                n_captures: captures,
                            });
                        }
                    }
                }
            }
        }
    }

    if let Some(switch) = kind.get("Switch") {
        if let Some(if_arr) = switch.get("If").and_then(|v| v.as_array()) {
            if if_arr.len() == 3 {
                recurse_block(&if_arr[1], type_decls, fun_decls, out);
                recurse_block(&if_arr[2], type_decls, fun_decls, out);
            }
        }
        if let Some(si) = switch.get("SwitchInt").and_then(|v| v.as_array()) {
            if si.len() == 4 {
                if let Some(arms) = si[2].as_array() {
                    for arm in arms {
                        if let Some(arr) = arm.as_array() {
                            if arr.len() == 2 {
                                recurse_block(&arr[1], type_decls, fun_decls, out);
                            }
                        }
                    }
                }
                recurse_block(&si[3], type_decls, fun_decls, out);
            }
        }
        if let Some(match_arr) = switch.get("Match").and_then(|v| v.as_array()) {
            for arm in match_arr.iter().skip(1) {
                if arm.is_object() {
                    recurse_block(arm, type_decls, fun_decls, out);
                }
            }
        }
    }
    if let Some(loop_block) = kind.get("Loop") {
        recurse_block(loop_block, type_decls, fun_decls, out);
    }
}

fn recurse_block(
    block: &Value,
    type_decls: Option<&Value>,
    fun_decls: Option<&Value>,
    out: &mut Vec<ClosureCaptureFingerprint>,
) {
    if let Some(inner) = block.get("statements").and_then(|s| s.as_array()) {
        for s in inner {
            collect_in_stmt(s, type_decls, fun_decls, out);
        }
    }
}

/// If `agg_kind` is `Adt(adt_id, _)` and `type_decls[adt_id]`'s
/// item_meta.name ends in `Ident("closure")`, return the path
/// PREFIX (everything before the `Ident("closure")` marker) so the
/// caller can look up the matching trait-impl fun_decl. Otherwise
/// return None.
fn adt_kind_is_closure(agg_kind: &Value, type_decls: Option<&Value>) -> Option<Vec<Value>> {
    let adt = agg_kind.get("Adt")?;
    // Charon AggregateKind::Adt = [TypeDeclRef, variant_id, ...]
    // TypeDeclRef = {"id": {"Adt": <id>}, "generics": ...} for a struct.
    let arr = adt.as_array()?;
    let type_id_obj = arr.first()?;
    let adt_id = type_id_obj
        .get("id")
        .and_then(|i| i.get("Adt"))
        .and_then(|v| v.as_u64())?;

    let type_decls = type_decls?.as_array()?;
    let decl = type_decls
        .iter()
        .find(|d| d.get("def_id").and_then(|v| v.as_u64()) == Some(adt_id))?;
    let elems = decl.get("item_meta")?.get("name")?.as_array()?;

    // Last element must be Ident("closure").
    let last = elems.last()?;
    let last_ident = last
        .get("Ident")
        .and_then(|v| v.as_array())
        .and_then(|a| a.first())
        .and_then(|v| v.as_str())?;
    if last_ident != "closure" {
        return None;
    }
    // Return everything BEFORE the "closure" marker.
    let prefix: Vec<Value> = elems[..elems.len() - 1].to_vec();
    Some(prefix)
}

/// Look up the closure body's fun_decl by matching the path prefix
/// (everything up to but not including `Ident("closure")`) to a
/// fun_decl whose path is the same prefix followed by an `Impl{...}`
/// element and a trailing `Ident("call"|"call_mut"|"call_once"|
/// "drop_in_place")`. Returns the body's content_cid if found.
///
/// We pick the FIRST matching fun_decl (Charon emits multiple per
/// closure — Fn/FnMut/FnOnce + drop_in_place — and they share the
/// same body shape; for substrate purposes any one's CID is the
/// closure-body identifier).
fn find_closure_body_cid(prefix: &[Value], fun_decls: Option<&Value>) -> String {
    let Some(arr) = fun_decls.and_then(|fd| fd.as_array()) else {
        return String::new();
    };
    for decl in arr {
        let Some(elems) = decl
            .get("item_meta")
            .and_then(|m| m.get("name"))
            .and_then(|n| n.as_array())
        else {
            continue;
        };
        // The fun_decl path must START with our prefix (in JSON
        // structural equality), then have an Impl{...} element, then
        // a trailing Ident with one of the call-like names.
        if elems.len() < prefix.len() + 2 {
            continue;
        }
        let prefix_match = prefix.iter().zip(elems.iter()).all(|(a, b)| a == b);
        if !prefix_match {
            continue;
        }
        let post_prefix = &elems[prefix.len()..];
        if post_prefix.first().and_then(|v| v.get("Impl")).is_none() {
            continue;
        }
        let Some(trailing_ident) = post_prefix
            .last()
            .and_then(|v| v.get("Ident"))
            .and_then(|a| a.as_array())
            .and_then(|a| a.first())
            .and_then(|v| v.as_str())
        else {
            continue;
        };
        if matches!(
            trailing_ident,
            "call" | "call_mut" | "call_once" | "drop_in_place"
        ) {
            // Hash this fun_decl's full JSON shape as the body cid.
            let canonical = serde_to_canonical(decl.clone());
            return cid_of_value(&canonical);
        }
    }
    String::new()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::llbc::LlbcCrate;

    fn fixture_path(name: &str) -> std::path::PathBuf {
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests")
            .join("fixtures")
            .join(name)
    }

    #[test]
    fn extracts_closure_capture_from_closure_capture_fixture() {
        // closure_capture.rs has `let g = |y| y + offset;` which
        // emits an Aggregate(Adt) for the synthetic closure type.
        let krate = LlbcCrate::from_path(fixture_path("closure_capture.llbc")).unwrap();
        let f = krate.function_by_name("f").unwrap();
        let type_decls = krate.type_decls_raw();
        let fun_decls = krate.raw_translated().and_then(|t| t.get("fun_decls"));
        let stmts: Vec<&Value> = f.statements().map(|s| s.raw()).collect();
        let captures = extract_closure_captures(&stmts, type_decls, fun_decls);
        assert!(
            !captures.is_empty(),
            "closure_capture fixture must have at least one closure capture site"
        );
        // body_fn_cid should resolve (closure body is in the same crate).
        for c in &captures {
            assert!(
                c.body_fn_cid.starts_with("blake3-512:"),
                "closure body cid should resolve: got {:?}",
                c.body_fn_cid
            );
        }
    }

    #[test]
    fn no_closure_captures_in_loopless_clean_fixture() {
        let krate = LlbcCrate::from_path(fixture_path("clean.llbc")).unwrap();
        let f = krate.function_by_name("f").unwrap();
        let type_decls = krate.type_decls_raw();
        let fun_decls = krate.raw_translated().and_then(|t| t.get("fun_decls"));
        let stmts: Vec<&Value> = f.statements().map(|s| s.raw()).collect();
        let captures = extract_closure_captures(&stmts, type_decls, fun_decls);
        assert!(captures.is_empty());
    }
}

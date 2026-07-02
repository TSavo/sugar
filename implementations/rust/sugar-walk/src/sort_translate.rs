// SPDX-License-Identifier: Apache-2.0
//
// sort_translate: canonical mapping from source types to Sort IR.
//
// This module is the single source of truth for the `infer_sort` logic
// that previously lived in duplicate in `contract.rs` and `type_decl.rs`.
// Both callers now delegate here, ensuring that the same Rust source type
// produces the same Sort via the AST path (syn::Type) and the LLBC path
// (Charon JSON Ty).
//
// ## Approach: rich `Sort::Primitive { name }` strings (Option A)
//
// We stay within `Sort::Primitive { name }` rather than adding new `Sort`
// enum variants. This avoids cross-kit exhaustiveness churn (the exact
// failure that motivated the fix). Each primitive carries a distinct,
// normalized name so that different Rust types produce different Sorts
// and therefore different content_cids. Composite shapes are encoded as
// structured strings ("Ref<U32>", "Slice<U32>", etc.) — readable, stable,
// and distinguishable.
//
// The long-term answer is to add proper Sort variants (Option B), but that
// requires updating every match on `Sort` across all kits. Filed as a
// follow-up to #384.
//
// ## Key properties
//
// 1. `u32` via AST and `{"Literal": {"UInt": "U32"}}` via Charon produce
//    `Sort::Primitive { name: "U32" }` byte-for-byte.
// 2. `&'a str` and `&str` produce the same Sort (lifetime annotations are
//    stripped — they don't change the type for our purposes).
// 3. `Vec<u32>` and `SomeStruct` produce distinct Sorts so struct-decl
//    CIDs and formal_sorts are distinguishable.
// 4. Unknown/opaque shapes fall to `"Unknown"` (not `"Int"`), documented
//    with a TODO for future extension.

use sugar_ir_types::Sort;

// ---- AST path ----

/// Translate a `syn::Type` into a `Sort`. Branches on the `syn::Type`
/// enum shape — does NOT do token-string matching, so lifetime
/// annotations (`&'a T`) and whitespace in the token stream cannot cause
/// false splits.
///
/// This replaces the old `infer_sort` in `contract.rs` and `type_decl.rs`,
/// which used `quote::ToTokens` + string matching and produced "Int" for
/// every type that didn't match a hardcoded string arm.
///
pub fn syn_type_to_sort(ty: &syn::Type) -> Sort {
    let name = syn_type_to_sort_name(ty);
    Sort::Primitive { name }
}

fn syn_type_to_sort_name(ty: &syn::Type) -> String {
    match ty {
        // Plain path: u32, bool, String, Vec<T>, SomeStruct, etc.
        syn::Type::Path(p) => path_sort_name(p),

        // Reference: &T or &mut T — lifetime annotations ignored.
        syn::Type::Reference(r) => {
            let inner = syn_type_to_sort_name(&r.elem);
            if r.mutability.is_some() {
                format!("RefMut<{}>", inner)
            } else {
                format!("Ref<{}>", inner)
            }
        }

        // Slice: [T]
        syn::Type::Slice(s) => {
            let inner = syn_type_to_sort_name(&s.elem);
            format!("Slice<{}>", inner)
        }

        // Array: [T; N] — treat as Slice for sort purposes (fixed-size
        // vs dynamic isn't modelled at the Sort level yet).
        syn::Type::Array(a) => {
            let inner = syn_type_to_sort_name(&a.elem);
            format!("Array<{}>", inner)
        }

        // Tuple: () is Unit; (T, U, ...) is Tuple.
        syn::Type::Tuple(t) if t.elems.is_empty() => "Unit".to_string(),
        syn::Type::Tuple(t) => {
            let inners: Vec<String> = t.elems.iter().map(syn_type_to_sort_name).collect();
            format!("Tuple<{}>", inners.join(","))
        }

        // Raw pointer: *const T / *mut T
        syn::Type::Ptr(p) => {
            let inner = syn_type_to_sort_name(&p.elem);
            if p.mutability.is_some() {
                format!("PtrMut<{}>", inner)
            } else {
                format!("Ptr<{}>", inner)
            }
        }

        // Bare function type (fn(T) -> U) — opaque for now.
        syn::Type::BareFn(_) => "FnPtr".to_string(),

        // impl Trait / dyn Trait — opaque.
        syn::Type::ImplTrait(_) | syn::Type::TraitObject(_) => "Opaque".to_string(),

        // Inferred / macro / never / verbatim.
        syn::Type::Infer(_) => "Infer".to_string(),
        syn::Type::Never(_) => "Never".to_string(),
        syn::Type::Macro(_) => "Macro".to_string(),

        // TODO(#384): Group/Paren wrappers — peel and recurse.
        syn::Type::Group(g) => syn_type_to_sort_name(&g.elem),
        syn::Type::Paren(p) => syn_type_to_sort_name(&p.elem),

        // Catch-all for future syn::Type variants.
        _ => "Unknown".to_string(),
    }
}

fn path_sort_name(p: &syn::TypePath) -> String {
    // If there's a leading self qualifier, try to use just the path.
    let segments = &p.path.segments;
    if segments.is_empty() {
        return "Unknown".to_string();
    }

    // Single-segment with no generics: check primitives first.
    if segments.len() == 1 && segments[0].arguments.is_none() {
        let ident = segments[0].ident.to_string();
        if let Some(prim) = primitive_sort_name(&ident) {
            return prim.to_string();
        }
        // Named type (struct, enum, type alias). Use the ident as the sort
        // name — distinct names produce distinct sorts.
        return ident;
    }

    // Single-segment with generics (Vec<T>, Option<T>, Result<T,E>, etc.)
    if segments.len() == 1 {
        let ident = segments[0].ident.to_string();
        if let syn::PathArguments::AngleBracketed(ab) = &segments[0].arguments {
            let inners: Vec<String> = ab
                .args
                .iter()
                .filter_map(|a| {
                    if let syn::GenericArgument::Type(t) = a {
                        Some(syn_type_to_sort_name(t))
                    } else {
                        None
                    }
                })
                .collect();
            if !inners.is_empty() {
                return format!("{}<{}>", ident, inners.join(","));
            }
        }
        return ident;
    }

    // Multi-segment path (std::vec::Vec, crate::Foo, etc.) — use last segment.
    let last = segments.last().unwrap();
    let ident = last.ident.to_string();
    if let Some(prim) = primitive_sort_name(&ident) {
        return prim.to_string();
    }
    if let syn::PathArguments::AngleBracketed(ab) = &last.arguments {
        let inners: Vec<String> = ab
            .args
            .iter()
            .filter_map(|a| {
                if let syn::GenericArgument::Type(t) = a {
                    Some(syn_type_to_sort_name(t))
                } else {
                    None
                }
            })
            .collect();
        if !inners.is_empty() {
            return format!("{}<{}>", ident, inners.join(","));
        }
    }
    ident
}

/// Map a bare Rust primitive type name to a normalized Sort name.
/// Returns None if the ident is not a primitive — callers fall back
/// to using the ident as a user-defined type sort name.
fn primitive_sort_name(ident: &str) -> Option<&'static str> {
    Some(match ident {
        // Integer types canonicalize to the spec's `Int`. Per
        // canonicalization-grammar.md §5 the canonical primitive set is a
        // fixed {Bool, Int, Real, String, Ref, ...}; width (`u32` vs `u64`) is
        // NOT a sort distinction. Width is a range refinement -- sidecar to the
        // contract -- and the SOURCE type system already owns width and
        // narrowing (a `u64 -> u32` truncation is a compile error, not our
        // job). Collapsing to `Int` is what lets a Rust `i64` contract
        // federate (share CIDs) with a Java `long` contract over the same
        // canonical `Int`, and keeps the solver in LIA.
        "u8" | "u16" | "u32" | "u64" | "u128" | "usize" | "i8" | "i16" | "i32" | "i64" | "i128"
        | "isize" => "Int",
        // Float values live in the platform-free `Real` sort. The source
        // width (`f32`/`f64`) and IEEE refinements are kit-local FOL
        // refinements, not IR sort identity.
        "f32" | "f64" => "Real",
        "bool" => "Bool",
        "char" => "Char",
        "str" => "Str",
        "String" => "String",
        _ => return None,
    })
}

// ---- Charon LLBC path ----

/// Translate a Charon JSON `Ty` value into a `Sort`. The top-level
/// shape is always `{"Untagged": <inner>}`. Returns `Sort::Primitive {
/// name: "Unknown" }` for shapes that aren't yet handled (documented
/// with TODO below).
///
/// IEEE-754 float types (`{"Literal": {"Float": "F32"}}` /
/// `{"Literal": {"Float": "F64"}}`) normalize to the platform-free `Real`
/// sort. The source width is a kit-local refinement, not IR sort identity.
///
/// To translate a `LlbcLocal`'s type, pass `local.ty_raw()`:
///
/// ```ignore
/// let sort = ty_to_sort(local.ty_raw(), type_decls);
/// ```
///
/// `type_decls` is the raw `translated.type_decls` JSON value. Pass
/// it when available so that `Adt` with a numeric `id` (user-defined
/// struct or enum) resolves to the source type name. Pass `None` when
/// only primitive types are expected (e.g. unit tests).
pub fn ty_to_sort(ty: Option<&serde_json::Value>, type_decls: Option<&serde_json::Value>) -> Sort {
    let name = ty_to_sort_name(ty, type_decls);
    Sort::Primitive { name }
}

fn ty_to_sort_name(
    ty: Option<&serde_json::Value>,
    type_decls: Option<&serde_json::Value>,
) -> String {
    let ty = match ty {
        Some(v) => v,
        None => return "Unknown".to_string(),
    };

    // Charon wraps every Ty in {"Untagged": <inner>}.
    let inner = match ty.get("Untagged") {
        Some(v) => v,
        None => return "Unknown".to_string(),
    };

    charon_inner_to_sort_name(inner, type_decls)
}

fn charon_inner_to_sort_name(
    inner: &serde_json::Value,
    type_decls: Option<&serde_json::Value>,
) -> String {
    // Literal types: {"Literal": <lit>}
    if let Some(lit) = inner.get("Literal") {
        return charon_literal_sort_name(lit);
    }

    // Reference: {"Ref": [<region>, <inner_ty>, "Shared"|"Mut"]}
    //
    // Charon emits the inner Ty already fully wrapped as {"Untagged": ...}.
    // Pass it directly to ty_to_sort_name — do NOT add another {"Untagged":}
    // layer, which would produce double-wrapping and fall through to "Unknown".
    if let Some(arr) = inner.get("Ref").and_then(|v| v.as_array()) {
        if arr.len() == 3 {
            let inner_ty = &arr[1];
            let Some(mutability) = arr[2].as_str() else {
                return "Unknown".to_string();
            };
            let inner_sort = ty_to_sort_name(Some(inner_ty), type_decls);
            return match mutability {
                "Mut" => format!("RefMut<{}>", inner_sort),
                "Shared" => format!("Ref<{}>", inner_sort),
                _ => "Unknown".to_string(),
            };
        }
    }

    // Slice: {"Slice": <elem_ty>}
    //
    // The elem Ty is also already {"Untagged": ...} wrapped in real Charon
    // output — pass directly.
    if let Some(elem) = inner.get("Slice") {
        let inner_sort = ty_to_sort_name(Some(elem), type_decls);
        return format!("Slice<{}>", inner_sort);
    }

    // Array: {"Array": [<elem_ty>, <len>]}
    if let Some(arr) = inner.get("Array").and_then(|v| v.as_array()) {
        if !arr.is_empty() {
            let inner_sort = ty_to_sort_name(Some(&arr[0]), type_decls);
            return format!("Array<{}>", inner_sort);
        }
    }

    // Raw pointer: {"RawPtr": [<inner_ty>, "Mut"|"Not"]}
    if let Some(arr) = inner.get("RawPtr").and_then(|v| v.as_array()) {
        if arr.len() >= 2 {
            let inner_ty = &arr[0];
            let Some(mutability) = arr[1].as_str() else {
                return "Unknown".to_string();
            };
            let inner_sort = ty_to_sort_name(Some(inner_ty), type_decls);
            return match mutability {
                "Mut" => format!("PtrMut<{}>", inner_sort),
                "Not" => format!("Ptr<{}>", inner_sort),
                _ => "Unknown".to_string(),
            };
        }
    }

    // Adt (struct, enum, Tuple, Array):
    // {"Adt": {"id": <id>, "generics": {...}}}
    if let Some(adt) = inner.get("Adt") {
        return charon_adt_sort_name(adt, type_decls);
    }

    // Never / Unit bare forms.
    if inner.is_string() && inner.as_str() == Some("Never") {
        return "Never".to_string();
    }

    // TypeVar / TraitRef / DynTrait etc.
    // TODO(#384): richer handling for generics and trait objects.
    "Unknown".to_string()
}

fn charon_adt_sort_name(adt: &serde_json::Value, type_decls: Option<&serde_json::Value>) -> String {
    let id = match adt.get("id") {
        Some(v) => v,
        None => return "Unknown".to_string(),
    };

    // Tuple: {"id": "Tuple", "generics": {"regions":[], "types":[...], ...}}
    if id.as_str() == Some("Tuple") {
        let types = adt
            .get("generics")
            .and_then(|g| g.get("types"))
            .and_then(|t| t.as_array());
        return match types {
            Some(ts) if ts.is_empty() => "Unit".to_string(),
            Some(ts) => {
                let inners: Vec<String> = ts
                    .iter()
                    .map(|t| ty_to_sort_name(Some(&serde_json::json!({"Untagged": t})), type_decls))
                    .collect();
                format!("Tuple<{}>", inners.join(","))
            }
            None => "Unit".to_string(),
        };
    }

    // Named Adt with numeric id. Resolve to source name via type_decls.
    // id may be a number or an {"Adt": <num>} shape.
    let adt_numeric_id: Option<u64> = if let Some(n) = id.as_u64() {
        Some(n)
    } else {
        id.get("Adt").and_then(|v| v.as_u64())
    };

    if let Some(num_id) = adt_numeric_id {
        // Try to resolve via type_decls. type_decls is a JSON array of
        // type_decl objects; each has {"def_id": {"index": N}, "item_meta": {"name": [...]}}
        // or sometimes just {"index": N} on the def_id.
        if let Some(tds) = type_decls.and_then(|v| v.as_array()) {
            for td in tds {
                // Match by def_id index.
                let td_index = td
                    .get("def_id")
                    .and_then(|d| d.get("index"))
                    .and_then(|i| i.as_u64());
                if td_index == Some(num_id) {
                    // Extract source name from item_meta.name path.
                    if let Some(name) = extract_type_decl_name(td) {
                        // Attach generic parameters if present.
                        let generics = adt
                            .get("generics")
                            .and_then(|g| g.get("types"))
                            .and_then(|t| t.as_array());
                        if let Some(types) = generics {
                            if !types.is_empty() {
                                let inners: Vec<String> = types
                                    .iter()
                                    .map(|t| {
                                        ty_to_sort_name(
                                            Some(&serde_json::json!({"Untagged": t})),
                                            type_decls,
                                        )
                                    })
                                    .collect();
                                return format!("{}<{}>", name, inners.join(","));
                            }
                        }
                        return name;
                    }
                }
            }
        }
        // Could not resolve — use the numeric id as a stable fallback.
        // Different types have different ids so content distinctness is preserved.
        // TODO(#384): log a warning when this path is taken.
        return format!("Adt:{}", num_id);
    }

    // String id that's not "Tuple" — could be "Array", "Str", "Bool" in
    // older Charon versions. Handle the known ones.
    if let Some(s) = id.as_str() {
        return s.to_string();
    }

    "Unknown".to_string()
}

fn charon_literal_sort_name(lit: &serde_json::Value) -> String {
    // Bare string: {"Literal": "Bool"} or {"Literal": "Char"} etc.
    if let Some(s) = lit.as_str() {
        return match s {
            "Bool" => "Bool".to_string(),
            "Char" => "Char".to_string(),
            "Str" => "Str".to_string(),
            _ => s.to_string(),
        };
    }

    // Object: {"Literal": {"UInt": "U32"}} or {"Literal": {"SInt": "I8"}}
    // or {"Literal": {"Float": "F32"}}. Integer widths canonicalize to `Int`
    // (see primitive_sort_name): width is a refinement, not a sort. Keeps the
    // syn and Charon paths in agreement on canonical `Int`.
    if let Some(obj) = lit.as_object() {
        if obj.get("UInt").and_then(|v| v.as_str()).is_some()
            || obj.get("SInt").and_then(|v| v.as_str()).is_some()
        {
            return "Int".to_string();
        }
        if obj.get("Float").and_then(|v| v.as_str()).is_some() {
            return "Real".to_string();
        }
    }

    "Unknown".to_string()
}

/// Extract the source name from a Charon type_decl JSON object.
/// The `item_meta.name` field is an array of path segments: each is
/// either `{"Ident": ["name", disambig]}` (source name) or `{"Impl": ...}`.
fn extract_type_decl_name(td: &serde_json::Value) -> Option<String> {
    let name_arr = td.get("item_meta")?.get("name")?.as_array()?;
    // Walk in reverse and find the first Ident segment.
    for seg in name_arr.iter().rev() {
        if let Some(ident_arr) = seg.get("Ident").and_then(|v| v.as_array()) {
            if let Some(s) = ident_arr.first().and_then(|v| v.as_str()) {
                return Some(s.to_string());
            }
        }
    }
    None
}

// ---- Region extraction from Charon Ty ----

/// Extract the region name from a Charon `Ty` value. Returns `Some(name)`
/// when the outermost Ty is a `Ref` or `RawPtr` carrying a region, and
/// `None` for all other types (primitives, Adts, slices, etc.).
///
/// The region in Charon's JSON may appear in several shapes depending
/// on the Charon version and the kind of region:
///
/// ```text
///   {"Body": N}              — body-bound region (implicit lifetime)
///   {"Bound": {"region_id": N, "var_id": M}} — generic-bound region
///   {"Var": "'a"}            — named region variable
///   {"Var": {"name": "'a"}}  — alternative named shape
///   {"Static": true}         — 'static lifetime
/// ```
///
/// Body/Bound regions are resolved to their generic name (from the
/// `generics.regions` array) by the caller via a lookup map, not here.
/// This function returns the region JSON value so the lifter can
/// produce a descriptive default like `'rN` from the region index.
///
/// Caller should pass `region_map: &HashMap<u32, String>` to resolve
/// Body/Bound ids to source names.
pub fn extract_region_name(
    ty: &serde_json::Value,
    region_map: &std::collections::HashMap<u32, String>,
) -> Option<String> {
    let inner = ty.get("Untagged")?;

    // Ref: [region, inner_ty, mutability]
    if let Some(ref_arr) = inner.get("Ref").and_then(|v| v.as_array()) {
        if let Some(region) = ref_arr.first() {
            return resolve_region_json(region, region_map);
        }
    }

    // RawPtr: [inner_ty, mutability] — RawPtr doesn't carry a region
    // in the JSON (the pointee does, but it's not at this level).

    None
}

pub fn resolve_region_json(
    region: &serde_json::Value,
    region_map: &std::collections::HashMap<u32, String>,
) -> Option<String> {
    // Static
    if region.get("Static").and_then(|v| v.as_bool()) == Some(true) {
        return Some("'static".to_string());
    }

    // Var: either a bare string "'a" or an object {"name": "'a"}
    if let Some(var_str) = region.get("Var").and_then(|v| v.as_str()) {
        return Some(var_str.to_string());
    }
    if let Some(var_obj) = region.get("Var") {
        if let Some(name) = var_obj.get("name").and_then(|v| v.as_str()) {
            return Some(name.to_string());
        }
    }

    // Bound: {"region_id": N, "var_id": M}
    if let Some(bound) = region.get("Bound") {
        let rid = bound.get("region_id").and_then(|v| v.as_u64())? as u32;
        return region_map
            .get(&rid)
            .cloned()
            .or_else(|| Some(format!("'r{}", rid)));
    }

    // Body: N (body-bound region, De Bruijn-like index)
    if let Some(body_id) = region.get("Body").and_then(|v| v.as_u64()) {
        let id = body_id as u32;
        return region_map
            .get(&id)
            .cloned()
            .or_else(|| Some(format!("'r{}", id)));
    }

    None
}

// ---- Tests ----

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn parse_ty(src: &str) -> syn::Type {
        syn::parse_str(src).unwrap()
    }

    // --- syn path: lifetime annotations must not change the sort ---

    #[test]
    fn ref_with_lifetime_and_without_produce_same_sort() {
        let with_lt = syn_type_to_sort(&parse_ty("&'a str"));
        let without_lt = syn_type_to_sort(&parse_ty("&str"));
        assert_eq!(with_lt, without_lt, "&'a str and &str must yield same Sort");
    }

    #[test]
    fn ref_mut_with_lifetime_and_without_produce_same_sort() {
        let with_lt = syn_type_to_sort(&parse_ty("&'a mut u32"));
        let without_lt = syn_type_to_sort(&parse_ty("&mut u32"));
        assert_eq!(with_lt, without_lt);
    }

    // --- syn path: distinct primitive types produce distinct sorts ---

    #[test]
    fn u32_and_bool_are_distinct() {
        let u32_sort = syn_type_to_sort(&parse_ty("u32"));
        let bool_sort = syn_type_to_sort(&parse_ty("bool"));
        assert_ne!(u32_sort, bool_sort);
    }

    #[test]
    fn integer_widths_canonicalize_to_int() {
        // Width is a refinement, not a sort: every integer width collapses to
        // the canonical `Int` (canonicalization-grammar §5). `u32`/`u64`/`i8`
        // are the SAME sort; their distinction lives in the contract's range
        // refinement, not the sort name. This is the deliberate reversal of
        // the old width-distinct "Option A".
        let int = Sort::Primitive {
            name: "Int".to_string(),
        };
        for ty in [
            "u8", "u16", "u32", "u64", "u128", "usize", "i8", "i16", "i32", "i64", "i128", "isize",
        ] {
            assert_eq!(
                syn_type_to_sort(&parse_ty(ty)),
                int,
                "`{ty}` must canonicalize to Int"
            );
        }
    }

    #[test]
    fn int_and_bool_are_distinct() {
        // Integers collapse to Int, but Int and Bool stay distinct sorts.
        let a = syn_type_to_sort(&parse_ty("i8"));
        let b = syn_type_to_sort(&parse_ty("bool"));
        assert_ne!(a, b);
    }

    // --- syn path: Vec<u32> and SomeStruct are distinct ---

    #[test]
    fn vec_u32_and_user_struct_are_distinct() {
        let vec_sort = syn_type_to_sort(&parse_ty("Vec<u32>"));
        let struct_sort = syn_type_to_sort(&parse_ty("SomeStruct"));
        assert_ne!(vec_sort, struct_sort);
    }

    // --- syn path: slice produces Slice<inner> ---

    #[test]
    fn slice_sort_wraps_inner() {
        let slice_sort = syn_type_to_sort(&parse_ty("[u32]"));
        assert_eq!(
            slice_sort,
            Sort::Primitive {
                name: "Slice<Int>".to_string()
            }
        );
    }

    #[test]
    fn ref_slice_sort() {
        let ty = syn_type_to_sort(&parse_ty("&[u32]"));
        assert_eq!(
            ty,
            Sort::Primitive {
                name: "Ref<Slice<Int>>".to_string()
            }
        );
    }

    // --- syn path: unit tuple is Unit ---

    #[test]
    fn unit_tuple_is_unit() {
        let ty = syn_type_to_sort(&parse_ty("()"));
        assert_eq!(
            ty,
            Sort::Primitive {
                name: "Unit".to_string()
            }
        );
    }

    // --- Charon path: agree with syn path on primitives ---

    #[test]
    fn charon_u32_matches_syn_u32() {
        let charon = ty_to_sort(
            Some(&json!({"Untagged": {"Literal": {"UInt": "U32"}}})),
            None,
        );
        let syn_sort = syn_type_to_sort(&parse_ty("u32"));
        assert_eq!(charon, syn_sort, "u32 via Charon and syn must agree");
    }

    #[test]
    fn charon_bool_matches_syn_bool() {
        let charon = ty_to_sort(Some(&json!({"Untagged": {"Literal": "Bool"}})), None);
        let syn_sort = syn_type_to_sort(&parse_ty("bool"));
        assert_eq!(charon, syn_sort);
    }

    #[test]
    fn charon_i32_matches_syn_i32() {
        let charon = ty_to_sort(
            Some(&json!({"Untagged": {"Literal": {"SInt": "I32"}}})),
            None,
        );
        let syn_sort = syn_type_to_sort(&parse_ty("i32"));
        assert_eq!(charon, syn_sort);
    }

    #[test]
    fn charon_usize_matches_syn_usize() {
        let charon = ty_to_sort(
            Some(&json!({"Untagged": {"Literal": {"UInt": "Usize"}}})),
            None,
        );
        let syn_sort = syn_type_to_sort(&parse_ty("usize"));
        assert_eq!(charon, syn_sort);
    }

    // --- Charon path: ref and slice ---

    #[test]
    fn charon_ref_slice_u32_matches_syn() {
        // &[u32] in real Charon output:
        // {"Untagged": {"Ref": [region, {"Untagged": {"Slice": {"Untagged": {"Literal": {"UInt":"U32"}}}}}, "Shared"]}}
        // The inner Ty elements are fully wrapped — they are passed directly
        // to ty_to_sort_name without additional {"Untagged":} wrapping.
        let charon = ty_to_sort(
            Some(&json!({"Untagged": {"Ref": [
                {"Var": {"Bound": [0, 0]}},
                {"Untagged": {"Slice": {"Untagged": {"Literal": {"UInt": "U32"}}}}},
                "Shared"
            ]}})),
            None,
        );
        let syn_sort = syn_type_to_sort(&parse_ty("&[u32]"));
        assert_eq!(charon, syn_sort);
    }

    // --- Charon path: distinct types produce distinct sorts ---

    #[test]
    fn charon_u32_and_bool_distinct() {
        let a = ty_to_sort(
            Some(&json!({"Untagged": {"Literal": {"UInt": "U32"}}})),
            None,
        );
        let b = ty_to_sort(Some(&json!({"Untagged": {"Literal": "Bool"}})), None);
        assert_ne!(a, b);
    }

    // --- Charon path: distinct Adt ids produce distinct sorts (no type_decls) ---

    #[test]
    fn charon_distinct_adt_ids_produce_distinct_sorts() {
        let a = ty_to_sort(
            Some(
                &json!({"Untagged": {"Adt": {"id": {"Adt": 1}, "generics": {"regions":[], "types":[], "const_generics":[], "trait_refs":[]}}}}),
            ),
            None,
        );
        let b = ty_to_sort(
            Some(
                &json!({"Untagged": {"Adt": {"id": {"Adt": 2}, "generics": {"regions":[], "types":[], "const_generics":[], "trait_refs":[]}}}}),
            ),
            None,
        );
        assert_ne!(a, b, "different Adt ids must produce different sorts");
    }

    // --- Charon path: unit tuple is Unit ---

    #[test]
    fn charon_unit_tuple_is_unit() {
        let ty = ty_to_sort(
            Some(
                &json!({"Untagged": {"Adt": {"id": "Tuple", "generics": {"regions":[], "types":[], "const_generics":[], "trait_refs":[]}}}}),
            ),
            None,
        );
        assert_eq!(
            ty,
            Sort::Primitive {
                name: "Unit".to_string()
            }
        );
    }

    // --- Charon path: type_decls resolution ---

    #[test]
    fn charon_adt_resolves_to_source_name_with_type_decls() {
        let type_decls = json!([{
            "def_id": {"index": 5},
            "item_meta": {
                "name": [{"Ident": ["Point", 0]}]
            }
        }]);
        let ty = ty_to_sort(
            Some(
                &json!({"Untagged": {"Adt": {"id": {"Adt": 5}, "generics": {"regions":[], "types":[], "const_generics":[], "trait_refs":[]}}}}),
            ),
            Some(&type_decls),
        );
        assert_eq!(
            ty,
            Sort::Primitive {
                name: "Point".to_string()
            }
        );
    }

    #[test]
    fn charon_two_distinct_adts_with_type_decls_are_distinct() {
        let type_decls = json!([
            {
                "def_id": {"index": 1},
                "item_meta": {"name": [{"Ident": ["Foo", 0]}]}
            },
            {
                "def_id": {"index": 2},
                "item_meta": {"name": [{"Ident": ["Bar", 0]}]}
            }
        ]);
        let foo = ty_to_sort(
            Some(
                &json!({"Untagged": {"Adt": {"id": {"Adt": 1}, "generics": {"regions":[], "types":[], "const_generics":[], "trait_refs":[]}}}}),
            ),
            Some(&type_decls),
        );
        let bar = ty_to_sort(
            Some(
                &json!({"Untagged": {"Adt": {"id": {"Adt": 2}, "generics": {"regions":[], "types":[], "const_generics":[], "trait_refs":[]}}}}),
            ),
            Some(&type_decls),
        );
        assert_ne!(foo, bar);
        assert_eq!(
            foo,
            Sort::Primitive {
                name: "Foo".to_string()
            }
        );
        assert_eq!(
            bar,
            Sort::Primitive {
                name: "Bar".to_string()
            }
        );
    }

    // ---- Float source types normalize to platform-free Real ----

    #[test]
    fn syn_f32_produces_real_sort() {
        let s = syn_type_to_sort(&parse_ty("f32"));
        assert_eq!(
            s,
            Sort::Primitive {
                name: "Real".to_string()
            },
            "f32 must yield platform-free Real"
        );
    }

    #[test]
    fn syn_f64_produces_real_sort() {
        let s = syn_type_to_sort(&parse_ty("f64"));
        assert_eq!(
            s,
            Sort::Primitive {
                name: "Real".to_string()
            },
            "f64 must yield platform-free Real"
        );
    }

    #[test]
    fn syn_f32_and_f64_share_real_sort() {
        let a = syn_type_to_sort(&parse_ty("f32"));
        let b = syn_type_to_sort(&parse_ty("f64"));
        assert_eq!(
            a, b,
            "f32/f64 width is a kit-local refinement, not an IR sort"
        );
    }

    #[test]
    fn syn_f64_and_u64_are_distinct() {
        let f = syn_type_to_sort(&parse_ty("f64"));
        let u = syn_type_to_sort(&parse_ty("u64"));
        assert_ne!(f, u, "f64 and u64 must produce distinct Sorts");
    }

    // ---- Charon LLBC float types normalize to platform-free Real ----

    #[test]
    fn charon_float_f64_produces_real_sort() {
        let s = ty_to_sort(
            Some(&json!({"Untagged": {"Literal": {"Float": "F64"}}})),
            None,
        );
        assert_eq!(
            s,
            Sort::Primitive {
                name: "Real".to_string()
            }
        );
    }

    #[test]
    fn charon_float_f32_produces_real_sort() {
        let s = ty_to_sort(
            Some(&json!({"Untagged": {"Literal": {"Float": "F32"}}})),
            None,
        );
        assert_eq!(
            s,
            Sort::Primitive {
                name: "Real".to_string()
            }
        );
    }

    #[test]
    fn charon_float_f64_matches_syn_f64() {
        // Agreement test: f64 via Charon and syn must produce identical Sorts.
        let charon = ty_to_sort(
            Some(&json!({"Untagged": {"Literal": {"Float": "F64"}}})),
            None,
        );
        let syn_sort = syn_type_to_sort(&parse_ty("f64"));
        assert_eq!(charon, syn_sort, "f64 via Charon and syn must agree");
    }

    #[test]
    fn charon_float_f32_matches_syn_f32() {
        let charon = ty_to_sort(
            Some(&json!({"Untagged": {"Literal": {"Float": "F32"}}})),
            None,
        );
        let syn_sort = syn_type_to_sort(&parse_ty("f32"));
        assert_eq!(charon, syn_sort, "f32 via Charon and syn must agree");
    }

    #[test]
    fn charon_float_f64_is_not_width_primitive() {
        // Width is a kit-local refinement. The platform-free IR sort is Real,
        // not a Rust/Charon width tag such as F64.
        let s = ty_to_sort(
            Some(&json!({"Untagged": {"Literal": {"Float": "F64"}}})),
            None,
        );
        assert_ne!(
            s,
            Sort::Primitive {
                name: "F64".to_string()
            },
            "Charon F64 width tag must not enter IR sort identity"
        );
    }
}

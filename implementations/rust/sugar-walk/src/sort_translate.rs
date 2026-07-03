// SPDX-License-Identifier: Apache-2.0
//
// sort_translate: canonical mapping from source types to Sort IR.
//
// This module is the single source of truth for the `infer_sort` logic
// that previously lived in duplicate in `contract.rs` and `type_decl.rs`.
// Both callers now delegate here, ensuring that the same Rust source type
// produces the same Sort via the syn AST path.
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
// 1. `&'a str` and `&str` produce the same Sort (lifetime annotations are
//    stripped — they don't change the type for our purposes).
// 2. `Vec<u32>` and `SomeStruct` produce distinct Sorts so struct-decl
//    CIDs and formal_sorts are distinguishable.
// 3. Unknown/opaque shapes fall to `"Unknown"` (not `"Int"`), documented
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

// ---- Tests ----

#[cfg(test)]
mod tests {
    use super::*;

    fn parse_ty(src: &str) -> syn::Type {
        syn::parse_str(src).unwrap()
    }

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

    #[test]
    fn integer_widths_canonicalize_to_int() {
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
        let a = syn_type_to_sort(&parse_ty("i8"));
        let b = syn_type_to_sort(&parse_ty("bool"));
        assert_ne!(a, b);
    }

    #[test]
    fn vec_u32_and_user_struct_are_distinct() {
        let vec_sort = syn_type_to_sort(&parse_ty("Vec<u32>"));
        let struct_sort = syn_type_to_sort(&parse_ty("SomeStruct"));
        assert_ne!(vec_sort, struct_sort);
    }

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

    #[test]
    fn floats_produce_platform_free_real_sort() {
        let f32_sort = syn_type_to_sort(&parse_ty("f32"));
        let f64_sort = syn_type_to_sort(&parse_ty("f64"));
        let real = Sort::Primitive {
            name: "Real".to_string(),
        };
        assert_eq!(f32_sort, real);
        assert_eq!(f64_sort, real);
        assert_eq!(f32_sort, f64_sort);
    }

    #[test]
    fn real_and_int_are_distinct() {
        let f = syn_type_to_sort(&parse_ty("f64"));
        let u = syn_type_to_sort(&parse_ty("u64"));
        assert_ne!(f, u, "f64 and u64 must produce distinct Sorts");
    }
}

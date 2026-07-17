// SPDX-License-Identifier: MIT OR Apache-2.0
//
// sugar-lift-contracts
//
// Walks the syn AST of a Rust source file looking for functions with
// `#[contracts::requires(...)]` and `#[contracts::ensures(...)]`
// attributes (the `contracts` crate). Translates each predicate to
// canonical IR and emits one ContractDecl per function.
//
// Recognized attribute paths:
//   #[requires(<expr>)]
//   #[ensures(<expr>)]
//   #[invariant(<expr>)]
//   #[contracts::requires(<expr>)]
//   #[contracts::ensures(<expr>)]
//   #[contracts::invariant(<expr>)]
//
// LIFTABLE PREDICATE SHAPE: same v0 whitelist as proptest:
//   <var|lit|single-arg-call> <binop> <var|lit|single-arg-call>
// where binop is one of >, >=, <, <=, ==, !=.
//
// The function's parameters define the universally-quantified
// variables. `ret` (when used in #[ensures]) maps to the contract's
// outBinding (default "out").
//
// NAMING ROUND-TRIP
// -----------------
// If the caller passes the raw source text via `lift_file_with_source`,
// the lifter also scans lines immediately preceding each function for
// a `// concept: <name>` annotation (or the `/// concept: <name>` doc
// comment form) and attaches it to `ContractDecl::concept_hint`.
//
// Canonical annotation format (emitted by the substrate rewriter):
//   // concept: retry-with-jitter
// Doc-comment form (also accepted, idiomatic when users want IDE hover):
//   /// concept: retry-with-jitter
//
// Placeholder names (`UNNAMED-CONCEPT-N`) are stored as-is; the
// downstream binding step distinguishes them from human names.
//
// `concept_hint` is METADATA ONLY — it does NOT participate in
// `canonical_bytes` / CID derivation.  Changing or removing the
// annotation never rewrites the shape identity.

use std::collections::BTreeMap;
use std::rc::Rc;
use std::sync::Arc;

use sugar_canonicalizer::{blake3_512_of, encode_jcs, json_to_value, Value as CValue};
use sugar_ir_symbolic::parse_expr::parse_expr;
use sugar_ir_symbolic::{
    and_, atomic_, eq, gt, gte, lt, lte, make_var, ne, num, or_, serialize::formula_to_value,
    str_const, ContractDecl, Formula, Int, Sort, Term,
};
use sugar_ir_types::{
    EvidenceMemento, IrFormula, SourceKind, SourceLocator, SourceLocatorPoint, SourceLocatorSpan,
};
use syn::spanned::Spanned;

/// The auto-promote sentinel lifter CID (128 hex zeros after the prefix).
/// Used until PR-F wires the real lifter CID (compound spec §4.4).
pub const AUTO_PROMOTE_LIFTER_CID: &str = concat!(
    "blake3-512:",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000000",
);

#[derive(Debug, Clone)]
pub struct LiftWarning {
    pub source_path: String,
    pub item_name: String,
    pub reason: String,
}

#[derive(Debug, Default)]
pub struct AdapterOutput {
    pub decls: Vec<ContractDecl>,
    /// One `EvidenceMemento` per lifted type-signature site.
    /// Populated only when `lift_file_with_sig_evidence` is called; empty
    /// when using the basic `lift_file` / `lift_file_with_source` API.
    pub evidences: Vec<EvidenceMemento>,
    pub warnings: Vec<LiftWarning>,
    pub seen: usize,
    pub lifted: usize,
}

/// Lift all contract attributes found in `file`.
///
/// Equivalent to `lift_file_with_source(file, source_path, None)`.
pub fn lift_file(file: &syn::File, source_path: &str) -> AdapterOutput {
    lift_file_with_source(file, source_path, None)
}

/// Lift all contract attributes found in `file`, optionally scanning
/// `source_text` for `// concept: <name>` annotations that precede each
/// function.  When `source_text` is `None`, `concept_hint` is always `None`.
pub fn lift_file_with_source(
    file: &syn::File,
    source_path: &str,
    source_text: Option<&str>,
) -> AdapterOutput {
    let source_lines: Option<Vec<&str>> = source_text.map(|s| s.lines().collect());
    let mut out = AdapterOutput::default();
    walk_items(&file.items, source_path, source_lines.as_deref(), &mut out);
    out
}

/// Walk every function in `file` and emit one `EvidenceMemento` per
/// type-derived contract site (return type, receiver, typed parameters).
///
/// Unlike `lift_file` / `lift_file_with_source`, this function does NOT
/// require contract annotations — it visits ALL functions. The caller
/// supplies the raw source bytes so the evidence's `source_locator.source_cid`
/// can be BLAKE3-512(source_bytes) per spec §1.1.
///
/// The returned `AdapterOutput.decls` is always empty: this path emits
/// evidences only, not ContractDecls.  Callers that want both should call
/// `lift_file_with_source` and `lift_file_with_sig_evidence` separately
/// and merge the outputs.
pub fn lift_file_with_sig_evidence(
    file: &syn::File,
    source_path: &str,
    source_bytes: &[u8],
) -> AdapterOutput {
    let source_cid = blake3_512_of(source_bytes);
    let mut out = AdapterOutput::default();
    walk_items_for_sig(&file.items, source_path, &source_cid, &mut out);
    out
}

fn walk_items_for_sig(
    items: &[syn::Item],
    source_path: &str,
    source_cid: &str,
    out: &mut AdapterOutput,
) {
    for item in items {
        match item {
            syn::Item::Fn(f) => visit_fn_sig(f, source_path, source_cid, out),
            syn::Item::Mod(m) => {
                if let Some((_, items)) = &m.content {
                    walk_items_for_sig(items, source_path, source_cid, out);
                }
            }
            syn::Item::Impl(i) => {
                for it in &i.items {
                    if let syn::ImplItem::Fn(f) = it {
                        visit_impl_fn_sig(f, source_path, source_cid, out);
                    }
                }
            }
            syn::Item::Const(_)
            | syn::Item::Enum(_)
            | syn::Item::ExternCrate(_)
            | syn::Item::ForeignMod(_)
            | syn::Item::Macro(_)
            | syn::Item::Static(_)
            | syn::Item::Struct(_)
            | syn::Item::Trait(_)
            | syn::Item::TraitAlias(_)
            | syn::Item::Type(_)
            | syn::Item::Union(_)
            | syn::Item::Use(_)
            | syn::Item::Verbatim(_) => {}
            _ => panic!("sugar-lift-contracts sig walker refused unknown syn::Item variant"),
        }
    }
}

fn visit_fn_sig(f: &syn::ItemFn, source_path: &str, source_cid: &str, out: &mut AdapterOutput) {
    emit_sig_evidences(&f.sig, source_path, source_cid, out);
}

fn visit_impl_fn_sig(
    f: &syn::ImplItemFn,
    source_path: &str,
    source_cid: &str,
    out: &mut AdapterOutput,
) {
    emit_sig_evidences(&f.sig, source_path, source_cid, out);
}

// ---------------------------------------------------------------------------
// Type-signature evidence emission
// ---------------------------------------------------------------------------

/// Emit zero or more `EvidenceMemento`s for a function signature:
///   - one per typed parameter with a derivable domain constraint
///   - one for the return type (unless trivially opaque / bare generic)
fn emit_sig_evidences(
    sig: &syn::Signature,
    source_path: &str,
    source_cid: &str,
    out: &mut AdapterOutput,
) {
    let fn_name = sig.ident.to_string();
    let fn_span = sig.ident.span();
    let fn_span_start = fn_span.start();
    let fn_span_end = fn_span.end();

    // The written return type string — required in every type-signature evidence
    // per spec §10: `{ "return_type": <type_string> }`.
    let fn_return_type_str = return_type_to_string(&sig.output);

    // Build the signature-span locator (covers the function name token).
    // col is 0-indexed per spec §1.1 — proc_macro2 Span::start().column is
    // already 0-indexed, so no +1.
    let sig_locator = SourceLocator {
        source_cid: source_cid.to_string(),
        span: SourceLocatorSpan {
            start: SourceLocatorPoint {
                line: fn_span_start.line as u32,
                col: fn_span_start.column as u32,
            },
            end: SourceLocatorPoint {
                line: fn_span_end.line as u32,
                col: fn_span_end.column as u32,
            },
        },
    };

    // --- Parameters ---
    for (param_idx, arg) in sig.inputs.iter().enumerate() {
        match arg {
            syn::FnArg::Receiver(recv) => {
                // &self or &mut self
                let type_shape = if recv.mutability.is_some() {
                    "receiver-exclusive"
                } else if recv.reference.is_some() {
                    "receiver-shared"
                } else {
                    "receiver-owned"
                };
                let position = format!("param:{param_idx}");
                let mut ext = BTreeMap::new();
                ext.insert(
                    "function_symbol".to_string(),
                    serde_json::Value::String(format!("{}@{}", fn_name, source_path)),
                );
                // Required per spec §10: return_type is the function's written
                // return type string for every type-signature evidence.
                ext.insert(
                    "return_type".to_string(),
                    serde_json::Value::String(fn_return_type_str.clone()),
                );
                ext.insert(
                    "signature_position".to_string(),
                    serde_json::Value::String(position),
                );
                ext.insert(
                    "type_shape".to_string(),
                    serde_json::Value::String(type_shape.to_string()),
                );
                // Predicate: atomic true — the ownership mode IS the contract.
                let formula = atomic_("true", vec![]);
                let ir_formula = formula_to_ir_formula(&formula);
                let cid = evidence_memento_cid(
                    10000,
                    &ext,
                    AUTO_PROMOTE_LIFTER_CID,
                    &ir_formula,
                    &SourceKind::TypeSignature,
                    &sig_locator,
                );
                out.evidences.push(EvidenceMemento {
                    cid,
                    confidence_basis_points: 10000,
                    extension_fields: ext,
                    kind: "evidence".to_string(),
                    lifter_cid: AUTO_PROMOTE_LIFTER_CID.to_string(),
                    predicate: ir_formula,
                    schema_version: "1".to_string(),
                    source_kind: SourceKind::TypeSignature,
                    source_locator: sig_locator.clone(),
                });
            }
            syn::FnArg::Typed(pt) => {
                let param_name = match &*pt.pat {
                    syn::Pat::Ident(pi) => pi.ident.to_string(),
                    _ => continue, // destructured pattern — skip
                };
                let (formula, type_shape, extra_fields) =
                    match classify_param_type(&*pt.ty, &param_name) {
                        Some(r) => r,
                        None => continue, // bare generic or opaque type — skip
                    };
                let position = format!("param:{param_idx}");
                let mut ext = BTreeMap::new();
                ext.insert(
                    "function_symbol".to_string(),
                    serde_json::Value::String(format!("{}@{}", fn_name, source_path)),
                );
                // Required per spec §10: return_type is the function's written
                // return type string for every type-signature evidence.
                ext.insert(
                    "return_type".to_string(),
                    serde_json::Value::String(fn_return_type_str.clone()),
                );
                ext.insert(
                    "signature_position".to_string(),
                    serde_json::Value::String(position),
                );
                ext.insert(
                    "type_shape".to_string(),
                    serde_json::Value::String(type_shape),
                );
                for (k, v) in extra_fields {
                    ext.insert(k, v);
                }
                let ir_formula = formula_to_ir_formula(&formula);
                let cid = evidence_memento_cid(
                    10000,
                    &ext,
                    AUTO_PROMOTE_LIFTER_CID,
                    &ir_formula,
                    &SourceKind::TypeSignature,
                    &sig_locator,
                );
                out.evidences.push(EvidenceMemento {
                    cid,
                    confidence_basis_points: 10000,
                    extension_fields: ext,
                    kind: "evidence".to_string(),
                    lifter_cid: AUTO_PROMOTE_LIFTER_CID.to_string(),
                    predicate: ir_formula,
                    schema_version: "1".to_string(),
                    source_kind: SourceKind::TypeSignature,
                    source_locator: sig_locator.clone(),
                });
            }
        }
    }

    // --- Return type ---
    if let Some((formula, type_shape, extra_fields)) = classify_return_type(&sig.output) {
        let mut ext = BTreeMap::new();
        ext.insert(
            "function_symbol".to_string(),
            serde_json::Value::String(format!("{}@{}", fn_name, source_path)),
        );
        // Required per spec §10: return_type is the function's written
        // return type string for every type-signature evidence.
        ext.insert(
            "return_type".to_string(),
            serde_json::Value::String(fn_return_type_str.clone()),
        );
        ext.insert(
            "signature_position".to_string(),
            serde_json::Value::String("return".to_string()),
        );
        ext.insert(
            "type_shape".to_string(),
            serde_json::Value::String(type_shape),
        );
        for (k, v) in extra_fields {
            ext.insert(k, v);
        }
        let ir_formula = formula_to_ir_formula(&formula);
        let cid = evidence_memento_cid(
            10000,
            &ext,
            AUTO_PROMOTE_LIFTER_CID,
            &ir_formula,
            &SourceKind::TypeSignature,
            &sig_locator,
        );
        out.evidences.push(EvidenceMemento {
            cid,
            confidence_basis_points: 10000,
            extension_fields: ext,
            kind: "evidence".to_string(),
            lifter_cid: AUTO_PROMOTE_LIFTER_CID.to_string(),
            predicate: ir_formula,
            schema_version: "1".to_string(),
            source_kind: SourceKind::TypeSignature,
            source_locator: sig_locator,
        });
    }
}

/// Classify a return type into a (predicate, type_shape, extra_fields) triple.
/// Returns `None` for opaque / bare-generic types where no contract is derivable.
fn classify_return_type(
    output: &syn::ReturnType,
) -> Option<(Rc<Formula>, String, Vec<(String, serde_json::Value)>)> {
    match output {
        syn::ReturnType::Default => {
            // `fn foo()` — implicit `()` return.
            Some((atomic_("true", vec![]), "unit".to_string(), vec![]))
        }
        syn::ReturnType::Type(_, ty) => classify_type(ty),
    }
}

/// Classify a parameter type into a (predicate, type_shape, extra_fields) triple.
/// Returns `None` for bare-generic / opaque types.
///
/// `param_name` is used to build the predicate variable (e.g. `ne(x, 0)` for NonZero types).
fn classify_param_type(
    ty: &syn::Type,
    param_name: &str,
) -> Option<(Rc<Formula>, String, Vec<(String, serde_json::Value)>)> {
    let type_str = type_to_string(ty);
    // Receiver / reference types as params.
    if let syn::Type::Reference(r) = ty {
        let inner_str = type_to_string(&r.elem);
        let type_shape = if r.mutability.is_some() {
            "borrow-mut"
        } else {
            "borrow"
        };
        let lifetime = r
            .lifetime
            .as_ref()
            .map(|lt| lt.ident.to_string())
            .unwrap_or_else(|| "_".to_string());
        return Some((
            atomic_("true", vec![]),
            type_shape.to_string(),
            vec![
                (
                    "inner_type".to_string(),
                    serde_json::Value::String(inner_str),
                ),
                ("lifetime".to_string(), serde_json::Value::String(lifetime)),
            ],
        ));
    }
    // Concrete named types.
    let base = strip_path_prefix(&type_str);
    // NonZero family: emit `ne(param, 0)`.
    if is_non_zero_type(base) {
        return Some((
            ne(make_var(param_name), num(0)),
            "non-zero".to_string(),
            vec![(
                "inner_type".to_string(),
                serde_json::Value::String(base.to_string()),
            )],
        ));
    }
    // Bounded primitives: emit `atomic_("true", [])` tagged with the type.
    if is_bounded_primitive(base) {
        return Some((
            atomic_("true", vec![]),
            "bounded-primitive".to_string(),
            vec![(
                "inner_type".to_string(),
                serde_json::Value::String(base.to_string()),
            )],
        ));
    }
    // Bare single-segment type param (like `T`, `V`, `Item`) — no contract derivable.
    if is_bare_generic(base) {
        return None;
    }
    // Other named types: skip — conservative.
    None
}

/// Classify a `syn::Type` into a (predicate, type_shape, extra_fields) triple.
/// Used for return-type classification.
fn classify_type(
    ty: &syn::Type,
) -> Option<(Rc<Formula>, String, Vec<(String, serde_json::Value)>)> {
    match ty {
        syn::Type::Tuple(t) if t.elems.is_empty() => {
            // Explicit `()` return.
            Some((atomic_("true", vec![]), "unit".to_string(), vec![]))
        }
        syn::Type::Reference(r) => {
            let inner_str = type_to_string(&r.elem);
            let type_shape = if r.mutability.is_some() {
                "borrow-mut"
            } else {
                "borrow"
            };
            let lifetime = r
                .lifetime
                .as_ref()
                .map(|lt| lt.ident.to_string())
                .unwrap_or_else(|| "_".to_string());
            Some((
                atomic_("true", vec![]),
                type_shape.to_string(),
                vec![
                    (
                        "inner_type".to_string(),
                        serde_json::Value::String(inner_str),
                    ),
                    ("lifetime".to_string(), serde_json::Value::String(lifetime)),
                ],
            ))
        }
        syn::Type::Path(tp) => {
            // Extract the outermost type name and optional single generic arg.
            let last = tp.path.segments.last()?;
            let name = last.ident.to_string();
            let inner_arg: Option<String> = match &last.arguments {
                syn::PathArguments::AngleBracketed(ab) => ab.args.iter().find_map(|a| match a {
                    syn::GenericArgument::Type(t) => Some(type_to_string(t)),
                    syn::GenericArgument::Lifetime(_)
                    | syn::GenericArgument::Const(_)
                    | syn::GenericArgument::AssocType(_)
                    | syn::GenericArgument::AssocConst(_)
                    | syn::GenericArgument::Constraint(_) => None,
                    _ => panic!(
                        "sugar-lift-contracts classify_type refused unknown syn::GenericArgument variant"
                    ),
                }),
                syn::PathArguments::None | syn::PathArguments::Parenthesized(_) => None,
            };
            // Two-arg generic for Result.
            let (ok_type, err_type): (Option<String>, Option<String>) = match &last.arguments {
                syn::PathArguments::AngleBracketed(ab) => {
                    let types: Vec<String> = ab
                        .args
                        .iter()
                        .filter_map(|a| match a {
                            syn::GenericArgument::Type(t) => Some(type_to_string(t)),
                            syn::GenericArgument::Lifetime(_)
                            | syn::GenericArgument::Const(_)
                            | syn::GenericArgument::AssocType(_)
                            | syn::GenericArgument::AssocConst(_)
                            | syn::GenericArgument::Constraint(_) => None,
                            _ => panic!(
                                "sugar-lift-contracts classify_type refused unknown syn::GenericArgument variant"
                            ),
                        })
                        .collect();
                    (types.get(0).cloned(), types.get(1).cloned())
                }
                _ => (None, None),
            };

            match name.as_str() {
                "Option" => {
                    let mut extra = vec![];
                    if let Some(inner) = &inner_arg {
                        // Skip bare generics as inner type (no useful claim).
                        if !is_bare_generic(inner.as_str()) {
                            extra.push((
                                "inner_type".to_string(),
                                serde_json::Value::String(inner.clone()),
                            ));
                        }
                    }
                    // Spec §1.1.1: predicate = result.is_some() ∨ result.is_none()
                    let predicate = or_(vec![
                        atomic_("is_some", vec![make_var("result")]),
                        atomic_("is_none", vec![make_var("result")]),
                    ]);
                    Some((predicate, "option".to_string(), extra))
                }
                "Result" => {
                    let mut extra = vec![];
                    if let Some(ok) = &ok_type {
                        if !is_bare_generic(ok.as_str()) {
                            extra.push((
                                "ok_type".to_string(),
                                serde_json::Value::String(ok.clone()),
                            ));
                        }
                    }
                    if let Some(err) = &err_type {
                        if !is_bare_generic(err.as_str()) {
                            extra.push((
                                "err_type".to_string(),
                                serde_json::Value::String(err.clone()),
                            ));
                        }
                    }
                    // Spec §1.1.1: predicate = result.is_ok() ∨ result.is_err()
                    let predicate = or_(vec![
                        atomic_("is_ok", vec![make_var("result")]),
                        atomic_("is_err", vec![make_var("result")]),
                    ]);
                    Some((predicate, "result".to_string(), extra))
                }
                "Vec" => {
                    let mut extra = vec![];
                    if let Some(elem) = &inner_arg {
                        if !is_bare_generic(elem.as_str()) {
                            extra.push((
                                "element_type".to_string(),
                                serde_json::Value::String(elem.clone()),
                            ));
                        }
                    }
                    // Spec §1.1.1: predicate = is_finite_list(result)
                    let predicate = atomic_("is_finite_list", vec![make_var("result")]);
                    Some((predicate, "vec".to_string(), extra))
                }
                _ => {
                    // Bare generic single-char names (T, V, E, etc.): skip.
                    if is_bare_generic(&name) {
                        return None;
                    }
                    // Bounded primitive return.
                    if is_bounded_primitive(&name) {
                        return Some((
                            atomic_("true", vec![]),
                            "bounded-primitive".to_string(),
                            vec![("inner_type".to_string(), serde_json::Value::String(name))],
                        ));
                    }
                    // Everything else: skip (conservative).
                    None
                }
            }
        }
        syn::Type::Array(_)
        | syn::Type::BareFn(_)
        | syn::Type::Group(_)
        | syn::Type::ImplTrait(_)
        | syn::Type::Infer(_)
        | syn::Type::Macro(_)
        | syn::Type::Never(_)
        | syn::Type::Paren(_)
        | syn::Type::Ptr(_)
        | syn::Type::Slice(_)
        | syn::Type::TraitObject(_)
        | syn::Type::Tuple(_)
        | syn::Type::Verbatim(_) => None,
        _ => panic!("sugar-lift-contracts classify_type refused unknown syn::Type variant"),
    }
}

/// Returns true for primitive Rust integer/float/bool types that carry
/// a bounded domain.
fn is_bounded_primitive(name: &str) -> bool {
    matches!(
        name,
        "i8" | "i16"
            | "i32"
            | "i64"
            | "i128"
            | "isize"
            | "u8"
            | "u16"
            | "u32"
            | "u64"
            | "u128"
            | "usize"
            | "f32"
            | "f64"
            | "bool"
            | "char"
    )
}

/// Returns true for NonZero* family types.
fn is_non_zero_type(name: &str) -> bool {
    matches!(
        name,
        "NonZeroU8"
            | "NonZeroU16"
            | "NonZeroU32"
            | "NonZeroU64"
            | "NonZeroU128"
            | "NonZeroUsize"
            | "NonZeroI8"
            | "NonZeroI16"
            | "NonZeroI32"
            | "NonZeroI64"
            | "NonZeroI128"
            | "NonZeroIsize"
    )
}

/// Returns true for a bare single-uppercase-char or short generic name
/// (e.g. `T`, `V`, `E`, `K`, `F`, `Fut`, `Item`) where no domain
/// constraint is derivable without bounds.
fn is_bare_generic(name: &str) -> bool {
    if name.is_empty() {
        return true;
    }
    // Single uppercase letter (T, V, E, etc.).
    if name.len() == 1 {
        return matches!(name.chars().next(), Some(c) if c.is_uppercase());
    }
    // Short common generic names used idiomatically.
    matches!(
        name,
        "Fut" | "Item" | "Output" | "Err" | "Ok" | "Key" | "Value" | "Iter"
    )
}

/// Strip a leading `std::num::` / `core::num::` path prefix, returning
/// just the leaf name. Returns the original if no prefix is present.
fn strip_path_prefix(s: &str) -> &str {
    if let Some(leaf) = s.rfind("::") {
        &s[leaf + 2..]
    } else {
        s
    }
}

/// Render a `syn::ReturnType` to the written type string for `return_type`
/// extension field per spec §10.  `fn foo()` → `"()"`;
/// `fn foo() -> Option<i32>` → `"Option<i32>"`.
fn return_type_to_string(output: &syn::ReturnType) -> String {
    match output {
        syn::ReturnType::Default => "()".to_string(),
        syn::ReturnType::Type(_, ty) => type_to_string(ty),
    }
}

/// Render a `syn::Type` to a stable string for use in `extension_fields`.
fn type_to_string(ty: &syn::Type) -> String {
    use quote::ToTokens;
    let mut ts = proc_macro2::TokenStream::new();
    ty.to_tokens(&mut ts);
    ts.to_string()
        .replace(" :: ", "::")
        .replace(" <", "<")
        .replace("< ", "<")
        .replace(" >", ">")
        .replace(" ,", ",")
}

// ---------------------------------------------------------------------------
// Docstring evidence lifter (PR-E of #716)
// ---------------------------------------------------------------------------

/// Confidence bands for docstring-pattern evidence.
/// All values in basis points (1/100 of a percent; 10000 = 100%).
const CONF_REQUIRES: u16 = 8000;
const CONF_PANICS_IF: u16 = 8000;
const CONF_RETURNS_IF: u16 = 7500;
const CONF_ARGUMENTS_MUST_BE: u16 = 8500;

/// Walk every function in `file` and emit one `EvidenceMemento` per
/// docstring pattern site (returns-if, requires, panics-if, arguments
/// must-be constraints).
///
/// Unlike `lift_file` / `lift_file_with_source`, this function does NOT
/// require contract annotations — it visits ALL functions with doc comments.
/// The caller supplies the raw source bytes so the evidence's
/// `source_locator.source_cid` can be BLAKE3-512(source_bytes) per spec §1.1.
///
/// The returned `AdapterOutput.decls` is always empty: this path emits
/// evidences only, not ContractDecls.  Callers that want both should call
/// `lift_file_with_source` and `lift_file_with_docstring_evidence` separately
/// and merge the outputs.
///
/// Conservative semantics (Supra omnia, rectum): patterns that do not match
/// unambiguously emit nothing.  Minimum confidence is 7500; there is no
/// sub-7500 band for ambiguous prose.
pub fn lift_file_with_docstring_evidence(
    file: &syn::File,
    source_path: &str,
    source_bytes: &[u8],
) -> AdapterOutput {
    let source_cid = blake3_512_of(source_bytes);
    let mut out = AdapterOutput::default();
    walk_items_for_doc(&file.items, source_path, &source_cid, &mut out);
    out
}

fn walk_items_for_doc(
    items: &[syn::Item],
    source_path: &str,
    source_cid: &str,
    out: &mut AdapterOutput,
) {
    for item in items {
        match item {
            syn::Item::Fn(f) => {
                let fn_name = f.sig.ident.to_string();
                emit_doc_evidences(&fn_name, &f.attrs, source_path, source_cid, out);
            }
            syn::Item::Mod(m) => {
                if let Some((_, items)) = &m.content {
                    walk_items_for_doc(items, source_path, source_cid, out);
                }
            }
            syn::Item::Impl(i) => {
                for it in &i.items {
                    if let syn::ImplItem::Fn(f) = it {
                        let fn_name = f.sig.ident.to_string();
                        emit_doc_evidences(&fn_name, &f.attrs, source_path, source_cid, out);
                    }
                }
            }
            syn::Item::Const(_)
            | syn::Item::Enum(_)
            | syn::Item::ExternCrate(_)
            | syn::Item::ForeignMod(_)
            | syn::Item::Macro(_)
            | syn::Item::Static(_)
            | syn::Item::Struct(_)
            | syn::Item::Trait(_)
            | syn::Item::TraitAlias(_)
            | syn::Item::Type(_)
            | syn::Item::Union(_)
            | syn::Item::Use(_)
            | syn::Item::Verbatim(_) => {}
            _ => panic!("sugar-lift-contracts doc walker refused unknown syn::Item variant"),
        }
    }
}

/// Collected doc attributes for a function.
struct DocAttr {
    /// The trimmed text from `#[doc = " ..."]` (leading space stripped).
    text: String,
    /// Line/col span of the attribute for `source_locator`.
    span_start_line: u32,
    span_start_col: u32,
    span_end_line: u32,
    span_end_col: u32,
}

/// Recognized docstring pattern kinds.
#[derive(Debug, Clone, PartialEq, Eq)]
enum DocPattern {
    /// "Returns None if <tail>"
    ReturnsNoneIf { tail: String, confidence: u16 },
    /// "Returns Some(...) if <tail>" / "Returns <non-None> if <tail>"
    ReturnsSomeIf { tail: String, confidence: u16 },
    /// "Requires <tail>"
    Requires { tail: String, confidence: u16 },
    /// "Panics if <tail>"
    PanicsIf { tail: String, confidence: u16 },
    /// `# Arguments` / `# Parameters` section bullet: "- `<var>`: must be <tail>"
    ArgumentsMustBe {
        var_name: String,
        tail: String,
        confidence: u16,
    },
}

/// Extract doc attribute text from syn attributes.
/// Returns a vec of (text, span) for all `#[doc = "..."]` attrs in order.
fn collect_doc_attrs(attrs: &[syn::Attribute]) -> Vec<DocAttr> {
    let mut result = Vec::new();
    for attr in attrs {
        if !attr.path().is_ident("doc") {
            continue;
        }
        if let syn::Meta::NameValue(nv) = &attr.meta {
            if let syn::Expr::Lit(el) = &nv.value {
                if let syn::Lit::Str(ls) = &el.lit {
                    let raw = ls.value();
                    // `///` lines come as " text" with a leading space; strip it.
                    let text = match raw.strip_prefix(' ') {
                        Some(stripped) => stripped,
                        None => raw.as_str(),
                    }
                    .to_string();
                    let sp = attr.span();
                    let s = sp.start();
                    let e = sp.end();
                    result.push(DocAttr {
                        text,
                        span_start_line: s.line as u32,
                        span_start_col: s.column as u32,
                        span_end_line: e.line as u32,
                        span_end_col: e.column as u32,
                    });
                }
            }
        }
    }
    result
}

/// Try to match a single doc line (or sequence of lines for # Arguments section)
/// against the 4 recognized patterns. Returns a list of matched patterns.
///
/// This function processes a SLICE of doc attrs: it handles both single-line
/// patterns and the multi-line `# Arguments` section.
fn match_doc_patterns(doc_attrs: &[DocAttr]) -> Vec<(DocPattern, usize)> {
    let mut matched = Vec::new();
    let mut in_arguments_section = false;

    for (idx, da) in doc_attrs.iter().enumerate() {
        let line = da.text.trim();

        // Section header detection (case-insensitive).
        if line.eq_ignore_ascii_case("# arguments") || line.eq_ignore_ascii_case("# parameters") {
            in_arguments_section = true;
            continue;
        }
        // Any other `#` section heading exits the arguments section.
        if line.starts_with('#') {
            in_arguments_section = false;
            continue;
        }
        // Blank lines within the arguments section are fine (common in rustdoc);
        // only exit the section when we see a non-blank, non-bullet line.
        if line.is_empty() {
            continue;
        }

        if in_arguments_section {
            // Parse `- \`var_name\`: must be <tail>` (bullet list item).
            if let Some(p) = try_parse_arguments_bullet(line) {
                matched.push((p, idx));
            }
            continue;
        }

        // Pattern 1: "Returns None if <tail>"  (case-insensitive anchor)
        if let Some(tail) = try_strip_prefix_ci(line, "returns none if ") {
            let tail = tail.trim_end_matches('.').trim().to_string();
            if !tail.is_empty() {
                matched.push((
                    DocPattern::ReturnsNoneIf {
                        tail,
                        confidence: CONF_RETURNS_IF,
                    },
                    idx,
                ));
            }
            continue;
        }

        // Pattern 2: "Returns Some(...) if <tail>" or "Returns <X> if <tail>"
        // where X is not "None" (captures the positive-result branch).
        if let Some(rest) = try_strip_prefix_ci(line, "returns ") {
            // Find " if " separator (case-insensitive).
            if let Some(if_pos) = rest.to_ascii_lowercase().find(" if ") {
                let _returned_val = &rest[..if_pos];
                let tail = rest[if_pos + 4..].trim_end_matches('.').trim().to_string();
                // Skip "returns none if" — handled above; only proceed if not "none"
                if !_returned_val.trim().eq_ignore_ascii_case("none") && !tail.is_empty() {
                    matched.push((
                        DocPattern::ReturnsSomeIf {
                            tail,
                            confidence: CONF_RETURNS_IF,
                        },
                        idx,
                    ));
                }
                continue;
            }
        }

        // Pattern 3: "Requires <tail>"
        if let Some(tail) = try_strip_prefix_ci(line, "requires ") {
            let tail = tail.trim_end_matches('.').trim().to_string();
            if !tail.is_empty() {
                matched.push((
                    DocPattern::Requires {
                        tail,
                        confidence: CONF_REQUIRES,
                    },
                    idx,
                ));
            }
            continue;
        }

        // Pattern 4: "Panics if <tail>"
        if let Some(tail) = try_strip_prefix_ci(line, "panics if ") {
            let tail = tail.trim_end_matches('.').trim().to_string();
            if !tail.is_empty() {
                matched.push((
                    DocPattern::PanicsIf {
                        tail,
                        confidence: CONF_PANICS_IF,
                    },
                    idx,
                ));
            }
            continue;
        }
    }

    matched
}

/// Try to parse an `# Arguments` section bullet of the form:
///   `- \`var_name\`: must be <tail>`
/// Returns None if the line doesn't match.
fn try_parse_arguments_bullet(line: &str) -> Option<DocPattern> {
    // Strip leading bullet marker(s): "- ", "* ", "  - " etc.
    let stripped = line.trim_start_matches(|c: char| c == '-' || c == '*' || c.is_whitespace());
    // Extract backtick-wrapped var name: `var_name`
    let stripped = stripped.trim();
    let stripped = stripped.strip_prefix('`')?;
    let (var_name, rest) = stripped.split_once('`')?;
    let var_name = var_name.trim().to_string();
    if var_name.is_empty() {
        return None;
    }
    // Expect `: must be <tail>`
    let rest = rest.trim();
    let rest = rest.strip_prefix(':')?;
    let rest = rest.trim();
    let tail = rest
        .strip_prefix("must be ")?
        .trim_end_matches('.')
        .trim()
        .to_string();
    if tail.is_empty() {
        return None;
    }
    Some(DocPattern::ArgumentsMustBe {
        var_name,
        tail,
        confidence: CONF_ARGUMENTS_MUST_BE,
    })
}

/// Case-insensitive prefix strip. Returns the suffix after the prefix
/// (preserving original case) if the line starts with `prefix` (case-insensitively).
fn try_strip_prefix_ci<'a>(line: &'a str, prefix: &str) -> Option<&'a str> {
    if line.len() < prefix.len() {
        return None;
    }
    let head = line.get(..prefix.len())?;
    if head.eq_ignore_ascii_case(prefix) {
        Some(&line[prefix.len()..])
    } else {
        None
    }
}

/// Convert a matched `DocPattern` to a `Formula`.
///
/// For `Requires` and `PanicsIf`, tries `parse_expr` on the tail.
/// If parsing fails → returns `None` (emit nothing; conservative).
///
/// For `ReturnsNoneIf` and `ReturnsSomeIf`, the condition pattern produces
/// a fixed structural predicate (is_none / is_some on `result`); the tail
/// is stored as `raw_text` in extension_fields but is not parsed symbolically
/// (natural-language condition is loss-characterized in `raw_text`).
///
/// For `ArgumentsMustBe`, tries `parse_expr` on `"<var> <tail>"`.
/// If parsing fails → returns `None`.
fn doc_pattern_to_formula(pattern: &DocPattern) -> Option<(Rc<Formula>, String, String)> {
    // Returns: (formula, pattern_kind, raw_text)
    match pattern {
        DocPattern::ReturnsNoneIf { tail, .. } => {
            // Predicate: is_none(result)  — the condition is characterized via raw_text.
            let formula = atomic_("is_none", vec![make_var("result")]);
            Some((
                formula,
                "returns_if".to_string(),
                format!("Returns None if {tail}"),
            ))
        }
        DocPattern::ReturnsSomeIf { tail, .. } => {
            // Predicate: is_some(result).
            let formula = atomic_("is_some", vec![make_var("result")]);
            Some((
                formula,
                "returns_if".to_string(),
                format!("Returns Some(...) if {tail}"),
            ))
        }
        DocPattern::Requires { tail, .. } => {
            // Try parse_expr on the tail.
            match parse_expr(tail) {
                Ok(f) => Some((f, "requires".to_string(), format!("Requires {tail}"))),
                Err(_) => None, // conservative: ambiguous prose emits nothing
            }
        }
        DocPattern::PanicsIf { tail, .. } => {
            // Try parse_expr on the tail.
            match parse_expr(tail) {
                Ok(f) => Some((f, "panics_if".to_string(), format!("Panics if {tail}"))),
                Err(_) => None, // conservative: ambiguous prose emits nothing
            }
        }
        DocPattern::ArgumentsMustBe { var_name, tail, .. } => {
            // Try parse_expr on the full constraint expression.
            // First try "var_name <tail>" (e.g. "n > 0"), then just tail.
            let expr_str = format!("{var_name} {tail}");
            match parse_expr(&expr_str).or_else(|_| parse_expr(tail)) {
                Ok(f) => Some((
                    f,
                    "arguments_must_be".to_string(),
                    format!("`{var_name}` must be {tail}"),
                )),
                Err(_) => None, // conservative
            }
        }
    }
}

/// Confidence for a matched `DocPattern`.
fn doc_pattern_confidence(pattern: &DocPattern) -> u16 {
    match pattern {
        DocPattern::ReturnsNoneIf { confidence, .. } => *confidence,
        DocPattern::ReturnsSomeIf { confidence, .. } => *confidence,
        DocPattern::Requires { confidence, .. } => *confidence,
        DocPattern::PanicsIf { confidence, .. } => *confidence,
        DocPattern::ArgumentsMustBe { confidence, .. } => *confidence,
    }
}

/// Emit `EvidenceMemento`s from docstring patterns on a function.
fn emit_doc_evidences(
    fn_name: &str,
    attrs: &[syn::Attribute],
    source_path: &str,
    source_cid: &str,
    out: &mut AdapterOutput,
) {
    let doc_attrs = collect_doc_attrs(attrs);
    if doc_attrs.is_empty() {
        return;
    }
    out.seen += 1;
    let patterns = match_doc_patterns(&doc_attrs);
    let function_symbol = format!("{fn_name}@{source_path}");

    for (pattern, attr_idx) in patterns {
        let confidence = doc_pattern_confidence(&pattern);
        let (formula, pattern_kind, raw_text) = match doc_pattern_to_formula(&pattern) {
            Some(r) => r,
            None => continue, // conservative: skip unparseable tails
        };

        let da = &doc_attrs[attr_idx];
        let locator = SourceLocator {
            source_cid: source_cid.to_string(),
            span: SourceLocatorSpan {
                start: SourceLocatorPoint {
                    line: da.span_start_line,
                    col: da.span_start_col,
                },
                end: SourceLocatorPoint {
                    line: da.span_end_line,
                    col: da.span_end_col,
                },
            },
        };

        let mut ext = BTreeMap::new();
        ext.insert(
            "function_symbol".to_string(),
            serde_json::Value::String(function_symbol.clone()),
        );
        ext.insert(
            "pattern_kind".to_string(),
            serde_json::Value::String(pattern_kind),
        );
        ext.insert("raw_text".to_string(), serde_json::Value::String(raw_text));

        let ir_formula = formula_to_ir_formula(&formula);
        let cid = evidence_memento_cid(
            confidence,
            &ext,
            AUTO_PROMOTE_LIFTER_CID,
            &ir_formula,
            &SourceKind::Docstring,
            &locator,
        );
        out.evidences.push(EvidenceMemento {
            cid,
            confidence_basis_points: confidence,
            extension_fields: ext,
            kind: "evidence".to_string(),
            lifter_cid: AUTO_PROMOTE_LIFTER_CID.to_string(),
            predicate: ir_formula,
            schema_version: "1".to_string(),
            source_kind: SourceKind::Docstring,
            source_locator: locator,
        });
        out.lifted += 1;
    }
}

// ---------------------------------------------------------------------------
// Helpers: formula-to-IrFormula round-trip, CID mint, serde_json<->CValue
// (Mirror of the same helpers in sugar-lift-rust-tests PR-C, so the
// two lifters produce byte-identical CID-derivation logic.)
// ---------------------------------------------------------------------------

/// Convert a `sugar_ir_symbolic::Formula` to `sugar_ir_types::IrFormula`
/// by round-tripping through JCS.
fn formula_to_ir_formula(f: &Rc<Formula>) -> IrFormula {
    let cv = formula_to_value(f);
    let json_str = encode_jcs(&cv);
    serde_json::from_str::<IrFormula>(&json_str)
        .expect("formula_to_ir_formula: round-trip through JCS should always succeed")
}

/// Convert a `serde_json::Value` to a `canonicalizer::Value`.
///
/// #3901: shared refuse door — no float→string second encoder.
fn serde_json_to_cvalue(v: &serde_json::Value) -> Arc<CValue> {
    json_to_value(v).unwrap_or_else(|err| {
        panic!(
            "lift-contracts serde_json_to_cvalue: {err} — non-integer JSON number \
             cannot enter a content-addressed evidence CID; use \
             sugar_canonicalizer::json_to_value"
        )
    })
}

/// Compute the JCS-canonical CID for an `EvidenceMemento`.
/// Mirrors the `evidence_memento_cid` helper in `sugar-lift-rust-tests`.
///
/// JCS key order (alphabetical):
///   confidence_basis_points, extension_fields, kind, lifter_cid,
///   predicate, schemaVersion, source_kind, source_locator
fn evidence_memento_cid(
    confidence_basis_points: u16,
    extension_fields: &BTreeMap<String, serde_json::Value>,
    lifter_cid: &str,
    predicate: &IrFormula,
    source_kind: &SourceKind,
    source_locator: &SourceLocator,
) -> String {
    let pred_json = serde_json::to_value(predicate).expect("IrFormula must be serializable");
    let pred_cv = serde_json_to_cvalue(&pred_json);

    let ext_entries: Vec<(String, Arc<CValue>)> = extension_fields
        .iter()
        .map(|(k, v)| (k.clone(), serde_json_to_cvalue(v)))
        .collect();
    let ext_cv = Arc::new(CValue::Object(ext_entries));

    let kind_str: String = source_kind.clone().into();

    fn make_point(p: &SourceLocatorPoint) -> Arc<CValue> {
        Arc::new(CValue::Object(vec![
            ("col".to_string(), CValue::integer(p.col as i128)),
            ("line".to_string(), CValue::integer(p.line as i128)),
        ]))
    }
    let span_cv = Arc::new(CValue::Object(vec![
        ("end".to_string(), make_point(&source_locator.span.end)),
        ("start".to_string(), make_point(&source_locator.span.start)),
    ]));
    let locator_cv = Arc::new(CValue::Object(vec![
        (
            "source_cid".to_string(),
            CValue::string(source_locator.source_cid.clone()),
        ),
        ("span".to_string(), span_cv),
    ]));

    let header = CValue::object([
        (
            "confidence_basis_points",
            CValue::integer(confidence_basis_points as i128),
        ),
        ("extension_fields", ext_cv),
        ("kind", CValue::string("evidence")),
        ("lifter_cid", CValue::string(lifter_cid.to_string())),
        ("predicate", pred_cv),
        ("schemaVersion", CValue::string("1")),
        ("source_kind", CValue::string(kind_str)),
        ("source_locator", locator_cv),
    ]);

    let canonical_bytes = encode_jcs(&header);
    blake3_512_of(canonical_bytes.as_bytes())
}

fn walk_items(
    items: &[syn::Item],
    source_path: &str,
    source_lines: Option<&[&str]>,
    out: &mut AdapterOutput,
) {
    for item in items {
        match item {
            syn::Item::Fn(f) => visit_fn(f, source_path, source_lines, out),
            syn::Item::Mod(m) => {
                if let Some((_, items)) = &m.content {
                    walk_items(items, source_path, source_lines, out);
                }
            }
            syn::Item::Impl(i) => {
                for it in &i.items {
                    if let syn::ImplItem::Fn(f) = it {
                        visit_impl_fn(f, source_path, source_lines, out);
                    }
                }
            }
            syn::Item::Const(_)
            | syn::Item::Enum(_)
            | syn::Item::ExternCrate(_)
            | syn::Item::ForeignMod(_)
            | syn::Item::Macro(_)
            | syn::Item::Static(_)
            | syn::Item::Struct(_)
            | syn::Item::Trait(_)
            | syn::Item::TraitAlias(_)
            | syn::Item::Type(_)
            | syn::Item::Union(_)
            | syn::Item::Use(_)
            | syn::Item::Verbatim(_) => {}
            _ => panic!("sugar-lift-contracts contract walker refused unknown syn::Item variant"),
        }
    }
}

fn visit_fn(
    f: &syn::ItemFn,
    source_path: &str,
    source_lines: Option<&[&str]>,
    out: &mut AdapterOutput,
) {
    let attrs = &f.attrs;
    let name = f.sig.ident.to_string();
    if !any_contract_attr(attrs) {
        return;
    }
    out.seen += 1;
    // syn span lines are 1-based; subtract 1 for 0-based slice index.
    let fn_line = f.sig.ident.span().start().line;
    let concept_hint = concept_hint_from_span(fn_line, attrs, source_lines);
    process(name, attrs, &f.sig, source_path, concept_hint, out);
}

fn visit_impl_fn(
    f: &syn::ImplItemFn,
    source_path: &str,
    source_lines: Option<&[&str]>,
    out: &mut AdapterOutput,
) {
    let attrs = &f.attrs;
    let name = f.sig.ident.to_string();
    if !any_contract_attr(attrs) {
        return;
    }
    out.seen += 1;
    let fn_line = f.sig.ident.span().start().line;
    let concept_hint = concept_hint_from_span(fn_line, attrs, source_lines);
    process(name, attrs, &f.sig, source_path, concept_hint, out);
}

fn any_contract_attr(attrs: &[syn::Attribute]) -> bool {
    attrs.iter().any(|a| classify_attr(a).is_some())
}

#[derive(Copy, Clone, Debug)]
enum Slot {
    Pre,
    Post,
    Inv,
}

fn classify_attr(a: &syn::Attribute) -> Option<Slot> {
    let p = path_to_string(a.path());
    match p.as_str() {
        "requires" | "contracts::requires" => Some(Slot::Pre),
        "ensures" | "contracts::ensures" => Some(Slot::Post),
        "invariant" | "contracts::invariant" => Some(Slot::Inv),
        // sugar-audit: not-mine(non-contract-attributes-are-ignored-by-contract-classifier)
        _ => None,
    }
}

// ---------------------------------------------------------------------------
// Concept-hint extraction (naming round-trip, lifter side)
// ---------------------------------------------------------------------------

/// Regex pattern for a concept annotation.  Matches:
///   `// concept: <name>`   -- regular comment (via raw source scan)
///   `/// concept: <name>`  -- doc comment (via #[doc = "..."] attribute)
///
/// Name grammar: starts with `[a-zA-Z]`, then `[a-zA-Z0-9\-:_]*`.
/// Surrounding whitespace is trimmed.  Names containing spaces or other
/// characters are rejected (returns None) rather than propagating garbage.
const CONCEPT_ANNOTATION_PREFIX: &str = "concept:";

/// Validate that `name` matches `[a-zA-Z][a-zA-Z0-9\-:_]*`.
fn is_valid_concept_label(name: &str) -> bool {
    let mut chars = name.chars();
    match chars.next() {
        None => false,
        Some(c) if !c.is_ascii_alphabetic() => false,
        _ => chars.all(|c| c.is_ascii_alphanumeric() || c == '-' || c == ':' || c == '_'),
    }
}

/// Parse a single text line (stripped of its `//` or `///` prefix and
/// surrounding whitespace) as a concept annotation.  Returns the concept
/// name string if the line matches `concept: <valid-name>`, otherwise None.
fn parse_concept_annotation(line: &str) -> Option<String> {
    let trimmed = line.trim();
    let rest = trimmed.strip_prefix(CONCEPT_ANNOTATION_PREFIX)?;
    let name = rest.trim();
    if is_valid_concept_label(name) {
        Some(name.to_string())
    } else {
        None
    }
}

/// Extract a concept hint for the function whose first token is at
/// `fn_line` (1-based, matching `proc_macro2::Span::start().line`).
///
/// Search order (first match wins):
///
/// 1. Doc attributes (`#[doc = "..."]`) on the function itself, scanned
///    in reverse until a non-doc attribute or the start is reached.
///    This catches `/// concept: <name>` written directly above the fn.
///
/// 2. Raw source lines immediately preceding the function (requires
///    `source_lines` to be Some).  Scans backwards from `fn_line - 1`,
///    skipping blank lines, until a `// concept:` line or a non-comment
///    line is encountered.
///
/// Returns `None` if neither source is available or no matching annotation
/// is found.
fn concept_hint_from_span(
    fn_line: usize,
    attrs: &[syn::Attribute],
    source_lines: Option<&[&str]>,
) -> Option<String> {
    // --- Path 1: doc attributes (/// concept: <name>) ---
    // Scan ALL attrs in reverse; skip non-doc attrs, return first matching doc attr.
    for attr in attrs.iter().rev() {
        if !attr.path().is_ident("doc") {
            continue;
        }
        // Extract the string value of the #[doc = "..."] attribute.
        if let syn::Meta::NameValue(nv) = &attr.meta {
            if let syn::Expr::Lit(el) = &nv.value {
                if let syn::Lit::Str(ls) = &el.lit {
                    let text = ls.value();
                    // `///` comments come through as `" concept: foo"` (leading space).
                    if let Some(hint) = parse_concept_annotation(&text) {
                        return Some(hint);
                    }
                }
            }
        }
    }

    // --- Path 2: raw source lines (// concept: <name>) ---
    let lines = source_lines?;
    // fn_line is 1-based; the line AT that index in a 0-based slice is
    // lines[fn_line - 1].  We want the lines BEFORE it.
    if fn_line == 0 {
        return None;
    }
    // Walk backwards from the line immediately before the fn definition.
    let mut idx = fn_line.saturating_sub(2); // 0-based index of line fn_line-1
    loop {
        let raw = if idx < lines.len() { lines[idx] } else { break };
        let trimmed = raw.trim();

        if trimmed.is_empty() {
            // Skip blank lines between comment and fn keyword.
            if idx == 0 {
                break;
            }
            idx -= 1;
            continue;
        }

        // Skip attribute lines (#[...]) — they appear between the
        // concept annotation and the `fn` keyword and must be stepped over.
        if trimmed.starts_with("#[") || trimmed.starts_with("#![") {
            if idx == 0 {
                break;
            }
            idx -= 1;
            continue;
        }

        // Accept both `// concept:` and `/// concept:`.
        let rest = if let Some(r) = trimmed.strip_prefix("///") {
            r
        } else if let Some(r) = trimmed.strip_prefix("//") {
            r
        } else {
            // Not a comment line; stop scanning.
            break;
        };

        if let Some(hint) = parse_concept_annotation(rest) {
            return Some(hint);
        }

        // It's a comment but not a concept annotation; keep scanning
        // upward in case the annotation is on an earlier line.
        if idx == 0 {
            break;
        }
        idx -= 1;
    }

    None
}

fn process(
    name: String,
    attrs: &[syn::Attribute],
    sig: &syn::Signature,
    source_path: &str,
    concept_hint: Option<String>,
    out: &mut AdapterOutput,
) {
    let mut params: Vec<(String, Sort)> = Vec::new();
    for arg in &sig.inputs {
        if let syn::FnArg::Typed(pt) = arg {
            if let syn::Pat::Ident(pi) = &*pt.pat {
                params.push((pi.ident.to_string(), sort_for_type(&pt.ty)));
            }
        }
    }

    let mut pre_atoms: Vec<Rc<Formula>> = Vec::new();
    let mut post_atoms: Vec<Rc<Formula>> = Vec::new();
    let mut inv_atoms: Vec<Rc<Formula>> = Vec::new();
    let mut had_failure = false;

    for a in attrs {
        let Some(slot) = classify_attr(a) else {
            continue;
        };
        let expr = match a.parse_args::<syn::Expr>() {
            Ok(e) => e,
            Err(e) => {
                out.warnings.push(LiftWarning {
                    source_path: source_path.into(),
                    item_name: name.clone(),
                    reason: format!("parse attr arg: {e}"),
                });
                had_failure = true;
                continue;
            }
        };
        match translate_bool_expr(&expr) {
            Ok(f) => match slot {
                Slot::Pre => pre_atoms.push(f),
                Slot::Post => post_atoms.push(f),
                Slot::Inv => inv_atoms.push(f),
            },
            Err(reason) => {
                out.warnings.push(LiftWarning {
                    source_path: source_path.into(),
                    item_name: name.clone(),
                    reason,
                });
                had_failure = true;
            }
        }
    }

    if pre_atoms.is_empty() && post_atoms.is_empty() && inv_atoms.is_empty() {
        if !had_failure {
            out.warnings.push(LiftWarning {
                source_path: source_path.into(),
                item_name: name,
                reason: "no liftable contracts attrs".into(),
            });
        }
        return;
    }

    let pre = combine(pre_atoms);
    let post = combine(post_atoms);
    let inv = combine(inv_atoms);

    // For each non-empty slot, wrap in forall over the function params.
    let pre = pre.map(|f| wrap_forall(&params, 0, f));
    let post = post.map(|f| wrap_forall(&params, 0, f));
    let inv = inv.map(|f| wrap_forall(&params, 0, f));

    out.decls.push(ContractDecl {
        name,
        pre,
        post,
        inv,
        out_binding: "out".into(),
        evidence: None,
        panic_loci: Vec::new(),
        concept_hint,
    });
    out.lifted += 1;
}

fn combine(mut atoms: Vec<Rc<Formula>>) -> Option<Rc<Formula>> {
    if atoms.is_empty() {
        None
    } else if atoms.len() == 1 {
        Some(atoms.pop().unwrap())
    } else {
        Some(and_(atoms))
    }
}

fn wrap_forall(params: &[(String, Sort)], i: usize, body: Rc<Formula>) -> Rc<Formula> {
    if i >= params.len() {
        return body;
    }
    let (pname, sort) = &params[i];
    let pname = pname.clone();
    let sort = sort.clone();
    let i_next = i + 1;
    let params = params.to_vec();
    let inner = wrap_forall(&params, i_next, body);
    Rc::new(Formula::Quantifier {
        kind: "forall".into(),
        name: pname,
        sort,
        body: inner,
    })
}

#[allow(dead_code)]
fn subst_var_name(f: &Rc<Formula>, from: &str, to: &str) -> Rc<Formula> {
    if from.is_empty() || from == to {
        return f.clone();
    }
    match &**f {
        Formula::Atomic { name, args } => {
            let new_args: Vec<Rc<Term>> = args.iter().map(|a| subst_term(a, from, to)).collect();
            atomic_(name.clone(), new_args)
        }
        Formula::Connective { kind, operands } => Rc::new(Formula::Connective {
            kind: kind.clone(),
            operands: operands
                .iter()
                .map(|o| subst_var_name(o, from, to))
                .collect(),
        }),
        Formula::Quantifier {
            kind,
            name,
            sort,
            body,
        } => {
            if name == from {
                f.clone()
            } else {
                Rc::new(Formula::Quantifier {
                    kind: kind.clone(),
                    name: name.clone(),
                    sort: sort.clone(),
                    body: subst_var_name(body, from, to),
                })
            }
        }
        _ => f.clone(), // Choice: TODO: implement
    }
}

#[allow(dead_code)]
fn subst_term(t: &Rc<Term>, from: &str, to: &str) -> Rc<Term> {
    match &**t {
        Term::Var { name } if name == from => make_var(to),
        Term::Var { .. } => t.clone(),
        Term::Const { .. } => t.clone(),
        Term::Ctor { name, args } => Rc::new(Term::Ctor {
            name: name.clone(),
            args: args.iter().map(|a| subst_term(a, from, to)).collect(),
        }),
        _ => t.clone(), // Lambda, Let: TODO: implement
    }
}

fn translate_bool_expr(expr: &syn::Expr) -> Result<Rc<Formula>, String> {
    match expr {
        syn::Expr::Binary(b) => {
            let l = translate_term(&b.left)?;
            let r = translate_term(&b.right)?;
            match b.op {
                syn::BinOp::Gt(_) => Ok(gt(l, r)),
                syn::BinOp::Ge(_) => Ok(gte(l, r)),
                syn::BinOp::Lt(_) => Ok(lt(l, r)),
                syn::BinOp::Le(_) => Ok(lte(l, r)),
                syn::BinOp::Eq(_) => Ok(eq(l, r)),
                syn::BinOp::Ne(_) => Ok(ne(l, r)),
                _ => Err(format!("unsupported binop: {:?}", b.op)),
            }
        }
        syn::Expr::Paren(p) => translate_bool_expr(&p.expr),
        _ => Err("contract expression must be a comparison".into()),
    }
}

fn translate_term(expr: &syn::Expr) -> Result<Rc<Term>, String> {
    match expr {
        syn::Expr::Path(p) => {
            if let Some(id) = p.path.get_ident() {
                Ok(make_var(id.to_string()))
            } else {
                Err("path is not a simple identifier".into())
            }
        }
        syn::Expr::Lit(l) => match &l.lit {
            syn::Lit::Int(li) => {
                let n: i128 = li
                    .base10_parse()
                    .map_err(|e| format!("integer literal: {e}"))?;
                Ok(num(n))
            }
            syn::Lit::Str(ls) => Ok(str_const(ls.value())),
            _ => Err("only integer and string literals are liftable in v0".into()),
        },
        syn::Expr::Paren(p) => translate_term(&p.expr),
        syn::Expr::Call(c) => {
            let callee = match &*c.func {
                syn::Expr::Path(p) => path_to_string(&p.path),
                _ => return Err("call target is not a simple path".into()),
            };
            if c.args.len() != 1 {
                return Err(format!(
                    "call `{callee}` with {} args is not liftable in v0 (single-arg only)",
                    c.args.len()
                ));
            }
            let inner = translate_term(c.args.first().unwrap())?;
            Ok(Rc::new(Term::Ctor {
                name: callee,
                args: vec![inner],
            }))
        }
        syn::Expr::Unary(u) => {
            if matches!(u.op, syn::UnOp::Neg(_)) {
                if let syn::Expr::Lit(l) = &*u.expr {
                    if let syn::Lit::Int(li) = &l.lit {
                        let n: i128 = li
                            .base10_parse()
                            .map_err(|e| format!("integer literal: {e}"))?;
                        return Ok(num(-n));
                    }
                }
            }
            Err("unary expression not liftable".into())
        }
        _ => Err("expression shape not in v0 lift whitelist".into()),
    }
}

fn sort_for_type(ty: &syn::Type) -> Sort {
    use quote::ToTokens;
    let mut ts = proc_macro2::TokenStream::new();
    ty.to_tokens(&mut ts);
    let s = ts.to_string();
    let s = s.trim();
    if s == "String" || s == "& str" || s == "str" {
        Sort::string()
    } else if s == "bool" {
        Sort::bool()
    } else if s == "f32" || s == "f64" {
        Sort::real()
    } else {
        Int()
    }
}

fn path_to_string(p: &syn::Path) -> String {
    let mut s = String::new();
    for (i, seg) in p.segments.iter().enumerate() {
        if i > 0 {
            s.push_str("::");
        }
        s.push_str(&seg.ident.to_string());
    }
    s
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(src: &str) -> syn::File {
        syn::parse_file(src).unwrap()
    }

    #[test]
    fn lifts_requires_and_ensures() {
        let src = r#"
            #[requires(x > 0)]
            #[ensures(ret >= 0)]
            fn sqrt(x: i64) -> i64 { x }
        "#;
        let f = parse(src);
        let out = lift_file(&f, "test.rs");
        assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
        let d = &out.decls[0];
        assert_eq!(d.name, "sqrt");
        assert!(d.pre.is_some());
        assert!(d.post.is_some());
    }

    #[test]
    fn lifts_namespaced_contracts_attr() {
        let src = r#"
            #[contracts::requires(x > 0)]
            fn f(x: i64) -> i64 { x }
        "#;
        let f = parse(src);
        let out = lift_file(&f, "test.rs");
        assert_eq!(out.lifted, 1);
    }

    #[test]
    fn skips_method_call_with_warning() {
        let src = r#"
            #[requires(s.len() > 0)]
            fn f(s: String) { }
        "#;
        let f = parse(src);
        let out = lift_file(&f, "test.rs");
        assert_eq!(out.lifted, 0);
        assert!(!out.warnings.is_empty());
    }

    // ------------------------------------------------------------------
    // Naming round-trip: concept_hint extraction
    // ------------------------------------------------------------------

    /// Human-supplied name is extracted from `// concept: retry-with-jitter`
    /// immediately preceding the function.
    #[test]
    fn concept_hint_human_name_extracted() {
        let src =
            "// concept: retry-with-jitter\n#[requires(x > 0)]\nfn retry(x: i64) -> i64 { x }\n";
        let f = parse(src);
        let out = lift_file_with_source(&f, "test.rs", Some(src));
        assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
        assert_eq!(
            out.decls[0].concept_hint.as_deref(),
            Some("retry-with-jitter"),
            "expected human concept name"
        );
    }

    /// Placeholder `UNNAMED-CONCEPT-N` is extracted verbatim — the downstream
    /// binding step distinguishes it from a human name by the prefix.
    #[test]
    fn concept_hint_unnamed_placeholder_extracted() {
        let src =
            "// concept: UNNAMED-CONCEPT-3\n#[requires(x > 0)]\nfn retry(x: i64) -> i64 { x }\n";
        let f = parse(src);
        let out = lift_file_with_source(&f, "test.rs", Some(src));
        assert_eq!(out.lifted, 1);
        assert_eq!(
            out.decls[0].concept_hint.as_deref(),
            Some("UNNAMED-CONCEPT-3"),
            "expected UNNAMED placeholder to be preserved verbatim"
        );
    }

    /// When no concept annotation is present, `concept_hint` is `None`.
    #[test]
    fn concept_hint_absent_returns_none() {
        let src = "// some other comment\n#[requires(x > 0)]\nfn f(x: i64) -> i64 { x }\n";
        let f = parse(src);
        let out = lift_file_with_source(&f, "test.rs", Some(src));
        assert_eq!(out.lifted, 1);
        assert_eq!(
            out.decls[0].concept_hint, None,
            "non-concept comment must not produce a hint"
        );
    }

    /// A malformed annotation (`concept: foo bar` — space in name) is
    /// ignored; `concept_hint` stays `None`.
    #[test]
    fn concept_hint_malformed_name_rejected() {
        let src = "// concept: foo bar\n#[requires(x > 0)]\nfn f(x: i64) -> i64 { x }\n";
        let f = parse(src);
        let out = lift_file_with_source(&f, "test.rs", Some(src));
        assert_eq!(out.lifted, 1);
        assert_eq!(
            out.decls[0].concept_hint, None,
            "malformed name (space) must be rejected"
        );
    }

    /// Doc comment (`/// concept: <name>`) is also accepted, via the
    /// `#[doc = "..."]` attribute path.
    #[test]
    fn concept_hint_doc_comment_form_accepted() {
        let src = r#"
            /// concept: retry-with-jitter
            #[requires(x > 0)]
            fn retry(x: i64) -> i64 { x }
        "#;
        let f = parse(src);
        // source_text not needed for doc-comment path — attrs carry the value.
        let out = lift_file_with_source(&f, "test.rs", Some(src));
        assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
        assert_eq!(
            out.decls[0].concept_hint.as_deref(),
            Some("retry-with-jitter"),
            "doc-comment concept annotation must be extracted"
        );
    }

    /// Regression: idiomatic Rust ordering is `[doc, requires]`; reverse iter
    /// sees `[requires, doc]`.  The old `break` on `requires` caused the doc
    /// attr to be silently skipped.  The fix changes `break` -> `continue` so
    /// all attrs are scanned and the doc attr is found.
    ///
    /// This test MUST fail against pre-fix HEAD and pass after the fix.
    #[test]
    fn concept_hint_doc_above_requires_extracts_correctly() {
        let src = r#"
            /// concept: retry-with-jitter
            #[requires(x > 0)]
            fn retry(x: i32) -> i32 { x }
        "#;
        let f = parse(src);
        // lift_file (no source_text) — mirrors the production caller in lift_pass.rs.
        let out = lift_file(&f, "test.rs");
        assert_eq!(out.lifted, 1, "warnings: {:?}", out.warnings);
        assert_eq!(
            out.decls[0].concept_hint.as_deref(),
            Some("retry-with-jitter"),
            "doc attr above #[requires] must be found despite non-doc attr in reverse iter"
        );
    }

    // ------------------------------------------------------------------
    // Type-signature evidence lifter (PR-D of #716)
    // ------------------------------------------------------------------

    fn parse_bytes(src: &str) -> (syn::File, Vec<u8>) {
        (syn::parse_file(src).unwrap(), src.as_bytes().to_vec())
    }

    /// `-> Option<i32>` produces one return evidence with type_shape "option".
    #[test]
    fn sig_option_return_produces_option_shape_evidence() {
        let src = "fn foo() -> Option<i32> { None }";
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        let ret_ev = out.evidences.iter().find(|e| {
            e.extension_fields
                .get("signature_position")
                .and_then(|v| v.as_str())
                == Some("return")
        });
        assert!(ret_ev.is_some(), "expected a return evidence");
        let ev = ret_ev.unwrap();
        assert_eq!(
            ev.extension_fields["type_shape"].as_str(),
            Some("option"),
            "type_shape must be 'option'"
        );
        assert_eq!(
            ev.extension_fields
                .get("inner_type")
                .and_then(|v| v.as_str()),
            Some("i32"),
            "inner_type must be 'i32'"
        );
    }

    /// `-> Result<T, E>` produces one return evidence with type_shape "result".
    #[test]
    fn sig_result_return_produces_alt_shape_evidence() {
        let src = "fn bar() -> Result<i32, String> { Ok(0) }";
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        let ret_ev = out.evidences.iter().find(|e| {
            e.extension_fields
                .get("signature_position")
                .and_then(|v| v.as_str())
                == Some("return")
        });
        assert!(ret_ev.is_some(), "expected a return evidence for Result");
        let ev = ret_ev.unwrap();
        assert_eq!(ev.extension_fields["type_shape"].as_str(), Some("result"));
        assert_eq!(
            ev.extension_fields.get("ok_type").and_then(|v| v.as_str()),
            Some("i32")
        );
        assert_eq!(
            ev.extension_fields.get("err_type").and_then(|v| v.as_str()),
            Some("String")
        );
    }

    /// `-> Vec<T>` produces a return evidence with type_shape "vec".
    #[test]
    fn sig_vec_return_produces_finite_list_evidence() {
        let src = "fn items() -> Vec<u8> { vec![] }";
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        let ret_ev = out.evidences.iter().find(|e| {
            e.extension_fields
                .get("signature_position")
                .and_then(|v| v.as_str())
                == Some("return")
        });
        assert!(ret_ev.is_some(), "expected a return evidence for Vec");
        let ev = ret_ev.unwrap();
        assert_eq!(ev.extension_fields["type_shape"].as_str(), Some("vec"));
        assert_eq!(
            ev.extension_fields
                .get("element_type")
                .and_then(|v| v.as_str()),
            Some("u8")
        );
    }

    /// `-> ()` (explicit unit) produces a trivial-result evidence.
    #[test]
    fn sig_unit_return_produces_trivial_result_evidence() {
        let src = "fn noop() -> () {}";
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        let ret_ev = out.evidences.iter().find(|e| {
            e.extension_fields
                .get("signature_position")
                .and_then(|v| v.as_str())
                == Some("return")
        });
        assert!(ret_ev.is_some(), "expected evidence for unit return");
        assert_eq!(
            ret_ev.unwrap().extension_fields["type_shape"].as_str(),
            Some("unit")
        );
    }

    /// `&self` and `&mut self` produce ownership-mode evidences.
    #[test]
    fn sig_self_mut_self_produce_ownership_evidences() {
        let src = r#"
            struct S;
            impl S {
                fn shared(&self) {}
                fn exclusive(&mut self) {}
            }
        "#;
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        // Find receiver evidences.
        let shared = out.evidences.iter().find(|e| {
            e.extension_fields
                .get("type_shape")
                .and_then(|v| v.as_str())
                == Some("receiver-shared")
        });
        let exclusive = out.evidences.iter().find(|e| {
            e.extension_fields
                .get("type_shape")
                .and_then(|v| v.as_str())
                == Some("receiver-exclusive")
        });
        assert!(
            shared.is_some(),
            "expected receiver-shared evidence for &self"
        );
        assert!(
            exclusive.is_some(),
            "expected receiver-exclusive evidence for &mut self"
        );
    }

    /// `x: NonZeroU32` produces a refined-domain evidence with `ne(x, 0)` predicate.
    #[test]
    fn sig_non_zero_param_produces_refined_domain_evidence() {
        let src = "fn f(x: NonZeroU32) -> u32 { x.get() }";
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        let nz_ev = out.evidences.iter().find(|e| {
            e.extension_fields
                .get("type_shape")
                .and_then(|v| v.as_str())
                == Some("non-zero")
                && e.extension_fields
                    .get("signature_position")
                    .and_then(|v| v.as_str())
                    .is_some_and(|p| p.starts_with("param:"))
        });
        assert!(nz_ev.is_some(), "expected non-zero evidence for NonZeroU32");
        let ev = nz_ev.unwrap();
        assert_eq!(
            ev.extension_fields
                .get("inner_type")
                .and_then(|v| v.as_str()),
            Some("NonZeroU32")
        );
        // source_kind must be TypeSignature.
        assert_eq!(
            ev.source_kind,
            sugar_ir_types::SourceKind::TypeSignature,
            "source_kind must be TypeSignature"
        );
        // confidence must be 10000 (static).
        assert_eq!(ev.confidence_basis_points, 10000);
    }

    /// A function with mixed signature emits all expected evidence types.
    #[test]
    fn sig_mixed_fn_produces_all_evidence_kinds() {
        // &self, x: NonZeroU32, y: i32, -> Option<u64>
        let src = r#"
            struct S;
            impl S {
                fn compute(&self, x: NonZeroU32, y: i32) -> Option<u64> { None }
            }
        "#;
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        // Should have: receiver-shared, non-zero (x), bounded-primitive (y), option (return).
        let shapes: Vec<&str> = out
            .evidences
            .iter()
            .filter_map(|e| {
                e.extension_fields
                    .get("type_shape")
                    .and_then(|v| v.as_str())
            })
            .collect();
        assert!(
            shapes.contains(&"receiver-shared"),
            "missing receiver-shared"
        );
        assert!(
            shapes.contains(&"non-zero"),
            "missing non-zero for NonZeroU32"
        );
        assert!(
            shapes.contains(&"bounded-primitive"),
            "missing bounded-primitive for i32"
        );
        assert!(shapes.contains(&"option"), "missing option return evidence");
    }

    /// A function with only bare-generic params and no return type emits
    /// no evidence (conservative: bare `T` has no derivable constraint).
    #[test]
    fn sig_bare_generic_only_emits_no_evidence() {
        let src = "fn identity<T>(x: T) -> T { x }";
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        assert!(
            out.evidences.is_empty(),
            "bare generic T must produce no evidence; got: {:?}",
            out.evidences
                .iter()
                .map(|e| &e.extension_fields)
                .collect::<Vec<_>>()
        );
    }

    /// `fn f(x: i32)` (bare primitive param, implicit unit return) emits
    /// two evidences: one bounded-primitive for the param, one unit for the return.
    #[test]
    fn sig_primitive_param_and_implicit_unit_return() {
        let src = "fn sink(x: i32) {}";
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        let prim_ev = out.evidences.iter().find(|e| {
            e.extension_fields
                .get("type_shape")
                .and_then(|v| v.as_str())
                == Some("bounded-primitive")
        });
        let unit_ev = out.evidences.iter().find(|e| {
            e.extension_fields
                .get("type_shape")
                .and_then(|v| v.as_str())
                == Some("unit")
        });
        assert!(
            prim_ev.is_some(),
            "expected bounded-primitive evidence for i32 param"
        );
        assert!(
            unit_ev.is_some(),
            "expected unit evidence for implicit () return"
        );
    }

    /// Evidence CIDs are deterministic: same source bytes = same CIDs.
    #[test]
    fn sig_evidence_cid_is_deterministic() {
        let src = "fn foo(x: u32) -> Option<i64> { None }";
        let (f, bytes) = parse_bytes(src);
        let out1 = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        let out2 = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        assert_eq!(out1.evidences.len(), out2.evidences.len());
        for (a, b) in out1.evidences.iter().zip(out2.evidences.iter()) {
            assert_eq!(a.cid, b.cid, "CIDs must be deterministic");
        }
    }

    /// `lift_file` leaves `evidences` empty (backward-compat: existing API
    /// is annotation-only, no type-sig evidences).
    #[test]
    fn basic_lift_file_does_not_populate_evidences() {
        let src = r#"
            #[requires(x > 0)]
            fn f(x: i64) -> i64 { x }
        "#;
        let f = parse(src);
        let out = lift_file(&f, "test.rs");
        assert!(
            out.evidences.is_empty(),
            "lift_file must not populate evidences"
        );
    }

    /// Every evidence carries `function_symbol` (not `function_term_cid`) as a
    /// plain `name@path` identifier string.  No evidence should have a key
    /// named `function_term_cid`.
    #[test]
    fn sig_evidence_carries_function_symbol_not_cid() {
        let src = "fn greet(x: u32) -> Option<String> { None }";
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "src/lib.rs", &bytes);
        assert!(!out.evidences.is_empty(), "expected at least one evidence");
        for ev in &out.evidences {
            // Must have function_symbol.
            let sym = ev
                .extension_fields
                .get("function_symbol")
                .and_then(|v| v.as_str())
                .expect("evidence must carry function_symbol");
            assert_eq!(sym, "greet@src/lib.rs", "function_symbol must be name@path");
            // Must NOT have function_term_cid.
            assert!(
                !ev.extension_fields.contains_key("function_term_cid"),
                "function_term_cid must not appear; use function_symbol"
            );
        }
    }

    // ------------------------------------------------------------------
    // Spec violation fixes: B1 (return_type), B2 (0-indexed col), B3
    // ------------------------------------------------------------------

    /// B1 — every type-signature evidence carries `return_type` in
    /// `extension_fields` set to the function's written return type string
    /// (spec §10: required field for `source_kind: "type-signature"`).
    #[test]
    fn spec_b1_every_type_sig_evidence_has_return_type_field() {
        // Mixed signature: receiver + primitive param + Option return.
        let src = r#"
            struct S;
            impl S {
                fn compute(&self, x: i32) -> Option<i32> { None }
            }
        "#;
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        assert!(!out.evidences.is_empty(), "expected evidences");
        for ev in &out.evidences {
            let rt = ev
                .extension_fields
                .get("return_type")
                .and_then(|v| v.as_str())
                .unwrap_or_else(|| {
                    panic!(
                        "evidence missing return_type field; extension_fields = {:?}",
                        ev.extension_fields
                    )
                });
            assert_eq!(
                rt, "Option<i32>",
                "return_type must be the function's written return type"
            );
        }
    }

    /// B1 corollary — implicit unit return `fn f()` renders as `"()"`.
    #[test]
    fn spec_b1_implicit_unit_return_type_string_is_parens() {
        let src = "fn sink(x: i32) {}";
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        assert!(!out.evidences.is_empty(), "expected evidences");
        for ev in &out.evidences {
            let rt = ev
                .extension_fields
                .get("return_type")
                .and_then(|v| v.as_str())
                .unwrap_or_else(|| {
                    panic!(
                        "evidence missing return_type; fields = {:?}",
                        ev.extension_fields
                    )
                });
            assert_eq!(rt, "()", "implicit unit must render as '()'");
        }
    }

    /// B2 — `col` in `source_locator` is 0-indexed (spec §1.1).
    ///
    /// Source layout (no leading spaces):
    ///   line 1: `fn precise(x: u32) { }`
    ///
    /// `fn` starts at col 0 and `precise` starts at col 3 (0-indexed).
    /// proc_macro2 Span::start().column is also 0-indexed, so no +1 must
    /// be added.  If this test fails with col=4 the +1 bug was re-introduced.
    #[test]
    fn spec_b2_source_locator_col_is_0indexed() {
        let src = "fn precise(x: u32) { }";
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "t.rs", &bytes);
        assert!(!out.evidences.is_empty(), "expected at least one evidence");
        let ev = &out.evidences[0];
        // "fn " is 3 bytes; `precise` identifier starts at col 3 (0-indexed).
        assert_eq!(
            ev.source_locator.span.start.col, 3,
            "col must be 0-indexed per spec §1.1; got {}. \
             If this is 4, the +1 bug was re-introduced.",
            ev.source_locator.span.start.col
        );
        assert_eq!(
            ev.source_locator.span.start.line, 1,
            "line must be 1-indexed; got {}",
            ev.source_locator.span.start.line
        );
    }

    /// B3 — `-> Option<T>` emits predicate `is_some(result) ∨ is_none(result)`,
    /// not `Atomic("true")` (spec §1.1.1).
    #[test]
    fn spec_b3_option_return_emits_is_some_or_is_none_predicate() {
        let src = "fn maybe(x: i32) -> Option<i32> { None }";
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        let ret_ev = out.evidences.iter().find(|e| {
            e.extension_fields
                .get("signature_position")
                .and_then(|v| v.as_str())
                == Some("return")
        });
        let ev = ret_ev.expect("expected a return evidence for Option<i32>");
        match &ev.predicate {
            sugar_ir_types::IrFormula::Or { operands } => {
                assert_eq!(operands.len(), 2, "Or must have 2 operands");
                let names: Vec<&str> = operands
                    .iter()
                    .filter_map(|o| match o {
                        sugar_ir_types::IrFormula::Atomic { name, .. } => Some(name.as_str()),
                        // sugar-audit: not-mine(test-helper-only-selects-atomic-predicate-names)
                        _ => None,
                    })
                    .collect();
                assert!(
                    names.contains(&"is_some"),
                    "predicate must contain is_some; got {:?}",
                    names
                );
                assert!(
                    names.contains(&"is_none"),
                    "predicate must contain is_none; got {:?}",
                    names
                );
            }
            other => panic!(
                "Option return predicate must be Or{{is_some,is_none}}; got {:?}",
                other
            ),
        }
    }

    /// B3 — `-> Result<T, E>` emits predicate `is_ok(result) ∨ is_err(result)`.
    #[test]
    fn spec_b3_result_return_emits_is_ok_or_is_err_predicate() {
        let src = "fn fallible(x: i32) -> Result<i32, String> { Ok(x) }";
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        let ret_ev = out.evidences.iter().find(|e| {
            e.extension_fields
                .get("signature_position")
                .and_then(|v| v.as_str())
                == Some("return")
        });
        let ev = ret_ev.expect("expected a return evidence for Result");
        match &ev.predicate {
            sugar_ir_types::IrFormula::Or { operands } => {
                assert_eq!(operands.len(), 2, "Or must have 2 operands");
                let names: Vec<&str> = operands
                    .iter()
                    .filter_map(|o| match o {
                        sugar_ir_types::IrFormula::Atomic { name, .. } => Some(name.as_str()),
                        // sugar-audit: not-mine(test-helper-only-selects-atomic-predicate-names)
                        _ => None,
                    })
                    .collect();
                assert!(
                    names.contains(&"is_ok"),
                    "predicate must contain is_ok; got {:?}",
                    names
                );
                assert!(
                    names.contains(&"is_err"),
                    "predicate must contain is_err; got {:?}",
                    names
                );
            }
            other => panic!(
                "Result return predicate must be Or{{is_ok,is_err}}; got {:?}",
                other
            ),
        }
    }

    // ------------------------------------------------------------------
    // Docstring evidence lifter (PR-E of #716)
    // ------------------------------------------------------------------

    fn parse_doc_bytes(src: &str) -> (syn::File, Vec<u8>) {
        (syn::parse_file(src).unwrap(), src.as_bytes().to_vec())
    }

    /// "Returns None if x is negative" produces a post evidence with
    /// predicate `is_none(result)` and source_kind Docstring.
    #[test]
    fn doc_returns_none_if_produces_is_none_evidence() {
        let src = r#"
            /// Returns None if x is negative.
            fn maybe_negate(x: i32) -> Option<i32> { None }
        "#;
        let (f, bytes) = parse_doc_bytes(src);
        let out = lift_file_with_docstring_evidence(&f, "test.rs", &bytes);
        assert_eq!(
            out.evidences.len(),
            1,
            "expected 1 evidence; got {:?}",
            out.evidences
        );
        let ev = &out.evidences[0];
        assert_eq!(ev.source_kind, sugar_ir_types::SourceKind::Docstring);
        assert_eq!(ev.confidence_basis_points, 7500);
        assert_eq!(
            ev.extension_fields
                .get("pattern_kind")
                .and_then(|v| v.as_str()),
            Some("returns_if"),
        );
        // Predicate must be is_none(result).
        match &ev.predicate {
            sugar_ir_types::IrFormula::Atomic { name, args } => {
                assert_eq!(name, "is_none");
                assert_eq!(args.len(), 1);
                match &args[0] {
                    sugar_ir_types::IrTerm::Var { name: v } => assert_eq!(v, "result"),
                    other => panic!("expected Var(result); got {other:?}"),
                }
            }
            other => panic!("expected Atomic(is_none); got {other:?}"),
        }
    }

    /// "Requires x > 0" produces a pre evidence with predicate `x > 0`.
    #[test]
    fn doc_requires_parseable_tail_produces_evidence() {
        let src = r#"
            /// Requires x > 0.
            fn sqrt(x: f64) -> f64 { x }
        "#;
        let (f, bytes) = parse_doc_bytes(src);
        let out = lift_file_with_docstring_evidence(&f, "test.rs", &bytes);
        assert_eq!(
            out.evidences.len(),
            1,
            "expected 1 evidence; got {:?}",
            out.evidences
        );
        let ev = &out.evidences[0];
        assert_eq!(ev.source_kind, sugar_ir_types::SourceKind::Docstring);
        assert_eq!(ev.confidence_basis_points, 8000);
        assert_eq!(
            ev.extension_fields
                .get("pattern_kind")
                .and_then(|v| v.as_str()),
            Some("requires"),
        );
        // Predicate should parse as x > 0.
        match &ev.predicate {
            sugar_ir_types::IrFormula::Atomic { name, args } => {
                assert_eq!(name, ">", "predicate name must be '>'");
                assert_eq!(args.len(), 2);
            }
            other => panic!("expected Atomic(>); got {other:?}"),
        }
    }

    /// "Panics if n == 0" produces a pre evidence with predicate `n == 0`.
    #[test]
    fn doc_panics_if_parseable_tail_produces_evidence() {
        let src = r#"
            /// Panics if n == 0.
            fn divide(a: i32, n: i32) -> i32 { a / n }
        "#;
        let (f, bytes) = parse_doc_bytes(src);
        let out = lift_file_with_docstring_evidence(&f, "test.rs", &bytes);
        assert_eq!(
            out.evidences.len(),
            1,
            "expected 1 evidence; got {:?}",
            out.evidences
        );
        let ev = &out.evidences[0];
        assert_eq!(ev.source_kind, sugar_ir_types::SourceKind::Docstring);
        assert_eq!(ev.confidence_basis_points, 8000);
        assert_eq!(
            ev.extension_fields
                .get("pattern_kind")
                .and_then(|v| v.as_str()),
            Some("panics_if"),
        );
    }

    /// Ambiguous prose (no recognized pattern) emits zero evidences.
    #[test]
    fn doc_ambiguous_prose_emits_no_evidence() {
        let src = r#"
            /// This function does something interesting when the input is large.
            /// It may or may not work under special conditions.
            fn do_thing(x: i32) -> i32 { x }
        "#;
        let (f, bytes) = parse_doc_bytes(src);
        let out = lift_file_with_docstring_evidence(&f, "test.rs", &bytes);
        assert!(
            out.evidences.is_empty(),
            "ambiguous prose must emit no evidence; got: {:?}",
            out.evidences
        );
    }

    /// Unrelated non-ASCII prose must be ignored without slicing through a char boundary.
    #[test]
    fn doc_unrelated_unicode_prose_emits_no_evidence() {
        let src = r#"
            /// Per CCP §2 + §9: this is the canonical primitive named in the spec.
            fn primitive_name() -> &'static str { "ccp" }
        "#;
        let (f, bytes) = parse_doc_bytes(src);
        let out = lift_file_with_docstring_evidence(&f, "test.rs", &bytes);
        assert!(
            out.evidences.is_empty(),
            "unrelated unicode prose must emit no evidence; got: {:?}",
            out.evidences
        );
    }

    /// "Requires" with an unparseable natural-language tail emits nothing (conservative).
    #[test]
    fn doc_requires_unparseable_tail_emits_no_evidence() {
        let src = r#"
            /// Requires the buffer to be non-empty and UTF-8 encoded.
            fn parse_str(buf: &[u8]) -> Option<String> { None }
        "#;
        let (f, bytes) = parse_doc_bytes(src);
        let out = lift_file_with_docstring_evidence(&f, "test.rs", &bytes);
        assert!(
            out.evidences.is_empty(),
            "unparseable tail must emit no evidence; got: {:?}",
            out.evidences
        );
    }

    /// Mixed doc: pre + post patterns in one docstring both produce evidences.
    #[test]
    fn doc_mixed_pre_and_post_in_one_docstring() {
        let src = r#"
            /// Returns None if x < 0.
            /// Requires x != -1.
            fn f(x: i32) -> Option<i32> { None }
        "#;
        let (f, bytes) = parse_doc_bytes(src);
        let out = lift_file_with_docstring_evidence(&f, "test.rs", &bytes);
        assert_eq!(
            out.evidences.len(),
            2,
            "expected 2 evidences (returns_if + requires); got {:?}",
            out.evidences
                .iter()
                .map(|e| e
                    .extension_fields
                    .get("pattern_kind")
                    .and_then(|v| v.as_str()))
                .collect::<Vec<_>>()
        );
        let kinds: Vec<&str> = out
            .evidences
            .iter()
            .filter_map(|e| {
                e.extension_fields
                    .get("pattern_kind")
                    .and_then(|v| v.as_str())
            })
            .collect();
        assert!(kinds.contains(&"returns_if"), "missing returns_if evidence");
        assert!(kinds.contains(&"requires"), "missing requires evidence");
    }

    /// `# Arguments` section with `must be` constraint produces evidence.
    #[test]
    fn doc_arguments_section_must_be_produces_evidence() {
        let src = r#"
            /// Does something.
            ///
            /// # Arguments
            ///
            /// - `count`: must be count > 0
            fn repeat(count: u32) -> Vec<u8> { vec![] }
        "#;
        let (f, bytes) = parse_doc_bytes(src);
        let out = lift_file_with_docstring_evidence(&f, "test.rs", &bytes);
        assert_eq!(
            out.evidences.len(),
            1,
            "expected 1 arguments_must_be evidence; got {:?}",
            out.evidences
        );
        let ev = &out.evidences[0];
        assert_eq!(ev.confidence_basis_points, 8500);
        assert_eq!(
            ev.extension_fields
                .get("pattern_kind")
                .and_then(|v| v.as_str()),
            Some("arguments_must_be"),
        );
    }

    /// Evidence CIDs are deterministic: same source bytes → same CIDs.
    #[test]
    fn doc_evidence_cid_is_deterministic() {
        let src = r#"
            /// Returns None if x < 0.
            /// Requires x != -1.
            fn f(x: i32) -> Option<i32> { None }
        "#;
        let (f, bytes) = parse_doc_bytes(src);
        let out1 = lift_file_with_docstring_evidence(&f, "test.rs", &bytes);
        let out2 = lift_file_with_docstring_evidence(&f, "test.rs", &bytes);
        assert_eq!(out1.evidences.len(), out2.evidences.len());
        for (a, b) in out1.evidences.iter().zip(out2.evidences.iter()) {
            assert_eq!(a.cid, b.cid, "CIDs must be deterministic");
        }
    }

    /// impl method docstring is walked (not just top-level fns).
    #[test]
    fn doc_impl_method_docstring_is_walked() {
        let src = r#"
            struct Counter;
            impl Counter {
                /// Panics if n == 0.
                fn increment(&mut self, n: i32) { }
            }
        "#;
        let (f, bytes) = parse_doc_bytes(src);
        let out = lift_file_with_docstring_evidence(&f, "test.rs", &bytes);
        assert_eq!(
            out.evidences.len(),
            1,
            "impl method docstring must be walked"
        );
        assert_eq!(
            out.evidences[0].source_kind,
            sugar_ir_types::SourceKind::Docstring
        );
    }

    /// B3 — `-> Vec<T>` emits predicate `is_finite_list(result)`.
    #[test]
    fn spec_b3_vec_return_emits_is_finite_list_predicate() {
        let src = "fn collect(x: i32) -> Vec<u8> { vec![] }";
        let (f, bytes) = parse_bytes(src);
        let out = lift_file_with_sig_evidence(&f, "test.rs", &bytes);
        let ret_ev = out.evidences.iter().find(|e| {
            e.extension_fields
                .get("signature_position")
                .and_then(|v| v.as_str())
                == Some("return")
        });
        let ev = ret_ev.expect("expected a return evidence for Vec<u8>");
        match &ev.predicate {
            sugar_ir_types::IrFormula::Atomic { name, args } => {
                assert_eq!(
                    name, "is_finite_list",
                    "Vec predicate must be is_finite_list; got {name}"
                );
                assert_eq!(args.len(), 1, "is_finite_list must have 1 arg");
                match &args[0] {
                    sugar_ir_types::IrTerm::Var { name: var_name } => {
                        assert_eq!(
                            var_name, "result",
                            "arg must be Var(result); got {var_name}"
                        );
                    }
                    other => panic!("expected Var(result); got {:?}", other),
                }
            }
            other => panic!(
                "Vec return predicate must be Atomic(is_finite_list); got {:?}",
                other
            ),
        }
    }
}

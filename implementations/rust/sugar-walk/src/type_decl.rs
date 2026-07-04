// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Type declarations: enums, structs, traits, impl blocks.
//
// Per #377. Each type definition emits a content-addressed memento
// describing the type's shape; impl blocks emit one
// FunctionContractMemento per method linked back to the type via
// `parent_type_cid`. Trait definitions emit method-signature
// mementos that bind impl methods can satisfy.
//
// Schema overview:
//
//   TypeDeclMemento (struct):
//     { schemaVersion: "1", kind: "type-decl-struct",
//       name: <string>, fields: [{name, sort}, ...], locus }
//
//   TypeDeclMemento (enum):
//     { schemaVersion: "1", kind: "type-decl-enum",
//       name: <string>, variants: [VariantMemento, ...], locus }
//
//   VariantMemento:
//     { name: <string>, kind: "unit" | "tuple" | "struct",
//       fields: [<sort>, ...] | [{name, sort}, ...] | [] }
//
//   TraitMemento:
//     { schemaVersion: "1", kind: "trait",
//       name: <string>, method_signatures: [<MethodSignature>, ...], locus }
//
//   MethodSignatureMemento:
//     { schemaVersion: "1", kind: "method-signature",
//       trait_name: <string>, method_name: <string>,
//       formals, formal_sorts, return_sort, locus }
//
//   ImplMemento:
//     { schemaVersion: "1", kind: "impl",
//       target_type: <string>, trait_name: <string or null>,
//       method_cids: [<cid>, ...], locus }
//
// MVP scope: extract these from a syn::File and emit
// content-addressed bytes. Substrate-side resolution (binding impl
// methods to trait method signatures, etc.) is downstream.

use std::sync::Arc;

use quote::ToTokens;
use sugar_canonicalizer::Value;
use sugar_ir_types::Sort;
use syn::{File, Item, ItemEnum, ItemImpl, ItemStruct, ItemTrait};

use crate::canonical::{cid_of_value, jcs_bytes_of_value};
use crate::contract::build_function_contract_with_file;
use crate::locus::{Locus, LocusFromSpanExt};

// ---- Struct ----

const LOSS_GENERICS_BOUNDS_NOT_DISCHARGED: &str = "generics-bounds-not-discharged";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GenericParameterMemento {
    pub name: String,
    pub kind: String,
}

impl GenericParameterMemento {
    fn to_value(&self) -> Arc<Value> {
        Value::object([
            ("name", Value::string(self.name.clone())),
            ("kind", Value::string(self.kind.clone())),
        ])
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WhereBoundCitation {
    pub concept: String,
    pub predicate: String,
}

impl WhereBoundCitation {
    fn to_value(&self) -> Arc<Value> {
        Value::object([
            ("concept", Value::string(self.concept.clone())),
            ("predicate", Value::string(self.predicate.clone())),
        ])
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TypeDeclLossRecord {
    pub loss: String,
    pub detail: String,
}

impl TypeDeclLossRecord {
    fn to_value(&self) -> Arc<Value> {
        Value::object([
            ("loss", Value::string(self.loss.clone())),
            ("detail", Value::string(self.detail.clone())),
        ])
    }
}

#[derive(Debug, Clone, Default)]
struct GenericMementoParts {
    parameters: Vec<GenericParameterMemento>,
    where_bounds: Vec<WhereBoundCitation>,
    loss_record: Vec<TypeDeclLossRecord>,
}

impl GenericMementoParts {
    fn handling(&self) -> String {
        if self.loss_record.is_empty() {
            "handles-fully".to_string()
        } else {
            "handles-partially-with-loss-record".to_string()
        }
    }
}

#[derive(Debug, Clone)]
pub struct StructDeclMemento {
    pub name: String,
    pub fields: Vec<(String, Sort)>,
    pub generic_parameters: Vec<GenericParameterMemento>,
    pub where_bounds: Vec<WhereBoundCitation>,
    pub handling: String,
    pub loss_record: Vec<TypeDeclLossRecord>,
    pub locus: Locus,
    pub canonical_bytes: Vec<u8>,
    pub cid: String,
}

pub fn lift_struct_decl(item: &ItemStruct, file_path: Option<&str>) -> StructDeclMemento {
    let name = item.ident.to_string();
    let fields = match &item.fields {
        syn::Fields::Named(named) => named
            .named
            .iter()
            .map(|f| {
                let field_name = f
                    .ident
                    .as_ref()
                    .map(|i| i.to_string())
                    .unwrap_or_else(|| "<unnamed>".to_string());
                (field_name, infer_sort(&f.ty))
            })
            .collect(),
        syn::Fields::Unnamed(unnamed) => unnamed
            .unnamed
            .iter()
            .enumerate()
            .map(|(i, f)| (format!("{}", i), infer_sort(&f.ty)))
            .collect(),
        syn::Fields::Unit => vec![],
    };
    let locus = Locus::from_span(item.ident.span(), file_path);
    let generics = generic_memento_parts(&item.generics);
    let handling = generics.handling();

    let fields_arr: Vec<Arc<Value>> = fields
        .iter()
        .map(|(n, s)| {
            Value::object([
                ("name", Value::string(n.clone())),
                ("sort", sort_to_value(s)),
            ])
        })
        .collect();
    let value = Value::object([
        ("schemaVersion", Value::string("1")),
        ("kind", Value::string("type-decl-struct")),
        ("name", Value::string(name.clone())),
        ("fields", Value::array(fields_arr)),
        (
            "genericParameters",
            Value::array(
                generics
                    .parameters
                    .iter()
                    .map(GenericParameterMemento::to_value)
                    .collect(),
            ),
        ),
        (
            "whereBounds",
            Value::array(
                generics
                    .where_bounds
                    .iter()
                    .map(WhereBoundCitation::to_value)
                    .collect(),
            ),
        ),
        ("handling", Value::string(handling.clone())),
        (
            "lossRecord",
            Value::array(
                generics
                    .loss_record
                    .iter()
                    .map(TypeDeclLossRecord::to_value)
                    .collect(),
            ),
        ),
        ("locus", locus.to_value()),
    ]);
    let canonical_bytes = jcs_bytes_of_value(&value);
    let cid = cid_of_value(&value);

    StructDeclMemento {
        name,
        fields,
        generic_parameters: generics.parameters,
        where_bounds: generics.where_bounds,
        handling,
        loss_record: generics.loss_record,
        locus,
        canonical_bytes,
        cid,
    }
}

// ---- Enum ----

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VariantShape {
    Unit,
    Tuple(Vec<Sort>),
    Struct(Vec<(String, Sort)>),
}

#[derive(Debug, Clone)]
pub struct VariantMemento {
    pub name: String,
    pub shape: VariantShape,
}

impl VariantMemento {
    fn to_value(&self) -> Arc<Value> {
        match &self.shape {
            VariantShape::Unit => Value::object([
                ("name", Value::string(self.name.clone())),
                ("kind", Value::string("unit")),
            ]),
            VariantShape::Tuple(sorts) => {
                let arr: Vec<Arc<Value>> = sorts.iter().map(sort_to_value).collect();
                Value::object([
                    ("name", Value::string(self.name.clone())),
                    ("kind", Value::string("tuple")),
                    ("fields", Value::array(arr)),
                ])
            }
            VariantShape::Struct(fields) => {
                let arr: Vec<Arc<Value>> = fields
                    .iter()
                    .map(|(n, s)| {
                        Value::object([
                            ("name", Value::string(n.clone())),
                            ("sort", sort_to_value(s)),
                        ])
                    })
                    .collect();
                Value::object([
                    ("name", Value::string(self.name.clone())),
                    ("kind", Value::string("struct")),
                    ("fields", Value::array(arr)),
                ])
            }
        }
    }
}

#[derive(Debug, Clone)]
pub struct EnumDeclMemento {
    pub name: String,
    pub variants: Vec<VariantMemento>,
    pub generic_parameters: Vec<GenericParameterMemento>,
    pub where_bounds: Vec<WhereBoundCitation>,
    pub handling: String,
    pub loss_record: Vec<TypeDeclLossRecord>,
    pub locus: Locus,
    pub canonical_bytes: Vec<u8>,
    pub cid: String,
}

pub fn lift_enum_decl(item: &ItemEnum, file_path: Option<&str>) -> EnumDeclMemento {
    let name = item.ident.to_string();
    let variants: Vec<VariantMemento> = item
        .variants
        .iter()
        .map(|v| {
            let vname = v.ident.to_string();
            let shape = match &v.fields {
                syn::Fields::Unit => VariantShape::Unit,
                syn::Fields::Unnamed(unnamed) => {
                    VariantShape::Tuple(unnamed.unnamed.iter().map(|f| infer_sort(&f.ty)).collect())
                }
                syn::Fields::Named(named) => VariantShape::Struct(
                    named
                        .named
                        .iter()
                        .map(|f| {
                            let field_name = f
                                .ident
                                .as_ref()
                                .expect("named enum variant field has an identifier")
                                .to_string();
                            (field_name, infer_sort(&f.ty))
                        })
                        .collect(),
                ),
            };
            VariantMemento { name: vname, shape }
        })
        .collect();
    let locus = Locus::from_span(item.ident.span(), file_path);
    let generics = generic_memento_parts(&item.generics);
    let handling = generics.handling();

    let variants_arr: Vec<Arc<Value>> = variants.iter().map(|v| v.to_value()).collect();
    let value = Value::object([
        ("schemaVersion", Value::string("1")),
        ("kind", Value::string("type-decl-enum")),
        ("name", Value::string(name.clone())),
        ("variants", Value::array(variants_arr)),
        (
            "genericParameters",
            Value::array(
                generics
                    .parameters
                    .iter()
                    .map(GenericParameterMemento::to_value)
                    .collect(),
            ),
        ),
        (
            "whereBounds",
            Value::array(
                generics
                    .where_bounds
                    .iter()
                    .map(WhereBoundCitation::to_value)
                    .collect(),
            ),
        ),
        ("handling", Value::string(handling.clone())),
        (
            "lossRecord",
            Value::array(
                generics
                    .loss_record
                    .iter()
                    .map(TypeDeclLossRecord::to_value)
                    .collect(),
            ),
        ),
        ("locus", locus.to_value()),
    ]);
    let canonical_bytes = jcs_bytes_of_value(&value);
    let cid = cid_of_value(&value);

    EnumDeclMemento {
        name,
        variants,
        generic_parameters: generics.parameters,
        where_bounds: generics.where_bounds,
        handling,
        loss_record: generics.loss_record,
        locus,
        canonical_bytes,
        cid,
    }
}

// ---- Trait ----

#[derive(Debug, Clone)]
pub struct MethodSignatureMemento {
    pub trait_name: String,
    pub method_name: String,
    pub formals: Vec<String>,
    pub formal_sorts: Vec<Sort>,
    pub return_sort: Sort,
    pub locus: Locus,
    pub canonical_bytes: Vec<u8>,
    pub cid: String,
}

#[derive(Debug, Clone)]
pub struct TraitMemento {
    pub name: String,
    pub method_signature_cids: Vec<String>,
    pub generic_parameters: Vec<GenericParameterMemento>,
    pub where_bounds: Vec<WhereBoundCitation>,
    pub handling: String,
    pub loss_record: Vec<TypeDeclLossRecord>,
    pub locus: Locus,
    pub canonical_bytes: Vec<u8>,
    pub cid: String,
}

pub fn lift_trait_decl(
    item: &ItemTrait,
    file_path: Option<&str>,
) -> (TraitMemento, Vec<MethodSignatureMemento>) {
    let trait_name = item.ident.to_string();
    let mut signatures = Vec::new();
    for trait_item in &item.items {
        if let syn::TraitItem::Fn(method) = trait_item {
            let method_name = method.sig.ident.to_string();
            let (formals, formal_sorts) = extract_formals_from_sig(&method.sig);
            let return_sort = match &method.sig.output {
                syn::ReturnType::Default => Sort::Primitive {
                    name: "Unit".to_string(),
                },
                syn::ReturnType::Type(_, ty) => infer_sort(ty),
            };
            let locus = Locus::from_span(method.sig.ident.span(), file_path);

            let formals_arr: Vec<Arc<Value>> =
                formals.iter().map(|n| Value::string(n.clone())).collect();
            let formal_sorts_arr: Vec<Arc<Value>> =
                formal_sorts.iter().map(sort_to_value).collect();
            let value = Value::object([
                ("schemaVersion", Value::string("1")),
                ("kind", Value::string("method-signature")),
                ("traitName", Value::string(trait_name.clone())),
                ("methodName", Value::string(method_name.clone())),
                ("formals", Value::array(formals_arr)),
                ("formalSorts", Value::array(formal_sorts_arr)),
                ("returnSort", sort_to_value(&return_sort)),
                ("locus", locus.to_value()),
            ]);
            let canonical_bytes = jcs_bytes_of_value(&value);
            let cid = cid_of_value(&value);

            signatures.push(MethodSignatureMemento {
                trait_name: trait_name.clone(),
                method_name,
                formals,
                formal_sorts,
                return_sort,
                locus,
                canonical_bytes,
                cid,
            });
        }
    }
    let trait_locus = Locus::from_span(item.ident.span(), file_path);
    let generics = generic_memento_parts(&item.generics);
    let handling = generics.handling();
    let sig_cids: Vec<Arc<Value>> = signatures
        .iter()
        .map(|s| Value::string(s.cid.clone()))
        .collect();
    let trait_value = Value::object([
        ("schemaVersion", Value::string("1")),
        ("kind", Value::string("trait")),
        ("name", Value::string(trait_name.clone())),
        ("methodSignatures", Value::array(sig_cids.clone())),
        (
            "genericParameters",
            Value::array(
                generics
                    .parameters
                    .iter()
                    .map(GenericParameterMemento::to_value)
                    .collect(),
            ),
        ),
        (
            "whereBounds",
            Value::array(
                generics
                    .where_bounds
                    .iter()
                    .map(WhereBoundCitation::to_value)
                    .collect(),
            ),
        ),
        ("handling", Value::string(handling.clone())),
        (
            "lossRecord",
            Value::array(
                generics
                    .loss_record
                    .iter()
                    .map(TypeDeclLossRecord::to_value)
                    .collect(),
            ),
        ),
        ("locus", trait_locus.to_value()),
    ]);
    let trait_bytes = jcs_bytes_of_value(&trait_value);
    let trait_cid = cid_of_value(&trait_value);

    (
        TraitMemento {
            name: trait_name,
            method_signature_cids: signatures.iter().map(|s| s.cid.clone()).collect(),
            generic_parameters: generics.parameters,
            where_bounds: generics.where_bounds,
            handling,
            loss_record: generics.loss_record,
            locus: trait_locus,
            canonical_bytes: trait_bytes,
            cid: trait_cid,
        },
        signatures,
    )
}

// ---- Impl block ----

#[derive(Debug, Clone)]
pub struct ImplMemento {
    pub target_type: String,
    pub trait_name: Option<String>,
    pub method_cids: Vec<String>,
    pub generic_parameters: Vec<GenericParameterMemento>,
    pub where_bounds: Vec<WhereBoundCitation>,
    pub handling: String,
    pub loss_record: Vec<TypeDeclLossRecord>,
    pub locus: Locus,
    pub canonical_bytes: Vec<u8>,
    pub cid: String,
}

pub fn lift_impl_block(
    item: &ItemImpl,
    file_path: Option<&str>,
) -> (ImplMemento, Vec<crate::contract::FunctionContractMemento>) {
    let target_type = type_name(&item.self_ty);
    let trait_name = item
        .trait_
        .as_ref()
        .and_then(|(_, path, _)| path.segments.last().map(|s| s.ident.to_string()));

    let mut methods = Vec::new();
    for impl_item in &item.items {
        if let syn::ImplItem::Fn(method) = impl_item {
            let synthetic = syn::ItemFn {
                attrs: method.attrs.clone(),
                vis: method.vis.clone(),
                sig: method.sig.clone(),
                block: Box::new(method.block.clone()),
            };
            let contract = build_function_contract_with_file(&synthetic, None, file_path);
            methods.push(contract);
        }
    }

    let locus = Locus::from_span(item.impl_token.span, file_path);
    let generics = generic_memento_parts(&item.generics);
    let handling = generics.handling();
    let method_cids: Vec<String> = methods.iter().map(|m| m.cid.clone()).collect();
    let method_cids_arr: Vec<Arc<Value>> = method_cids
        .iter()
        .map(|c| Value::string(c.clone()))
        .collect();
    let trait_value: Arc<Value> = match &trait_name {
        Some(t) => Value::string(t.clone()),
        None => Value::null(),
    };
    let value = Value::object([
        ("schemaVersion", Value::string("1")),
        ("kind", Value::string("impl")),
        ("targetType", Value::string(target_type.clone())),
        ("traitName", trait_value),
        ("methodCids", Value::array(method_cids_arr)),
        (
            "genericParameters",
            Value::array(
                generics
                    .parameters
                    .iter()
                    .map(GenericParameterMemento::to_value)
                    .collect(),
            ),
        ),
        (
            "whereBounds",
            Value::array(
                generics
                    .where_bounds
                    .iter()
                    .map(WhereBoundCitation::to_value)
                    .collect(),
            ),
        ),
        ("handling", Value::string(handling.clone())),
        (
            "lossRecord",
            Value::array(
                generics
                    .loss_record
                    .iter()
                    .map(TypeDeclLossRecord::to_value)
                    .collect(),
            ),
        ),
        ("locus", locus.to_value()),
    ]);
    let canonical_bytes = jcs_bytes_of_value(&value);
    let cid = cid_of_value(&value);

    (
        ImplMemento {
            target_type,
            trait_name,
            method_cids,
            generic_parameters: generics.parameters,
            where_bounds: generics.where_bounds,
            handling,
            loss_record: generics.loss_record,
            locus,
            canonical_bytes,
            cid,
        },
        methods,
    )
}

// ---- File-level dispatch ----

#[derive(Debug, Clone, Default)]
pub struct TypeDeclSet {
    pub structs: Vec<StructDeclMemento>,
    pub enums: Vec<EnumDeclMemento>,
    pub traits: Vec<TraitMemento>,
    pub method_signatures: Vec<MethodSignatureMemento>,
    pub impls: Vec<ImplMemento>,
    pub impl_methods: Vec<crate::contract::FunctionContractMemento>,
}

/// Walk a syn::File and extract every type declaration + impl block.
pub fn lift_file_type_decls(file: &File, file_path: Option<&str>) -> TypeDeclSet {
    let mut out = TypeDeclSet::default();
    for item in &file.items {
        match item {
            Item::Struct(s) => out.structs.push(lift_struct_decl(s, file_path)),
            Item::Enum(e) => out.enums.push(lift_enum_decl(e, file_path)),
            Item::Trait(t) => {
                let (trait_memento, sigs) = lift_trait_decl(t, file_path);
                out.traits.push(trait_memento);
                out.method_signatures.extend(sigs);
            }
            Item::Impl(i) => {
                let (impl_memento, methods) = lift_impl_block(i, file_path);
                out.impls.push(impl_memento);
                out.impl_methods.extend(methods);
            }
            Item::Const(_)
            | Item::ExternCrate(_)
            | Item::Fn(_)
            | Item::ForeignMod(_)
            | Item::Macro(_)
            | Item::Mod(_)
            | Item::Static(_)
            | Item::TraitAlias(_)
            | Item::Type(_)
            | Item::Union(_)
            | Item::Use(_)
            | Item::Verbatim(_) => {}
            _ => panic!("sugar-walk type_decl refused unknown syn::Item variant"),
        }
    }
    out
}

// ---- helpers ----

fn extract_formals_from_sig(sig: &syn::Signature) -> (Vec<String>, Vec<Sort>) {
    let mut names = Vec::new();
    let mut sorts = Vec::new();
    for input in &sig.inputs {
        match input {
            syn::FnArg::Receiver(_) => {
                names.push("self".to_string());
                sorts.push(Sort::Primitive {
                    name: "Self".to_string(),
                });
            }
            syn::FnArg::Typed(pt) => {
                let n = match &*pt.pat {
                    syn::Pat::Ident(p) => p.ident.to_string(),
                    _ => "<arg>".to_string(),
                };
                names.push(n);
                sorts.push(infer_sort(&pt.ty));
            }
        }
    }
    (names, sorts)
}

fn generic_memento_parts(generics: &syn::Generics) -> GenericMementoParts {
    let mut parts = GenericMementoParts::default();

    for param in &generics.params {
        match param {
            syn::GenericParam::Type(param) => {
                parts.parameters.push(GenericParameterMemento {
                    name: param.ident.to_string(),
                    kind: "type".to_string(),
                });
                if !param.bounds.is_empty() {
                    let predicate = format!(
                        "{} : {}",
                        param.ident,
                        param
                            .bounds
                            .iter()
                            .map(normalized_tokens)
                            .collect::<Vec<_>>()
                            .join(" + ")
                    );
                    push_where_bound(&mut parts, predicate, type_bounds_supported(&param.bounds));
                }
            }
            syn::GenericParam::Lifetime(param) => {
                parts.parameters.push(GenericParameterMemento {
                    name: param.lifetime.to_string(),
                    kind: "lifetime".to_string(),
                });
                if !param.bounds.is_empty() {
                    let predicate = format!(
                        "{} : {}",
                        param.lifetime,
                        param
                            .bounds
                            .iter()
                            .map(normalized_tokens)
                            .collect::<Vec<_>>()
                            .join(" + ")
                    );
                    push_where_bound(&mut parts, predicate, true);
                }
            }
            syn::GenericParam::Const(param) => {
                parts.parameters.push(GenericParameterMemento {
                    name: param.ident.to_string(),
                    kind: "const".to_string(),
                });
            }
        }
    }

    if let Some(where_clause) = &generics.where_clause {
        for predicate in &where_clause.predicates {
            let supported = where_predicate_supported(predicate);
            push_where_bound(&mut parts, normalized_tokens(predicate), supported);
        }
    }

    parts
}

fn push_where_bound(parts: &mut GenericMementoParts, predicate: String, supported: bool) {
    parts.where_bounds.push(WhereBoundCitation {
        concept: "concept:where-bound".to_string(),
        predicate: predicate.clone(),
    });
    if !supported {
        parts.loss_record.push(TypeDeclLossRecord {
            loss: LOSS_GENERICS_BOUNDS_NOT_DISCHARGED.to_string(),
            detail: predicate,
        });
    }
}

fn where_predicate_supported(predicate: &syn::WherePredicate) -> bool {
    match predicate {
        syn::WherePredicate::Lifetime(_) => true,
        syn::WherePredicate::Type(predicate) => type_bounds_supported(&predicate.bounds),
        _ => false,
    }
}

fn type_bounds_supported(
    bounds: &syn::punctuated::Punctuated<syn::TypeParamBound, syn::Token![+]>,
) -> bool {
    bounds.iter().all(type_bound_supported)
}

fn type_bound_supported(bound: &syn::TypeParamBound) -> bool {
    match bound {
        syn::TypeParamBound::Trait(bound) => trait_bound_supported(bound),
        syn::TypeParamBound::Lifetime(_) => true,
        syn::TypeParamBound::PreciseCapture(_) | syn::TypeParamBound::Verbatim(_) => false,
        _ => false,
    }
}

fn trait_bound_supported(bound: &syn::TraitBound) -> bool {
    bound.paren_token.is_none()
        && bound
            .path
            .segments
            .iter()
            .all(|segment| match &segment.arguments {
                syn::PathArguments::None => true,
                syn::PathArguments::AngleBracketed(args) => args.args.iter().all(|arg| {
                    matches!(
                        arg,
                        syn::GenericArgument::Lifetime(_) | syn::GenericArgument::Type(_)
                    )
                }),
                syn::PathArguments::Parenthesized(_) => false,
            })
}

fn normalized_tokens<T: ToTokens>(node: T) -> String {
    node.to_token_stream().to_string()
}

fn type_name(ty: &syn::Type) -> String {
    ty.to_token_stream().to_string().replace(' ', "")
}

fn infer_sort(ty: &syn::Type) -> Sort {
    crate::sort_translate::syn_type_to_sort(ty)
}

fn sort_to_value(s: &Sort) -> Arc<Value> {
    match s {
        Sort::Primitive { name } => Value::object([
            ("kind", Value::string("primitive")),
            ("name", Value::string(name.clone())),
        ]),
        // Function / Dependent sorts (added by #361) aren't yet
        // produced by the type_decl lifter - emit as opaque so the
        // type_decl canonical bytes stay valid when Sort variants
        // expand. Translating them faithfully is part of #384 A.1.
        Sort::Function { .. } | Sort::Dependent { .. } => Value::object([
            ("kind", Value::string("opaque")),
            (
                "reason",
                Value::string("function-or-dependent-sort-not-yet-modeled"),
            ),
        ]),
        // RegionSort (added by #401). Carry kind + name so type_decl CIDs
        // for lifetime-annotated fields are distinguishable from primitives.
        Sort::Region { name } => Value::object([
            ("kind", Value::string("region")),
            ("name", Value::string(name.clone())),
        ]),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse_file(src: &str) -> File {
        syn::parse_str(src).unwrap()
    }

    #[test]
    fn struct_decl_lifts_fields_with_sorts() {
        let f = parse_file(
            r#"
            struct Point { x: u32, y: u32 }
        "#,
        );
        let set = lift_file_type_decls(&f, Some("test.rs"));
        assert_eq!(set.structs.len(), 1);
        let p = &set.structs[0];
        assert_eq!(p.name, "Point");
        assert_eq!(p.fields.len(), 2);
        assert_eq!(p.fields[0].0, "x");
        assert_eq!(p.fields[1].0, "y");
        assert!(p.cid.starts_with("blake3-512:"));
    }

    #[test]
    fn enum_decl_lifts_variants_with_shapes() {
        let f = parse_file(
            r#"
            enum Color {
                Red,
                Green,
                Blue(u32),
                Custom { r: u32, g: u32, b: u32 },
            }
        "#,
        );
        let set = lift_file_type_decls(&f, Some("test.rs"));
        assert_eq!(set.enums.len(), 1);
        let c = &set.enums[0];
        assert_eq!(c.name, "Color");
        assert_eq!(c.variants.len(), 4);
        assert!(matches!(c.variants[0].shape, VariantShape::Unit));
        assert!(matches!(c.variants[2].shape, VariantShape::Tuple(_)));
        assert!(matches!(c.variants[3].shape, VariantShape::Struct(_)));
    }

    #[test]
    fn trait_decl_emits_method_signatures() {
        let f = parse_file(
            r#"
            trait Greet {
                fn hello(&self) -> u32;
                fn hello_with(&self, who: u32) -> u32;
            }
        "#,
        );
        let set = lift_file_type_decls(&f, Some("test.rs"));
        assert_eq!(set.traits.len(), 1);
        let t = &set.traits[0];
        assert_eq!(t.name, "Greet");
        assert_eq!(t.method_signature_cids.len(), 2);
        assert_eq!(set.method_signatures.len(), 2);
        assert_eq!(set.method_signatures[1].method_name, "hello_with");
        assert_eq!(set.method_signatures[1].formals.len(), 2); // self + who
    }

    #[test]
    fn impl_block_emits_method_contracts() {
        let f = parse_file(
            r#"
            struct Counter { n: u32 }
            impl Counter {
                fn double(self) -> u32 {
                    self.n * 2
                }
                fn add(&self, x: u32) -> u32 {
                    self.n + x
                }
            }
        "#,
        );
        let set = lift_file_type_decls(&f, Some("test.rs"));
        assert_eq!(set.impls.len(), 1);
        let i = &set.impls[0];
        assert_eq!(i.target_type, "Counter");
        assert!(i.trait_name.is_none());
        assert_eq!(i.method_cids.len(), 2);
        assert_eq!(set.impl_methods.len(), 2);
        // Each impl method emits a function contract memento.
        assert_eq!(set.impl_methods[0].fn_name, "double");
        assert_eq!(set.impl_methods[1].fn_name, "add");
    }

    #[test]
    fn impl_for_trait_records_trait_name() {
        let f = parse_file(
            r#"
            trait Greet { fn hello(&self) -> u32; }
            struct Foo;
            impl Greet for Foo {
                fn hello(&self) -> u32 { 42 }
            }
        "#,
        );
        let set = lift_file_type_decls(&f, Some("test.rs"));
        assert_eq!(set.impls.len(), 1);
        assert_eq!(set.impls[0].target_type, "Foo");
        assert_eq!(set.impls[0].trait_name.as_deref(), Some("Greet"));
    }

    #[test]
    fn cids_are_deterministic_and_self_identifying() {
        let f = parse_file(
            r#"
            struct P { x: u32 }
            enum E { A, B(u32) }
            trait T { fn f(&self) -> u32; }
            impl T for P { fn f(&self) -> u32 { self.x } }
        "#,
        );
        let set_a = lift_file_type_decls(&f, Some("test.rs"));
        let set_b = lift_file_type_decls(&f, Some("test.rs"));
        for (a, b) in set_a.structs.iter().zip(set_b.structs.iter()) {
            assert_eq!(a.cid, b.cid);
            assert!(a.cid.starts_with("blake3-512:"));
            assert_eq!(a.cid.len(), 139);
        }
        for (a, b) in set_a.enums.iter().zip(set_b.enums.iter()) {
            assert_eq!(a.cid, b.cid);
        }
        for (a, b) in set_a.traits.iter().zip(set_b.traits.iter()) {
            assert_eq!(a.cid, b.cid);
        }
        for (a, b) in set_a.impls.iter().zip(set_b.impls.iter()) {
            assert_eq!(a.cid, b.cid);
        }
    }

    // ---- Bug #384 A.1: struct-field sort-collapse regression tests ----

    /// struct A { x: Vec<u32> } and struct A { x: SomeStruct } must produce
    /// DISTINCT struct-decl CIDs. This was the false-collision from the old
    /// infer_sort that collapsed every non-primitive type to "Int".
    #[test]
    fn struct_with_vec_field_distinct_from_struct_with_user_type_field() {
        let f_vec = parse_file(r#"struct A { x: Vec<u32> }"#);
        let f_user = parse_file(r#"struct A { x: SomeStruct }"#);
        let set_vec = lift_file_type_decls(&f_vec, Some("test.rs"));
        let set_user = lift_file_type_decls(&f_user, Some("test.rs"));
        assert_eq!(set_vec.structs.len(), 1);
        assert_eq!(set_user.structs.len(), 1);
        assert_ne!(
            set_vec.structs[0].cid, set_user.structs[0].cid,
            "struct A {{ x: Vec<u32> }} and struct A {{ x: SomeStruct }} must have distinct CIDs"
        );
        assert_ne!(
            set_vec.structs[0].fields[0].1, set_user.structs[0].fields[0].1,
            "Vec<u32> and SomeStruct field sorts must be distinct"
        );
    }

    /// struct A { x: u32 } and struct A { x: bool } must produce distinct CIDs.
    #[test]
    fn struct_with_u32_field_distinct_from_bool_field() {
        let f_u32 = parse_file(r#"struct A { x: u32 }"#);
        let f_bool = parse_file(r#"struct A { x: bool }"#);
        let set_u32 = lift_file_type_decls(&f_u32, Some("test.rs"));
        let set_bool = lift_file_type_decls(&f_bool, Some("test.rs"));
        assert_ne!(set_u32.structs[0].cid, set_bool.structs[0].cid);
    }
}

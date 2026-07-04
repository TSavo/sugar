// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Emit the shadow source as a v1.5.0-shape proof.ir bundle.
//
// The bundle is a single JCS-canonical JSON document containing:
//   - schemaVersion: "sugar-walk/1"
//   - shadowSourceCid: top-level CID for the shadow source
//   - shadowSource: the canonical shadow-source bytes (decoded back to a
//     JSON object so consumers can inspect without re-canonicalizing)
//   - arrivals: array of every shadow arrival's edge memento, each
//     shaped as ContractDecl per paper 07 §11
//   - composedChain: optional flat composed edge for the longest chain
//
// This is the "from source to substrate" wire-format gap closed: feed
// any Rust source into walk_demo and out the other side comes a single
// JCS+BLAKE3-addressed bundle that downstream substrate tools (lift,
// linker, mint) can consume.

use std::{
    cell::RefCell,
    collections::{HashMap, HashSet},
    rc::Rc,
    sync::Arc,
};

use quote::ToTokens;
use serde_json::{json, Value as JsonValue};
use sugar_canonicalizer::{blake3_512_of, Value};
use sugar_floor_algebra::{Effect, Outcome, RaiseEffect, RouteRaisesOperation};
use syn::parse::Parser;
use syn::{BinOp, Expr, ExprIf, Lit, Meta, ReturnType, Stmt, Type, UnOp};

use crate::canonical::{cid_of_value, jcs_bytes_of_value, serde_to_canonical};
use crate::shadow::{compose_chain, edge_memento_value, ShadowSource};
use crate::signature::{op_cid, RUST_LANGUAGE_SIGNATURE_CID};

/// Emit a single proof.ir bundle for the given shadow source.
/// Returns JCS-canonical bytes ready for write or transmit. The bundle's
/// own CID is included inline.
pub fn shadow_to_proof_ir(s: &ShadowSource) -> Vec<u8> {
    let bundle = build_bundle_value(s);
    jcs_bytes_of_value(&bundle)
}

/// CID of the proof.ir bundle.
pub fn shadow_proof_ir_cid(s: &ShadowSource) -> String {
    let bundle = build_bundle_value(s);
    cid_of_value(&bundle)
}

/// Emit a Rust algebra term over the minted rust:rust signature.
pub fn rust_function_term_json(
    item_fn: &syn::ItemFn,
    source: impl Into<String>,
) -> Result<Vec<u8>, String> {
    let value = rust_function_term_json_value_with_context(
        item_fn,
        source,
        Vec::new(),
        HashMap::new(),
        Vec::new(),
    )?;
    let canonical = serde_to_canonical(value);
    Ok(jcs_bytes_of_value(&canonical))
}

/// Emit a Rust algebra term for a function found inside a parsed source file.
///
/// D3 accepted-loss classes include context that a bare `syn::ItemFn` cannot
/// carry, such as associated types on a containing impl block. This entrypoint
/// also preserves source-visible derive and attribute macro invocations as
/// first-class concept operations.
pub fn rust_function_term_json_for_file(
    file: &syn::File,
    function_name: &str,
    source: impl Into<String>,
) -> Result<Vec<u8>, String> {
    let target = find_term_function(file, function_name)
        .ok_or_else(|| format!("function `{function_name}` not found"))?;
    let value = rust_function_term_json_value_with_context(
        &target.item_fn,
        source.into(),
        target.contextual_losses,
        target.ffi_declarations,
        target.contextual_proc_macro_invocations,
    )?;
    let canonical = serde_to_canonical(value);
    Ok(jcs_bytes_of_value(&canonical))
}

/// CID of the emitted Rust algebra term JSON document.
pub fn rust_function_term_json_cid(
    item_fn: &syn::ItemFn,
    source: impl Into<String>,
) -> Result<String, String> {
    let value = rust_function_term_json_value_with_context(
        item_fn,
        source,
        Vec::new(),
        HashMap::new(),
        Vec::new(),
    )?;
    let canonical = serde_to_canonical(value);
    Ok(cid_of_value(&canonical))
}

/// CID of the file-aware emitted Rust algebra term JSON document.
pub fn rust_function_term_json_cid_for_file(
    file: &syn::File,
    function_name: &str,
    source: impl Into<String>,
) -> Result<String, String> {
    let target = find_term_function(file, function_name)
        .ok_or_else(|| format!("function `{function_name}` not found"))?;
    let value = rust_function_term_json_value_with_context(
        &target.item_fn,
        source.into(),
        target.contextual_losses,
        target.ffi_declarations,
        target.contextual_proc_macro_invocations,
    )?;
    let canonical = serde_to_canonical(value);
    Ok(cid_of_value(&canonical))
}

/// Build the inspectable JSON value before JCS encoding.
pub fn rust_function_term_json_value(
    item_fn: &syn::ItemFn,
    source: impl Into<String>,
) -> Result<JsonValue, String> {
    rust_function_term_json_value_with_context(
        item_fn,
        source,
        Vec::new(),
        HashMap::new(),
        Vec::new(),
    )
}

fn rust_function_term_json_value_with_context(
    item_fn: &syn::ItemFn,
    source: impl Into<String>,
    contextual_losses: Vec<LossRecord>,
    ffi_declarations: HashMap<String, FfiDeclaration>,
    contextual_proc_macro_invocations: Vec<ProcMacroInvocation>,
) -> Result<JsonValue, String> {
    let source = source.into();
    let ctx = LoweringContext::from_item_fn_with_context(
        item_fn,
        contextual_losses,
        ffi_declarations,
        source.clone(),
    );
    let mut proc_macro_invocations = Vec::new();
    for invocation in contextual_proc_macro_invocations {
        push_proc_macro_invocation(&mut proc_macro_invocations, invocation);
    }
    for invocation in proc_macro_invocations_for_attrs(&item_fn.attrs) {
        push_proc_macro_invocation(&mut proc_macro_invocations, invocation);
    }
    let term = match lower_function_body_to_term(item_fn, &ctx) {
        Ok(term) => term,
        Err(_) if ctx.allows_accepted_loss_placeholder() => AlgebraTerm::skip(),
        Err(err) => return Err(err),
    };
    let term_surface = term.surface();
    let loss_record = ctx.loss_record_json();
    let effect_occurrences = ctx.effect_occurrences_json();
    let handling = if loss_record.is_empty() {
        "handles-fully"
    } else {
        "handles-partially-with-loss-record"
    };
    Ok(json!({
        "kind": "rust-algebra-term",
        "signature_cid": RUST_LANGUAGE_SIGNATURE_CID,
        "source": source,
        "handling": handling,
        "effect_occurrences": effect_occurrences,
        "loss_record": loss_record,
        "return_sort": ctx.return_shape.return_sort_json(),
        "proc_macro_invocations": proc_macro_invocations
            .iter()
            .map(ProcMacroInvocation::to_json)
            .collect::<Vec<_>>(),
        "term_surface": term_surface,
        "term": term.to_json()?,
    }))
}

/// Universal op for a source-visible procedural macro invocation.
const PROC_MACRO_INVOCATION_CONCEPT: &str = "concept:proc-macro-invocation";

/// Typed subcase for Rust derive attributes.
const DERIVE_ATTRIBUTE_CONCEPT: &str = "concept:derive-attribute";

/// Accepted-loss dimension for associated type declarations on impl blocks
/// that are not carried into the emitted function term.
const LOSS_IMPL_ASSOCIATED_TYPE_NOT_LOWERED: &str = "impl-associated-type-not-lowered";

/// Accepted-loss dimension for Rust ABI annotations such as `extern "C"` that
/// are parsed on a function signature but not represented in the term.
const LOSS_ABI_ATTRIBUTE_NOT_CARRIED: &str = "abi-attribute-not-carried";

/// Accepted-loss dimension for `let mut` bindings whose mutability marker is
/// not represented in the let pattern term.
const LOSS_LET_BINDING_MUTABILITY: &str = "let-binding-mutability";

/// Accepted-loss dimension for boolean `let` expressions whose pattern test is
/// kept but whose binding semantics are not fully represented during bootstrap.
const LOSS_D4_EXPR_LET: &str = "Expr::Let";

/// Accepted-loss dimension for Rust macro invocations that are recorded without
/// expanding their token streams.
const LOSS_MACRO_NOT_EXPANDED: &str = "macro-not-expanded";

const RUST_UNRESOLVED_CALL_EFFECT_SIGNATURE_CID: &str = "blake3-512:2d368ad6123c2617a938deb71b7094a20cecfa6229909dad7c1d368aa0f931ed9bd2ff4bbf497962f8cdf104ddda56050275e6ee4a2998ce3d75b36925c362cf";

#[derive(Debug, Clone, PartialEq, Eq)]
enum AlgebraTerm {
    Op {
        name: String,
        args: Vec<AlgebraTerm>,
    },
    Var(String),
    FullyQualifiedPath(String),
    Symbol(String),
    List(Vec<AlgebraTerm>),
    Struct {
        name: String,
        fields: Vec<(String, AlgebraTerm)>,
    },
    ConstInt(i64),
    ConstBool(bool),
    Unit,
}

impl AlgebraTerm {
    fn op(name: impl Into<String>, args: Vec<AlgebraTerm>) -> Self {
        Self::Op {
            name: name.into(),
            args,
        }
    }

    fn skip() -> Self {
        Self::op("skip", vec![Self::Unit])
    }

    fn to_json(&self) -> Result<JsonValue, String> {
        match self {
            AlgebraTerm::Op { name, args } => {
                let Some(cid) = op_cid(name) else {
                    return Err(format!("operation `{name}` is not in the Rust signature"));
                };
                let args = args
                    .iter()
                    .map(AlgebraTerm::to_json)
                    .collect::<Result<Vec<_>, _>>()?;
                Ok(json!({
                    "kind": "op",
                    "name": name,
                    "op_cid": cid,
                    "args": args,
                }))
            }
            AlgebraTerm::Var(name) => Ok(json!({"kind": "var", "name": name})),
            AlgebraTerm::FullyQualifiedPath(path) => Ok(json!({
                "concept": "concept:fully-qualified-path",
                "kind": "fully-qualified-path",
                "path": path,
            })),
            AlgebraTerm::Symbol(name) => Ok(json!({"kind": "symbol", "name": name})),
            AlgebraTerm::List(items) => {
                let items = items
                    .iter()
                    .map(AlgebraTerm::to_json)
                    .collect::<Result<Vec<_>, _>>()?;
                Ok(json!({"kind": "list", "items": items}))
            }
            AlgebraTerm::Struct { name, fields } => {
                let fields = fields
                    .iter()
                    .map(|(field, value)| {
                        Ok(json!({
                            "name": field,
                            "value": value.to_json()?,
                        }))
                    })
                    .collect::<Result<Vec<_>, String>>()?;
                Ok(json!({
                    "kind": "struct",
                    "name": name,
                    "fields": fields,
                }))
            }
            AlgebraTerm::ConstInt(value) => Ok(json!({
                "kind": "const",
                "value": value,
                "sort": {"kind": "ctor", "name": "Int", "args": []}
            })),
            AlgebraTerm::ConstBool(value) => Ok(json!({
                "kind": "const",
                "value": value,
                "sort": {"kind": "ctor", "name": "Bool", "args": []}
            })),
            AlgebraTerm::Unit => Ok(json!({"kind": "unit"})),
        }
    }

    fn surface(&self) -> String {
        match self {
            AlgebraTerm::Op { name, args }
                if name == "skip" && matches!(args.as_slice(), [AlgebraTerm::Unit]) =>
            {
                "skip".to_string()
            }
            AlgebraTerm::Op { name, args } => {
                let args = args
                    .iter()
                    .map(AlgebraTerm::surface)
                    .collect::<Vec<_>>()
                    .join(", ");
                format!("{name}({args})")
            }
            AlgebraTerm::Var(name) => name.clone(),
            AlgebraTerm::FullyQualifiedPath(path) => path.clone(),
            AlgebraTerm::Symbol(name) => name.clone(),
            AlgebraTerm::List(items) => {
                let items = items
                    .iter()
                    .map(AlgebraTerm::surface)
                    .collect::<Vec<_>>()
                    .join(", ");
                format!("[{items}]")
            }
            AlgebraTerm::Struct { name, fields } => {
                let fields = fields
                    .iter()
                    .map(|(field, value)| format!("{field}: {}", value.surface()))
                    .collect::<Vec<_>>()
                    .join(", ");
                format!("{name}{{{fields}}}")
            }
            AlgebraTerm::ConstInt(value) => value.to_string(),
            AlgebraTerm::ConstBool(value) => value.to_string(),
            AlgebraTerm::Unit => "unit".to_string(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ExprSort {
    Bool,
    Int,
    Unit,
}

impl ExprSort {
    fn name(self) -> &'static str {
        match self {
            ExprSort::Bool => "Bool",
            ExprSort::Int => "Int",
            ExprSort::Unit => "Unit",
        }
    }

    fn concept_sort(self) -> ConceptSort {
        ConceptSort::new(self.name(), Vec::new())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct ConceptSort {
    name: String,
    args: Vec<ConceptSort>,
}

impl ConceptSort {
    fn new(name: impl Into<String>, args: Vec<ConceptSort>) -> Self {
        Self {
            name: name.into(),
            args,
        }
    }

    fn to_json(&self) -> JsonValue {
        json!({
            "kind": "ctor",
            "name": self.name,
            "args": self.args.iter().map(ConceptSort::to_json).collect::<Vec<_>>(),
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum ReturnShape {
    Full(ExprSort),
    Partial {
        loss: &'static str,
        rust_type: String,
        return_sort: ConceptSort,
    },
    SortOnly(ConceptSort),
    Unsupported,
}

impl ReturnShape {
    fn sort(&self) -> Option<ExprSort> {
        match self {
            ReturnShape::Full(sort) => Some(*sort),
            ReturnShape::Partial { .. } | ReturnShape::SortOnly(_) | ReturnShape::Unsupported => {
                None
            }
        }
    }

    fn return_sort_json(&self) -> JsonValue {
        match self {
            ReturnShape::Full(sort) => sort.concept_sort().to_json(),
            ReturnShape::Partial { return_sort, .. } | ReturnShape::SortOnly(return_sort) => {
                return_sort.to_json()
            }
            ReturnShape::Unsupported => JsonValue::Null,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct LossRecord {
    loss: &'static str,
    detail: String,
}

#[derive(Debug, Clone, PartialEq)]
struct EffectOccurrenceRecord {
    args: JsonValue,
    discharge_key: String,
    locator: JsonValue,
    occurrence_kind: &'static str,
    role: &'static str,
    signature_cid: &'static str,
}

#[derive(Debug, Clone)]
struct FfiDeclaration {
    abi: String,
    binding: String,
    symbol: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct ProcMacroInvocation {
    operator: &'static str,
    macro_path: String,
    macro_cid: String,
    args: Vec<JsonValue>,
    token_stream: String,
}

impl ProcMacroInvocation {
    fn to_json(&self) -> JsonValue {
        json!({
            "kind": "concept:op-application",
            "op_cid": local_op_definition_cid(self.operator),
            "macro_cid": self.macro_cid,
            "macro_path": self.macro_path,
            "args": self.args,
            "token_stream": self.token_stream,
        })
    }
}

#[derive(Debug, Clone)]
struct LoweringContext {
    return_shape: ReturnShape,
    source: String,
    vars: HashMap<String, ExprSort>,
    mutable_vars: HashSet<String>,
    ssa_aliases: HashMap<String, String>,
    ssa_versions: HashMap<String, usize>,
    ffi_declarations: HashMap<String, FfiDeclaration>,
    losses: Rc<RefCell<Vec<LossRecord>>>,
    effect_occurrences: Rc<RefCell<Vec<EffectOccurrenceRecord>>>,
}

impl LoweringContext {
    fn from_item_fn_with_context(
        item_fn: &syn::ItemFn,
        contextual_losses: Vec<LossRecord>,
        ffi_declarations: HashMap<String, FfiDeclaration>,
        source: String,
    ) -> Self {
        let mut vars = HashMap::new();
        let mut mutable_vars = HashSet::new();
        for arg in &item_fn.sig.inputs {
            let syn::FnArg::Typed(pat_type) = arg else {
                continue;
            };
            let syn::Pat::Ident(ident) = &*pat_type.pat else {
                continue;
            };
            let name = ident.ident.to_string();
            if let Some(sort) = sort_from_type(&pat_type.ty) {
                vars.insert(name.clone(), sort);
            }
            if ident.mutability.is_some() {
                mutable_vars.insert(name);
            }
        }
        let losses = Rc::new(RefCell::new(Vec::new()));
        let effect_occurrences = Rc::new(RefCell::new(Vec::new()));
        for loss in contextual_losses {
            push_loss(&losses, loss);
        }
        if let Some(abi) = &item_fn.sig.abi {
            push_loss(
                &losses,
                LossRecord {
                    loss: LOSS_ABI_ATTRIBUTE_NOT_CARRIED,
                    detail: abi.to_token_stream().to_string(),
                },
            );
        }
        let return_shape = return_shape_from_return_type(&item_fn.sig.output);
        if let ReturnShape::Partial {
            loss, rust_type, ..
        } = &return_shape
        {
            push_loss(
                &losses,
                LossRecord {
                    loss,
                    detail: rust_type.clone(),
                },
            );
        }
        Self {
            return_shape,
            source,
            vars,
            mutable_vars,
            ssa_aliases: HashMap::new(),
            ssa_versions: HashMap::new(),
            ffi_declarations,
            losses,
            effect_occurrences,
        }
    }

    fn with_var(&self, name: impl Into<String>, sort: Option<ExprSort>) -> Self {
        self.with_local_var(name, sort, false)
    }

    fn with_local_var(
        &self,
        name: impl Into<String>,
        sort: Option<ExprSort>,
        is_mutable: bool,
    ) -> Self {
        let name = name.into();
        let mut vars = self.vars.clone();
        if let Some(sort) = sort {
            vars.insert(name.clone(), sort);
        }
        let mut mutable_vars = self.mutable_vars.clone();
        if is_mutable {
            mutable_vars.insert(name.clone());
        } else {
            mutable_vars.remove(&name);
        }
        let mut ssa_aliases = self.ssa_aliases.clone();
        ssa_aliases.remove(&name);
        let mut ssa_versions = self.ssa_versions.clone();
        ssa_versions.remove(&name);
        Self {
            return_shape: self.return_shape.clone(),
            source: self.source.clone(),
            vars,
            mutable_vars,
            ssa_aliases,
            ssa_versions,
            ffi_declarations: self.ffi_declarations.clone(),
            losses: Rc::clone(&self.losses),
            effect_occurrences: Rc::clone(&self.effect_occurrences),
        }
    }

    fn current_name(&self, source_name: &str) -> String {
        self.ssa_aliases
            .get(source_name)
            .cloned()
            .unwrap_or_else(|| source_name.to_string())
    }

    fn is_mutable_source(&self, source_name: &str) -> bool {
        self.mutable_vars.contains(source_name)
    }

    fn with_ssa_rebinding(&self, source_name: &str) -> (String, Self) {
        let current_name = self.current_name(source_name);
        let next_version = match self.ssa_versions.get(source_name).copied() {
            Some(version) => version,
            None => 0,
        } + 1;
        let rebound_name = format!("{source_name}_v{next_version}");
        let mut vars = self.vars.clone();
        if let Some(sort) = self
            .vars
            .get(&current_name)
            .copied()
            .or_else(|| self.vars.get(source_name).copied())
        {
            vars.insert(rebound_name.clone(), sort);
        }
        let mut mutable_vars = self.mutable_vars.clone();
        if mutable_vars.contains(source_name) {
            mutable_vars.insert(rebound_name.clone());
        }
        let mut ssa_aliases = self.ssa_aliases.clone();
        ssa_aliases.insert(source_name.to_string(), rebound_name.clone());
        let mut ssa_versions = self.ssa_versions.clone();
        ssa_versions.insert(source_name.to_string(), next_version);
        let ctx = Self {
            return_shape: self.return_shape.clone(),
            source: self.source.clone(),
            vars,
            mutable_vars,
            ssa_aliases,
            ssa_versions,
            ffi_declarations: self.ffi_declarations.clone(),
            losses: Rc::clone(&self.losses),
            effect_occurrences: Rc::clone(&self.effect_occurrences),
        };
        (rebound_name, ctx)
    }

    fn add_loss(&self, loss: &'static str, detail: impl Into<String>) {
        push_loss(
            &self.losses,
            LossRecord {
                loss,
                detail: detail.into(),
            },
        );
    }

    fn loss_record_json(&self) -> Vec<JsonValue> {
        self.losses
            .borrow()
            .iter()
            .map(|record| {
                json!({
                    "loss": record.loss,
                    "detail": record.detail,
                })
            })
            .collect()
    }

    fn add_ffi_call_effect_occurrence(&self, declaration: &FfiDeclaration) {
        let occurrence = EffectOccurrenceRecord {
            args: json!({
                "name": declaration.symbol.clone(),
            }),
            discharge_key: format!("unresolved-call:{}", declaration.symbol),
            locator: json!({
                "abi": declaration.abi.clone(),
                "binding": declaration.binding.clone(),
                "file": self.source.clone(),
                "source": "extern",
            }),
            occurrence_kind: "UnresolvedCall",
            role: "body",
            signature_cid: RUST_UNRESOLVED_CALL_EFFECT_SIGNATURE_CID,
        };
        push_effect_occurrence(&self.effect_occurrences, occurrence);
    }

    fn ffi_declaration(&self, callee: &str) -> Option<FfiDeclaration> {
        self.ffi_declarations.get(callee).cloned()
    }

    fn effect_occurrences_json(&self) -> Vec<JsonValue> {
        self.effect_occurrences
            .borrow()
            .iter()
            .map(|record| {
                json!({
                    "args": record.args.clone(),
                    "discharge_key": record.discharge_key.clone(),
                    "locator": record.locator.clone(),
                    "occurrence_kind": record.occurrence_kind,
                    "role": record.role,
                    "signature_cid": record.signature_cid,
                })
            })
            .collect()
    }

    fn has_loss(&self, loss: &'static str) -> bool {
        self.losses
            .borrow()
            .iter()
            .any(|record| record.loss == loss)
    }

    fn allows_accepted_loss_placeholder(&self) -> bool {
        self.has_loss(LOSS_ABI_ATTRIBUTE_NOT_CARRIED)
            || self.has_loss(LOSS_IMPL_ASSOCIATED_TYPE_NOT_LOWERED)
    }
}

fn push_loss(losses: &Rc<RefCell<Vec<LossRecord>>>, loss: LossRecord) {
    let mut losses = losses.borrow_mut();
    if !losses
        .iter()
        .any(|record| record.loss == loss.loss && record.detail == loss.detail)
    {
        losses.push(loss);
    }
}

fn push_effect_occurrence(
    effect_occurrences: &Rc<RefCell<Vec<EffectOccurrenceRecord>>>,
    occurrence: EffectOccurrenceRecord,
) {
    let mut effect_occurrences = effect_occurrences.borrow_mut();
    if !effect_occurrences
        .iter()
        .any(|record| record == &occurrence)
    {
        effect_occurrences.push(occurrence);
    }
}

struct TermFunctionContext {
    item_fn: syn::ItemFn,
    contextual_losses: Vec<LossRecord>,
    ffi_declarations: HashMap<String, FfiDeclaration>,
    contextual_proc_macro_invocations: Vec<ProcMacroInvocation>,
}

fn find_term_function(file: &syn::File, name: &str) -> Option<TermFunctionContext> {
    let ffi_declarations = ffi_declarations_for_file(file);
    let file_proc_macro_invocations = proc_macro_invocations_for_file(file);
    find_term_function_in_items(
        &file.items,
        name,
        &[],
        &ffi_declarations,
        &file_proc_macro_invocations,
    )
}

fn find_term_function_in_items(
    items: &[syn::Item],
    name: &str,
    inherited_losses: &[LossRecord],
    ffi_declarations: &HashMap<String, FfiDeclaration>,
    inherited_proc_macro_invocations: &[ProcMacroInvocation],
) -> Option<TermFunctionContext> {
    for item in items {
        match item {
            syn::Item::Fn(item_fn) if item_fn.sig.ident == name => {
                return Some(TermFunctionContext {
                    item_fn: item_fn.clone(),
                    contextual_losses: inherited_losses.to_vec(),
                    ffi_declarations: ffi_declarations.clone(),
                    contextual_proc_macro_invocations: inherited_proc_macro_invocations.to_vec(),
                });
            }
            syn::Item::Impl(impl_block) => {
                let mut impl_losses = inherited_losses.to_vec();
                if impl_block
                    .items
                    .iter()
                    .any(|item| matches!(item, syn::ImplItem::Type(_)))
                {
                    impl_losses.push(LossRecord {
                        loss: LOSS_IMPL_ASSOCIATED_TYPE_NOT_LOWERED,
                        detail: impl_block.self_ty.to_token_stream().to_string(),
                    });
                }
                for impl_item in &impl_block.items {
                    if let syn::ImplItem::Fn(method) = impl_item {
                        if method.sig.ident == name {
                            return Some(TermFunctionContext {
                                item_fn: syn::ItemFn {
                                    attrs: method.attrs.clone(),
                                    vis: method.vis.clone(),
                                    sig: method.sig.clone(),
                                    block: Box::new(method.block.clone()),
                                },
                                contextual_losses: impl_losses,
                                ffi_declarations: ffi_declarations.clone(),
                                contextual_proc_macro_invocations: inherited_proc_macro_invocations
                                    .to_vec(),
                            });
                        }
                    }
                }
            }
            syn::Item::Mod(module) => {
                if let Some((_, nested_items)) = &module.content {
                    if let Some(found) = find_term_function_in_items(
                        nested_items,
                        name,
                        inherited_losses,
                        ffi_declarations,
                        inherited_proc_macro_invocations,
                    ) {
                        return Some(found);
                    }
                }
            }
            syn::Item::Const(_)
            | syn::Item::Enum(_)
            | syn::Item::ExternCrate(_)
            | syn::Item::ForeignMod(_)
            | syn::Item::Fn(_)
            | syn::Item::Macro(_)
            | syn::Item::Static(_)
            | syn::Item::Struct(_)
            | syn::Item::Trait(_)
            | syn::Item::TraitAlias(_)
            | syn::Item::Type(_)
            | syn::Item::Union(_)
            | syn::Item::Use(_)
            | syn::Item::Verbatim(_) => {}
            _ => panic!("sugar-walk emit find_term_function refused unknown syn::Item variant"),
        }
    }
    None
}

fn ffi_declarations_for_file(file: &syn::File) -> HashMap<String, FfiDeclaration> {
    let mut declarations = HashMap::new();
    collect_ffi_declarations_in_items(&file.items, &mut Vec::new(), &mut declarations);
    declarations
}

fn collect_ffi_declarations_in_items(
    items: &[syn::Item],
    module_path: &mut Vec<String>,
    declarations: &mut HashMap<String, FfiDeclaration>,
) {
    for item in items {
        match item {
            syn::Item::ForeignMod(foreign_mod) => {
                let abi = foreign_mod
                    .abi
                    .name
                    .as_ref()
                    .map(|name| name.value())
                    .unwrap_or_else(|| "Rust".to_string());
                for foreign_item in &foreign_mod.items {
                    let syn::ForeignItem::Fn(foreign_fn) = foreign_item else {
                        continue;
                    };
                    let binding = foreign_fn.sig.ident.to_string();
                    let symbol =
                        link_name_from_attrs(&foreign_fn.attrs).unwrap_or_else(|| binding.clone());
                    let declaration = FfiDeclaration {
                        abi: abi.clone(),
                        binding: binding.clone(),
                        symbol,
                    };
                    declarations.insert(binding.clone(), declaration.clone());
                    if !module_path.is_empty() {
                        let mut qualified = module_path.join("::");
                        qualified.push_str("::");
                        qualified.push_str(&binding);
                        declarations.insert(qualified, declaration);
                    }
                }
            }
            syn::Item::Mod(module) => {
                if let Some((_, nested_items)) = &module.content {
                    module_path.push(module.ident.to_string());
                    collect_ffi_declarations_in_items(nested_items, module_path, declarations);
                    module_path.pop();
                }
            }
            syn::Item::Const(_)
            | syn::Item::Enum(_)
            | syn::Item::ExternCrate(_)
            | syn::Item::Fn(_)
            | syn::Item::Impl(_)
            | syn::Item::Macro(_)
            | syn::Item::Static(_)
            | syn::Item::Struct(_)
            | syn::Item::Trait(_)
            | syn::Item::TraitAlias(_)
            | syn::Item::Type(_)
            | syn::Item::Union(_)
            | syn::Item::Use(_)
            | syn::Item::Verbatim(_) => {}
            _ => panic!("sugar-walk emit ffi collector refused unknown syn::Item variant"),
        }
    }
}

fn link_name_from_attrs(attrs: &[syn::Attribute]) -> Option<String> {
    attrs.iter().find_map(|attr| {
        if !attr.path().is_ident("link_name") {
            return None;
        }
        let syn::Meta::NameValue(name_value) = &attr.meta else {
            return None;
        };
        let Expr::Lit(expr_lit) = &name_value.value else {
            return None;
        };
        let Lit::Str(lit) = &expr_lit.lit else {
            return None;
        };
        Some(lit.value())
    })
}

fn proc_macro_invocations_for_file(file: &syn::File) -> Vec<ProcMacroInvocation> {
    let mut invocations = Vec::new();
    for item in &file.items {
        collect_proc_macro_invocations_from_item(item, &mut invocations);
    }
    invocations
}

fn collect_proc_macro_invocations_from_item(
    item: &syn::Item,
    invocations: &mut Vec<ProcMacroInvocation>,
) {
    let attrs: &[syn::Attribute] = match item {
        syn::Item::Const(item) => &item.attrs,
        syn::Item::Enum(item) => &item.attrs,
        syn::Item::Fn(item) => &item.attrs,
        syn::Item::Impl(item) => {
            extend_proc_macro_invocations(invocations, &item.attrs);
            for impl_item in &item.items {
                match impl_item {
                    syn::ImplItem::Const(item) => {
                        extend_proc_macro_invocations(invocations, &item.attrs)
                    }
                    syn::ImplItem::Fn(item) => {
                        extend_proc_macro_invocations(invocations, &item.attrs)
                    }
                    syn::ImplItem::Type(item) => {
                        extend_proc_macro_invocations(invocations, &item.attrs)
                    }
                    syn::ImplItem::Macro(_) | syn::ImplItem::Verbatim(_) => {}
                    _ => panic!(
                        "sugar-walk emit proc-macro collector refused unknown syn::ImplItem variant"
                    ),
                }
            }
            return;
        }
        syn::Item::Mod(item) => {
            extend_proc_macro_invocations(invocations, &item.attrs);
            if let Some((_, items)) = &item.content {
                for item in items {
                    collect_proc_macro_invocations_from_item(item, invocations);
                }
            }
            return;
        }
        syn::Item::Struct(item) => &item.attrs,
        syn::Item::Trait(item) => &item.attrs,
        syn::Item::Type(item) => &item.attrs,
        syn::Item::Union(item) => &item.attrs,
        syn::Item::ExternCrate(_)
        | syn::Item::ForeignMod(_)
        | syn::Item::Macro(_)
        | syn::Item::Static(_)
        | syn::Item::TraitAlias(_)
        | syn::Item::Use(_)
        | syn::Item::Verbatim(_) => &[],
        _ => panic!("sugar-walk emit proc-macro collector refused unknown syn::Item variant"),
    };
    extend_proc_macro_invocations(invocations, attrs);
}

fn extend_proc_macro_invocations(
    invocations: &mut Vec<ProcMacroInvocation>,
    attrs: &[syn::Attribute],
) {
    for invocation in proc_macro_invocations_for_attrs(attrs) {
        push_proc_macro_invocation(invocations, invocation);
    }
}

fn proc_macro_invocations_for_attrs(attrs: &[syn::Attribute]) -> Vec<ProcMacroInvocation> {
    attrs
        .iter()
        .filter(|attr| attr_counts_as_proc_macro_invocation(attr))
        .map(proc_macro_invocation_for_attr)
        .collect()
}

fn attr_counts_as_proc_macro_invocation(attr: &syn::Attribute) -> bool {
    let Some(ident) = attr.path().get_ident() else {
        return true;
    };
    !matches!(
        ident.to_string().as_str(),
        "allow" | "cfg" | "cfg_attr" | "deny" | "doc" | "forbid" | "inline" | "must_use" | "warn"
    )
}

fn proc_macro_invocation_for_attr(attr: &syn::Attribute) -> ProcMacroInvocation {
    let macro_path = rust_path_surface(attr.path());
    let operator = if macro_path == "derive" {
        DERIVE_ATTRIBUTE_CONCEPT
    } else {
        PROC_MACRO_INVOCATION_CONCEPT
    };
    ProcMacroInvocation {
        operator,
        macro_cid: blake3_512_of(format!("rust:attribute-macro:{macro_path}").as_bytes()),
        args: if operator == DERIVE_ATTRIBUTE_CONCEPT {
            derive_attribute_args(attr)
        } else {
            attribute_macro_args(attr)
        },
        token_stream: attr_token_stream(attr),
        macro_path,
    }
}

fn push_proc_macro_invocation(
    invocations: &mut Vec<ProcMacroInvocation>,
    invocation: ProcMacroInvocation,
) {
    if !invocations.iter().any(|existing| {
        existing.operator == invocation.operator
            && existing.macro_path == invocation.macro_path
            && existing.token_stream == invocation.token_stream
    }) {
        invocations.push(invocation);
    }
}

fn derive_attribute_args(attr: &syn::Attribute) -> Vec<JsonValue> {
    let Meta::List(list) = &attr.meta else {
        return Vec::new();
    };
    let parser = syn::punctuated::Punctuated::<syn::Path, syn::Token![,]>::parse_terminated;
    parser
        .parse2(list.tokens.clone())
        .map(|paths| {
            paths
                .iter()
                .map(|path| json!({"kind": "symbol", "name": rust_path_surface(path)}))
                .collect()
        })
        .unwrap_or_else(|_| {
            vec![token_stream_term(normalize_attr_tokens(
                list.tokens.to_string(),
            ))]
        })
}

fn attribute_macro_args(attr: &syn::Attribute) -> Vec<JsonValue> {
    match &attr.meta {
        Meta::Path(_) => Vec::new(),
        Meta::NameValue(name_value) => vec![expr_arg_term(&name_value.value)],
        Meta::List(list) => {
            if list.tokens.is_empty() {
                return Vec::new();
            }
            let parser = syn::punctuated::Punctuated::<Expr, syn::Token![,]>::parse_terminated;
            parser
                .parse2(list.tokens.clone())
                .map(|exprs| exprs.iter().map(expr_arg_term).collect())
                .unwrap_or_else(|_| {
                    vec![token_stream_term(normalize_attr_tokens(
                        list.tokens.to_string(),
                    ))]
                })
        }
    }
}

fn expr_arg_term(expr: &Expr) -> JsonValue {
    match expr {
        Expr::Path(path) => json!({"kind": "symbol", "name": rust_path_surface(&path.path)}),
        Expr::Lit(lit) => literal_arg_term(&lit.lit),
        _ => token_stream_term(normalize_attr_tokens(expr.to_token_stream().to_string())),
    }
}

fn literal_arg_term(lit: &Lit) -> JsonValue {
    match lit {
        Lit::Bool(value) => json!({
            "kind": "const",
            "sort": {"kind": "ctor", "name": "Bool", "args": []},
            "value": value.value(),
        }),
        Lit::Int(value) => match value.base10_parse::<i64>() {
            Ok(parsed) => json!({
                "kind": "const",
                "sort": {"kind": "ctor", "name": "Int", "args": []},
                "value": parsed,
            }),
            Err(_) => token_stream_term(normalize_attr_tokens(value.to_token_stream().to_string())),
        },
        Lit::Str(value) => json!({
            "kind": "const",
            "sort": {"kind": "ctor", "name": "String", "args": []},
            "value": value.value(),
        }),
        _ => token_stream_term(normalize_attr_tokens(lit.to_token_stream().to_string())),
    }
}

fn token_stream_term(surface: String) -> JsonValue {
    json!({
        "kind": "token-stream",
        "surface": surface,
    })
}

fn attr_token_stream(attr: &syn::Attribute) -> String {
    match &attr.meta {
        Meta::Path(path) => format!("#[{}]", rust_path_surface(path)),
        Meta::List(list) => {
            let args = normalize_attr_tokens(list.tokens.to_string());
            format!("#[{}({args})]", rust_path_surface(&list.path))
        }
        Meta::NameValue(name_value) => format!(
            "#[{} = {}]",
            rust_path_surface(&name_value.path),
            normalize_attr_tokens(name_value.value.to_token_stream().to_string())
        ),
    }
}

fn rust_path_surface(path: &syn::Path) -> String {
    normalize_attr_tokens(path.to_token_stream().to_string())
}

fn normalize_attr_tokens(raw: String) -> String {
    let mut out = String::new();
    let mut prev_ws = false;
    for ch in raw.chars() {
        if ch.is_whitespace() {
            if !prev_ws && !out.is_empty() {
                out.push(' ');
            }
            prev_ws = true;
        } else {
            out.push(ch);
            prev_ws = false;
        }
    }
    let mut normalized = out.trim().to_string();
    for (from, to) in [
        (" :: ", "::"),
        (" ::", "::"),
        (":: ", "::"),
        (" < ", "<"),
        (" >", ">"),
        (" ,", ","),
        (" (", "("),
        ("( ", "("),
        (" )", ")"),
        ("[ ", "["),
        (" ]", "]"),
    ] {
        normalized = normalized.replace(from, to);
    }
    normalized
}

fn local_op_definition_cid(operator: &str) -> String {
    blake3_512_of(operator.as_bytes())
}

fn lower_function_body_to_term(
    item_fn: &syn::ItemFn,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    lower_stmts_to_stmt(&item_fn.block.stmts, ctx)
}

fn lower_stmts_to_stmt(stmts: &[Stmt], ctx: &LoweringContext) -> Result<AlgebraTerm, String> {
    if let Some((first, rest)) = stmts.split_first() {
        if let Stmt::Local(local) = first {
            return lower_local_binding_to_stmt(local, rest, ctx);
        }
        if let Stmt::Expr(Expr::MethodCall(method), Some(_)) = first {
            return lower_method_call_statement_to_stmt(method, rest, ctx);
        }
    }

    let mut lowered = Vec::new();
    for (idx, stmt) in stmts.iter().enumerate() {
        let is_tail = idx + 1 == stmts.len();
        match stmt {
            Stmt::Expr(expr, None) if is_tail => lowered.push(lower_tail_expr_to_stmt(expr, ctx)?),
            Stmt::Expr(Expr::MethodCall(method), Some(_)) => {
                let tail = lower_method_call_statement_to_stmt(method, &stmts[idx + 1..], ctx)?;
                return Ok(seq_all_then(lowered, tail));
            }
            Stmt::Expr(expr, _) => lowered.push(lower_expr_to_stmt(expr, ctx)?),
            Stmt::Local(local) => {
                let tail = lower_local_binding_to_stmt(local, &stmts[idx + 1..], ctx)?;
                return Ok(seq_all_then(lowered, tail));
            }
            Stmt::Item(_) => {}
            Stmt::Macro(mac) => {
                lowered.push(lower_macro_to_value_term(&mac.mac, ctx)?);
            }
        }
    }
    Ok(seq_all(lowered))
}

fn lower_local_binding_to_stmt(
    local: &syn::Local,
    rest: &[Stmt],
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    let pattern = lower_local_let_pattern(&local.pat, ctx)?;
    let Some(init) = &local.init else {
        return Err("unsupported let-binding without initializer".to_string());
    };
    let value = lower_expr_to_value_term(&init.expr, ctx)?;
    let declared_sort = local_pat_type(&local.pat).and_then(sort_from_type);
    let inferred_sort = declared_sort.or_else(|| expr_sort(&init.expr, ctx));
    let body = match pattern.binding_name() {
        Some(name) => {
            let nested_ctx = ctx.with_local_var(name, inferred_sort, pattern.is_mutable());
            lower_stmts_to_stmt(rest, &nested_ctx)?
        }
        None => lower_stmts_to_stmt(rest, ctx)?,
    };
    Ok(AlgebraTerm::op(
        "let",
        vec![pattern.into_term(), value, body],
    ))
}

fn seq_all(terms: Vec<AlgebraTerm>) -> AlgebraTerm {
    let mut iter = terms.into_iter();
    let Some(first) = iter.next() else {
        return AlgebraTerm::skip();
    };
    iter.fold(first, |acc, term| AlgebraTerm::op("seq", vec![acc, term]))
}

fn seq_all_then(mut terms: Vec<AlgebraTerm>, tail: AlgebraTerm) -> AlgebraTerm {
    if terms.is_empty() {
        return tail;
    }
    terms.push(tail);
    seq_all(terms)
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
struct TryHandlerContextDecision {
    owner: &'static str,
    handlers_at_emit: usize,
    reason: &'static str,
}

fn route_try_handler_context_decision() -> TryHandlerContextDecision {
    TryHandlerContextDecision {
        owner: "function-boundary",
        handlers_at_emit: 0,
        reason: "Rust ? at sugar-walk emit propagates to the caller boundary; emit has no in-crate catch/handler context, so RouteRaisesOperation is intentionally terminal-empty and byte-compatible.",
    }
}

fn route_try_residual_to_legacy_term(
    op_name: &'static str,
    inner: AlgebraTerm,
    effect: Effect,
) -> Result<AlgebraTerm, String> {
    let original = effect.clone();
    let handler_context = route_try_handler_context_decision();
    debug_assert_eq!(handler_context.handlers_at_emit, 0);
    match RouteRaisesOperation::new(Vec::new(), "sugar-walk.emit.try")
        .route_incomplete(Outcome::Incomplete(effect))
    {
        Outcome::Incomplete(returned) if returned == original => Ok(AlgebraTerm::op(op_name, vec![inner])),
        Outcome::Incomplete(returned) => Err(format!(
            "sugar-walk.emit.try: RouteRaisesOperation rewrote unmatched raise {original:?} into {returned:?}"
        )),
        Outcome::Complete(_) => {
            Err("sugar-walk.emit.try: RouteRaisesOperation routed residual try without a handler".to_string())
        }
    }
}

fn result_try_effect(try_expr: &syn::ExprTry) -> Effect {
    Effect::Raise(RaiseEffect::ResultErr {
        boundary: try_expr.to_token_stream().to_string(),
    })
}

fn option_try_effect(try_expr: &syn::ExprTry) -> Effect {
    Effect::Raise(RaiseEffect::EarlyReturn {
        boundary: try_expr.to_token_stream().to_string(),
    })
}

fn lower_try_expr_to_stmt(
    try_expr: &syn::ExprTry,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    let inner = lower_expr_to_value_term(&try_expr.expr, ctx)?;
    route_try_residual_to_legacy_term("try", inner, result_try_effect(try_expr))
}

fn lower_try_expr_to_value_term(
    try_expr: &syn::ExprTry,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    let inner = lower_expr_to_value_term(&try_expr.expr, ctx)?;
    let (op_name, effect) = match &ctx.return_shape {
        ReturnShape::Partial { loss, .. } if *loss == "return-type-option" => {
            ("try_option", option_try_effect(try_expr))
        }
        _ => ("try", result_try_effect(try_expr)),
    };
    route_try_residual_to_legacy_term(op_name, inner, effect)
}

fn lower_tail_expr_to_stmt(expr: &Expr, ctx: &LoweringContext) -> Result<AlgebraTerm, String> {
    if ctx.return_shape.sort() == Some(ExprSort::Unit)
        && matches!(expr, Expr::ForLoop(_) | Expr::If(_) | Expr::Match(_))
    {
        return Ok(seq_all(vec![
            lower_expr_to_stmt(expr, ctx)?,
            AlgebraTerm::op("return", vec![AlgebraTerm::Unit]),
        ]));
    }
    if let Expr::If(if_expr) = expr {
        if let Some(term) = lower_tail_if_expr_to_stmt(if_expr, ctx)? {
            return Ok(term);
        }
    }
    Ok(AlgebraTerm::op(
        "return",
        vec![lower_return_expr_to_value_term(expr, ctx)?],
    ))
}

fn lower_tail_if_expr_to_stmt(
    if_expr: &ExprIf,
    ctx: &LoweringContext,
) -> Result<Option<AlgebraTerm>, String> {
    let Some((_, else_expr)) = &if_expr.else_branch else {
        return Ok(None);
    };
    let Some(then_expr) = block_single_tail_expr(&if_expr.then_branch) else {
        return Ok(None);
    };
    let Some(else_tail) = expr_single_tail_expr(else_expr) else {
        return Ok(None);
    };
    let cond = lower_expr_to_bool_term(&if_expr.cond, ctx)?;
    let then_return = AlgebraTerm::op(
        "return",
        vec![lower_return_expr_to_value_term(then_expr, ctx)?],
    );
    let if_stmt = AlgebraTerm::op("if", vec![cond, then_return, AlgebraTerm::skip()]);
    let trailing_return = AlgebraTerm::op(
        "return",
        vec![lower_return_expr_to_value_term(else_tail, ctx)?],
    );
    Ok(Some(AlgebraTerm::op("seq", vec![if_stmt, trailing_return])))
}

fn lower_expr_to_stmt(expr: &Expr, ctx: &LoweringContext) -> Result<AlgebraTerm, String> {
    match expr {
        Expr::Return(ret) => {
            let value = match &ret.expr {
                Some(value) => lower_return_expr_to_value_term(value, ctx)?,
                None if ctx.return_shape.sort() == Some(ExprSort::Unit) => AlgebraTerm::Unit,
                None => {
                    return Err("bare return in non-unit function".to_string());
                }
            };
            Ok(AlgebraTerm::op("return", vec![value]))
        }
        Expr::If(if_expr) => {
            let cond = lower_expr_to_bool_term(&if_expr.cond, ctx)?;
            let then_branch = lower_stmts_to_stmt(&if_expr.then_branch.stmts, ctx)?;
            let else_branch = match &if_expr.else_branch {
                Some((_, else_expr)) => lower_expr_to_stmt(else_expr, ctx)?,
                None => AlgebraTerm::skip(),
            };
            Ok(AlgebraTerm::op("if", vec![cond, then_branch, else_branch]))
        }
        Expr::Assign(assign) => lower_assign_expr_to_stmt(assign, ctx),
        Expr::Block(block) => lower_stmts_to_stmt(&block.block.stmts, ctx),
        Expr::ForLoop(for_loop) => lower_for_loop_to_stmt(for_loop, ctx),
        Expr::Match(match_expr) => lower_match_to_stmt(match_expr, ctx),
        Expr::Unsafe(unsafe_expr) => lower_stmts_to_stmt(&unsafe_expr.block.stmts, ctx),
        Expr::MethodCall(method) => {
            if method.turbofish.is_some() {
                return Err(
                    "unsupported statement-position method call with explicit turbofish"
                        .to_string(),
                );
            }
            lower_method_call_expr_to_value_term(method, ctx)
        }
        Expr::Call(call) => lower_call_expr_to_value_term(call, ctx),
        Expr::Macro(mac) => lower_macro_to_value_term(&mac.mac, ctx),
        Expr::Try(try_expr) => lower_try_expr_to_stmt(try_expr, ctx),
        Expr::Index(_) => lower_discarded_value_expr_to_stmt(expr, ctx),
        Expr::Field(_) => lower_discarded_value_expr_to_stmt(expr, ctx),
        Expr::Tuple(tuple) => {
            if tuple.elems.is_empty() {
                Ok(AlgebraTerm::skip())
            } else {
                lower_discarded_value_expr_to_stmt(expr, ctx)
            }
        }
        Expr::Array(_) => lower_discarded_value_expr_to_stmt(expr, ctx),
        Expr::Reference(_) => lower_discarded_value_expr_to_stmt(expr, ctx),
        Expr::Path(_) => Ok(AlgebraTerm::skip()),
        Expr::Lit(_) => Ok(AlgebraTerm::skip()),
        _ => Err(format!(
            "unsupported expression statement {}",
            expr_kind(expr)
        )),
    }
}

fn lower_method_call_statement_to_stmt(
    method: &syn::ExprMethodCall,
    rest: &[Stmt],
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    if method.turbofish.is_some() {
        return Err(
            "unsupported statement-position method call with explicit turbofish".to_string(),
        );
    }

    let mut sources = Vec::new();
    if let Some(receiver_source) = method_receiver_source_name(&method.receiver) {
        if ctx.is_mutable_source(&receiver_source) {
            push_unique(&mut sources, receiver_source);
        }
    }
    for arg in &method.args {
        if let Some(source) = mut_borrow_source_name(arg) {
            push_unique(&mut sources, source);
        }
    }

    if sources.is_empty() {
        let value = lower_method_call_expr_to_value_term(method, ctx)?;
        if rest.is_empty() {
            return Ok(value);
        }
        let tail = lower_stmts_to_stmt(rest, ctx)?;
        return Ok(seq_all_then(vec![value], tail));
    }

    let value = lower_method_call_expr_to_statement_value_term(method, ctx)?;
    let mut rebound_ctx = ctx.clone();
    let mut bindings = Vec::new();
    for source in sources {
        let (rebound_name, next_ctx) = rebound_ctx.with_ssa_rebinding(&source);
        rebound_ctx = next_ctx;
        bindings.push(rebound_name);
    }

    let mut binding_terms = Vec::new();
    let mut previous_binding: Option<String> = None;
    for binding in bindings {
        let rhs = match &previous_binding {
            Some(previous) => AlgebraTerm::Var(previous.clone()),
            None => value.clone(),
        };
        previous_binding = Some(binding.clone());
        binding_terms.push((binding, rhs));
    }

    let mut body = lower_stmts_to_stmt(rest, &rebound_ctx)?;
    for (binding, rhs) in binding_terms.into_iter().rev() {
        body = AlgebraTerm::op(
            "let",
            vec![
                AlgebraTerm::op("pattern_bind", vec![AlgebraTerm::Symbol(binding.clone())]),
                rhs,
                body,
            ],
        );
    }
    Ok(body)
}

fn push_unique(items: &mut Vec<String>, item: String) {
    if !items.iter().any(|existing| existing == &item) {
        items.push(item);
    }
}

fn method_receiver_source_name(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Path(path) => path_name(path),
        Expr::MethodCall(method) => method_receiver_source_name(&method.receiver),
        Expr::Paren(paren) => method_receiver_source_name(&paren.expr),
        Expr::Group(group) => method_receiver_source_name(&group.expr),
        Expr::Field(field) => method_receiver_source_name(&field.base),
        Expr::Reference(reference) => method_receiver_source_name(&reference.expr),
        Expr::Unary(unary) if matches!(unary.op, UnOp::Deref(_)) => {
            method_receiver_source_name(&unary.expr)
        }
        Expr::Array(_)
        | Expr::Assign(_)
        | Expr::Async(_)
        | Expr::Await(_)
        | Expr::Binary(_)
        | Expr::Block(_)
        | Expr::Break(_)
        | Expr::Call(_)
        | Expr::Cast(_)
        | Expr::Closure(_)
        | Expr::Const(_)
        | Expr::Continue(_)
        | Expr::ForLoop(_)
        | Expr::If(_)
        | Expr::Index(_)
        | Expr::Infer(_)
        | Expr::Let(_)
        | Expr::Lit(_)
        | Expr::Loop(_)
        | Expr::Macro(_)
        | Expr::Match(_)
        | Expr::Range(_)
        | Expr::RawAddr(_)
        | Expr::Repeat(_)
        | Expr::Return(_)
        | Expr::Struct(_)
        | Expr::Try(_)
        | Expr::TryBlock(_)
        | Expr::Tuple(_)
        | Expr::Unary(_)
        | Expr::Unsafe(_)
        | Expr::Verbatim(_)
        | Expr::While(_)
        | Expr::Yield(_) => None,
        _ => panic!("sugar-walk emit receiver source refused unknown syn::Expr variant"),
    }
}

fn mut_borrow_source_name(expr: &Expr) -> Option<String> {
    let Expr::Reference(reference) = expr else {
        return None;
    };
    reference.mutability.as_ref()?;
    match &*reference.expr {
        Expr::Path(path) => path_name(path),
        Expr::Paren(paren) => mut_borrow_source_name(&paren.expr),
        Expr::Group(group) => mut_borrow_source_name(&group.expr),
        Expr::Field(field) => method_receiver_source_name(&field.base),
        Expr::Array(_)
        | Expr::Assign(_)
        | Expr::Async(_)
        | Expr::Await(_)
        | Expr::Binary(_)
        | Expr::Block(_)
        | Expr::Break(_)
        | Expr::Call(_)
        | Expr::Cast(_)
        | Expr::Closure(_)
        | Expr::Const(_)
        | Expr::Continue(_)
        | Expr::ForLoop(_)
        | Expr::If(_)
        | Expr::Index(_)
        | Expr::Infer(_)
        | Expr::Let(_)
        | Expr::Lit(_)
        | Expr::Loop(_)
        | Expr::Macro(_)
        | Expr::Match(_)
        | Expr::MethodCall(_)
        | Expr::Range(_)
        | Expr::RawAddr(_)
        | Expr::Reference(_)
        | Expr::Repeat(_)
        | Expr::Return(_)
        | Expr::Struct(_)
        | Expr::Try(_)
        | Expr::TryBlock(_)
        | Expr::Tuple(_)
        | Expr::Unary(_)
        | Expr::Unsafe(_)
        | Expr::Verbatim(_)
        | Expr::While(_)
        | Expr::Yield(_) => None,
        _ => panic!("sugar-walk emit mutable borrow source refused unknown syn::Expr variant"),
    }
}

fn lower_discarded_value_expr_to_stmt(
    expr: &Expr,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    Ok(AlgebraTerm::op(
        "drop",
        vec![lower_expr_to_value_term(expr, ctx)?],
    ))
}

fn lower_assign_expr_to_stmt(
    assign: &syn::ExprAssign,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    Ok(AlgebraTerm::op(
        "assign",
        vec![
            lower_expr_to_value_term(&assign.left, ctx)?,
            lower_expr_to_value_term(&assign.right, ctx)?,
        ],
    ))
}

fn lower_for_loop_to_stmt(
    for_loop: &syn::ExprForLoop,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    Ok(AlgebraTerm::op(
        "for",
        vec![
            lower_pat_to_pattern_term(&for_loop.pat),
            AlgebraTerm::op(
                "into_iter",
                vec![lower_expr_to_value_term(&for_loop.expr, ctx)?],
            ),
            lower_stmts_to_stmt(&for_loop.body.stmts, ctx)?,
        ],
    ))
}

fn lower_match_to_stmt(
    match_expr: &syn::ExprMatch,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    Ok(AlgebraTerm::op(
        "match",
        vec![
            lower_expr_to_value_term(&match_expr.expr, ctx)?,
            lower_match_arms_to_terms(&match_expr.arms, ctx, lower_match_arm_body_to_stmt)?,
        ],
    ))
}

fn lower_match_arm_body_to_stmt(expr: &Expr, ctx: &LoweringContext) -> Result<AlgebraTerm, String> {
    match expr {
        Expr::Tuple(tuple) if tuple.elems.is_empty() => Ok(AlgebraTerm::skip()),
        Expr::Block(block) if block.block.stmts.is_empty() => Ok(AlgebraTerm::skip()),
        _ => lower_expr_to_stmt(expr, ctx),
    }
}

fn lower_return_expr_to_value_term(
    expr: &Expr,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    match &ctx.return_shape {
        ReturnShape::Full(ExprSort::Bool) => {
            if matches!(expr, Expr::Call(_) | Expr::MethodCall(_) | Expr::Unsafe(_)) {
                lower_expr_to_value_term(expr, ctx)
            } else {
                lower_expr_to_bool_term(expr, ctx)
            }
        }
        ReturnShape::Full(ExprSort::Int) => {
            if matches!(expr, Expr::Call(_) | Expr::MethodCall(_) | Expr::Unsafe(_)) {
                lower_expr_to_value_term(expr, ctx)
            } else {
                lower_expr_to_int_term(expr, ctx)
            }
        }
        ReturnShape::Full(ExprSort::Unit) => lower_expr_to_unit_term(expr, ctx),
        ReturnShape::Partial { .. } | ReturnShape::SortOnly(_) => {
            lower_expr_to_value_term(expr, ctx)
        }
        ReturnShape::Unsupported => {
            Err("unsupported function return type for term emission".to_string())
        }
    }
}

fn lower_expr_to_bool_term(expr: &Expr, ctx: &LoweringContext) -> Result<AlgebraTerm, String> {
    match expr {
        Expr::Binary(binary) => {
            if let Some(op) = comparison_op(&binary.op) {
                return Ok(AlgebraTerm::op(
                    op,
                    vec![
                        lower_expr_to_int_term(&binary.left, ctx)?,
                        lower_expr_to_int_term(&binary.right, ctx)?,
                    ],
                ));
            }
            if let Some(op) = logical_binary_op(&binary.op) {
                return Ok(AlgebraTerm::op(
                    op,
                    vec![
                        lower_expr_to_bool_term(&binary.left, ctx)?,
                        lower_expr_to_bool_term(&binary.right, ctx)?,
                    ],
                ));
            }
            Err(format!("unsupported boolean operator: {:?}", binary.op))
        }
        Expr::Unary(unary) if matches!(unary.op, UnOp::Not(_)) => Ok(AlgebraTerm::op(
            "not",
            vec![lower_expr_to_bool_term(&unary.expr, ctx)?],
        )),
        Expr::Field(_) => {
            ctx.add_loss("type-inference-assumed-bool", expr_kind(expr));
            lower_expr_to_value_term(expr, ctx)
        }
        Expr::Let(let_expr) => lower_let_expr_to_bool_term(let_expr, ctx),
        Expr::Macro(mac) => lower_macro_to_value_term(&mac.mac, ctx),
        Expr::Match(match_expr) => lower_match_to_bool_term(match_expr, ctx),
        Expr::Paren(paren) => lower_expr_to_bool_term(&paren.expr, ctx),
        Expr::Block(block) => {
            let Some(tail) = block_single_tail_expr(&block.block) else {
                return Err("block expression has no single tail expression".to_string());
            };
            lower_expr_to_bool_term(tail, ctx)
        }
        Expr::Lit(lit) => match &lit.lit {
            Lit::Bool(value) => Ok(AlgebraTerm::ConstBool(value.value)),
            _ => Err("non-bool literal in boolean term".to_string()),
        },
        Expr::Path(path) => {
            let term = path_term_for_expr(path, ctx)
                .ok_or_else(|| "empty path in boolean term".to_string())?;
            match &term {
                AlgebraTerm::Var(name) => match ctx.vars.get(name).copied() {
                    Some(ExprSort::Bool) => Ok(term),
                    Some(sort) => Err(format!(
                        "expected Bool path in boolean term, found {} for `{name}`",
                        sort.name()
                    )),
                    None => {
                        ctx.add_loss("type-inference-assumed-bool", name.clone());
                        Ok(term)
                    }
                },
                AlgebraTerm::FullyQualifiedPath(path) => {
                    ctx.add_loss("type-inference-assumed-bool", path.clone());
                    Ok(term)
                }
                _ => unreachable!("path term must be a var or fully qualified path"),
            }
        }
        Expr::Call(_) | Expr::MethodCall(_) => {
            ctx.add_loss("type-inference-assumed-bool", expr_kind(expr));
            lower_expr_to_value_term(expr, ctx)
        }
        _ => Err(format!(
            "unsupported boolean expression {}",
            expr_kind(expr)
        )),
    }
}

fn lower_expr_to_int_term(expr: &Expr, ctx: &LoweringContext) -> Result<AlgebraTerm, String> {
    match expr_sort(expr, ctx) {
        Some(ExprSort::Int) => lower_expr_to_value_term(expr, ctx),
        Some(sort) => Err(format!(
            "expected Int expression, found {} in {}",
            sort.name(),
            expr_kind(expr)
        )),
        None if matches!(
            expr,
            Expr::Binary(_)
                | Expr::Block(_)
                | Expr::Call(_)
                | Expr::Field(_)
                | Expr::Index(_)
                | Expr::MethodCall(_)
                | Expr::Paren(_)
                | Expr::Path(_)
                | Expr::Unsafe(_)
                | Expr::Unary(_)
        ) =>
        {
            ctx.add_loss("type-inference-assumed-int", expr_kind(expr));
            lower_expr_to_value_term(expr, ctx)
        }
        None => Err(format!(
            "cannot prove expression is Int for term emission: {}",
            expr_kind(expr)
        )),
    }
}

fn lower_let_expr_to_bool_term(
    let_expr: &syn::ExprLet,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    ctx.add_loss(LOSS_D4_EXPR_LET, let_expr.to_token_stream().to_string());
    Ok(AlgebraTerm::op(
        "if_let",
        vec![
            lower_pat_to_pattern_term(&let_expr.pat),
            lower_expr_to_value_term(&let_expr.expr, ctx)?,
        ],
    ))
}

fn lower_expr_to_unit_term(expr: &Expr, ctx: &LoweringContext) -> Result<AlgebraTerm, String> {
    match expr {
        Expr::Tuple(tuple) if tuple.elems.is_empty() => Ok(AlgebraTerm::Unit),
        Expr::Block(block) if block.block.stmts.is_empty() => Ok(AlgebraTerm::Unit),
        Expr::Unsafe(unsafe_expr) => lower_stmts_to_stmt(&unsafe_expr.block.stmts, ctx),
        Expr::ForLoop(_) | Expr::If(_) | Expr::Match(_) => lower_expr_to_stmt(expr, ctx),
        _ => Err(format!("unsupported unit expression {}", expr_kind(expr))),
    }
}

fn lower_expr_to_value_term(expr: &Expr, ctx: &LoweringContext) -> Result<AlgebraTerm, String> {
    match expr {
        Expr::Lit(lit) => match &lit.lit {
            Lit::Int(value) => value
                .base10_parse::<i64>()
                .map(AlgebraTerm::ConstInt)
                .map_err(|err| format!("integer literal does not fit i64: {err}")),
            Lit::Bool(value) => Ok(AlgebraTerm::ConstBool(value.value)),
            _ => Err("unsupported literal expression".to_string()),
        },
        Expr::Path(path) => {
            path_term_for_expr(path, ctx).ok_or_else(|| "empty path expression".to_string())
        }
        Expr::Paren(paren) => lower_expr_to_value_term(&paren.expr, ctx),
        Expr::Group(group) => lower_expr_to_value_term(&group.expr, ctx),
        Expr::Block(block) => {
            let Some(tail) = block_single_tail_expr(&block.block) else {
                return Err("block expression has no single tail expression".to_string());
            };
            lower_expr_to_value_term(tail, ctx)
        }
        Expr::Unsafe(unsafe_expr) => {
            let Some(tail) = block_single_tail_expr(&unsafe_expr.block) else {
                return Err("unsafe block expression has no single tail expression".to_string());
            };
            lower_expr_to_value_term(tail, ctx)
        }
        Expr::Unary(unary) => {
            let op = match &unary.op {
                UnOp::Neg(_) => "neg",
                UnOp::Not(_) => match expr_sort(&unary.expr, ctx) {
                    Some(ExprSort::Int) => "bit_not",
                    Some(ExprSort::Bool) => {
                        return Err("logical ! used in value position".to_string());
                    }
                    Some(ExprSort::Unit) => {
                        return Err("unary ! is unsupported for Unit".to_string());
                    }
                    None => {
                        return Err(
                            "cannot determine whether unary ! is Bool or Int; skipping term"
                                .to_string(),
                        );
                    }
                },
                UnOp::Deref(_) => "deref",
                _ => return Err(format!("unsupported unary operator: {:?}", unary.op)),
            };
            Ok(AlgebraTerm::op(
                op,
                vec![lower_expr_to_value_term(&unary.expr, ctx)?],
            ))
        }
        Expr::Binary(binary) => {
            let op = arithmetic_binary_op(&binary.op)
                .or_else(|| bitwise_binary_op(&binary.op))
                .or_else(|| comparison_op(&binary.op));
            let Some(op) = op else {
                return Err(format!("unsupported value operator: {:?}", binary.op));
            };
            Ok(AlgebraTerm::op(
                op,
                vec![
                    lower_expr_to_int_term(&binary.left, ctx)?,
                    lower_expr_to_int_term(&binary.right, ctx)?,
                ],
            ))
        }
        Expr::Call(call) => lower_call_expr_to_value_term(call, ctx),
        Expr::MethodCall(method) => lower_method_call_expr_to_value_term(method, ctx),
        Expr::Closure(closure) => {
            if closure.asyncness.is_some() {
                return Err("unsupported async closure in value position".to_string());
            }
            if closure.capture.is_some() {
                return Err("unsupported move closure in value position".to_string());
            }
            let mut params = Vec::new();
            let mut closure_ctx = ctx.clone();
            for input in &closure.inputs {
                let mut bindings = match input {
                    syn::Pat::Ident(ident) => vec![(ident.ident.to_string(), None)],
                    syn::Pat::Type(pat_type) => match &*pat_type.pat {
                        syn::Pat::Ident(ident) => {
                            vec![(ident.ident.to_string(), sort_from_type(&pat_type.ty))]
                        }
                        _ => {
                            return Err(
                                "unsupported closure parameter destructuring pattern".to_string()
                            );
                        }
                    },
                    syn::Pat::Tuple(tuple) if closure.inputs.len() == 1 => {
                        let mut tuple_bindings = Vec::new();
                        for elem in &tuple.elems {
                            match elem {
                                syn::Pat::Ident(ident) => {
                                    tuple_bindings.push((ident.ident.to_string(), None))
                                }
                                syn::Pat::Type(pat_type) => {
                                    let syn::Pat::Ident(ident) = &*pat_type.pat else {
                                        return Err(
                                            "unsupported closure parameter destructuring pattern"
                                                .to_string(),
                                        );
                                    };
                                    tuple_bindings.push((
                                        ident.ident.to_string(),
                                        sort_from_type(&pat_type.ty),
                                    ));
                                }
                                _ => {
                                    return Err(
                                        "unsupported closure parameter destructuring pattern"
                                            .to_string(),
                                    );
                                }
                            }
                        }
                        tuple_bindings
                    }
                    _ => {
                        return Err(
                            "unsupported closure parameter destructuring pattern".to_string()
                        );
                    }
                };
                for (name, sort) in bindings.drain(..) {
                    closure_ctx = closure_ctx.with_var(name.clone(), sort);
                    params.push(AlgebraTerm::Symbol(name));
                }
            }
            ctx.add_loss(
                "closure-captures-environment",
                closure.to_token_stream().to_string(),
            );
            Ok(AlgebraTerm::op(
                "closure",
                vec![
                    AlgebraTerm::List(params),
                    lower_expr_to_value_term(&closure.body, &closure_ctx)?,
                ],
            ))
        }
        Expr::Array(array) => {
            let items = array
                .elems
                .iter()
                .map(|expr| lower_expr_to_value_term(expr, ctx))
                .collect::<Result<Vec<_>, _>>()?;
            Ok(AlgebraTerm::op("array", vec![AlgebraTerm::List(items)]))
        }
        Expr::Repeat(repeat) => Ok(AlgebraTerm::op(
            "array_repeat",
            vec![
                lower_expr_to_value_term(&repeat.expr, ctx)?,
                lower_expr_to_int_term(&repeat.len, ctx)?,
            ],
        )),
        Expr::Tuple(tuple) => {
            if tuple.elems.is_empty() {
                return Ok(AlgebraTerm::Unit);
            }
            let items = tuple
                .elems
                .iter()
                .map(|expr| lower_expr_to_value_term(expr, ctx))
                .collect::<Result<Vec<_>, _>>()?;
            Ok(AlgebraTerm::op("tuple", vec![AlgebraTerm::List(items)]))
        }
        Expr::Struct(strukt) => lower_struct_expr_to_value_term(strukt, ctx),
        Expr::Field(field) => Ok(AlgebraTerm::op(
            "field",
            vec![
                lower_expr_to_value_term(&field.base, ctx)?,
                AlgebraTerm::Symbol(field.member.to_token_stream().to_string()),
            ],
        )),
        Expr::Index(index) => Ok(AlgebraTerm::op(
            "index",
            vec![
                lower_expr_to_value_term(&index.expr, ctx)?,
                lower_expr_to_int_term(&index.index, ctx)?,
            ],
        )),
        Expr::Try(try_expr) => lower_try_expr_to_value_term(try_expr, ctx),
        Expr::Macro(mac) => lower_macro_to_value_term(&mac.mac, ctx),
        Expr::Match(match_expr) => lower_match_to_value_term(match_expr, ctx),
        Expr::Reference(reference) => {
            let op = if reference.mutability.is_some() {
                "borrow_mut"
            } else {
                "borrow"
            };
            Ok(AlgebraTerm::op(
                op,
                vec![lower_expr_to_value_term(&reference.expr, ctx)?],
            ))
        }
        Expr::Cast(_) => Err("unsupported value expression Expr::Cast".to_string()),
        _ => Err(format!("unsupported value expression {}", expr_kind(expr))),
    }
}

fn lower_match_to_value_term(
    match_expr: &syn::ExprMatch,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    Ok(AlgebraTerm::op(
        "match_expr",
        vec![
            lower_expr_to_value_term(&match_expr.expr, ctx)?,
            lower_match_arms_to_terms(&match_expr.arms, ctx, lower_expr_to_value_term)?,
        ],
    ))
}

fn lower_match_to_bool_term(
    match_expr: &syn::ExprMatch,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    Ok(AlgebraTerm::op(
        "match_expr",
        vec![
            lower_expr_to_value_term(&match_expr.expr, ctx)?,
            lower_match_arms_to_terms(&match_expr.arms, ctx, lower_expr_to_bool_term)?,
        ],
    ))
}

fn lower_match_arms_to_terms(
    arms: &[syn::Arm],
    ctx: &LoweringContext,
    mut lower_body: impl FnMut(&Expr, &LoweringContext) -> Result<AlgebraTerm, String>,
) -> Result<AlgebraTerm, String> {
    let arms = arms
        .iter()
        .map(|arm| {
            let pattern = lower_pat_to_pattern_term(&arm.pat);
            let body = lower_body(&arm.body, ctx)?;
            if let Some((_, guard)) = &arm.guard {
                return Ok(AlgebraTerm::op(
                    "guarded_arm",
                    vec![pattern, lower_expr_to_bool_term(guard, ctx)?, body],
                ));
            }
            Ok(AlgebraTerm::op("arm", vec![pattern, body]))
        })
        .collect::<Result<Vec<_>, String>>()?;
    Ok(AlgebraTerm::op("arms", vec![AlgebraTerm::List(arms)]))
}

fn lower_pat_to_pattern_term(pat: &syn::Pat) -> AlgebraTerm {
    match pat {
        syn::Pat::Ident(ident) => AlgebraTerm::op(
            "pattern_bind",
            vec![AlgebraTerm::Symbol(ident.ident.to_string())],
        ),
        syn::Pat::Lit(lit) => AlgebraTerm::op(
            "pattern_bind",
            vec![AlgebraTerm::Symbol(lit.to_token_stream().to_string())],
        ),
        syn::Pat::Path(path) => AlgebraTerm::op(
            "pattern_bind",
            vec![AlgebraTerm::Symbol(path.to_token_stream().to_string())],
        ),
        syn::Pat::Reference(reference) => lower_pat_to_pattern_term(&reference.pat),
        syn::Pat::TupleStruct(tuple) => {
            let name = tuple
                .path
                .segments
                .last()
                .map(|segment| segment.ident.to_string());
            let args = tuple
                .elems
                .iter()
                .map(lower_pat_to_pattern_term)
                .collect::<Vec<_>>();
            match name.as_deref() {
                Some("Ok") => AlgebraTerm::op("pattern_ok", args),
                Some("Err") => AlgebraTerm::op("pattern_err", args),
                Some("Some") => AlgebraTerm::op("pattern_some", args),
                Some("None") => AlgebraTerm::op("pattern_none", args),
                _ => AlgebraTerm::op(
                    "pattern_bind",
                    vec![AlgebraTerm::Symbol(tuple.to_token_stream().to_string())],
                ),
            }
        }
        syn::Pat::Type(pat_type) => lower_pat_to_pattern_term(&pat_type.pat),
        syn::Pat::Wild(_) => AlgebraTerm::op("pattern_wild", vec![]),
        _ => AlgebraTerm::op(
            "pattern_bind",
            vec![AlgebraTerm::Symbol(pat.to_token_stream().to_string())],
        ),
    }
}

fn lower_call_expr_to_value_term(
    call: &syn::ExprCall,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    let (op_name, callee) = match &*call.func {
        Expr::Path(path) => path_call_name_for_expr(path)
            .unwrap_or_else(|| ("unknown".to_string(), "unknown".to_string())),
        other => {
            ctx.add_loss(
                "ffi-call-unresolved-callee",
                format!("non-path callee {}", expr_kind(other)),
            );
            ("unknown".to_string(), "unknown".to_string())
        }
    };
    if let Some(declaration) = ctx.ffi_declaration(&callee) {
        ctx.add_ffi_call_effect_occurrence(&declaration);
    }
    let args = call
        .args
        .iter()
        .map(|arg| lower_expr_to_value_term(arg, ctx))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(AlgebraTerm::op(
        format!("call:{op_name}"),
        vec![AlgebraTerm::Symbol(callee), AlgebraTerm::List(args)],
    ))
}

fn lower_method_call_expr_to_value_term(
    method: &syn::ExprMethodCall,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    lower_method_call_expr_to_value_term_with_options(method, ctx, false)
}

fn lower_method_call_expr_to_statement_value_term(
    method: &syn::ExprMethodCall,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    lower_method_call_expr_to_value_term_with_options(method, ctx, true)
}

fn lower_method_call_expr_to_value_term_with_options(
    method: &syn::ExprMethodCall,
    ctx: &LoweringContext,
    statement_mut_args: bool,
) -> Result<AlgebraTerm, String> {
    let method_name = method.method.to_string();
    let receiver = lower_expr_to_value_term(&method.receiver, ctx)?;
    let args = method
        .args
        .iter()
        .map(|arg| lower_method_arg_expr_to_value_term(arg, ctx, statement_mut_args))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(AlgebraTerm::op(
        format!("method:{method_name}"),
        vec![receiver, AlgebraTerm::List(args)],
    ))
}

fn lower_method_arg_expr_to_value_term(
    arg: &Expr,
    ctx: &LoweringContext,
    statement_mut_args: bool,
) -> Result<AlgebraTerm, String> {
    if statement_mut_args {
        if let Some(source) = mut_borrow_source_name(arg) {
            return Ok(AlgebraTerm::Var(ctx.current_name(&source)));
        }
    }
    lower_expr_to_value_term(arg, ctx)
}

fn lower_struct_expr_to_value_term(
    strukt: &syn::ExprStruct,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    let name = strukt
        .path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
        .unwrap_or_else(|| "anonymous".to_string());
    let fields = strukt
        .fields
        .iter()
        .map(|field| {
            let name = field.member.to_token_stream().to_string();
            let value = lower_expr_to_value_term(&field.expr, ctx)?;
            Ok((name, value))
        })
        .collect::<Result<Vec<_>, String>>()?;
    Ok(AlgebraTerm::Struct { name, fields })
}

fn lower_macro_to_value_term(
    mac: &syn::Macro,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    let name = mac
        .path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
        .unwrap_or_else(|| "unknown".to_string());
    ctx.add_loss(LOSS_MACRO_NOT_EXPANDED, format!("{name}!"));
    if mac.path.is_ident("vec") {
        if let Some(term) = lower_vec_macro_to_value_term(mac, ctx)? {
            return Ok(term);
        }
    }
    Ok(AlgebraTerm::op(
        format!("macro_call:{name}"),
        vec![AlgebraTerm::Symbol(mac.tokens.to_string())],
    ))
}

fn lower_vec_macro_to_value_term(
    mac: &syn::Macro,
    ctx: &LoweringContext,
) -> Result<Option<AlgebraTerm>, String> {
    let parser = syn::punctuated::Punctuated::<Expr, syn::Token![,]>::parse_terminated;
    let items = match parser.parse2(mac.tokens.clone()) {
        Ok(items) => items
            .iter()
            .map(|expr| lower_expr_to_value_term(expr, ctx))
            .collect::<Result<Vec<_>, _>>()?,
        Err(_) => return Ok(None),
    };
    Ok(Some(AlgebraTerm::op(
        "array",
        vec![AlgebraTerm::List(items)],
    )))
}

fn expr_sort(expr: &Expr, ctx: &LoweringContext) -> Option<ExprSort> {
    match expr {
        Expr::Lit(lit) => match &lit.lit {
            Lit::Bool(_) => Some(ExprSort::Bool),
            Lit::Int(_) => Some(ExprSort::Int),
            Lit::Byte(_) | Lit::Char(_) => Some(ExprSort::Int),
            Lit::Float(_) | Lit::Str(_) | Lit::ByteStr(_) | Lit::CStr(_) | Lit::Verbatim(_) => {
                // #3017 item 2 owns richer scalar floors; ExprSort only proves
                // the current Unit/Bool/Int subset.
                None
            }
            _ => panic!("sugar-walk emit expr_sort refused unknown syn::Lit variant"),
        },
        Expr::Path(path) => {
            local_path_name_for_expr(path, ctx).and_then(|name| ctx.vars.get(&name).copied())
        }
        Expr::Paren(paren) => expr_sort(&paren.expr, ctx),
        Expr::Group(group) => expr_sort(&group.expr, ctx),
        Expr::Block(block) => {
            block_single_tail_expr(&block.block).and_then(|expr| expr_sort(expr, ctx))
        }
        Expr::Unary(unary) => match &unary.op {
            UnOp::Neg(_) => {
                (expr_sort(&unary.expr, ctx) == Some(ExprSort::Int)).then_some(ExprSort::Int)
            }
            UnOp::Not(_) => match expr_sort(&unary.expr, ctx) {
                Some(ExprSort::Bool) => Some(ExprSort::Bool),
                Some(ExprSort::Int) => Some(ExprSort::Int),
                Some(ExprSort::Unit) | None => {
                    // #3017 item 8 owns the predicate-vs-raw-term split that
                    // would let unknown `!x` classify without guessing.
                    None
                }
            },
            UnOp::Deref(_) => expr_sort(&unary.expr, ctx),
            _ => panic!("sugar-walk emit expr_sort refused unknown syn::UnOp variant"),
        },
        Expr::Binary(binary) => {
            if arithmetic_binary_op(&binary.op).is_some() || bitwise_binary_op(&binary.op).is_some()
            {
                return operands_have_sort(&binary.left, &binary.right, ctx, ExprSort::Int)
                    .then_some(ExprSort::Int);
            }
            if comparison_op(&binary.op).is_some() {
                return operands_have_sort(&binary.left, &binary.right, ctx, ExprSort::Int)
                    .then_some(ExprSort::Bool);
            }
            if logical_binary_op(&binary.op).is_some() {
                return operands_have_sort(&binary.left, &binary.right, ctx, ExprSort::Bool)
                    .then_some(ExprSort::Bool);
            }
            None
        }
        Expr::Array(_)
        | Expr::Assign(_)
        | Expr::Async(_)
        | Expr::Await(_)
        | Expr::Break(_)
        | Expr::Call(_)
        | Expr::Cast(_)
        | Expr::Closure(_)
        | Expr::Const(_)
        | Expr::Continue(_)
        | Expr::Field(_)
        | Expr::ForLoop(_)
        | Expr::If(_)
        | Expr::Index(_)
        | Expr::Infer(_)
        | Expr::Let(_)
        | Expr::Loop(_)
        | Expr::Macro(_)
        | Expr::Match(_)
        | Expr::MethodCall(_)
        | Expr::Range(_)
        | Expr::RawAddr(_)
        | Expr::Reference(_)
        | Expr::Repeat(_)
        | Expr::Return(_)
        | Expr::Struct(_)
        | Expr::Try(_)
        | Expr::TryBlock(_)
        | Expr::Tuple(_)
        | Expr::Unsafe(_)
        | Expr::Verbatim(_)
        | Expr::While(_)
        | Expr::Yield(_) => None,
        _ => panic!("sugar-walk emit expr_sort refused unknown syn::Expr variant"),
    }
}

fn operands_have_sort(left: &Expr, right: &Expr, ctx: &LoweringContext, sort: ExprSort) -> bool {
    expr_sort(left, ctx) == Some(sort) && expr_sort(right, ctx) == Some(sort)
}

fn logical_binary_op(op: &BinOp) -> Option<&'static str> {
    match op {
        BinOp::And(_) => Some("and"),
        BinOp::Or(_) => Some("or"),
        BinOp::Add(_)
        | BinOp::Sub(_)
        | BinOp::Mul(_)
        | BinOp::Div(_)
        | BinOp::Rem(_)
        | BinOp::BitXor(_)
        | BinOp::BitAnd(_)
        | BinOp::BitOr(_)
        | BinOp::Shl(_)
        | BinOp::Shr(_)
        | BinOp::Eq(_)
        | BinOp::Lt(_)
        | BinOp::Le(_)
        | BinOp::Ne(_)
        | BinOp::Ge(_)
        | BinOp::Gt(_) => None,
        _ => panic!("sugar-walk emit logical op refused unknown syn::BinOp variant"),
    }
}

fn comparison_op(op: &BinOp) -> Option<&'static str> {
    match op {
        BinOp::Eq(_) => Some("eq"),
        BinOp::Ne(_) => Some("ne"),
        BinOp::Lt(_) => Some("lt"),
        BinOp::Le(_) => Some("le"),
        BinOp::Gt(_) => Some("gt"),
        BinOp::Ge(_) => Some("ge"),
        BinOp::Add(_)
        | BinOp::Sub(_)
        | BinOp::Mul(_)
        | BinOp::Div(_)
        | BinOp::Rem(_)
        | BinOp::And(_)
        | BinOp::Or(_)
        | BinOp::BitXor(_)
        | BinOp::BitAnd(_)
        | BinOp::BitOr(_)
        | BinOp::Shl(_)
        | BinOp::Shr(_) => None,
        _ => panic!("sugar-walk emit comparison op refused unknown syn::BinOp variant"),
    }
}

fn arithmetic_binary_op(op: &BinOp) -> Option<&'static str> {
    match op {
        BinOp::Add(_) => Some("add"),
        BinOp::Sub(_) => Some("sub"),
        BinOp::Mul(_) => Some("mul"),
        BinOp::Div(_) => Some("div"),
        BinOp::Rem(_) => Some("rem"),
        BinOp::And(_)
        | BinOp::Or(_)
        | BinOp::BitXor(_)
        | BinOp::BitAnd(_)
        | BinOp::BitOr(_)
        | BinOp::Shl(_)
        | BinOp::Shr(_)
        | BinOp::Eq(_)
        | BinOp::Lt(_)
        | BinOp::Le(_)
        | BinOp::Ne(_)
        | BinOp::Ge(_)
        | BinOp::Gt(_) => None,
        _ => panic!("sugar-walk emit arithmetic op refused unknown syn::BinOp variant"),
    }
}

fn bitwise_binary_op(op: &BinOp) -> Option<&'static str> {
    match op {
        BinOp::BitAnd(_) => Some("bit_and"),
        BinOp::BitOr(_) => Some("bit_or"),
        BinOp::BitXor(_) => Some("bit_xor"),
        BinOp::Shl(_) => Some("shl"),
        BinOp::Shr(_) => Some("shr"),
        BinOp::Add(_)
        | BinOp::Sub(_)
        | BinOp::Mul(_)
        | BinOp::Div(_)
        | BinOp::Rem(_)
        | BinOp::And(_)
        | BinOp::Or(_)
        | BinOp::Eq(_)
        | BinOp::Lt(_)
        | BinOp::Le(_)
        | BinOp::Ne(_)
        | BinOp::Ge(_)
        | BinOp::Gt(_) => None,
        _ => panic!("sugar-walk emit bitwise op refused unknown syn::BinOp variant"),
    }
}

fn return_shape_from_return_type(output: &ReturnType) -> ReturnShape {
    match output {
        ReturnType::Default => ReturnShape::Full(ExprSort::Unit),
        ReturnType::Type(_, ty) => {
            if let Some(sort) = sort_from_type(ty) {
                ReturnShape::Full(sort)
            } else if let Some(loss) = partial_return_loss(ty) {
                ReturnShape::Partial {
                    loss,
                    rust_type: type_surface(ty),
                    return_sort: concept_sort_from_type(ty)
                        .unwrap_or_else(|| ConceptSort::new(type_surface(ty), Vec::new())),
                }
            } else if let Some(return_sort) = concept_sort_from_type(ty) {
                ReturnShape::SortOnly(return_sort)
            } else {
                ReturnShape::Unsupported
            }
        }
    }
}

fn sort_from_type(ty: &Type) -> Option<ExprSort> {
    match ty {
        Type::Path(path) if path.qself.is_none() => {
            let ident = path.path.segments.last()?.ident.to_string();
            sort_from_type_name(&ident)
        }
        Type::Paren(paren) => sort_from_type(&paren.elem),
        Type::Group(group) => sort_from_type(&group.elem),
        Type::Tuple(tuple) if tuple.elems.is_empty() => Some(ExprSort::Unit),
        Type::Path(_)
        | Type::Array(_)
        | Type::BareFn(_)
        | Type::ImplTrait(_)
        | Type::Infer(_)
        | Type::Macro(_)
        | Type::Never(_)
        | Type::Ptr(_)
        | Type::Reference(_)
        | Type::Slice(_)
        | Type::TraitObject(_)
        | Type::Tuple(_)
        | Type::Verbatim(_) => {
            // #3017 item 2 keeps non-primitive and sort-neutral values out of
            // this scalar classifier; concept_sort_from_type carries them.
            None
        }
        _ => panic!("sugar-walk emit sort_from_type refused unknown syn::Type variant"),
    }
}

fn sort_from_type_name(name: &str) -> Option<ExprSort> {
    match name {
        "bool" => Some(ExprSort::Bool),
        "i8" | "i16" | "i32" | "i64" | "i128" | "isize" | "u8" | "u16" | "u32" | "u64" | "u128"
        | "usize" => Some(ExprSort::Int),
        // sugar-audit: not-mine(user-defined-type-names-flow-to-concept-sort-not-scalar-sort)
        _ => None,
    }
}

fn concept_sort_from_type(ty: &Type) -> Option<ConceptSort> {
    match ty {
        Type::Path(path) if path.qself.is_none() => {
            let segment = path.path.segments.last()?;
            let ident = segment.ident.to_string();
            let name = match concept_sort_name_from_type_name(&ident) {
                Some(name) => name,
                None => ident,
            };
            Some(ConceptSort::new(
                name,
                concept_sort_args_from_path_segment(segment)?,
            ))
        }
        Type::Reference(reference) => {
            let name = if reference.mutability.is_some() {
                "RefMut"
            } else {
                "Ref"
            };
            Some(ConceptSort::new(
                name,
                vec![concept_sort_from_type(&reference.elem)?],
            ))
        }
        Type::Array(array) => Some(ConceptSort::new(
            "Array",
            vec![concept_sort_from_type(&array.elem)?],
        )),
        Type::Slice(slice) => Some(ConceptSort::new(
            "Slice",
            vec![concept_sort_from_type(&slice.elem)?],
        )),
        Type::Ptr(ptr) => {
            let name = if ptr.mutability.is_some() {
                "PtrMut"
            } else {
                "Ptr"
            };
            Some(ConceptSort::new(
                name,
                vec![concept_sort_from_type(&ptr.elem)?],
            ))
        }
        Type::Tuple(tuple) if tuple.elems.is_empty() => Some(ExprSort::Unit.concept_sort()),
        Type::Tuple(tuple) => Some(ConceptSort::new(
            "Tuple",
            tuple
                .elems
                .iter()
                .map(concept_sort_from_type)
                .collect::<Option<Vec<_>>>()?,
        )),
        Type::Paren(paren) => concept_sort_from_type(&paren.elem),
        Type::Group(group) => concept_sort_from_type(&group.elem),
        Type::BareFn(_)
        | Type::ImplTrait(_)
        | Type::Infer(_)
        | Type::Macro(_)
        | Type::Never(_)
        | Type::Path(_)
        | Type::TraitObject(_)
        | Type::Verbatim(_) => None,
        _ => panic!("sugar-walk emit concept_sort refused unknown syn::Type variant"),
    }
}

fn concept_sort_name_from_type_name(name: &str) -> Option<String> {
    sort_from_type_name(name).map(|sort| sort.name().to_string())
}

fn concept_sort_args_from_path_segment(segment: &syn::PathSegment) -> Option<Vec<ConceptSort>> {
    match &segment.arguments {
        syn::PathArguments::None => Some(Vec::new()),
        syn::PathArguments::AngleBracketed(args) => {
            let mut type_args = Vec::new();
            for arg in &args.args {
                match arg {
                    syn::GenericArgument::Type(ty) => {
                        type_args.push(concept_sort_from_type(ty)?);
                    }
                    syn::GenericArgument::Lifetime(_) => {}
                    syn::GenericArgument::AssocType(assoc) => {
                        type_args.push(concept_sort_from_type(&assoc.ty)?);
                    }
                    _ => return None,
                }
            }
            Some(type_args)
        }
        syn::PathArguments::Parenthesized(_) => None,
    }
}

fn partial_return_loss(ty: &Type) -> Option<&'static str> {
    match ty {
        Type::Path(path) if path.qself.is_none() => {
            let segment = path.path.segments.last()?;
            let ident = segment.ident.to_string();
            match ident.as_str() {
                "Result" => Some("return-type-result"),
                "Option" => Some("return-type-option"),
                "Vec" if path_type_arg_is_u8(segment) => Some("return-type-byte-vec"),
                "Vec" => Some("return-type-vec"),
                // sugar-audit: not-mine(non-container-return-type-has-no-partial-loss-record)
                _ => None,
            }
        }
        Type::Array(array) if type_is_u8(&array.elem) => Some("return-type-byte-array"),
        Type::Reference(reference) => partial_return_loss(&reference.elem),
        Type::Paren(paren) => partial_return_loss(&paren.elem),
        Type::Group(group) => partial_return_loss(&group.elem),
        Type::Array(_)
        | Type::BareFn(_)
        | Type::ImplTrait(_)
        | Type::Infer(_)
        | Type::Macro(_)
        | Type::Never(_)
        | Type::Path(_)
        | Type::Ptr(_)
        | Type::Slice(_)
        | Type::TraitObject(_)
        | Type::Tuple(_)
        | Type::Verbatim(_) => None,
        _ => panic!("sugar-walk emit partial_return_loss refused unknown syn::Type variant"),
    }
}

fn path_type_arg_is_u8(segment: &syn::PathSegment) -> bool {
    let syn::PathArguments::AngleBracketed(args) = &segment.arguments else {
        return false;
    };
    args.args.iter().any(|arg| match arg {
        syn::GenericArgument::Type(ty) => type_is_u8(ty),
        _ => false,
    })
}

fn type_is_u8(ty: &Type) -> bool {
    matches!(
        ty,
        Type::Path(path)
            if path.qself.is_none()
                && path
                    .path
                    .segments
                    .last()
                    .is_some_and(|segment| segment.ident == "u8")
    )
}

fn type_surface(ty: &Type) -> String {
    ty.to_token_stream().to_string()
}

enum LocalLetPattern {
    Bind { name: String, is_mutable: bool },
    Wild,
}

impl LocalLetPattern {
    fn binding_name(&self) -> Option<String> {
        match self {
            LocalLetPattern::Bind { name, .. } => Some(name.clone()),
            LocalLetPattern::Wild => None,
        }
    }

    fn is_mutable(&self) -> bool {
        match self {
            LocalLetPattern::Bind { is_mutable, .. } => *is_mutable,
            LocalLetPattern::Wild => false,
        }
    }

    fn into_term(self) -> AlgebraTerm {
        match self {
            LocalLetPattern::Bind { name, .. } => {
                AlgebraTerm::op("pattern_bind", vec![AlgebraTerm::Symbol(name)])
            }
            LocalLetPattern::Wild => AlgebraTerm::op("pattern_wild", vec![]),
        }
    }
}

fn lower_local_let_pattern(
    pat: &syn::Pat,
    ctx: &LoweringContext,
) -> Result<LocalLetPattern, String> {
    match pat {
        syn::Pat::Ident(ident) => {
            let name = ident.ident.to_string();
            let is_mutable = ident.mutability.is_some();
            if ident.mutability.is_some() {
                ctx.add_loss(LOSS_LET_BINDING_MUTABILITY, name.clone());
            }
            Ok(LocalLetPattern::Bind { name, is_mutable })
        }
        syn::Pat::Type(pat_type) => lower_local_let_pattern(&pat_type.pat, ctx),
        syn::Pat::Wild(_) => Ok(LocalLetPattern::Wild),
        _ => Err("unsupported let-binding pattern".to_string()),
    }
}

fn local_pat_type(pat: &syn::Pat) -> Option<&Type> {
    match pat {
        syn::Pat::Type(pat_type) => Some(&pat_type.ty),
        syn::Pat::Const(_)
        | syn::Pat::Ident(_)
        | syn::Pat::Lit(_)
        | syn::Pat::Macro(_)
        | syn::Pat::Or(_)
        | syn::Pat::Paren(_)
        | syn::Pat::Path(_)
        | syn::Pat::Range(_)
        | syn::Pat::Reference(_)
        | syn::Pat::Rest(_)
        | syn::Pat::Slice(_)
        | syn::Pat::Struct(_)
        | syn::Pat::Tuple(_)
        | syn::Pat::TupleStruct(_)
        | syn::Pat::Verbatim(_)
        | syn::Pat::Wild(_) => None,
        _ => panic!("sugar-walk emit local_pat_type refused unknown syn::Pat variant"),
    }
}

fn path_name(path: &syn::ExprPath) -> Option<String> {
    if path.qself.is_some() {
        return None;
    }
    path.path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
}

fn path_call_name_for_expr(path: &syn::ExprPath) -> Option<(String, String)> {
    let op_name = path.path.segments.last()?.ident.to_string();
    let callee = expr_path_surface(path)?;
    Some((op_name, callee))
}

fn path_term_for_expr(path: &syn::ExprPath, ctx: &LoweringContext) -> Option<AlgebraTerm> {
    if let Some(name) = local_path_name_for_expr(path, ctx) {
        return Some(AlgebraTerm::Var(name));
    }
    expr_path_surface(path).map(AlgebraTerm::FullyQualifiedPath)
}

fn local_path_name_for_expr(path: &syn::ExprPath, ctx: &LoweringContext) -> Option<String> {
    if path.qself.is_some() || path.path.leading_colon.is_some() || path.path.segments.len() != 1 {
        return None;
    }
    path_name(path).map(|name| ctx.current_name(&name))
}

fn expr_path_surface(path: &syn::ExprPath) -> Option<String> {
    if let Some(qself) = &path.qself {
        return qself_path_surface(qself, &path.path);
    }
    syn_path_surface(&path.path)
}

fn qself_path_surface(qself: &syn::QSelf, path: &syn::Path) -> Option<String> {
    let segments = path
        .segments
        .iter()
        .map(path_segment_surface)
        .collect::<Vec<_>>();
    if qself.position > segments.len() {
        return None;
    }

    let self_type = compact_rust_token_surface(qself.ty.to_token_stream().to_string());
    let trait_path = path_surface_from_segments(
        path.leading_colon.is_some() && qself.position > 0,
        &segments[..qself.position],
    );
    let associated_path = path_surface_from_segments(false, &segments[qself.position..]);

    match (trait_path, associated_path) {
        (Some(trait_path), Some(associated_path)) => {
            Some(format!("<{self_type} as {trait_path}>::{associated_path}"))
        }
        (Some(trait_path), None) => Some(format!("<{self_type} as {trait_path}>")),
        (None, Some(associated_path)) => Some(format!("<{self_type}>::{associated_path}")),
        (None, None) => None,
    }
}

fn syn_path_surface(path: &syn::Path) -> Option<String> {
    let segments = path
        .segments
        .iter()
        .map(path_segment_surface)
        .collect::<Vec<_>>();
    path_surface_from_segments(path.leading_colon.is_some(), &segments)
}

fn path_surface_from_segments(leading_colon: bool, segments: &[String]) -> Option<String> {
    if segments.is_empty() {
        return None;
    }
    let mut surface = segments.join("::");
    if leading_colon {
        surface = format!("::{surface}");
    }
    Some(surface)
}

fn path_segment_surface(segment: &syn::PathSegment) -> String {
    compact_rust_token_surface(segment.to_token_stream().to_string())
}

fn compact_rust_token_surface(surface: String) -> String {
    surface
        .replace(" :: ", "::")
        .replace(" ::", "::")
        .replace(":: ", "::")
        .replace(" < ", "<")
        .replace(" <", "<")
        .replace("< ", "<")
        .replace(" > ", ">")
        .replace(" >", ">")
        .replace("> ", ">")
        .replace(" , ", ", ")
        .replace(" ,", ",")
        .replace(" ( ", "(")
        .replace(" (", "(")
        .replace("( ", "(")
        .replace(" ) ", ")")
        .replace(" )", ")")
        .replace(") ", ")")
}

fn expr_kind(expr: &Expr) -> &'static str {
    match expr {
        Expr::Array(_) => "Expr::Array",
        Expr::Assign(_) => "Expr::Assign",
        Expr::Async(_) => "Expr::Async",
        Expr::Await(_) => "Expr::Await",
        Expr::Binary(_) => "Expr::Binary",
        Expr::Block(_) => "Expr::Block",
        Expr::Break(_) => "Expr::Break",
        Expr::Call(_) => "Expr::Call",
        Expr::Cast(_) => "Expr::Cast",
        Expr::Closure(_) => "Expr::Closure",
        Expr::Const(_) => "Expr::Const",
        Expr::Continue(_) => "Expr::Continue",
        Expr::Field(_) => "Expr::Field",
        Expr::ForLoop(_) => "Expr::ForLoop",
        Expr::Group(_) => "Expr::Group",
        Expr::If(_) => "Expr::If",
        Expr::Index(_) => "Expr::Index",
        Expr::Infer(_) => "Expr::Infer",
        Expr::Let(_) => "Expr::Let",
        Expr::Lit(_) => "Expr::Lit",
        Expr::Loop(_) => "Expr::Loop",
        Expr::Macro(_) => "Expr::Macro",
        Expr::Match(_) => "Expr::Match",
        Expr::MethodCall(_) => "Expr::MethodCall",
        Expr::Paren(_) => "Expr::Paren",
        Expr::Path(_) => "Expr::Path",
        Expr::Range(_) => "Expr::Range",
        Expr::Reference(_) => "Expr::Reference",
        Expr::Repeat(_) => "Expr::Repeat",
        Expr::Return(_) => "Expr::Return",
        Expr::Struct(_) => "Expr::Struct",
        Expr::Try(_) => "Expr::Try",
        Expr::TryBlock(_) => "Expr::TryBlock",
        Expr::Tuple(_) => "Expr::Tuple",
        Expr::Unary(_) => "Expr::Unary",
        Expr::Unsafe(_) => "Expr::Unsafe",
        Expr::Verbatim(_) => "Expr::Verbatim",
        Expr::While(_) => "Expr::While",
        Expr::Yield(_) => "Expr::Yield",
        _ => "Expr::<unknown>",
    }
}

fn block_single_tail_expr(block: &syn::Block) -> Option<&Expr> {
    match block.stmts.as_slice() {
        [Stmt::Expr(expr, None)] => Some(expr),
        // sugar-audit: not-mine(non-single-tail-block-is-a-shape-miss-not-a-dropped-obligation)
        _ => None,
    }
}

fn expr_single_tail_expr(expr: &Expr) -> Option<&Expr> {
    match expr {
        Expr::Block(block) => block_single_tail_expr(&block.block),
        other => Some(other),
    }
}

fn build_bundle_value(s: &ShadowSource) -> Arc<Value> {
    // Collect every arrival's edge memento as a separate object inside
    // the bundle's `arrivals` array. Each carries its own CID (as a
    // sibling field) so consumers can index without re-hashing.
    let arrivals: Vec<Arc<Value>> = s
        .all_arrivals()
        .map(|(_slot, arrival)| {
            let edge_value = edge_memento_value(arrival);
            let edge_cid = cid_of_value(&edge_value);
            Value::object([
                ("cid", Value::string(edge_cid)),
                ("memento", edge_value),
                ("arrivalCid", Value::string(arrival.cid.clone())),
                ("calleeName", Value::string(arrival.callee_name.clone())),
                ("sourceIndex", Value::integer(arrival.source_index as i128)),
            ])
        })
        .collect();

    // Best-effort composed chain: take the longest chain (stable tie-break).
    let composed_chain_value: Arc<Value> = match longest_chain(s) {
        Some(arrivals) if !arrivals.is_empty() => {
            let composed = compose_chain(arrivals.iter().copied());
            let component_cids: Vec<Arc<Value>> = composed
                .component_cids
                .iter()
                .map(|c| Value::string(c.clone()))
                .collect();
            Value::object([
                ("cid", Value::string(composed.cid)),
                ("componentCids", Value::array(component_cids)),
            ])
        }
        _ => Value::null(),
    };

    Value::object([
        ("schemaVersion", Value::string("sugar-walk/1")),
        ("kind", Value::string("walk-bundle")),
        ("shadowSourceCid", Value::string(s.cid.clone())),
        ("fnName", Value::string(s.fn_name.clone())),
        ("slotCount", Value::integer(s.slots.len() as i128)),
        ("arrivals", Value::array(arrivals)),
        ("composedChain", composed_chain_value),
    ])
}

fn longest_chain(s: &ShadowSource) -> Option<Vec<&crate::shadow::ShadowArrival>> {
    // Group arrivals by callee_root_cid and pick the chain with the most
    // arrivals. BTreeMap (sorted by callee_root_cid key) guarantees
    // deterministic iteration order so that when two chains have the same
    // length the FIRST key in lexicographic order wins - result is
    // byte-for-byte identical across calls regardless of HashMap seed.
    use std::collections::BTreeMap;
    let mut chains: BTreeMap<String, Vec<&crate::shadow::ShadowArrival>> = BTreeMap::new();
    for (_, arrival) in s.all_arrivals() {
        chains
            .entry(arrival.callee_root_cid.clone())
            .or_default()
            .push(arrival);
    }
    chains.into_values().max_by_key(|c| c.len())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        atomic_ge, build_shadow_source, const_int, lift_function_precondition, var, CalleeContract,
    };

    fn parse_named(src: &str, name: &str) -> syn::ItemFn {
        let file: syn::File = syn::parse_str(src).unwrap();
        file.items
            .into_iter()
            .find_map(|item| match item {
                syn::Item::Fn(f) if f.sig.ident == name => Some(f),
                // sugar-audit: not-mine(test-helper-search-ignores-non-target-items)
                _ => None,
            })
            .unwrap()
    }

    #[test]
    fn rust_term_json_round_trips_with_stable_cid() {
        let src = r#"
            fn foo(x: i32) -> i32 { if x == 0 { -22 } else { x } }
        "#;
        let foo_fn = parse_named(src, "foo");
        let bytes = rust_function_term_json(&foo_fn, "foo.rs").unwrap();
        let cid = rust_function_term_json_cid(&foo_fn, "foo.rs").unwrap();
        assert!(cid.starts_with("blake3-512:"));
        assert_eq!(bytes, rust_function_term_json(&foo_fn, "foo.rs").unwrap());
        assert_eq!(cid, rust_function_term_json_cid(&foo_fn, "foo.rs").unwrap());

        let parsed: serde_json::Value = serde_json::from_slice(&bytes).expect("valid JSON");
        assert_eq!(parsed["kind"].as_str(), Some("rust-algebra-term"));
        assert_eq!(
            parsed["signature_cid"].as_str(),
            Some(crate::signature::RUST_LANGUAGE_SIGNATURE_CID)
        );
        assert_eq!(
            parsed["term_surface"].as_str(),
            Some("seq(if(eq(x, 0), return(neg(22)), skip), return(x))")
        );
        assert_eq!(parsed["term"]["name"].as_str(), Some("seq"));
        assert_eq!(
            parsed["term"]["op_cid"].as_str(),
            crate::signature::op_cid("seq")
        );
    }

    #[test]
    fn overflowing_integer_literal_is_not_fabricated_as_zero() {
        let lit: syn::Lit = syn::parse_str("9223372036854775808").expect("parse integer literal");
        let term = literal_arg_term(&lit);

        assert_eq!(term["kind"].as_str(), Some("token-stream"));
        assert_eq!(term["surface"].as_str(), Some("9223372036854775808"));
        assert!(
            term.get("value").is_none(),
            "overflow must not mint value 0"
        );
    }

    #[test]
    fn rust_term_json_lowers_local_bindings() {
        let src = r#"
            fn with_let(x: i32) -> i32 { let y = x + 1; y }
        "#;
        let item_fn = parse_named(src, "with_let");
        let bytes = rust_function_term_json(&item_fn, "with_let.rs").unwrap();
        let parsed: serde_json::Value = serde_json::from_slice(&bytes).expect("valid JSON");
        assert_eq!(
            parsed["term_surface"].as_str(),
            Some("let(pattern_bind(y), add(x, 1), return(y))")
        );
    }

    #[test]
    fn rust_term_json_lowers_statement_position_method_call() {
        let src = r#"
            struct Sink;
            impl Sink {
                fn write(&mut self, value: i32) {}
            }
            fn caller(mut sink: Sink, value: i32) {
                sink.write(value);
            }
        "#;
        let item_fn = parse_named(src, "caller");
        let bytes = rust_function_term_json(&item_fn, "caller.rs").unwrap();
        let parsed: serde_json::Value = serde_json::from_slice(&bytes).expect("valid JSON");

        assert_eq!(
            parsed["term_surface"].as_str(),
            Some("let(pattern_bind(sink_v1), method:write(sink, [value]), skip)")
        );
        assert_eq!(parsed["term"]["name"].as_str(), Some("let"));
    }

    #[test]
    fn rust_term_json_lowers_boolean_and_as_logical_and() {
        let src = r#"
            fn g(a: bool, b: bool, c: bool) -> bool { a && b && c }
        "#;
        let item_fn = parse_named(src, "g");
        let bytes = rust_function_term_json(&item_fn, "g.rs").unwrap();
        let parsed: serde_json::Value = serde_json::from_slice(&bytes).expect("valid JSON");
        let surface = parsed["term_surface"].as_str().unwrap();
        assert_eq!(surface, "return(and(and(a, b), c))");
        assert!(!surface.contains("bit_and"));
    }

    #[test]
    fn rust_term_json_lowers_boolean_not_as_logical_not() {
        let src = r#"
            fn h(flag: bool) -> bool { !flag }
        "#;
        let item_fn = parse_named(src, "h");
        let bytes = rust_function_term_json(&item_fn, "h.rs").unwrap();
        let parsed: serde_json::Value = serde_json::from_slice(&bytes).expect("valid JSON");
        let surface = parsed["term_surface"].as_str().unwrap();
        assert_eq!(surface, "return(not(flag))");
        assert!(!surface.contains("bit_not"));
    }

    #[test]
    fn rust_term_json_lowers_nested_boolean_condition_as_logical_and() {
        let src = r#"
            fn choose(a: bool, b: bool, c: bool, x: i32) -> i32 {
                if a && b && c { x } else { 0 }
            }
        "#;
        let item_fn = parse_named(src, "choose");
        let bytes = rust_function_term_json(&item_fn, "choose.rs").unwrap();
        let parsed: serde_json::Value = serde_json::from_slice(&bytes).expect("valid JSON");
        let surface = parsed["term_surface"].as_str().unwrap();
        assert_eq!(
            surface,
            "seq(if(and(and(a, b), c), return(x), skip), return(0))"
        );
        assert!(!surface.contains("bit_and"));
    }

    #[test]
    fn rust_term_json_keeps_integer_not_as_bit_not() {
        let src = r#"
            fn invert(x: i32) -> i32 { !x }
        "#;
        let item_fn = parse_named(src, "invert");
        let bytes = rust_function_term_json(&item_fn, "invert.rs").unwrap();
        let parsed: serde_json::Value = serde_json::from_slice(&bytes).expect("valid JSON");
        assert_eq!(parsed["term_surface"].as_str(), Some("return(bit_not(x))"));
    }

    #[test]
    fn rust_term_json_distinct_for_distinct_sources() {
        let src_a = r#"
            fn foo(x: i32) -> i32 { if x == 0 { -22 } else { x } }
        "#;
        let src_b = r#"
            fn foo(x: i32) -> i32 { if x == 1 { -22 } else { x } }
        "#;
        let a_fn = parse_named(src_a, "foo");
        let b_fn = parse_named(src_b, "foo");
        let cid_a = rust_function_term_json_cid(&a_fn, "foo.rs").unwrap();
        let cid_b = rust_function_term_json_cid(&b_fn, "foo.rs").unwrap();
        assert_ne!(cid_a, cid_b);
    }

    #[test]
    fn proof_ir_round_trips_with_stable_cid() {
        let src = r#"
            fn f(x: u32) -> u32 { if x < 10 { panic!(); } x * 2 }
            fn main() { let y: u32 = 42; let result = f(y); }
        "#;
        let f_fn = parse_named(src, "f");
        let main_fn = parse_named(src, "main");
        let pre = lift_function_precondition(&f_fn);
        let s = build_shadow_source(
            &main_fn,
            &[CalleeContract {
                callee_name: "f".to_string(),
                formal_params: vec!["x".to_string()],
                precondition: pre,
            }],
        );
        let bytes = shadow_to_proof_ir(&s);
        let cid = shadow_proof_ir_cid(&s);
        assert!(!bytes.is_empty());
        assert!(cid.starts_with("blake3-512:"));
        // Stable across calls.
        assert_eq!(bytes, shadow_to_proof_ir(&s));
        assert_eq!(cid, shadow_proof_ir_cid(&s));
        // The bytes should parse as JSON.
        let parsed: serde_json::Value = serde_json::from_slice(&bytes).expect("valid JSON");
        assert_eq!(parsed["schemaVersion"].as_str(), Some("sugar-walk/1"));
        assert_eq!(parsed["shadowSourceCid"].as_str(), Some(s.cid.as_str()));
    }

    #[test]
    fn proof_ir_distinct_for_distinct_sources() {
        let src_a = r#"
            fn f(x: u32) -> u32 { if x < 10 { panic!(); } x * 2 }
            fn main() { let y: u32 = 42; let result = f(y); }
        "#;
        let src_b = r#"
            fn f(x: u32) -> u32 { if x < 20 { panic!(); } x * 3 }
            fn main() { let y: u32 = 99; let result = f(y); }
        "#;
        let make_bundle = |src: &str| {
            let f_fn = parse_named(src, "f");
            let main_fn = parse_named(src, "main");
            let pre = lift_function_precondition(&f_fn);
            let s = build_shadow_source(
                &main_fn,
                &[CalleeContract {
                    callee_name: "f".to_string(),
                    formal_params: vec!["x".to_string()],
                    precondition: pre,
                }],
            );
            shadow_proof_ir_cid(&s)
        };
        // Suppress unused-helper warning; both calls below.
        let _bare = atomic_ge(var("x"), const_int(10));
        assert_ne!(make_bundle(src_a), make_bundle(src_b));
    }

    // Bug #1: longest_chain must be deterministic when two callees produce
    // chains of equal length. With HashMap (random iteration) the tie-break
    // was non-deterministic; with BTreeMap it picks the lexicographically
    // first key every time.
    #[test]
    fn longest_chain_tie_break_is_deterministic() {
        let src = r#"
            fn f(x: u32) -> u32 { if x < 10 { panic!(); } x * 2 }
            fn g(y: u32) -> u32 { if y < 5  { panic!(); } y + 1 }
            fn main() {
                let a: u32 = 42;
                let b: u32 = 20;
                let r1 = f(a);
                let r2 = g(b);
            }
        "#;
        let f_fn = parse_named(src, "f");
        let g_fn = parse_named(src, "g");
        let main_fn = parse_named(src, "main");
        let pre_f = lift_function_precondition(&f_fn);
        let pre_g = lift_function_precondition(&g_fn);
        let s = build_shadow_source(
            &main_fn,
            &[
                CalleeContract {
                    callee_name: "f".to_string(),
                    formal_params: vec!["x".to_string()],
                    precondition: pre_f,
                },
                CalleeContract {
                    callee_name: "g".to_string(),
                    formal_params: vec!["y".to_string()],
                    precondition: pre_g,
                },
            ],
        );
        let bytes_first = shadow_to_proof_ir(&s);
        for _ in 0..50 {
            assert_eq!(
                bytes_first,
                shadow_to_proof_ir(&s),
                "bundle bytes must be deterministic across calls (tie-break in longest_chain)"
            );
        }
        let cid_first = shadow_proof_ir_cid(&s);
        for _ in 0..50 {
            assert_eq!(
                cid_first,
                shadow_proof_ir_cid(&s),
                "bundle CID must be deterministic across calls"
            );
        }
    }

    #[test]
    fn question_mark_emit_handler_decision_is_named_terminal_empty() {
        let decision = route_try_handler_context_decision();

        assert_eq!(decision.owner, "function-boundary");
        assert_eq!(decision.handlers_at_emit, 0);
        assert!(
            decision
                .reason
                .contains("propagates to the caller boundary"),
            "decision must argue why emit uses an empty handler set: {}",
            decision.reason
        );
    }
}

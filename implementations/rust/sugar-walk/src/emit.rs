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

    /// Claims each `AlgebraTerm` variant and serializes it to the matching
    /// JSON shape, in the same order and with the same fail-fast op-CID
    /// lookup as the original ladder. Every variant is a closed, local enum;
    /// there is no wildcard/default arm to fall through.
    fn to_json(&self) -> Result<JsonValue, String> {
        if let AlgebraTerm::Op { name, args } = self {
            let Some(cid) = op_cid(name) else {
                return Err(format!("operation `{name}` is not in the Rust signature"));
            };
            let args = args
                .iter()
                .map(AlgebraTerm::to_json)
                .collect::<Result<Vec<_>, _>>()?;
            return Ok(json!({
                "kind": "op",
                "name": name,
                "op_cid": cid,
                "args": args,
            }));
        }
        if let AlgebraTerm::Var(name) = self {
            return Ok(json!({"kind": "var", "name": name}));
        }
        if let AlgebraTerm::FullyQualifiedPath(path) = self {
            return Ok(json!({
                "concept": "concept:fully-qualified-path",
                "kind": "fully-qualified-path",
                "path": path,
            }));
        }
        if let AlgebraTerm::Symbol(name) = self {
            return Ok(json!({"kind": "symbol", "name": name}));
        }
        if let AlgebraTerm::List(items) = self {
            let items = items
                .iter()
                .map(AlgebraTerm::to_json)
                .collect::<Result<Vec<_>, _>>()?;
            return Ok(json!({"kind": "list", "items": items}));
        }
        if let AlgebraTerm::Struct { name, fields } = self {
            let fields = fields
                .iter()
                .map(|(field, value)| {
                    Ok(json!({
                        "name": field,
                        "value": value.to_json()?,
                    }))
                })
                .collect::<Result<Vec<_>, String>>()?;
            return Ok(json!({
                "kind": "struct",
                "name": name,
                "fields": fields,
            }));
        }
        if let AlgebraTerm::ConstInt(value) = self {
            return Ok(json!({
                "kind": "const",
                "value": value,
                "sort": {"kind": "ctor", "name": "Int", "args": []}
            }));
        }
        if let AlgebraTerm::ConstBool(value) = self {
            return Ok(json!({
                "kind": "const",
                "value": value,
                "sort": {"kind": "ctor", "name": "Bool", "args": []}
            }));
        }
        Ok(json!({"kind": "unit"}))
    }

    /// Claims each `AlgebraTerm` variant and renders its surface form, in the
    /// same order and with the same skip-op special case as the original
    /// ladder's guarded first arm. Every variant is a closed, local enum;
    /// there is no wildcard/default arm to fall through.
    fn surface(&self) -> String {
        if let AlgebraTerm::Op { name, args } = self {
            if name == "skip" && matches!(args.as_slice(), [AlgebraTerm::Unit]) {
                return "skip".to_string();
            }
            let args = args
                .iter()
                .map(AlgebraTerm::surface)
                .collect::<Vec<_>>()
                .join(", ");
            return format!("{name}({args})");
        }
        if let AlgebraTerm::Var(name) = self {
            return name.clone();
        }
        if let AlgebraTerm::FullyQualifiedPath(path) = self {
            return path.clone();
        }
        if let AlgebraTerm::Symbol(name) = self {
            return name.clone();
        }
        if let AlgebraTerm::List(items) = self {
            let items = items
                .iter()
                .map(AlgebraTerm::surface)
                .collect::<Vec<_>>()
                .join(", ");
            return format!("[{items}]");
        }
        if let AlgebraTerm::Struct { name, fields } = self {
            let fields = fields
                .iter()
                .map(|(field, value)| format!("{field}: {}", value.surface()))
                .collect::<Vec<_>>()
                .join(", ");
            return format!("{name}{{{fields}}}");
        }
        if let AlgebraTerm::ConstInt(value) = self {
            return value.to_string();
        }
        if let AlgebraTerm::ConstBool(value) = self {
            return value.to_string();
        }
        "unit".to_string()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ExprSort {
    Bool,
    Int,
    Unit,
}

impl ExprSort {
    /// Claims each closed `ExprSort` variant and names it; there is no
    /// wildcard/default arm to fall through.
    fn name(self) -> &'static str {
        if let ExprSort::Bool = self {
            return "Bool";
        }
        if let ExprSort::Int = self {
            return "Int";
        }
        "Unit"
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
    /// Claims each closed `ReturnShape` variant and extracts its scalar
    /// sort when there is one; there is no wildcard/default arm to fall
    /// through.
    fn sort(&self) -> Option<ExprSort> {
        if let ReturnShape::Full(sort) = self {
            return Some(*sort);
        }
        None
    }

    /// Claims each closed `ReturnShape` variant and renders its sort JSON;
    /// there is no wildcard/default arm to fall through.
    fn return_sort_json(&self) -> JsonValue {
        if let ReturnShape::Full(sort) = self {
            return sort.concept_sort().to_json();
        }
        if let ReturnShape::Partial { return_sort, .. } | ReturnShape::SortOnly(return_sort) = self
        {
            return return_sort.to_json();
        }
        JsonValue::Null
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
        if let syn::Item::Fn(item_fn) = item {
            if item_fn.sig.ident == name {
                return Some(TermFunctionContext {
                    item_fn: item_fn.clone(),
                    contextual_losses: inherited_losses.to_vec(),
                    ffi_declarations: ffi_declarations.clone(),
                    contextual_proc_macro_invocations: inherited_proc_macro_invocations.to_vec(),
                });
            }
            continue;
        }
        if let syn::Item::Impl(impl_block) = item {
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
            continue;
        }
        if let syn::Item::Mod(module) = item {
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
            continue;
        }
        if known_no_term_function_item(item) {
            continue;
        }
        panic!("sugar-walk emit find_term_function refused unknown syn::Item variant")
    }
    None
}

/// Item shapes that never carry a term function and never need recursion:
/// `Const`, `Enum`, `ExternCrate`, `ForeignMod`, `Fn` (handled above but also
/// matched here as a fallthrough guard), `Macro`, `Static`, `Struct`,
/// `Trait`, `TraitAlias`, `Type`, `Union`, `Use`, `Verbatim`.
fn known_no_term_function_item(item: &syn::Item) -> bool {
    matches!(
        item,
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
            | syn::Item::Verbatim(_)
    )
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
        if let syn::Item::ForeignMod(foreign_mod) = item {
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
            continue;
        }
        if let syn::Item::Mod(module) = item {
            if let Some((_, nested_items)) = &module.content {
                module_path.push(module.ident.to_string());
                collect_ffi_declarations_in_items(nested_items, module_path, declarations);
                module_path.pop();
            }
            continue;
        }
        if known_no_ffi_declaration_item(item) {
            continue;
        }
        panic!("sugar-walk emit ffi collector refused unknown syn::Item variant")
    }
}

/// Item shapes that never carry an FFI declaration and never need
/// recursion: `Const`, `Enum`, `ExternCrate`, `Fn`, `Impl`, `Macro`,
/// `Static`, `Struct`, `Trait`, `TraitAlias`, `Type`, `Union`, `Use`,
/// `Verbatim`.
fn known_no_ffi_declaration_item(item: &syn::Item) -> bool {
    matches!(
        item,
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
            | syn::Item::Verbatim(_)
    )
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
    if let syn::Item::Impl(item) = item {
        extend_proc_macro_invocations(invocations, &item.attrs);
        for impl_item in &item.items {
            if let syn::ImplItem::Const(item) = impl_item {
                extend_proc_macro_invocations(invocations, &item.attrs);
                continue;
            }
            if let syn::ImplItem::Fn(item) = impl_item {
                extend_proc_macro_invocations(invocations, &item.attrs);
                continue;
            }
            if let syn::ImplItem::Type(item) = impl_item {
                extend_proc_macro_invocations(invocations, &item.attrs);
                continue;
            }
            if matches!(
                impl_item,
                syn::ImplItem::Macro(_) | syn::ImplItem::Verbatim(_)
            ) {
                continue;
            }
            panic!("sugar-walk emit proc-macro collector refused unknown syn::ImplItem variant")
        }
        return;
    }
    if let syn::Item::Mod(item) = item {
        extend_proc_macro_invocations(invocations, &item.attrs);
        if let Some((_, items)) = &item.content {
            for item in items {
                collect_proc_macro_invocations_from_item(item, invocations);
            }
        }
        return;
    }
    let attrs: &[syn::Attribute] = if let syn::Item::Const(item) = item {
        &item.attrs
    } else if let syn::Item::Enum(item) = item {
        &item.attrs
    } else if let syn::Item::Fn(item) = item {
        &item.attrs
    } else if let syn::Item::Struct(item) = item {
        &item.attrs
    } else if let syn::Item::Trait(item) = item {
        &item.attrs
    } else if let syn::Item::Type(item) = item {
        &item.attrs
    } else if let syn::Item::Union(item) = item {
        &item.attrs
    } else if known_no_attrs_item(item) {
        &[]
    } else {
        panic!("sugar-walk emit proc-macro collector refused unknown syn::Item variant")
    };
    extend_proc_macro_invocations(invocations, attrs);
}

/// Item shapes that carry no attribute list worth scanning for proc-macro
/// invocations: `ExternCrate`, `ForeignMod`, `Macro`, `Static`,
/// `TraitAlias`, `Use`, `Verbatim`.
fn known_no_attrs_item(item: &syn::Item) -> bool {
    matches!(
        item,
        syn::Item::ExternCrate(_)
            | syn::Item::ForeignMod(_)
            | syn::Item::Macro(_)
            | syn::Item::Static(_)
            | syn::Item::TraitAlias(_)
            | syn::Item::Use(_)
            | syn::Item::Verbatim(_)
    )
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
    if let Expr::Path(path) = expr {
        return json!({"kind": "symbol", "name": rust_path_surface(&path.path)});
    }
    if let Expr::Lit(lit) = expr {
        return literal_arg_term(&lit.lit);
    }
    token_stream_term(normalize_attr_tokens(expr.to_token_stream().to_string()))
}

/// Claims the three literal shapes that carry a direct const encoding
/// (`Bool`/`Int`/`Str`); every other `syn::Lit` variant falls through to the
/// same fail-safe token-stream default as the original wildcard arm.
fn literal_arg_term(lit: &Lit) -> JsonValue {
    if let Lit::Bool(value) = lit {
        return json!({
            "kind": "const",
            "sort": {"kind": "ctor", "name": "Bool", "args": []},
            "value": value.value(),
        });
    }
    if let Lit::Int(value) = lit {
        return match value.base10_parse::<i64>() {
            Ok(parsed) => json!({
                "kind": "const",
                "sort": {"kind": "ctor", "name": "Int", "args": []},
                "value": parsed,
            }),
            Err(_) => token_stream_term(normalize_attr_tokens(value.to_token_stream().to_string())),
        };
    }
    if let Lit::Str(value) = lit {
        return json!({
            "kind": "const",
            "sort": {"kind": "ctor", "name": "String", "args": []},
            "value": value.value(),
        });
    }
    token_stream_term(normalize_attr_tokens(lit.to_token_stream().to_string()))
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
        if let Stmt::Expr(expr, None) = stmt {
            if is_tail {
                lowered.push(lower_tail_expr_to_stmt(expr, ctx)?);
                continue;
            }
        }
        if let Stmt::Expr(Expr::MethodCall(method), Some(_)) = stmt {
            let tail = lower_method_call_statement_to_stmt(method, &stmts[idx + 1..], ctx)?;
            return Ok(seq_all_then(lowered, tail));
        }
        if let Stmt::Expr(expr, _) = stmt {
            lowered.push(lower_expr_to_stmt(expr, ctx)?);
            continue;
        }
        if let Stmt::Local(local) = stmt {
            let tail = lower_local_binding_to_stmt(local, &stmts[idx + 1..], ctx)?;
            return Ok(seq_all_then(lowered, tail));
        }
        if let Stmt::Item(_) = stmt {
            continue;
        }
        if let Stmt::Macro(mac) = stmt {
            lowered.push(lower_macro_to_value_term(&mac.mac, ctx)?);
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
    if let Expr::Return(ret) = expr {
        let value = if let Some(value) = &ret.expr {
            lower_return_expr_to_value_term(value, ctx)?
        } else if ctx.return_shape.sort() == Some(ExprSort::Unit) {
            AlgebraTerm::Unit
        } else {
            return Err("bare return in non-unit function".to_string());
        };
        return Ok(AlgebraTerm::op("return", vec![value]));
    }
    if let Expr::If(if_expr) = expr {
        let cond = lower_expr_to_bool_term(&if_expr.cond, ctx)?;
        let then_branch = lower_stmts_to_stmt(&if_expr.then_branch.stmts, ctx)?;
        let else_branch = if let Some((_, else_expr)) = &if_expr.else_branch {
            lower_expr_to_stmt(else_expr, ctx)?
        } else {
            AlgebraTerm::skip()
        };
        return Ok(AlgebraTerm::op("if", vec![cond, then_branch, else_branch]));
    }
    if let Expr::Assign(assign) = expr {
        return lower_assign_expr_to_stmt(assign, ctx);
    }
    if let Expr::Block(block) = expr {
        return lower_stmts_to_stmt(&block.block.stmts, ctx);
    }
    if let Expr::ForLoop(for_loop) = expr {
        return lower_for_loop_to_stmt(for_loop, ctx);
    }
    if let Expr::Match(match_expr) = expr {
        return lower_match_to_stmt(match_expr, ctx);
    }
    if let Expr::Unsafe(unsafe_expr) = expr {
        return lower_stmts_to_stmt(&unsafe_expr.block.stmts, ctx);
    }
    if let Expr::MethodCall(method) = expr {
        if method.turbofish.is_some() {
            return Err(
                "unsupported statement-position method call with explicit turbofish".to_string(),
            );
        }
        return lower_method_call_expr_to_value_term(method, ctx);
    }
    if let Expr::Call(call) = expr {
        return lower_call_expr_to_value_term(call, ctx);
    }
    if let Expr::Macro(mac) = expr {
        return lower_macro_to_value_term(&mac.mac, ctx);
    }
    if let Expr::Try(try_expr) = expr {
        return lower_try_expr_to_stmt(try_expr, ctx);
    }
    if matches!(expr, Expr::Index(_) | Expr::Field(_)) {
        return lower_discarded_value_expr_to_stmt(expr, ctx);
    }
    if let Expr::Tuple(tuple) = expr {
        if tuple.elems.is_empty() {
            return Ok(AlgebraTerm::skip());
        }
        return lower_discarded_value_expr_to_stmt(expr, ctx);
    }
    if matches!(expr, Expr::Array(_) | Expr::Reference(_)) {
        return lower_discarded_value_expr_to_stmt(expr, ctx);
    }
    if matches!(expr, Expr::Path(_) | Expr::Lit(_)) {
        return Ok(AlgebraTerm::skip());
    }
    Err(format!(
        "unsupported expression statement {}",
        expr_kind(expr)
    ))
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

/// Claims a `Path`, or recurses through `MethodCall`/`Paren`/`Group`/
/// `Field`/`Reference`/deref-`Unary` to find the source name of a method
/// receiver. Every shape in `known_non_receiver_source_expr` is a
/// recognized non-source (`None`); the trailing panic default is unchanged.
fn method_receiver_source_name(expr: &Expr) -> Option<String> {
    if let Expr::Path(path) = expr {
        return path_name(path);
    }
    if let Expr::MethodCall(method) = expr {
        return method_receiver_source_name(&method.receiver);
    }
    if let Expr::Paren(paren) = expr {
        return method_receiver_source_name(&paren.expr);
    }
    if let Expr::Group(group) = expr {
        return method_receiver_source_name(&group.expr);
    }
    if let Expr::Field(field) = expr {
        return method_receiver_source_name(&field.base);
    }
    if let Expr::Reference(reference) = expr {
        return method_receiver_source_name(&reference.expr);
    }
    if let Expr::Unary(unary) = expr {
        if matches!(unary.op, UnOp::Deref(_)) {
            return method_receiver_source_name(&unary.expr);
        }
        return None;
    }
    if known_non_receiver_source_expr(expr) {
        return None;
    }
    panic!("sugar-walk emit receiver source refused unknown syn::Expr variant")
}

/// Shapes that can never resolve to a method receiver source name: neither
/// the source itself nor a transparent wrapper (`Paren`/`Group`/`Field`/
/// `Reference`/deref-`Unary`) around one.
fn known_non_receiver_source_expr(expr: &Expr) -> bool {
    matches!(
        expr,
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
            | Expr::Yield(_)
    )
}

/// Claims a mutably-borrowed `Path`/`Field`, or recurses through `Paren`/
/// `Group` wrappers to find one. Every shape in
/// `known_non_mut_borrow_source_expr` is a recognized non-source (`None`);
/// the trailing panic default is unchanged.
fn mut_borrow_source_name(expr: &Expr) -> Option<String> {
    let Expr::Reference(reference) = expr else {
        return None;
    };
    reference.mutability.as_ref()?;
    let inner = &*reference.expr;
    if let Expr::Path(path) = inner {
        return path_name(path);
    }
    if let Expr::Paren(paren) = inner {
        return mut_borrow_source_name(&paren.expr);
    }
    if let Expr::Group(group) = inner {
        return mut_borrow_source_name(&group.expr);
    }
    if let Expr::Field(field) = inner {
        return method_receiver_source_name(&field.base);
    }
    if known_non_mut_borrow_source_expr(inner) {
        return None;
    }
    panic!("sugar-walk emit mutable borrow source refused unknown syn::Expr variant")
}

/// Shapes that can never resolve to a mutable-borrow source name: neither
/// the source itself nor a transparent `Paren`/`Group` wrapper around one.
fn known_non_mut_borrow_source_expr(expr: &Expr) -> bool {
    matches!(
        expr,
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
            | Expr::Yield(_)
    )
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

/// Claims an empty-tuple or empty-block match-arm body as a no-op `skip`
/// term; every other shape falls through to the same fail-safe
/// `lower_expr_to_stmt` default as the original wildcard arm.
fn lower_match_arm_body_to_stmt(expr: &Expr, ctx: &LoweringContext) -> Result<AlgebraTerm, String> {
    if let Expr::Tuple(tuple) = expr {
        if tuple.elems.is_empty() {
            return Ok(AlgebraTerm::skip());
        }
    }
    if let Expr::Block(block) = expr {
        if block.block.stmts.is_empty() {
            return Ok(AlgebraTerm::skip());
        }
    }
    lower_expr_to_stmt(expr, ctx)
}

fn lower_return_expr_to_value_term(
    expr: &Expr,
    ctx: &LoweringContext,
) -> Result<AlgebraTerm, String> {
    if let ReturnShape::Full(sort) = &ctx.return_shape {
        if *sort == ExprSort::Bool {
            if matches!(expr, Expr::Call(_) | Expr::MethodCall(_) | Expr::Unsafe(_)) {
                return lower_expr_to_value_term(expr, ctx);
            }
            return lower_expr_to_bool_term(expr, ctx);
        }
        if *sort == ExprSort::Int {
            if matches!(expr, Expr::Call(_) | Expr::MethodCall(_) | Expr::Unsafe(_)) {
                return lower_expr_to_value_term(expr, ctx);
            }
            return lower_expr_to_int_term(expr, ctx);
        }
        return lower_expr_to_unit_term(expr, ctx);
    }
    if matches!(
        ctx.return_shape,
        ReturnShape::Partial { .. } | ReturnShape::SortOnly(_)
    ) {
        return lower_expr_to_value_term(expr, ctx);
    }
    Err("unsupported function return type for term emission".to_string())
}

fn lower_expr_to_bool_term(expr: &Expr, ctx: &LoweringContext) -> Result<AlgebraTerm, String> {
    if let Expr::Binary(binary) = expr {
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
        return Err(format!("unsupported boolean operator: {:?}", binary.op));
    }
    if let Expr::Unary(unary) = expr {
        if matches!(unary.op, UnOp::Not(_)) {
            return Ok(AlgebraTerm::op(
                "not",
                vec![lower_expr_to_bool_term(&unary.expr, ctx)?],
            ));
        }
    }
    if matches!(expr, Expr::Field(_)) {
        ctx.add_loss("type-inference-assumed-bool", expr_kind(expr));
        return lower_expr_to_value_term(expr, ctx);
    }
    if let Expr::Let(let_expr) = expr {
        return lower_let_expr_to_bool_term(let_expr, ctx);
    }
    if let Expr::Macro(mac) = expr {
        return lower_macro_to_value_term(&mac.mac, ctx);
    }
    if let Expr::Match(match_expr) = expr {
        return lower_match_to_bool_term(match_expr, ctx);
    }
    if let Expr::Paren(paren) = expr {
        return lower_expr_to_bool_term(&paren.expr, ctx);
    }
    if let Expr::Block(block) = expr {
        let Some(tail) = block_single_tail_expr(&block.block) else {
            return Err("block expression has no single tail expression".to_string());
        };
        return lower_expr_to_bool_term(tail, ctx);
    }
    if let Expr::Lit(lit) = expr {
        if let Lit::Bool(value) = &lit.lit {
            return Ok(AlgebraTerm::ConstBool(value.value));
        }
        return Err("non-bool literal in boolean term".to_string());
    }
    if let Expr::Path(path) = expr {
        let term = path_term_for_expr(path, ctx)
            .ok_or_else(|| "empty path in boolean term".to_string())?;
        if let AlgebraTerm::Var(name) = &term {
            if let Some(sort) = ctx.vars.get(name).copied() {
                if sort == ExprSort::Bool {
                    return Ok(term);
                }
                return Err(format!(
                    "expected Bool path in boolean term, found {} for `{name}`",
                    sort.name()
                ));
            }
            ctx.add_loss("type-inference-assumed-bool", name.clone());
            return Ok(term);
        }
        if let AlgebraTerm::FullyQualifiedPath(path) = &term {
            ctx.add_loss("type-inference-assumed-bool", path.clone());
            return Ok(term);
        }
        unreachable!("path term must be a var or fully qualified path");
    }
    if matches!(expr, Expr::Call(_) | Expr::MethodCall(_)) {
        ctx.add_loss("type-inference-assumed-bool", expr_kind(expr));
        return lower_expr_to_value_term(expr, ctx);
    }
    Err(format!(
        "unsupported boolean expression {}",
        expr_kind(expr)
    ))
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
    if let Expr::Tuple(tuple) = expr {
        if tuple.elems.is_empty() {
            return Ok(AlgebraTerm::Unit);
        }
    }
    if let Expr::Block(block) = expr {
        if block.block.stmts.is_empty() {
            return Ok(AlgebraTerm::Unit);
        }
    }
    if let Expr::Unsafe(unsafe_expr) = expr {
        return lower_stmts_to_stmt(&unsafe_expr.block.stmts, ctx);
    }
    if matches!(expr, Expr::ForLoop(_) | Expr::If(_) | Expr::Match(_)) {
        return lower_expr_to_stmt(expr, ctx);
    }
    Err(format!("unsupported unit expression {}", expr_kind(expr)))
}

fn lower_expr_to_value_term(expr: &Expr, ctx: &LoweringContext) -> Result<AlgebraTerm, String> {
    if let Expr::Lit(lit) = expr {
        if let Lit::Int(value) = &lit.lit {
            return value
                .base10_parse::<i64>()
                .map(AlgebraTerm::ConstInt)
                .map_err(|err| format!("integer literal does not fit i64: {err}"));
        }
        if let Lit::Bool(value) = &lit.lit {
            return Ok(AlgebraTerm::ConstBool(value.value));
        }
        return Err("unsupported literal expression".to_string());
    }
    if let Expr::Path(path) = expr {
        return path_term_for_expr(path, ctx).ok_or_else(|| "empty path expression".to_string());
    }
    if let Expr::Paren(paren) = expr {
        return lower_expr_to_value_term(&paren.expr, ctx);
    }
    if let Expr::Group(group) = expr {
        return lower_expr_to_value_term(&group.expr, ctx);
    }
    if let Expr::Block(block) = expr {
        let Some(tail) = block_single_tail_expr(&block.block) else {
            return Err("block expression has no single tail expression".to_string());
        };
        return lower_expr_to_value_term(tail, ctx);
    }
    if let Expr::Unsafe(unsafe_expr) = expr {
        let Some(tail) = block_single_tail_expr(&unsafe_expr.block) else {
            return Err("unsafe block expression has no single tail expression".to_string());
        };
        return lower_expr_to_value_term(tail, ctx);
    }
    if let Expr::Unary(unary) = expr {
        let op = if matches!(unary.op, UnOp::Neg(_)) {
            "neg"
        } else if matches!(unary.op, UnOp::Not(_)) {
            let sort = expr_sort(&unary.expr, ctx);
            if sort == Some(ExprSort::Int) {
                "bit_not"
            } else if sort == Some(ExprSort::Bool) {
                return Err("logical ! used in value position".to_string());
            } else if sort == Some(ExprSort::Unit) {
                return Err("unary ! is unsupported for Unit".to_string());
            } else {
                return Err(
                    "cannot determine whether unary ! is Bool or Int; skipping term".to_string(),
                );
            }
        } else if matches!(unary.op, UnOp::Deref(_)) {
            "deref"
        } else {
            return Err(format!("unsupported unary operator: {:?}", unary.op));
        };
        return Ok(AlgebraTerm::op(
            op,
            vec![lower_expr_to_value_term(&unary.expr, ctx)?],
        ));
    }
    if let Expr::Binary(binary) = expr {
        let op = arithmetic_binary_op(&binary.op)
            .or_else(|| bitwise_binary_op(&binary.op))
            .or_else(|| comparison_op(&binary.op));
        let Some(op) = op else {
            return Err(format!("unsupported value operator: {:?}", binary.op));
        };
        return Ok(AlgebraTerm::op(
            op,
            vec![
                lower_expr_to_int_term(&binary.left, ctx)?,
                lower_expr_to_int_term(&binary.right, ctx)?,
            ],
        ));
    }
    if let Expr::Call(call) = expr {
        return lower_call_expr_to_value_term(call, ctx);
    }
    if let Expr::MethodCall(method) = expr {
        return lower_method_call_expr_to_value_term(method, ctx);
    }
    if let Expr::Closure(closure) = expr {
        if closure.asyncness.is_some() {
            return Err("unsupported async closure in value position".to_string());
        }
        if closure.capture.is_some() {
            return Err("unsupported move closure in value position".to_string());
        }
        let mut params = Vec::new();
        let mut closure_ctx = ctx.clone();
        for input in &closure.inputs {
            let bindings = closure_param_bindings(input, closure.inputs.len() == 1)?;
            for (name, sort) in bindings {
                closure_ctx = closure_ctx.with_var(name.clone(), sort);
                params.push(AlgebraTerm::Symbol(name));
            }
        }
        ctx.add_loss(
            "closure-captures-environment",
            closure.to_token_stream().to_string(),
        );
        return Ok(AlgebraTerm::op(
            "closure",
            vec![
                AlgebraTerm::List(params),
                lower_expr_to_value_term(&closure.body, &closure_ctx)?,
            ],
        ));
    }
    if let Expr::Array(array) = expr {
        let items = array
            .elems
            .iter()
            .map(|expr| lower_expr_to_value_term(expr, ctx))
            .collect::<Result<Vec<_>, _>>()?;
        return Ok(AlgebraTerm::op("array", vec![AlgebraTerm::List(items)]));
    }
    if let Expr::Repeat(repeat) = expr {
        return Ok(AlgebraTerm::op(
            "array_repeat",
            vec![
                lower_expr_to_value_term(&repeat.expr, ctx)?,
                lower_expr_to_int_term(&repeat.len, ctx)?,
            ],
        ));
    }
    if let Expr::Tuple(tuple) = expr {
        if tuple.elems.is_empty() {
            return Ok(AlgebraTerm::Unit);
        }
        let items = tuple
            .elems
            .iter()
            .map(|expr| lower_expr_to_value_term(expr, ctx))
            .collect::<Result<Vec<_>, _>>()?;
        return Ok(AlgebraTerm::op("tuple", vec![AlgebraTerm::List(items)]));
    }
    if let Expr::Struct(strukt) = expr {
        return lower_struct_expr_to_value_term(strukt, ctx);
    }
    if let Expr::Field(field) = expr {
        return Ok(AlgebraTerm::op(
            "field",
            vec![
                lower_expr_to_value_term(&field.base, ctx)?,
                AlgebraTerm::Symbol(field.member.to_token_stream().to_string()),
            ],
        ));
    }
    if let Expr::Index(index) = expr {
        return Ok(AlgebraTerm::op(
            "index",
            vec![
                lower_expr_to_value_term(&index.expr, ctx)?,
                lower_expr_to_int_term(&index.index, ctx)?,
            ],
        ));
    }
    if let Expr::Try(try_expr) = expr {
        return lower_try_expr_to_value_term(try_expr, ctx);
    }
    if let Expr::Macro(mac) = expr {
        return lower_macro_to_value_term(&mac.mac, ctx);
    }
    if let Expr::Match(match_expr) = expr {
        return lower_match_to_value_term(match_expr, ctx);
    }
    if let Expr::Reference(reference) = expr {
        let op = if reference.mutability.is_some() {
            "borrow_mut"
        } else {
            "borrow"
        };
        return Ok(AlgebraTerm::op(
            op,
            vec![lower_expr_to_value_term(&reference.expr, ctx)?],
        ));
    }
    if matches!(expr, Expr::Cast(_)) {
        return Err("unsupported value expression Expr::Cast".to_string());
    }
    Err(format!("unsupported value expression {}", expr_kind(expr)))
}

fn closure_param_bindings(
    input: &syn::Pat,
    single_input: bool,
) -> Result<Vec<(String, Option<ExprSort>)>, String> {
    if let syn::Pat::Ident(ident) = input {
        return Ok(vec![(ident.ident.to_string(), None)]);
    }
    if let syn::Pat::Type(pat_type) = input {
        return typed_closure_param_binding(pat_type).map(|binding| vec![binding]);
    }
    if let syn::Pat::Tuple(tuple) = input {
        if !single_input {
            return Err("unsupported closure parameter destructuring pattern".to_string());
        }
        let mut tuple_bindings = Vec::new();
        for elem in &tuple.elems {
            if let syn::Pat::Ident(ident) = elem {
                tuple_bindings.push((ident.ident.to_string(), None));
            } else if let syn::Pat::Type(pat_type) = elem {
                tuple_bindings.push(typed_closure_param_binding(pat_type)?);
            } else {
                return Err("unsupported closure parameter destructuring pattern".to_string());
            }
        }
        return Ok(tuple_bindings);
    }
    Err("unsupported closure parameter destructuring pattern".to_string())
}

fn typed_closure_param_binding(
    pat_type: &syn::PatType,
) -> Result<(String, Option<ExprSort>), String> {
    let syn::Pat::Ident(ident) = &*pat_type.pat else {
        return Err("unsupported closure parameter destructuring pattern".to_string());
    };
    Ok((ident.ident.to_string(), sort_from_type(&pat_type.ty)))
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

/// Claims each `syn::Pat` variant that lowers to a specific pattern term
/// shape; every other variant falls through to the same fail-safe
/// `pattern_bind`-on-token-stream default as the original wildcard arm.
fn lower_pat_to_pattern_term(pat: &syn::Pat) -> AlgebraTerm {
    if let syn::Pat::Ident(ident) = pat {
        return AlgebraTerm::op(
            "pattern_bind",
            vec![AlgebraTerm::Symbol(ident.ident.to_string())],
        );
    }
    if let syn::Pat::Lit(lit) = pat {
        return AlgebraTerm::op(
            "pattern_bind",
            vec![AlgebraTerm::Symbol(lit.to_token_stream().to_string())],
        );
    }
    if let syn::Pat::Path(path) = pat {
        return AlgebraTerm::op(
            "pattern_bind",
            vec![AlgebraTerm::Symbol(path.to_token_stream().to_string())],
        );
    }
    if let syn::Pat::Reference(reference) = pat {
        return lower_pat_to_pattern_term(&reference.pat);
    }
    if let syn::Pat::TupleStruct(tuple) = pat {
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
        return match name.as_deref() {
            Some("Ok") => AlgebraTerm::op("pattern_ok", args),
            Some("Err") => AlgebraTerm::op("pattern_err", args),
            Some("Some") => AlgebraTerm::op("pattern_some", args),
            Some("None") => AlgebraTerm::op("pattern_none", args),
            _ => AlgebraTerm::op(
                "pattern_bind",
                vec![AlgebraTerm::Symbol(tuple.to_token_stream().to_string())],
            ),
        };
    }
    if let syn::Pat::Type(pat_type) = pat {
        return lower_pat_to_pattern_term(&pat_type.pat);
    }
    if let syn::Pat::Wild(_) = pat {
        return AlgebraTerm::op("pattern_wild", vec![]);
    }
    AlgebraTerm::op(
        "pattern_bind",
        vec![AlgebraTerm::Symbol(pat.to_token_stream().to_string())],
    )
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
    if let Expr::Lit(lit) = expr {
        return lit_expr_sort(&lit.lit);
    }
    if let Expr::Path(path) = expr {
        return local_path_name_for_expr(path, ctx).and_then(|name| ctx.vars.get(&name).copied());
    }
    if let Expr::Paren(paren) = expr {
        return expr_sort(&paren.expr, ctx);
    }
    if let Expr::Group(group) = expr {
        return expr_sort(&group.expr, ctx);
    }
    if let Expr::Block(block) = expr {
        return block_single_tail_expr(&block.block).and_then(|expr| expr_sort(expr, ctx));
    }
    if let Expr::Unary(unary) = expr {
        if matches!(unary.op, UnOp::Neg(_)) {
            return (expr_sort(&unary.expr, ctx) == Some(ExprSort::Int)).then_some(ExprSort::Int);
        }
        if matches!(unary.op, UnOp::Not(_)) {
            let sort = expr_sort(&unary.expr, ctx);
            if sort == Some(ExprSort::Bool) {
                return Some(ExprSort::Bool);
            }
            if sort == Some(ExprSort::Int) {
                return Some(ExprSort::Int);
            }
            // #3017 item 8 owns the predicate-vs-raw-term split that would let
            // unknown `!x` classify without guessing.
            return None;
        }
        if matches!(unary.op, UnOp::Deref(_)) {
            return expr_sort(&unary.expr, ctx);
        }
        panic!("sugar-walk emit expr_sort refused unknown syn::UnOp variant");
    }
    if let Expr::Binary(binary) = expr {
        if arithmetic_binary_op(&binary.op).is_some() || bitwise_binary_op(&binary.op).is_some() {
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
        return None;
    }
    if known_unsorted_expr(expr) {
        return None;
    }
    panic!("sugar-walk emit expr_sort refused unknown syn::Expr variant")
}

fn lit_expr_sort(lit: &Lit) -> Option<ExprSort> {
    if matches!(lit, Lit::Bool(_)) {
        return Some(ExprSort::Bool);
    }
    if matches!(lit, Lit::Int(_) | Lit::Byte(_) | Lit::Char(_)) {
        return Some(ExprSort::Int);
    }
    if matches!(
        lit,
        Lit::Float(_) | Lit::Str(_) | Lit::ByteStr(_) | Lit::CStr(_) | Lit::Verbatim(_)
    ) {
        // #3017 item 2 owns richer scalar floors; ExprSort only proves the
        // current Unit/Bool/Int subset.
        return None;
    }
    panic!("sugar-walk emit expr_sort refused unknown syn::Lit variant")
}

fn known_unsorted_expr(expr: &Expr) -> bool {
    matches!(
        expr,
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
            | Expr::Yield(_)
    )
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

/// Claims each closed `syn::ReturnType` variant; there is no
/// wildcard/default arm to fall through.
fn return_shape_from_return_type(output: &ReturnType) -> ReturnShape {
    if let ReturnType::Default = output {
        return ReturnShape::Full(ExprSort::Unit);
    }
    let ReturnType::Type(_, ty) = output else {
        unreachable!("sugar-walk emit return shape: only Default and Type variants exist")
    };
    if let Some(sort) = sort_from_type(ty) {
        return ReturnShape::Full(sort);
    }
    if let Some(loss) = partial_return_loss(ty) {
        return ReturnShape::Partial {
            loss,
            rust_type: type_surface(ty),
            return_sort: concept_sort_from_type(ty)
                .unwrap_or_else(|| ConceptSort::new(type_surface(ty), Vec::new())),
        };
    }
    if let Some(return_sort) = concept_sort_from_type(ty) {
        return ReturnShape::SortOnly(return_sort);
    }
    ReturnShape::Unsupported
}

/// Claims a bare path type name or recurses through `Paren`/`Group`
/// wrappers, and claims an empty tuple as `Unit`. Every shape in
/// `known_non_scalar_sort_type` is a recognized sort-neutral non-source
/// (`None`, kept out of this scalar classifier per #3017 item 2); the
/// trailing panic default is unchanged.
fn sort_from_type(ty: &Type) -> Option<ExprSort> {
    if let Type::Path(path) = ty {
        if path.qself.is_none() {
            let ident = path.path.segments.last()?.ident.to_string();
            return sort_from_type_name(&ident);
        }
        return None;
    }
    if let Type::Paren(paren) = ty {
        return sort_from_type(&paren.elem);
    }
    if let Type::Group(group) = ty {
        return sort_from_type(&group.elem);
    }
    if let Type::Tuple(tuple) = ty {
        if tuple.elems.is_empty() {
            return Some(ExprSort::Unit);
        }
        return None;
    }
    if known_non_scalar_sort_type(ty) {
        // #3017 item 2 keeps non-primitive and sort-neutral values out of
        // this scalar classifier; concept_sort_from_type carries them.
        return None;
    }
    panic!("sugar-walk emit sort_from_type refused unknown syn::Type variant")
}

/// Shapes that never carry a scalar `ExprSort` and never need recursion:
/// `Array`, `BareFn`, `ImplTrait`, `Infer`, `Macro`, `Never`, `Ptr`,
/// `Reference`, `Slice`, `TraitObject`, `Verbatim`.
fn known_non_scalar_sort_type(ty: &Type) -> bool {
    matches!(
        ty,
        Type::Array(_)
            | Type::BareFn(_)
            | Type::ImplTrait(_)
            | Type::Infer(_)
            | Type::Macro(_)
            | Type::Never(_)
            | Type::Ptr(_)
            | Type::Reference(_)
            | Type::Slice(_)
            | Type::TraitObject(_)
            | Type::Verbatim(_)
    )
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

/// Claims each `syn::Type` variant that lowers to a `ConceptSort`, in the
/// same order as the original ladder. Every shape in
/// `known_non_concept_sort_type` is a recognized non-source (`None`); the
/// trailing panic default is unchanged.
fn concept_sort_from_type(ty: &Type) -> Option<ConceptSort> {
    if let Type::Path(path) = ty {
        if path.qself.is_none() {
            let segment = path.path.segments.last()?;
            let ident = segment.ident.to_string();
            let name = match concept_sort_name_from_type_name(&ident) {
                Some(name) => name,
                None => ident,
            };
            return Some(ConceptSort::new(
                name,
                concept_sort_args_from_path_segment(segment)?,
            ));
        }
        return None;
    }
    if let Type::Reference(reference) = ty {
        let name = if reference.mutability.is_some() {
            "RefMut"
        } else {
            "Ref"
        };
        return Some(ConceptSort::new(
            name,
            vec![concept_sort_from_type(&reference.elem)?],
        ));
    }
    if let Type::Array(array) = ty {
        return Some(ConceptSort::new(
            "Array",
            vec![concept_sort_from_type(&array.elem)?],
        ));
    }
    if let Type::Slice(slice) = ty {
        return Some(ConceptSort::new(
            "Slice",
            vec![concept_sort_from_type(&slice.elem)?],
        ));
    }
    if let Type::Ptr(ptr) = ty {
        let name = if ptr.mutability.is_some() {
            "PtrMut"
        } else {
            "Ptr"
        };
        return Some(ConceptSort::new(
            name,
            vec![concept_sort_from_type(&ptr.elem)?],
        ));
    }
    if let Type::Tuple(tuple) = ty {
        if tuple.elems.is_empty() {
            return Some(ExprSort::Unit.concept_sort());
        }
        return Some(ConceptSort::new(
            "Tuple",
            tuple
                .elems
                .iter()
                .map(concept_sort_from_type)
                .collect::<Option<Vec<_>>>()?,
        ));
    }
    if let Type::Paren(paren) = ty {
        return concept_sort_from_type(&paren.elem);
    }
    if let Type::Group(group) = ty {
        return concept_sort_from_type(&group.elem);
    }
    if known_non_concept_sort_type(ty) {
        return None;
    }
    panic!("sugar-walk emit concept_sort refused unknown syn::Type variant")
}

/// Shapes that never carry a `ConceptSort`: `BareFn`, `ImplTrait`, `Infer`,
/// `Macro`, `Never`, `Path` (only reachable via a qualified-self path,
/// handled above), `TraitObject`, `Verbatim`.
fn known_non_concept_sort_type(ty: &Type) -> bool {
    matches!(
        ty,
        Type::BareFn(_)
            | Type::ImplTrait(_)
            | Type::Infer(_)
            | Type::Macro(_)
            | Type::Never(_)
            | Type::Path(_)
            | Type::TraitObject(_)
            | Type::Verbatim(_)
    )
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

/// Claims a bare `Result`/`Option`/`Vec` path type, a `u8` array, or
/// recurses through `Reference`/`Paren`/`Group` wrappers to find one. Every
/// shape in `known_no_partial_return_loss_type` is a recognized non-source
/// (`None`); the trailing panic default is unchanged.
fn partial_return_loss(ty: &Type) -> Option<&'static str> {
    if let Type::Path(path) = ty {
        if path.qself.is_none() {
            let segment = path.path.segments.last()?;
            let ident = segment.ident.to_string();
            if ident == "Result" {
                return Some("return-type-result");
            }
            if ident == "Option" {
                return Some("return-type-option");
            }
            if ident == "Vec" {
                if path_type_arg_is_u8(segment) {
                    return Some("return-type-byte-vec");
                }
                return Some("return-type-vec");
            }
            // sugar-audit: not-mine(non-container-return-type-has-no-partial-loss-record)
            return None;
        }
        return None;
    }
    if let Type::Array(array) = ty {
        if type_is_u8(&array.elem) {
            return Some("return-type-byte-array");
        }
        return None;
    }
    if let Type::Reference(reference) = ty {
        return partial_return_loss(&reference.elem);
    }
    if let Type::Paren(paren) = ty {
        return partial_return_loss(&paren.elem);
    }
    if let Type::Group(group) = ty {
        return partial_return_loss(&group.elem);
    }
    if known_no_partial_return_loss_type(ty) {
        return None;
    }
    panic!("sugar-walk emit partial_return_loss refused unknown syn::Type variant")
}

/// Shapes that never carry a partial-return loss record and never need
/// recursion: `Array` (non-`u8`, handled above), `BareFn`, `ImplTrait`,
/// `Infer`, `Macro`, `Never`, `Path` (non-container, handled above), `Ptr`,
/// `Slice`, `TraitObject`, `Tuple`, `Verbatim`.
fn known_no_partial_return_loss_type(ty: &Type) -> bool {
    matches!(
        ty,
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
            | Type::Verbatim(_)
    )
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

/// Claims `Ident`/`Type`/`Wild` let-binding patterns; every other pattern
/// falls through to the same fail-safe `Err` default as the original
/// wildcard arm.
fn lower_local_let_pattern(
    pat: &syn::Pat,
    ctx: &LoweringContext,
) -> Result<LocalLetPattern, String> {
    if let syn::Pat::Ident(ident) = pat {
        let name = ident.ident.to_string();
        let is_mutable = ident.mutability.is_some();
        if ident.mutability.is_some() {
            ctx.add_loss(LOSS_LET_BINDING_MUTABILITY, name.clone());
        }
        return Ok(LocalLetPattern::Bind { name, is_mutable });
    }
    if let syn::Pat::Type(pat_type) = pat {
        return lower_local_let_pattern(&pat_type.pat, ctx);
    }
    if let syn::Pat::Wild(_) = pat {
        return Ok(LocalLetPattern::Wild);
    }
    Err("unsupported let-binding pattern".to_string())
}

/// Claims a `syn::Pat::Type` annotation; every shape in
/// `known_no_pat_type` carries no type annotation of its own (`None`); the
/// trailing panic default is unchanged.
fn local_pat_type(pat: &syn::Pat) -> Option<&Type> {
    if let syn::Pat::Type(pat_type) = pat {
        return Some(&pat_type.ty);
    }
    if known_no_pat_type(pat) {
        return None;
    }
    panic!("sugar-walk emit local_pat_type refused unknown syn::Pat variant")
}

/// Pattern shapes that never carry their own type annotation: `Const`,
/// `Ident`, `Lit`, `Macro`, `Or`, `Paren`, `Path`, `Range`, `Reference`,
/// `Rest`, `Slice`, `Struct`, `Tuple`, `TupleStruct`, `Verbatim`, `Wild`.
fn known_no_pat_type(pat: &syn::Pat) -> bool {
    matches!(
        pat,
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
            | syn::Pat::Wild(_)
    )
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
    if matches!(expr, Expr::Array(_)) {
        return "Expr::Array";
    }
    if matches!(expr, Expr::Assign(_)) {
        return "Expr::Assign";
    }
    if matches!(expr, Expr::Async(_)) {
        return "Expr::Async";
    }
    if matches!(expr, Expr::Await(_)) {
        return "Expr::Await";
    }
    if matches!(expr, Expr::Binary(_)) {
        return "Expr::Binary";
    }
    if matches!(expr, Expr::Block(_)) {
        return "Expr::Block";
    }
    if matches!(expr, Expr::Break(_)) {
        return "Expr::Break";
    }
    if matches!(expr, Expr::Call(_)) {
        return "Expr::Call";
    }
    if matches!(expr, Expr::Cast(_)) {
        return "Expr::Cast";
    }
    if matches!(expr, Expr::Closure(_)) {
        return "Expr::Closure";
    }
    if matches!(expr, Expr::Const(_)) {
        return "Expr::Const";
    }
    if matches!(expr, Expr::Continue(_)) {
        return "Expr::Continue";
    }
    if matches!(expr, Expr::Field(_)) {
        return "Expr::Field";
    }
    if matches!(expr, Expr::ForLoop(_)) {
        return "Expr::ForLoop";
    }
    if matches!(expr, Expr::Group(_)) {
        return "Expr::Group";
    }
    if matches!(expr, Expr::If(_)) {
        return "Expr::If";
    }
    if matches!(expr, Expr::Index(_)) {
        return "Expr::Index";
    }
    if matches!(expr, Expr::Infer(_)) {
        return "Expr::Infer";
    }
    if matches!(expr, Expr::Let(_)) {
        return "Expr::Let";
    }
    if matches!(expr, Expr::Lit(_)) {
        return "Expr::Lit";
    }
    if matches!(expr, Expr::Loop(_)) {
        return "Expr::Loop";
    }
    if matches!(expr, Expr::Macro(_)) {
        return "Expr::Macro";
    }
    if matches!(expr, Expr::Match(_)) {
        return "Expr::Match";
    }
    if matches!(expr, Expr::MethodCall(_)) {
        return "Expr::MethodCall";
    }
    if matches!(expr, Expr::Paren(_)) {
        return "Expr::Paren";
    }
    if matches!(expr, Expr::Path(_)) {
        return "Expr::Path";
    }
    if matches!(expr, Expr::Range(_)) {
        return "Expr::Range";
    }
    if matches!(expr, Expr::Reference(_)) {
        return "Expr::Reference";
    }
    if matches!(expr, Expr::Repeat(_)) {
        return "Expr::Repeat";
    }
    if matches!(expr, Expr::Return(_)) {
        return "Expr::Return";
    }
    if matches!(expr, Expr::Struct(_)) {
        return "Expr::Struct";
    }
    if matches!(expr, Expr::Try(_)) {
        return "Expr::Try";
    }
    if matches!(expr, Expr::TryBlock(_)) {
        return "Expr::TryBlock";
    }
    if matches!(expr, Expr::Tuple(_)) {
        return "Expr::Tuple";
    }
    if matches!(expr, Expr::Unary(_)) {
        return "Expr::Unary";
    }
    if matches!(expr, Expr::Unsafe(_)) {
        return "Expr::Unsafe";
    }
    if matches!(expr, Expr::Verbatim(_)) {
        return "Expr::Verbatim";
    }
    if matches!(expr, Expr::While(_)) {
        return "Expr::While";
    }
    if matches!(expr, Expr::Yield(_)) {
        return "Expr::Yield";
    }
    "Expr::<unknown>"
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

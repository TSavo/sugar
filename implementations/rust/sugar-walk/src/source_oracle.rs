// SPDX-License-Identifier: Apache-2.0
//! Rust `SourceOracle`: emits and resolves `SourceMemento`s.
//!
//! A memento is a pointer into source: file, span, function name, parameter
//! names, and recomputable CIDs. It never carries source text or serialized AST
//! content. Consumers re-read the authoritative source file and recompute the
//! CIDs to prove the pointer still names the same body.

use std::collections::BTreeMap;

use quote::ToTokens;
use serde_json::{json, Value};
use sugar_canonicalizer::blake3_512_of;
use syn::spanned::Spanned;

/// A source span, 1-based line / 0-based column.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SrcSpan {
    pub start_line: usize,
    pub start_col: usize,
    pub end_line: usize,
    pub end_col: usize,
}

/// The oracle-side source fragment. This is the materialized form that may carry
/// source body text and an AST template. It is never emitted as a memento.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SourceFragment {
    pub file: String,
    pub function_name: String,
    pub span: SrcSpan,
    pub param_names: Vec<String>,
    pub body_text: String,
    pub ast_template: Value,
}

impl SourceFragment {
    pub fn to_memento(&self) -> SourceMemento {
        SourceMemento {
            file: self.file.clone(),
            function_name: self.function_name.clone(),
            span: self.span.clone(),
            param_names: self.param_names.clone(),
            source_cid: blake3_512_of(self.body_text.as_bytes()),
            template_cid: blake3_512_of(self.ast_template.to_string().as_bytes()),
        }
    }
}

/// Content-addressed pointer to a Rust source function body.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SourceMemento {
    pub file: String,
    pub function_name: String,
    pub span: SrcSpan,
    pub param_names: Vec<String>,
    pub source_cid: String,
    pub template_cid: String,
}

impl SourceMemento {
    pub fn source_function_name(&self) -> Option<&str> {
        (!self.function_name.is_empty()).then_some(self.function_name.as_str())
    }

    pub fn to_json(&self) -> Value {
        let mut value = json!({
            "kind": "source-memento",
            "file": self.file,
            "span": {
                "start_line": self.span.start_line,
                "start_col": self.span.start_col,
                "end_line": self.span.end_line,
                "end_col": self.span.end_col,
            },
            "paramNames": self.param_names,
            "param_names": self.param_names,
            "source_cid": self.source_cid,
            "template_cid": self.template_cid,
        });
        if let Some(name) = self.source_function_name() {
            value["sourceFunctionName"] = json!(name);
            value["source_function_name"] = json!(name);
        }
        value
    }

    pub fn to_body_source_json(&self) -> Value {
        json!({
            "file": self.file,
            "span": {
                "start_line": self.span.start_line,
                "start_col": self.span.start_col,
                "end_line": self.span.end_line,
                "end_col": self.span.end_col,
            },
            "source_cid": self.source_cid,
            "template_cid": self.template_cid,
            "param_names": self.param_names,
        })
    }

    pub fn from_body_source(
        source_function_name: Option<String>,
        body_source: &Value,
    ) -> Option<Self> {
        let file = body_source.get("file").and_then(Value::as_str)?.to_string();
        let span = body_source.get("span")?;
        let param_names = body_source
            .get("param_names")
            .or_else(|| body_source.get("paramNames"))
            .and_then(Value::as_array)
            .map(|arr| {
                arr.iter()
                    .filter_map(Value::as_str)
                    .map(str::to_string)
                    .collect()
            })
            .unwrap_or_default();
        Some(SourceMemento {
            file,
            function_name: source_function_name.unwrap_or_default(),
            span: SrcSpan {
                start_line: span.get("start_line").and_then(Value::as_u64).unwrap_or(0) as usize,
                start_col: span.get("start_col").and_then(Value::as_u64).unwrap_or(0) as usize,
                end_line: span.get("end_line").and_then(Value::as_u64).unwrap_or(0) as usize,
                end_col: span.get("end_col").and_then(Value::as_u64).unwrap_or(0) as usize,
            },
            source_cid: body_source
                .get("source_cid")
                .or_else(|| body_source.get("sourceCid"))
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            template_cid: body_source
                .get("template_cid")
                .or_else(|| body_source.get("templateCid"))
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            param_names,
        })
    }
}

/// A typed refusal from the SourceOracle.
#[derive(Debug)]
pub struct SourceOracleRefusal {
    pub reason: String,
}

/// The reconstructed source fragment plus recomputed pins.
#[derive(Debug)]
pub struct ResolvedSource {
    pub fragment: SourceFragment,
    pub source_cid: String,
    pub template_cid: String,
    pub param_names: Vec<String>,
}

impl ResolvedSource {
    pub fn body_text(&self) -> &str {
        &self.fragment.body_text
    }

    pub fn ast_template(&self) -> &Value {
        &self.fragment.ast_template
    }
}

/// Immutable source view used to mint many mementos from the same file.
///
/// There is no invalidation path by design: a lift request works over one
/// parsed source string. If the source changes, the caller constructs a new
/// view for the next request.
#[derive(Debug)]
pub struct SourceTextIndex<'a> {
    src: &'a str,
    line_starts: Vec<usize>,
}

impl<'a> SourceTextIndex<'a> {
    pub fn new(src: &'a str) -> Self {
        Self {
            src,
            line_starts: line_starts(src),
        }
    }

    pub fn source_memento_of(
        &self,
        file_rel: &str,
        span: proc_macro2::Span,
        name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> SourceMemento {
        self.source_fragment_of(file_rel, span, name, sig, block)
            .to_memento()
    }

    pub fn source_memento_of_statement_span(
        &self,
        file_rel: &str,
        span: proc_macro2::Span,
        owner_name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> Option<SourceMemento> {
        self.source_fragment_of_statement_span(file_rel, span, owner_name, sig, block)
            .map(|fragment| fragment.to_memento())
    }

    pub fn source_fragment_of_statement_span(
        &self,
        file_rel: &str,
        span: proc_macro2::Span,
        owner_name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> Option<SourceFragment> {
        let target = span_to_src_span(span);
        self.source_fragment_of_statement_src_span(file_rel, &target, owner_name, sig, block)
    }

    fn source_fragment_of_statement_src_span(
        &self,
        file_rel: &str,
        target: &SrcSpan,
        owner_name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> Option<SourceFragment> {
        let params = param_names_without_receiver_from_signature(sig);
        let stmt = find_stmt_by_span(block, target)?;
        Some(self.source_fragment_of_stmt(file_rel, owner_name, &params, stmt))
    }

    pub fn source_fragment_of(
        &self,
        file_rel: &str,
        span: proc_macro2::Span,
        name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> SourceFragment {
        let start = span.start();
        let end = block.brace_token.span.close().end();
        let param_names = param_names_without_receiver_from_signature(sig);
        let body_text = self
            .block_inner_source(block)
            .map(canonical_sugar_body_text)
            .unwrap_or_default()
            .to_string();
        let ast_template = block_to_ast_template(block, &param_names);
        SourceFragment {
            file: file_rel.to_string(),
            function_name: name.to_string(),
            span: SrcSpan {
                start_line: start.line,
                start_col: start.column,
                end_line: end.line,
                end_col: end.column,
            },
            param_names,
            body_text,
            ast_template,
        }
    }

    pub fn source_fragment_of_stmt(
        &self,
        file_rel: &str,
        owner_name: &str,
        param_names: &[String],
        stmt: &syn::Stmt,
    ) -> SourceFragment {
        let span = span_to_src_span(stmt.span());
        let body_text = self
            .source_slice_between(stmt.span().start(), stmt.span().end())
            .map(canonical_sugar_body_text)
            .unwrap_or_default()
            .to_string();
        let ast_template = stmt_to_template(stmt, param_names);
        SourceFragment {
            file: file_rel.to_string(),
            function_name: owner_name.to_string(),
            span,
            param_names: param_names.to_vec(),
            body_text,
            ast_template,
        }
    }

    pub fn block_inner_source(&self, block: &syn::Block) -> Option<&'a str> {
        let open_end = block.brace_token.span.open().end();
        let close_start = block.brace_token.span.close().start();
        self.source_slice_between(open_end, close_start)
    }

    pub fn source_slice_between(
        &self,
        start: proc_macro2::LineColumn,
        end: proc_macro2::LineColumn,
    ) -> Option<&'a str> {
        let start = self.line_column_to_byte_offset(start)?;
        let end = self.line_column_to_byte_offset(end)?;
        if start <= end {
            self.src.get(start..end)
        } else {
            None
        }
    }

    pub fn line_column_to_byte_offset(&self, loc: proc_macro2::LineColumn) -> Option<usize> {
        line_column_to_byte_offset_with_starts(self.src, &self.line_starts, loc)
    }
}

#[derive(Clone, Debug)]
struct CachedSourceFragment {
    fragment: SourceFragment,
    source_text: String,
    line_starts: Vec<usize>,
}

/// Request-scoped source-fragment cache.
///
/// A fragment can be minted from an existing cached fragment when its absolute
/// source span is contained by the cached fragment's span. The cache is immutable
/// with respect to source bytes: callers create a fresh cache for each source
/// snapshot, so there is no invalidation path.
#[derive(Debug)]
pub struct SourceFragmentCache<'a> {
    index: SourceTextIndex<'a>,
    fragments: BTreeMap<(usize, usize), CachedSourceFragment>,
}

impl<'a> SourceFragmentCache<'a> {
    pub fn new(src: &'a str) -> Self {
        Self {
            index: SourceTextIndex::new(src),
            fragments: BTreeMap::new(),
        }
    }

    pub fn source_memento_of(
        &mut self,
        file_rel: &str,
        span: proc_macro2::Span,
        name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> SourceMemento {
        self.source_fragment_of(file_rel, span, name, sig, block)
            .to_memento()
    }

    pub fn source_memento_of_statement_span(
        &mut self,
        file_rel: &str,
        span: proc_macro2::Span,
        owner_name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> Option<SourceMemento> {
        self.source_fragment_of_statement_span(file_rel, span, owner_name, sig, block)
            .map(|fragment| fragment.to_memento())
    }

    pub fn source_fragment_of(
        &mut self,
        file_rel: &str,
        span: proc_macro2::Span,
        name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> SourceFragment {
        let fragment = self
            .index
            .source_fragment_of(file_rel, span, name, sig, block);
        let source_text = self
            .index
            .source_slice_between(span.start(), block.brace_token.span.close().end())
            .unwrap_or_default()
            .to_string();
        self.insert_fragment(fragment.clone(), source_text);
        fragment
    }

    pub fn source_fragment_of_statement_span(
        &mut self,
        file_rel: &str,
        span: proc_macro2::Span,
        owner_name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> Option<SourceFragment> {
        let target = span_to_src_span(span);
        let params = param_names_without_receiver_from_signature(sig);
        let stmt = find_stmt_by_span(block, &target)?;
        Some(self.source_fragment_of_stmt(file_rel, owner_name, &params, stmt))
    }

    pub fn source_fragment_of_stmt(
        &mut self,
        file_rel: &str,
        owner_name: &str,
        param_names: &[String],
        stmt: &syn::Stmt,
    ) -> SourceFragment {
        let span = span_to_src_span(stmt.span());
        let source_text = self
            .source_text_from_cached_fragment(&span)
            .unwrap_or_else(|| {
                self.index
                    .source_slice_between(stmt.span().start(), stmt.span().end())
                    .unwrap_or_default()
                    .to_string()
            });
        let body_text = canonical_sugar_body_text(&source_text).to_string();
        let fragment = SourceFragment {
            file: file_rel.to_string(),
            function_name: owner_name.to_string(),
            span,
            param_names: param_names.to_vec(),
            body_text,
            ast_template: stmt_to_template(stmt, param_names),
        };
        self.insert_fragment(fragment.clone(), source_text);
        fragment
    }

    fn insert_fragment(&mut self, fragment: SourceFragment, source_text: String) {
        let key = span_start_key(&fragment.span);
        let cached = CachedSourceFragment {
            fragment,
            line_starts: line_starts(&source_text),
            source_text,
        };
        self.fragments.insert(key, cached);
    }

    fn source_text_from_cached_fragment(&self, target: &SrcSpan) -> Option<String> {
        for (_, cached) in self.fragments.range(..=span_start_key(target)).rev() {
            if !span_contains(&cached.fragment.span, target) {
                continue;
            }
            let start =
                relative_line_column(&cached.fragment.span, target.start_line, target.start_col)?;
            let end = relative_line_column(&cached.fragment.span, target.end_line, target.end_col)?;
            let start = line_column_to_byte_offset_with_starts(
                &cached.source_text,
                &cached.line_starts,
                start,
            )?;
            let end = line_column_to_byte_offset_with_starts(
                &cached.source_text,
                &cached.line_starts,
                end,
            )?;
            if start <= end {
                return cached.source_text.get(start..end).map(str::to_string);
            }
        }
        None
    }
}

fn span_start_key(span: &SrcSpan) -> (usize, usize) {
    (span.start_line, span.start_col)
}

fn span_contains(parent: &SrcSpan, child: &SrcSpan) -> bool {
    span_position_le(
        parent.start_line,
        parent.start_col,
        child.start_line,
        child.start_col,
    ) && span_position_le(
        child.end_line,
        child.end_col,
        parent.end_line,
        parent.end_col,
    )
}

fn span_position_le(
    left_line: usize,
    left_col: usize,
    right_line: usize,
    right_col: usize,
) -> bool {
    (left_line, left_col) <= (right_line, right_col)
}

fn relative_line_column(
    parent: &SrcSpan,
    line: usize,
    column: usize,
) -> Option<proc_macro2::LineColumn> {
    if line < parent.start_line {
        return None;
    }
    let relative_line = line - parent.start_line + 1;
    let relative_column = if line == parent.start_line {
        column.checked_sub(parent.start_col)?
    } else {
        column
    };
    Some(proc_macro2::LineColumn {
        line: relative_line,
        column: relative_column,
    })
}

pub fn source_memento_of(
    file_rel: &str,
    src: &str,
    span: proc_macro2::Span,
    name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> SourceMemento {
    SourceTextIndex::new(src)
        .source_fragment_of(file_rel, span, name, sig, block)
        .to_memento()
}

pub fn source_memento_of_statement_span(
    file_rel: &str,
    src: &str,
    span: proc_macro2::Span,
    owner_name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> Option<SourceMemento> {
    SourceTextIndex::new(src)
        .source_fragment_of_statement_span(file_rel, span, owner_name, sig, block)
        .map(|fragment| fragment.to_memento())
}

pub fn source_fragment_of_statement_span(
    file_rel: &str,
    src: &str,
    span: proc_macro2::Span,
    owner_name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> Option<SourceFragment> {
    SourceTextIndex::new(src)
        .source_fragment_of_statement_span(file_rel, span, owner_name, sig, block)
}

pub fn source_fragment_of(
    file_rel: &str,
    src: &str,
    span: proc_macro2::Span,
    name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> SourceFragment {
    SourceTextIndex::new(src).source_fragment_of(file_rel, span, name, sig, block)
}

pub fn source_fragment_of_stmt(
    file_rel: &str,
    src: &str,
    owner_name: &str,
    param_names: &[String],
    stmt: &syn::Stmt,
) -> SourceFragment {
    SourceTextIndex::new(src).source_fragment_of_stmt(file_rel, owner_name, param_names, stmt)
}

fn span_to_src_span(span: proc_macro2::Span) -> SrcSpan {
    let start = span.start();
    let end = span.end();
    SrcSpan {
        start_line: start.line,
        start_col: start.column,
        end_line: end.line,
        end_col: end.column,
    }
}

pub fn source_memento_of_item_fn(file_rel: &str, src: &str, item: &syn::ItemFn) -> SourceMemento {
    source_memento_of_named_item_fn(file_rel, src, &item.sig.ident.to_string(), item)
}

pub fn source_memento_of_named_item_fn(
    file_rel: &str,
    src: &str,
    name: &str,
    item: &syn::ItemFn,
) -> SourceMemento {
    source_memento_of(
        file_rel,
        src,
        function_surface_span(&item.attrs, item.sig.fn_token.span),
        name,
        &item.sig,
        &item.block,
    )
}

pub fn source_fragment_of_item_fn(file_rel: &str, src: &str, item: &syn::ItemFn) -> SourceFragment {
    source_fragment_of_named_item_fn(file_rel, src, &item.sig.ident.to_string(), item)
}

pub fn source_fragment_of_named_item_fn(
    file_rel: &str,
    src: &str,
    name: &str,
    item: &syn::ItemFn,
) -> SourceFragment {
    source_fragment_of(
        file_rel,
        src,
        function_surface_span(&item.attrs, item.sig.fn_token.span),
        name,
        &item.sig,
        &item.block,
    )
}

pub fn param_names_without_receiver(item_fn: &syn::ItemFn) -> Vec<String> {
    param_names_without_receiver_from_signature(&item_fn.sig)
}

pub fn param_names_without_receiver_from_signature(sig: &syn::Signature) -> Vec<String> {
    sig.inputs
        .iter()
        .filter_map(|arg| match arg {
            syn::FnArg::Typed(pat_ty) => match &*pat_ty.pat {
                syn::Pat::Ident(pid) => Some(pid.ident.to_string()),
                _ => None,
            },
            syn::FnArg::Receiver(_) => None,
        })
        .collect()
}

pub fn resolve_source_memento(
    project_root: &std::path::Path,
    memento: &SourceMemento,
) -> Result<ResolvedSource, SourceOracleRefusal> {
    let path = project_root.join(&memento.file);
    let src = std::fs::read_to_string(&path).map_err(|e| SourceOracleRefusal {
        reason: format!("cannot read source `{}`: {e}", path.display()),
    })?;
    let file = syn::parse_file(&src).map_err(|e| SourceOracleRefusal {
        reason: format!("cannot parse source `{}`: {e}", path.display()),
    })?;
    let source_fn = locate_source_fn(&file.items, memento).ok_or_else(|| SourceOracleRefusal {
        reason: format!(
            "source function `{}` not found in `{}` near line {}",
            memento.source_function_name().unwrap_or("<any>"),
            memento.file,
            memento.span.start_line
        ),
    })?;

    let source_index = SourceTextIndex::new(&src);
    let whole_fragment = source_index.source_fragment_of(
        &memento.file,
        source_fn.span,
        memento
            .source_function_name()
            .unwrap_or(&source_fn.full_name),
        source_fn.sig,
        source_fn.block,
    );
    let fragment = if source_span_eq(&memento.span, &whole_fragment.span) {
        whole_fragment
    } else {
        source_index
            .source_fragment_of_statement_src_span(
                &memento.file,
                &memento.span,
                memento
                    .source_function_name()
                    .unwrap_or(&source_fn.full_name),
                source_fn.sig,
                source_fn.block,
            )
            .ok_or_else(|| SourceOracleRefusal {
                reason: format!(
                    "source fragment for `{}` not found in `{}` at line {}",
                    memento.source_function_name().unwrap_or("<any>"),
                    memento.file,
                    memento.span.start_line
                ),
            })?
    };
    let recomputed = fragment.to_memento();
    let recomputed_source_cid = recomputed.source_cid;
    let recomputed_template_cid = recomputed.template_cid;

    if !memento.source_cid.is_empty() && recomputed_source_cid != memento.source_cid {
        return Err(SourceOracleRefusal {
            reason: format!(
                "source CID misaligned for `{}` in `{}`: pinned {}, on-disk {recomputed_source_cid} -- the source drifted from the proof",
                memento.source_function_name().unwrap_or("<any>"),
                memento.file,
                memento.source_cid
            ),
        });
    }
    if !memento.template_cid.is_empty() && recomputed_template_cid != memento.template_cid {
        return Err(SourceOracleRefusal {
            reason: format!(
                "template CID misaligned for `{}` in `{}`: pinned {}, on-disk {recomputed_template_cid} -- the AST drifted from the proof",
                memento.source_function_name().unwrap_or("<any>"),
                memento.file,
                memento.template_cid
            ),
        });
    }

    Ok(ResolvedSource {
        param_names: fragment.param_names.clone(),
        fragment,
        source_cid: recomputed_source_cid,
        template_cid: recomputed_template_cid,
    })
}

fn source_span_eq(a: &SrcSpan, b: &SrcSpan) -> bool {
    a.start_line == b.start_line
        && a.start_col == b.start_col
        && a.end_line == b.end_line
        && a.end_col == b.end_col
}

struct SourceFnRef<'a> {
    full_name: String,
    leaf_name: String,
    span: proc_macro2::Span,
    start_line: usize,
    end_line: usize,
    sig: &'a syn::Signature,
    block: &'a syn::Block,
}

fn locate_source_fn<'a>(
    items: &'a [syn::Item],
    memento: &SourceMemento,
) -> Option<SourceFnRef<'a>> {
    let mut matches = Vec::new();
    collect_source_fns(items, &mut matches);
    let wanted = memento.source_function_name();
    matches.retain(|candidate| {
        wanted.is_none_or(|name| {
            candidate.full_name == name
                || candidate.leaf_name == name
                || candidate.full_name.ends_with(&format!("::{name}"))
        })
    });
    if matches.is_empty() {
        return None;
    }
    if matches.len() > 1 && memento.span.start_line > 0 {
        for candidate in &matches {
            if candidate.start_line <= memento.span.start_line
                && memento.span.start_line <= candidate.end_line
            {
                return Some(SourceFnRef {
                    full_name: candidate.full_name.clone(),
                    leaf_name: candidate.leaf_name.clone(),
                    span: candidate.span,
                    start_line: candidate.start_line,
                    end_line: candidate.end_line,
                    sig: candidate.sig,
                    block: candidate.block,
                });
            }
        }
    }
    matches.into_iter().next()
}

fn collect_source_fns<'a>(items: &'a [syn::Item], out: &mut Vec<SourceFnRef<'a>>) {
    collect_source_fns_in_scope(items, &mut Vec::new(), out);
}

fn collect_source_fns_in_scope<'a>(
    items: &'a [syn::Item],
    modules: &mut Vec<String>,
    out: &mut Vec<SourceFnRef<'a>>,
) {
    for item in items {
        match item {
            syn::Item::Fn(item_fn) => {
                out.push(source_fn_ref(
                    scoped_source_name(modules, &item_fn.sig.ident.to_string()),
                    item_fn.sig.ident.to_string(),
                    function_surface_span(&item_fn.attrs, item_fn.sig.fn_token.span),
                    &item_fn.sig,
                    &item_fn.block,
                ));
            }
            syn::Item::Impl(impl_block) => {
                let qualifier = impl_self_ty_name(&impl_block.self_ty);
                for impl_item in &impl_block.items {
                    let syn::ImplItem::Fn(method) = impl_item else {
                        continue;
                    };
                    let leaf = method.sig.ident.to_string();
                    out.push(source_fn_ref(
                        scoped_source_name(modules, &format!("{qualifier}::{leaf}")),
                        leaf,
                        function_surface_span(&method.attrs, method.sig.fn_token.span),
                        &method.sig,
                        &method.block,
                    ));
                }
            }
            syn::Item::Mod(module) => {
                if let Some((_, nested)) = &module.content {
                    modules.push(module.ident.to_string());
                    collect_source_fns_in_scope(nested, modules, out);
                    modules.pop();
                }
            }
            syn::Item::Trait(item_trait) => {
                let qualifier = item_trait.ident.to_string();
                for trait_item in &item_trait.items {
                    let syn::TraitItem::Fn(method) = trait_item else {
                        continue;
                    };
                    let Some(block) = &method.default else {
                        continue;
                    };
                    let leaf = method.sig.ident.to_string();
                    out.push(source_fn_ref(
                        scoped_source_name(modules, &format!("{qualifier}::{leaf}")),
                        leaf,
                        function_surface_span(&method.attrs, method.sig.fn_token.span),
                        &method.sig,
                        block,
                    ));
                }
            }
            _ => {}
        }
    }
}

fn scoped_source_name(modules: &[String], name: &str) -> String {
    if modules.is_empty() {
        name.to_string()
    } else {
        format!("{}::{name}", modules.join("::"))
    }
}

fn source_fn_ref<'a>(
    full_name: String,
    leaf_name: String,
    span: proc_macro2::Span,
    sig: &'a syn::Signature,
    block: &'a syn::Block,
) -> SourceFnRef<'a> {
    SourceFnRef {
        full_name,
        leaf_name,
        span,
        start_line: span.start().line,
        end_line: block.brace_token.span.close().end().line,
        sig,
        block,
    }
}

fn function_surface_span(
    attrs: &[syn::Attribute],
    fallback: proc_macro2::Span,
) -> proc_macro2::Span {
    attrs.first().map_or(fallback, |attr| attr.span())
}

fn find_stmt_by_span<'a>(block: &'a syn::Block, target: &SrcSpan) -> Option<&'a syn::Stmt> {
    struct Finder<'a> {
        target: SrcSpan,
        found: Option<&'a syn::Stmt>,
    }
    impl<'a> syn::visit::Visit<'a> for Finder<'a> {
        fn visit_stmt(&mut self, stmt: &'a syn::Stmt) {
            if self.found.is_some() {
                return;
            }
            if source_span_eq(&span_to_src_span(stmt.span()), &self.target) {
                self.found = Some(stmt);
                return;
            }
            syn::visit::visit_stmt(self, stmt);
        }
    }

    let mut finder = Finder {
        target: target.clone(),
        found: None,
    };
    syn::visit::Visit::visit_block(&mut finder, block);
    finder.found
}

fn impl_self_ty_name(ty: &syn::Type) -> String {
    if let syn::Type::Path(path) = ty {
        if let Some(segment) = path.path.segments.last() {
            return segment.ident.to_string();
        }
    }
    ty.to_token_stream().to_string().replace(' ', "")
}

pub fn canonical_sugar_body_text(body: &str) -> &str {
    body.trim()
}

pub fn block_to_ast_template(block: &syn::Block, params: &[String]) -> Value {
    let stmts: Vec<Value> = block
        .stmts
        .iter()
        .map(|stmt| stmt_to_template(stmt, params))
        .collect();
    json!({ "kind": "block", "stmts": stmts })
}

fn stmt_to_template(stmt: &syn::Stmt, params: &[String]) -> Value {
    use syn::Stmt;
    match stmt {
        Stmt::Local(local) => {
            let pat = pat_to_template(&local.pat, params);
            let init = local
                .init
                .as_ref()
                .map(|init| expr_to_template(&init.expr, params))
                .unwrap_or(Value::Null);
            json!({ "kind": "let", "pat": pat, "init": init })
        }
        Stmt::Item(_) => json!({ "kind": "item" }),
        Stmt::Expr(expr, semi) => {
            let inner = expr_to_template(expr, params);
            let trailing = semi.is_some();
            json!({ "kind": "expr_stmt", "expr": inner, "trailing_semi": trailing })
        }
        Stmt::Macro(m) => {
            let path = path_to_template(&m.mac.path);
            json!({ "kind": "macro_stmt", "path": path })
        }
    }
}

fn expr_to_template(expr: &syn::Expr, params: &[String]) -> Value {
    use syn::Expr;
    match expr {
        Expr::Call(c) => {
            let func = expr_to_template(&c.func, params);
            let args: Vec<Value> = c.args.iter().map(|a| expr_to_template(a, params)).collect();
            json!({ "kind": "call", "func": func, "args": args })
        }
        Expr::MethodCall(m) => {
            let receiver = expr_to_template(&m.receiver, params);
            let method = m.method.to_string();
            let args: Vec<Value> = m.args.iter().map(|a| expr_to_template(a, params)).collect();
            json!({
                "kind": "method_call",
                "receiver": receiver,
                "method": method,
                "args": args,
            })
        }
        Expr::Path(p) => {
            let segs: Vec<String> = p
                .path
                .segments
                .iter()
                .map(|s| s.ident.to_string())
                .collect();
            if segs.len() == 1 {
                if let Some(idx) = params.iter().position(|n| n == &segs[0]) {
                    return json!({ "kind": "param_ref", "index": idx + 1 });
                }
                return json!({ "kind": "ident", "name": segs[0] });
            }
            json!({ "kind": "path", "segments": segs })
        }
        Expr::Lit(l) => lit_to_template(&l.lit),
        Expr::Reference(r) => {
            let inner = expr_to_template(&r.expr, params);
            json!({ "kind": "ref", "mutability": r.mutability.is_some(), "expr": inner })
        }
        Expr::Try(t) => {
            let inner = expr_to_template(&t.expr, params);
            json!({ "kind": "try", "expr": inner })
        }
        Expr::Block(b) => block_to_ast_template(&b.block, params),
        Expr::Paren(p) => expr_to_template(&p.expr, params),
        Expr::Tuple(t) => {
            let elems: Vec<Value> = t
                .elems
                .iter()
                .map(|e| expr_to_template(e, params))
                .collect();
            json!({ "kind": "tuple", "elems": elems })
        }
        Expr::Array(a) => {
            let elems: Vec<Value> = a
                .elems
                .iter()
                .map(|e| expr_to_template(e, params))
                .collect();
            json!({ "kind": "array", "elems": elems })
        }
        Expr::Closure(_) => json!({ "kind": "closure" }),
        Expr::Match(_) => json!({ "kind": "match" }),
        Expr::If(_) => json!({ "kind": "if" }),
        Expr::Return(r) => {
            let inner = r
                .expr
                .as_ref()
                .map(|e| expr_to_template(e, params))
                .unwrap_or(Value::Null);
            json!({ "kind": "return", "expr": inner })
        }
        Expr::Binary(b) => {
            let left = expr_to_template(&b.left, params);
            let right = expr_to_template(&b.right, params);
            let op = format!("{:?}", b.op);
            json!({ "kind": "binary", "op": op, "left": left, "right": right })
        }
        Expr::Unary(u) => {
            let inner = expr_to_template(&u.expr, params);
            let op = format!("{:?}", u.op);
            json!({ "kind": "unary", "op": op, "expr": inner })
        }
        Expr::Field(f) => {
            let base = expr_to_template(&f.base, params);
            let member = match &f.member {
                syn::Member::Named(n) => n.to_string(),
                syn::Member::Unnamed(u) => u.index.to_string(),
            };
            json!({ "kind": "field", "base": base, "member": member })
        }
        Expr::Macro(m) => {
            let path = path_to_template(&m.mac.path);
            json!({ "kind": "macro", "path": path })
        }
        other => json!({
            "kind": "other",
            "variant": format!("{:?}", std::mem::discriminant(other)),
        }),
    }
}

fn pat_to_template(pat: &syn::Pat, params: &[String]) -> Value {
    use syn::Pat;
    match pat {
        Pat::Ident(pi) => {
            let name = pi.ident.to_string();
            if let Some(idx) = params.iter().position(|n| n == &name) {
                json!({ "kind": "param_ref", "index": idx + 1 })
            } else {
                json!({ "kind": "binding", "name": name })
            }
        }
        Pat::Wild(_) => json!({ "kind": "wildcard" }),
        Pat::Tuple(t) => {
            let elems: Vec<Value> = t.elems.iter().map(|p| pat_to_template(p, params)).collect();
            json!({ "kind": "pat_tuple", "elems": elems })
        }
        _ => json!({ "kind": "pat_other" }),
    }
}

fn path_to_template(path: &syn::Path) -> Value {
    let segs: Vec<String> = path.segments.iter().map(|s| s.ident.to_string()).collect();
    json!({ "segments": segs })
}

fn lit_to_template(lit: &syn::Lit) -> Value {
    match lit {
        syn::Lit::Str(s) => json!({ "kind": "lit_str", "value": s.value() }),
        syn::Lit::Int(i) => json!({ "kind": "lit_int", "value": i.base10_digits() }),
        syn::Lit::Bool(b) => json!({ "kind": "lit_bool", "value": b.value }),
        syn::Lit::Char(c) => json!({ "kind": "lit_char", "value": c.value().to_string() }),
        syn::Lit::Float(f) => json!({ "kind": "lit_float", "value": f.base10_digits() }),
        _ => json!({ "kind": "lit_other" }),
    }
}

pub fn block_inner_source<'a>(src: &'a str, block: &syn::Block) -> Option<&'a str> {
    let open_end = block.brace_token.span.open().end();
    let close_start = block.brace_token.span.close().start();
    source_slice_between(src, open_end, close_start)
}

pub fn source_slice_between(
    src: &str,
    start: proc_macro2::LineColumn,
    end: proc_macro2::LineColumn,
) -> Option<&str> {
    SourceTextIndex::new(src).source_slice_between(start, end)
}

pub fn line_column_to_byte_offset(src: &str, loc: proc_macro2::LineColumn) -> Option<usize> {
    SourceTextIndex::new(src).line_column_to_byte_offset(loc)
}

fn line_column_to_byte_offset_with_starts(
    src: &str,
    line_starts: &[usize],
    loc: proc_macro2::LineColumn,
) -> Option<usize> {
    if loc.line == 0 {
        return None;
    }

    let line_start = *line_starts.get(loc.line - 1)?;
    let line_end = line_starts
        .get(loc.line)
        .copied()
        .map(|next_start| next_start.saturating_sub(1))
        .unwrap_or(src.len());
    let line = src.get(line_start..line_end)?;

    if loc.column == 0 {
        return Some(line_start);
    }

    match line.char_indices().nth(loc.column) {
        Some((offset, _)) => Some(line_start + offset),
        None if line.chars().count() == loc.column => Some(line_end),
        None => None,
    }
}

fn line_starts(src: &str) -> Vec<usize> {
    let mut starts = vec![0usize];
    for (idx, byte) in src.bytes().enumerate() {
        if byte == b'\n' {
            starts.push(idx + 1);
        }
    }
    starts
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn memento_is_content_addressed_recomputable_and_carries_no_source_text() {
        let src = "fn double(x: i64) -> i64 {\n    x * 2\n}\n";
        let file: syn::File = syn::parse_str(src).expect("parses");
        let syn::Item::Fn(item) = &file.items[0] else {
            panic!("expected a fn item");
        };

        let m1 = source_memento_of_item_fn("demo.rs", src, item);
        let m2 = source_memento_of_item_fn("demo.rs", src, item);
        assert_eq!(m1, m2);
        assert!(!m1.source_cid.is_empty());
        assert!(!m1.template_cid.is_empty());
        let rendered = m1.to_json().to_string();
        assert!(!rendered.contains("x * 2"));
        assert!(m1.to_json().get("body_text").is_none());
        assert!(m1.to_json().get("ast_template").is_none());
        assert_eq!(m1.function_name, "double");
        assert_eq!(m1.param_names, vec!["x".to_string()]);
        assert_eq!(m1.span.start_line, 1);
    }

    #[test]
    fn source_fragment_materializes_body_text_and_ast_template_inside_oracle() {
        let src = "fn double(x: i64) -> i64 {\n    x * 2\n}\n";
        let file: syn::File = syn::parse_str(src).expect("parses");
        let syn::Item::Fn(item) = &file.items[0] else {
            panic!("expected a fn item");
        };

        let fragment = source_fragment_of_item_fn("demo.rs", src, item);
        assert_eq!(fragment.body_text, "x * 2");
        assert_eq!(fragment.ast_template["kind"], "block");
        let memento = fragment.to_memento();
        assert!(memento.to_json().get("body_text").is_none());
        assert!(memento.to_json().get("ast_template").is_none());
    }

    #[test]
    fn source_oracle_mints_surface_and_statement_mementos() {
        use syn::spanned::Spanned;

        let root = std::env::temp_dir().join(format!(
            "sugar-source-oracle-stmt-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        std::fs::create_dir_all(root.join("src")).expect("mkdir src");
        let src = r#"
#[cfg(test)]
mod tests {
    #[test]
    fn emits_fact() {
        assert_eq!(1 + 1, 2);
    }
}
"#;
        std::fs::write(root.join("src/lib.rs"), src).expect("write source");
        let file: syn::File = syn::parse_str(src).expect("parses");
        let syn::Item::Mod(module) = &file.items[0] else {
            panic!("expected module");
        };
        let Some((_, items)) = &module.content else {
            panic!("expected inline module");
        };
        let syn::Item::Fn(item) = &items[0] else {
            panic!("expected test fn");
        };

        let surface = source_memento_of_named_item_fn("src/lib.rs", src, "tests::emits_fact", item);
        assert_eq!(surface.span.start_line, 4);
        assert_eq!(surface.span.end_line, 7);
        assert!(surface.to_json().get("body_text").is_none());
        assert!(surface.to_json().get("ast_template").is_none());

        let statement = source_memento_of_statement_span(
            "src/lib.rs",
            src,
            item.block.stmts[0].span(),
            "tests::emits_fact",
            &item.sig,
            &item.block,
        )
        .expect("statement memento");
        assert_eq!(statement.span.start_line, 6);
        assert_eq!(statement.span.end_line, 6);
        assert!(statement.to_json().get("body_text").is_none());
        assert!(statement.to_json().get("ast_template").is_none());

        let resolved_surface = resolve_source_memento(&root, &surface).expect("surface resolves");
        assert_eq!(resolved_surface.fragment.span, surface.span);
        let resolved_statement =
            resolve_source_memento(&root, &statement).expect("statement resolves");
        assert_eq!(resolved_statement.fragment.span, statement.span);
        assert_eq!(
            resolved_statement.fragment.body_text,
            "assert_eq!(1 + 1, 2);"
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn cached_source_fragment_mints_nested_statement_memento() {
        use syn::spanned::Spanned;

        let src = r#"
fn emits_fact(x: i64) {
    let y = x + 1;
    assert_eq!(y, 2);
}
"#;
        let file: syn::File = syn::parse_str(src).expect("parses");
        let syn::Item::Fn(item) = &file.items[0] else {
            panic!("expected function");
        };
        let stmt = &item.block.stmts[1];
        let direct = source_memento_of_statement_span(
            "src/lib.rs",
            src,
            stmt.span(),
            "emits_fact",
            &item.sig,
            &item.block,
        )
        .expect("direct statement memento");

        let mut cache = SourceFragmentCache::new(src);
        let parent = cache.source_fragment_of(
            "src/lib.rs",
            function_surface_span(&item.attrs, item.sig.fn_token.span),
            "emits_fact",
            &item.sig,
            &item.block,
        );
        assert!(parent.span.start_line <= direct.span.start_line);
        assert!(direct.span.start_line <= parent.span.end_line);

        let cached = cache
            .source_memento_of_statement_span(
                "src/lib.rs",
                stmt.span(),
                "emits_fact",
                &item.sig,
                &item.block,
            )
            .expect("cached statement memento");
        assert_eq!(cached, direct);
    }

    #[test]
    fn template_cid_is_stable_under_param_renaming() {
        let src_a = "fn f(x: i64) -> i64 { x + 1 }";
        let src_b = "fn f(input: i64) -> i64 { input + 1 }";
        let file_a: syn::File = syn::parse_str(src_a).expect("parse a");
        let file_b: syn::File = syn::parse_str(src_b).expect("parse b");
        let syn::Item::Fn(item_a) = &file_a.items[0] else {
            panic!("expected fn a");
        };
        let syn::Item::Fn(item_b) = &file_b.items[0] else {
            panic!("expected fn b");
        };

        let a = source_memento_of_item_fn("a.rs", src_a, item_a);
        let b = source_memento_of_item_fn("b.rs", src_b, item_b);
        assert_eq!(a.template_cid, b.template_cid);
        assert_ne!(a.source_cid, b.source_cid);
    }

    #[test]
    fn body_source_view_is_lean_binding_shape() {
        let src = "fn f(x: i64) -> i64 { x + 1 }";
        let file: syn::File = syn::parse_str(src).expect("parse");
        let syn::Item::Fn(item) = &file.items[0] else {
            panic!("expected fn");
        };
        let body_source = source_memento_of_item_fn("demo.rs", src, item).to_body_source_json();
        let keys = body_source
            .as_object()
            .expect("object")
            .keys()
            .map(String::as_str)
            .collect::<std::collections::BTreeSet<_>>();
        assert_eq!(
            keys,
            std::collections::BTreeSet::from([
                "file",
                "span",
                "source_cid",
                "template_cid",
                "param_names"
            ])
        );
    }
}

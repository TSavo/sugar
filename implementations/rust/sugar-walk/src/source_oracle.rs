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

    /// Extract the source text this memento's span refers to from a full source
    /// file string. Returns `None` when the line/column indices are out of range
    /// or the byte slice is not valid UTF-8.
    ///
    /// Span coordinates: `start_line` / `end_line` are 1-indexed; `start_col`
    /// / `end_col` are 0-indexed byte offsets within the line (exclusive end),
    /// matching proc_macro2 / syn conventions.
    pub fn extract_term_source<'a>(&self, source_text: &'a str) -> Option<&'a str> {
        if self.span.start_line == 0 || self.span.start_line != self.span.end_line {
            return None; // absent or multi-line: not supported
        }
        let line = source_text.lines().nth(self.span.start_line - 1)?; // 1→0 indexed
        let bytes = line.as_bytes();
        let start = self.span.start_col.min(bytes.len());
        let end = self.span.end_col.min(bytes.len());
        if start >= end {
            return None;
        }
        std::str::from_utf8(&bytes[start..end]).ok()
    }

    /// Like `to_json` but stamps a `sourceOracle.source` field with the term
    /// text extracted from `source_text` at the stored span. Consumers that
    /// have the source text in scope (e.g. test helpers, CLI renderers) call
    /// this instead of a separate oracle RPC round-trip.
    pub fn to_json_stamped(&self, source_text: &str) -> Value {
        let mut value = self.to_json();
        if let Some(source) = self.extract_term_source(source_text) {
            value["sourceOracle"] = json!({
                "status": "resolved",
                "source": source,
            });
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

    pub fn source_memento_of_term_span(
        &self,
        file_rel: &str,
        span: proc_macro2::Span,
        owner_name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> Option<SourceMemento> {
        self.source_fragment_of_term_span(file_rel, span, owner_name, sig, block)
            .map(|fragment| fragment.to_memento())
    }

    pub fn source_memento_of_term_src_span(
        &self,
        file_rel: &str,
        target: &SrcSpan,
        owner_name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> Option<SourceMemento> {
        self.source_fragment_of_term_src_span(file_rel, target, owner_name, sig, block)
            .map(|fragment| fragment.to_memento())
    }

    pub fn source_fragment_of_term_span(
        &self,
        file_rel: &str,
        span: proc_macro2::Span,
        owner_name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> Option<SourceFragment> {
        let target = span_to_src_span(span);
        self.source_fragment_of_term_src_span(file_rel, &target, owner_name, sig, block)
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

    pub fn source_fragment_of_term_src_span(
        &self,
        file_rel: &str,
        target: &SrcSpan,
        owner_name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> Option<SourceFragment> {
        let params = param_names_without_receiver_from_signature(sig);
        let expr = find_expr_by_span(block, target)?;
        Some(self.source_fragment_of_expr(file_rel, owner_name, &params, expr))
    }

    pub fn source_fragment_of_raw_src_span(
        &self,
        file_rel: &str,
        target: &SrcSpan,
        owner_name: &str,
        sig: &syn::Signature,
    ) -> Option<SourceFragment> {
        let param_names = param_names_without_receiver_from_signature(sig);
        let source_text =
            self.source_slice_between(src_span_start(target), src_span_end(target))?;
        Some(raw_source_fragment(
            file_rel,
            target,
            owner_name,
            &param_names,
            source_text,
        ))
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

    pub fn source_fragment_of_expr(
        &self,
        file_rel: &str,
        owner_name: &str,
        param_names: &[String],
        expr: &syn::Expr,
    ) -> SourceFragment {
        let span = span_to_src_span(expr.span());
        let body_text = self
            .source_slice_between(expr.span().start(), expr.span().end())
            .map(canonical_sugar_body_text)
            .unwrap_or_default()
            .to_string();
        SourceFragment {
            file: file_rel.to_string(),
            function_name: owner_name.to_string(),
            span,
            param_names: param_names.to_vec(),
            body_text,
            ast_template: expr_to_template(expr, param_names),
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

    pub fn source_memento_of_term_span(
        &mut self,
        file_rel: &str,
        span: proc_macro2::Span,
        owner_name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> Option<SourceMemento> {
        self.source_fragment_of_term_span(file_rel, span, owner_name, sig, block)
            .map(|fragment| fragment.to_memento())
    }

    pub fn source_memento_of_term_src_span(
        &mut self,
        file_rel: &str,
        target: &SrcSpan,
        owner_name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> Option<SourceMemento> {
        self.source_fragment_of_term_src_span(file_rel, target, owner_name, sig, block)
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

    pub fn source_fragment_of_term_span(
        &mut self,
        file_rel: &str,
        span: proc_macro2::Span,
        owner_name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> Option<SourceFragment> {
        let target = span_to_src_span(span);
        let params = param_names_without_receiver_from_signature(sig);
        let expr = find_expr_by_span(block, &target)?;
        Some(self.source_fragment_of_expr(file_rel, owner_name, &params, expr))
    }

    pub fn source_fragment_of_term_src_span(
        &mut self,
        file_rel: &str,
        target: &SrcSpan,
        owner_name: &str,
        sig: &syn::Signature,
        block: &syn::Block,
    ) -> Option<SourceFragment> {
        let params = param_names_without_receiver_from_signature(sig);
        let expr = find_expr_by_span(block, target)?;
        Some(self.source_fragment_of_expr(file_rel, owner_name, &params, expr))
    }

    pub fn source_fragment_of_raw_src_span(
        &mut self,
        file_rel: &str,
        target: &SrcSpan,
        owner_name: &str,
        sig: &syn::Signature,
    ) -> Option<SourceFragment> {
        let param_names = param_names_without_receiver_from_signature(sig);
        let source_text = self.source_text_from_cached_fragment(target).or_else(|| {
            self.index
                .source_slice_between(src_span_start(target), src_span_end(target))
                .map(str::to_string)
        })?;
        let fragment =
            raw_source_fragment(file_rel, target, owner_name, &param_names, &source_text);
        self.insert_fragment(fragment.clone(), source_text);
        Some(fragment)
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

    pub fn source_fragment_of_expr(
        &mut self,
        file_rel: &str,
        owner_name: &str,
        param_names: &[String],
        expr: &syn::Expr,
    ) -> SourceFragment {
        let span = span_to_src_span(expr.span());
        let source_text = self
            .source_text_from_cached_fragment(&span)
            .unwrap_or_else(|| {
                self.index
                    .source_slice_between(expr.span().start(), expr.span().end())
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
            ast_template: expr_to_template(expr, param_names),
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

fn raw_source_fragment(
    file_rel: &str,
    target: &SrcSpan,
    owner_name: &str,
    param_names: &[String],
    source_text: &str,
) -> SourceFragment {
    let body_text = canonical_sugar_body_text(source_text).to_string();
    let source_cid = blake3_512_of(body_text.as_bytes());
    SourceFragment {
        file: file_rel.to_string(),
        function_name: owner_name.to_string(),
        span: target.clone(),
        param_names: param_names.to_vec(),
        body_text,
        ast_template: json!({
            "kind": "source-span",
            "source_cid": source_cid,
        }),
    }
}

fn src_span_start(span: &SrcSpan) -> proc_macro2::LineColumn {
    proc_macro2::LineColumn {
        line: span.start_line,
        column: span.start_col,
    }
}

fn src_span_end(span: &SrcSpan) -> proc_macro2::LineColumn {
    proc_macro2::LineColumn {
        line: span.end_line,
        column: span.end_col,
    }
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

pub fn source_memento_of_term_span(
    file_rel: &str,
    src: &str,
    span: proc_macro2::Span,
    owner_name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> Option<SourceMemento> {
    SourceTextIndex::new(src)
        .source_fragment_of_term_span(file_rel, span, owner_name, sig, block)
        .map(|fragment| fragment.to_memento())
}

pub fn source_memento_of_term_src_span(
    file_rel: &str,
    src: &str,
    target: &SrcSpan,
    owner_name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> Option<SourceMemento> {
    SourceTextIndex::new(src)
        .source_fragment_of_term_src_span(file_rel, target, owner_name, sig, block)
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

pub fn source_fragment_of_term_span(
    file_rel: &str,
    src: &str,
    span: proc_macro2::Span,
    owner_name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> Option<SourceFragment> {
    SourceTextIndex::new(src).source_fragment_of_term_span(file_rel, span, owner_name, sig, block)
}

pub fn source_fragment_of_term_src_span(
    file_rel: &str,
    src: &str,
    target: &SrcSpan,
    owner_name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> Option<SourceFragment> {
    SourceTextIndex::new(src)
        .source_fragment_of_term_src_span(file_rel, target, owner_name, sig, block)
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
    let source_name_change = memento
        .source_function_name()
        .filter(|wanted| !source_fn_matches_name(&source_fn, wanted))
        .map(|wanted| {
            format!(
                "source name changed from `{wanted}` to `{}` at pinned locus; ",
                source_fn.full_name
            )
        });

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
    // Identify a WHOLE-FUNCTION memento by START alignment (start_line + start_col
    // against the located function's surface start), which is invariant under body
    // drift: a function's start does not move when its body changes, only its END
    // does. The previous full-span discriminator broke exactly there -- body drift
    // shifted end_line, so a whole-function memento failed the equality, fell through
    // to the statement path, found no statement at the function-surface span, and
    // refused with a misleading "fragment not found" instead of recomputing the
    // whole-function CID and reporting the honest "source CID misaligned".
    let fragment = if memento.span.start_line == whole_fragment.span.start_line
        && memento.span.start_col == whole_fragment.span.start_col
    {
        whole_fragment
    } else {
        // Not a whole-function memento: locate the pinned statement OR term by its
        // span. If the fragment is gone (the body drifted under the pin), fall
        // through to the whole-function fragment so the CID comparison below still
        // reports drift as "source CID misaligned" -- a function we located by name
        // whose pinned fragment span is now absent IS drift, never a bare "fragment
        // not found".
        source_index
            .source_fragment_of_term_src_span(
                &memento.file,
                &memento.span,
                memento
                    .source_function_name()
                    .unwrap_or(&source_fn.full_name),
                source_fn.sig,
                source_fn.block,
            )
            .or_else(|| {
                source_index.source_fragment_of_statement_src_span(
                    &memento.file,
                    &memento.span,
                    memento
                        .source_function_name()
                        .unwrap_or(&source_fn.full_name),
                    source_fn.sig,
                    source_fn.block,
                )
            })
            .or_else(|| {
                source_index.source_fragment_of_raw_src_span(
                    &memento.file,
                    &memento.span,
                    memento
                        .source_function_name()
                        .unwrap_or(&source_fn.full_name),
                    source_fn.sig,
                )
            })
            .unwrap_or(whole_fragment)
    };
    let recomputed = fragment.to_memento();
    let recomputed_source_cid = recomputed.source_cid;
    let recomputed_template_cid = recomputed.template_cid;

    if !memento.source_cid.is_empty() && recomputed_source_cid != memento.source_cid {
        return Err(SourceOracleRefusal {
            reason: format!(
                "{}source CID misaligned for `{}` in `{}`: pinned {}, on-disk {recomputed_source_cid} -- the source drifted from the proof",
                source_name_change.as_deref().unwrap_or(""),
                memento.source_function_name().unwrap_or("<any>"),
                memento.file,
                memento.source_cid
            ),
        });
    }
    if !memento.template_cid.is_empty() && recomputed_template_cid != memento.template_cid {
        return Err(SourceOracleRefusal {
            reason: format!(
                "{}template CID misaligned for `{}` in `{}`: pinned {}, on-disk {recomputed_template_cid} -- the AST drifted from the proof",
                source_name_change.as_deref().unwrap_or(""),
                memento.source_function_name().unwrap_or("<any>"),
                memento.file,
                memento.template_cid
            ),
        });
    }

    if let Some(reason) = source_name_change {
        return Err(SourceOracleRefusal {
            reason: format!(
                "{reason}source function name drifted from the proof in `{}`",
                memento.file
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

fn source_fn_matches_name(source_fn: &SourceFnRef<'_>, wanted: &str) -> bool {
    source_fn_matches_candidate_name(source_fn, wanted)
        || trait_impl_display_name_source_name(wanted)
            .is_some_and(|source_name| source_fn_matches_candidate_name(source_fn, &source_name))
}

fn source_fn_matches_candidate_name(source_fn: &SourceFnRef<'_>, wanted: &str) -> bool {
    source_fn.full_name == wanted
        || source_fn.leaf_name == wanted
        || source_fn.full_name.ends_with(&format!("::{wanted}"))
}

fn trait_impl_display_name_source_name(wanted: &str) -> Option<String> {
    let after_open = wanted.strip_prefix('<')?;
    let (self_ty, after_as) = after_open.split_once(" as ")?;
    let (_, method) = after_as.split_once(">::")?;
    if self_ty.is_empty() || method.is_empty() {
        return None;
    }
    Some(format!("{self_ty}::{method}"))
}

#[derive(Clone)]
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
    let mut candidates = Vec::new();
    collect_source_fns(items, &mut candidates);
    let mut matches = candidates
        .iter()
        .map(|candidate| SourceFnRef {
            full_name: candidate.full_name.clone(),
            leaf_name: candidate.leaf_name.clone(),
            span: candidate.span,
            start_line: candidate.start_line,
            end_line: candidate.end_line,
            sig: candidate.sig,
            block: candidate.block,
        })
        .collect::<Vec<_>>();
    let wanted = memento.source_function_name();
    matches.retain(|candidate| {
        wanted.is_none_or(|name| {
            candidate.full_name == name
                || candidate.leaf_name == name
                || candidate.full_name.ends_with(&format!("::{name}"))
        })
    });
    if matches.is_empty() {
        return locate_source_fn_by_span(&candidates, memento);
    }
    if matches.len() > 1 && memento.span.start_line > 0 {
        if let Some(candidate) = locate_source_fn_by_span(&matches, memento) {
            return Some(candidate);
        }
    }
    matches.into_iter().next()
}

fn locate_source_fn_by_span<'a>(
    matches: &[SourceFnRef<'a>],
    memento: &SourceMemento,
) -> Option<SourceFnRef<'a>> {
    if memento.span.start_line == 0 {
        return None;
    }
    matches
        .iter()
        .find(|candidate| {
            candidate.start_line <= memento.span.start_line
                && memento.span.start_line <= candidate.end_line
        })
        .cloned()
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

fn find_expr_by_span<'a>(block: &'a syn::Block, target: &SrcSpan) -> Option<&'a syn::Expr> {
    struct Finder<'a> {
        target: SrcSpan,
        found: Option<&'a syn::Expr>,
    }
    impl<'a> syn::visit::Visit<'a> for Finder<'a> {
        fn visit_expr(&mut self, expr: &'a syn::Expr) {
            if self.found.is_some() {
                return;
            }
            if source_span_eq(&span_to_src_span(expr.span()), &self.target) {
                self.found = Some(expr);
                return;
            }
            syn::visit::visit_expr(self, expr);
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
    fn source_oracle_uses_memento_span_when_display_function_name_does_not_match_ast_name() {
        use syn::spanned::Spanned;

        let root = std::env::temp_dir().join(format!(
            "sugar-source-oracle-display-name-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        std::fs::create_dir_all(root.join("src")).expect("mkdir src");
        let src = r#"
pub trait Engine {
    fn config(&self) -> bool;
}

pub struct GeneralPurpose;

impl Engine for GeneralPurpose {
    fn config(&self) -> bool {
        let ok = true;
        ok
    }
}
"#;
        std::fs::write(root.join("src/lib.rs"), src).expect("write source");
        let file: syn::File = syn::parse_str(src).expect("parses");
        let syn::Item::Impl(item_impl) = &file.items[2] else {
            panic!("expected impl");
        };
        let syn::ImplItem::Fn(method) = &item_impl.items[0] else {
            panic!("expected method");
        };
        let item_fn = syn::ItemFn {
            attrs: method.attrs.clone(),
            vis: method.vis.clone(),
            sig: method.sig.clone(),
            block: Box::new(method.block.clone()),
        };
        let mut memento = source_memento_of_statement_span(
            "src/lib.rs",
            src,
            item_fn.block.stmts[0].span(),
            "<GeneralPurpose as super::Engine>::config",
            &item_fn.sig,
            &item_fn.block,
        )
        .expect("statement memento");
        memento.function_name = "<GeneralPurpose as super::Engine>::config".to_string();

        let resolved = resolve_source_memento(&root, &memento)
            .expect("span-bearing memento should resolve even with display-only function name");

        assert_eq!(resolved.fragment.body_text, "let ok = true;");
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_oracle_refuses_real_name_drift_even_when_span_matches() {
        use syn::spanned::Spanned;

        let root = std::env::temp_dir().join(format!(
            "sugar-source-oracle-real-name-drift-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        std::fs::create_dir_all(root.join("src")).expect("mkdir src");
        let src = r#"
pub struct GeneralPurpose;

impl GeneralPurpose {
    fn config(&self) -> bool {
        let ok = true;
        ok
    }
}
"#;
        std::fs::write(root.join("src/lib.rs"), src).expect("write source");
        let file: syn::File = syn::parse_str(src).expect("parses");
        let syn::Item::Impl(item_impl) = &file.items[1] else {
            panic!("expected impl");
        };
        let syn::ImplItem::Fn(method) = &item_impl.items[0] else {
            panic!("expected method");
        };
        let item_fn = syn::ItemFn {
            attrs: method.attrs.clone(),
            vis: method.vis.clone(),
            sig: method.sig.clone(),
            block: Box::new(method.block.clone()),
        };
        let mut memento = source_memento_of_statement_span(
            "src/lib.rs",
            src,
            item_fn.block.stmts[0].span(),
            "GeneralPurpose::config",
            &item_fn.sig,
            &item_fn.block,
        )
        .expect("statement memento");
        memento.function_name = "OtherPurpose::config".to_string();

        let drift =
            resolve_source_memento(&root, &memento).expect_err("real name drift must refuse");

        assert!(
            drift
                .reason
                .contains("source function name drifted from the proof"),
            "unexpected drift reason: {}",
            drift.reason
        );
        assert!(
            drift.reason.contains("OtherPurpose::config")
                && drift.reason.contains("GeneralPurpose::config"),
            "unexpected drift reason: {}",
            drift.reason
        );
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn source_oracle_mints_and_resolves_term_mementos_without_embedding_source() {
        use syn::spanned::Spanned;

        let root = std::env::temp_dir().join(format!(
            "sugar-source-oracle-term-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        std::fs::create_dir_all(root.join("src")).expect("mkdir src");
        let src = r#"
fn computes(x: i64) -> i64 {
    let y = x + 1;
    y * 2
}
"#;
        std::fs::write(root.join("src/lib.rs"), src).expect("write source");
        let file: syn::File = syn::parse_str(src).expect("parses");
        let syn::Item::Fn(item) = &file.items[0] else {
            panic!("expected function");
        };
        let syn::Stmt::Local(local) = &item.block.stmts[0] else {
            panic!("expected let");
        };
        let init = local.init.as_ref().expect("let init");

        let term = source_memento_of_term_span(
            "src/lib.rs",
            src,
            init.expr.span(),
            "computes",
            &item.sig,
            &item.block,
        )
        .expect("term memento");
        let rendered = term.to_json().to_string();
        assert!(!rendered.contains("x + 1"));
        assert!(term.to_json().get("body_text").is_none());
        assert!(term.to_json().get("ast_template").is_none());

        let resolved = resolve_source_memento(&root, &term).expect("term resolves");
        assert_eq!(resolved.fragment.span, term.span);
        assert_eq!(resolved.fragment.body_text, "x + 1");
        assert_eq!(resolved.fragment.ast_template["kind"], "binary");

        std::fs::write(root.join("src/lib.rs"), src.replace("x + 1", "x + 2"))
            .expect("rewrite drifted source");
        let drift = resolve_source_memento(&root, &term).expect_err("term drift must refuse");
        assert!(
            drift.reason.contains("source CID misaligned"),
            "unexpected drift reason: {}",
            drift.reason
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

// SPDX-License-Identifier: Apache-2.0
//! Rust `SourceOracle`: emits and resolves `SourceMemento`s.
//!
//! A memento is a pointer into source: file, span, function name, parameter
//! names, and recomputable CIDs. It never carries source text or serialized AST
//! content. Consumers re-read the authoritative source file and recompute the
//! CIDs to prove the pointer still names the same body.

use quote::ToTokens;
use serde_json::{json, Value};
use sugar_canonicalizer::blake3_512_of;

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

pub fn source_memento_of(
    file_rel: &str,
    src: &str,
    span: proc_macro2::Span,
    name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> SourceMemento {
    source_fragment_of(file_rel, src, span, name, sig, block).to_memento()
}

pub fn source_fragment_of(
    file_rel: &str,
    src: &str,
    span: proc_macro2::Span,
    name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> SourceFragment {
    let start = span.start();
    let end = block.brace_token.span.close().end();
    let param_names = param_names_without_receiver_from_signature(sig);
    let body_text = block_inner_source(src, block)
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
        item.sig.fn_token.span,
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
        item.sig.fn_token.span,
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

    let fragment = source_fragment_of(
        &memento.file,
        &src,
        source_fn.sig.fn_token.span,
        memento
            .source_function_name()
            .unwrap_or(&source_fn.full_name),
        source_fn.sig,
        source_fn.block,
    );
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

struct SourceFnRef<'a> {
    full_name: String,
    leaf_name: String,
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
    for item in items {
        match item {
            syn::Item::Fn(item_fn) => {
                out.push(source_fn_ref(
                    item_fn.sig.ident.to_string(),
                    item_fn.sig.ident.to_string(),
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
                        format!("{qualifier}::{leaf}"),
                        leaf,
                        &method.sig,
                        &method.block,
                    ));
                }
            }
            syn::Item::Mod(module) => {
                if let Some((_, nested)) = &module.content {
                    collect_source_fns(nested, out);
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
                        format!("{qualifier}::{leaf}"),
                        leaf,
                        &method.sig,
                        block,
                    ));
                }
            }
            _ => {}
        }
    }
}

fn source_fn_ref<'a>(
    full_name: String,
    leaf_name: String,
    sig: &'a syn::Signature,
    block: &'a syn::Block,
) -> SourceFnRef<'a> {
    SourceFnRef {
        full_name,
        leaf_name,
        start_line: sig.fn_token.span.start().line,
        end_line: block.brace_token.span.close().end().line,
        sig,
        block,
    }
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
    let start = line_column_to_byte_offset(src, start)?;
    let end = line_column_to_byte_offset(src, end)?;
    if start <= end {
        src.get(start..end)
    } else {
        None
    }
}

pub fn line_column_to_byte_offset(src: &str, loc: proc_macro2::LineColumn) -> Option<usize> {
    if loc.line == 0 {
        return None;
    }

    let mut line_starts = vec![0usize];
    for (idx, byte) in src.bytes().enumerate() {
        if byte == b'\n' {
            line_starts.push(idx + 1);
        }
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

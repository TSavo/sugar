// SPDX-License-Identifier: Apache-2.0
//! Rust `SourceOracle` — emits `SourceMemento`s: content-addressed pointers to a
//! source fragment. A memento is `file + span + BLAKE3-512(body) + BLAKE3-512(ast
//! template)` and NEVER carries source text. A third party recomputes the CIDs
//! from the on-disk source at the locus to verify (recompute-don't-trust), the
//! same contract as `JavaSourceOracle.sourceMementoOf` and Python's
//! `source_oracle.resolve_source_memento`.
//!
//! Mirrors the cross-kit derivation so the CIDs are recomputable WITHIN the Rust
//! kit (same Rust source -> same memento on any machine): `source_cid` hashes the
//! on-disk body bytes a reader re-reads; `template_cid` hashes a deterministic
//! token-structure of the body.

use quote::ToTokens;
use serde_json::{json, Value};
use sugar_canonicalizer::blake3_512_of;
use syn::spanned::Spanned;

/// A source span, 1-based line / 0-based column, mirroring the Java `Span`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SrcSpan {
    pub start_line: usize,
    pub start_col: usize,
    pub end_line: usize,
    pub end_col: usize,
}

/// A content-addressed pointer to a source fragment. Carries hashes, never text.
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
    pub fn to_json(&self) -> Value {
        json!({
            "file": self.file,
            "sourceFunctionName": self.function_name,
            "span": {
                "start_line": self.span.start_line,
                "start_col": self.span.start_col,
                "end_line": self.span.end_line,
                "end_col": self.span.end_col,
            },
            "paramNames": self.param_names,
            "source_cid": self.source_cid,
            "template_cid": self.template_cid,
        })
    }
}

/// Build a `SourceMemento` for a function item. `src` is the full file text;
/// `file_rel` the workspace-relative path. `source_cid` hashes the on-disk body
/// fragment (the bytes a third party re-reads at the locus); `template_cid`
/// hashes a deterministic token-structure of the body.
pub fn source_memento_of(
    file_rel: &str,
    src: &str,
    span: proc_macro2::Span,
    name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> SourceMemento {
    let start = span.start();
    let end = span.end();
    let src_span = SrcSpan {
        start_line: start.line,
        start_col: start.column,
        end_line: end.line,
        end_col: end.column,
    };
    let body_text = fragment_text(src, src_span.start_line, src_span.end_line);
    let template = template_json(sig, block);
    SourceMemento {
        file: file_rel.to_string(),
        function_name: name.to_string(),
        param_names: param_names(sig),
        source_cid: blake3_512_of(body_text.as_bytes()),
        template_cid: blake3_512_of(template.as_bytes()),
        span: src_span,
    }
}

/// Convenience: build a memento for a free `fn` item.
pub fn source_memento_of_item_fn(file_rel: &str, src: &str, item: &syn::ItemFn) -> SourceMemento {
    source_memento_of(
        file_rel,
        src,
        item.span(),
        &item.sig.ident.to_string(),
        &item.sig,
        &item.block,
    )
}

/// The source fragment text for an inclusive 1-based line range. This is what a
/// third party re-reads off disk and re-hashes to verify `source_cid`.
fn fragment_text(src: &str, start_line: usize, end_line: usize) -> String {
    if start_line == 0 || end_line < start_line {
        return String::new();
    }
    src.lines()
        .skip(start_line - 1)
        .take(end_line - start_line + 1)
        .collect::<Vec<_>>()
        .join("\n")
}

/// A deterministic AST template (kind + param count + the body's token string),
/// mirroring the shape of `JavaSourceOracle.templateJson`. Field order is fixed
/// so the bytes -- and thus `template_cid` -- recompute.
fn template_json(sig: &syn::Signature, block: &syn::Block) -> String {
    let body_tokens = block.to_token_stream().to_string();
    format!(
        r#"{{"kind":"rust-fn-body","param_count":{},"tokens":{}}}"#,
        sig.inputs.len(),
        serde_json::to_string(&body_tokens).unwrap_or_else(|_| "\"\"".to_string()),
    )
}

fn param_names(sig: &syn::Signature) -> Vec<String> {
    sig.inputs
        .iter()
        .filter_map(|arg| match arg {
            syn::FnArg::Typed(pt) => match &*pt.pat {
                syn::Pat::Ident(p) => Some(p.ident.to_string()),
                _ => None,
            },
            syn::FnArg::Receiver(_) => Some("self".to_string()),
        })
        .collect()
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
        // Recomputable: same source -> byte-identical memento (any machine).
        let m2 = source_memento_of_item_fn("demo.rs", src, item);
        assert_eq!(m1, m2, "memento must be deterministic (recomputable)");

        // Content-addressed: CIDs present and non-empty.
        assert!(!m1.source_cid.is_empty(), "source_cid present");
        assert!(!m1.template_cid.is_empty(), "template_cid present");
        // It is a POINTER, not the text: the body `x * 2` must not appear.
        let rendered = m1.to_json().to_string();
        assert!(
            !rendered.contains("x * 2"),
            "memento must carry hashes, never source text: {rendered}"
        );

        assert_eq!(m1.function_name, "double");
        assert_eq!(m1.param_names, vec!["x".to_string()]);
        assert_eq!(m1.span.start_line, 1);
    }

    #[test]
    fn different_body_yields_different_source_cid() {
        let a: syn::File = syn::parse_str("fn f() -> i64 { 1 }").unwrap();
        let b: syn::File = syn::parse_str("fn f() -> i64 { 2 }").unwrap();
        let (syn::Item::Fn(ia), syn::Item::Fn(ib)) = (&a.items[0], &b.items[0]) else {
            panic!();
        };
        let ma = source_memento_of_item_fn("a.rs", "fn f() -> i64 { 1 }", ia);
        let mb = source_memento_of_item_fn("b.rs", "fn f() -> i64 { 2 }", ib);
        assert_ne!(
            ma.source_cid, mb.source_cid,
            "distinct bodies must hash to distinct source CIDs (teeth)"
        );
    }
}

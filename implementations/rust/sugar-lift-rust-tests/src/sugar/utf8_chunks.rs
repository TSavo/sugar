// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `Utf8ChunksSugar`: literal-backed stdlib temporal replay for
// `[u8]::utf8_chunks()`.
//
// This is intentionally a block-level macro-expansion rewrite rather than a
// factory policy. The macro expander hands us ordinary Rust statements such as:
//
//   let mut iter = b"A\xC2B".utf8_chunks();
//   let chunk = iter.next().expect("missing chunk");
//   assert_eq!("A", chunk.valid());
//   assert_eq!(b"\xC2", chunk.invalid());
//   let chunk = iter.next().expect("missing chunk");
//   assert_eq!("B", chunk.valid());
//   assert_eq!(b"", chunk.invalid());
//   assert_eq!(None, iter.next());
//
// The receiver is a written byte/string literal, and `utf8_chunks` is a rustc
// stdlib axiom. We replay the iterator temporally and replace only the observed
// `valid()` / `invalid()` / exhausted `next()` assertion operands with literal
// expressions, then the normal assertion factory builds the facts. Non-literal
// receivers, non-exhausted direct `next()`, or unrecognized shapes decline so
// the existing runtime-boundary accounting remains honest.

use std::collections::BTreeMap;

use proc_macro2::Span;
use quote::quote;
use syn::parse::Parser;
use syn::punctuated::Punctuated;
use syn::{Expr, Lit, Stmt};

#[derive(Clone, Debug)]
struct Utf8ChunkLiteral {
    valid: String,
    invalid: Vec<u8>,
}

#[derive(Clone, Debug)]
struct Utf8Cursor {
    chunks: Vec<Utf8ChunkLiteral>,
    next_index: usize,
}

/// Rewrite literal-backed `utf8_chunks` macro expansions to literal assertion
/// operands. Returns `None` when no recognized replay happened.
pub(crate) fn rewrite_literal_utf8_chunks_block(block: &syn::Block) -> Option<syn::Block> {
    let mut state = RewriteState::default();
    let rewritten = state.rewrite_block(block);
    (state.rewrites > 0).then_some(rewritten)
}

#[derive(Default)]
struct RewriteState {
    cursors: BTreeMap<String, Utf8Cursor>,
    chunk_bindings: BTreeMap<String, Utf8ChunkLiteral>,
    rewrites: usize,
}

impl RewriteState {
    fn rewrite_block(&mut self, block: &syn::Block) -> syn::Block {
        let mut rewritten = block.clone();
        rewritten.stmts = block
            .stmts
            .iter()
            .map(|stmt| self.rewrite_stmt(stmt))
            .collect();
        rewritten
    }

    fn rewrite_stmt(&mut self, stmt: &Stmt) -> Stmt {
        match stmt {
            Stmt::Local(local) => {
                self.record_utf8_local(local);
                stmt.clone()
            }
            Stmt::Macro(stmt_macro) => {
                let mut rewritten = stmt_macro.clone();
                if let Some(mac) = self.rewrite_assert_macro(&stmt_macro.mac) {
                    rewritten.mac = mac;
                }
                Stmt::Macro(rewritten)
            }
            Stmt::Expr(Expr::Macro(expr_macro), semi) => {
                if let Some(mac) = self.rewrite_assert_macro(&expr_macro.mac) {
                    let mut rewritten = expr_macro.clone();
                    rewritten.mac = mac;
                    Stmt::Expr(Expr::Macro(rewritten), *semi)
                } else {
                    stmt.clone()
                }
            }
            Stmt::Expr(Expr::Block(expr_block), semi) => {
                let mut rewritten = expr_block.clone();
                let mut nested = RewriteState::default();
                rewritten.block = nested.rewrite_block(&expr_block.block);
                self.rewrites += nested.rewrites;
                Stmt::Expr(Expr::Block(rewritten), *semi)
            }
            Stmt::Expr(Expr::Unsafe(expr_unsafe), semi) => {
                let mut rewritten = expr_unsafe.clone();
                let mut nested = RewriteState::default();
                rewritten.block = nested.rewrite_block(&expr_unsafe.block);
                self.rewrites += nested.rewrites;
                Stmt::Expr(Expr::Unsafe(rewritten), *semi)
            }
            _ => stmt.clone(),
        }
    }

    fn record_utf8_local(&mut self, local: &syn::Local) {
        let Some(init) = local.init.as_ref().filter(|init| init.diverge.is_none()) else {
            return;
        };
        if let Some(name) = let_mut_ident(&local.pat) {
            if let Some(bytes) = literal_utf8_chunks_receiver_bytes(&init.expr) {
                let chunks = utf8_chunks(&bytes);
                tracing::debug!(
                    target: "sugar_lift_rust_tests::utf8_chunks",
                    iterator = %name,
                    bytes = bytes.len(),
                    chunks = chunks.len(),
                    "recorded literal utf8_chunks iterator"
                );
                self.cursors.insert(
                    name,
                    Utf8Cursor {
                        chunks,
                        next_index: 0,
                    },
                );
            }
        }
        if let Some(name) = let_ident(&local.pat) {
            if let Some(iter_name) = iter_next_expect_receiver(&init.expr) {
                if let Some(cursor) = self.cursors.get_mut(&iter_name) {
                    if let Some(chunk) = cursor.chunks.get(cursor.next_index).cloned() {
                        cursor.next_index += 1;
                        tracing::debug!(
                            target: "sugar_lift_rust_tests::utf8_chunks",
                            binding = %name,
                            iterator = %iter_name,
                            index = cursor.next_index - 1,
                            "bound utf8 chunk literal"
                        );
                        self.chunk_bindings.insert(name, chunk);
                    }
                }
            }
        }
    }

    fn rewrite_assert_macro(&mut self, mac: &syn::Macro) -> Option<syn::Macro> {
        if mac.path.segments.last()?.ident != "assert_eq" {
            return None;
        }
        let parser = Punctuated::<Expr, syn::Token![,]>::parse_terminated;
        let args = parser.parse2(mac.tokens.clone()).ok()?;
        if args.len() != 2 {
            return None;
        }
        let mut iter = args.into_iter();
        let mut left = iter.next()?;
        let mut right = iter.next()?;
        let mut changed = false;
        if let Some(rewritten) = self.rewrite_assert_operand(&left) {
            left = rewritten;
            changed = true;
        }
        if let Some(rewritten) = self.rewrite_assert_operand(&right) {
            right = rewritten;
            changed = true;
        }
        if !changed {
            return None;
        }
        self.rewrites += 1;
        tracing::debug!(
            target: "sugar_lift_rust_tests::utf8_chunks",
            assertion = %mac.path.segments.last()?.ident,
            "rewrote utf8_chunks assertion operand to literal"
        );
        let mut rewritten = mac.clone();
        rewritten.tokens = quote! { #left, #right };
        Some(rewritten)
    }

    fn rewrite_assert_operand(&self, expr: &Expr) -> Option<Expr> {
        if let Some((binding, accessor)) = chunk_accessor(expr) {
            let chunk = self.chunk_bindings.get(&binding)?;
            return match accessor {
                ChunkAccessor::Valid => Some(string_literal_expr(&chunk.valid)),
                ChunkAccessor::Invalid => Some(byte_string_literal_expr(&chunk.invalid)),
            };
        }
        if let Some(iter_name) = iter_next_receiver(expr) {
            let cursor = self.cursors.get(&iter_name)?;
            if cursor.next_index >= cursor.chunks.len() {
                return Some(syn::parse_quote!(None));
            }
        }
        None
    }
}

#[derive(Clone, Copy)]
enum ChunkAccessor {
    Valid,
    Invalid,
}

fn let_mut_ident(pat: &syn::Pat) -> Option<String> {
    match pat {
        syn::Pat::Ident(pi)
            if pi.mutability.is_some() && pi.by_ref.is_none() && pi.subpat.is_none() =>
        {
            Some(pi.ident.to_string())
        }
        syn::Pat::Type(t) => let_mut_ident(&t.pat),
        syn::Pat::Paren(p) => let_mut_ident(&p.pat),
        _ => None,
    }
}

fn let_ident(pat: &syn::Pat) -> Option<String> {
    match pat {
        syn::Pat::Ident(pi) if pi.by_ref.is_none() && pi.subpat.is_none() => {
            Some(pi.ident.to_string())
        }
        syn::Pat::Type(t) => let_ident(&t.pat),
        syn::Pat::Paren(p) => let_ident(&p.pat),
        _ => None,
    }
}

fn literal_utf8_chunks_receiver_bytes(expr: &Expr) -> Option<Vec<u8>> {
    let Expr::MethodCall(call) = strip(expr) else {
        return None;
    };
    if call.method != "utf8_chunks" || !call.args.is_empty() {
        return None;
    }
    literal_bytes(&call.receiver)
}

fn literal_bytes(expr: &Expr) -> Option<Vec<u8>> {
    match strip(expr) {
        Expr::Lit(syn::ExprLit {
            lit: Lit::ByteStr(bs),
            ..
        }) => Some(bs.value()),
        Expr::Lit(syn::ExprLit {
            lit: Lit::Str(s), ..
        }) => Some(s.value().into_bytes()),
        Expr::MethodCall(call) if call.method == "as_bytes" && call.args.is_empty() => {
            literal_bytes(&call.receiver)
        }
        _ => None,
    }
}

fn iter_next_expect_receiver(expr: &Expr) -> Option<String> {
    match strip(expr) {
        Expr::MethodCall(call) if call.method == "expect" => iter_next_receiver(&call.receiver),
        other => iter_next_receiver(other),
    }
}

fn iter_next_receiver(expr: &Expr) -> Option<String> {
    let Expr::MethodCall(call) = strip(expr) else {
        return None;
    };
    if call.method != "next" || !call.args.is_empty() {
        return None;
    }
    simple_path_ident(&call.receiver)
}

fn chunk_accessor(expr: &Expr) -> Option<(String, ChunkAccessor)> {
    let Expr::MethodCall(call) = strip(expr) else {
        return None;
    };
    if !call.args.is_empty() {
        return None;
    }
    let accessor = match call.method.to_string().as_str() {
        "valid" => ChunkAccessor::Valid,
        "invalid" => ChunkAccessor::Invalid,
        _ => return None,
    };
    Some((simple_path_ident(&call.receiver)?, accessor))
}

fn simple_path_ident(expr: &Expr) -> Option<String> {
    let Expr::Path(path) = strip(expr) else {
        return None;
    };
    if path.qself.is_some() || path.path.segments.len() != 1 {
        return None;
    }
    Some(path.path.segments[0].ident.to_string())
}

fn strip(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(paren) => strip(&paren.expr),
        Expr::Group(group) => strip(&group.expr),
        Expr::Reference(reference) => strip(&reference.expr),
        _ => expr,
    }
}

fn utf8_chunks(bytes: &[u8]) -> Vec<Utf8ChunkLiteral> {
    let mut chunks = Vec::new();
    let mut rest = bytes;
    while !rest.is_empty() {
        match std::str::from_utf8(rest) {
            Ok(valid) => {
                chunks.push(Utf8ChunkLiteral {
                    valid: valid.to_string(),
                    invalid: Vec::new(),
                });
                break;
            }
            Err(err) => {
                let valid_up_to = err.valid_up_to();
                let invalid_len = err
                    .error_len()
                    .unwrap_or_else(|| rest.len().saturating_sub(valid_up_to));
                let valid = std::str::from_utf8(&rest[..valid_up_to])
                    .expect("valid_up_to prefix is valid utf8")
                    .to_string();
                let invalid = rest[valid_up_to..valid_up_to + invalid_len].to_vec();
                chunks.push(Utf8ChunkLiteral { valid, invalid });
                rest = &rest[valid_up_to + invalid_len..];
            }
        }
    }
    chunks
}

fn string_literal_expr(value: &str) -> Expr {
    let lit = syn::LitStr::new(value, Span::call_site());
    syn::parse_quote!(#lit)
}

fn byte_string_literal_expr(value: &[u8]) -> Expr {
    let lit = syn::LitByteStr::new(value, Span::call_site());
    syn::parse_quote!(#lit)
}

// SPDX-License-Identifier: Apache-2.0
//
// `GenericBodySugar`: recognize a functional string-encoder function body and
// emit a `str.eq-bv-blocks` universe post atom by COMPOSITION.
//
// Body shape (the ONLY shape we accept -- no side doors):
//
//   fn <name>(<param>: &[u8]) -> ... {
//       const <TABLE>: &[u8] = b"<alphabet>";
//       let b0 = <param>[0] as u32;
//       let b1 = <param>[1] as u32;
//       // ... more byte vars ...
//       [TABLE[<bv_expr>], TABLE[<bv_expr>], ...]
//   }
//
// Mechanism (four-step composition):
//   1. Extract the const table name and its byte values.
//   2. Recognize byte-var bindings bN = param[N] as u32.
//   3. Walk the return array: each element TABLE[<bv_expr>] gives one
//      symbolic index term. BV ops are built directly (not through the
//      Sugar catalog -- the catalog path would need a TemporalContext with
//      symbolic floor bindings, which is not how broad_functional_warrant
//      works). The BV walker mirrors bv_binop.rs node names exactly so the
//      SMT compiler's render_bv_index_json / render_b64_blocks_body_with_input
//      can consume the payload unchanged.
//   4. Serialize the payload as JCS JSON and emit:
//        atomic_("str.eq-bv-blocks", [out, param, str_const(payload)])
//
// GENERAL: the alphabet is just the literal table in source; no base64-specific
// logic appears here. Prove generality by calling this on a 64-char/3-byte and a
// 20-char/1-byte encoder and observing the same code path.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_canonicalizer::{encode_jcs, Value};
use sugar_ir_symbolic::serialize::term_to_value;
use sugar_ir_symbolic::{atomic_, make_var, num, str_const, Formula, Term};
use syn::{BinOp, Expr, Lit, Pat, Stmt};

// Second accepted body shape (value: &str, .as_bytes() indexing):
//
//   fn <name>(<param>: &str) -> String {
//       const <TABLE>: &[u8] = b"<alphabet>";
//       let b0 = <param>.as_bytes()[0] as u32;
//       let b1 = <param>.as_bytes()[1] as u32;
//       // ... more byte vars ...
//       [TABLE[<bv_expr>] as char, ...].into_iter().collect()
//   }
//
// The recognizer strips `.into_iter().collect()` method chains and handles
// both direct index (`param[N]`) and `.as_bytes()[N]` so the SAME code path
// fires for both `&[u8]` and `&str` encoder bodies.

// ── Public entrypoint ────────────────────────────────────────────────────────

/// Try to recognize a functional string-encoder function body and emit a
/// `str.eq-bv-blocks` atom.
///
/// Returns `Some(atomic_("str.eq-bv-blocks", [out, param, payload]))` when the
/// body matches the encoder shape, `None` otherwise.
///
/// Called from `source_contract::broad_functional_warrant` before the generic
/// EUF fallback, so encoder bodies get strong symbolic teeth instead of the
/// opaque `out = call:NAME(...)` warrant.
pub(crate) fn recognize_and_emit_encoder_contract(
    _name: &str,
    sig: &syn::Signature,
    block: &syn::Block,
) -> Option<Rc<Formula>> {
    let param_name = first_param_name(sig)?;
    let stmts = &block.stmts;
    // Minimum viable body: const TABLE, at least one byte assign, return expr.
    if stmts.len() < 3 {
        return None;
    }
    let (table_name, table_bytes) = recognize_table_binding(&stmts[0])?;
    let (byte_names, ret_expr) = recognize_ord_assigns_and_return(&stmts[1..], &param_name)?;
    if byte_names.is_empty() {
        return None;
    }
    let byte_vars: BTreeMap<String, Rc<Term>> = byte_names
        .iter()
        .map(|n| (n.clone(), make_var(n.as_str())))
        .collect();
    let floor = reduce_encoded_string(ret_expr, &table_name, &table_bytes, &byte_vars)?;
    let payload = build_payload(&byte_names, &floor);
    Some(atomic_(
        "str.eq-bv-blocks",
        vec![
            make_var("out"),
            make_var(param_name.as_str()),
            str_const(payload),
        ],
    ))
}

// ── Private types ────────────────────────────────────────────────────────────

/// The accumulated output of the encoder body walk:
/// the table byte values and the symbolic BV index term for each output char.
struct EncodedStringFloor {
    table: Vec<u8>,
    indices: Vec<Rc<Term>>,
}

// ── Step 1: table binding ────────────────────────────────────────────────────

/// Recognize `const <NAME>: &[u8] = b"...";` or `let <name> = b"...";` as the
/// first statement in an encoder body.
fn recognize_table_binding(stmt: &Stmt) -> Option<(String, Vec<u8>)> {
    match stmt {
        Stmt::Item(syn::Item::Const(item)) => {
            let bytes = byte_str_literal(&*item.expr)?;
            Some((item.ident.to_string(), bytes))
        }
        Stmt::Local(local) => {
            let Pat::Ident(id) = &local.pat else {
                return None;
            };
            let init = local.init.as_ref()?;
            let bytes = byte_str_literal(&*init.expr)?;
            Some((id.ident.to_string(), bytes))
        }
        _ => None,
    }
}

/// Extract the byte values from a `b"..."` literal, possibly wrapped in
/// `as &[u8]`, parens, or groups.
fn byte_str_literal(expr: &Expr) -> Option<Vec<u8>> {
    match expr {
        Expr::Lit(lit_expr) => match &lit_expr.lit {
            Lit::ByteStr(bs) => Some(bs.value()),
            _ => None,
        },
        Expr::Cast(cast) => byte_str_literal(&cast.expr),
        Expr::Reference(r) => byte_str_literal(&r.expr),
        Expr::Group(g) => byte_str_literal(&g.expr),
        Expr::Paren(p) => byte_str_literal(&p.expr),
        _ => None,
    }
}

// ── Step 2: byte-var bindings ────────────────────────────────────────────────

/// Consume as many `let bN = param[N] as u32;` stmts as possible, then return
/// the byte variable names in order and the return expression.
fn recognize_ord_assigns_and_return<'a>(
    stmts: &'a [Stmt],
    param_name: &str,
) -> Option<(Vec<String>, &'a Expr)> {
    let mut byte_names: Vec<String> = Vec::new();
    let mut idx = 0;
    while idx < stmts.len() {
        match recognize_byte_assign(&stmts[idx], param_name) {
            Some(name) => {
                byte_names.push(name);
                idx += 1;
            }
            None => break,
        }
    }
    if byte_names.is_empty() {
        return None;
    }
    let remaining = &stmts[idx..];
    let ret_expr = match remaining {
        // Implicit return: last expression without a semicolon.
        [Stmt::Expr(expr, None)] => expr,
        // Explicit `return expr;`
        [Stmt::Expr(Expr::Return(ret), _)] => ret.expr.as_deref()?,
        _ => return None,
    };
    Some((byte_names, ret_expr))
}

/// Recognize a byte-variable binding in encoder bodies. Accepts two shapes:
///
///   Shape 1: `let <name> = <param>[<N>] as <int_ty>;`  (param: &[u8])
///   Shape 2: `let <name> = <param>.as_bytes()[<N>] as <int_ty>;`  (param: &str)
///
/// N must be a literal integer; `param_name` is the function's first parameter.
fn recognize_byte_assign(stmt: &Stmt, param_name: &str) -> Option<String> {
    let Stmt::Local(local) = stmt else {
        return None;
    };
    let Pat::Ident(id) = &local.pat else {
        return None;
    };
    let init = local.init.as_ref()?;
    // Must be `<expr> as <type>` (a cast to u32/u8/usize/etc.)
    let stripped = strip_parens(&*init.expr);
    let Expr::Cast(cast) = stripped else {
        return None;
    };
    // Inner must be a subscript `<base>[N]` with a literal integer index.
    let inner = strip_parens(&cast.expr);
    let Expr::Index(index) = inner else {
        return None;
    };
    if !expr_is_int_lit(&index.index) {
        return None;
    }
    // Shape 1: direct index on the parameter — param[N]
    if expr_is_path(&index.expr, param_name) {
        return Some(id.ident.to_string());
    }
    // Shape 2: index on param.as_bytes() — param.as_bytes()[N]
    if is_as_bytes_call(&index.expr, param_name) {
        return Some(id.ident.to_string());
    }
    None
}

/// True iff `expr` is a zero-argument `.as_bytes()` method call on `param_name`.
///
/// Matches `<param>.as_bytes()` (and paren/group-wrapped variants).
fn is_as_bytes_call(expr: &Expr, param_name: &str) -> bool {
    match strip_parens(expr) {
        Expr::MethodCall(mc) => {
            mc.method == "as_bytes"
                && mc.args.is_empty()
                && expr_is_path(&mc.receiver, param_name)
        }
        _ => false,
    }
}

// ── Step 3: return expression walker ─────────────────────────────────────────

/// Walk the return expression into an `EncodedStringFloor`.
///
/// Accepted shapes (recursively):
///   `Expr::Array([e0, e1, ..])` -- each element must reduce to a table lookup
///   `Expr::Binary(op: Add, ..)` -- string concat: recurse both sides
///   `Expr::Index(TABLE, bv_expr)` -- single table lookup -> one index term
///   `Expr::Cast(inner, _)` -- strip and recurse (handles `as usize` wrappers)
///   `Expr::Paren / Group` -- strip and recurse
fn reduce_encoded_string(
    expr: &Expr,
    table_name: &str,
    table_bytes: &[u8],
    byte_vars: &BTreeMap<String, Rc<Term>>,
) -> Option<EncodedStringFloor> {
    match strip_parens(expr) {
        Expr::Array(arr) => {
            let mut all_indices: Vec<Rc<Term>> = Vec::new();
            for elem in &arr.elems {
                let floor =
                    reduce_encoded_string(elem, table_name, table_bytes, byte_vars)?;
                // Every element's table must match the outer binding.
                if floor.table != table_bytes {
                    return None;
                }
                all_indices.extend(floor.indices);
            }
            if all_indices.is_empty() {
                return None;
            }
            Some(EncodedStringFloor {
                table: table_bytes.to_vec(),
                indices: all_indices,
            })
        }
        Expr::Binary(bin) if matches!(bin.op, BinOp::Add(_)) => {
            // Rust string-concat: left + right, both must be table lookups.
            let left =
                reduce_encoded_string(&bin.left, table_name, table_bytes, byte_vars)?;
            let right =
                reduce_encoded_string(&bin.right, table_name, table_bytes, byte_vars)?;
            if left.table != right.table {
                return None;
            }
            let mut indices = left.indices;
            indices.extend(right.indices);
            Some(EncodedStringFloor {
                table: left.table,
                indices,
            })
        }
        Expr::Index(idx_expr) => {
            // Container must be the table variable; index must BV-reduce.
            if !expr_is_path(&idx_expr.expr, table_name) {
                return None;
            }
            let bv_term = reduce_bv_index(&idx_expr.index, byte_vars)?;
            Some(EncodedStringFloor {
                table: table_bytes.to_vec(),
                indices: vec![bv_term],
            })
        }
        Expr::Cast(cast) => {
            // `as usize` wrappers on the whole expression are transparent.
            reduce_encoded_string(&cast.expr, table_name, table_bytes, byte_vars)
        }
        Expr::MethodCall(mc) => {
            // Strip zero-argument iterator-adapter method calls that do not
            // change the semantic content of the encoder's output sequence:
            //   `[...].into_iter().collect()`
            //   `[...].iter().collect()`
            // The recognizer looks past these wrappers to the underlying array.
            let method = mc.method.to_string();
            if mc.args.is_empty()
                && matches!(method.as_str(), "into_iter" | "collect" | "iter")
            {
                reduce_encoded_string(&mc.receiver, table_name, table_bytes, byte_vars)
            } else {
                None
            }
        }
        _ => None,
    }
}

// ── Step 3b: BV index walker ──────────────────────────────────────────────────

/// Walk a BV index expression into a symbolic `Term`.
///
/// Handles:
///   `Binary(Shl/Shr/BitAnd/BitOr)` -> `Ctor("bv32.*", [l, r])`
///   `Cast(inner, _)` -> strip and recurse
///   `Paren / Group` -> strip and recurse (via strip_parens at entry)
///   `Path(name)` where name is in `byte_vars` -> the pre-built `Var` term
///   `Lit(Int(v))` -> `num(v)`
///
/// Mirrors `bv_binop.rs::bv32_op_name` exactly so the payload ctor names
/// (`bv32.and/or/shl/lshr`) match what `render_bv_index_json` in
/// `sugar-ir-compiler-smt-lib` expects.
fn reduce_bv_index(
    expr: &Expr,
    byte_vars: &BTreeMap<String, Rc<Term>>,
) -> Option<Rc<Term>> {
    match strip_parens(expr) {
        Expr::Binary(bin) => {
            let op_name = bv32_op_name(&bin.op)?;
            let l = reduce_bv_index(&bin.left, byte_vars)?;
            let r = reduce_bv_index(&bin.right, byte_vars)?;
            Some(Rc::new(Term::Ctor {
                name: op_name.to_string(),
                args: vec![l, r],
            }))
        }
        Expr::Cast(cast) => reduce_bv_index(&cast.expr, byte_vars),
        Expr::Path(p) if p.qself.is_none() => {
            let ident = p.path.get_ident()?.to_string();
            byte_vars.get(&ident).cloned()
        }
        Expr::Lit(lit_expr) => {
            if let Lit::Int(int_lit) = &lit_expr.lit {
                let v: i128 = int_lit.base10_parse().ok()?;
                Some(num(v))
            } else {
                None
            }
        }
        _ => None,
    }
}

/// Map a bit-operation `BinOp` to the canonical `bv32.*` ctor name.
/// Returns `None` for arithmetic ops (those are not valid BV index ops).
fn bv32_op_name(op: &BinOp) -> Option<&'static str> {
    match op {
        BinOp::Shl(_) => Some("bv32.shl"),
        BinOp::Shr(_) => Some("bv32.lshr"),
        BinOp::BitAnd(_) => Some("bv32.and"),
        BinOp::BitOr(_) => Some("bv32.or"),
        _ => None,
    }
}

// ── Step 4: payload serialization ─────────────────────────────────────────────

/// Build the JCS-encoded payload string for the `str.eq-bv-blocks` atom.
///
/// Format (keys sorted alphabetically by JCS):
///   {"per_char": [<term_json>, ...], "table": [<int>, ...], "vars": ["b0", ...]}
///
/// The `per_char` terms are serialized via `term_to_value` which emits Rust
/// ctor names (`bv32.lshr` etc.) -- matching what `render_bv_index_json` in
/// the SMT compiler expects.
fn build_payload(byte_names: &[String], floor: &EncodedStringFloor) -> String {
    let per_char: Vec<_> = floor
        .indices
        .iter()
        .map(|t| term_to_value(t))
        .collect();
    let table: Vec<_> = floor
        .table
        .iter()
        .map(|&b| Value::integer(b as i128))
        .collect();
    let vars: Vec<_> = byte_names
        .iter()
        .map(|n| Value::string(n.clone()))
        .collect();
    let payload = Value::object([
        ("per_char", Value::array(per_char)),
        ("table", Value::array(table)),
        ("vars", Value::array(vars)),
    ]);
    encode_jcs(&payload)
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/// Extract the first positional parameter name from the function signature.
/// Skips receiver params (`self`).
fn first_param_name(sig: &syn::Signature) -> Option<String> {
    sig.inputs.iter().find_map(|arg| match arg {
        syn::FnArg::Typed(pt) => match &*pt.pat {
            Pat::Ident(id) => Some(id.ident.to_string()),
            _ => None,
        },
        syn::FnArg::Receiver(_) => None,
    })
}

/// Strip `Paren` and `Group` wrappers recursively, returning the innermost
/// non-paren non-group expression.
fn strip_parens(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(p) => strip_parens(&p.expr),
        Expr::Group(g) => strip_parens(&g.expr),
        _ => expr,
    }
}

/// True iff `expr` (after stripping parens) is a simple path equal to `name`.
fn expr_is_path(expr: &Expr, name: &str) -> bool {
    match strip_parens(expr) {
        Expr::Path(p) => p.qself.is_none() && p.path.is_ident(name),
        _ => false,
    }
}

/// True iff `expr` (after stripping parens) is an integer literal.
fn expr_is_int_lit(expr: &Expr) -> bool {
    match strip_parens(expr) {
        Expr::Lit(l) => matches!(l.lit, Lit::Int(_)),
        _ => false,
    }
}

#[cfg(test)]
mod unit_tests {
    use super::*;
    use syn::parse_quote;

    fn call_recognizer(src: syn::ItemFn) -> Option<Rc<Formula>> {
        recognize_and_emit_encoder_contract(&src.sig.ident.to_string(), &src.sig, &src.block)
    }

    #[test]
    fn recognizes_base64_body() {
        let f: syn::ItemFn = parse_quote! {
            fn enc(value: &[u8]) -> [u8; 4] {
                const ALPHA: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
                let b0 = value[0] as u32;
                let b1 = value[1] as u32;
                let b2 = value[2] as u32;
                [
                    ALPHA[(b0 >> 2) as usize],
                    ALPHA[(((b0 & 3) << 4) | (b1 >> 4)) as usize],
                    ALPHA[(((b1 & 15) << 2) | (b2 >> 6)) as usize],
                    ALPHA[(b2 & 63) as usize],
                ]
            }
        };
        let result = call_recognizer(f);
        assert!(result.is_some(), "encoder body must be recognized");
    }

    #[test]
    fn recognizes_str_param_as_bytes_collect_body() {
        // &str param + .as_bytes()[N] + [... as char].into_iter().collect() shape.
        let f: syn::ItemFn = parse_quote! {
            fn enc(value: &str) -> String {
                const ALPHA: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
                let b0 = value.as_bytes()[0] as u32;
                let b1 = value.as_bytes()[1] as u32;
                let b2 = value.as_bytes()[2] as u32;
                [
                    ALPHA[(b0 >> 2) as usize] as char,
                    ALPHA[(((b0 & 3) << 4) | (b1 >> 4)) as usize] as char,
                    ALPHA[(((b1 & 15) << 2) | (b2 >> 6)) as usize] as char,
                    ALPHA[(b2 & 63) as usize] as char,
                ]
                .into_iter()
                .collect()
            }
        };
        let result = call_recognizer(f);
        assert!(result.is_some(), "str-param encoder with .as_bytes() and .collect() must be recognized");
    }

    #[test]
    fn declines_body_without_table() {
        let f: syn::ItemFn = parse_quote! {
            fn plain(x: u32) -> u32 { x + 1 }
        };
        assert!(
            call_recognizer(f).is_none(),
            "body without const table must not match"
        );
    }

    #[test]
    fn declines_body_without_byte_assigns() {
        let f: syn::ItemFn = parse_quote! {
            fn indexed(value: &[u8]) -> u8 {
                const T: &[u8] = b"ABC";
                value[0]
            }
        };
        assert!(
            call_recognizer(f).is_none(),
            "body without byte-assign stmts must not match"
        );
    }
}

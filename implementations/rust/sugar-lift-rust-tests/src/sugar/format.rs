// SPDX-License-Identifier: Apache-2.0
//
// `FormatSugar`: the general string-formatting unroller. A `format!`/`.to_string()`/
// `concat!`/string-`+` over operands that all resolve to WRITTEN LITERALS is sugar for
// ONE reproducible string. We compute it by reconstructing the typed literal values
// from the AST and calling **Rust's real `format!`** at lift time. The lifter is built
// with stdlib, so its `format!` IS stdlib's — this is RECOMPUTE-DON'T-REIMPLEMENT, the
// same dissolution doctrine `flt2dec_eval` applies to floats, generalized to all the
// Display/Debug scalars the corpus formats (the ONE stdlib exception, T's ruling
// 2026-06-14: the rust kit owns rust's stdlib, so a closed/deterministic/total/
// effect-free formatting term has one value we may compute with the same stdlib we
// ship). The resulting string is a LITERAL AXIOM the caller lowers to a `str_const`,
// so an `assert_eq!(format!(…), "…")` becomes the REAL constant equality
// `eq(str_const(computed), str_const(expected))` — z3-checkable, with TEETH (a wrong
// expected string is z3-UNSAT), NOT the opaque `macro:format!(…)` EUF var the term
// translator falls back to (which the solver satisfies tautologically — no teeth).
//
// COMPOSITIONAL. Each format ARGUMENT is itself resolved through this same module:
// `format!("{}", x)` digs when `x` resolves to a literal (inline literal, a `let`/
// `const`-bound literal, a nested `format!`/`concat!`/`.to_string()`); it BAILS (a
// genuinely runtime arg) when `x` is opaque. The format-string operand MUST be a
// literal; a runtime format string bails.
//
// REFUSE BY NAME, NEVER GUESS. A format spec we do not FAITHFULLY reproduce
// (`{:p}` pointer, an unhandled fill/align/width/sign/precision combination) does not
// dig — it bails so the caller falls through to the conservative opaque path. We only
// dig a spec we render through a STATICALLY-WRITTEN real `format!` call (we cannot pass
// a runtime spec string to `format!`, whose first arg must be a compile-time literal;
// so each supported spec is one written arm calling the real macro). `f16`/`f128` are
// unstable and unformattable on the stable toolchain the lifter ships — they bail with
// a terminal Display-unsupported reason carrying the k-remedy (build on nightly).

use std::collections::BTreeMap;

use syn::punctuated::Punctuated;
use syn::{Expr, ExprLit, Lit, Pat, Stmt, Token};

use crate::{strip_refs_groups, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx};

/// The terminal reason for an `f16`/`f128` formatting operand: the stable toolchain
/// the lifter ships cannot Display it, and we never model the algorithm (no-model
/// axiom). Carries its own k-remedy. Mirrors the existing flt2dec f16/f128 terminal.
pub(crate) const F16_F128_DISPLAY_UNSUPPORTED: &str =
    "format: f16/f128 Display is unsupported by stdlib on the stable toolchain the \
     lifter ships; build on nightly to enable; refused";

/// Build a `&str` literal expr from a Rust string value (so a resolved format string
/// can flow back through the normal term translator's `Lit::Str -> str_const` path).
fn string_literal_expr(s: &str) -> Expr {
    Expr::Lit(ExprLit {
        attrs: Vec::new(),
        lit: Lit::Str(syn::LitStr::new(s, proc_macro2::Span::call_site())),
    })
}

/// A recognized string-formatting construction whose operands MAY all resolve to
/// literals. `let_bindings` resolves a `let`/`const`-bound operand to its written
/// literal (one or more pure indirections), exactly like `RegexSugar`'s pattern
/// resolver. Recognition keys on the construction SHAPE; whether the operands resolve
/// to literals is decided LATER by `desugar` (the dig), so a binding/nested-format
/// operand is recognized and composes.
pub(crate) struct FormatSugar {
    expr: Expr,
    let_bindings: BTreeMap<String, Expr>,
}

impl Sugar for FormatSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        match resolve_format_string(&self.expr, &self.let_bindings) {
            Ok(Some(s)) => Outcome::Dug(Desugared::Seq(vec![DesugaredElem {
                expr: string_literal_expr(&s),
                value: None,
            }])),
            // A runtime / unsupported producer (runtime arg, runtime fmt string, an
            // unsupported spec) -> bail TODAY. The caller falls through to its
            // conservative path (the opaque `macro:` EUF var). The structural backstop
            // (`Hit(Effect::Unsupported)`).
            Ok(None) => Outcome::from_opt(None),
            // A NAMED terminal (f16/f128 Display unsupported) -> the caller surfaces
            // this reason; for now a bail with the structural backstop is the
            // conservative wire (the caller's fall-through emits its own reason). We
            // still distinguish it for the recognizer-level refusal at the call site.
            Err(_) => Outcome::from_opt(None),
        }
    }
}

/// Build a `FormatSugar` for any format-producing SHAPE (`format!`/`concat!`/
/// `.to_string()`/ string `+`), else `None` (decline to recognize — not this node).
/// Recognition does NOT pre-judge resolvability; the dig decides that.
pub(crate) fn decompose_format(
    expr: &Expr,
    let_bindings: &BTreeMap<String, Expr>,
) -> Option<FormatSugar> {
    if !is_format_shape(expr) {
        return None;
    }
    Some(FormatSugar {
        expr: expr.clone(),
        let_bindings: let_bindings.clone(),
    })
}

/// Is `expr` one of the recognized format-producing shapes? (Recognition only — the
/// operands need not be literals here.)
fn is_format_shape(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Macro(m) => {
            let id = m.mac.path.segments.last().map(|s| s.ident.to_string());
            matches!(id.as_deref(), Some("format") | Some("concat"))
        }
        Expr::MethodCall(c) => c.method == "to_string" && c.args.is_empty(),
        Expr::Binary(b) => matches!(b.op, syn::BinOp::Add(_)),
        _ => false,
    }
}

// ── The core: resolve a format-producing expr to its ONE string value ────────────
//
// Result semantics:
//   Ok(Some(s)) — dissolved to the string `s` (recompute via real `format!`).
//   Ok(None)    — a genuinely runtime / unsupported-but-unnamed operand: bail (the
//                 conservative opaque fall-through; safe under-claim).
//   Err(reason) — a NAMED terminal (f16/f128 Display unsupported); refuse by name.

/// A typed literal value reconstructed from the source AST, carrying enough to render
/// it through the real stdlib `format!` for every spec we faithfully reproduce.
enum FmtValue {
    /// An integer with its width suffix (so `{:x}`/`{:b}`/`{:o}` render at the right
    /// width and a value's signed/unsigned-ness is honored). i128 carrier; the suffix
    /// drives the actual render.
    Int {
        value: i128,
        suffix: IntKind,
    },
    F32(f32),
    F64(f64),
    Char(char),
    Str(String),
    Bool(bool),
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum IntKind {
    I8,
    I16,
    I32,
    I64,
    I128,
    Isize,
    U8,
    U16,
    U32,
    U64,
    U128,
    Usize,
    /// An unsuffixed integer literal — rust defaults it to `i32`.
    Unsuffixed,
}

/// Resolve a format-producing expr (or, compositionally, any operand) to its string
/// value. The TOP-LEVEL caller passes a `format!`/`concat!`/`.to_string()`/`+`; the
/// recursion also handles literal operands and `let`/`const` indirections.
fn resolve_format_string(
    expr: &Expr,
    binds: &BTreeMap<String, Expr>,
) -> Result<Option<String>, String> {
    match strip_refs_groups(expr) {
        Expr::Macro(m) if macro_is(m, "format") => {
            let args = match parse_args(&m.mac.tokens) {
                Some(a) => a,
                None => return Ok(None),
            };
            let Some((fmt_expr, rest)) = args.split_first() else {
                return Ok(None);
            };
            // The format string MUST be a literal (a runtime fmt string bails).
            let Some(fmt) = resolve_str_literal_only(fmt_expr, binds)? else {
                return Ok(None);
            };
            render_format(&fmt, rest, binds)
        }
        Expr::Macro(m) if macro_is(m, "concat") => {
            let args = match parse_args(&m.mac.tokens) {
                Some(a) => a,
                None => return Ok(None),
            };
            let mut out = String::new();
            for a in &args {
                match resolve_concat_fragment(a, binds)? {
                    Some(frag) => out.push_str(&frag),
                    None => return Ok(None),
                }
            }
            Ok(Some(out))
        }
        // `<expr>.to_string()` — Display of the resolved value.
        Expr::MethodCall(c) if c.method == "to_string" && c.args.is_empty() => {
            match resolve_fmt_value(&c.receiver, binds)? {
                Some(v) => render_one(&v, &Spec::display()),
                None => Ok(None),
            }
        }
        // String `+`: `a + b` where both sides resolve to strings (`String + &str`).
        Expr::Binary(b) if matches!(b.op, syn::BinOp::Add(_)) => {
            let l = resolve_string_operand(&b.left, binds)?;
            let r = resolve_string_operand(&b.right, binds)?;
            match (l, r) {
                (Some(ls), Some(rs)) => Ok(Some(format!("{ls}{rs}"))),
                _ => Ok(None),
            }
        }
        // NOT a format-producing shape -> resolve only as a literal/bound string
        // operand. CRUCIAL: this arm must NOT re-dispatch a non-format MethodCall back
        // into `resolve_string_operand` (which would re-enter here) -- that is the
        // recursion cycle. A bare runtime MethodCall (`foo.bar()`) is simply not a
        // string we can resolve -> the literal/path resolver returns `Ok(None)`.
        _ => resolve_string_operand(expr, binds),
    }
}

/// Resolve an operand that must be a STRING value (for `+` / `concat!` string
/// fragments): a `&str` literal, a `let`/`const`-bound one, or a nested
/// `format!`/`concat!`/`.to_string()`. A non-format MethodCall / non-string operand
/// returns `Ok(None)` (no recursion into the dispatcher -- the cycle guard).
fn resolve_string_operand(
    expr: &Expr,
    binds: &BTreeMap<String, Expr>,
) -> Result<Option<String>, String> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Str(s), ..
        }) => Ok(Some(s.value())),
        Expr::Path(p) if p.qself.is_none() => match p.path.get_ident() {
            Some(id) => match binds.get(&id.to_string()) {
                Some(bound) => resolve_string_operand(bound, binds),
                None => Ok(None),
            },
            None => Ok(None),
        },
        // ONLY recurse into the dispatcher for a RECOGNIZED format shape
        // (`format!`/`concat!`/`.to_string()`/string `+`); anything else is not a
        // resolvable string -> `Ok(None)`. This guard breaks the recursion cycle.
        e if is_format_shape(e) => resolve_format_string(e, binds),
        _ => Ok(None),
    }
}

/// Resolve an operand that MUST be a plain string literal (the format-string operand):
/// inline `&str` literal, a `let`/`const`-bound one, or a `concat!` of literals. NOT a
/// `format!` (a format string is written, not computed). `None` for anything runtime.
fn resolve_str_literal_only(
    expr: &Expr,
    binds: &BTreeMap<String, Expr>,
) -> Result<Option<String>, String> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Str(s), ..
        }) => Ok(Some(s.value())),
        Expr::Path(p) if p.qself.is_none() => match p.path.get_ident() {
            Some(id) => match binds.get(&id.to_string()) {
                Some(bound) => resolve_str_literal_only(bound, binds),
                None => Ok(None),
            },
            None => Ok(None),
        },
        Expr::Macro(m) if macro_is(m, "concat") => resolve_format_string(expr, binds),
        _ => Ok(None),
    }
}

/// A `concat!` fragment: a string literal, a char/int/bool literal (concat stringifies
/// scalar literals), or a nested `concat!`. (concat! does NOT accept `format!` — only
/// literals and other concat!/stringify!-like macros; we accept the literal forms.)
fn resolve_concat_fragment(
    expr: &Expr,
    binds: &BTreeMap<String, Expr>,
) -> Result<Option<String>, String> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit { lit, .. }) => Ok(match lit {
            Lit::Str(s) => Some(s.value()),
            Lit::Char(c) => Some(c.value().to_string()),
            Lit::Int(i) => i.base10_parse::<i128>().ok().map(|n| n.to_string()),
            Lit::Bool(b) => Some(b.value.to_string()),
            Lit::Float(f) => f.base10_parse::<f64>().ok().map(|v| format!("{v}")),
            Lit::Byte(b) => Some(b.value().to_string()),
            _ => None,
        }),
        Expr::Macro(m) if macro_is(m, "concat") => resolve_format_string(expr, binds),
        Expr::Path(p) if p.qself.is_none() => match p.path.get_ident() {
            Some(id) => match binds.get(&id.to_string()) {
                Some(bound) => resolve_concat_fragment(bound, binds),
                None => Ok(None),
            },
            None => Ok(None),
        },
        _ => Ok(None),
    }
}

fn macro_is(m: &syn::ExprMacro, name: &str) -> bool {
    m.mac.path.segments.last().is_some_and(|s| s.ident == name)
}

fn parse_args(tokens: &proc_macro2::TokenStream) -> Option<Vec<Expr>> {
    let parser = syn::punctuated::Punctuated::<Expr, syn::Token![,]>::parse_terminated;
    syn::parse::Parser::parse2(parser, tokens.clone())
        .ok()
        .map(|p| p.into_iter().collect())
}

// ── Render a parsed format string with positional/named/captured arguments ───────

/// Render a `format!("<fmt>", <args>)` by parsing the fmt string into literal segments
/// and `{...}` placeholders, resolving each placeholder's argument to a `FmtValue`, and
/// rendering it through a STATICALLY-WRITTEN real `format!` per its spec. Returns
/// `Ok(None)` on any runtime arg / unsupported spec (bail); `Err` on a named terminal.
fn render_format(
    fmt: &str,
    args: &[Expr],
    binds: &BTreeMap<String, Expr>,
) -> Result<Option<String>, String> {
    let pieces = match parse_fmt_pieces(fmt) {
        Some(p) => p,
        None => return Ok(None), // malformed / unsupported brace use -> bail
    };
    // Resolve positional args once (used by `{}` / `{0}`); named/captured resolved
    // per-placeholder against the binding map (Rust 1.58 implicit capture).
    let mut next_positional = 0usize;
    let mut out = String::new();
    for piece in pieces {
        match piece {
            Piece::Lit(s) => out.push_str(&s),
            Piece::Placeholder { arg, spec } => {
                let value = match arg {
                    ArgRef::Implicit => {
                        let e = args.get(next_positional);
                        next_positional += 1;
                        match e {
                            Some(e) => resolve_fmt_value(e, binds)?,
                            None => return Ok(None),
                        }
                    }
                    ArgRef::Positional(i) => match args.get(i) {
                        Some(e) => resolve_fmt_value(e, binds)?,
                        None => return Ok(None),
                    },
                    ArgRef::Named(name) => {
                        // A named arg `{x}` is either an explicit `x = <expr>` trailing
                        // argument OR an implicit capture of an in-scope `let`/`const`
                        // binding. We support the implicit-capture case (the corpus's
                        // `{max}` / `{socket}` forms) by resolving the name through the
                        // binding map; an explicit `name = expr` arg form is parsed as a
                        // `syn::Expr::Assign` in `args` — handle that too.
                        match named_arg_expr(&name, args) {
                            Some(e) => resolve_fmt_value(&e, binds)?,
                            None => match binds.get(&name) {
                                Some(bound) => resolve_fmt_value(bound, binds)?,
                                None => return Ok(None),
                            },
                        }
                    }
                };
                match value {
                    Some(v) => match render_one(&v, &spec)? {
                        Some(s) => out.push_str(&s),
                        None => return Ok(None),
                    },
                    None => return Ok(None),
                }
            }
        }
    }
    Ok(Some(out))
}

/// Find an explicit `name = <expr>` trailing format argument.
fn named_arg_expr(name: &str, args: &[Expr]) -> Option<Expr> {
    for a in args {
        if let Expr::Assign(assign) = a {
            if let Expr::Path(p) = &*assign.left {
                if p.path.is_ident(name) {
                    return Some((*assign.right).clone());
                }
            }
        }
    }
    None
}

// ── Format-string mini-parser ────────────────────────────────────────────────────

enum Piece {
    Lit(String),
    Placeholder { arg: ArgRef, spec: Spec },
}

enum ArgRef {
    Implicit,
    Positional(usize),
    Named(String),
}

/// Parse a format string into literal segments and placeholders. Handles `{{`/`}}`
/// escapes. Returns `None` on a malformed brace structure (so the caller bails rather
/// than guess).
fn parse_fmt_pieces(fmt: &str) -> Option<Vec<Piece>> {
    let mut pieces = Vec::new();
    let mut lit = String::new();
    let bytes = fmt.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        let c = bytes[i] as char;
        if c == '{' {
            if i + 1 < bytes.len() && bytes[i + 1] == b'{' {
                lit.push('{');
                i += 2;
                continue;
            }
            // start of a placeholder; find the matching '}'
            let close = fmt[i + 1..].find('}').map(|j| i + 1 + j)?;
            if !lit.is_empty() {
                pieces.push(Piece::Lit(std::mem::take(&mut lit)));
            }
            let inner = &fmt[i + 1..close];
            let (arg, spec) = parse_placeholder(inner)?;
            pieces.push(Piece::Placeholder { arg, spec });
            i = close + 1;
        } else if c == '}' {
            if i + 1 < bytes.len() && bytes[i + 1] == b'}' {
                lit.push('}');
                i += 2;
                continue;
            }
            // a lone '}' is malformed
            return None;
        } else {
            lit.push(c);
            i += c.len_utf8();
        }
    }
    if !lit.is_empty() {
        pieces.push(Piece::Lit(lit));
    }
    Some(pieces)
}

/// Parse a placeholder's inner text `arg:spec` into `(ArgRef, Spec)`. The arg part
/// (before `:`) is implicit/positional/named; the spec part is parsed by `Spec`.
fn parse_placeholder(inner: &str) -> Option<(ArgRef, Spec)> {
    let (arg_str, spec_str) = match inner.split_once(':') {
        Some((a, s)) => (a, s),
        None => (inner, ""),
    };
    let arg = if arg_str.is_empty() {
        ArgRef::Implicit
    } else if let Ok(n) = arg_str.parse::<usize>() {
        ArgRef::Positional(n)
    } else if is_ident(arg_str) {
        ArgRef::Named(arg_str.to_string())
    } else {
        return None;
    };
    let spec = Spec::parse(spec_str)?;
    Some((arg, spec))
}

fn is_ident(s: &str) -> bool {
    let mut chars = s.chars();
    match chars.next() {
        Some(c) if c.is_alphabetic() || c == '_' => {}
        _ => return false,
    }
    chars.all(|c| c.is_alphanumeric() || c == '_')
}

// ── The format spec we faithfully reproduce ──────────────────────────────────────
//
// We support the closed set of specs the corpus uses that we can render through a
// STATICALLY-WRITTEN real `format!` call: the trait kind (Display / Debug / lower-hex /
// upper-hex / binary / octal / lower-exp / upper-exp), an optional `+` sign, optional
// `0`-pad-to-width, and optional `.N` precision. A width WITHOUT zero-pad (alignment /
// fill — `{:>9}`, `{:^9}`) and the pointer kind `{:p}` are NOT reproduced here -> bail.

#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    Display,
    Debug,
    LowerHex,
    UpperHex,
    Binary,
    Octal,
    LowerExp,
    UpperExp,
}

struct Spec {
    kind: Kind,
    plus: bool,
    zero_width: Option<usize>,
    precision: Option<usize>,
}

impl Spec {
    fn display() -> Spec {
        Spec {
            kind: Kind::Display,
            plus: false,
            zero_width: None,
            precision: None,
        }
    }

    /// Parse a format SPEC (the part after `:`). Returns `None` for any spec feature we
    /// do NOT faithfully reproduce (fill/align, non-zero width, pointer, `#`
    /// alternate, `$`/`*` dynamic width, etc.) — refuse by NOT digging, never guess.
    fn parse(spec: &str) -> Option<Spec> {
        let mut s = spec;
        let mut plus = false;
        let mut zero_width = None;
        let mut precision = None;

        // [[fill]align] — we do NOT reproduce fill/align, so reject if present. An
        // align char is one of < ^ >, optionally preceded by a fill char.
        // Detect: second char is an align, or first char is an align.
        let chars: Vec<char> = s.chars().collect();
        if let Some(&c0) = chars.first() {
            if matches!(c0, '<' | '^' | '>') {
                return None;
            }
            if chars.len() >= 2 && matches!(chars[1], '<' | '^' | '>') {
                return None;
            }
        }

        // [sign] — `+` supported, `-` is a no-op in rust (rejected to be safe).
        if let Some(rest) = s.strip_prefix('+') {
            plus = true;
            s = rest;
        } else if s.starts_with('-') {
            return None;
        }

        // `#` alternate — not reproduced here (e.g. `{:#?}`, `{:#x}`). Bail.
        if s.starts_with('#') {
            return None;
        }

        // [0][width] — we ONLY reproduce a `0`-padded fixed width. A bare width (no
        // leading 0) is an alignment we do not reproduce -> bail.
        if let Some(rest) = s.strip_prefix('0') {
            // parse the width digits
            let digits: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
            if !digits.is_empty() {
                zero_width = Some(digits.parse().ok()?);
                s = &rest[digits.len()..];
            } else {
                // `{:0}` with no width — degenerate; treat as width 0 (no pad) and
                // continue (rare). Effectively a no-op.
                s = rest;
            }
        } else if s.chars().next().is_some_and(|c| c.is_ascii_digit()) {
            // a bare width (alignment to a min width) — not reproduced -> bail.
            return None;
        }

        // [.precision]
        if let Some(rest) = s.strip_prefix('.') {
            let digits: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
            // `.*` / `.N$` dynamic precision -> bail.
            if digits.is_empty() {
                return None;
            }
            precision = Some(digits.parse().ok()?);
            s = &rest[digits.len()..];
        }

        // [type] — the trailing trait selector.
        let kind = match s {
            "" => Kind::Display,
            "?" => Kind::Debug,
            "x" => Kind::LowerHex,
            "X" => Kind::UpperHex,
            "b" => Kind::Binary,
            "o" => Kind::Octal,
            "e" => Kind::LowerExp,
            "E" => Kind::UpperExp,
            // `p` pointer / `x?`/`X?` hex-debug / anything else -> not reproduced.
            _ => return None,
        };

        Some(Spec {
            kind,
            plus,
            zero_width,
            precision,
        })
    }
}

// ── Render ONE value through the REAL stdlib `format!` per its spec ───────────────
//
// We cannot pass a runtime spec string to `format!` (its first arg is a compile-time
// literal), so each supported (kind, plus, zero_width, precision) combination dispatches
// to a statically-written `format!` call. This is the recompute-don't-reimplement floor:
// the bytes come from stdlib's own formatter, never from our re-derivation.

fn render_one(v: &FmtValue, spec: &Spec) -> Result<Option<String>, String> {
    // f16/f128 never reach here (FmtValue has no such variant); reconstruction names
    // them terminal upstream. Floats only support Display/Debug/exp; ints support all.
    let s = match v {
        FmtValue::Int { value, suffix } => render_int(*value, *suffix, spec),
        FmtValue::F64(x) => render_float_f64(*x, spec),
        FmtValue::F32(x) => render_float_f32(*x, spec),
        FmtValue::Char(c) => render_char(*c, spec),
        FmtValue::Str(s) => render_str(s, spec),
        FmtValue::Bool(b) => render_bool(*b, spec),
    };
    Ok(s)
}

/// Apply the `0`-pad-to-width and `+`-sign post-formatting that our supported spec
/// allows, given an already-rendered magnitude+sign body. Used where the static
/// `format!` arm cannot itself carry the (dynamic) width. We instead build the body
/// with the real formatter and pad here ONLY for the numeric cases where `0`-fill is
/// well-defined (digits left-padded after an optional sign). Returns the padded string.
fn zero_pad(body: String, width: usize) -> String {
    if body.len() >= width {
        return body;
    }
    let pad = width - body.len();
    // 0-fill goes AFTER a leading sign (rust: `format!("{:05}", -7)` == "-0007").
    if let Some(rest) = body.strip_prefix('-') {
        format!("-{}{}", "0".repeat(pad), rest)
    } else if let Some(rest) = body.strip_prefix('+') {
        format!("+{}{}", "0".repeat(pad), rest)
    } else {
        format!("{}{}", "0".repeat(pad), body)
    }
}

fn render_int(value: i128, suffix: IntKind, spec: &Spec) -> Option<String> {
    // Precision is meaningless for integer Display/radix in rust (it's ignored for
    // integers except `e`/`E`). We bail if a precision is set on a non-exp integer
    // spec to avoid guessing.
    let unsigned = is_unsigned(suffix);
    // Render the body via the real formatter, honoring sign for Display/Debug.
    let body = match spec.kind {
        Kind::Display | Kind::Debug => {
            if spec.precision.is_some() {
                return None; // precision on an integer Display — bail (no faithful arm)
            }
            if spec.plus {
                format!("{value:+}")
            } else {
                format!("{value}")
            }
        }
        // Radix formats operate on the value's BITS at its width. We reconstruct the
        // unsigned bit pattern at the declared width so `{:x}` of `-1i8` == "ff" etc.
        Kind::LowerHex | Kind::UpperHex | Kind::Binary | Kind::Octal => {
            if spec.precision.is_some() || spec.plus {
                return None;
            }
            let bits = bits_at_width(value, suffix)?;
            match spec.kind {
                Kind::LowerHex => format!("{bits:x}"),
                Kind::UpperHex => format!("{bits:X}"),
                Kind::Binary => format!("{bits:b}"),
                Kind::Octal => format!("{bits:o}"),
                _ => unreachable!(),
            }
        }
        Kind::LowerExp | Kind::UpperExp => {
            // integer exp: rust formats the integer in exponential. Only support the
            // unsuffixed/standard widths via i128/u128 real format.
            let prec = spec.precision;
            let mut b = if unsigned {
                let u = value as u128;
                match (spec.kind, prec) {
                    (Kind::LowerExp, None) => format!("{u:e}"),
                    (Kind::UpperExp, None) => format!("{u:E}"),
                    (Kind::LowerExp, Some(p)) => format!("{u:.p$e}"),
                    (Kind::UpperExp, Some(p)) => format!("{u:.p$E}"),
                    _ => unreachable!(),
                }
            } else {
                match (spec.kind, prec) {
                    (Kind::LowerExp, None) => format!("{value:e}"),
                    (Kind::UpperExp, None) => format!("{value:E}"),
                    (Kind::LowerExp, Some(p)) => format!("{value:.p$e}"),
                    (Kind::UpperExp, Some(p)) => format!("{value:.p$E}"),
                    _ => unreachable!(),
                }
            };
            if spec.plus && value >= 0 {
                b = format!("+{b}");
            }
            b
        }
    };
    Some(match spec.zero_width {
        Some(w) => zero_pad(body, w),
        None => body,
    })
}

/// The unsigned bit pattern of `value` at its declared width, for radix rendering.
/// Bails for the i128/u128 widths only if the carrier cannot represent it (it always
/// can for i128/u128). Unsuffixed defaults to i32.
fn bits_at_width(value: i128, suffix: IntKind) -> Option<u128> {
    let bits: u128 = match suffix {
        IntKind::I8 => (value as i8) as u8 as u128,
        IntKind::U8 => (value as u8) as u128,
        IntKind::I16 => (value as i16) as u16 as u128,
        IntKind::U16 => (value as u16) as u128,
        IntKind::I32 | IntKind::Unsuffixed => (value as i32) as u32 as u128,
        IntKind::U32 => (value as u32) as u128,
        IntKind::I64 | IntKind::Isize => (value as i64) as u64 as u128,
        IntKind::U64 | IntKind::Usize => (value as u64) as u128,
        IntKind::I128 => (value as i128) as u128,
        IntKind::U128 => value as u128,
    };
    Some(bits)
}

fn is_unsigned(suffix: IntKind) -> bool {
    matches!(
        suffix,
        IntKind::U8 | IntKind::U16 | IntKind::U32 | IntKind::U64 | IntKind::U128 | IntKind::Usize
    )
}

fn render_float_f64(x: f64, spec: &Spec) -> Option<String> {
    let body = match (spec.kind, spec.precision, spec.plus) {
        (Kind::Display | Kind::Debug, None, false) => format!("{x}"),
        (Kind::Display | Kind::Debug, None, true) => format!("{x:+}"),
        (Kind::Display | Kind::Debug, Some(p), false) => format!("{x:.p$}"),
        (Kind::Display | Kind::Debug, Some(p), true) => format!("{x:+.p$}"),
        (Kind::LowerExp, None, false) => format!("{x:e}"),
        (Kind::LowerExp, Some(p), false) => format!("{x:.p$e}"),
        (Kind::UpperExp, None, false) => format!("{x:E}"),
        (Kind::UpperExp, Some(p), false) => format!("{x:.p$E}"),
        (Kind::LowerExp, None, true) => format!("{x:+e}"),
        (Kind::LowerExp, Some(p), true) => format!("{x:+.p$e}"),
        (Kind::UpperExp, None, true) => format!("{x:+E}"),
        (Kind::UpperExp, Some(p), true) => format!("{x:+.p$E}"),
        // radix on a float is a type error in rust — bail.
        _ => return None,
    };
    Some(match spec.zero_width {
        Some(w) => zero_pad(body, w),
        None => body,
    })
}

fn render_float_f32(x: f32, spec: &Spec) -> Option<String> {
    let body = match (spec.kind, spec.precision, spec.plus) {
        (Kind::Display | Kind::Debug, None, false) => format!("{x}"),
        (Kind::Display | Kind::Debug, None, true) => format!("{x:+}"),
        (Kind::Display | Kind::Debug, Some(p), false) => format!("{x:.p$}"),
        (Kind::Display | Kind::Debug, Some(p), true) => format!("{x:+.p$}"),
        (Kind::LowerExp, None, false) => format!("{x:e}"),
        (Kind::LowerExp, Some(p), false) => format!("{x:.p$e}"),
        (Kind::UpperExp, None, false) => format!("{x:E}"),
        (Kind::UpperExp, Some(p), false) => format!("{x:.p$E}"),
        (Kind::LowerExp, None, true) => format!("{x:+e}"),
        (Kind::LowerExp, Some(p), true) => format!("{x:+.p$e}"),
        (Kind::UpperExp, None, true) => format!("{x:+E}"),
        (Kind::UpperExp, Some(p), true) => format!("{x:+.p$E}"),
        _ => return None,
    };
    Some(match spec.zero_width {
        Some(w) => zero_pad(body, w),
        None => body,
    })
}

fn render_char(c: char, spec: &Spec) -> Option<String> {
    let body = match (spec.kind, spec.precision) {
        (Kind::Display, None) => format!("{c}"),
        (Kind::Debug, None) => format!("{c:?}"),
        // A char in a radix prints its code point. The corpus does not do this; bail to
        // be safe rather than guess width semantics.
        _ => return None,
    };
    if spec.plus {
        return None;
    }
    Some(match spec.zero_width {
        Some(w) => zero_pad(body, w),
        None => body,
    })
}

fn render_str(s: &str, spec: &Spec) -> Option<String> {
    if spec.plus || spec.zero_width.is_some() {
        return None; // sign/zero-pad meaningless for &str
    }
    let mut body = match spec.kind {
        Kind::Display => s.to_string(),
        Kind::Debug => format!("{s:?}"),
        _ => return None,
    };
    // `{:.N}` on a &str truncates to N chars.
    if let Some(p) = spec.precision {
        if spec.kind == Kind::Display {
            let truncated: String = s.chars().take(p).collect();
            body = truncated;
        } else {
            return None;
        }
    }
    Some(body)
}

fn render_bool(b: bool, spec: &Spec) -> Option<String> {
    if spec.plus || spec.zero_width.is_some() || spec.precision.is_some() {
        return None;
    }
    match spec.kind {
        Kind::Display => Some(format!("{b}")),
        Kind::Debug => Some(format!("{b:?}")),
        _ => None,
    }
}

// ── Reconstruct a typed literal value from the source AST ─────────────────────────

/// Resolve an argument expr to a `FmtValue` (a typed literal), composing through
/// `let`/`const` bindings and unary negation / `inf`-`NaN`-shaped float divisions (the
/// flt2dec corpus shape). `Ok(None)` for a runtime / non-literal arg (bail);
/// `Err(reason)` for a NAMED terminal (f16/f128).
fn resolve_fmt_value(
    expr: &Expr,
    binds: &BTreeMap<String, Expr>,
) -> Result<Option<FmtValue>, String> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit { lit, .. }) => reconstruct_lit(lit),
        // unary negation of a literal.
        Expr::Unary(u) if matches!(u.op, syn::UnOp::Neg(_)) => {
            match resolve_fmt_value(&u.expr, binds)? {
                Some(FmtValue::Int { value, suffix }) => Ok(Some(FmtValue::Int {
                    value: value
                        .checked_neg()
                        .ok_or_else(|| "int overflow".to_string())?,
                    suffix,
                })),
                Some(FmtValue::F64(x)) => Ok(Some(FmtValue::F64(-x))),
                Some(FmtValue::F32(x)) => Ok(Some(FmtValue::F32(-x))),
                _ => Ok(None),
            }
        }
        // float division of two literals: `1.0 / 0.0` = inf, `0.0 / 0.0` = NaN, etc.
        Expr::Binary(b) if matches!(b.op, syn::BinOp::Div(_)) => {
            match (
                resolve_fmt_value(&b.left, binds)?,
                resolve_fmt_value(&b.right, binds)?,
            ) {
                (Some(FmtValue::F64(l)), Some(FmtValue::F64(r))) => Ok(Some(FmtValue::F64(l / r))),
                (Some(FmtValue::F32(l)), Some(FmtValue::F32(r))) => Ok(Some(FmtValue::F32(l / r))),
                _ => Ok(None),
            }
        }
        // a `let`/`const`-bound name resolves to its written literal.
        Expr::Path(p) if p.qself.is_none() => match p.path.get_ident() {
            Some(id) => match binds.get(&id.to_string()) {
                Some(bound) => {
                    // guard against a self-referential binding.
                    let mut narrowed = binds.clone();
                    narrowed.remove(&id.to_string());
                    resolve_fmt_value(bound, &narrowed)
                }
                None => Ok(None),
            },
            None => Ok(None),
        },
        // a nested `format!`/`concat!`/`.to_string()`/`+` arg resolves to a string.
        // Guarded by `is_format_shape` so a bare runtime MethodCall (`foo.bar()`) is
        // `Ok(None)` directly -- never re-dispatched (the recursion-cycle guard).
        e if is_format_shape(e) => match resolve_format_string(e, binds)? {
            Some(s) => Ok(Some(FmtValue::Str(s))),
            None => Ok(None),
        },
        _ => Ok(None),
    }
}

/// Reconstruct a single literal token into a `FmtValue`. `Err` for f16/f128 (named
/// terminal); `Ok(None)` for byte-strings / other unsupported literal kinds (bail).
fn reconstruct_lit(lit: &Lit) -> Result<Option<FmtValue>, String> {
    match lit {
        Lit::Int(i) => {
            let value = match i.base10_parse::<i128>() {
                Ok(v) => v,
                // a u128 literal larger than i128::MAX.
                Err(_) => match i.base10_parse::<u128>() {
                    Ok(u) => u as i128,
                    Err(_) => return Ok(None),
                },
            };
            let suffix = match i.suffix() {
                "i8" => IntKind::I8,
                "i16" => IntKind::I16,
                "i32" => IntKind::I32,
                "i64" => IntKind::I64,
                "i128" => IntKind::I128,
                "isize" => IntKind::Isize,
                "u8" => IntKind::U8,
                "u16" => IntKind::U16,
                "u32" => IntKind::U32,
                "u64" => IntKind::U64,
                "u128" => IntKind::U128,
                "usize" => IntKind::Usize,
                "" => IntKind::Unsuffixed,
                _ => return Ok(None),
            };
            Ok(Some(FmtValue::Int { value, suffix }))
        }
        Lit::Float(f) => match f.suffix() {
            "f32" => Ok(f.base10_parse::<f32>().ok().map(FmtValue::F32)),
            "f64" | "" => Ok(f.base10_parse::<f64>().ok().map(FmtValue::F64)),
            // f16 / f128: unstable, unformattable on the stable toolchain -> named
            // terminal carrying its k-remedy.
            "f16" | "f128" => Err(F16_F128_DISPLAY_UNSUPPORTED.to_string()),
            _ => Ok(None),
        },
        Lit::Char(c) => Ok(Some(FmtValue::Char(c.value()))),
        Lit::Str(s) => Ok(Some(FmtValue::Str(s.value()))),
        Lit::Bool(b) => Ok(Some(FmtValue::Bool(b.value))),
        // a byte literal `b'0'` is a u8.
        Lit::Byte(b) => Ok(Some(FmtValue::Int {
            value: i128::from(b.value()),
            suffix: IntKind::U8,
        })),
        _ => Ok(None),
    }
}

/// Public entry: resolve a format-producing expr to its string value, classifying the
/// outcome for the caller's term-translation hook. `Ok(Some(s))` digs to `str_const(s)`;
/// `Ok(None)` falls through to the conservative opaque path; `Err(reason)` is a named
/// terminal refusal (f16/f128 Display unsupported).
pub(crate) fn try_resolve_format(
    expr: &Expr,
    let_bindings: &BTreeMap<String, Expr>,
) -> Result<Option<String>, String> {
    if !is_format_shape(expr) {
        return Ok(None);
    }
    resolve_format_string(expr, let_bindings)
}

/// The in-scope IMMUTABLE `let` bindings (`name -> init`), the map the FormatSugar
/// hooks (`a + b`, `format!`, `.to_string()`) resolve operands against: a `let mut` is
/// excluded so a mutated operand is never mis-dissolved. Byte-identical to the inline
/// `stable` map the old inline term translation built from `scope.let_bindings`.
pub(crate) fn stable_let_bindings(scope: &crate::TemporalScope) -> BTreeMap<String, Expr> {
    scope
        .let_bindings_iter()
        .filter(|(name, _)| !scope.is_mut_local(name))
        .map(|(name, init)| (name.clone(), init.clone()))
        .collect()
}

// ─────────────────────────────────────────────────────────────────────────────────
// FLOAT-FORMATTING ENGINE (subsumes the former `flt2dec_eval.rs`).
//
// The four `core::num::imp::flt2dec` test-helper surfaces (`to_shortest_str` /
// `to_exact_fixed_str` / `to_exact_exp_str` / `to_shortest_exp_str`) format a closed
// float with a sign-mode and a digit count. They are NOT plain `format!` calls, but
// each one IS a `format!` rendering of the value — so FormatSugar, the single format
// authority, computes them HERE with the lifter's own stdlib `format!` (recompute-
// don't-reimplement), exactly as it computes a `format!("{}", x)`. The flt2dec
// recognizer (lib.rs `dissolve_flt2dec_assert`) reconstructs the `(value, sign, mode,
// digits)` operands and calls these functions; the float-formatting computation lives
// here, in FormatSugar, not in a separate float-only module.
//
// `format!` is itself built on `core::num`'s flt2dec, so this evaluation and the
// term-under-test compute the IDENTICAL canonical shortest/exact decimal — an
// INDEPENDENT correct recomputation, sound by recompute-don't-trust.

/// `m * 2^exp`, computed by exact stepwise scaling (matching the corpus's own
/// `ldexp_fN` helper). We deliberately do NOT use `2f64.powi(exp)`: for extreme
/// negative exponents (`ldexp_f64(1.0, -1074)`) `powi` underflows to `0.0`, while
/// stepwise `*= 0.5` is each-step exact and reproduces the subnormal bit-for-bit.
pub(crate) fn ldexp_f64(m: f64, exp: i32) -> f64 {
    let mut v = m;
    let mut e = exp;
    while e > 0 {
        v *= 2.0;
        e -= 1;
    }
    while e < 0 {
        v *= 0.5;
        e += 1;
    }
    v
}

pub(crate) fn ldexp_f32(m: f32, exp: i32) -> f32 {
    let mut v = m;
    let mut e = exp;
    while e > 0 {
        v *= 2.0;
        e -= 1;
    }
    while e < 0 {
        v *= 0.5;
        e += 1;
    }
    v
}

/// The sign mode (`core::num::imp::flt2dec::Sign`). `Minus` prints `-` only for
/// negatives; `MinusPlus` additionally prints `+` for non-negatives. NaN never carries
/// a sign in either mode.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum FmtSign {
    Minus,
    MinusPlus,
}

fn sign_prefix(is_negative: bool, sign: FmtSign) -> &'static str {
    if is_negative {
        "-"
    } else if matches!(sign, FmtSign::MinusPlus) {
        "+"
    } else {
        ""
    }
}

fn special_f64(v: f64, sign: FmtSign) -> Option<String> {
    if v.is_nan() {
        return Some("NaN".to_string());
    }
    if v.is_infinite() {
        return Some(format!("{}inf", sign_prefix(v.is_sign_negative(), sign)));
    }
    None
}

fn special_f32(v: f32, sign: FmtSign) -> Option<String> {
    if v.is_nan() {
        return Some("NaN".to_string());
    }
    if v.is_infinite() {
        return Some(format!("{}inf", sign_prefix(v.is_sign_negative(), sign)));
    }
    None
}

/// Pad a magnitude string (no sign) to at least `frac` fractional digits.
fn pad_to_min_frac(mut s: String, frac: usize) -> String {
    let have = match s.split_once('.') {
        Some((_, f)) => f.len(),
        None => 0,
    };
    if frac > have {
        if have == 0 {
            s.push('.');
        }
        for _ in 0..(frac - have) {
            s.push('0');
        }
    }
    s
}

/// `to_shortest_str`: Display (shortest, fixed) padded to >= `frac` fractional digits.
pub(crate) fn shortest_f64(v: f64, sign: FmtSign, frac: usize) -> String {
    if let Some(x) = special_f64(v, sign) {
        return x;
    }
    let body = pad_to_min_frac(format!("{}", v.abs()), frac);
    format!("{}{}", sign_prefix(v.is_sign_negative(), sign), body)
}

pub(crate) fn shortest_f32(v: f32, sign: FmtSign, frac: usize) -> String {
    if let Some(x) = special_f32(v, sign) {
        return x;
    }
    let body = pad_to_min_frac(format!("{}", v.abs()), frac);
    format!("{}{}", sign_prefix(v.is_sign_negative(), sign), body)
}

/// `to_exact_fixed_str`: `{:.frac}` (rounding) with the sign mode.
pub(crate) fn exact_fixed_f64(v: f64, sign: FmtSign, frac: usize) -> String {
    if let Some(x) = special_f64(v, sign) {
        return x;
    }
    format!(
        "{}{:.*}",
        sign_prefix(v.is_sign_negative(), sign),
        frac,
        v.abs()
    )
}

pub(crate) fn exact_fixed_f32(v: f32, sign: FmtSign, frac: usize) -> String {
    if let Some(x) = special_f32(v, sign) {
        return x;
    }
    format!(
        "{}{:.*}",
        sign_prefix(v.is_sign_negative(), sign),
        frac,
        v.abs()
    )
}

/// `to_exact_exp_str`: `ndigits` significant digits in exponential (`{:.ndigits-1 e}`),
/// `E` if `upper`, with the sign mode.
pub(crate) fn exact_exp_f64(v: f64, sign: FmtSign, ndigits: usize, upper: bool) -> String {
    if let Some(x) = special_f64(v, sign) {
        return x;
    }
    let body = format!("{:.*e}", ndigits.saturating_sub(1), v.abs());
    let body = if upper { body.replace('e', "E") } else { body };
    format!("{}{}", sign_prefix(v.is_sign_negative(), sign), body)
}

pub(crate) fn exact_exp_f32(v: f32, sign: FmtSign, ndigits: usize, upper: bool) -> String {
    if let Some(x) = special_f32(v, sign) {
        return x;
    }
    let body = format!("{:.*e}", ndigits.saturating_sub(1), v.abs());
    let body = if upper { body.replace('e', "E") } else { body };
    format!("{}{}", sign_prefix(v.is_sign_negative(), sign), body)
}

/// `to_shortest_exp_str`: shortest digits rendered FIXED when the leading-digit decimal
/// exponent `K` is in `[lo, hi)`, else EXPONENTIAL.
pub(crate) fn shortest_exp_f64(v: f64, sign: FmtSign, lo: i32, hi: i32, upper: bool) -> String {
    if let Some(x) = special_f64(v, sign) {
        return x;
    }
    let se = format!("{:e}", v.abs());
    let k: i32 = se
        .split('e')
        .nth(1)
        .and_then(|e| e.parse().ok())
        .unwrap_or(0);
    let body = if lo <= k && k < hi {
        format!("{}", v.abs())
    } else if upper {
        se.replace('e', "E")
    } else {
        se
    };
    format!("{}{}", sign_prefix(v.is_sign_negative(), sign), body)
}

pub(crate) fn shortest_exp_f32(v: f32, sign: FmtSign, lo: i32, hi: i32, upper: bool) -> String {
    if let Some(x) = special_f32(v, sign) {
        return x;
    }
    let se = format!("{:e}", v.abs());
    let k: i32 = se
        .split('e')
        .nth(1)
        .and_then(|e| e.parse().ok())
        .unwrap_or(0);
    let body = if lo <= k && k < hi {
        format!("{}", v.abs())
    } else if upper {
        se.replace('e', "E")
    } else {
        se
    };
    format!("{}{}", sign_prefix(v.is_sign_negative(), sign), body)
}

// ─────────────────────────────────────────────────────────────────────────────────
// FLOAT-FORMATTING-HELPER RECOGNIZER (the former lib.rs flt2dec recognizer, now OWNED
// here). The four `core::num::imp::flt2dec` test-helper surfaces are recognized
// (`flt2dec_helper_mode`), their `(value, sign, mode, digits)` operands reconstructed
// (`parse_flt2dec_value` / `parse_flt2dec_sign` / ...), and each assert dissolved by
// rendering the value through the FormatSugar float engine above and comparing to the
// asserted literal (`dissolve_flt2dec_assert`). `lift_flt2dec_helper` is the single
// entry lib.rs `visit_non_test_fn` calls; FormatSugar owns the entire feature.

#[derive(Clone, Copy, Debug)]
pub(crate) enum Flt2decMode {
    Shortest,
    ExactFixed,
    ExactExp,
    ShortestExp,
}

/// Detect whether `f` is a flt2dec string-formatting test helper, by which core
/// `flt2dec` entry point its body calls. Returns `None` for `to_shortest_exp_str`
/// (bounds-driven fixed-vs-exp, no single `format!` equivalent -- left unclassified)
/// and for non-flt2dec fns.
pub(crate) fn flt2dec_helper_mode(f: &syn::ItemFn) -> Option<Flt2decMode> {
    struct V {
        mode: Option<Flt2decMode>,
    }
    impl<'ast> syn::visit::Visit<'ast> for V {
        fn visit_path(&mut self, p: &'ast syn::Path) {
            if let Some(seg) = p.segments.last() {
                match seg.ident.to_string().as_str() {
                    "to_shortest_str" => self.mode = Some(Flt2decMode::Shortest),
                    "to_exact_fixed_str" => self.mode = Some(Flt2decMode::ExactFixed),
                    "to_exact_exp_str" => self.mode = Some(Flt2decMode::ExactExp),
                    "to_shortest_exp_str" => self.mode = Some(Flt2decMode::ShortestExp),
                    _ => {}
                }
            }
            syn::visit::visit_path(self, p);
        }
    }
    let mut v = V { mode: None };
    syn::visit::Visit::visit_item_fn(&mut v, f);
    v.mode
}

/// A concrete float value parsed from a closed source operand, tagged with its
/// width so we evaluate at the right precision (f32 vs f64 shortest digits differ).
enum Flt2decValue {
    F64(f64),
    F32(f32),
}

/// Parse a flt2dec value operand into a concrete f32/f64. Bare float literals are
/// f64 (the corpus only ever types f32/f16 values explicitly via `fN::CONST` /
/// `ldexp_fN`). `ldexp_f32(m, e)` / `ldexp_f64(m, e)` are computed exactly via
/// stepwise scaling (`ldexp_*`). A bare identifier is resolved
/// through `bindings` (the enclosing helper's `let` map), e.g. `minf32` ->
/// `ldexp_f32(1.0, -149)`. Returns `None` for anything not a closed f32/f64 term
/// (f16/f128 -- including `ldexp_f16` and idents bound to them, unknown consts,
/// unbound idents) -- those stay unclassified (safe under-claim).
fn parse_flt2dec_value(expr: &Expr, bindings: &BTreeMap<String, Expr>) -> Option<Flt2decValue> {
    match expr {
        // bare / suffixed float literal
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Float(lf),
            ..
        }) => {
            let s = lf.suffix();
            if s == "f32" {
                lf.base10_parse::<f32>().ok().map(Flt2decValue::F32)
            } else {
                // "" or "f64"
                lf.base10_parse::<f64>().ok().map(Flt2decValue::F64)
            }
        }
        // negation of a literal: -0.0, -3.14
        Expr::Unary(u) if matches!(u.op, syn::UnOp::Neg(_)) => {
            match parse_flt2dec_value(&u.expr, bindings)? {
                Flt2decValue::F64(v) => Some(Flt2decValue::F64(-v)),
                Flt2decValue::F32(v) => Some(Flt2decValue::F32(-v)),
            }
        }
        // division of two literals: 1.0/0.0 = inf, 0.0/0.0 = NaN, -1.0/0.0 = -inf
        Expr::Binary(b) if matches!(b.op, syn::BinOp::Div(_)) => {
            match (
                parse_flt2dec_value(&b.left, bindings)?,
                parse_flt2dec_value(&b.right, bindings)?,
            ) {
                (Flt2decValue::F64(l), Flt2decValue::F64(r)) => Some(Flt2decValue::F64(l / r)),
                (Flt2decValue::F32(l), Flt2decValue::F32(r)) => Some(Flt2decValue::F32(l / r)),
                _ => None,
            }
        }
        // `ldexp_f32(m, e)` / `ldexp_f64(m, e)` = m * 2^e (computed exactly).
        // `ldexp_f16` (unstable) is intentionally NOT handled -> None.
        Expr::Call(c) => {
            let Expr::Path(fp) = c.func.as_ref() else {
                return None;
            };
            let fname = fp.path.segments.last()?.ident.to_string();
            let (is_f32, is_f64) = (fname == "ldexp_f32", fname == "ldexp_f64");
            if !(is_f32 || is_f64) {
                return None;
            }
            let mut a = c.args.iter();
            let m_expr = a.next()?;
            let e_expr = a.next()?;
            if a.next().is_some() {
                return None;
            }
            // mantissa: a closed f32/f64 value (commonly the literal `1.0`).
            let m = parse_flt2dec_value(m_expr, bindings)?;
            let e = parse_i32_literal(e_expr)?;
            match m {
                Flt2decValue::F64(mv) if is_f64 => Some(Flt2decValue::F64(ldexp_f64(mv, e))),
                // The mantissa literal `1.0` parses as F64; for `ldexp_f32` cast it.
                Flt2decValue::F64(mv) if is_f32 => Some(Flt2decValue::F32(ldexp_f32(mv as f32, e))),
                Flt2decValue::F32(mv) if is_f32 => Some(Flt2decValue::F32(ldexp_f32(mv, e))),
                _ => None,
            }
        }
        // known associated consts: f64::MAX / f32::INFINITY / ...
        Expr::Path(p) => {
            // single-segment ident -> resolve via the enclosing helper's `let` map.
            if p.path.segments.len() == 1 {
                let name = p.path.segments[0].ident.to_string();
                let bound = bindings.get(&name)?;
                // Guard against a binding that refers to itself (shadowing): drop
                // the just-resolved name so resolution strictly shrinks.
                let mut narrowed = bindings.clone();
                narrowed.remove(&name);
                return parse_flt2dec_value(bound, &narrowed);
            }
            let segs: Vec<String> = p
                .path
                .segments
                .iter()
                .map(|s| s.ident.to_string())
                .collect();
            if segs.len() != 2 {
                return None;
            }
            let val = match segs[1].as_str() {
                "MAX" => 1.0,
                "MIN" => -1.0,
                "INFINITY" => f64::INFINITY,
                "NEG_INFINITY" => f64::NEG_INFINITY,
                "NAN" => f64::NAN,
                _ => return None,
            };
            match segs[0].as_str() {
                // MAX/MIN of f32/f64 are huge magnitudes whose shortest form the corpus
                // writes via `format!`; only the INFINITY/NAN consts evaluate cleanly to a
                // small string. Hand MAX/MIN back as the real const so the eval is correct,
                // but only if the RHS is a plain string literal (caller gates that).
                "f64" => match segs[1].as_str() {
                    "MAX" => Some(Flt2decValue::F64(f64::MAX)),
                    "MIN" => Some(Flt2decValue::F64(f64::MIN)),
                    _ => Some(Flt2decValue::F64(val)),
                },
                "f32" => match segs[1].as_str() {
                    "MAX" => Some(Flt2decValue::F32(f32::MAX)),
                    "MIN" => Some(Flt2decValue::F32(f32::MIN)),
                    "INFINITY" => Some(Flt2decValue::F32(f32::INFINITY)),
                    "NEG_INFINITY" => Some(Flt2decValue::F32(f32::NEG_INFINITY)),
                    "NAN" => Some(Flt2decValue::F32(f32::NAN)),
                    _ => None,
                },
                _ => None,
            }
        }
        Expr::Paren(p) => parse_flt2dec_value(&p.expr, bindings),
        Expr::Group(g) => parse_flt2dec_value(&g.expr, bindings),
        _ => None,
    }
}

/// `Minus` / `MinusPlus` path operand -> `FmtSign`.
fn parse_flt2dec_sign(expr: &Expr) -> Option<FmtSign> {
    let Expr::Path(p) = expr else { return None };
    match p.path.segments.last()?.ident.to_string().as_str() {
        "Minus" => Some(FmtSign::Minus),
        "MinusPlus" => Some(FmtSign::MinusPlus),
        _ => None,
    }
}

fn parse_usize_literal(expr: &Expr) -> Option<usize> {
    match expr {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Int(i),
            ..
        }) => i.base10_parse::<usize>().ok(),
        Expr::Paren(p) => parse_usize_literal(&p.expr),
        Expr::Group(g) => parse_usize_literal(&g.expr),
        _ => None,
    }
}

fn parse_bool_literal(expr: &Expr) -> Option<bool> {
    match expr {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Bool(b),
            ..
        }) => Some(b.value),
        Expr::Paren(p) => parse_bool_literal(&p.expr),
        Expr::Group(g) => parse_bool_literal(&g.expr),
        _ => None,
    }
}

/// An `i32` literal, allowing a unary negation (`-4`).
fn parse_i32_literal(expr: &Expr) -> Option<i32> {
    match expr {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Int(i),
            ..
        }) => i.base10_parse::<i32>().ok(),
        Expr::Unary(u) if matches!(u.op, syn::UnOp::Neg(_)) => {
            parse_i32_literal(&u.expr).map(|n| -n)
        }
        Expr::Paren(p) => parse_i32_literal(&p.expr),
        Expr::Group(g) => parse_i32_literal(&g.expr),
        _ => None,
    }
}

/// A `(lo, hi)` dec-bounds tuple of two i32 literals.
fn parse_bounds_tuple(expr: &Expr) -> Option<(i32, i32)> {
    match expr {
        Expr::Tuple(t) if t.elems.len() == 2 => {
            let lo = parse_i32_literal(&t.elems[0])?;
            let hi = parse_i32_literal(&t.elems[1])?;
            Some((lo, hi))
        }
        Expr::Paren(p) => parse_bounds_tuple(&p.expr),
        Expr::Group(g) => parse_bounds_tuple(&g.expr),
        _ => None,
    }
}

/// A plain string-literal RHS -> its value. Anything else (e.g. a `format!(..)`
/// expected) returns `None`, leaving that assert unclassified.
fn parse_string_literal(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Str(s),
            ..
        }) => Some(s.value()),
        Expr::Paren(p) => parse_string_literal(&p.expr),
        Expr::Group(g) => parse_string_literal(&g.expr),
        _ => None,
    }
}

/// Evaluate a CLOSED, CONSTANT `format!` expected-RHS into its string value.
///
/// The coretests corpus expresses the huge-magnitude / tiny-subnormal expected
/// strings as `format!("..{:0>N}..", "")` -- a format string with exactly one
/// zero-fill placeholder `{:0>N}` whose argument is the empty string literal, so
/// it expands to `N` literal `'0'` characters at that position. We reproduce that
/// expansion EXACTLY (verified against `f32::MAX`/`f64::MAX`/`minf32`/`minf64`):
///   * exactly one positional argument, the string literal `""`;
///   * the format string contains exactly one `{...}` placeholder, of the form
///     `{:0>N}` (zero fill, right-align, fixed width `N`, no other spec), and no
///     escaped braces (`{{`/`}}`);
///   * the result is `prefix + "0".repeat(N) + suffix`.
///
/// Anything outside this exact closed shape -> `None` (skip, safe under-claim).
/// Note `""` right-aligned into a `0`-filled width of `N` is `N` zeros for ANY
/// fill char/alignment, but we still require `0>` so we never silently accept a
/// spec whose meaning we have not reasoned through.
fn parse_format_zerofill(expr: &Expr) -> Option<String> {
    let mac = match expr {
        Expr::Macro(m) => &m.mac,
        Expr::Paren(p) => return parse_format_zerofill(&p.expr),
        Expr::Group(g) => return parse_format_zerofill(&g.expr),
        _ => return None,
    };
    if mac.path.segments.last()?.ident != "format" {
        return None;
    }
    let parser = Punctuated::<Expr, Token![,]>::parse_terminated;
    let args = syn::parse::Parser::parse2(parser, mac.tokens.clone()).ok()?;
    let mut it = args.iter();
    // arg 0: the format string literal.
    let fmt = parse_string_literal(it.next()?)?;
    // arg 1: must be exactly the empty string literal `""`.
    let fill = parse_string_literal(it.next()?)?;
    if !fill.is_empty() {
        return None;
    }
    // no further args.
    if it.next().is_some() {
        return None;
    }
    // Reject any escaped braces -- they complicate placeholder counting and never
    // appear in the corpus patterns.
    if fmt.contains("{{") || fmt.contains("}}") {
        return None;
    }
    // Exactly one `{...}` placeholder.
    let open = fmt.find('{')?;
    let close = fmt[open..].find('}').map(|i| open + i)?;
    // no second placeholder
    if fmt[close + 1..].contains('{') {
        return None;
    }
    // spec between braces must be exactly `:0>N` with N a usize.
    let spec = &fmt[open + 1..close];
    let n_str = spec.strip_prefix(":0>")?;
    let n: usize = n_str.parse().ok()?;
    Some(format!(
        "{}{}{}",
        &fmt[..open],
        "0".repeat(n),
        &fmt[close + 1..]
    ))
}

/// The expected-RHS of a flt2dec assert: a plain string literal, or a closed
/// constant `format!("..{:0>N}..", "")` pattern. `None` for anything else.
fn parse_flt2dec_expected(expr: &Expr) -> Option<String> {
    parse_string_literal(expr).or_else(|| parse_format_zerofill(expr))
}

/// Try to dissolve one `assert_eq!(to_string(f, V, S, D[, U]), EXPECTED)` from a
/// flt2dec helper into the constant equality `eq(eval(V,S,D[,U]), EXPECTED)`.
///   * `Some(true)`  -- evaluated, and our stdlib formatting equals the asserted literal
///                      (discharged by dissolution).
///   * `Some(false)` -- evaluated, but disagrees (a real refutation; never expected for a
///                      passing vendor test, refused not discharged).
///   * `None`        -- operands are not a closed f32/f64 literal term, or the expected is
///                      neither a plain string literal nor a closed `format!` pattern:
///                      leave unclassified.
/// `bindings` is the enclosing helper's `let <ident> = <expr>` map, used to resolve
/// value operands like `minf32` to their `ldexp_fN(..)` definition.
fn dissolve_flt2dec_assert(
    mac: &syn::Macro,
    mode: Flt2decMode,
    bindings: &BTreeMap<String, Expr>,
) -> Option<bool> {
    let parser = Punctuated::<Expr, syn::Token![,]>::parse_terminated;
    let args = syn::parse::Parser::parse2(parser, mac.tokens.clone()).ok()?;
    let mut it = args.iter();
    let lhs = it.next()?;
    let rhs = it.next()?;
    // LHS must be `to_string(f, V, S, D[, U])`.
    let Expr::Call(call) = lhs else { return None };
    let Expr::Path(cp) = call.func.as_ref() else {
        return None;
    };
    if cp.path.segments.last()?.ident != "to_string" {
        return None;
    }
    let call_args: Vec<&Expr> = call.args.iter().collect();
    // args[0] is the formatter closure `f` (ignored -- we evaluate with our own stdlib).
    let value = parse_flt2dec_value(call_args.get(1)?, bindings)?;
    let sign = parse_flt2dec_sign(call_args.get(2)?)?;
    let expected = parse_flt2dec_expected(rhs)?;

    let computed = match mode {
        Flt2decMode::Shortest => {
            let frac = parse_usize_literal(call_args.get(3)?)?;
            match value {
                Flt2decValue::F64(v) => shortest_f64(v, sign, frac),
                Flt2decValue::F32(v) => shortest_f32(v, sign, frac),
            }
        }
        Flt2decMode::ExactFixed => {
            let frac = parse_usize_literal(call_args.get(3)?)?;
            match value {
                Flt2decValue::F64(v) => exact_fixed_f64(v, sign, frac),
                Flt2decValue::F32(v) => exact_fixed_f32(v, sign, frac),
            }
        }
        Flt2decMode::ExactExp => {
            let frac = parse_usize_literal(call_args.get(3)?)?;
            let upper = parse_bool_literal(call_args.get(4)?)?;
            match value {
                Flt2decValue::F64(v) => exact_exp_f64(v, sign, frac, upper),
                Flt2decValue::F32(v) => exact_exp_f32(v, sign, frac, upper),
            }
        }
        Flt2decMode::ShortestExp => {
            let (lo, hi) = parse_bounds_tuple(call_args.get(3)?)?;
            let upper = parse_bool_literal(call_args.get(4)?)?;
            match value {
                Flt2decValue::F64(v) => shortest_exp_f64(v, sign, lo, hi, upper),
                Flt2decValue::F32(v) => shortest_exp_f32(v, sign, lo, hi, upper),
            }
        }
    };
    Some(computed == expected)
}

/// Dissolve a flt2dec formatting test helper: evaluate each closed
/// `assert_eq!(to_string(..), "..")` with our own stdlib `format!` and discharge it,
/// leaving non-closed / f16 / `format!`-expected asserts unclassified. Every textual
/// assert macro is accounted (discharged or refused), so nothing is silently dropped.
pub(crate) fn lift_flt2dec_helper(
    f: &syn::ItemFn,
    mode: Flt2decMode,
    source_path: &str,
    modules: &[String],
    out: &mut crate::AdapterOutput,
) {
    let scoped = crate::scoped_test_name(source_path, modules, &f.sig.ident.to_string());
    let total = crate::count_asserts_in_stmts(&f.block.stmts);

    // Collect every assert_eq!/assert! macro in the helper body (incl. nested blocks),
    // in textual order, so the per-macro disposition reconciles against `total`.
    struct MacroWalk {
        macros: Vec<syn::Macro>,
    }
    impl<'ast> syn::visit::Visit<'ast> for MacroWalk {
        fn visit_macro(&mut self, m: &'ast syn::Macro) {
            if crate::is_assert_macro_path(&m.path) {
                self.macros.push(m.clone());
            }
            syn::visit::visit_macro(self, m);
        }
    }
    let mut w = MacroWalk { macros: Vec::new() };
    syn::visit::Visit::visit_item_fn(&mut w, f);

    // Collect simple `let <ident> = <expr>;` bindings from the helper body so a
    // value operand written as an identifier (e.g. `minf32`) resolves to its
    // definition (`ldexp_f32(1.0, -149)`). Only un-typed, non-`mut`, single-ident
    // patterns with an initializer are captured; anything else is ignored (the
    // operand then stays unresolved -> None -> refused, which is safe). The corpus
    // defines these once at top of the helper, so last-write-wins on the BTreeMap
    // is correct.
    let mut bindings: BTreeMap<String, Expr> = BTreeMap::new();
    for stmt in &f.block.stmts {
        if let Stmt::Local(local) = stmt {
            if let Pat::Ident(pi) = &local.pat {
                if pi.by_ref.is_none() && pi.subpat.is_none() {
                    if let Some(init) = &local.init {
                        if init.diverge.is_none() {
                            bindings.insert(pi.ident.to_string(), (*init.expr).clone());
                        }
                    }
                }
            }
        }
    }

    let mut lifted = 0usize;
    let mut refused = 0usize;
    for m in &w.macros {
        match dissolve_flt2dec_assert(m, mode, &bindings) {
            Some(true) => lifted += 1,
            Some(false) => {
                // Our independent stdlib evaluation disagrees with the asserted literal.
                // For a passing vendor test this cannot happen; refuse rather than ever
                // false-discharge.
                refused += 1;
                out.skip_reasons.push(
                    "flt2dec dissolution: independent stdlib evaluation disagrees with the \
                     asserted value; refused"
                        .to_string(),
                );
            }
            None => {
                refused += 1;
                let toks = m.tokens.to_string();
                if toks.contains("f16") || toks.contains("f128") {
                    // TERMINAL: f16/f128 formatting. These are UNSTABLE float types; the
                    // stable toolchain the lifter ships cannot format them (no stable
                    // Display/flt2dec for f16/f128), so the value cannot be dissolved by
                    // evaluation, and we do NOT model the flt2dec algorithm (no-model
                    // axiom). The assert tests an unstable API not expressible as a
                    // point-wise claim over the stable surface -- a source/environment
                    // property, not a lifter gap. (Refused, stated plainly; not a fake-zero.)
                    out.skip_reasons.push(
                        "flt2dec assert: f16/f128 formatting is unstable -- unformattable on \
                         the stable toolchain the lifter ships and not modellable as a \
                         point-wise claim; refused"
                            .to_string(),
                    );
                } else {
                    out.skip_reasons.push(
                        "flt2dec assert: operand is not a closed f32/f64 literal term (ldexp \
                         or a format! expected); released to layer 0"
                            .to_string(),
                    );
                }
            }
        }
    }
    out.assertions_lifted += lifted;
    out.assertions_refused += refused;

    // Totality net: account any assert the macro walk did not reach.
    let accounted = lifted + refused;
    if total > accounted {
        let gap = total - accounted;
        for _ in 0..gap {
            out.assertions_refused += 1;
            out.skip_reasons
                .push("flt2dec helper: unenumerated assert; released to layer 0".to_string());
        }
    }
    out.warnings.push(crate::LiftWarning {
        source_path: source_path.to_string(),
        item_name: scoped,
        reason: format!(
            "flt2dec formatting helper dissolved by stdlib evaluation: {lifted} discharged, \
             {refused} unclassified (mode {mode:?})"
        ),
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(src: &str) -> Expr {
        syn::parse_str(src).expect("expr parses")
    }
    fn no_binds() -> BTreeMap<String, Expr> {
        BTreeMap::new()
    }
    fn resolve(src: &str) -> Result<Option<String>, String> {
        try_resolve_format(&parse(src), &no_binds())
    }

    // ── Display / Debug over each scalar kind ──
    #[test]
    fn display_int() {
        assert_eq!(
            resolve(r#"format!("{}", 0)"#).unwrap().as_deref(),
            Some("0")
        );
        assert_eq!(
            resolve(r#"format!("{}", 1i8)"#).unwrap().as_deref(),
            Some("1")
        );
        assert_eq!(
            resolve(r#"format!("{}", 42u64)"#).unwrap().as_deref(),
            Some("42")
        );
        assert_eq!(
            resolve(r#"format!("{}", -7)"#).unwrap().as_deref(),
            Some("-7")
        );
    }
    #[test]
    fn debug_int() {
        assert_eq!(
            resolve(r#"format!("{:?}", 0u32)"#).unwrap().as_deref(),
            Some("0")
        );
    }
    #[test]
    fn radix_int() {
        assert_eq!(
            resolve(r#"format!("{:x}", 255u32)"#).unwrap().as_deref(),
            Some("ff")
        );
        assert_eq!(
            resolve(r#"format!("{:X}", 255u32)"#).unwrap().as_deref(),
            Some("FF")
        );
        assert_eq!(
            resolve(r#"format!("{:b}", 5u32)"#).unwrap().as_deref(),
            Some("101")
        );
        assert_eq!(
            resolve(r#"format!("{:o}", 8u32)"#).unwrap().as_deref(),
            Some("10")
        );
        // two's-complement at width: `-1i8` lower-hex is "ff".
        assert_eq!(
            resolve(r#"format!("{:x}", -1i8)"#).unwrap().as_deref(),
            Some("ff")
        );
    }
    #[test]
    fn exp_int() {
        assert_eq!(
            resolve(r#"format!("{:e}", 0)"#).unwrap().as_deref(),
            Some("0e0")
        );
        assert_eq!(
            resolve(r#"format!("{:E}", 0u32)"#).unwrap().as_deref(),
            Some("0E0")
        );
    }
    #[test]
    fn zero_pad_int() {
        assert_eq!(
            resolve(r#"format!("{:05}", 7)"#).unwrap().as_deref(),
            Some("00007")
        );
        assert_eq!(
            resolve(r#"format!("{:05}", -7)"#).unwrap().as_deref(),
            Some("-0007")
        );
    }
    #[test]
    fn display_float_and_precision() {
        assert_eq!(
            resolve(r#"format!("{}", 3.14)"#).unwrap().as_deref(),
            Some("3.14")
        );
        assert_eq!(
            resolve(r#"format!("{:.2}", 3.14159)"#).unwrap().as_deref(),
            Some("3.14")
        );
        assert_eq!(
            resolve(r#"format!("{:.0}", 3.14)"#).unwrap().as_deref(),
            Some("3")
        );
    }
    #[test]
    fn display_char_str_bool() {
        assert_eq!(
            resolve(r#"format!("{}", 'a')"#).unwrap().as_deref(),
            Some("a")
        );
        assert_eq!(
            resolve(r#"format!("{}", "hi")"#).unwrap().as_deref(),
            Some("hi")
        );
        assert_eq!(
            resolve(r#"format!("{:?}", "hi")"#).unwrap().as_deref(),
            Some("\"hi\"")
        );
        assert_eq!(
            resolve(r#"format!("{}", true)"#).unwrap().as_deref(),
            Some("true")
        );
    }
    #[test]
    fn literal_segments_and_multiple_args() {
        assert_eq!(
            resolve(r#"format!("a={}, b={:x}", 1, 255u32)"#)
                .unwrap()
                .as_deref(),
            Some("a=1, b=ff")
        );
        assert_eq!(
            resolve(r#"format!("{{}}")"#).unwrap().as_deref(),
            Some("{}")
        );
    }
    #[test]
    fn to_string_and_concat() {
        assert_eq!(
            resolve(r#"3.14.to_string()"#).unwrap().as_deref(),
            Some("3.14")
        );
        assert_eq!(
            resolve(r#"42u8.to_string()"#).unwrap().as_deref(),
            Some("42")
        );
        assert_eq!(
            resolve(r#"concat!("a", "b", "c")"#).unwrap().as_deref(),
            Some("abc")
        );
        assert_eq!(
            resolve(r#"concat!("x", 1, true)"#).unwrap().as_deref(),
            Some("x1true")
        );
    }
    #[test]
    fn nested_compositional() {
        // a format! whose arg is itself a format!.
        assert_eq!(
            resolve(r#"format!("[{}]", format!("{:x}", 255u32))"#)
                .unwrap()
                .as_deref(),
            Some("[ff]")
        );
    }
    #[test]
    fn named_capture_via_binding() {
        let mut binds = BTreeMap::new();
        binds.insert("max".to_string(), parse("9u8"));
        assert_eq!(
            try_resolve_format(&parse(r#"format!("{max}")"#), &binds)
                .unwrap()
                .as_deref(),
            Some("9")
        );
    }
    #[test]
    fn explicit_named_arg() {
        assert_eq!(
            resolve(r#"format!("{x}", x = 5)"#).unwrap().as_deref(),
            Some("5")
        );
    }

    // ── BAIL: runtime arg / unsupported spec ──
    #[test]
    fn bails_on_runtime_arg() {
        assert_eq!(resolve(r#"format!("{}", runtime_var)"#).unwrap(), None);
        assert_eq!(resolve(r#"format!("{}", foo.bar())"#).unwrap(), None);
    }
    #[test]
    fn bails_on_runtime_fmt_string() {
        assert_eq!(resolve(r#"format!(dynamic_fmt, 1)"#).unwrap(), None);
    }
    #[test]
    fn bails_on_unsupported_spec_pointer() {
        assert_eq!(resolve(r#"format!("{:p}", &x)"#).unwrap(), None);
    }
    #[test]
    fn bails_on_alignment_width() {
        // a bare width / fill+align is an alignment we do NOT reproduce -> bail.
        assert_eq!(resolve(r#"format!("{:>9}", 1)"#).unwrap(), None);
        assert_eq!(resolve(r#"format!("{:9}", 1)"#).unwrap(), None);
        assert_eq!(resolve(r#"format!("{:^9?}", 1)"#).unwrap(), None);
    }
    #[test]
    fn bails_on_alternate() {
        assert_eq!(resolve(r#"format!("{:#?}", 1)"#).unwrap(), None);
        assert_eq!(resolve(r#"format!("{:#x}", 255u32)"#).unwrap(), None);
    }

    // ── TERMINAL: f16/f128 ──
    #[test]
    fn terminal_f16_f128() {
        let r = resolve(r#"format!("{}", 1.0f16)"#);
        assert!(r.is_err(), "f16 must be a named terminal");
        assert!(r.unwrap_err().contains("f16/f128"));
        let r = resolve(r#"3.0f128.to_string()"#);
        assert!(r.is_err());
    }

    // ── DECOMPOSE: recognizes the shapes, declines foreign ──
    #[test]
    fn decompose_recognizes_shapes() {
        assert!(decompose_format(&parse(r#"format!("{}", 1)"#), &no_binds()).is_some());
        assert!(decompose_format(&parse(r#"concat!("a")"#), &no_binds()).is_some());
        assert!(decompose_format(&parse(r#"x.to_string()"#), &no_binds()).is_some());
        assert!(decompose_format(&parse(r#"a + b"#), &no_binds()).is_some());
        // foreign: not a format shape.
        assert!(decompose_format(&parse(r#"foo.bar()"#), &no_binds()).is_none());
        assert!(decompose_format(&parse(r#"vec![1, 2]"#), &no_binds()).is_none());
    }

    // ── flt2dec dissolution: ldexp values + format! expected-RHS ──────────────

    // Parse a single `assert_eq!(..)` expression statement into its `syn::Macro`.
    fn assert_macro(src: &str) -> syn::Macro {
        let stmt: Stmt = syn::parse_str(src).expect("assert stmt must parse");
        let expr = match stmt {
            Stmt::Macro(m) => return m.mac,
            Stmt::Expr(e, _) => e,
            _ => panic!("expected a macro/expr stmt"),
        };
        match expr {
            Expr::Macro(m) => m.mac,
            _ => panic!("expected a macro expr"),
        }
    }

    fn bind(name: &str, expr_src: &str) -> BTreeMap<String, Expr> {
        let mut b = BTreeMap::new();
        b.insert(
            name.to_string(),
            syn::parse_str::<Expr>(expr_src).expect("binding expr must parse"),
        );
        b
    }

    #[test]
    fn ldexp_binding_dissolves_to_right_string() {
        // minf32 = ldexp_f32(1.0, -149) is the smallest f32 subnormal; its shortest
        // Display is "0." + 44 zeros + "1". Resolved through the let-binding map and
        // evaluated by our own stdlib, the assert dissolves (Some(true)).
        let b = bind("minf32", "ldexp_f32(1.0, -149)");
        let want = format!(r#""0.{}1""#, "0".repeat(44));
        let m = assert_macro(&format!(
            "assert_eq!(to_string(f, minf32, Minus, 0), {want});"
        ));
        assert_eq!(
            dissolve_flt2dec_assert(&m, Flt2decMode::Shortest, &b),
            Some(true),
            "ldexp-bound subnormal must dissolve to its exact shortest string"
        );
        // minf64 = ldexp_f64(1.0, -1074): "0." + 323 zeros + "5".
        let b64 = bind("minf64", "ldexp_f64(1.0, -1074)");
        let want64 = format!(r#""0.{}5""#, "0".repeat(323));
        let m64 = assert_macro(&format!(
            "assert_eq!(to_string(f, minf64, Minus, 0), {want64});"
        ));
        assert_eq!(
            dissolve_flt2dec_assert(&m64, Flt2decMode::Shortest, &b64),
            Some(true)
        );
    }

    #[test]
    fn ldexp_wrong_expected_does_not_discharge() {
        // break-the-twin: an expected string that does NOT match our independent
        // value must be refused (Some(false)), never force-discharged.
        let b = bind("minf32", "ldexp_f32(1.0, -149)");
        let m = assert_macro(r#"assert_eq!(to_string(f, minf32, Minus, 0), "0.5");"#);
        assert_eq!(
            dissolve_flt2dec_assert(&m, Flt2decMode::Shortest, &b),
            Some(false),
            "a wrong expected literal must refuse, not discharge"
        );
    }

    #[test]
    fn format_zerofill_expected_evaluates() {
        // f32::MAX shortest is `format!("34028235{:0>31}", "")` = 34028235 + 31 zeros.
        let b = BTreeMap::new();
        let m = assert_macro(
            r#"assert_eq!(to_string(f, f32::MAX, Minus, 0), format!("34028235{:0>31}", ""));"#,
        );
        assert_eq!(
            dissolve_flt2dec_assert(&m, Flt2decMode::Shortest, &b),
            Some(true),
            "closed format! zero-fill expected must evaluate and dissolve"
        );
        // And the same pattern with a wrong leading prefix must refuse.
        let bad = assert_macro(
            r#"assert_eq!(to_string(f, f32::MAX, Minus, 0), format!("99999999{:0>31}", ""));"#,
        );
        assert_eq!(
            dissolve_flt2dec_assert(&bad, Flt2decMode::Shortest, &b),
            Some(false)
        );
    }

    #[test]
    fn format_zerofill_direct_eval() {
        // Direct unit on the evaluator: prefix/suffix around one {:0>N}.
        assert_eq!(
            parse_format_zerofill(
                &syn::parse_str::<Expr>(r#"format!("0.{:0>323}5", "")"#).unwrap()
            ),
            Some(format!("0.{}5", "0".repeat(323)))
        );
        // Non-empty fill arg -> not our closed pattern -> None.
        assert_eq!(
            parse_format_zerofill(&syn::parse_str::<Expr>(r#"format!("{:0>4}", "x")"#).unwrap()),
            None
        );
        // Two placeholders -> None (we only evaluate the single-placeholder shape).
        assert_eq!(
            parse_format_zerofill(
                &syn::parse_str::<Expr>(r#"format!("{:0>4}{:0>4}", "")"#).unwrap()
            ),
            None
        );
        // A non-format! macro -> None.
        assert_eq!(
            parse_format_zerofill(&syn::parse_str::<Expr>(r#"vec!["a"]"#).unwrap()),
            None
        );
    }

    #[test]
    fn unparseable_value_or_expected_is_skipped() {
        let b = BTreeMap::new();
        // f16 value (ldexp_f16) -> unresolved -> None (skip, NOT discharge).
        let bf16 = bind("minf16", "ldexp_f16(1.0, -24)");
        let m16 = assert_macro(r#"assert_eq!(to_string(f, minf16, Minus, 0), "0.00000006");"#);
        assert_eq!(
            dissolve_flt2dec_assert(&m16, Flt2decMode::Shortest, &bf16),
            None,
            "f16-bound value must stay unclassified (stable cannot format f16)"
        );
        // Unbound ident -> None.
        let mub = assert_macro(r#"assert_eq!(to_string(f, mystery, Minus, 0), "0");"#);
        assert_eq!(
            dissolve_flt2dec_assert(&mub, Flt2decMode::Shortest, &b),
            None
        );
        // A non-closed format! expected (runtime arg) -> None.
        let mfmt =
            assert_macro(r#"assert_eq!(to_string(f, 1.0, Minus, 0), format!("{}", some_var));"#);
        assert_eq!(
            dissolve_flt2dec_assert(&mfmt, Flt2decMode::Shortest, &b),
            None
        );
    }

    #[test]
    fn exact_fixed_full_expansion_mismatch_is_refused_not_discharged() {
        // SOUNDNESS GUARD: `to_exact_fixed_str(f64::MAX, 8)`'s corpus expected is the
        // SHORTEST decimal zero-padded (`format!("17976931348623157{:0>292}.00000000")`),
        // but our `{:.8}` reproduces the FULL exact expansion (`...570814527...`). These
        // differ, so this row must REFUSE (Some(false)) -- never force-discharge a value
        // we did not reproduce. This is the dog that didn't bark: the format! RHS now
        // PARSES, so the row is no longer skipped (None); it is actively refuted.
        let b = BTreeMap::new();
        let m = assert_macro(
            r#"assert_eq!(to_string(f, f64::MAX, Minus, 8), format!("17976931348623157{:0>292}.00000000", ""));"#,
        );
        assert_eq!(
            dissolve_flt2dec_assert(&m, Flt2decMode::ExactFixed, &b),
            Some(false),
            "a full-expansion fixed value that differs from the shortest-padded expected \
             must refuse, never discharge"
        );
        // The SHORTEST-mode row for the same value DOES match (shortest == padded shortest).
        let ms = assert_macro(
            r#"assert_eq!(to_string(f, f64::MAX, Minus, 0), format!("17976931348623157{:0>292}", ""));"#,
        );
        assert_eq!(
            dissolve_flt2dec_assert(&ms, Flt2decMode::Shortest, &b),
            Some(true)
        );
    }

    #[test]
    fn ldexp_minf32_drains_end_to_end() {
        // End-to-end through the helper: a `to_shortest_str` test fn that defines
        // minf32 via ldexp and asserts both a string-literal and a format!-pattern
        // expected. Both must lift (assertions_lifted == 2, none refused).
        let src = r#"
            #[test]
            fn to_string() {
                fn to_string<T>(_: T, _: f32, _: Sign, _: usize) -> String { String::new() }
                let minf32 = ldexp_f32(1.0, -149);
                assert_eq!(to_string(f, minf32, Minus, 0), format!("0.{:0>44}1", ""));
                assert_eq!(to_string(f, 1.0e-6_f32, Minus, 0), "0.000001");
            }
        "#;
        // Build via the flt2dec path directly so the test is independent of the
        // outer dispatcher's helper recognition heuristics.
        let file: syn::File = syn::parse_str(src).unwrap();
        let mut out = crate::AdapterOutput::default();
        // Find the inner test fn and lift it in Shortest mode.
        fn find_fn(items: &[syn::Item]) -> Option<&syn::ItemFn> {
            for it in items {
                if let syn::Item::Fn(f) = it {
                    return Some(f);
                }
            }
            None
        }
        let f = find_fn(&file.items).expect("test fn");
        lift_flt2dec_helper(f, Flt2decMode::Shortest, "tests/x.rs", &[], &mut out);
        assert_eq!(
            out.assertions_lifted, 2,
            "both the format!-pattern and the literal expected must dissolve"
        );
        assert_eq!(
            out.assertions_refused, 0,
            "nothing refused: {:?}",
            out.skip_reasons
        );
    }

    // ── Float-formatting engine (moved verbatim from the former flt2dec_eval.rs).
    // Every tuple below is a VERBATIM (input, expected) pair lifted from the coretests
    // flt2dec corpus -- the break-the-twin ground truth. If a mapping drifts, one fails.
    use FmtSign::*;

    #[test]
    fn shortest_matches_corpus() {
        let inf = 1.0_f64 / 0.0;
        let ninf = -1.0_f64 / 0.0;
        let nan = 0.0_f64 / 0.0;
        let cases: &[(f64, FmtSign, usize, &str)] = &[
            (0.0, Minus, 0, "0"),
            (0.0, MinusPlus, 0, "+0"),
            (-0.0, Minus, 0, "-0"),
            (-0.0, MinusPlus, 0, "-0"),
            (0.0, Minus, 1, "0.0"),
            (0.0, MinusPlus, 1, "+0.0"),
            (-0.0, Minus, 8, "-0.00000000"),
            (inf, Minus, 0, "inf"),
            (inf, MinusPlus, 0, "+inf"),
            (nan, Minus, 0, "NaN"),
            (nan, MinusPlus, 64, "NaN"),
            (ninf, Minus, 0, "-inf"),
            (3.14, Minus, 0, "3.14"),
            (3.14, MinusPlus, 0, "+3.14"),
            (-3.14, Minus, 0, "-3.14"),
            (3.14, Minus, 1, "3.14"),
            (3.14, Minus, 2, "3.14"),
            (3.14, MinusPlus, 4, "+3.1400"),
            (-3.14, Minus, 8, "-3.14000000"),
            (7.5e-11, Minus, 0, "0.000000000075"),
            (7.5e-11, Minus, 13, "0.0000000000750"),
            (1.9971e20, Minus, 0, "199710000000000000000"),
            (1.9971e20, Minus, 1, "199710000000000000000.0"),
        ];
        for (v, s, frac, want) in cases {
            assert_eq!(
                &shortest_f64(*v, *s, *frac),
                want,
                "shortest({v},{s:?},{frac})"
            );
        }
    }

    #[test]
    fn exact_fixed_matches_corpus() {
        let inf = 1.0_f64 / 0.0;
        let nan = 0.0_f64 / 0.0;
        let cases: &[(f64, FmtSign, usize, &str)] = &[
            (0.0, Minus, 0, "0"),
            (0.0, MinusPlus, 0, "+0"),
            (-0.0, Minus, 0, "-0"),
            (0.0, Minus, 1, "0.0"),
            (-0.0, Minus, 8, "-0.00000000"),
            (inf, Minus, 0, "inf"),
            (inf, MinusPlus, 64, "+inf"),
            (nan, Minus, 0, "NaN"),
            (3.14, Minus, 0, "3"),
            (3.14, MinusPlus, 0, "+3"),
            (-3.14, Minus, 0, "-3"),
            (3.14, Minus, 1, "3.1"),
            (3.14, Minus, 2, "3.14"),
        ];
        for (v, s, frac, want) in cases {
            assert_eq!(
                &exact_fixed_f64(*v, *s, *frac),
                want,
                "exact_fixed({v},{s:?},{frac})"
            );
        }
    }

    #[test]
    fn exact_exp_matches_corpus() {
        let inf = 1.0_f64 / 0.0;
        let cases: &[(f64, FmtSign, usize, bool, &str)] = &[
            (0.0, Minus, 1, true, "0E0"),
            (0.0, Minus, 1, false, "0e0"),
            (0.0, MinusPlus, 1, false, "+0e0"),
            (-0.0, Minus, 1, true, "-0E0"),
            (0.0, Minus, 2, true, "0.0E0"),
            (-0.0, Minus, 8, false, "-0.0000000e0"),
            (inf, Minus, 1, false, "inf"),
            (3.14, Minus, 1, true, "3E0"),
            (3.14, Minus, 1, false, "3e0"),
            (3.14, MinusPlus, 1, false, "+3e0"),
            (3.14, Minus, 3, true, "3.14E0"),
            (3.14, Minus, 3, false, "3.14e0"),
            (0.195, Minus, 1, false, "2e-1"),
            (0.195, Minus, 1, true, "2E-1"),
            (0.195, MinusPlus, 1, true, "+2E-1"),
            (0.195, Minus, 3, false, "1.95e-1"),
            (0.195, Minus, 3, true, "1.95E-1"),
        ];
        for (v, s, n, u, want) in cases {
            assert_eq!(
                &exact_exp_f64(*v, *s, *n, *u),
                want,
                "exact_exp({v},{s:?},{n},{u})"
            );
        }
    }

    #[test]
    fn shortest_exp_matches_corpus() {
        let cases: &[(f64, FmtSign, i32, i32, bool, &str)] = &[
            (0.0, Minus, -4, 16, false, "0"),
            (0.0, MinusPlus, -4, 16, false, "+0"),
            (0.0, Minus, 0, 0, true, "0E0"),
            (0.0, Minus, 0, 0, false, "0e0"),
            (0.0, MinusPlus, 5, 9, false, "+0e0"),
            (3.14, Minus, -4, 16, false, "3.14"),
            (3.14, MinusPlus, -4, 16, false, "+3.14"),
            (3.14, Minus, 0, 0, true, "3.14E0"),
            (3.14, Minus, 0, 0, false, "3.14e0"),
            (3.14, MinusPlus, 5, 9, false, "+3.14e0"),
            (0.1, Minus, -4, 16, false, "0.1"),
            (0.1, Minus, 0, 0, true, "1E-1"),
            (0.1, Minus, 0, 0, false, "1e-1"),
            (1.0e23, Minus, 22, 23, false, "1e23"),
            (1.0e23, Minus, 23, 24, false, "100000000000000000000000"),
            (1.0e23, Minus, 24, 25, false, "1e23"),
        ];
        for (v, s, lo, hi, u, want) in cases {
            assert_eq!(
                &shortest_exp_f64(*v, *s, *lo, *hi, *u),
                want,
                "shortest_exp({v},{s:?},({lo},{hi}),{u})"
            );
        }
    }

    #[test]
    fn distinct_values_do_not_collapse() {
        assert_ne!(shortest_f64(3.14, Minus, 0), shortest_f64(3.15, Minus, 0));
        assert_ne!(
            exact_exp_f64(0.195, Minus, 1, false),
            exact_exp_f64(0.295, Minus, 1, false)
        );
    }

    #[test]
    fn ldexp_reproduces_exact_subnormals() {
        assert_eq!(ldexp_f32(1.0, -149).to_bits(), 1, "smallest f32 subnormal");
        assert_eq!(ldexp_f64(1.0, -1074).to_bits(), 1, "smallest f64 subnormal");
        assert_eq!(ldexp_f32(1.0, 25), 33554432.0_f32);
        assert_eq!(ldexp_f64(1.0, 64), 18446744073709552000.0_f64);
        assert_eq!(ldexp_f64(1.0, 0), 1.0);
    }

    #[test]
    fn ldexp_subnormal_format_matches_corpus() {
        let minf32 = ldexp_f32(1.0, -149);
        let want32 = format!("0.{}1", "0".repeat(44));
        assert_eq!(shortest_f32(minf32, Minus, 0), want32);
        assert_eq!(exact_exp_f32(minf32, Minus, 1, false), "1e-45");
        assert_eq!(exact_exp_f32(minf32, Minus, 2, false), "1.4e-45");
        let minf64 = ldexp_f64(1.0, -1074);
        let want64 = format!("0.{}5", "0".repeat(323));
        assert_eq!(shortest_f64(minf64, Minus, 0), want64);
        assert_ne!(shortest_f32(ldexp_f32(1.0, -148), Minus, 0), want32);
    }
}

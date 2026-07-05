// SPDX-License-Identifier: MIT OR Apache-2.0
//
// The general string-formatting reducer. A `format!`/`.to_string()`/
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
// `format!("{}", x)` completes when `x` resolves through its child floor (inline
// literal, a `let`/`const`-bound literal, a nested `format!`/`concat!`/`.to_string()`).
// Runtime/opaque-ness belongs to the child that owns it. If this sugar cannot construct
// that typed child floor, it is a factory gap and panics instead of inventing an effect.
// The format-string operand MUST be a literal/template floor.
//
// REFUSE BY NAME, NEVER GUESS. A format spec we do not FAITHFULLY reproduce (an
// unhandled fill/align/width/sign/precision combination) does not complete; it takes the
// factory gap path. Pointer formatting (`{:p}`) is parsed but refused by a named
// `FormatArgument` effect because the rendered value is runtime address identity. We
// only complete a spec we render through a STATICALLY-WRITTEN real `format!` call (we
// cannot pass a runtime spec string to `format!`, whose first arg must be a compile-time
// literal; so each supported spec is one written arm calling the real macro). `f16`/`f128`
// are unstable and unformattable on the stable toolchain the lifter ships; until a typed
// owner exists, reaching that path is a factory gap, not a runtime-argument effect.

use std::collections::BTreeMap;
use std::ffi::CStr;
use std::rc::Rc;

use syn::punctuated::Punctuated;
use syn::{Expr, ExprLit, Lit, Pat, Stmt, Token};

use crate::sugar::cstr::{CStrBytes, LiteralCStrVisitor};
use crate::sugar::factory::{
    FloorRead, FormatTemplateFloor, FormatValueFloor, LiteralCStrFloor, LiteralStringFloor,
    SugarBody, SugarBuildCtx, TermFloor,
};
use crate::sugar::int_literal::{
    numeric_floor_from_term, ExactInt, IntKind as NumericIntKind, NumericFloor,
};
use crate::sugar::monadic::OPT_SOME;
use crate::sugar::source_fragment::SourceFragment;
use crate::{canonical_term_sig, token_key};
use crate::{strip_refs_groups, Desugared, Effect, Outcome, Sugar, SugarCtx};
use sugar_ir_symbolic::{ConstValue, Term};

/// The terminal reason for an `f16`/`f128` formatting operand: the stable toolchain
/// the lifter ships cannot Display it, and we never model the algorithm (no-model
/// axiom). Carries its own k-remedy. Mirrors the existing flt2dec f16/f128 terminal.
pub(crate) const F16_F128_DISPLAY_UNSUPPORTED: &str =
    "format: f16/f128 Display is unsupported by stdlib on the stable toolchain the \
     lifter ships; build on nightly to enable; refused";

pub(crate) fn build_literal_string_term_node(expr: &Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    Box::new(LiteralStringTermSugar {
        body: SugarBody::literal_string(expr, fcx),
    })
}

/// Frag-based wrapper for `is_factory_string_add_shape`. Raw syn is inside
/// `as_expr()` + `is_factory_string_add_shape`; recognize bodies stay clean.
pub(crate) fn is_factory_string_add_shape_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> bool {
    match frag.as_expr() {
        Some(expr) => is_factory_string_add_shape(expr, fcx),
        None => false,
    }
}

/// Frag-based wrapper for `build_literal_string_term_node`. Raw syn is inside
/// `as_expr()`; recognize bodies stay clean.
pub(crate) fn build_literal_string_term_node_frag(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Box<dyn Sugar> {
    build_literal_string_term_node(
        frag.as_expr()
            .expect("build_literal_string_term_node_frag: non-expr fragment"),
        fcx,
    )
}

pub(crate) fn build_format_template_body(expr: &Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    let body = match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Str(s), ..
        }) => FormatTemplateBody::Literal(s.value()),
        Expr::Macro(m) if macro_is(m, "concat") => {
            match build_concat_string_body(expr, fcx) {
                Ok(body) => FormatTemplateBody::LiteralString(SugarBody::from_node(Box::new(body))),
                Err(reason) => FormatTemplateBody::Unconstructible(reason),
            }
        }
        _ => FormatTemplateBody::Unconstructible(
            "format template constructor reached a non-template source site; write more Sugar for this AST"
                .to_string(),
        ),
    };
    Box::new(body)
}

pub(crate) fn build_literal_string_body(expr: &Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    let body = match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Str(s), ..
        }) => LiteralStringBody::Literal(s.value()),
        Expr::Path(path) if path.qself.is_none() => match path.path.get_ident() {
            Some(ident) => {
                let name = ident.to_string();
                match stable_binding_init(&name, fcx) {
                    Some(init) if !fcx.resolving_bound_path(&name) => {
                        let child_fcx = fcx.with_bound_path(&name);
                        LiteralStringBody::Child(SugarBody::literal_string(init, &child_fcx))
                    }
                    Some(_) => LiteralStringBody::Unconstructible(
                        "self-referential literal string binding; write more Sugar for this AST"
                            .to_string(),
                    ),
                    None => LiteralStringBody::Unconstructible(
                        format!(
                            "format string path `{name}` has no literal-string child floor; write more Sugar for this AST"
                        ),
                    ),
                }
            }
            None => LiteralStringBody::Unconstructible(
                "format string path has no ident; write more Sugar for this AST".to_string(),
            ),
        },
        Expr::Macro(m) if macro_is(m, "format") => LiteralStringBody::Child(SugarBody::from_node(
            crate::sugar::format_macro::build_literal_string_node(expr, fcx),
        )),
        Expr::Macro(m) if macro_is(m, "concat") => match build_concat_string_body(expr, fcx) {
            Ok(body) => body,
            Err(reason) => LiteralStringBody::Unconstructible(reason),
        },
        Expr::MethodCall(c) if c.method == "to_string" && c.args.is_empty() => {
            LiteralStringBody::ToString {
                receiver: SugarBody::format_value(&c.receiver, fcx),
            }
        }
        Expr::Binary(b) if matches!(b.op, syn::BinOp::Add(_)) => LiteralStringBody::StringAdd {
            left: SugarBody::literal_string(&b.left, fcx),
            right: SugarBody::literal_string(&b.right, fcx),
        },
        _ => LiteralStringBody::Unconstructible(
            "format string body did not reduce to a literal string; write more Sugar for this AST"
                .to_string(),
        ),
    };
    Box::new(body)
}

pub(crate) fn build_format_value_body(expr: &Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    let body = match strip_refs_groups(expr) {
        e if crate::sugar::cstr::has_literal_cstr_floor(e, fcx) => {
            FormatValueBody::CStr(SugarBody::literal_cstr(e, fcx))
        }
        Expr::Lit(ExprLit { lit, .. }) => match reconstruct_lit(lit) {
            Ok(Some(value)) => FormatValueBody::Literal(value),
            Ok(None) => FormatValueBody::Unconstructible(format!(
                "format argument literal is not supported: {}; write more Sugar for this AST",
                token_key(strip_refs_groups(expr))
            )),
            Err(reason) => FormatValueBody::Terminal(reason),
        },
        Expr::Unary(u) if matches!(u.op, syn::UnOp::Neg(_)) => {
            FormatValueBody::Neg(SugarBody::format_value(&u.expr, fcx))
        }
        Expr::Binary(b) if is_fmt_arith_op(&b.op) => FormatValueBody::Binary {
            op: b.op.clone(),
            left: SugarBody::format_value(&b.left, fcx),
            right: SugarBody::format_value(&b.right, fcx),
        },
        Expr::Macro(m) if macro_is(m, "format_args") => match build_format_args_value(expr, fcx) {
            Ok(body) => FormatValueBody::FormatArgs(body),
            Err(reason) => FormatValueBody::Unconstructible(reason),
        },
        Expr::Path(path) if path.qself.is_none() => match path.path.get_ident() {
            Some(ident) => {
                let name = ident.to_string();
                match stable_binding_init(&name, fcx) {
                    Some(init) if !fcx.resolving_bound_path(&name) => {
                        let child_fcx = fcx.with_bound_path(&name);
                        FormatValueBody::Child(SugarBody::format_value(init, &child_fcx))
                    }
                    Some(_) => FormatValueBody::Unconstructible(
                        "self-referential format argument binding; write more Sugar for this AST"
                            .to_string(),
                    ),
                    None => FormatValueBody::Term(SugarBody::term(strip_refs_groups(expr), fcx)),
                }
            }
            None => FormatValueBody::Term(SugarBody::term(strip_refs_groups(expr), fcx)),
        },
        e if is_format_shape(e) => {
            FormatValueBody::String(SugarBody::literal_string(strip_refs_groups(expr), fcx))
        }
        _ => FormatValueBody::Term(SugarBody::term(strip_refs_groups(expr), fcx)),
    };
    Box::new(body)
}

pub(crate) fn literal_format_capture_names(expr: &Expr) -> Option<Vec<String>> {
    let Expr::Lit(ExprLit {
        lit: Lit::Str(value),
        ..
    }) = strip_refs_groups(expr)
    else {
        return None;
    };
    format_capture_names(&value.value())
}

pub(crate) fn format_capture_names(fmt: &str) -> Option<Vec<String>> {
    let mut names = Vec::new();
    for piece in parse_fmt_pieces(fmt)? {
        if let Piece::Placeholder {
            arg: ArgRef::Named(name),
            ..
        } = piece
        {
            names.push(name);
        }
    }
    Some(names)
}

fn stable_binding_init<'a>(name: &str, fcx: &'a SugarBuildCtx) -> Option<&'a Expr> {
    fcx.scope().stable_let_binding_for_term(name)
}

enum FormatTemplateBody {
    Literal(String),
    LiteralString(SugarBody<LiteralStringFloor>),
    Unconstructible(String),
}

impl Sugar for FormatTemplateBody {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self {
            FormatTemplateBody::Literal(value) => {
                Outcome::Complete(Desugared::LiteralString(value.clone()))
            }
            FormatTemplateBody::LiteralString(child) => match child.reduce_literal_string(ctx) {
                FloorRead::Complete(value) => Outcome::Complete(Desugared::LiteralString(value)),
                FloorRead::Incomplete(effect) => Outcome::Incomplete(effect),
            },
            FormatTemplateBody::Unconstructible(reason) => panic!("{reason}"),
        }
    }
}

enum LiteralStringBody {
    Literal(String),
    Child(SugarBody<LiteralStringFloor>),
    Concat(Vec<ConcatFragmentBody>),
    ToString {
        receiver: SugarBody<FormatValueFloor>,
    },
    StringAdd {
        left: SugarBody<LiteralStringFloor>,
        right: SugarBody<LiteralStringFloor>,
    },
    Unconstructible(String),
}

enum ConcatFragmentBody {
    String(SugarBody<LiteralStringFloor>),
    Value(SugarBody<FormatValueFloor>),
    Unconstructible(String),
}

struct LiteralStringTermSugar {
    body: SugarBody<LiteralStringFloor>,
}

impl Sugar for LiteralStringTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.body.reduce_literal_string(ctx) {
            FloorRead::Complete(value) => {
                Outcome::Complete(Desugared::Term(sugar_ir_symbolic::str_const(value)))
            }
            FloorRead::Incomplete(effect) => Outcome::Incomplete(effect),
        }
    }
}

impl Sugar for LiteralStringBody {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self {
            LiteralStringBody::Literal(value) => {
                Outcome::Complete(Desugared::LiteralString(value.clone()))
            }
            LiteralStringBody::Child(child) => match child.reduce_literal_string(ctx) {
                FloorRead::Complete(value) => Outcome::Complete(Desugared::LiteralString(value)),
                FloorRead::Incomplete(effect) => Outcome::Incomplete(effect),
            },
            LiteralStringBody::Concat(fragments) => {
                let mut out = String::new();
                for fragment in fragments {
                    match fragment {
                        ConcatFragmentBody::String(body) => match body.reduce_literal_string(ctx) {
                            FloorRead::Complete(value) => out.push_str(&value),
                            FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
                        },
                        ConcatFragmentBody::Value(body) => match body.reduce_format_value(ctx) {
                            FloorRead::Complete(value) => {
                                match value.render(&Spec::display()) {
                                    Ok(Some(value)) => out.push_str(&value),
                                    Ok(None) => panic!(
                                        "concat fragment did not render as a literal string; implement the typed formatter"
                                    ),
                                    Err(reason) => panic!(
                                        "concat fragment formatter could not render its literal floor: {reason}"
                                    ),
                                }
                            }
                            FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
                        },
                        ConcatFragmentBody::Unconstructible(reason) => {
                            panic!("{reason}");
                        }
                    }
                }
                Outcome::Complete(Desugared::LiteralString(out))
            }
            LiteralStringBody::ToString { receiver } => {
                let value = match receiver.reduce_format_value(ctx) {
                    FloorRead::Complete(value) => value,
                    FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
                };
                match value.render(&Spec::display()) {
                    Ok(Some(value)) => Outcome::Complete(Desugared::LiteralString(value)),
                    Ok(None) => panic!(
                        "to_string receiver did not render as a literal string; implement the typed formatter"
                    ),
                    Err(reason) => panic!(
                        "to_string formatter could not render its literal floor: {reason}"
                    ),
                }
            }
            LiteralStringBody::StringAdd { left, right } => {
                let left = match left.reduce_literal_string(ctx) {
                    FloorRead::Complete(value) => value,
                    FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
                };
                let right = match right.reduce_literal_string(ctx) {
                    FloorRead::Complete(value) => value,
                    FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
                };
                Outcome::Complete(Desugared::LiteralString(format!("{left}{right}")))
            }
            LiteralStringBody::Unconstructible(reason) => {
                panic!("{reason}");
            }
        }
    }
}

fn build_concat_string_body(expr: &Expr, fcx: &SugarBuildCtx) -> Result<LiteralStringBody, String> {
    let Expr::Macro(mac) = strip_refs_groups(expr) else {
        return Err(
            "concat macro recognizer received a non-macro site; write more Sugar for this AST"
                .to_string(),
        );
    };
    let args = parse_args(&mac.mac.tokens).ok_or_else(|| {
        "concat macro arguments did not parse; write more Sugar for this AST".to_string()
    })?;
    Ok(LiteralStringBody::Concat(
        args.iter()
            .map(|arg| build_concat_fragment_body(arg, fcx))
            .collect(),
    ))
}

fn build_concat_fragment_body(expr: &Expr, fcx: &SugarBuildCtx) -> ConcatFragmentBody {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Str(_), ..
        })
        | Expr::Macro(_) => ConcatFragmentBody::String(SugarBody::literal_string(expr, fcx)),
        Expr::Lit(_) => ConcatFragmentBody::Value(SugarBody::format_value(expr, fcx)),
        Expr::Path(path) if path.qself.is_none() => {
            ConcatFragmentBody::String(SugarBody::literal_string(expr, fcx))
        }
        _ => ConcatFragmentBody::Unconstructible(
            "concat fragment is not a literal string/value floor; write more Sugar for this AST"
                .to_string(),
        ),
    }
}

enum FormatValueBody {
    Literal(FmtValue),
    Child(SugarBody<FormatValueFloor>),
    String(SugarBody<LiteralStringFloor>),
    CStr(SugarBody<LiteralCStrFloor>),
    Term(SugarBody<TermFloor>),
    Neg(SugarBody<FormatValueFloor>),
    Binary {
        op: syn::BinOp,
        left: SugarBody<FormatValueFloor>,
        right: SugarBody<FormatValueFloor>,
    },
    FormatArgs(FormatArgsValueBody),
    Terminal(String),
    Unconstructible(String),
}

struct FormatArgsValueBody {
    source_memento: String,
    fmt: SugarBody<FormatTemplateFloor>,
    positional: Vec<SugarBody<FormatValueFloor>>,
    explicit_named: BTreeMap<String, SugarBody<FormatValueFloor>>,
    captures: BTreeMap<String, SugarBody<FormatValueFloor>>,
}

fn build_format_args_value(
    expr: &Expr,
    fcx: &SugarBuildCtx,
) -> Result<FormatArgsValueBody, String> {
    let Expr::Macro(mac) = strip_refs_groups(expr) else {
        return Err(
            "format_args value recognizer received a non-macro site; write more Sugar for this AST"
                .to_string(),
        );
    };
    let args = parse_args(&mac.mac.tokens).ok_or_else(|| {
        "format_args macro arguments did not parse; write more Sugar for this AST".to_string()
    })?;
    let Some((fmt_expr, rest)) = args.split_first() else {
        return Err(
            "format_args macro has no format string; write more Sugar for this AST".to_string(),
        );
    };

    let mut positional = Vec::new();
    let mut explicit_named = BTreeMap::new();
    for arg in rest {
        if let Some((name, value)) = explicit_named_format_arg(arg) {
            explicit_named.insert(name, SugarBody::format_value(value, fcx));
        } else {
            positional.push(SugarBody::format_value(arg, fcx));
        }
    }

    let captures = format_capture_bodies(fmt_expr, fcx, &explicit_named)?;

    Ok(FormatArgsValueBody {
        source_memento: token_key(expr),
        fmt: SugarBody::format_template(fmt_expr, fcx),
        positional,
        explicit_named,
        captures,
    })
}

fn format_capture_bodies(
    fmt_expr: &Expr,
    fcx: &SugarBuildCtx,
    explicit_named: &BTreeMap<String, SugarBody<FormatValueFloor>>,
) -> Result<BTreeMap<String, SugarBody<FormatValueFloor>>, String> {
    match literal_format_capture_names(fmt_expr) {
        Some(names) => names
            .into_iter()
            .filter(|name| !explicit_named.contains_key(name))
            .map(|name| {
                let body = match fcx.scope().stable_let_binding_for_term(&name) {
                    Some(init) if !fcx.resolving_bound_path(&name) => {
                        let child_fcx = fcx.with_bound_path(&name);
                        SugarBody::format_value(init, &child_fcx)
                    }
                    Some(_) => {
                        return Err(format!(
                            "format_args capture `{name}` is self-referential; write more Sugar for this AST"
                        ));
                    }
                    None => {
                        let captured: Expr = syn::parse_str(&name).unwrap_or_else(|err| {
                            panic!("format_args capture `{name}` was not an expression path: {err}")
                        });
                        SugarBody::format_value(&captured, fcx)
                    }
                };
                Ok((name, body))
            })
            .collect(),
        None => Ok(fcx
            .scope()
            .let_bindings_iter()
            .filter_map(|(name, _)| {
                if explicit_named.contains_key(name) {
                    return None;
                }
                let init = fcx.scope().stable_let_binding_for_term(name)?;
                if fcx.resolving_bound_path(name) {
                    return None;
                }
                let child_fcx = fcx.with_bound_path(name);
                Some((name.clone(), SugarBody::format_value(init, &child_fcx)))
            })
            .collect()),
    }
}

fn explicit_named_format_arg(expr: &Expr) -> Option<(String, &Expr)> {
    let Expr::Assign(assign) = expr else {
        return None;
    };
    let Expr::Path(path) = assign.left.as_ref() else {
        return None;
    };
    let ident = path.path.get_ident()?;
    Some((ident.to_string(), assign.right.as_ref()))
}

impl Sugar for FormatValueBody {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self {
            FormatValueBody::Literal(value) => {
                Outcome::Complete(Desugared::FormatValue(value.clone()))
            }
            FormatValueBody::Child(child) => match child.reduce_format_value(ctx) {
                FloorRead::Complete(value) => Outcome::Complete(Desugared::FormatValue(value)),
                FloorRead::Incomplete(effect) => Outcome::Incomplete(effect),
            },
            FormatValueBody::String(child) => match child.reduce_literal_string(ctx) {
                FloorRead::Complete(value) => {
                    Outcome::Complete(Desugared::FormatValue(FmtValue::Str(value)))
                }
                FloorRead::Incomplete(effect) => Outcome::Incomplete(effect),
            },
            FormatValueBody::CStr(child) => match child.reduce_literal_cstr(ctx) {
                FloorRead::Complete(value) => {
                    Outcome::Complete(Desugared::FormatValue(FmtValue::CStr(value)))
                }
                FloorRead::Incomplete(effect) => Outcome::Incomplete(effect),
            },
            FormatValueBody::Term(child) => match child.reduce(ctx) {
                Outcome::Complete(Desugared::Term(term)) => {
                    match format_value_from_term_floor_opt(&term) {
                        Some(value) => Outcome::Complete(Desugared::FormatValue(value)),
                        None => Outcome::Incomplete(runtime_format_argument_effect(
                            &canonical_term_sig(&term),
                        )),
                    }
                }
                Outcome::Complete(_) => {
                    panic!("format argument child completed a non-term floor; fix the factory")
                }
                Outcome::Incomplete(effect) => Outcome::Incomplete(effect),
            },
            FormatValueBody::Neg(child) => {
                let value = match child.reduce_format_value(ctx) {
                    FloorRead::Complete(value) => value,
                    FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
                };
                let negated = match value {
                    FmtValue::Int { value, suffix } => FmtValue::Int {
                        value: match value.checked_neg() {
                            Some(value) => value,
                            None => panic!(
                                "format unary negation overflowed; delegate numeric semantics to the owning floor"
                            ),
                        },
                        suffix,
                    },
                    FmtValue::F32(value) => FmtValue::F32(-value),
                    FmtValue::F64(value) => FmtValue::F64(-value),
                    _ => {
                        panic!(
                            "format unary negation did not receive a numeric value; write the owning format value floor"
                        )
                    }
                };
                Outcome::Complete(Desugared::FormatValue(negated))
            }
            FormatValueBody::Binary { op, left, right } => {
                let left = match left.reduce_format_value(ctx) {
                    FloorRead::Complete(value) => value,
                    FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
                };
                let right = match right.reduce_format_value(ctx) {
                    FloorRead::Complete(value) => value,
                    FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
                };
                let folded = match fold_format_values(op, left, right) {
                    Ok(value) => value,
                    Err(reason)
                        if reason
                            .contains("format integer arithmetic overflow or divide-by-zero") =>
                    {
                        return Outcome::Incomplete(format_arithmetic_effect(&reason));
                    }
                    Err(reason) => panic!("{reason}"),
                };
                Outcome::Complete(Desugared::FormatValue(folded))
            }
            FormatValueBody::FormatArgs(body) => body.desugar(ctx),
            FormatValueBody::Terminal(reason) => panic!("{reason}"),
            FormatValueBody::Unconstructible(reason) => {
                panic!("{reason}");
            }
        }
    }
}

impl Sugar for FormatArgsValueBody {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let fmt = match self.fmt.reduce_format_template(ctx) {
            FloorRead::Complete(value) => value,
            FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
        };

        let mut positional = Vec::new();
        for body in &self.positional {
            match body.reduce_format_value(ctx) {
                FloorRead::Complete(value) => positional.push(value),
                FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
            }
        }

        let mut explicit_named = BTreeMap::new();
        for (name, body) in &self.explicit_named {
            match body.reduce_format_value(ctx) {
                FloorRead::Complete(value) => {
                    explicit_named.insert(name.clone(), value);
                }
                FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
            }
        }

        let mut captures = BTreeMap::new();
        for (name, body) in &self.captures {
            match body.reduce_format_value(ctx) {
                FloorRead::Complete(value) => {
                    captures.insert(name.clone(), value);
                }
                FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
            }
        }

        match render_format_values(
            &fmt,
            &positional,
            &explicit_named,
            &captures,
            &self.source_memento,
        ) {
            FloorRead::Complete(value) => {
                Outcome::Complete(Desugared::FormatValue(FmtValue::FormatArgsText(value)))
            }
            FloorRead::Incomplete(effect) => Outcome::Incomplete(effect),
        }
    }
}

pub(crate) fn display_format_value_floor(value: &FmtValue) -> Result<Option<String>, String> {
    value.render(&Spec::display())
}

pub(crate) fn literal_string_floor_from_outcome(reduction: Outcome) -> FloorRead<String> {
    match reduction {
        Outcome::Complete(Desugared::LiteralString(value)) => FloorRead::Complete(value),
        Outcome::Complete(_) => {
            panic!("format string child completed a non-literal-string floor; fix the factory")
        }
        Outcome::Incomplete(effect) => FloorRead::Incomplete(effect),
    }
}

pub(crate) fn format_template_floor_from_outcome(reduction: Outcome) -> FloorRead<String> {
    match reduction {
        Outcome::Complete(Desugared::LiteralString(value)) => FloorRead::Complete(value),
        Outcome::Complete(_) => {
            panic!("format template child completed a non-template floor; fix the factory")
        }
        Outcome::Incomplete(effect) => FloorRead::Incomplete(effect),
    }
}

pub(crate) fn format_value_floor_from_outcome(reduction: Outcome) -> FloorRead<FmtValue> {
    match reduction {
        Outcome::Complete(Desugared::FormatValue(value)) => FloorRead::Complete(value),
        Outcome::Complete(_) => {
            panic!("format argument child completed a non-format-value floor; fix the factory")
        }
        Outcome::Incomplete(effect) => FloorRead::Incomplete(effect),
    }
}

fn fold_format_values(
    op: &syn::BinOp,
    left: FmtValue,
    right: FmtValue,
) -> Result<FmtValue, String> {
    if let (
        FmtValue::Int {
            value: lv,
            suffix: ls,
        },
        FmtValue::Int {
            value: rv,
            suffix: rs,
        },
    ) = (&left, &right)
    {
        return fold_int_arith_for_format(op, *lv, *ls, *rv, *rs)
            .map(|(value, suffix)| FmtValue::Int { value, suffix });
    }

    if matches!(op, syn::BinOp::Div(_)) {
        return match (left, right) {
            (FmtValue::F64(l), FmtValue::F64(r)) => Ok(FmtValue::F64(l / r)),
            (FmtValue::F32(l), FmtValue::F32(r)) => Ok(FmtValue::F32(l / r)),
            _ => Err(
                "format float division did not receive matching float literals; write more Sugar for this AST"
                    .to_string(),
            ),
        };
    }

    if matches!(op, syn::BinOp::Add(_)) {
        if let (FmtValue::Str(left), FmtValue::Str(right)) = (left, right) {
            return Ok(FmtValue::Str(format!("{left}{right}")));
        }
    }

    Err(
        "format binary argument did not reduce to a supported literal operation; write more Sugar for this AST"
            .to_string(),
    )
}

pub(crate) fn is_format_macro_shape(expr: &Expr) -> bool {
    matches!(strip_refs_groups(expr), Expr::Macro(m) if macro_is(m, "format"))
}

pub(crate) fn is_format_args_macro_shape(expr: &Expr) -> bool {
    matches!(strip_refs_groups(expr), Expr::Macro(m) if macro_is(m, "format_args"))
}

pub(crate) fn is_concat_macro_shape(expr: &Expr) -> bool {
    matches!(strip_refs_groups(expr), Expr::Macro(m) if macro_is(m, "concat"))
}

pub(crate) fn is_to_string_shape(expr: &Expr) -> bool {
    matches!(
        strip_refs_groups(expr),
        Expr::MethodCall(c) if c.method == "to_string" && c.args.is_empty()
    )
}

pub(crate) fn is_string_add_shape(expr: &Expr) -> bool {
    matches!(
        strip_refs_groups(expr),
        Expr::Binary(b) if matches!(b.op, syn::BinOp::Add(_))
    )
}

pub(crate) fn is_factory_string_add_shape(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    let Expr::Binary(binary) = strip_refs_groups(expr) else {
        return false;
    };
    matches!(binary.op, syn::BinOp::Add(_))
        && (is_string_add_operand_shape(&binary.left, fcx)
            || is_string_add_operand_shape(&binary.right, fcx))
}

fn is_string_add_operand_shape(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Str(_), ..
        }) => true,
        Expr::Macro(m) if macro_is(m, "format") || macro_is(m, "concat") => true,
        Expr::MethodCall(call) if call.method == "to_string" && call.args.is_empty() => true,
        Expr::Binary(_) => is_factory_string_add_shape(expr, fcx),
        Expr::Path(path) if path.qself.is_none() => path
            .path
            .get_ident()
            .and_then(|ident| {
                let name = ident.to_string();
                if fcx.resolving_bound_path(&name) {
                    return None;
                }
                let child_fcx = fcx.with_bound_path(&name);
                stable_binding_init(&name, fcx)
                    .map(|init| is_string_add_operand_shape(init, &child_fcx))
            })
            .unwrap_or(false),
        _ => false,
    }
}

/// Is `expr` one of the recognized format-producing shapes? (Recognition only — the
/// operands need not be literals here.)
fn is_format_shape(expr: &Expr) -> bool {
    is_format_macro_shape(expr)
        || is_concat_macro_shape(expr)
        || is_to_string_shape(expr)
        || is_string_add_shape(expr)
}

// ── The core: resolve a format-producing expr to its ONE string value ────────────
//
// Result semantics for the legacy helper tests below:
//   Ok(Some(s)) — dissolved to the string `s` (recompute via real `format!`).
//   Ok(None)    — the helper could not resolve a string on its own. The constructed
//                 Sugar path must represent that as a factory gap or a child effect,
//                 never as a local format/runtime-argument effect.
//   Err(reason) — a named unsupported render path. The constructed Sugar path treats
//                 this as a gap until a typed owner exists.

/// A typed literal value reconstructed from the source AST, carrying enough to render
/// it through the real stdlib `format!` for every spec we faithfully reproduce.
#[derive(Clone, Debug)]
pub(crate) enum FmtValue {
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
    ByteStr(Vec<u8>),
    CStr(CStrBytes),
    Bool(bool),
    FormatArgsText(String),
    DebugText(String),
}

trait FormatLiteralVisitor {
    type Output;

    fn visit_int(self, value: i128, suffix: IntKind) -> Self::Output;
    fn visit_f32(self, value: f32) -> Self::Output;
    fn visit_f64(self, value: f64) -> Self::Output;
    fn visit_char(self, value: char) -> Self::Output;
    fn visit_string(self, value: &str) -> Self::Output;
    fn visit_byte_string(self, value: &[u8]) -> Self::Output;
    fn visit_cstr(self, value: &CStrBytes) -> Self::Output;
    fn visit_bool(self, value: bool) -> Self::Output;
    fn visit_format_args_text(self, value: &str) -> Self::Output;
    fn visit_debug_text(self, value: &str) -> Self::Output;
}

impl FmtValue {
    fn accept<V: FormatLiteralVisitor>(&self, visitor: V) -> V::Output {
        match self {
            FmtValue::Int { value, suffix } => visitor.visit_int(*value, *suffix),
            FmtValue::F32(value) => visitor.visit_f32(*value),
            FmtValue::F64(value) => visitor.visit_f64(*value),
            FmtValue::Char(value) => visitor.visit_char(*value),
            FmtValue::Str(value) => visitor.visit_string(value),
            FmtValue::ByteStr(value) => visitor.visit_byte_string(value),
            FmtValue::CStr(value) => visitor.visit_cstr(value),
            FmtValue::Bool(value) => visitor.visit_bool(*value),
            FmtValue::FormatArgsText(value) => visitor.visit_format_args_text(value),
            FmtValue::DebugText(value) => visitor.visit_debug_text(value),
        }
    }

    fn render(&self, spec: &Spec) -> Result<Option<String>, String> {
        if let Some((fill, align, width)) = spec.explicit_arbitrary_fill_padding() {
            let inner = spec.without_explicit_fill_padding();
            return self.accept(RenderVisitor { spec: &inner }).map(|rendered| {
                rendered.map(|body| apply_explicit_fill(body, fill, align, width))
            });
        }
        self.accept(RenderVisitor { spec })
    }
}

#[cfg(test)]
fn format_value_from_term_floor(term: &Rc<Term>, owner: &str) -> FmtValue {
    format_value_from_term_floor_opt(term).unwrap_or_else(|| {
        panic!(
            "{} term floor did not dispatch to a literal format value: {}",
            owner,
            canonical_term_sig(term)
        )
    })
}

fn runtime_format_argument_effect(boundary: &str) -> Effect {
    Effect::RuntimeFormatArgument {
        boundary: boundary.to_string(),
    }
}

fn format_arithmetic_effect(reason: &str) -> Effect {
    Effect::FormatArgument {
        reason: reason.to_string(),
    }
}

fn format_pointer_effect(boundary: &str) -> Effect {
    Effect::FormatPointerAddress {
        boundary: boundary.to_string(),
    }
}

pub(crate) fn display_literal_term_floor(term: &Rc<Term>) -> Option<String> {
    format_value_from_term_floor_opt(term)?
        .render(&Spec::display())
        .ok()?
}

fn format_value_from_term_floor_opt(term: &Rc<Term>) -> Option<FmtValue> {
    if let Some(floor) = numeric_floor_from_term(term) {
        return format_value_from_numeric_floor(floor);
    }

    match term.as_ref() {
        Term::Const {
            value: ConstValue::String(value),
            ..
        } => Some(FmtValue::Str(value.clone())),
        Term::Const {
            value: ConstValue::Bool(value),
            ..
        } => Some(FmtValue::Bool(*value)),
        Term::Ctor { name, args } if name == "method:unwrap" && args.len() == 1 => {
            literal_unwrap_format_value(&args[0])
        }
        _ => crate::sugar::range_term::literal_range_debug_string(term).map(FmtValue::DebugText),
    }
}

fn literal_unwrap_format_value(term: &Rc<Term>) -> Option<FmtValue> {
    match term.as_ref() {
        Term::Ctor { name, args } if name == OPT_SOME && args.len() == 1 => {
            format_value_from_term_floor_opt(&args[0])
        }
        _ => None,
    }
}

fn format_value_from_numeric_floor(floor: NumericFloor) -> Option<FmtValue> {
    match floor {
        NumericFloor::Untyped(value) => Some(FmtValue::Int {
            value,
            suffix: IntKind::Unsuffixed,
        }),
        NumericFloor::Typed { value, kind } => {
            let suffix = format_int_kind(kind)?;
            let value = match value {
                ExactInt::Signed(value) => value,
                ExactInt::Unsigned(value) => value as i128,
            };
            Some(FmtValue::Int { value, suffix })
        }
    }
}

fn format_int_kind(kind: NumericIntKind) -> Option<IntKind> {
    Some(match kind.name {
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
        _ => return None,
    })
}

struct RenderVisitor<'a> {
    spec: &'a Spec,
}

impl FormatLiteralVisitor for RenderVisitor<'_> {
    type Output = Result<Option<String>, String>;

    fn visit_int(self, value: i128, suffix: IntKind) -> Self::Output {
        Ok(render_int(value, suffix, self.spec))
    }

    fn visit_f32(self, value: f32) -> Self::Output {
        Ok(render_float_f32(value, self.spec))
    }

    fn visit_f64(self, value: f64) -> Self::Output {
        Ok(render_float_f64(value, self.spec))
    }

    fn visit_char(self, value: char) -> Self::Output {
        Ok(render_char(value, self.spec))
    }

    fn visit_string(self, value: &str) -> Self::Output {
        Ok(render_str(value, self.spec))
    }

    fn visit_byte_string(self, value: &[u8]) -> Self::Output {
        Ok(render_byte_str(value, self.spec))
    }

    fn visit_cstr(self, value: &CStrBytes) -> Self::Output {
        value.accept_literal_cstr(RenderCStrVisitor { spec: self.spec })
    }

    fn visit_bool(self, value: bool) -> Self::Output {
        Ok(render_bool(value, self.spec))
    }

    fn visit_format_args_text(self, value: &str) -> Self::Output {
        if matches!(self.spec.kind, Kind::Display | Kind::Debug)
            && !self.spec.plus
            && self.spec.align.is_none()
            && self.spec.zero_width.is_none()
            && self.spec.precision.is_none()
            && (self.spec.kind == Kind::Debug || !self.spec.alternate)
        {
            Ok(Some(value.to_string()))
        } else {
            Ok(None)
        }
    }

    fn visit_debug_text(self, value: &str) -> Self::Output {
        if self.spec.kind == Kind::Debug
            && !self.spec.plus
            && self.spec.align.is_none()
            && self.spec.width.is_none()
            && self.spec.zero_width.is_none()
            && self.spec.precision.is_none()
        {
            Ok(Some(value.to_string()))
        } else {
            Ok(None)
        }
    }
}

struct RenderCStrVisitor<'a> {
    spec: &'a Spec,
}

impl LiteralCStrVisitor for RenderCStrVisitor<'_> {
    type Output = Result<Option<String>, String>;

    fn visit_cstr(self, bytes: &CStrBytes) -> Self::Output {
        Ok(Some(render_cstr(bytes, self.spec)))
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum IntKind {
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
                Some(v) => v.render(&Spec::display()),
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

pub(crate) fn try_estimate_format_args_capacity(
    expr: &Expr,
    binds: &BTreeMap<String, Expr>,
) -> Result<Option<usize>, String> {
    let Expr::Macro(m) = strip_refs_groups(expr) else {
        return Ok(None);
    };
    if !macro_is(m, "format_args") {
        return Ok(None);
    }
    let args = match parse_args(&m.mac.tokens) {
        Some(a) => a,
        None => return Ok(None),
    };
    let Some((fmt_expr, _rest)) = args.split_first() else {
        return Ok(None);
    };
    let Some(fmt) = resolve_str_literal_only(fmt_expr, binds)? else {
        return Ok(None);
    };
    Ok(estimate_format_args_capacity(&fmt))
}

fn estimate_format_args_capacity(fmt: &str) -> Option<usize> {
    let mut literal_len = 0usize;
    let mut starts_with_placeholder = false;
    let mut saw_placeholder = false;
    let mut i = 0usize;
    while i < fmt.len() {
        let c = fmt[i..].chars().next()?;
        if c == '{' {
            if i + 1 < fmt.len() && fmt.as_bytes()[i + 1] == b'{' {
                literal_len = literal_len.wrapping_add(1);
                i += 2;
                continue;
            }
            let close = fmt[i + 1..].find('}').map(|j| i + 1 + j)?;
            saw_placeholder = true;
            if literal_len == 0 {
                starts_with_placeholder = true;
            }
            i = close + 1;
        } else if c == '}' {
            if i + 1 < fmt.len() && fmt.as_bytes()[i + 1] == b'}' {
                literal_len = literal_len.wrapping_add(1);
                i += 2;
                continue;
            }
            return None;
        } else {
            literal_len = literal_len.wrapping_add(c.len_utf8());
            i += c.len_utf8();
        }
    }
    if !saw_placeholder {
        return Some(literal_len);
    }
    if starts_with_placeholder && literal_len < 16 {
        Some(0)
    } else {
        Some(literal_len.wrapping_mul(2))
    }
}

fn macro_is(m: &syn::ExprMacro, name: &str) -> bool {
    m.mac.path.segments.last().is_some_and(|s| s.ident == name)
}

pub(crate) fn parse_args(tokens: &proc_macro2::TokenStream) -> Option<Vec<Expr>> {
    let parser = syn::punctuated::Punctuated::<Expr, syn::Token![,]>::parse_terminated;
    syn::parse::Parser::parse2(parser, tokens.clone())
        .ok()
        .map(|p| p.into_iter().collect())
}

// ── Render a parsed format string with positional/named/captured arguments ───────

/// Render a `format!("<fmt>", <args>)` by parsing the fmt string into literal segments
/// and `{...}` placeholders, resolving each placeholder's argument to a `FmtValue`, and
/// rendering it through a STATICALLY-WRITTEN real `format!` per its spec. Returns
/// `Ok(None)` on runtime args; uncovered written specs take the construction-gap panic.
fn render_format(
    fmt: &str,
    args: &[Expr],
    binds: &BTreeMap<String, Expr>,
) -> Result<Option<String>, String> {
    let pieces = match parse_fmt_pieces(fmt) {
        Some(p) => p,
        None => panic!(
            "write more Sugar for this AST: format-spec grammar not reproduced for `{fmt}`; \
             replacement=teach the format recognizer this exact rust-format spec or route a typed runtime-format refusal"
        ),
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
                    Some(v) => match v.render(&spec)? {
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

pub(crate) fn render_format_values(
    fmt: &str,
    positional: &[FmtValue],
    explicit_named: &BTreeMap<String, FmtValue>,
    captures: &BTreeMap<String, FmtValue>,
    source_memento: &str,
) -> FloorRead<String> {
    let context = || format!("template={fmt:?}; source_memento={source_memento}");
    let pieces = match parse_fmt_pieces(fmt) {
        Some(p) => p,
        None => panic!(
            "compiled format template did not parse; fix format template sugar: {}",
            context()
        ),
    };
    let mut next_positional = 0usize;
    let mut out = String::new();
    for piece in pieces {
        match piece {
            Piece::Lit(s) => out.push_str(&s),
            Piece::Placeholder { arg, spec } => {
                let value = match arg {
                    ArgRef::Implicit => {
                        let value = positional.get(next_positional);
                        next_positional += 1;
                        value
                    }
                    ArgRef::Positional(i) => positional.get(i),
                    ArgRef::Named(name) => {
                        explicit_named.get(&name).or_else(|| captures.get(&name))
                    }
                };
                let Some(value) = value else {
                    panic!(
                        "compiled format template referenced an argument the factory did not build: {}",
                        context()
                    );
                };
                match value.render(&spec) {
                    Ok(Some(s)) => out.push_str(&s),
                    Ok(None) if spec.kind == Kind::Pointer => {
                        return FloorRead::Incomplete(format_pointer_effect(&context()));
                    }
                    Ok(None) => {
                        panic!(
                            "completed format value did not render; implement double dispatch for this formatter: {}",
                            context()
                        );
                    }
                    Err(reason) => {
                        panic!(
                            "completed format value failed to render: {reason}: {}",
                            context()
                        )
                    }
                }
            }
        }
    }
    FloorRead::Complete(out)
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
// `#` alternate debug, optional `+` sign, optional fill/alignment, optional
// `0`-pad-to-width, optional bare width, and optional `.N` precision. Bare width is
// only rendered by value floors that explicitly own it; pointer formatting parses and
// bubbles a named runtime-address effect.

#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    Display,
    Debug,
    LowerHex,
    LowerHexDebug,
    UpperHex,
    UpperHexDebug,
    Binary,
    Octal,
    LowerExp,
    UpperExp,
    Pointer,
}

#[derive(Clone, Copy)]
struct Spec {
    kind: Kind,
    alternate: bool,
    plus: bool,
    fill: Option<char>,
    align: Option<Align>,
    width: Option<usize>,
    zero_width: Option<usize>,
    precision: Option<usize>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Align {
    Left,
    Right,
    Center,
}

impl Align {
    fn parse(c: char) -> Option<Self> {
        Some(match c {
            '<' => Align::Left,
            '>' => Align::Right,
            '^' => Align::Center,
            _ => return None,
        })
    }
}

impl Spec {
    fn display() -> Spec {
        Spec {
            kind: Kind::Display,
            alternate: false,
            plus: false,
            fill: None,
            align: None,
            width: None,
            zero_width: None,
            precision: None,
        }
    }

    fn explicit_arbitrary_fill_padding(&self) -> Option<(char, Align, usize)> {
        let fill = self.fill?;
        if fill == '0' || fill == ' ' {
            return None;
        }
        let align = self.align?;
        Some((fill, align, self.zero_width.or(self.width).unwrap_or(0)))
    }

    fn without_explicit_fill_padding(&self) -> Spec {
        let mut spec = *self;
        spec.fill = None;
        spec.align = None;
        spec.width = None;
        spec.zero_width = None;
        spec
    }

    /// Parse a format SPEC (the part after `:`). Returns `None` for any spec feature we
    /// do NOT faithfully reproduce (`$`/`*` dynamic width, etc.) — refuse by NOT digging,
    /// never guess.
    fn parse(spec: &str) -> Option<Spec> {
        let mut s = spec;
        let mut alternate = false;
        let mut plus = false;
        let mut fill = None;
        let mut align = None;
        let mut zero_fill = false;
        let mut width = None;
        let mut zero_width = None;
        let mut precision = None;

        // [[fill]align] — Rust permits any fill char when followed by `<`, `>`, or `^`.
        // The value floor renders the body through the real formatter, then applies the
        // explicit fill as pure padding around that already-reduced text.
        let mut chars = s.char_indices();
        if let Some((_, c0)) = chars.next() {
            if let Some((i1, c1)) = chars.next() {
                if let Some(parsed) = Align::parse(c1) {
                    fill = Some(c0);
                    align = Some(parsed);
                    if c0 == '0' {
                        zero_fill = true;
                    }
                    s = &s[i1 + c1.len_utf8()..];
                } else if let Some(parsed) = Align::parse(c0) {
                    align = Some(parsed);
                    s = &s[c0.len_utf8()..];
                }
            } else if let Some(parsed) = Align::parse(c0) {
                align = Some(parsed);
                s = &s[c0.len_utf8()..];
            }
        }

        // [sign] — `+` supported, `-` is a no-op in rust (rejected to be safe).
        if let Some(rest) = s.strip_prefix('+') {
            plus = true;
            s = rest;
        } else if s.starts_with('-') {
            return None;
        }

        // [#] alternate — supported only where the owning floor below can delegate to
        // Rust's real formatter. Unsupported combinations still return None later.
        if let Some(rest) = s.strip_prefix('#') {
            alternate = true;
            s = rest;
        }

        // [0][width] — `0`-padded fixed width gets its own field. Bare width is accepted
        // structurally and then rendered only by floors that explicitly own it.
        if let Some(rest) = s.strip_prefix('0') {
            zero_fill = true;
            s = rest;
        }

        if zero_fill {
            // parse the width digits
            let digits: String = s.chars().take_while(|c| c.is_ascii_digit()).collect();
            if !digits.is_empty() {
                zero_width = Some(digits.parse().ok()?);
                s = &s[digits.len()..];
            } else {
                // `{:0}` with no width — degenerate; treat as width 0 (no pad) and
                // continue (rare). Effectively a no-op.
            }
        } else {
            let digits: String = s.chars().take_while(|c| c.is_ascii_digit()).collect();
            if !digits.is_empty() {
                width = Some(digits.parse().ok()?);
                s = &s[digits.len()..];
            }
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
            "x?" => Kind::LowerHexDebug,
            "X" => Kind::UpperHex,
            "X?" => Kind::UpperHexDebug,
            "b" => Kind::Binary,
            "o" => Kind::Octal,
            "e" => Kind::LowerExp,
            "E" => Kind::UpperExp,
            "p" => Kind::Pointer,
            // Anything else -> not reproduced.
            _ => return None,
        };

        Some(Spec {
            kind,
            alternate,
            plus,
            fill,
            align,
            width,
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

fn apply_explicit_fill(body: String, fill: char, align: Align, width: usize) -> String {
    let len = body.chars().count();
    if len >= width {
        return body;
    }
    let pad = width - len;
    match align {
        Align::Left => format!("{body}{}", repeat_fill(fill, pad)),
        Align::Right => format!("{}{body}", repeat_fill(fill, pad)),
        Align::Center => {
            let left = pad / 2;
            let right = pad - left;
            format!(
                "{}{body}{}",
                repeat_fill(fill, left),
                repeat_fill(fill, right)
            )
        }
    }
}

fn repeat_fill(fill: char, count: usize) -> String {
    std::iter::repeat_n(fill, count).collect()
}

fn render_i128_display(value: i128, spec: &Spec) -> String {
    if spec.alternate {
        return match (spec.align, spec.zero_width, spec.width, spec.plus) {
            (None, Some(w), _, false) => format!("{value:#0w$}"),
            (None, Some(w), _, true) => format!("{value:+#0w$}"),
            (None, None, Some(w), false) => format!("{value:#w$}"),
            (None, None, Some(w), true) => format!("{value:+#w$}"),
            (None, None, None, false) => format!("{value:#}"),
            (None, None, None, true) => format!("{value:+#}"),
            (Some(Align::Left), Some(w), _, false) => format!("{value:<#0w$}"),
            (Some(Align::Left), Some(w), _, true) => format!("{value:<+#0w$}"),
            (Some(Align::Left), None, Some(w), false) => format!("{value:<#w$}"),
            (Some(Align::Left), None, Some(w), true) => format!("{value:<+#w$}"),
            (Some(Align::Right), Some(w), _, false) => format!("{value:>#0w$}"),
            (Some(Align::Right), Some(w), _, true) => format!("{value:>+#0w$}"),
            (Some(Align::Right), None, Some(w), false) => format!("{value:>#w$}"),
            (Some(Align::Right), None, Some(w), true) => format!("{value:>+#w$}"),
            (Some(Align::Center), Some(w), _, false) => format!("{value:^#0w$}"),
            (Some(Align::Center), Some(w), _, true) => format!("{value:^+#0w$}"),
            (Some(Align::Center), None, Some(w), false) => format!("{value:^#w$}"),
            (Some(Align::Center), None, Some(w), true) => format!("{value:^+#w$}"),
            (Some(_), None, None, false) => format!("{value:#}"),
            (Some(_), None, None, true) => format!("{value:+#}"),
        };
    }

    match (spec.align, spec.zero_width, spec.width, spec.plus) {
        (None, Some(w), _, false) => format!("{value:0w$}"),
        (None, Some(w), _, true) => format!("{value:+0w$}"),
        (None, None, Some(w), false) => format!("{value:w$}"),
        (None, None, Some(w), true) => format!("{value:+w$}"),
        (None, None, None, false) => format!("{value}"),
        (None, None, None, true) => format!("{value:+}"),
        (Some(Align::Left), Some(w), _, false) => format!("{value:<0w$}"),
        (Some(Align::Left), Some(w), _, true) => format!("{value:<+0w$}"),
        (Some(Align::Left), None, Some(w), false) => format!("{value:<w$}"),
        (Some(Align::Left), None, Some(w), true) => format!("{value:<+w$}"),
        (Some(Align::Right), Some(w), _, false) => format!("{value:>0w$}"),
        (Some(Align::Right), Some(w), _, true) => format!("{value:>+0w$}"),
        (Some(Align::Right), None, Some(w), false) => format!("{value:>w$}"),
        (Some(Align::Right), None, Some(w), true) => format!("{value:>+w$}"),
        (Some(Align::Center), Some(w), _, false) => format!("{value:^0w$}"),
        (Some(Align::Center), Some(w), _, true) => format!("{value:^+0w$}"),
        (Some(Align::Center), None, Some(w), false) => format!("{value:^w$}"),
        (Some(Align::Center), None, Some(w), true) => format!("{value:^+w$}"),
        (Some(_), None, None, false) => format!("{value}"),
        (Some(_), None, None, true) => format!("{value:+}"),
    }
}

fn render_i128_debug(value: i128, spec: &Spec) -> Option<String> {
    Some(match (spec.align, spec.zero_width, spec.width, spec.plus) {
        (None, Some(w), _, false) => format!("{value:0w$?}"),
        (None, Some(w), _, true) => format!("{value:+0w$?}"),
        (None, None, Some(w), false) => format!("{value:w$?}"),
        (None, None, Some(w), true) => format!("{value:+w$?}"),
        (None, None, None, false) => format!("{value:?}"),
        (None, None, None, true) => format!("{value:+?}"),
        (Some(Align::Left), Some(w), _, false) => format!("{value:<0w$?}"),
        (Some(Align::Left), Some(w), _, true) => format!("{value:<+0w$?}"),
        (Some(Align::Left), None, Some(w), false) => format!("{value:<w$?}"),
        (Some(Align::Left), None, Some(w), true) => format!("{value:<+w$?}"),
        (Some(Align::Right), Some(w), _, false) => format!("{value:>0w$?}"),
        (Some(Align::Right), Some(w), _, true) => format!("{value:>+0w$?}"),
        (Some(Align::Right), None, Some(w), false) => format!("{value:>w$?}"),
        (Some(Align::Right), None, Some(w), true) => format!("{value:>+w$?}"),
        (Some(Align::Center), Some(w), _, false) => format!("{value:^0w$?}"),
        (Some(Align::Center), Some(w), _, true) => format!("{value:^+0w$?}"),
        (Some(Align::Center), None, Some(w), false) => format!("{value:^w$?}"),
        (Some(Align::Center), None, Some(w), true) => format!("{value:^+w$?}"),
        (Some(_), None, None, false) => format!("{value:?}"),
        (Some(_), None, None, true) => format!("{value:+?}"),
    })
}

fn render_str_display_floor(value: &str, spec: &Spec) -> String {
    match (spec.align, spec.zero_width, spec.width) {
        (None, Some(w), _) => format!("{value:0w$}"),
        (None, None, Some(w)) => format!("{value:w$}"),
        (None, None, None) => format!("{value}"),
        (Some(Align::Left), Some(w), _) => format!("{value:<0w$}"),
        (Some(Align::Left), None, Some(w)) => format!("{value:<w$}"),
        (Some(Align::Right), Some(w), _) => format!("{value:>0w$}"),
        (Some(Align::Right), None, Some(w)) => format!("{value:>w$}"),
        (Some(Align::Center), Some(w), _) => format!("{value:^0w$}"),
        (Some(Align::Center), None, Some(w)) => format!("{value:^w$}"),
        (Some(_), None, None) => format!("{value}"),
    }
}

fn render_str_debug_floor(value: &str, spec: &Spec) -> String {
    match (spec.align, spec.zero_width, spec.width) {
        (None, Some(w), _) => format!("{value:0w$?}"),
        (None, None, Some(w)) => format!("{value:w$?}"),
        (None, None, None) => format!("{value:?}"),
        (Some(Align::Left), Some(w), _) => format!("{value:<0w$?}"),
        (Some(Align::Left), None, Some(w)) => format!("{value:<w$?}"),
        (Some(Align::Right), Some(w), _) => format!("{value:>0w$?}"),
        (Some(Align::Right), None, Some(w)) => format!("{value:>w$?}"),
        (Some(Align::Center), Some(w), _) => format!("{value:^0w$?}"),
        (Some(Align::Center), None, Some(w)) => format!("{value:^w$?}"),
        (Some(_), None, None) => format!("{value:?}"),
    }
}

fn render_char_display_floor(value: char, spec: &Spec) -> String {
    match (spec.align, spec.zero_width, spec.width) {
        (None, Some(w), _) => format!("{value:0w$}"),
        (None, None, Some(w)) => format!("{value:w$}"),
        (None, None, None) => format!("{value}"),
        (Some(Align::Left), Some(w), _) => format!("{value:<0w$}"),
        (Some(Align::Left), None, Some(w)) => format!("{value:<w$}"),
        (Some(Align::Right), Some(w), _) => format!("{value:>0w$}"),
        (Some(Align::Right), None, Some(w)) => format!("{value:>w$}"),
        (Some(Align::Center), Some(w), _) => format!("{value:^0w$}"),
        (Some(Align::Center), None, Some(w)) => format!("{value:^w$}"),
        (Some(_), None, None) => format!("{value}"),
    }
}

fn render_char_debug_floor(value: char, spec: &Spec) -> String {
    match (spec.align, spec.zero_width, spec.width) {
        (None, Some(w), _) => format!("{value:0w$?}"),
        (None, None, Some(w)) => format!("{value:w$?}"),
        (None, None, None) => format!("{value:?}"),
        (Some(Align::Left), Some(w), _) => format!("{value:<0w$?}"),
        (Some(Align::Left), None, Some(w)) => format!("{value:<w$?}"),
        (Some(Align::Right), Some(w), _) => format!("{value:>0w$?}"),
        (Some(Align::Right), None, Some(w)) => format!("{value:>w$?}"),
        (Some(Align::Center), Some(w), _) => format!("{value:^0w$?}"),
        (Some(Align::Center), None, Some(w)) => format!("{value:^w$?}"),
        (Some(_), None, None) => format!("{value:?}"),
    }
}

fn render_bool_display_floor(value: bool, spec: &Spec) -> String {
    match (spec.align, spec.width) {
        (None, Some(w)) => format!("{value:w$}"),
        (None, None) => format!("{value}"),
        (Some(Align::Left), Some(w)) => format!("{value:<w$}"),
        (Some(Align::Right), Some(w)) => format!("{value:>w$}"),
        (Some(Align::Center), Some(w)) => format!("{value:^w$}"),
        (Some(_), None) => format!("{value}"),
    }
}

fn render_bool_debug_floor(value: bool, spec: &Spec) -> String {
    match (spec.align, spec.width) {
        (None, Some(w)) => format!("{value:w$?}"),
        (None, None) => format!("{value:?}"),
        (Some(Align::Left), Some(w)) => format!("{value:<w$?}"),
        (Some(Align::Right), Some(w)) => format!("{value:>w$?}"),
        (Some(Align::Center), Some(w)) => format!("{value:^w$?}"),
        (Some(_), None) => format!("{value:?}"),
    }
}

macro_rules! render_radix_kind {
    (
        $value:expr,
        $spec:expr,
        plain: $plain:literal,
        alternate: $alternate:literal,
        width: $width:literal,
        alternate_width: $alternate_width:literal,
        zero_width: $zero_width:literal,
        alternate_zero_width: $alternate_zero_width:literal,
        left: $left:literal,
        alternate_left: $alternate_left:literal,
        left_zero_width: $left_zero_width:literal,
        alternate_left_zero_width: $alternate_left_zero_width:literal,
        right: $right:literal,
        alternate_right: $alternate_right:literal,
        right_zero_width: $right_zero_width:literal,
        alternate_right_zero_width: $alternate_right_zero_width:literal,
        center: $center:literal,
        alternate_center: $alternate_center:literal,
        center_zero_width: $center_zero_width:literal,
        alternate_center_zero_width: $alternate_center_zero_width:literal $(,)?
    ) => {{
        let value = $value;
        Some(
            match ($spec.alternate, $spec.align, $spec.zero_width, $spec.width) {
                (false, None, Some(w), _) => format!($zero_width, value = value, w = w),
                (true, None, Some(w), _) => format!($alternate_zero_width, value = value, w = w),
                (false, None, None, Some(w)) => format!($width, value = value, w = w),
                (true, None, None, Some(w)) => format!($alternate_width, value = value, w = w),
                (false, None, None, None) => format!($plain, value = value),
                (true, None, None, None) => format!($alternate, value = value),
                (false, Some(Align::Left), Some(w), _) => {
                    format!($left_zero_width, value = value, w = w)
                }
                (true, Some(Align::Left), Some(w), _) => {
                    format!($alternate_left_zero_width, value = value, w = w)
                }
                (false, Some(Align::Left), None, Some(w)) => {
                    format!($left, value = value, w = w)
                }
                (true, Some(Align::Left), None, Some(w)) => {
                    format!($alternate_left, value = value, w = w)
                }
                (false, Some(Align::Left), None, None) => format!($plain, value = value),
                (true, Some(Align::Left), None, None) => format!($alternate, value = value),
                (false, Some(Align::Right), Some(w), _) => {
                    format!($right_zero_width, value = value, w = w)
                }
                (true, Some(Align::Right), Some(w), _) => {
                    format!($alternate_right_zero_width, value = value, w = w)
                }
                (false, Some(Align::Right), None, Some(w)) => {
                    format!($right, value = value, w = w)
                }
                (true, Some(Align::Right), None, Some(w)) => {
                    format!($alternate_right, value = value, w = w)
                }
                (false, Some(Align::Right), None, None) => format!($plain, value = value),
                (true, Some(Align::Right), None, None) => format!($alternate, value = value),
                (false, Some(Align::Center), Some(w), _) => {
                    format!($center_zero_width, value = value, w = w)
                }
                (true, Some(Align::Center), Some(w), _) => {
                    format!($alternate_center_zero_width, value = value, w = w)
                }
                (false, Some(Align::Center), None, Some(w)) => {
                    format!($center, value = value, w = w)
                }
                (true, Some(Align::Center), None, Some(w)) => {
                    format!($alternate_center, value = value, w = w)
                }
                (false, Some(Align::Center), None, None) => format!($plain, value = value),
                (true, Some(Align::Center), None, None) => format!($alternate, value = value),
            },
        )
    }};
}

fn render_radix_value<T>(value: T, spec: &Spec) -> Option<String>
where
    T: std::fmt::Binary
        + std::fmt::Debug
        + std::fmt::LowerHex
        + std::fmt::Octal
        + std::fmt::UpperHex
        + Copy,
{
    if spec.precision.is_some() || spec.plus {
        return None;
    }

    match spec.kind {
        Kind::LowerHex => render_radix_kind!(
            value,
            spec,
            plain: "{value:x}",
            alternate: "{value:#x}",
            width: "{value:w$x}",
            alternate_width: "{value:#w$x}",
            zero_width: "{value:0w$x}",
            alternate_zero_width: "{value:#0w$x}",
            left: "{value:<w$x}",
            alternate_left: "{value:<#w$x}",
            left_zero_width: "{value:<0w$x}",
            alternate_left_zero_width: "{value:<#0w$x}",
            right: "{value:>w$x}",
            alternate_right: "{value:>#w$x}",
            right_zero_width: "{value:>0w$x}",
            alternate_right_zero_width: "{value:>#0w$x}",
            center: "{value:^w$x}",
            alternate_center: "{value:^#w$x}",
            center_zero_width: "{value:^0w$x}",
            alternate_center_zero_width: "{value:^#0w$x}",
        ),
        Kind::LowerHexDebug => render_radix_kind!(
            value,
            spec,
            plain: "{value:x?}",
            alternate: "{value:#x?}",
            width: "{value:w$x?}",
            alternate_width: "{value:#w$x?}",
            zero_width: "{value:0w$x?}",
            alternate_zero_width: "{value:#0w$x?}",
            left: "{value:<w$x?}",
            alternate_left: "{value:<#w$x?}",
            left_zero_width: "{value:<0w$x?}",
            alternate_left_zero_width: "{value:<#0w$x?}",
            right: "{value:>w$x?}",
            alternate_right: "{value:>#w$x?}",
            right_zero_width: "{value:>0w$x?}",
            alternate_right_zero_width: "{value:>#0w$x?}",
            center: "{value:^w$x?}",
            alternate_center: "{value:^#w$x?}",
            center_zero_width: "{value:^0w$x?}",
            alternate_center_zero_width: "{value:^#0w$x?}",
        ),
        Kind::UpperHex => render_radix_kind!(
            value,
            spec,
            plain: "{value:X}",
            alternate: "{value:#X}",
            width: "{value:w$X}",
            alternate_width: "{value:#w$X}",
            zero_width: "{value:0w$X}",
            alternate_zero_width: "{value:#0w$X}",
            left: "{value:<w$X}",
            alternate_left: "{value:<#w$X}",
            left_zero_width: "{value:<0w$X}",
            alternate_left_zero_width: "{value:<#0w$X}",
            right: "{value:>w$X}",
            alternate_right: "{value:>#w$X}",
            right_zero_width: "{value:>0w$X}",
            alternate_right_zero_width: "{value:>#0w$X}",
            center: "{value:^w$X}",
            alternate_center: "{value:^#w$X}",
            center_zero_width: "{value:^0w$X}",
            alternate_center_zero_width: "{value:^#0w$X}",
        ),
        Kind::UpperHexDebug => render_radix_kind!(
            value,
            spec,
            plain: "{value:X?}",
            alternate: "{value:#X?}",
            width: "{value:w$X?}",
            alternate_width: "{value:#w$X?}",
            zero_width: "{value:0w$X?}",
            alternate_zero_width: "{value:#0w$X?}",
            left: "{value:<w$X?}",
            alternate_left: "{value:<#w$X?}",
            left_zero_width: "{value:<0w$X?}",
            alternate_left_zero_width: "{value:<#0w$X?}",
            right: "{value:>w$X?}",
            alternate_right: "{value:>#w$X?}",
            right_zero_width: "{value:>0w$X?}",
            alternate_right_zero_width: "{value:>#0w$X?}",
            center: "{value:^w$X?}",
            alternate_center: "{value:^#w$X?}",
            center_zero_width: "{value:^0w$X?}",
            alternate_center_zero_width: "{value:^#0w$X?}",
        ),
        Kind::Binary => render_radix_kind!(
            value,
            spec,
            plain: "{value:b}",
            alternate: "{value:#b}",
            width: "{value:w$b}",
            alternate_width: "{value:#w$b}",
            zero_width: "{value:0w$b}",
            alternate_zero_width: "{value:#0w$b}",
            left: "{value:<w$b}",
            alternate_left: "{value:<#w$b}",
            left_zero_width: "{value:<0w$b}",
            alternate_left_zero_width: "{value:<#0w$b}",
            right: "{value:>w$b}",
            alternate_right: "{value:>#w$b}",
            right_zero_width: "{value:>0w$b}",
            alternate_right_zero_width: "{value:>#0w$b}",
            center: "{value:^w$b}",
            alternate_center: "{value:^#w$b}",
            center_zero_width: "{value:^0w$b}",
            alternate_center_zero_width: "{value:^#0w$b}",
        ),
        Kind::Octal => render_radix_kind!(
            value,
            spec,
            plain: "{value:o}",
            alternate: "{value:#o}",
            width: "{value:w$o}",
            alternate_width: "{value:#w$o}",
            zero_width: "{value:0w$o}",
            alternate_zero_width: "{value:#0w$o}",
            left: "{value:<w$o}",
            alternate_left: "{value:<#w$o}",
            left_zero_width: "{value:<0w$o}",
            alternate_left_zero_width: "{value:<#0w$o}",
            right: "{value:>w$o}",
            alternate_right: "{value:>#w$o}",
            right_zero_width: "{value:>0w$o}",
            alternate_right_zero_width: "{value:>#0w$o}",
            center: "{value:^w$o}",
            alternate_center: "{value:^#w$o}",
            center_zero_width: "{value:^0w$o}",
            alternate_center_zero_width: "{value:^#0w$o}",
        ),
        _ => None,
    }
}

fn render_int_radix(value: i128, suffix: IntKind, spec: &Spec) -> Option<String> {
    match suffix {
        IntKind::I8 => render_radix_value(value as i8, spec),
        IntKind::U8 => render_radix_value(value as u8, spec),
        IntKind::I16 => render_radix_value(value as i16, spec),
        IntKind::U16 => render_radix_value(value as u16, spec),
        IntKind::I32 | IntKind::Unsuffixed => render_radix_value(value as i32, spec),
        IntKind::U32 => render_radix_value(value as u32, spec),
        IntKind::I64 => render_radix_value(value as i64, spec),
        IntKind::U64 => render_radix_value(value as u64, spec),
        IntKind::I128 => render_radix_value(value, spec),
        IntKind::U128 => render_radix_value(value as u128, spec),
        IntKind::Isize => render_radix_value(value as isize, spec),
        IntKind::Usize => render_radix_value(value as usize, spec),
    }
}

fn render_int(value: i128, suffix: IntKind, spec: &Spec) -> Option<String> {
    // Precision is meaningless for integer Display/radix in rust (it's ignored for
    // integers except `e`/`E`). We bail if a precision is set on a non-exp integer
    // spec to avoid guessing.
    let unsigned = is_unsigned(suffix);
    // Render the body via the real formatter, honoring sign for Display/Debug.
    let body = match spec.kind {
        Kind::Display => {
            if spec.precision.is_some() {
                return None; // precision on an integer Display — bail (no faithful arm)
            }
            return Some(render_i128_display(value, spec));
        }
        Kind::Debug => {
            if spec.precision.is_some() {
                return None;
            }
            match (spec.alternate, spec.plus) {
                (false, _) => return render_i128_debug(value, spec),
                (true, false)
                    if spec.align.is_none()
                        && spec.width.is_none()
                        && spec.zero_width.is_none() =>
                {
                    format!("{value:#?}")
                }
                (true, true) => return None,
                (true, false) => return None,
            }
        }
        // Radix formats belong to the typed integer floor. Preserve the literal's
        // concrete width, then let Rust's formatter produce the bytes.
        Kind::LowerHex
        | Kind::LowerHexDebug
        | Kind::UpperHex
        | Kind::UpperHexDebug
        | Kind::Binary
        | Kind::Octal => return render_int_radix(value, suffix, spec),
        Kind::LowerExp | Kind::UpperExp => {
            if spec.alternate || spec.align.is_some() {
                return None;
            }
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
        Kind::Pointer => return None,
    };
    Some(match (spec.zero_width, spec.width) {
        (Some(w), _) => zero_pad(body, w),
        (None, Some(w)) => format!("{body:>w$}"),
        (None, None) => body,
    })
}

fn is_unsigned(suffix: IntKind) -> bool {
    matches!(
        suffix,
        IntKind::U8 | IntKind::U16 | IntKind::U32 | IntKind::U64 | IntKind::U128 | IntKind::Usize
    )
}

fn render_float_f64(x: f64, spec: &Spec) -> Option<String> {
    if spec.align.is_some() {
        return None;
    }
    // CRITICAL: Display (`{}`) and Debug (`{:?}`) DIFFER for floats -- Debug always shows
    // a decimal point (`0.0`, `-3.0`) and switches to exponential outside [1e-4, 1e16)
    // (`1e16`, `9e-5`), while Display does not. Each dispatches to its OWN real `format!`;
    // collapsing them (rendering Debug via Display) is a fake string -> false refutation.
    let body = match (spec.kind, spec.precision, spec.plus, spec.alternate) {
        (Kind::Display, None, false, false) => format!("{x}"),
        (Kind::Display, None, true, false) => format!("{x:+}"),
        (Kind::Display, Some(p), false, false) => format!("{x:.p$}"),
        (Kind::Display, Some(p), true, false) => format!("{x:+.p$}"),
        (Kind::Debug, None, false, false) => format!("{x:?}"),
        (Kind::Debug, None, true, false) => format!("{x:+?}"),
        (Kind::Debug, Some(p), false, false) => format!("{x:.p$?}"),
        (Kind::Debug, Some(p), true, false) => format!("{x:+.p$?}"),
        (Kind::Debug, None, false, true) => format!("{x:#?}"),
        (Kind::LowerExp, None, false, false) => format!("{x:e}"),
        (Kind::LowerExp, Some(p), false, false) => format!("{x:.p$e}"),
        (Kind::UpperExp, None, false, false) => format!("{x:E}"),
        (Kind::UpperExp, Some(p), false, false) => format!("{x:.p$E}"),
        (Kind::LowerExp, None, true, false) => format!("{x:+e}"),
        (Kind::LowerExp, Some(p), true, false) => format!("{x:+.p$e}"),
        (Kind::UpperExp, None, true, false) => format!("{x:+E}"),
        (Kind::UpperExp, Some(p), true, false) => format!("{x:+.p$E}"),
        // radix on a float is a type error in rust — bail.
        _ => return None,
    };
    Some(match (spec.zero_width, spec.width) {
        (Some(w), _) => zero_pad(body, w),
        (None, Some(w)) => format!("{body:>w$}"),
        (None, None) => body,
    })
}

fn render_float_f32(x: f32, spec: &Spec) -> Option<String> {
    if spec.align.is_some() {
        return None;
    }
    // See `render_float_f64`: Display and Debug differ for floats; render each through
    // its own real `format!`, never collapse Debug onto Display.
    let body = match (spec.kind, spec.precision, spec.plus, spec.alternate) {
        (Kind::Display, None, false, false) => format!("{x}"),
        (Kind::Display, None, true, false) => format!("{x:+}"),
        (Kind::Display, Some(p), false, false) => format!("{x:.p$}"),
        (Kind::Display, Some(p), true, false) => format!("{x:+.p$}"),
        (Kind::Debug, None, false, false) => format!("{x:?}"),
        (Kind::Debug, None, true, false) => format!("{x:+?}"),
        (Kind::Debug, Some(p), false, false) => format!("{x:.p$?}"),
        (Kind::Debug, Some(p), true, false) => format!("{x:+.p$?}"),
        (Kind::Debug, None, false, true) => format!("{x:#?}"),
        (Kind::LowerExp, None, false, false) => format!("{x:e}"),
        (Kind::LowerExp, Some(p), false, false) => format!("{x:.p$e}"),
        (Kind::UpperExp, None, false, false) => format!("{x:E}"),
        (Kind::UpperExp, Some(p), false, false) => format!("{x:.p$E}"),
        (Kind::LowerExp, None, true, false) => format!("{x:+e}"),
        (Kind::LowerExp, Some(p), true, false) => format!("{x:+.p$e}"),
        (Kind::UpperExp, None, true, false) => format!("{x:+E}"),
        (Kind::UpperExp, Some(p), true, false) => format!("{x:+.p$E}"),
        _ => return None,
    };
    Some(match (spec.zero_width, spec.width) {
        (Some(w), _) => zero_pad(body, w),
        (None, Some(w)) => format!("{body:>w$}"),
        (None, None) => body,
    })
}

fn render_char(c: char, spec: &Spec) -> Option<String> {
    if spec.plus {
        return None;
    }
    match (spec.kind, spec.precision, spec.alternate) {
        (Kind::Display, None, false) => Some(render_char_display_floor(c, spec)),
        (Kind::Debug, None, false) => Some(render_char_debug_floor(c, spec)),
        (Kind::Debug, None, true)
            if spec.align.is_none() && spec.width.is_none() && spec.zero_width.is_none() =>
        {
            Some(format!("{c:#?}"))
        }
        // A char in a radix prints its code point. The corpus does not do this; bail to
        // be safe rather than guess width semantics.
        _ => None,
    }
}

fn render_str(s: &str, spec: &Spec) -> Option<String> {
    if spec.plus {
        return None; // sign/zero-pad meaningless for &str
    }
    match (spec.kind, spec.alternate, spec.precision, spec.width) {
        (Kind::Display, false, None, _) => Some(render_str_display_floor(s, spec)),
        (Kind::Display, false, Some(p), width) => {
            if spec.align.is_some() || spec.zero_width.is_some() {
                return None;
            }
            let truncated: String = s.chars().take(p).collect();
            Some(match width {
                Some(w) => format!("{truncated:<w$}"),
                None => truncated,
            })
        }
        (Kind::Debug, false, None, _) => Some(render_str_debug_floor(s, spec)),
        (Kind::Debug, true, None, None) if spec.align.is_none() && spec.zero_width.is_none() => {
            Some(format!("{s:#?}"))
        }
        _ => None,
    }
}

fn render_byte_str(bytes: &[u8], spec: &Spec) -> Option<String> {
    if spec.plus || spec.alternate || spec.precision.is_some() || spec.align.is_some() {
        return None;
    }
    match spec.kind {
        Kind::Debug | Kind::LowerHexDebug | Kind::UpperHexDebug => {
            let mut rendered = Vec::with_capacity(bytes.len());
            for byte in bytes {
                rendered.push(render_byte_str_element(*byte, spec)?);
            }
            Some(format!("[{}]", rendered.join(", ")))
        }
        _ => None,
    }
}

fn render_byte_str_element(byte: u8, spec: &Spec) -> Option<String> {
    Some(match (spec.kind, spec.zero_width, spec.width) {
        (Kind::Debug, Some(w), _) => format!("{byte:0w$?}"),
        (Kind::Debug, None, Some(w)) => format!("{byte:w$?}"),
        (Kind::Debug, None, None) => format!("{byte:?}"),
        (Kind::LowerHexDebug, Some(w), _) => format!("{byte:0w$x}"),
        (Kind::LowerHexDebug, None, Some(w)) => format!("{byte:w$x}"),
        (Kind::LowerHexDebug, None, None) => format!("{byte:x}"),
        (Kind::UpperHexDebug, Some(w), _) => format!("{byte:0w$X}"),
        (Kind::UpperHexDebug, None, Some(w)) => format!("{byte:w$X}"),
        (Kind::UpperHexDebug, None, None) => format!("{byte:X}"),
        _ => return None,
    })
}

fn render_cstr(bytes: &CStrBytes, spec: &Spec) -> String {
    if spec.kind != Kind::Debug
        || spec.plus
        || spec.align.is_some()
        || spec.width.is_some()
        || spec.zero_width.is_some()
        || spec.precision.is_some()
    {
        panic!("CStr reached a non-Debug formatter; rustc would reject this source")
    }
    let value = CStr::from_bytes_with_nul(bytes.with_nul())
        .unwrap_or_else(|_| panic!("LiteralCStrFloor carried invalid C string bytes"));
    if spec.alternate {
        format!("{value:#?}")
    } else {
        format!("{value:?}")
    }
}

fn render_bool(b: bool, spec: &Spec) -> Option<String> {
    if spec.plus || spec.zero_width.is_some() || spec.precision.is_some() {
        return None;
    }
    match (spec.kind, spec.alternate) {
        (Kind::Display, false) => Some(render_bool_display_floor(b, spec)),
        (Kind::Debug, false) => Some(render_bool_debug_floor(b, spec)),
        (Kind::Debug, true)
            if spec.align.is_none() && spec.width.is_none() && spec.zero_width.is_none() =>
        {
            Some(format!("{b:#?}"))
        }
        _ => None,
    }
}

// ── Reconstruct a typed literal value from the source AST ─────────────────────────

/// Resolve an argument expr to a `FmtValue` (a typed literal), composing through
/// `let`/`const` bindings and unary negation / `inf`-`NaN`-shaped float divisions (the
/// flt2dec corpus shape). `Ok(None)` means this helper did not resolve the value by
/// itself; constructed Sugar must gap or bubble a child effect instead of inventing a
/// local format effect. `Err(reason)` is an unsupported render path.
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
        // Closed arithmetic over literal operands. This composes through `let`/`const`
        // indirections (each operand is resolved recursively), so it is the natural
        // completion of the unary-negation / float-division folds above.
        Expr::Binary(b) if is_fmt_arith_op(&b.op) => {
            let l = resolve_fmt_value(&b.left, binds)?;
            let r = resolve_fmt_value(&b.right, binds)?;
            // Integer `+ - * / %` of two reconstructed integer literals CONSTANT-FOLDS
            // (recompute-don't-trust) with CHECKED, width-aware semantics. A mixed-width
            // pair / i128-carrier overflow / divide-by-zero / result outside the type's
            // range BAILS to the factory gap path, never forging a wrapped value for an
            // expression real rust would panic on.
            if let (
                Some(FmtValue::Int {
                    value: lv,
                    suffix: ls,
                }),
                Some(FmtValue::Int {
                    value: rv,
                    suffix: rs,
                }),
            ) = (&l, &r)
            {
                return Ok(fold_int_arith(&b.op, *lv, *ls, *rv, *rs)
                    .map(|(value, suffix)| FmtValue::Int { value, suffix }));
            }
            // float division of two literals: `1.0 / 0.0` = inf, `0.0 / 0.0` = NaN, etc.
            if matches!(b.op, syn::BinOp::Div(_)) {
                return Ok(match (l, r) {
                    (Some(FmtValue::F64(lf)), Some(FmtValue::F64(rf))) => {
                        Some(FmtValue::F64(lf / rf))
                    }
                    (Some(FmtValue::F32(lf)), Some(FmtValue::F32(rf))) => {
                        Some(FmtValue::F32(lf / rf))
                    }
                    _ => None,
                });
            }
            // A string `+` (`String + &str`) is NOT arithmetic; defer to the string
            // concatenation resolver so `format!("{}", a + b)` over STRING operands keeps
            // resolving exactly as before (no regression for the string-add-as-arg path).
            if matches!(b.op, syn::BinOp::Add(_)) {
                return Ok(
                    resolve_format_string(strip_refs_groups(expr), binds)?.map(FmtValue::Str)
                );
            }
            Ok(None)
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

/// The integer/float arithmetic binary operators we constant-fold over literal
/// operands (`+ - * / %`). A string `+` shares the `Add` token but is handled as
/// concatenation, not arithmetic.
fn is_fmt_arith_op(op: &syn::BinOp) -> bool {
    matches!(
        op,
        syn::BinOp::Add(_)
            | syn::BinOp::Sub(_)
            | syn::BinOp::Mul(_)
            | syn::BinOp::Div(_)
            | syn::BinOp::Rem(_)
    )
}

/// Legacy helper wrapper for checked integer formatting arithmetic. The constructed
/// sugar path calls `fold_int_arith_for_format` so it can distinguish a real
/// non-text-determined arithmetic boundary from a compiler-impossible operand mix.
fn fold_int_arith(
    op: &syn::BinOp,
    lv: i128,
    ls: IntKind,
    rv: i128,
    rs: IntKind,
) -> Option<(i128, IntKind)> {
    fold_int_arith_for_format(op, lv, ls, rv, rs).ok()
}

fn fold_int_arith_for_format(
    op: &syn::BinOp,
    lv: i128,
    ls: IntKind,
    rv: i128,
    rs: IntKind,
) -> Result<(i128, IntKind), String> {
    let Some(suffix) = reconcile_int_suffix(ls, rs) else {
        return Err(
            "format integer arithmetic operands have incompatible primitive widths; rustc would reject this source"
                .to_string(),
        );
    };
    // `u128` near its top cannot be represented in the signed i128 carrier — bail rather
    // than risk a wrapped reconstruction.
    if matches!(suffix, IntKind::U128) {
        return Err(format_int_arith_boundary());
    }
    let result = match op {
        syn::BinOp::Add(_) => lv.checked_add(rv),
        syn::BinOp::Sub(_) => lv.checked_sub(rv),
        syn::BinOp::Mul(_) => lv.checked_mul(rv),
        // integer `/` and `%` truncate toward zero (i128 matches); div/rem by zero and
        // `MIN / -1` overflow both bail via the zero guard + `checked_*`.
        syn::BinOp::Div(_) => {
            if rv == 0 {
                return Err(format_int_arith_boundary());
            }
            lv.checked_div(rv)
        }
        syn::BinOp::Rem(_) => {
            if rv == 0 {
                return Err(format_int_arith_boundary());
            }
            lv.checked_rem(rv)
        }
        _ => {
            return Err("format integer arithmetic is not supported for this operator".to_string());
        }
    }
    .ok_or_else(format_int_arith_boundary)?;
    let Some((min, max)) = int_value_range(suffix) else {
        return Err(format_int_arith_boundary());
    };
    if result < min || result > max {
        return Err(format_int_arith_boundary());
    }
    Ok((result, suffix))
}

fn format_int_arith_boundary() -> String {
    "format integer arithmetic overflow or divide-by-zero, not literal-determined; refused"
        .to_string()
}

/// Reconcile the width suffix of two arithmetic operands. Equal kinds keep their kind;
/// an `Unsuffixed` operand takes the other's kind (rust's literal-inference default);
/// two DISTINCT concrete widths cannot be combined (not a valid rust expr) → `None`.
fn reconcile_int_suffix(a: IntKind, b: IntKind) -> Option<IntKind> {
    match (a, b) {
        (x, y) if x == y => Some(x),
        (IntKind::Unsuffixed, y) => Some(y),
        (x, IntKind::Unsuffixed) => Some(x),
        _ => None,
    }
}

/// The inclusive `[min, max]` value range of an integer kind, as `i128`. `Unsuffixed`
/// defaults to `i32` (rust's default). `Isize`/`Usize` are modeled at 64 bits, matching
/// `bits_at_width` and the corpus's 64-bit target. `U128` is excluded by the caller.
fn int_value_range(suffix: IntKind) -> Option<(i128, i128)> {
    let range = match suffix {
        IntKind::I8 => (i128::from(i8::MIN), i128::from(i8::MAX)),
        IntKind::I16 => (i128::from(i16::MIN), i128::from(i16::MAX)),
        IntKind::I32 | IntKind::Unsuffixed => (i128::from(i32::MIN), i128::from(i32::MAX)),
        IntKind::I64 | IntKind::Isize => (i128::from(i64::MIN), i128::from(i64::MAX)),
        IntKind::I128 => (i128::MIN, i128::MAX),
        IntKind::U8 => (0, i128::from(u8::MAX)),
        IntKind::U16 => (0, i128::from(u16::MAX)),
        IntKind::U32 => (0, i128::from(u32::MAX)),
        IntKind::U64 | IntKind::Usize => (0, i128::from(u64::MAX)),
        IntKind::U128 => return None,
    };
    Some(range)
}

/// Reconstruct a single literal token into a `FmtValue`. `Err` for f16/f128 (named
/// terminal); `Ok(None)` for byte-strings / other unsupported literal kinds (bail).
fn reconstruct_lit(lit: &Lit) -> Result<Option<FmtValue>, String> {
    match lit {
        Lit::Int(i) => {
            if i.suffix() == "f32" {
                return Ok(i.base10_digits().parse::<f32>().ok().map(FmtValue::F32));
            }
            if i.suffix() == "f64" {
                return Ok(i.base10_digits().parse::<f64>().ok().map(FmtValue::F64));
            }
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
        Lit::ByteStr(bytes) => Ok(Some(FmtValue::ByteStr(bytes.value()))),
        Lit::Bool(b) => Ok(Some(FmtValue::Bool(b.value))),
        // a byte literal `b'0'` is a u8.
        Lit::Byte(b) => Ok(Some(FmtValue::Int {
            value: i128::from(b.value()),
            suffix: IntKind::U8,
        })),
        _ => Ok(None),
    }
}

/// The in-scope IMMUTABLE `let` bindings (`name -> init`), the map the format reducer
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
// each one IS a `format!` rendering of the value — so the format reducer, the single
// format authority, computes them HERE with the lifter's own stdlib `format!` (recompute-
// don't-reimplement), exactly as it computes a `format!("{}", x)`. The flt2dec
// recognizer (lib.rs `dissolve_flt2dec_assert`) reconstructs the `(value, sign, mode,
// digits)` operands and calls these functions; the float-formatting computation lives
// here, in the format reducer, not in a separate float-only module.
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
// rendering the value through the format float engine above and comparing to the
// asserted literal (`dissolve_flt2dec_assert`). `lift_flt2dec_helper` is the single
// entry lib.rs `visit_non_test_fn` calls; the format reducer owns the entire feature.

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
            if crate::macro_is_assertion_surface(m) {
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
    use sugar_ir_symbolic::num;

    use crate::{
        sugar_ctx, Desugared, FloatWidthScope, LiftOptions, ReductionCtx, TemporalPlan,
        TemporalScope,
    };

    fn parse(src: &str) -> Expr {
        syn::parse_str(src).expect("expr parses")
    }
    fn no_binds() -> BTreeMap<String, Expr> {
        BTreeMap::new()
    }
    fn resolve(src: &str) -> Result<Option<String>, String> {
        let expr = parse(src);
        if is_format_shape(&expr) {
            resolve_format_string(&expr, &no_binds())
        } else {
            Ok(None)
        }
    }
    fn resolve_with_binds(
        src: &str,
        binds: &BTreeMap<String, Expr>,
    ) -> Result<Option<String>, String> {
        let expr = parse(src);
        if is_format_shape(&expr) {
            resolve_format_string(&expr, binds)
        } else {
            Ok(None)
        }
    }

    fn panic_text(payload: &(dyn std::any::Any + Send)) -> String {
        if let Some(text) = payload.downcast_ref::<String>() {
            text.clone()
        } else if let Some(text) = payload.downcast_ref::<&'static str>() {
            text.to_string()
        } else {
            "<non-string panic>".to_string()
        }
    }

    #[test]
    fn render_format_values_parse_panic_names_template_and_source_memento() {
        let panic = std::panic::catch_unwind(|| {
            let _ = render_format_values(
                "{:.*}",
                &[],
                &BTreeMap::new(),
                &BTreeMap::new(),
                "format!(\"{:.*}\", 2, 1.0)",
            );
        })
        .expect_err("parse-rejected compiled format template should panic");
        let message = panic_text(panic.as_ref());

        assert!(
            message.contains("compiled format template did not parse"),
            "{message}"
        );
        assert!(message.contains("template=\"{:.*}\""), "{message}");
        assert!(
            message.contains("source_memento=format!(\"{:.*}\", 2, 1.0)"),
            "{message}"
        );
    }

    #[test]
    fn format_value_dispatches_completed_int_term_floor() {
        let value = format_value_from_term_floor(&num(5), "test");
        assert_eq!(
            value.render(&Spec::parse("?").unwrap()).unwrap().as_deref(),
            Some("5")
        );
    }

    #[test]
    fn format_value_dispatches_completed_inclusive_range_term_floor() {
        let value = format_value_from_term_floor(
            &Rc::new(Term::Ctor {
                name: "range_incl".to_string(),
                args: vec![num(1), num(1)],
            }),
            "test",
        );
        assert_eq!(
            value.render(&Spec::parse("?").unwrap()).unwrap().as_deref(),
            Some("1..=1")
        );
    }

    #[test]
    fn format_value_dispatches_replayed_inclusive_range_skip_floor() {
        let value = format_value_from_term_floor(
            &Rc::new(Term::Ctor {
                name: "method:skip".to_string(),
                args: vec![
                    Rc::new(Term::Ctor {
                        name: "range_incl".to_string(),
                        args: vec![num(1), num(1)],
                    }),
                    num(1),
                ],
            }),
            "test",
        );
        assert_eq!(
            value.render(&Spec::parse("?").unwrap()).unwrap().as_deref(),
            Some("1..=1 (exhausted)")
        );
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
    fn bare_width_and_sign_padding_int() {
        assert_eq!(
            resolve(r#"format!("{:+5}", 1)"#).unwrap().as_deref(),
            Some("   +1")
        );
        assert_eq!(
            resolve(r#"format!("{:+5}", -1)"#).unwrap().as_deref(),
            Some("   -1")
        );
        assert_eq!(
            resolve(r#"format!("{:+05}", 1)"#).unwrap().as_deref(),
            Some("+0001")
        );
        assert_eq!(
            resolve(r#"format!("{:+05}", -1)"#).unwrap().as_deref(),
            Some("-0001")
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
    fn byte_string_hex_debug_dispatches_on_byte_floor() {
        assert_eq!(
            resolve(r#"format!("{:02x?}", b"Foo\0")"#)
                .unwrap()
                .as_deref(),
            Some("[46, 6f, 6f, 00]")
        );
        assert_eq!(
            resolve(r#"format!("{:02X?}", b"Foo\0")"#)
                .unwrap()
                .as_deref(),
            Some("[46, 6F, 6F, 00]")
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
            resolve_with_binds(r#"format!("{max}")"#, &binds)
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
    fn default_alignment_delegates_to_format_floor() {
        assert_eq!(
            resolve(r#"format!("{:>9}", 1)"#).unwrap().as_deref(),
            Some("        1")
        );
        assert_eq!(
            resolve(r#"format!("{:^9?}", 1)"#).unwrap().as_deref(),
            Some("    1    ")
        );
    }

    #[test]
    fn explicit_arbitrary_fill_alignment_width_lifts() {
        assert_eq!(
            resolve(r#"format!("{:*>9}", 1)"#).unwrap().as_deref(),
            Some("********1")
        );
        assert_eq!(
            resolve(r#"format!("{:x^9?}", 1)"#).unwrap().as_deref(),
            Some("xxxx1xxxx")
        );
        assert_eq!(
            resolve(r#"format!("{:_<5}", "a")"#).unwrap().as_deref(),
            Some("a____")
        );
        assert_eq!(
            resolve(r#"format!("{: >3}", 'a')"#).unwrap().as_deref(),
            Some("  a")
        );
        assert_eq!(
            resolve(r#"format!("{:*^8?}", "hi")"#).unwrap().as_deref(),
            Some(r#"**"hi"**"#)
        );
    }

    #[test]
    fn parses_left_align_zero_width_template_for_format_floor() {
        let mut captures = BTreeMap::new();
        captures.insert(
            "Bar".to_string(),
            FmtValue::Int {
                value: 1,
                suffix: IntKind::Unsuffixed,
            },
        );

        match render_format_values(
            "{Bar:<03}",
            &[],
            &BTreeMap::new(),
            &captures,
            r#"format!("{Bar:<03}")"#,
        ) {
            FloorRead::Complete(value) => assert_eq!(value, "001"),
            FloorRead::Incomplete(effect) => panic!("unexpected effect: {}", effect.reason()),
        }
        assert_eq!(
            resolve(r#"format!("{:<03}", 1)"#).unwrap().as_deref(),
            Some("001")
        );
        assert_eq!(
            resolve(r#"format!("{:<03}", "a")"#).unwrap().as_deref(),
            Some("a  ")
        );
    }

    #[test]
    fn alternate_debug_delegates_to_literal_floors() {
        assert_eq!(
            resolve(r#"format!("{:#?}", 1)"#).unwrap().as_deref(),
            Some("1")
        );
        assert_eq!(
            resolve(r#"format!("{:#?}", "hi")"#).unwrap().as_deref(),
            Some("\"hi\"")
        );
        assert_eq!(
            resolve(r#"format!("{:#?}", true)"#).unwrap().as_deref(),
            Some("true")
        );
        assert_eq!(
            resolve(r#"format!("{:#?}", 'x')"#).unwrap().as_deref(),
            Some("'x'")
        );
    }

    #[test]
    fn alternate_display_int_delegates_to_literal_floor() {
        match render_format_values(
            "{:#}",
            &[FmtValue::Int {
                value: 1,
                suffix: IntKind::Unsuffixed,
            }],
            &BTreeMap::new(),
            &BTreeMap::new(),
            r#"format!("{:#}", 1)"#,
        ) {
            FloorRead::Complete(value) => assert_eq!(value, "1"),
            FloorRead::Incomplete(effect) => panic!("unexpected effect: {}", effect.reason()),
        }
        assert_eq!(
            resolve(r#"format!("{:#}", 1)"#).unwrap().as_deref(),
            Some("1")
        );
    }

    #[test]
    fn alternate_lower_hex_int_delegates_to_literal_floor() {
        match render_format_values(
            "{:#x}",
            &[FmtValue::Int {
                value: 10,
                suffix: IntKind::Unsuffixed,
            }],
            &BTreeMap::new(),
            &BTreeMap::new(),
            r#"format!("{:#x}", 10)"#,
        ) {
            FloorRead::Complete(value) => assert_eq!(value, "0xa"),
            FloorRead::Incomplete(effect) => panic!("unexpected effect: {}", effect.reason()),
        }
        assert_eq!(
            resolve(r#"format!("{:#x}", 10)"#).unwrap().as_deref(),
            Some("0xa")
        );
    }

    #[test]
    fn alternate_radix_delegates_to_literal_floors() {
        assert_eq!(
            resolve(r#"format!("{:#x}", 255u32)"#).unwrap().as_deref(),
            Some("0xff")
        );
        assert_eq!(
            resolve(r#"format!("{:#x}", -1i8)"#).unwrap().as_deref(),
            Some("0xff")
        );
    }

    #[test]
    fn aligned_radix_int_delegates_to_literal_floor() {
        match render_format_values(
            "{:<8x}",
            &[FmtValue::Int {
                value: 10,
                suffix: IntKind::Unsuffixed,
            }],
            &BTreeMap::new(),
            &BTreeMap::new(),
            r#"format!("{:<8x}", 10)"#,
        ) {
            FloorRead::Complete(value) => assert_eq!(value, "a       "),
            FloorRead::Incomplete(effect) => panic!("unexpected effect: {}", effect.reason()),
        }

        assert_eq!(
            resolve(r#"format!("{:<8x}", 10)"#).unwrap().as_deref(),
            Some("a       ")
        );
        assert_eq!(
            resolve(r#"format!("{:>8x}", 10)"#).unwrap().as_deref(),
            Some("       a")
        );
        assert_eq!(
            resolve(r#"format!("{:^8x}", 10)"#).unwrap().as_deref(),
            Some("   a    ")
        );
        assert_eq!(
            resolve(r#"format!("{:<#8x}", 10)"#).unwrap().as_deref(),
            Some("0xa     ")
        );
        assert_eq!(
            resolve(r#"format!("{:<8x}", -1i8)"#).unwrap().as_deref(),
            Some("ff      ")
        );
        assert_eq!(
            resolve(r#"format!("{:>8X}", 10)"#).unwrap().as_deref(),
            Some("       A")
        );
        assert_eq!(
            resolve(r#"format!("{:^8b}", 10)"#).unwrap().as_deref(),
            Some("  1010  ")
        );
        assert_eq!(
            resolve(r#"format!("{:<#8o}", 10)"#).unwrap().as_deref(),
            Some("0o12    ")
        );
        assert_eq!(
            resolve(r#"format!("{:>8X?}", 10)"#).unwrap().as_deref(),
            Some("       A")
        );
    }

    #[test]
    fn format_args_macro_reduces_to_debug_text_format_value() {
        let expr = parse(r#"format_args!("{}/{}", 10, 20)"#);
        let scope = TemporalScope::new("format-args-value-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = build_format_value_body(&expr, &fcx);
        let items = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);

        let Outcome::Complete(Desugared::FormatValue(value)) = node.desugar(&ctx) else {
            panic!("format_args! should complete as a format value floor");
        };

        assert_eq!(
            value.render(&Spec::parse("?").unwrap()).unwrap().as_deref(),
            Some("10/20")
        );
    }

    #[test]
    fn format_args_text_dispatches_bare_width_on_its_floor() {
        let mut captures = BTreeMap::new();
        captures.insert(
            "a".to_string(),
            FmtValue::FormatArgsText("hello".to_string()),
        );

        match render_format_values(
            "hello {a:1}",
            &[],
            &BTreeMap::new(),
            &captures,
            r#"format_args!("hello {a:1}")"#,
        ) {
            FloorRead::Complete(value) => assert_eq!(value, "hello hello"),
            FloorRead::Incomplete(effect) => panic!("unexpected effect: {}", effect.reason()),
        }
    }

    #[test]
    fn pointer_format_bubbles_format_argument_effect() {
        let mut captures = BTreeMap::new();
        captures.insert("s".to_string(), FmtValue::Str(String::new()));

        match render_format_values(
            "{s:p}",
            &[],
            &BTreeMap::new(),
            &captures,
            r#"format!("{s:p}")"#,
        ) {
            FloorRead::Complete(value) => panic!("pointer format should not complete: {value}"),
            FloorRead::Incomplete(effect @ Effect::FormatPointerAddress { .. }) => {
                let reason = effect.reason();
                assert!(reason.contains("runtime address identity"), "{reason}");
            }
            FloorRead::Incomplete(effect) => panic!("unexpected effect: {}", effect.reason()),
        }
    }

    // ── FOLD: closed integer arithmetic over literal operands ──
    #[test]
    fn folds_integer_arithmetic_over_literals() {
        // `+ - * / %` of literal ints constant-fold to ONE text-determined value.
        assert_eq!(
            resolve(r#"format!("{}", 2 + 3)"#).unwrap().as_deref(),
            Some("5")
        );
        assert_eq!(
            resolve(r#"format!("{}", 10 - 4)"#).unwrap().as_deref(),
            Some("6")
        );
        assert_eq!(
            resolve(r#"format!("{}", 6 * 7)"#).unwrap().as_deref(),
            Some("42")
        );
        // integer division truncates toward zero (rust semantics).
        assert_eq!(
            resolve(r#"format!("{}", 17 / 5)"#).unwrap().as_deref(),
            Some("3")
        );
        assert_eq!(
            resolve(r#"format!("{}", 17 % 5)"#).unwrap().as_deref(),
            Some("2")
        );
        assert_eq!(
            resolve(r#"format!("{}", -7 / 2)"#).unwrap().as_deref(),
            Some("-3")
        );
        // composes with unary negation and width suffixes.
        assert_eq!(
            resolve(r#"format!("{}", -3i32 * 4)"#).unwrap().as_deref(),
            Some("-12")
        );
        // nested arithmetic.
        assert_eq!(
            resolve(r#"format!("{}", (1 + 2) * (3 + 4))"#)
                .unwrap()
                .as_deref(),
            Some("21")
        );
        // a radix spec over a folded value still renders at width.
        assert_eq!(
            resolve(r#"format!("{:x}", 200 + 55)"#).unwrap().as_deref(),
            Some("ff")
        );
    }

    #[test]
    fn folds_integer_arithmetic_through_local_bindings() {
        // a text-determined LOCAL operand resolves through the binding map, then folds.
        let binds = bind("n", "2");
        assert_eq!(
            resolve_with_binds(r#"format!("{}", n + 40)"#, &binds)
                .unwrap()
                .as_deref(),
            Some("42")
        );
        // two locals + the `{}-{}` shape (the brief's canonical form), arithmetic per arg.
        let mut two = bind("a", "6");
        two.insert("b".to_string(), parse("7"));
        assert_eq!(
            resolve_with_binds(r#"format!("{}-{}", a * b, b - a)"#, &two)
                .unwrap()
                .as_deref(),
            Some("42-1")
        );
    }

    #[test]
    fn fold_bails_on_overflow_and_divzero_never_forging() {
        // The inverse of teeth: an expression rust would PANIC on (overflow) or that is
        // undefined (div-by-zero) must BAIL (stay opaque), never forge a wrapped value.
        assert_eq!(resolve(r#"format!("{}", 200u8 + 100u8)"#).unwrap(), None); // 300 > u8::MAX
        assert_eq!(
            resolve(r#"format!("{}", 2000000000 + 2000000000)"#).unwrap(),
            None
        ); // > i32::MAX
        assert_eq!(resolve(r#"format!("{}", 1 / 0)"#).unwrap(), None);
        assert_eq!(resolve(r#"format!("{}", 1 % 0)"#).unwrap(), None);
        // a runtime operand keeps the whole fold opaque.
        assert_eq!(resolve(r#"format!("{}", runtime_var + 1)"#).unwrap(), None);
    }

    #[test]
    fn wide_suffixed_arithmetic_folds_within_range() {
        // u64 arithmetic that overflows i32/u32 but fits u64 is still text-determined.
        assert_eq!(
            resolve(r#"format!("{}", 3000000000u64 + 3000000000u64)"#)
                .unwrap()
                .as_deref(),
            Some("6000000000")
        );
    }

    #[test]
    fn string_add_as_format_arg_still_resolves_no_regression() {
        // The `Add` token is shared with string concatenation; a `String + &str` operand
        // must keep resolving via the string path (folding must not intercept it).
        let binds = bind("s", r#""foo".to_string() + "bar""#);
        assert_eq!(
            resolve_with_binds(r#"format!("{}", s)"#, &binds)
                .unwrap()
                .as_deref(),
            Some("foobar")
        );
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

    // ── SHAPE: recognizes the format family, declines foreign ──
    #[test]
    fn format_shape_recognizes_family() {
        assert!(is_format_shape(&parse(r#"format!("{}", 1)"#)));
        assert!(is_format_shape(&parse(r#"concat!("a")"#)));
        assert!(is_format_shape(&parse(r#"x.to_string()"#)));
        assert!(is_format_shape(&parse(r#"a + b"#)));
        // foreign: not a format shape.
        assert!(!is_format_shape(&parse(r#"foo.bar()"#)));
        assert!(!is_format_shape(&parse(r#"vec![1, 2]"#)));
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

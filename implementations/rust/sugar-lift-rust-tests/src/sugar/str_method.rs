// SPDX-License-Identifier: MIT OR Apache-2.0
//
// TERM recognizer for closed stdlib `&str`/`String` methods over written string
// literals: string-producing methods (`.to_ascii_uppercase()`, `.to_ascii_lowercase()`,
// ASCII-gated `.to_uppercase()`/`.to_lowercase()`, `.replace(from, to)`,
// `.trim()`/`.trim_start()`/`.trim_end()`, `.repeat(n)`) plus scalar surfaces
// (`.len()`, `.chars().count()`, `.bytes().count()`, `.is_empty()`,
// `.starts_with(lit)`, `.contains(lit)`). These are PURE functions of text-determined
// strings, so the result dissolves to the literal floor (`Int`/`Bool`/`String`) with real
// z3 teeth, not an opaque `method:*` EUF var.
//
// finite-or-refuse: recognition only captures the raw source site. Resolution happens
// lazily in `desugar`, where the binding context is live. ONLY a literal-resolvable
// receiver/args warrant; runtime/opaque receivers, `format!`-built receivers, oversized
// repeats, or non-ASCII full-case mappings Incomplete the structural frontier — never a
// fabricated value. A structural miss is a factory gap, not an opaque method result.

use std::{collections::BTreeMap, rc::Rc};
use sugar_ir_symbolic::{num, str_const, Term};
use syn::{Expr, ExprLit, ExprMethodCall, Lit};

use crate::sugar::factory::{FloorRead, LiteralStringFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::format::stable_let_bindings;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    bool_const, const_fold_int_term, simple_path_name, strip_refs_groups, token_key, Desugared,
    Effect, Outcome, Sugar, SugarCtx,
};

/// Upper bound on a `.repeat(n)` expansion (bytes). A larger expansion DECLINES rather
/// than materialize a huge string const — a bounded, conservative cap.
const REPEAT_BYTE_CAP: usize = 4096;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "str_method",
        &["iter_terminal", "is_empty", "len"],
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                #[test]
                fn t_str_method_good() {
                    assert_eq!(" hi ".trim(), "hi");
                }
            "#,
            r#"
                #[test]
                fn t_str_method_bad() {
                    assert_eq!(" hi ".trim(), " hi ");
                }
            "#,
        ),
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    let stable = stable_let_bindings(fcx.scope());
    let let_inits = merged_let_inits(&stable, fcx.let_inits());
    let kind = recognized_kind(call, &let_inits)?;
    let receiver = recognized_receiver(call, kind)?.clone();
    Some(Box::new(StrMethodSugar {
        kind,
        receiver_body: SugarBody::literal_string(&receiver, fcx),
        args: recognized_args(call, kind, fcx, &let_inits)?,
    }))
}

#[derive(Clone, Copy)]
enum StrMethodKind {
    String(StringMethodKind),
    Len,
    CharsCount,
    BytesCount,
    IsEmpty,
    StartsWith,
    Contains,
}

#[derive(Clone, Copy)]
enum StringMethodKind {
    ToAsciiUppercase,
    ToAsciiLowercase,
    ToUppercase,
    ToLowercase,
    Replace,
    Trim,
    TrimStart,
    TrimEnd,
    Repeat,
}

struct StrMethodSugar {
    kind: StrMethodKind,
    receiver_body: SugarBody<LiteralStringFloor>,
    args: StrMethodArgs,
}

enum StrMethodArgs {
    None,
    StartsWith {
        needle: SugarBody<LiteralStringFloor>,
    },
    Contains {
        pattern: StrPatternArg,
    },
    Replace {
        from: StrPatternArg,
        to: SugarBody<LiteralStringFloor>,
    },
    Repeat {
        count: SugarBody<TermFloor>,
        count_source: String,
    },
}

enum StrPatternArg {
    String(SugarBody<LiteralStringFloor>),
    Char(char),
}

impl Sugar for StrMethodSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let recv = match self.receiver_body.reduce_literal_string(ctx) {
            FloorRead::Complete(value) => value,
            FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let term = match self.kind {
            StrMethodKind::String(kind) => {
                if matches!(
                    kind,
                    StringMethodKind::ToUppercase | StringMethodKind::ToLowercase
                ) && !recv.is_ascii()
                {
                    return Outcome::Incomplete(Effect::UnicodeStringCase);
                }
                match self.compute_string_kind(kind, recv, ctx) {
                    Ok(value) => str_const(value),
                    Err(outcome) => return outcome,
                }
            }
            StrMethodKind::Len => num(recv.len() as i128),
            StrMethodKind::CharsCount => num(rev_char_count(&recv)),
            StrMethodKind::BytesCount => num(recv.len() as i128),
            StrMethodKind::IsEmpty => bool_const(recv.is_empty()),
            StrMethodKind::StartsWith => {
                let needle = match &self.args {
                    StrMethodArgs::StartsWith { needle } => match needle.reduce_literal_string(ctx)
                    {
                        FloorRead::Complete(value) => value,
                        FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
                    },
                    _ => panic!("str_method starts_with constructed without typed needle"),
                };
                bool_const(recv.starts_with(&needle))
            }
            StrMethodKind::Contains => {
                let needle = match &self.args {
                    StrMethodArgs::Contains { pattern } => match pattern.reduce(ctx) {
                        Ok(value) => value,
                        Err(outcome) => return outcome,
                    },
                    _ => panic!("str_method contains constructed without typed pattern"),
                };
                bool_const(recv.contains(&needle))
            }
        };
        Outcome::Complete(Desugared::Term(term))
    }
}

impl StrMethodSugar {
    fn compute_string_kind(
        &self,
        kind: StringMethodKind,
        recv: String,
        ctx: &SugarCtx,
    ) -> Result<String, Outcome> {
        match kind {
            StringMethodKind::ToAsciiUppercase => Ok(recv.to_ascii_uppercase()),
            StringMethodKind::ToAsciiLowercase => Ok(recv.to_ascii_lowercase()),
            // Unicode full-case mapping: warrant ONLY for an ASCII receiver, where it equals
            // the byte-wise `to_ascii_*` and is Unicode-version-independent. A non-ASCII
            // receiver returns a named incomplete before this arm.
            StringMethodKind::ToUppercase if recv.is_ascii() => Ok(recv.to_uppercase()),
            StringMethodKind::ToLowercase if recv.is_ascii() => Ok(recv.to_lowercase()),
            StringMethodKind::ToUppercase | StringMethodKind::ToLowercase => {
                unreachable!("non-ASCII Unicode case was handled before string computation")
            }
            StringMethodKind::Trim => Ok(recv.trim().to_string()),
            StringMethodKind::TrimStart => Ok(recv.trim_start().to_string()),
            StringMethodKind::TrimEnd => Ok(recv.trim_end().to_string()),
            StringMethodKind::Replace => {
                let (from, to) = match &self.args {
                    StrMethodArgs::Replace { from, to } => {
                        let from = from.reduce(ctx)?;
                        let to = match to.reduce_literal_string(ctx) {
                            FloorRead::Complete(value) => value,
                            FloorRead::Incomplete(effect) => {
                                return Err(Outcome::Incomplete(effect));
                            }
                        };
                        (from, to)
                    }
                    _ => panic!("str_method replace constructed without typed args"),
                };
                Ok(recv.replace(&from, &to))
            }
            StringMethodKind::Repeat => {
                let n = match &self.args {
                    StrMethodArgs::Repeat {
                        count,
                        count_source,
                    } => repeat_count(count, count_source, ctx)?,
                    _ => panic!("str_method repeat constructed without typed count"),
                };
                match recv.len().checked_mul(n) {
                    Some(bytes) if bytes <= REPEAT_BYTE_CAP => Ok(recv.repeat(n)),
                    _ => panic!(
                        "str repeat expansion exceeds finite literal cap; write a streaming string floor before Outcome"
                    ),
                }
            }
        }
    }
}

fn rev_char_count(s: &str) -> i128 {
    s.chars().count() as i128
}

fn recognized_kind(
    call: &ExprMethodCall,
    let_inits: &BTreeMap<String, Expr>,
) -> Option<StrMethodKind> {
    let method = call.method.to_string();
    match method.as_str() {
        "len" if call.args.is_empty() && is_text_receiver_shape(&call.receiver, let_inits) => {
            Some(StrMethodKind::Len)
        }
        "is_empty" if call.args.is_empty() && is_text_receiver_shape(&call.receiver, let_inits) => {
            Some(StrMethodKind::IsEmpty)
        }
        "starts_with"
            if call.args.len() == 1
                && is_text_receiver_shape(&call.args[0], let_inits)
                && is_text_receiver_shape(&call.receiver, let_inits) =>
        {
            Some(StrMethodKind::StartsWith)
        }
        "contains"
            if call.args.len() == 1
                && is_pattern_arg_shape(&call.args[0], let_inits)
                && is_text_receiver_shape(&call.receiver, let_inits) =>
        {
            Some(StrMethodKind::Contains)
        }
        "count" if call.args.is_empty() => recognize_string_iterator_count(call, let_inits),
        _ => recognized_string_method(&method, call, let_inits).map(StrMethodKind::String),
    }
}

fn recognized_string_method(
    method: &str,
    call: &ExprMethodCall,
    let_inits: &BTreeMap<String, Expr>,
) -> Option<StringMethodKind> {
    let kind = match method {
        "to_ascii_uppercase" if call.args.is_empty() => StringMethodKind::ToAsciiUppercase,
        "to_ascii_lowercase" if call.args.is_empty() => StringMethodKind::ToAsciiLowercase,
        "to_uppercase" if call.args.is_empty() => StringMethodKind::ToUppercase,
        "to_lowercase" if call.args.is_empty() => StringMethodKind::ToLowercase,
        "trim" if call.args.is_empty() => StringMethodKind::Trim,
        "trim_start" if call.args.is_empty() => StringMethodKind::TrimStart,
        "trim_end" if call.args.is_empty() => StringMethodKind::TrimEnd,
        "replace"
            if call.args.len() == 2
                && is_pattern_arg_shape(&call.args[0], let_inits)
                && is_text_receiver_shape(&call.args[1], let_inits) =>
        {
            StringMethodKind::Replace
        }
        "repeat" if call.args.len() == 1 => StringMethodKind::Repeat,
        _ => return None,
    };
    is_text_receiver_shape(&call.receiver, let_inits).then_some(kind)
}

fn recognize_string_iterator_count(
    call: &ExprMethodCall,
    let_inits: &BTreeMap<String, Expr>,
) -> Option<StrMethodKind> {
    let Expr::MethodCall(inner) = strip_refs_groups(&call.receiver) else {
        return None;
    };
    if !inner.args.is_empty() {
        return None;
    }
    match inner.method.to_string().as_str() {
        "chars" if is_text_receiver_shape(&inner.receiver, let_inits) => {
            Some(StrMethodKind::CharsCount)
        }
        "bytes" if is_text_receiver_shape(&inner.receiver, let_inits) => {
            Some(StrMethodKind::BytesCount)
        }
        _ => None,
    }
}

fn recognized_receiver(call: &ExprMethodCall, kind: StrMethodKind) -> Option<&Expr> {
    match kind {
        StrMethodKind::CharsCount | StrMethodKind::BytesCount => {
            let Expr::MethodCall(inner) = strip_refs_groups(&call.receiver) else {
                return None;
            };
            Some(inner.receiver.as_ref())
        }
        _ => Some(&call.receiver),
    }
}

fn recognized_args(
    call: &ExprMethodCall,
    kind: StrMethodKind,
    fcx: &SugarBuildCtx,
    let_inits: &BTreeMap<String, Expr>,
) -> Option<StrMethodArgs> {
    match kind {
        StrMethodKind::String(StringMethodKind::Replace) => {
            let [from, to] = call.args.iter().collect::<Vec<_>>()[..] else {
                return None;
            };
            Some(StrMethodArgs::Replace {
                from: pattern_arg(from, fcx, let_inits)?,
                to: SugarBody::literal_string(to, fcx),
            })
        }
        StrMethodKind::String(StringMethodKind::Repeat) => {
            let [count] = call.args.iter().collect::<Vec<_>>()[..] else {
                return None;
            };
            Some(StrMethodArgs::Repeat {
                count: SugarBody::term(count, fcx),
                count_source: token_key(count),
            })
        }
        StrMethodKind::String(_)
        | StrMethodKind::Len
        | StrMethodKind::CharsCount
        | StrMethodKind::BytesCount
        | StrMethodKind::IsEmpty => Some(StrMethodArgs::None),
        StrMethodKind::StartsWith => {
            let [needle] = call.args.iter().collect::<Vec<_>>()[..] else {
                return None;
            };
            Some(StrMethodArgs::StartsWith {
                needle: SugarBody::literal_string(needle, fcx),
            })
        }
        StrMethodKind::Contains => {
            let [pattern] = call.args.iter().collect::<Vec<_>>()[..] else {
                return None;
            };
            Some(StrMethodArgs::Contains {
                pattern: pattern_arg(pattern, fcx, let_inits)?,
            })
        }
    }
}

fn is_string_result_method(method: &str) -> bool {
    matches!(
        method,
        "to_ascii_uppercase"
            | "to_ascii_lowercase"
            | "to_uppercase"
            | "to_lowercase"
            | "replace"
            | "trim"
            | "trim_start"
            | "trim_end"
            | "repeat"
    )
}

fn is_text_receiver_shape(expr: &Expr, let_inits: &BTreeMap<String, Expr>) -> bool {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Str(_), ..
        }) => true,
        Expr::Macro(m) if macro_name_is(m, "format") => true,
        Expr::Path(_) => simple_path_name(expr)
            .and_then(|name| let_inits.get(&name))
            .is_some_and(|bound| is_text_receiver_shape(bound, let_inits)),
        Expr::MethodCall(call) if call.method == "to_string" && call.args.is_empty() => {
            is_text_receiver_shape(&call.receiver, let_inits)
        }
        Expr::MethodCall(call) if is_string_result_method(&call.method.to_string()) => {
            is_text_receiver_shape(&call.receiver, let_inits)
        }
        _ => false,
    }
}

fn merged_let_inits(
    stable: &BTreeMap<String, Expr>,
    captured: &BTreeMap<String, &Expr>,
) -> BTreeMap<String, Expr> {
    let mut out = stable.clone();
    out.extend(
        captured
            .iter()
            .map(|(name, init)| (name.clone(), (*init).clone())),
    );
    out
}

fn pattern_arg(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    let_inits: &BTreeMap<String, Expr>,
) -> Option<StrPatternArg> {
    if is_text_receiver_shape(expr, let_inits) {
        return Some(StrPatternArg::String(SugarBody::literal_string(expr, fcx)));
    }
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Char(c), ..
        }) => Some(StrPatternArg::Char(c.value())),
        _ => None,
    }
}

fn is_pattern_arg_shape(expr: &Expr, let_inits: &BTreeMap<String, Expr>) -> bool {
    is_text_receiver_shape(expr, let_inits)
        || matches!(
            strip_refs_groups(expr),
            Expr::Lit(ExprLit {
                lit: Lit::Char(_),
                ..
            })
        )
}

impl StrPatternArg {
    fn reduce(&self, ctx: &SugarCtx) -> Result<String, Outcome> {
        match self {
            StrPatternArg::String(body) => match body.reduce_literal_string(ctx) {
                FloorRead::Complete(value) => Ok(value),
                FloorRead::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
            },
            StrPatternArg::Char(ch) => Ok(ch.to_string()),
        }
    }
}

fn repeat_count(
    body: &SugarBody<TermFloor>,
    source: &str,
    ctx: &SugarCtx,
) -> Result<usize, Outcome> {
    let term = term_body(body, ctx)?;
    let Some(value) = const_fold_int_term(&term) else {
        return Err(Outcome::Incomplete(Effect::RuntimeStringRepeatCount {
            boundary: source.to_string(),
        }));
    };
    usize::try_from(value).map_err(|_| {
        Outcome::Incomplete(Effect::RuntimeStringRepeatCount {
            boundary: source.to_string(),
        })
    })
}

fn term_body(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_term()
            .unwrap_or_else(|| panic!("term body completed as non-term before str_method"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn macro_name_is(m: &syn::ExprMacro, name: &str) -> bool {
    m.mac.path.segments.last().is_some_and(|s| s.ident == name)
}

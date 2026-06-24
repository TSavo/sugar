// SPDX-License-Identifier: Apache-2.0
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

use std::collections::BTreeMap;
use sugar_ir_symbolic::{num, str_const};
use syn::{Expr, ExprLit, ExprMethodCall, Lit};

use crate::sugar::factory::{
    compat_reduction, FactoryGap, FactoryReduction, FloorRead, LiteralStringFloor, SugarBody,
    SugarBuildCtx,
};
use crate::sugar::format::stable_let_bindings;
use crate::{
    bool_const, simple_path_name, strip_refs_groups, Desugared, Effect, Outcome, Sugar, SugarCtx,
};

/// Upper bound on a `.repeat(n)` expansion (bytes). A larger expansion DECLINES rather
/// than materialize a huge string const — a bounded, conservative cap.
const REPEAT_BYTE_CAP: usize = 4096;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "str_method",
        &["iter_terminal", "is_empty", "len"],
        recognize,
    );

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
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
        args: recognized_args(call, kind),
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
    args: Vec<Expr>,
}

impl Sugar for StrMethodSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        self.eval(ctx)
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

impl StrMethodSugar {
    fn eval(&self, ctx: &SugarCtx) -> FactoryReduction {
        let recv = match self.receiver_body.reduce_literal_string(ctx)? {
            FloorRead::Complete(value) => value,
            FloorRead::Incomplete(effect) => return Ok(Outcome::Incomplete(effect)),
        };
        let term = match self.kind {
            StrMethodKind::String(kind) => {
                if matches!(
                    kind,
                    StringMethodKind::ToUppercase | StringMethodKind::ToLowercase
                ) && !recv.is_ascii()
                {
                    return Ok(Outcome::Incomplete(Effect::Unsupported {
                        reason:
                            "Unicode string case mapping is not modeled for non-ASCII receivers; refused"
                                .to_string(),
                    }));
                }
                compute_string_kind(kind, recv, &self.args)
                    .map(str_const)
                    .ok_or_else(|| FactoryGap::new("string method did not reduce to a literal string; write more Sugar for this AST"))?
            }
            StrMethodKind::Len => num(recv.len() as i128),
            StrMethodKind::CharsCount => num(rev_char_count(&recv)),
            StrMethodKind::BytesCount => num(recv.len() as i128),
            StrMethodKind::IsEmpty => bool_const(recv.is_empty()),
            StrMethodKind::StartsWith => {
                let needle = string_literal_value(&self.args[0]).ok_or_else(|| {
                    FactoryGap::new(
                        "starts_with argument did not reduce to a literal string; write more Sugar for this AST",
                    )
                })?;
                bool_const(recv.starts_with(&needle))
            }
            StrMethodKind::Contains => {
                let needle = resolve_pattern_value(&self.args[0]).ok_or_else(|| {
                    FactoryGap::new(
                        "contains argument did not reduce to a literal pattern; write more Sugar for this AST",
                    )
                })?;
                bool_const(recv.contains(&needle))
            }
        };
        Ok(Outcome::Complete(Desugared::Term(term)))
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
                && string_literal_value(&call.args[0]).is_some()
                && is_text_receiver_shape(&call.receiver, let_inits) =>
        {
            Some(StrMethodKind::StartsWith)
        }
        "contains"
            if call.args.len() == 1
                && resolve_pattern_value(&call.args[0]).is_some()
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
            if call.args.len() == 2 && replace_args_are_literal(&call.args[0], &call.args[1]) =>
        {
            StringMethodKind::Replace
        }
        "repeat" if call.args.len() == 1 && usize_literal_value(&call.args[0]).is_some() => {
            StringMethodKind::Repeat
        }
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

fn recognized_args(call: &ExprMethodCall, kind: StrMethodKind) -> Vec<Expr> {
    match kind {
        StrMethodKind::CharsCount | StrMethodKind::BytesCount => Vec::new(),
        _ => call.args.iter().cloned().collect(),
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

/// Compute the result of a supported string method over a literal-resolvable receiver,
/// or `None` (decline -> factory gap, never a forged value).
#[cfg(test)]
fn compute_str_method(call: &ExprMethodCall, binds: &BTreeMap<String, Expr>) -> Option<String> {
    let recv = resolve_str_value(&call.receiver, binds)?;
    let kind = match call.method.to_string().as_str() {
        "to_ascii_uppercase" if call.args.is_empty() => StringMethodKind::ToAsciiUppercase,
        "to_ascii_lowercase" if call.args.is_empty() => StringMethodKind::ToAsciiLowercase,
        "to_uppercase" if call.args.is_empty() => StringMethodKind::ToUppercase,
        "to_lowercase" if call.args.is_empty() => StringMethodKind::ToLowercase,
        "trim" if call.args.is_empty() => StringMethodKind::Trim,
        "trim_start" if call.args.is_empty() => StringMethodKind::TrimStart,
        "trim_end" if call.args.is_empty() => StringMethodKind::TrimEnd,
        "replace" if call.args.len() == 2 => StringMethodKind::Replace,
        "repeat" if call.args.len() == 1 => StringMethodKind::Repeat,
        _ => return None,
    };
    let args: Vec<Expr> = call.args.iter().cloned().collect();
    compute_string_kind(kind, recv, &args)
}

fn compute_string_kind(kind: StringMethodKind, recv: String, args: &[Expr]) -> Option<String> {
    match kind {
        StringMethodKind::ToAsciiUppercase => Some(recv.to_ascii_uppercase()),
        StringMethodKind::ToAsciiLowercase => Some(recv.to_ascii_lowercase()),
        // Unicode full-case mapping: warrant ONLY for an ASCII receiver, where it equals
        // the byte-wise `to_ascii_*` and is Unicode-version-independent. A non-ASCII
        // receiver declines (opaque), never a version-dependent guess.
        StringMethodKind::ToUppercase if recv.is_ascii() => Some(recv.to_uppercase()),
        StringMethodKind::ToLowercase if recv.is_ascii() => Some(recv.to_lowercase()),
        StringMethodKind::ToUppercase | StringMethodKind::ToLowercase => None,
        StringMethodKind::Trim => Some(recv.trim().to_string()),
        StringMethodKind::TrimStart => Some(recv.trim_start().to_string()),
        StringMethodKind::TrimEnd => Some(recv.trim_end().to_string()),
        StringMethodKind::Replace => {
            // `str::replace<P: Pattern>(from: P, to: &str)`: `from` is a `&str`/`char`
            // literal, `to` is a `&str` literal.
            let [from_arg, to_arg] = args else {
                return None;
            };
            let from = resolve_pattern_value(from_arg)?;
            let to = string_literal_value(to_arg)?;
            Some(recv.replace(&from, &to))
        }
        StringMethodKind::Repeat => {
            let [n_arg] = args else {
                return None;
            };
            let n = usize_literal_value(n_arg)?;
            // bound the expansion; a huge repeat declines rather than materialize.
            if recv.len().checked_mul(n)? > REPEAT_BYTE_CAP {
                return None;
            }
            Some(recv.repeat(n))
        }
    }
}

/// Resolve an expr to its written string value: a `&str` literal, an immutable
/// `let`/`const`-bound name resolving to one, or a nested supported string-method call
/// (chaining). `None` for any runtime / non-literal receiver.
#[cfg(test)]
fn resolve_str_value(expr: &Expr, binds: &BTreeMap<String, Expr>) -> Option<String> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Str(s), ..
        }) => Some(s.value()),
        Expr::Macro(m) if macro_name_is(m, "format") => None,
        // a `let`/`const`-bound name resolves to its written literal (guard against a
        // self-referential binding, mirroring the format resolver).
        Expr::Path(p) if p.qself.is_none() => {
            let id = p.path.get_ident()?.to_string();
            let bound = binds.get(&id)?;
            let mut narrowed = binds.clone();
            narrowed.remove(&id);
            resolve_str_value(bound, &narrowed)
        }
        Expr::MethodCall(call) if call.method == "to_string" && call.args.is_empty() => {
            resolve_str_value(&call.receiver, binds)
        }
        // a nested supported string-method call composes.
        Expr::MethodCall(call) if is_string_result_method(&call.method.to_string()) => {
            compute_str_method(call, binds)
        }
        _ => None,
    }
}

fn replace_args_are_literal(from: &Expr, to: &Expr) -> bool {
    resolve_pattern_value(from).is_some() && string_literal_value(to).is_some()
}

fn macro_name_is(m: &syn::ExprMacro, name: &str) -> bool {
    m.mac.path.segments.last().is_some_and(|s| s.ident == name)
}

/// A `replace` pattern argument: a `&str` OR `char` literal, as a `String`.
fn resolve_pattern_value(expr: &Expr) -> Option<String> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Str(s), ..
        }) => Some(s.value()),
        Expr::Lit(ExprLit {
            lit: Lit::Char(c), ..
        }) => Some(c.value().to_string()),
        _ => None,
    }
}

/// A `&str` literal argument, as a `String`.
fn string_literal_value(expr: &Expr) -> Option<String> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Str(s), ..
        }) => Some(s.value()),
        _ => None,
    }
}

/// A `usize`/unsuffixed-int literal argument, as a `usize`. `None` for a negative /
/// non-int / out-of-range literal.
fn usize_literal_value(expr: &Expr) -> Option<usize> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Int(i), ..
        }) => i.base10_parse::<usize>().ok(),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(src: &str) -> Expr {
        syn::parse_str(src).expect("expr must parse")
    }

    fn no_binds() -> BTreeMap<String, Expr> {
        BTreeMap::new()
    }

    fn compute(src: &str) -> Option<String> {
        let Expr::MethodCall(call) = parse(src) else {
            panic!("expected a method call");
        };
        compute_str_method(&call, &no_binds())
    }

    #[test]
    fn ascii_case_conversion_recomputes_byte_wise() {
        assert_eq!(
            compute(r#""abc".to_ascii_uppercase()"#).as_deref(),
            Some("ABC")
        );
        assert_eq!(
            compute(r#""ABC".to_ascii_lowercase()"#).as_deref(),
            Some("abc")
        );
        // non-ASCII bytes are untouched by ascii case (the corpus's `ü`/`ß` edge).
        assert_eq!(
            compute(r#""url()uRl()ürl".to_ascii_uppercase()"#).as_deref(),
            Some("URL()URL()üRL")
        );
        assert_eq!(
            compute(r#""hıKß".to_ascii_uppercase()"#).as_deref(),
            Some("HıKß")
        );
    }

    #[test]
    fn unicode_case_warrants_only_ascii_receiver() {
        assert_eq!(compute(r#""abc".to_uppercase()"#).as_deref(), Some("ABC"));
        assert_eq!(compute(r#""ABC".to_lowercase()"#).as_deref(), Some("abc"));
        // a non-ASCII receiver declines (opaque), never a version-dependent guess.
        assert_eq!(compute(r#""ßürl".to_uppercase()"#), None);
        assert_eq!(compute(r#""İ".to_lowercase()"#), None);
    }

    #[test]
    fn replace_trim_repeat_recompute() {
        assert_eq!(
            compute(r#""abcabc".replace("a", "x")"#).as_deref(),
            Some("xbcxbc")
        );
        assert_eq!(
            compute(r#""a.b.c".replace('.', "/")"#).as_deref(),
            Some("a/b/c")
        );
        assert_eq!(compute(r#""  hi  ".trim()"#).as_deref(), Some("hi"));
        assert_eq!(compute(r#""  hi  ".trim_start()"#).as_deref(), Some("hi  "));
        assert_eq!(compute(r#""  hi  ".trim_end()"#).as_deref(), Some("  hi"));
        assert_eq!(compute(r#""ab".repeat(3)"#).as_deref(), Some("ababab"));
        assert_eq!(compute(r#""x".repeat(0)"#).as_deref(), Some(""));
    }

    #[test]
    fn chaining_and_bindings_compose() {
        // method chaining composes.
        assert_eq!(
            compute(r#""Abc".to_ascii_lowercase().to_ascii_uppercase()"#).as_deref(),
            Some("ABC")
        );
        // an immutable let-bound literal resolves through the binding map.
        let mut binds = BTreeMap::new();
        binds.insert("s".to_string(), parse(r#""abc""#));
        let Expr::MethodCall(call) = parse(r#"s.to_ascii_uppercase()"#) else {
            panic!("method call");
        };
        assert_eq!(compute_str_method(&call, &binds).as_deref(), Some("ABC"));
    }

    #[test]
    fn runtime_and_oversized_decline_never_forging() {
        // a runtime receiver declines -> opaque (no fabrication).
        assert_eq!(compute(r#"x.to_ascii_uppercase()"#), None);
        assert_eq!(compute(r#"some_call().to_lowercase()"#), None);
        // an unsupported method is not ours.
        assert_eq!(compute(r#""abc".len()"#), None);
        // an oversized repeat declines rather than materialize a huge const.
        assert_eq!(compute(r#""abcd".repeat(100000)"#), None);
        // a runtime replace argument declines.
        assert_eq!(compute(r#""abc".replace(pat, "x")"#), None);
    }
}

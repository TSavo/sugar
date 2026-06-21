// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for closed stdlib STRING-PRODUCING `&str`/`String` methods over
// written string literals: `.to_ascii_uppercase()`, `.to_ascii_lowercase()`,
// `.to_uppercase()`/`.to_lowercase()` (ASCII-gated), `.replace(from, to)`,
// `.trim()`/`.trim_start()`/`.trim_end()`, `.repeat(n)`. These are PURE functions of a
// literal string, so the result is text-determined: we RECOMPUTE it with the lifter's
// own stdlib (recompute-don't-trust) and dissolve to the real `str_const`, the same
// string-theory floor `to_string`/`format!` dissolve to. So `"abc".to_ascii_uppercase()
// == "ABC"` lifts the checkable `eq("ABC", "ABC")` with real teeth (the wrong-value twin
// `== "ABD"` is z3-UNSAT), NOT an opaque `method:to_ascii_uppercase(...)` EUF var that
// the solver would satisfy tautologically.
//
// finite-or-refuse: ONLY a literal-resolvable receiver/args warrant; a runtime / opaque
// receiver DECLINES (returns `None`) so generic `MethodSugar` keeps the conservative
// opaque term — never a fabricated value. `to_uppercase`/`to_lowercase` are the Unicode
// full-case mappings; we warrant them ONLY for an ASCII receiver (where they equal the
// `to_ascii_*` byte mapping and are Unicode-version-INDEPENDENT), declining otherwise.

use std::collections::BTreeMap;

use sugar_ir_symbolic::str_const;
use syn::{Expr, ExprLit, ExprMethodCall, Lit};

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::format::stable_let_bindings;
use crate::sugar::term_leaf::resolved_term;
use crate::{strip_refs_groups, Sugar};

/// Upper bound on a `.repeat(n)` expansion (bytes). A larger expansion DECLINES rather
/// than materialize a huge string const — a bounded, conservative cap.
const REPEAT_BYTE_CAP: usize = 4096;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("str_method", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    // Quick reject: only claim the string-producing methods we own (so an unrelated
    // method call is never even resolved here).
    if !is_supported_method(&call.method.to_string()) {
        return None;
    }
    let binds = stable_let_bindings(fcx.scope());
    // Resolve to ONE text-determined string, else decline to the opaque method path.
    compute_str_method(call, &binds).map(|s| resolved_term(str_const(s)))
}

fn is_supported_method(method: &str) -> bool {
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

/// Compute the result of a supported string method over a literal-resolvable receiver,
/// or `None` (decline — stays the conservative opaque term, never a forged value).
fn compute_str_method(call: &ExprMethodCall, binds: &BTreeMap<String, Expr>) -> Option<String> {
    let recv = resolve_str_value(&call.receiver, binds)?;
    let method = call.method.to_string();
    match method.as_str() {
        "to_ascii_uppercase" if call.args.is_empty() => Some(recv.to_ascii_uppercase()),
        "to_ascii_lowercase" if call.args.is_empty() => Some(recv.to_ascii_lowercase()),
        // Unicode full-case mapping: warrant ONLY for an ASCII receiver, where it equals
        // the byte-wise `to_ascii_*` and is Unicode-version-independent. A non-ASCII
        // receiver declines (opaque), never a version-dependent guess.
        "to_uppercase" if call.args.is_empty() && recv.is_ascii() => Some(recv.to_uppercase()),
        "to_lowercase" if call.args.is_empty() && recv.is_ascii() => Some(recv.to_lowercase()),
        "trim" if call.args.is_empty() => Some(recv.trim().to_string()),
        "trim_start" if call.args.is_empty() => Some(recv.trim_start().to_string()),
        "trim_end" if call.args.is_empty() => Some(recv.trim_end().to_string()),
        "replace" if call.args.len() == 2 => {
            // `str::replace<P: Pattern>(from: P, to: &str)`: `from` is a `&str`/`char`
            // literal, `to` is a `&str` literal.
            let from = resolve_pattern_value(&call.args[0])?;
            let to = string_literal_value(&call.args[1])?;
            Some(recv.replace(&from, &to))
        }
        "repeat" if call.args.len() == 1 => {
            let n = usize_literal_value(&call.args[0])?;
            // bound the expansion; a huge repeat declines rather than materialize.
            if recv.len().checked_mul(n)? > REPEAT_BYTE_CAP {
                return None;
            }
            Some(recv.repeat(n))
        }
        _ => None,
    }
}

/// Resolve an expr to its written string value: a `&str` literal, an immutable
/// `let`/`const`-bound name resolving to one, or a nested supported string-method call
/// (chaining). `None` for any runtime / non-literal receiver.
fn resolve_str_value(expr: &Expr, binds: &BTreeMap<String, Expr>) -> Option<String> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Str(s), ..
        }) => Some(s.value()),
        // a `let`/`const`-bound name resolves to its written literal (guard against a
        // self-referential binding, mirroring the format resolver).
        Expr::Path(p) if p.qself.is_none() => {
            let id = p.path.get_ident()?.to_string();
            let bound = binds.get(&id)?;
            let mut narrowed = binds.clone();
            narrowed.remove(&id);
            resolve_str_value(bound, &narrowed)
        }
        // a nested supported string-method call composes.
        Expr::MethodCall(call) if is_supported_method(&call.method.to_string()) => {
            compute_str_method(call, binds)
        }
        _ => None,
    }
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

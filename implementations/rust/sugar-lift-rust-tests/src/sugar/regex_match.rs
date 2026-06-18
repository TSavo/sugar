// SPDX-License-Identifier: Apache-2.0
//
// `RegexSugar`: the rust-side regex-match lifter, COMPOSITIONAL. A
// `Regex::new(<pattern>).unwrap().is_match(s)` / `re.is_match(s)` /
// `Regex::new(<pattern>)…find(s).is_some()` assertion is NOT runtime — it is
// first-order string theory:
//
//     re.is_match(s)   ⟺   str.in_re(s, R)
//
// where the pattern operand desugars to a string literal `R` that lowers to a z3
// `RegLan` term. We LIFT THE SHAPE; we never link or run the `regex` crate.
//
// THE PATTERN IS A CHILD SUGAR, NOT A RAW LITERAL. The `<pattern>` operand of
// `Regex::new(<pattern>)` is built into an inner `Sugar` by the SAME `build` walk
// as everything else (mirroring `MapSugar`'s inner sequence). The regex node's
// `desugar` resolves it: `self.pattern.desugar(ctx).dug()?.as_string_literal()?`.
// So the pattern is not REQUIRED to BE a `LitStr` — it must DESUGAR to one:
//   * an inline `"pat"` literal builds to a string `LiteralSugar` (digs NOW);
//   * a `let p = "pat";` / `const PAT: &str = "pat";` builds to whatever resolves
//     the binding (digs NOW via the in-scope `let`-binding resolver);
//   * a `concat!("a", "b")` builds to a `ConcatSugar` (digs NOW — string literals);
//   * a `format!(…)` pattern builds to a `FormatSugar`, which DOES NOT EXIST yet,
//     so it `Hit`s TODAY (a genuinely runtime pattern) — and will dig FOR FREE the
//     instant `FormatSugar` lands, with ZERO change to `RegexSugar`. That is the
//     whole point: `Regex ∘ Format ∘ Literal` composes.
// The node bails (`Hit`) ONLY if the pattern operand `desugar`s to `Hit` (runtime /
// unsupported), NEVER merely because the pattern is not an inline literal.
//
// THE EMISSION IS THE JAVA `@Pattern` PASS, MIRRORED. The Java kit's `@Pattern`
// universe walk emits into ProofIR:
//
//     {"kind":"atomic","name":"str.in-regex","args":[<subject>, <regex-const>]}
//
// — the verbatim regex string carried as arg[1] (a String-sorted const), the
// subject as arg[0]. The SINGLE lowering authority
// (`sugar_ir_compiler_smt_lib::regex_regln`) parses that raw regex at SMT-compile
// time into `(str.in_re subject <regln>)`; a non-regular feature is REFUSED BY
// NAME there. This node resolves the SAME raw pattern and lib.rs emits the
// IDENTICAL atom, so both languages meet at the same `RegLan` by CID. The raw
// pattern is carried, NOT a pre-lowered regln (exactly as Java's
// `buildRegexUniverseContract`); the regularity GATE at lift time reuses
// `regex_regln` as the one regular-language oracle.

use std::collections::BTreeMap;

use syn::{Expr, ExprLit, Lit};

use crate::sugar::bound::BoundSugar;
use crate::{strip_refs_groups, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx};

/// A recognized rust regex-match assertion: the pattern operand built into an
/// inner `Sugar`, and the subject expr. lib.rs drives `desugar` to resolve the
/// pattern string, gates regularity, and emits `str.in-regex(subject, pattern)`.
pub(crate) struct RegexMatch {
    /// The pattern operand of `Regex::new(<pattern>)`, built into an inner `Sugar`.
    /// Resolving it is `self.pattern.desugar(ctx)` — compositional, so a literal /
    /// const-string / `concat!` all flow through one path.
    pub(crate) pattern: Box<dyn Sugar>,
    /// The subject expr the regex is matched against (`is_match(subj)` /
    /// `find(subj)`). A literal subject is the decidable POINT case; a variable
    /// subject is the UNIVERSAL membership case (translated as an opaque term in
    /// lib.rs).
    pub(crate) subject: Expr,
    /// The regex method that named this membership (`is_match` / `find`), for the
    /// EUF callsite name.
    pub(crate) method: &'static str,
}

impl RegexMatch {
    /// Resolve the pattern operand by DESUGARING the inner pattern `Sugar`
    /// (mirroring `MapSugar`'s `self.inner.desugar(ctx)`). The caller reads the
    /// resolved string off the `Outcome` via `Desugared::as_string_literal`. A
    /// `Dug` carries the resolved literal (a literal / const-string / `concat!`
    /// all flow through this one path); a `Hit` is a genuinely runtime /
    /// unsupported pattern (a `format!(…)` with no FormatSugar yet) — the caller
    /// declines on `Hit`, the composition frontier. This is the WHOLE compositional
    /// contract: `RegexSugar` consumes whatever its pattern child dug to.
    pub(crate) fn resolve_pattern(&self, ctx: &SugarCtx) -> Outcome {
        self.pattern.desugar(ctx)
    }
}

/// Build a `&str` literal expr from a Rust string value (fallback when the debug
/// round-trip does not parse, which it always does for `{:?}` of a `String`).
fn string_literal_expr(s: &str) -> Expr {
    let lit = syn::LitStr::new(s, proc_macro2::Span::call_site());
    Expr::Lit(ExprLit {
        attrs: Vec::new(),
        lit: Lit::Str(lit),
    })
}

/// Build arm: recognize a rust regex-match SHAPE and `build` the pattern operand
/// into an inner `Sugar` (recursively, by the same walk). Returns `None` (declines
/// to recognize) on a non-regex shape or an unrecognized API. The pattern is NOT
/// required to be an inline literal here — recognition keys ONLY on the
/// construction site `Regex::new(<anything>)`; whether that `<anything>` resolves
/// to a string literal is decided LATER by `resolve_pattern` (the dig), so a
/// `const`/`concat!`/future-`format!` pattern is recognized and composes. No
/// source that does not name `Regex::new` can fire this node.
pub(crate) fn recognize_regex_match(
    expr: &Expr,
    let_bindings: &BTreeMap<String, Expr>,
) -> Option<RegexMatch> {
    match unwrap_grouping(expr) {
        // `<regex>.is_match(subj)`
        Expr::MethodCall(call) if call.method == "is_match" => {
            if call.args.len() != 1 {
                return None;
            }
            let pattern_expr = regex_pattern_expr(&call.receiver, let_bindings)?;
            Some(RegexMatch {
                pattern: build_pattern_sugar(pattern_expr, let_bindings),
                subject: unwrap_grouping(&call.args[0]).clone(),
                method: "is_match",
            })
        }
        // `<regex>.find(subj).is_some()`
        Expr::MethodCall(call) if call.method == "is_some" => {
            if !call.args.is_empty() {
                return None;
            }
            let find = match unwrap_grouping(&call.receiver) {
                Expr::MethodCall(f) if f.method == "find" => f,
                _ => return None,
            };
            if find.args.len() != 1 {
                return None;
            }
            let pattern_expr = regex_pattern_expr(&find.receiver, let_bindings)?;
            Some(RegexMatch {
                pattern: build_pattern_sugar(pattern_expr, let_bindings),
                subject: unwrap_grouping(&find.args[0]).clone(),
                method: "find",
            })
        }
        _ => None,
    }
}

/// Walk a receiver chain back to the `Regex::new(<pattern-expr>)` it was built
/// from, returning the RAW pattern operand expr (NOT yet resolved to a literal).
/// Recognizes the construction site through the `Result` peel and a `let`-bound
/// regex; the pattern operand is whatever was passed to `Regex::new` — its
/// resolution is the inner `Sugar`'s job. `None` for a non-regex receiver.
fn regex_pattern_expr(recv: &Expr, let_bindings: &BTreeMap<String, Expr>) -> Option<Expr> {
    match unwrap_grouping(recv) {
        // `Regex::new(<pattern-expr>)` — the construction site.
        Expr::Call(call) => {
            if !path_is_regex_new(&call.func) {
                return None;
            }
            if call.args.len() != 1 {
                return None;
            }
            Some(call.args[0].clone())
        }
        // `Regex::new(<pat>).unwrap()` / `.expect(..)` — peel the Result, recurse.
        Expr::MethodCall(call) if call.method == "unwrap" || call.method == "expect" => {
            regex_pattern_expr(&call.receiver, let_bindings)
        }
        // A bare path `re` — resolve a `let re = Regex::new(<pat>)…;` binding.
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let bound = let_bindings.get(&name)?;
            regex_pattern_expr(bound, let_bindings)
        }
        _ => None,
    }
}

/// Is `func` the path `Regex::new` (or qualified `regex::Regex::new`)? The
/// recognizer keys on this exact construction-site name; no source that does not
/// name `Regex::new` can fire this node.
fn path_is_regex_new(func: &Expr) -> bool {
    let Expr::Path(path) = unwrap_grouping(func) else {
        return false;
    };
    let segs: Vec<String> = path
        .path
        .segments
        .iter()
        .map(|s| s.ident.to_string())
        .collect();
    matches!(segs.as_slice(), [.., reg, new] if reg == "Regex" && new == "new")
}

/// Peel `Paren`/`Group` wrappers.
fn unwrap_grouping(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(p) => unwrap_grouping(&p.expr),
        Expr::Group(g) => unwrap_grouping(&g.expr),
        other => other,
    }
}

// ── The pattern operand as a child `Sugar` ──────────────────────────────────
//
// `build_pattern_sugar` is the recursive `build` for the pattern operand of
// `Regex::new(<pattern>)`. It mirrors the closed set of resolvers that exist
// TODAY; an operand it cannot resolve builds to `UnsupportedPatternSugar`, which
// `Hit`s (the `format!(…)` frontier). Adding a new pattern producer (FormatSugar)
// = adding one arm here; `RegexSugar` itself never changes.

/// Build the pattern operand into a child `Sugar`. The operand digs to a string
/// literal NOW for: an inline `&str` literal; a `let`/`const`-bound name that
/// resolves to one; a `concat!(…)` of string literals. It `Hit`s for a runtime /
/// unsupported producer (a `format!(…)`, a bare runtime variable) — the
/// composition frontier that flips to dig when its producer `Sugar` lands.
pub(crate) fn build_pattern_sugar(
    pattern: Expr,
    let_bindings: &BTreeMap<String, Expr>,
) -> Box<dyn Sugar> {
    Box::new(PatternSugar {
        pattern,
        let_bindings: let_bindings.clone(),
    })
}

/// The pattern-operand `Sugar`: resolves the operand to a single string-literal
/// element `Seq`, or `Hit`s on a runtime / unsupported producer. This is the
/// "LiteralSugar of String kind" the pattern must DESUGAR to — composed through
/// the const/let resolver and `concat!`, not a hardcoded inline match.
struct PatternSugar {
    pattern: Expr,
    let_bindings: BTreeMap<String, Expr>,
}

impl Sugar for PatternSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        // A `let p = "pat";` / `const PAT: &str = "pat";` reference resolves through a
        // first-class `BoundSugar` node, NOT an ad-hoc `let_bindings.get(name)`
        // recursion inlined here: the binding reference is a composed `Sugar` whose
        // outcome is whatever the bound init's `Sugar` (another `PatternSugar` over the
        // init) collapses to, with the binding `name` carried as provenance. The
        // resolved string is byte-identical to recursing the init directly -- the
        // binding reference is transparent. Shadowing is handled UPSTREAM: `let_bindings`
        // is the binding in effect at the reference's program point.
        if let Some((name, bound)) = self.let_bound_reference() {
            return BoundSugar::new(
                name,
                Box::new(PatternSugar {
                    pattern: bound,
                    let_bindings: self.let_bindings.clone(),
                }),
            )
            .desugar(ctx);
        }
        match resolve_string_literal(&self.pattern, &self.let_bindings) {
            Some(s) => Outcome::Dug(Desugared::Seq(vec![DesugaredElem {
                expr: string_literal_expr(&s),
                value: None,
            }])),
            // A runtime / unsupported pattern producer (e.g. `format!(…)`, a bare
            // runtime variable). Bails TODAY; digs FOR FREE when its producer lands.
            None => Outcome::from_opt(None),
        }
    }
}

impl PatternSugar {
    /// If the pattern operand is a bare `let`/`const`-bound NAME in scope, return the
    /// `(name, bound-init-expr)` so the resolution routes through `BoundSugar`. `None`
    /// for an inline literal, a `concat!`, an unbound path, or any non-path operand --
    /// those resolve directly through `resolve_string_literal` (the literal/concat
    /// base cases), never through a binding node. This is the SINGLE binding-reference
    /// recognizer for the pattern operand (lifted out of `resolve_string_literal`'s
    /// inlined path arm, so the binding resolution is now a uniform composed node).
    fn let_bound_reference(&self) -> Option<(String, Expr)> {
        match strip_refs_groups(&self.pattern) {
            Expr::Path(path) if path.qself.is_none() => {
                let name = path.path.get_ident()?.to_string();
                let bound = self.let_bindings.get(&name)?;
                Some((name, bound.clone()))
            }
            _ => None,
        }
    }
}

/// Resolve a pattern operand expr to its string-literal value, composing the
/// resolvers that exist today: inline `&str` literal, `let`/`const`-bound name, and
/// `concat!(<string literals>)`. This is the FRAGMENT-LEVEL resolver: it is the base
/// case the operand-level `BoundSugar` ultimately delegates to (via a `PatternSugar`
/// over a bound init), and it also resolves nested `concat!` fragments that may
/// themselves be bound names. The TOP-LEVEL operand binding reference is intercepted
/// in `PatternSugar::desugar` and routed through `BoundSugar` BEFORE reaching here, so
/// the operand's binding resolution is the uniform composed node; the path arm here
/// only fires for fragments NESTED inside a `concat!` (and for the in-isolation unit
/// tests of this pure resolver). Returns `None` for a runtime / unsupported producer —
/// the floor must be a WRITTEN literal (reached through any number of pure resolver
/// indirections), never runtime data.
fn resolve_string_literal(expr: &Expr, let_bindings: &BTreeMap<String, Expr>) -> Option<String> {
    match strip_refs_groups(expr) {
        // Inline `&str` literal — the base case (LiteralSugar of String kind).
        Expr::Lit(ExprLit {
            lit: Lit::Str(s), ..
        }) => Some(s.value()),
        // `let p = "pat";` / `const PAT: &str = "pat";` — a fragment-level (or
        // unit-test) binding indirection to the written literal. (The TOP-LEVEL
        // operand binding reference is routed through `BoundSugar` upstream; this arm
        // resolves a binding NESTED inside a `concat!` fragment.)
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let bound = let_bindings.get(&name)?;
            resolve_string_literal(bound, let_bindings)
        }
        // `concat!("a", "b", …)` — a pure compile-time concatenation of string
        // literals (a resolver that exists today). Each fragment must itself
        // resolve to a string literal.
        Expr::Macro(m) if m.mac.path.is_ident("concat") => {
            let parsed = m
                .mac
                .parse_body_with(
                    syn::punctuated::Punctuated::<Expr, syn::Token![,]>::parse_terminated,
                )
                .ok()?;
            let mut out = String::new();
            for frag in parsed {
                out.push_str(&resolve_string_literal(&frag, let_bindings)?);
            }
            Some(out)
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    // The recognizer + pattern resolver are exercised end-to-end through the
    // lift in tests/assertion_lift.rs (str.in-regex atom shape, composition via a
    // const-string pattern, non-regular refusal, over-fire guard). Here we unit-
    // test the pure resolver and the build-arm recognition in isolation.
    use super::*;
    use std::collections::BTreeMap;

    fn parse(src: &str) -> Expr {
        syn::parse_str(src).expect("expr parses")
    }

    fn no_bindings() -> BTreeMap<String, Expr> {
        BTreeMap::new()
    }

    // ── resolve_string_literal: the compositional pattern resolver ──

    #[test]
    fn resolves_inline_literal() {
        assert_eq!(
            resolve_string_literal(&parse(r#""^[a-z]+$""#), &no_bindings()).as_deref(),
            Some("^[a-z]+$")
        );
    }

    #[test]
    fn resolves_let_bound_literal() {
        // `let x = "myregex"; Regex::new(x)` — the pattern is a String literal one
        // indirection away. Composes through the binding resolver.
        let mut binds = BTreeMap::new();
        binds.insert("x".to_string(), parse(r#""myregex""#));
        assert_eq!(
            resolve_string_literal(&parse("x"), &binds).as_deref(),
            Some("myregex")
        );
    }

    #[test]
    fn resolves_chained_const_indirection() {
        let mut binds = BTreeMap::new();
        binds.insert("A".to_string(), parse(r#""pat""#));
        binds.insert("B".to_string(), parse("A"));
        assert_eq!(
            resolve_string_literal(&parse("B"), &binds).as_deref(),
            Some("pat")
        );
    }

    #[test]
    fn resolves_concat_of_literals() {
        // `concat!("^", "[a-z]+", "$")` — a pure resolver that exists today.
        assert_eq!(
            resolve_string_literal(&parse(r#"concat!("^", "[a-z]+", "$")"#), &no_bindings())
                .as_deref(),
            Some("^[a-z]+$")
        );
    }

    #[test]
    fn declines_runtime_pattern() {
        // A `format!(…)` / bare runtime value does NOT resolve to a literal today.
        assert!(resolve_string_literal(&parse(r#"format!("{}", x)"#), &no_bindings()).is_none());
        assert!(resolve_string_literal(&parse("user_input"), &no_bindings()).is_none());
    }

    // ── recognize_regex_match: the build-arm shapes ──

    #[test]
    fn recognizes_inline_is_match() {
        let e = parse(r#"Regex::new("^[a-z]+$").unwrap().is_match(s)"#);
        let m = recognize_regex_match(&e, &no_bindings()).expect("recognized");
        assert_eq!(m.method, "is_match");
        // The pattern operand resolves to the inline literal.
        assert_eq!(
            resolve_string_literal(&parse(r#""^[a-z]+$""#), &no_bindings()).as_deref(),
            Some("^[a-z]+$")
        );
    }

    #[test]
    fn recognizes_find_is_some() {
        let e = parse(r#"Regex::new("[0-9]+").unwrap().find(s).is_some()"#);
        let m = recognize_regex_match(&e, &no_bindings()).expect("recognized");
        assert_eq!(m.method, "find");
    }

    #[test]
    fn recognizes_const_pattern_through_let_binding() {
        // The pattern operand is a NON-inline `const`-string name resolved via the
        // binding map; recognition succeeds (the dig resolves it later).
        let mut binds = BTreeMap::new();
        binds.insert("PAT".to_string(), parse(r#""a.c""#));
        let e = parse(r#"Regex::new(PAT).unwrap().is_match(s)"#);
        let m = recognize_regex_match(&e, &binds).expect("recognized const-string pattern");
        assert_eq!(m.method, "is_match");
    }

    #[test]
    fn recognizes_runtime_pattern_shape_but_resolves_to_none() {
        // `Regex::new(format!(…))` IS recognized (it is a Regex::new construction);
        // the pattern operand only fails to RESOLVE (the composition frontier). The
        // recognizer does not pre-judge resolvability — that is the dig's job.
        let e = parse(r#"Regex::new(format!("{}", x)).unwrap().is_match(s)"#);
        let m = recognize_regex_match(&e, &no_bindings()).expect("recognized regex construction");
        assert!(resolve_string_literal(&parse(r#"format!("{}", x)"#), &no_bindings()).is_none());
        assert_eq!(m.method, "is_match");
    }

    // ── over-fire guards ──

    #[test]
    fn declines_foreign_is_match() {
        assert!(recognize_regex_match(&parse(r#"matcher.is_match(s)"#), &no_bindings()).is_none());
    }

    #[test]
    fn declines_non_regex_call() {
        assert!(
            recognize_regex_match(&parse(r#"Foo::new("x").is_match(s)"#), &no_bindings()).is_none()
        );
    }

    #[test]
    fn declines_find_without_is_some() {
        assert!(recognize_regex_match(
            &parse(r#"Regex::new("a").unwrap().find(s)"#),
            &no_bindings()
        )
        .is_none());
    }

    #[test]
    fn declines_unbound_path_receiver() {
        assert!(recognize_regex_match(&parse(r#"re.is_match(s)"#), &no_bindings()).is_none());
    }

    // ── let_bound_reference: the operand-level binding recognizer (routes through
    //    BoundSugar). Three tests per the discrimination discipline: positive,
    //    discrimination (the shapes that must NOT be treated as a binding reference),
    //    structural (an in-shape path that is unbound). ──

    fn pattern_sugar(src: &str, binds: BTreeMap<String, Expr>) -> PatternSugar {
        PatternSugar {
            pattern: parse(src),
            let_bindings: binds,
        }
    }

    #[test]
    fn let_bound_reference_recognizes_bound_path() {
        // POSITIVE: a bare name bound in scope -> (name, bound-init) so resolution
        // routes through `BoundSugar`.
        let mut binds = BTreeMap::new();
        binds.insert("p".to_string(), parse(r#""a.c""#));
        let ps = pattern_sugar("p", binds);
        let (name, bound) = ps.let_bound_reference().expect("bound path recognized");
        assert_eq!(name, "p");
        // The bound init is the written literal expr.
        assert_eq!(
            resolve_string_literal(&bound, &BTreeMap::new()).as_deref(),
            Some("a.c")
        );
    }

    #[test]
    fn let_bound_reference_declines_inline_literal_and_concat() {
        // DISCRIMINATION: an inline literal and a `concat!` are NOT binding references
        // -- they resolve directly through `resolve_string_literal`, never `BoundSugar`.
        let ps_lit = pattern_sugar(r#""^[a-z]+$""#, BTreeMap::new());
        assert!(ps_lit.let_bound_reference().is_none());
        let ps_concat = pattern_sugar(r#"concat!("^", "x")"#, BTreeMap::new());
        assert!(ps_concat.let_bound_reference().is_none());
    }

    #[test]
    fn let_bound_reference_declines_unbound_path() {
        // STRUCTURAL: a bare path of the right SHAPE but NOT bound in scope is declined
        // (no init to wrap) -- the operand falls through to `resolve_string_literal`,
        // which also declines it (a runtime variable). No `BoundSugar` is built.
        let ps = pattern_sugar("user_input", BTreeMap::new());
        assert!(ps.let_bound_reference().is_none());
    }
}

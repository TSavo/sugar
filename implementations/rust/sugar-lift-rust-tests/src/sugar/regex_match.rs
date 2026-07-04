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
// `Regex::new(<pattern>)` is built into an inner `SugarBody<LiteralStringFloor>` by
// the SAME `build` walk as everything else (mirroring `MapSugar`'s inner sequence).
// The regex node's `desugar` reduces that body and reads the literal string floor.
// So the pattern is not REQUIRED to BE a `LitStr` — it must DESUGAR to one:
//   * an inline `"pat"` literal builds to a string `LiteralSugar` (completes NOW);
//   * a `let p = "pat";` / `const PAT: &str = "pat";` builds to whatever resolves
//     the binding (completes NOW via the in-scope `let`-binding resolver);
//   * a `concat!("a", "b")` / `format!(...)` builds through the ordinary term
//     catalog and bottoms out in a string `Term` when its operands are closed;
//   * a pure in-source helper such as `pattern()` composes through `CallSugar`.
// The node bails (`Incomplete`) ONLY if the pattern operand `desugar`s to `Incomplete` (runtime /
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

use syn::Expr;

#[cfg(test)]
use crate::strip_refs_groups;
use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{FloorRead, LiteralStringFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::format::{
    is_concat_macro_shape, is_factory_string_add_shape, is_format_macro_shape, is_to_string_shape,
    stable_let_bindings,
};
use crate::{
    callsite_assertion_name, AssertionFactKind, Desugared, Effect, Outcome, Sugar, SugarCtx,
    Warrant,
};
use sugar_ir_symbolic::{atomic_, str_const, Formula, Term};

use crate::sugar::source_fragment::SourceFragment;
pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_regex_match",
    SugarRole::Constraint,
    crate::sugar::claim::SugarWitnesses::pair(
        r#"
            struct Regex(&'static str);

            impl Regex {
                fn new(pattern: &'static str) -> Result<Self, ()> {
                    Ok(Self(pattern))
                }

                fn is_match(&self, subject: &str) -> bool {
                    self.0 == "^a+$"
                        && subject.chars().all(|ch| ch == 'a')
                        && !subject.is_empty()
                }
            }

            #[test]
            fn t_regex_match_good() {
                assert!(Regex::new("^a+$").unwrap().is_match("aaa"));
            }
        "#,
        r#"
            struct Regex(&'static str);

            impl Regex {
                fn new(pattern: &'static str) -> Result<Self, ()> {
                    Ok(Self(pattern))
                }

                fn is_match(&self, subject: &str) -> bool {
                    self.0 == "^a+$"
                        && subject.chars().all(|ch| ch == 'a')
                        && !subject.is_empty()
                }
            }

            #[test]
            fn t_regex_match_bad() {
                assert!(Regex::new("^a+$").unwrap().is_match("bbb"));
            }
        "#,
    ),
    recognize_constraint,
);

/// A recognized rust regex-match assertion: the raw pattern operand and the
/// subject expr. lib.rs drives `desugar` to build and resolve the pattern string,
/// gates regularity, and emits `str.in-regex(subject, pattern)`.
pub(crate) struct RegexMatch {
    /// The raw pattern operand of `Regex::new(<pattern>)`. Resolving it is lazy:
    /// `resolve_pattern(ctx)` builds the child `Sugar` under the desugar-time scope.
    pub(crate) pattern: Expr,
    /// The subject expr the regex is matched against (`is_match(subj)` /
    /// `find(subj)`). A literal subject is the decidable POINT case; a variable
    /// subject is the UNIVERSAL membership case (translated as an opaque term in
    /// lib.rs).
    pub(crate) subject: Expr,
    /// The regex method that named this membership (`is_match` / `find`), for the
    /// EUF callsite name.
    pub(crate) method: &'static str,
}

struct RegexMatchSugar {
    pattern: SugarBody<LiteralStringFloor>,
    subject: SugarBody<TermFloor>,
    method: &'static str,
}

fn recognize_constraint(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let stable = stable_let_bindings(fcx.scope());
    let matched = recognize_regex_match(expr, &stable, fcx)?;
    if !pattern_claims_literal_string_floor(&matched.pattern, &stable, fcx) {
        return None;
    }
    Some(Box::new(RegexMatchSugar {
        pattern: SugarBody::literal_string(&matched.pattern, fcx),
        subject: SugarBody::term(&matched.subject, fcx),
        method: matched.method,
    }))
}

fn pattern_claims_literal_string_floor(
    expr: &Expr,
    let_bindings: &BTreeMap<String, Expr>,
    fcx: &SugarBuildCtx,
) -> bool {
    match unwrap_grouping(expr) {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Str(_),
            ..
        }) => true,
        Expr::Macro(_) => is_format_macro_shape(expr) || is_concat_macro_shape(expr),
        Expr::MethodCall(call) if call.args.is_empty() && is_to_string_shape(expr) => true,
        Expr::Binary(_) if is_factory_string_add_shape(expr, fcx) => true,
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(ToString::to_string) else {
                return false;
            };
            let Some(bound) = let_bindings.get(&name) else {
                return false;
            };
            pattern_claims_literal_string_floor(bound, let_bindings, fcx)
        }
        _ => false,
    }
}

impl Sugar for RegexMatchSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let pattern_str = match self.pattern.reduce_literal_string(ctx) {
            FloorRead::Complete(pattern) => pattern,
            FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        if let Err(e) = sugar_ir_compiler_smt_lib::regex_regln::regex_to_regln(&pattern_str) {
            return regex_pattern_incomplete(pattern_str, e);
        }
        let subject = match self.subject.reduce(ctx) {
            Outcome::Complete(desugared) => desugared.into_term().unwrap_or_else(|| {
                regex_gap(
                    "regex subject completed a non-Term where a Term was required; write more Sugar for this AST",
                )
            }),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let pattern = str_const(pattern_str);
        let name = method_assertion_name(
            self.method,
            vec![subject.clone(), pattern.clone()],
            ctx.scope.local_scope(),
        );
        constraint(atomic_("str.in-regex", vec![subject, pattern]), name)
    }
}

/// Build arm: recognize a rust regex-match SHAPE and `build` the pattern operand
/// into an inner `Sugar` (recursively, by the same walk). Returns `None` (declines
/// to recognize) on a non-regex shape or an unrecognized API. The pattern is NOT
/// required to be an inline literal here — recognition keys ONLY on the
/// construction site `Regex::new(<anything>)`; whether that `<anything>` resolves
/// to a string literal is decided LATER by `resolve_pattern` (the complete), so a
/// `const`/`concat!`/future-`format!` pattern is recognized and composes. No
/// source that does not name `Regex::new` can fire this node.
pub(crate) fn recognize_regex_match(
    expr: &Expr,
    let_bindings: &BTreeMap<String, Expr>,
    _fcx: &SugarBuildCtx,
) -> Option<RegexMatch> {
    match unwrap_grouping(expr) {
        // `<regex>.is_match(subj)`
        Expr::MethodCall(call) if call.method == "is_match" => {
            if call.args.len() != 1 {
                return None;
            }
            let pattern_expr = regex_pattern_expr(&call.receiver, let_bindings)?;
            Some(RegexMatch {
                pattern: pattern_expr,
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
                pattern: pattern_expr,
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
// `Regex::new(<pattern>)`. A bare stable binding gets a `BoundSugar` provenance wrapper;
// everything else goes through the ordinary term factory.

/// If the pattern operand is a bare stable binding name, return the binding and route
/// it through `BoundSugar`. Other shapes go straight to the recursive term factory.
#[cfg(test)]
fn let_bound_reference(
    pattern: &Expr,
    let_bindings: &BTreeMap<String, Expr>,
) -> Option<(String, Expr)> {
    match strip_refs_groups(pattern) {
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let bound = let_bindings.get(&name)?;
            Some((name, bound.clone()))
        }
        _ => None,
    }
}

fn constraint(atom: std::rc::Rc<Formula>, name: Option<String>) -> Outcome {
    Outcome::Complete(Desugared::Constraints {
        atom,
        n: 1,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name },
    })
}

fn method_assertion_name(
    method: &str,
    args: Vec<std::rc::Rc<Term>>,
    local_scope: &str,
) -> Option<String> {
    let term = Term::Ctor {
        name: format!("method:{method}"),
        args,
    };
    callsite_assertion_name(&term, local_scope)
}

fn regex_pattern_incomplete(
    pattern: String,
    error: sugar_ir_compiler_smt_lib::regex_regln::RegexError,
) -> Outcome {
    Outcome::Incomplete(regex_pattern_effect(pattern, error))
}

fn regex_pattern_effect(
    pattern: String,
    error: sugar_ir_compiler_smt_lib::regex_regln::RegexError,
) -> Effect {
    let reason = regex_pattern_error_reason(&pattern, error);
    Effect::RegexPattern { reason }
}

fn regex_pattern_error_reason(
    pattern: &str,
    error: sugar_ir_compiler_smt_lib::regex_regln::RegexError,
) -> String {
    match error {
        sugar_ir_compiler_smt_lib::regex_regln::RegexError::NotRegular(feat) => format!(
            "regex pattern `{}` uses a non-regular feature ({feat}) -- not expressible \
             as RegLan; refused by name (no str.in-regex membership row)",
            pattern
        ),
        sugar_ir_compiler_smt_lib::regex_regln::RegexError::Malformed(msg) => format!(
            "regex pattern `{}` is malformed ({msg}); refused (no str.in-regex membership row)",
            pattern
        ),
    }
}

fn regex_gap(reason: &str) -> ! {
    panic!("RegexMatchSugar did not reach a lawful value floor: {reason}")
}

#[cfg(test)]
mod tests {
    // The recognizer + pattern resolver are exercised end-to-end through the lift
    // tests (str.in-regex atom shape, composition via the factory, non-regular refusal,
    // over-fire guard). Here we unit-test the build-arm recognition in isolation.
    use super::*;
    use std::collections::BTreeMap;

    fn parse(src: &str) -> Expr {
        syn::parse_str(src).expect("expr parses")
    }

    fn no_bindings() -> BTreeMap<String, Expr> {
        BTreeMap::new()
    }

    fn with_fcx<T>(f: impl FnOnce(&SugarBuildCtx<'_, '_>) -> T) -> T {
        let scope = crate::TemporalScope::new("test", crate::TemporalPlan::default());
        let options = crate::LiftOptions::default();
        let inits: BTreeMap<String, &Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &inits);
        f(&fcx)
    }

    // ── recognize_regex_match: the build-arm shapes ──

    #[test]
    fn recognizes_inline_is_match() {
        let e = parse(r#"Regex::new("^[a-z]+$").unwrap().is_match(s)"#);
        let m = with_fcx(|fcx| recognize_regex_match(&e, &no_bindings(), fcx)).expect("recognized");
        assert_eq!(m.method, "is_match");
    }

    #[test]
    fn recognizes_find_is_some() {
        let e = parse(r#"Regex::new("[0-9]+").unwrap().find(s).is_some()"#);
        let m = with_fcx(|fcx| recognize_regex_match(&e, &no_bindings(), fcx)).expect("recognized");
        assert_eq!(m.method, "find");
    }

    #[test]
    fn recognizes_const_pattern_through_let_binding() {
        // The pattern operand is a NON-inline `const`-string name resolved via the
        // binding map; recognition succeeds (the complete resolves it later).
        let mut binds = BTreeMap::new();
        binds.insert("PAT".to_string(), parse(r#""a.c""#));
        let e = parse(r#"Regex::new(PAT).unwrap().is_match(s)"#);
        let m = with_fcx(|fcx| recognize_regex_match(&e, &binds, fcx))
            .expect("recognized const-string pattern");
        assert_eq!(m.method, "is_match");
    }

    #[test]
    fn recognizes_runtime_pattern_shape_but_resolves_to_none() {
        // `Regex::new(format!(…))` IS recognized (it is a Regex::new construction);
        // this one only fails to RESOLVE because the format argument is runtime. The
        // recognizer does not pre-judge resolvability -- that is the complete's job.
        let e = parse(r#"Regex::new(format!("{}", x)).unwrap().is_match(s)"#);
        let m = with_fcx(|fcx| recognize_regex_match(&e, &no_bindings(), fcx))
            .expect("recognized regex construction");
        assert_eq!(m.method, "is_match");
    }

    // ── over-fire guards ──

    #[test]
    fn declines_foreign_is_match() {
        assert!(with_fcx(|fcx| {
            recognize_regex_match(&parse(r#"matcher.is_match(s)"#), &no_bindings(), fcx).is_none()
        }));
    }

    #[test]
    fn declines_non_regex_call() {
        assert!(with_fcx(|fcx| {
            recognize_regex_match(&parse(r#"Foo::new("x").is_match(s)"#), &no_bindings(), fcx)
                .is_none()
        }));
    }

    #[test]
    fn declines_find_without_is_some() {
        assert!(with_fcx(|fcx| {
            recognize_regex_match(
                &parse(r#"Regex::new("a").unwrap().find(s)"#),
                &no_bindings(),
                fcx,
            )
            .is_none()
        }));
    }

    #[test]
    fn declines_unbound_path_receiver() {
        assert!(with_fcx(|fcx| {
            recognize_regex_match(&parse(r#"re.is_match(s)"#), &no_bindings(), fcx).is_none()
        }));
    }

    // ── let_bound_reference: the operand-level binding recognizer (routes through
    //    BoundSugar). Three tests per the discrimination discipline: positive,
    //    discrimination (the shapes that must NOT be treated as a binding reference),
    //    structural (an in-shape path that is unbound). ──

    #[test]
    fn let_bound_reference_recognizes_bound_path() {
        // POSITIVE: a bare name bound in scope -> (name, bound-init) so resolution
        // routes through `BoundSugar`.
        let mut binds = BTreeMap::new();
        binds.insert("p".to_string(), parse(r#""a.c""#));
        let (name, bound) =
            let_bound_reference(&parse("p"), &binds).expect("bound path recognized");
        assert_eq!(name, "p");
        // The bound init is the written literal expr.
        assert!(matches!(strip_refs_groups(&bound), Expr::Lit(_)));
    }

    #[test]
    fn let_bound_reference_declines_inline_literal_and_concat() {
        // DISCRIMINATION: an inline literal and a `concat!` are NOT binding references
        // -- they resolve directly through the factory, never `BoundSugar`.
        assert!(let_bound_reference(&parse(r#""^[a-z]+$""#), &BTreeMap::new()).is_none());
        assert!(let_bound_reference(&parse(r#"concat!("^", "x")"#), &BTreeMap::new()).is_none());
    }

    #[test]
    fn let_bound_reference_declines_unbound_path() {
        // STRUCTURAL: a bare path of the right SHAPE but NOT bound in scope is declined
        // (no init to wrap) -- the operand falls through to the recursive factory.
        // No `BoundSugar` is built.
        assert!(let_bound_reference(&parse("user_input"), &BTreeMap::new()).is_none());
    }
}

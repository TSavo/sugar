// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Macro`: the mut-local temporal-instability refusal, then -- for a
// `macro_rules!` we HOLD THE DEFINITION FOR -- an EXPANSION complete walk that feeds the macro's
// own body back to the factory (`my_macro!(2,3)` -> `2 + 3` -> `+(2,3)`, which grounds).
// If a visible source macro cannot expand to a term we know how to reduce, construction records a
// panic reason. If a dependency/compiler macro has no visible expansion source at all, this sugar
// emits the typed opaque-macro effect instead of guessing vendor semantics.
//
// The expansion lives at DESUGAR time, not recognize time: the macro_rules registry
// hangs off `ReductionCtx`, which is in the DESUGAR-time `SugarCtx` (`ctx.reducer`), not
// recognize time.
use sugar_ir_symbolic::str_const;
use syn::parse::{Parse, ParseStream};

use crate::sugar::configuration::{self, CfgDisposition};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    bool_const, CfgPredicate, Desugared, Effect, Outcome, Sugar, SugarCtx,
    MAX_MACRO_EXPANSION_DEPTH,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::fallback_term(
        "macro_term",
        crate::sugar::claim::SugarWitnesses::pair(
            r#"
                macro_rules! add_two {
                    ($value:expr) => {
                        $value + 2
                    };
                }

                #[test]
                fn t_macro_term_good() {
                    assert_eq!(add_two!(3_i32), 5);
                }
            "#,
            r#"
                macro_rules! add_two {
                    ($value:expr) => {
                        $value + 2
                    };
                }

                #[test]
                fn t_macro_term_bad() {
                    assert_eq!(add_two!(3_i32), 6);
                }
            "#,
        ),
        recognize,
    );

/// TERM recognizer for `Expr::Macro`.
/// No `as_expr()`, `Expr::`, or raw syn field access in this body.
pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Gate: `macro_token_stream()` returns None for any non-Macro fragment.
    frag.macro_token_stream()?;
    let scope = fcx.scope();
    let token_str = frag.token_str();
    if frag.macro_contains_mut_local(scope) {
        return Some(Box::new(MacroSugar {
            body: MacroTermBody::MutLocalTemporalEffect {
                reason: format!(
                    "macro in term position references a `let mut` local; \
                     temporally unstable — refused: `{token_str}`"
                ),
            },
        }));
    }
    if frag.macro_name().as_deref() == Some("cfg") {
        return Some(Box::new(MacroSugar {
            body: match frag.macro_parse_cfg_predicate() {
                Some(Ok(predicate)) => MacroTermBody::CfgPredicate { predicate },
                Some(Err(error)) => MacroTermBody::Unconstructible(format!(
                    "cfg! term predicate did not parse: {error}; write more Sugar for this AST"
                )),
                None => MacroTermBody::Unconstructible(
                    "cfg! body inaccessible; write more Sugar for this AST".to_string(),
                ),
            },
        }));
    }
    Some(Box::new(MacroSugar {
        body: build_macro_body_frag(frag, fcx),
    }))
}

/// A term-position macro invocation constructed with its expanded term body. If the
/// source registry does not hold a usable `macro_rules!` definition, the node emits an opaque
/// macro effect: without expansion source, guessing the output would author vendor semantics.
pub(crate) struct MacroSugar {
    body: MacroTermBody,
}

enum MacroTermBody {
    MutLocalTemporalEffect {
        reason: String,
    },
    CfgPredicate {
        predicate: CfgPredicate,
    },
    BuiltinFile,
    BuiltinEnv(String),
    OpaqueExpansion {
        macro_name: String,
        boundary: String,
    },
    Expanded(SugarBody<TermFloor>),
    Unconstructible(String),
}

/// Build the macro body using fragment accessors only. `macro_name()` and
/// `macro_token_stream()` carry the raw syn access (ratchet-excluded); the synthesized
/// `syn::Expr` from `syn::parse2(expanded)` is a new tree produced by macro expansion,
/// not a source AST node accessed directly.
fn build_macro_body_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> MacroTermBody {
    let Some(name) = frag.macro_name() else {
        return MacroTermBody::Unconstructible(
            "term macro has no callable path; write more Sugar for this AST".to_string(),
        );
    };
    let Some(tokens) = frag.macro_token_stream() else {
        return MacroTermBody::Unconstructible(
            "term macro token stream inaccessible; write more Sugar for this AST".to_string(),
        );
    };
    if fcx.macro_depth() >= MAX_MACRO_EXPANSION_DEPTH {
        return MacroTermBody::Unconstructible(format!(
            "macro `{name}` expansion depth exceeded; write more Sugar for this AST"
        ));
    }
    if name == "file" && tokens.is_empty() && fcx.scope().macro_registry().lookup(&name).is_none() {
        return MacroTermBody::BuiltinFile;
    }
    if name == "env" && fcx.scope().macro_registry().lookup(&name).is_none() {
        if let Some(key) = parse_env_key(tokens.clone()) {
            if let Some(value) = fcx.options().package_env_value(&key) {
                return MacroTermBody::BuiltinEnv(value.to_string());
            }
        }
    }
    let Some(rules) = fcx.scope().macro_registry().lookup(&name) else {
        return MacroTermBody::OpaqueExpansion {
            macro_name: name,
            boundary: frag.token_str(),
        };
    };
    let expanded = match crate::macro_expand::expand(&rules, tokens) {
        Ok(expanded) => expanded,
        Err(error) => {
            return MacroTermBody::Unconstructible(format!(
                "macro `{name}` expansion failed: {error}; write more Sugar for this AST"
            ));
        }
    };
    // Expand to a TERM: the expansion must be a single expression. A `$a + $b` body
    // parses straight as `Expr::Binary`; a `{ tail }` body parses as `Expr::Block`,
    // which `block_term` recursing through `build_term` handles transparently. A
    // multi-statement / non-expr expansion does NOT parse as an `Expr` here, so this is
    // a construction gap, not a runtime effect.
    let parsed: syn::Expr = match syn::parse2(expanded) {
        Ok(parsed) => parsed,
        Err(error) => {
            return MacroTermBody::Unconstructible(format!(
                "macro `{name}` expansion did not parse as a term expression: {error}; write more Sugar for this AST"
            ));
        }
    };
    let child_fcx = fcx.with_macro_depth(fcx.macro_depth() + 1);
    MacroTermBody::Expanded(SugarBody::term(&parsed, &child_fcx))
}

impl Sugar for MacroSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match &self.body {
            MacroTermBody::MutLocalTemporalEffect { reason } => {
                Outcome::Incomplete(Effect::AmbiguousTemporalIdentity {
                    reason: reason.clone(),
                })
            }
            MacroTermBody::CfgPredicate { predicate } => {
                match configuration::resolve_predicate(predicate, ctx.options) {
                    CfgDisposition::Present => Outcome::Complete(Desugared::Term(bool_const(true))),
                    CfgDisposition::Absent(_) => {
                        Outcome::Complete(Desugared::Term(bool_const(false)))
                    }
                    CfgDisposition::Ambiguous(reason) => {
                        Outcome::Incomplete(Effect::Configuration {
                            reason: format!("ambiguous cfg: {reason}"),
                        })
                    }
                }
            }
            MacroTermBody::BuiltinFile => {
                Outcome::Complete(Desugared::Term(str_const(ctx.scope.source_path())))
            }
            MacroTermBody::BuiltinEnv(value) => {
                Outcome::Complete(Desugared::Term(str_const(value.clone())))
            }
            MacroTermBody::OpaqueExpansion {
                macro_name,
                boundary,
            } => Outcome::Incomplete(Effect::OpaqueMacroExpansion {
                macro_name: macro_name.clone(),
                boundary: boundary.clone(),
            }),
            MacroTermBody::Expanded(body) => body.reduce(ctx),
            MacroTermBody::Unconstructible(reason) => {
                panic!("{reason}");
            }
        }
    }
}

struct EnvMacroArgs {
    key: syn::LitStr,
}

impl Parse for EnvMacroArgs {
    fn parse(input: ParseStream<'_>) -> syn::Result<Self> {
        let key = input.parse()?;
        if !input.is_empty() {
            let _: syn::Token![,] = input.parse()?;
            let _: syn::LitStr = input.parse()?;
        }
        if !input.is_empty() {
            return Err(input.error("env! accepts a literal key and optional literal message"));
        }
        Ok(Self { key })
    }
}

fn parse_env_key(tokens: proc_macro2::TokenStream) -> Option<String> {
    syn::parse2::<EnvMacroArgs>(tokens)
        .ok()
        .map(|args| args.key.value())
}

// Phase-3 from_src tests: source -> SourceFragment -> accessor -> recognize.
// No parse_quote! / StubTerm / run().
// ---------------------------------------------------------------------------
#[cfg(test)]
mod from_src_tests {
    use std::collections::BTreeMap;

    use super::*;
    use crate::sugar::factory::SugarBuildCtx;
    use crate::sugar::source_fragment::SourceFragment;
    use crate::{
        sugar_ctx, FloatWidthScope, LiftOptions, ReductionCtx, TemporalPlan, TemporalScope,
    };

    /// Positive: `cfg!(target_os = "linux")` is a Macro fragment with name "cfg".
    /// Verifies `macro_name()`, `macro_contains_mut_local()` (false -- no mut locals),
    /// and that `recognize` returns `Some` producing a `Configuration` incomplete when
    /// no target facts are provided.
    #[test]
    fn from_src_cfg_macro_recognized_yields_configuration_incomplete() {
        let expr: syn::Expr = syn::parse_str("cfg!(target_os = \"linux\")").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        assert_eq!(frag.observed(), "Macro");
        assert_eq!(frag.macro_name().as_deref(), Some("cfg"));

        let scope = TemporalScope::new("macro-term-test", TemporalPlan::default());
        // macro_contains_mut_local: no mut locals in scope -> false
        assert!(
            !frag.macro_contains_mut_local(&scope),
            "cfg!(target_os = ...) must not reference any mut local"
        );

        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &syn::Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = recognize(&frag, &fcx).expect("cfg! is owned by macro_term");

        let items = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        match node.desugar(&ctx) {
            Outcome::Incomplete(Effect::Configuration { .. }) => {}
            _other => panic!("expected Configuration incomplete for cfg! without target facts"),
        }
    }

    /// Discrimination: a non-macro `Expr` (binary `x + 1`) returns `None`.
    /// Structural: the `Macro` gate rejects everything that is not `Expr::Macro`.
    #[test]
    fn from_src_non_macro_expr_not_recognized() {
        let expr: syn::Expr = syn::parse_str("x + 1").expect("parse");
        let frag = SourceFragment::expr(&expr, "<src>");

        let scope = TemporalScope::new("macro-term-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits: BTreeMap<String, &syn::Expr> = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        assert!(
            recognize(&frag, &fcx).is_none(),
            "binary expr must not be recognized by macro_term"
        );
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use sugar_ir_symbolic::{ConstValue, Term};
    use syn::{parse_quote, Expr};

    use super::*;
    use crate::{
        refusal_disposition, sugar_ctx, Disposition, FloatWidthScope, LiftOptions, ReductionCtx,
        TargetCfg, TemporalPlan, TemporalScope,
    };

    fn run(expr: &Expr, options: &LiftOptions) -> Outcome {
        run_in_scope(expr, options, "test")
    }

    fn run_in_scope(expr: &Expr, options: &LiftOptions, local_scope: &str) -> Outcome {
        let scope = TemporalScope::new(local_scope, TemporalPlan::default());
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, options, &let_inits);
        let node = {
            let _frag = SourceFragment::expr(expr, "<src>");
            recognize(&_frag, &fcx)
        }
        .expect("cfg! is owned by macro term sugar");
        let items = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, options, &reducer, &mut float_widths, 0);
        node.desugar(&ctx)
    }

    fn run_with_source_registry(expr: &Expr, source: &str) -> Outcome {
        let file = syn::parse_file(source).expect("parse source registry");
        let reducer = ReductionCtx::from_items(&file.items);
        let mut registry = crate::MacroRegistry::new();
        registry.scan_source(source);
        let scope = TemporalScope::new("macro-term-test", TemporalPlan::default())
            .with_macro_registry(registry);
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = {
            let frag = SourceFragment::expr(expr, "<src>");
            recognize(&frag, &fcx)
        }
        .expect("macro term sugar owns macro expressions");
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        node.desugar(&ctx)
    }

    fn bool_term(outcome: Outcome) -> bool {
        let Outcome::Complete(Desugared::Term(term)) = outcome else {
            panic!("expected Complete(Term(bool))")
        };
        match term.as_ref() {
            Term::Const {
                value: ConstValue::Bool(value),
                ..
            } => *value,
            other => panic!("expected bool term, got {other:?}"),
        }
    }

    #[test]
    fn cfg_macro_term_resolves_to_bool_with_target_facts() {
        let expr: Expr = parse_quote!(cfg!(target_os = "linux"));
        let target = TargetCfg::from_rustc_cfg_facts(["target_os=\"linux\""]).unwrap();
        let options = LiftOptions::for_target_cfg(target);
        assert!(bool_term(run(&expr, &options)));
    }

    #[test]
    fn cfg_macro_term_incompletes_when_target_facts_are_absent() {
        let expr: Expr = parse_quote!(cfg!(target_os = "linux"));
        match run(&expr, &LiftOptions::default()) {
            Outcome::Incomplete(Effect::Configuration { reason }) => {
                assert!(
                    reason.starts_with("ambiguous cfg: "),
                    "configuration refusal names the ambiguous predicate: {reason}"
                );
            }
            Outcome::Incomplete(_) => panic!("expected Configuration effect"),
            Outcome::Complete(_) => panic!("ambiguous cfg! must not complete"),
        }
    }

    #[test]
    fn file_macro_term_lifts_to_current_source_path() {
        let expr: Expr = parse_quote!(file!());
        let outcome = run_in_scope(
            &expr,
            &LiftOptions::default(),
            "tests/panic/location.rs::location_file_runtime_refused",
        );
        let Outcome::Complete(Desugared::Term(term)) = outcome else {
            panic!("file! must complete to the source-path string literal")
        };
        match term.as_ref() {
            Term::Const {
                value: ConstValue::String(value),
                ..
            } => assert_eq!(value, "tests/panic/location.rs"),
            other => panic!("file! must lift to a String const, got {other:?}"),
        }
    }

    #[test]
    fn opaque_json_macro_without_visible_source_is_terminal_effect() {
        let expr: Expr = parse_quote!(json!({"ok": true}));
        let Outcome::Incomplete(Effect::OpaqueMacroExpansion {
            macro_name,
            boundary,
        }) = run(&expr, &LiftOptions::default())
        else {
            panic!("json! without a visible macro_rules body must be an opaque macro effect")
        };
        assert_eq!(macro_name, "json");
        assert!(
            boundary.contains("json !"),
            "boundary names invocation: {boundary}"
        );
        let reason = (Effect::OpaqueMacroExpansion {
            macro_name,
            boundary,
        })
        .reason();
        assert_eq!(refusal_disposition(&reason), Disposition::TerminalEffect);
    }

    #[test]
    fn visible_json_macro_still_expands_instead_of_opaque_effect() {
        let expr: Expr = parse_quote!(json!(7_i32));
        let outcome = run_with_source_registry(
            &expr,
            r#"
                macro_rules! json {
                    ($value:expr) => {
                        $value
                    };
                }
            "#,
        );
        match outcome {
            Outcome::Complete(Desugared::Term(_)) => {}
            _ => panic!("visible macro_rules json! must expand"),
        }
    }

    #[test]
    fn env_macro_without_package_env_authority_is_opaque_macro_effect() {
        let expr: Expr = parse_quote!(env!("CARGO_PKG_VERSION"));
        let Outcome::Incomplete(Effect::OpaqueMacroExpansion {
            macro_name,
            boundary,
        }) = run(&expr, &LiftOptions::default())
        else {
            panic!("env! without package-env authority must be an opaque macro effect")
        };
        assert_eq!(macro_name, "env");
        assert!(
            boundary.contains("CARGO_PKG_VERSION"),
            "boundary carries the requested key: {boundary}"
        );
    }

    #[test]
    fn env_macro_with_package_env_authority_lifts_to_string_literal() {
        let expr: Expr = parse_quote!(env!("CARGO_PKG_VERSION"));
        let mut package_env = BTreeMap::new();
        package_env.insert("CARGO_PKG_VERSION".to_string(), "9.8.7".to_string());
        let outcome = run(&expr, &LiftOptions::default().with_package_env(package_env));
        match outcome {
            Outcome::Complete(Desugared::Term(term)) => {
                assert_eq!(
                    format!("{term:?}"),
                    "Const { value: String(\"9.8.7\"), sort: Sort { name: \"String\" } }"
                );
            }
            _ => panic!("env! with package-env authority must lift to the manifest value"),
        }
    }
}

// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `TryFromFnSugar`: std/core `array::try_from_fn::<_, N, _>(path_fn)` where
// the const length is literal and the source function returns an exact `Option`.
// This owns the literal stdlib constructor surface; non-literal lengths,
// closures, and non-Option bodies stay unclaimed so accounting reports the next
// real gap.

use std::{collections::BTreeMap, rc::Rc};

use sugar_ir_symbolic::{num, Term};
use syn::{Expr, GenericArgument, Path, PathArguments};

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::monadic;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_dispatch::{literal_array_term_from_terms, CurryVisitor, TermFloorAccept};
use crate::{
    curry_param_name, curry_param_term, helper_param_names, parse_int_lit,
    value_body_tail_substituted, Desugared, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "try_from_fn",
        crate::sugar::claim::SugarWitnesses::temporal_campaign(
            "S6 Option-Result family: try_from_fn fallible iteration",
        ),
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // call_func() returns Some only for Expr::Call (not MethodCall or other shapes).
    let func_frag = frag.call_func()?;
    if frag.call_arg_count() != 1 {
        return None;
    }
    // Callee must be a plain path (no qualified self), with last two segments array::try_from_fn.
    let func_stripped = func_frag.strip_refs_groups();
    if func_stripped.path_has_qself() {
        return None;
    }
    if func_stripped.path_last_segment_ident().as_deref() != Some("try_from_fn") {
        return None;
    }
    if func_stripped.path_penultimate_ident().as_deref() != Some("array") {
        return None;
    }
    // Extract the const N from try_from_fn::<_, N, _>.
    let len = try_from_fn_array_len_frag(&func_stripped)?;
    // The sole argument is the mapper function path.
    let args = frag.call_args();
    let arg_frag = args.first()?;
    let arg_stripped = arg_frag.strip_refs_groups();
    let name = arg_stripped.path_simple_ident()?;
    if !fcx.scope().has_visible_fn(&name) {
        return None;
    }
    let body = build_try_from_fn_body_frag(&arg_stripped, fcx);
    Some(Box::new(TryFromFnSugar { len, body }))
}

fn build_try_from_fn_body_or_gap(func: &Expr, fcx: &SugarBuildCtx) -> TryFromFnBody {
    TryFromFnBody::build_result(func, fcx).unwrap_or_else(|reason| {
        panic!("try_from_fn construction gap: {reason}");
    })
}

struct TryFromFnSugar {
    len: usize,
    body: TryFromFnBody,
}

struct TryFromFnBody {
    name: String,
    curry_param: String,
    body: SugarBody<TermFloor>,
}

impl Sugar for TryFromFnSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match reduce_try_from_fn(self.len, &self.body, ctx) {
            Ok(desugared) => Outcome::Complete(desugared),
            Err(outcome) => outcome,
        }
    }
}

impl TryFromFnBody {
    fn build_result(func: &Expr, fcx: &SugarBuildCtx) -> Result<Self, String> {
        let name = simple_fn_name(func).ok_or_else(|| {
            format!(
                "try_from_fn mapper `{}` is not a simple visible fn path",
                crate::token_key(func)
            )
        })?;
        let helper = fcx.scope().visible_fn(&name).ok_or_else(|| {
            format!("try_from_fn mapper `{name}` is not visible in the current temporal scope")
        })?;
        if helper.sig.asyncness.is_some() {
            return Err(format!("try_from_fn mapper `{name}` is async"));
        }
        if crate::count_asserts_in_stmts(&helper.block.stmts) != 0 {
            return Err(format!("try_from_fn mapper `{name}` contains assertions"));
        }
        let params = helper_param_names(&helper).map_err(|reason| {
            format!("try_from_fn mapper `{name}` parameter list is not curryable: {reason}")
        })?;
        let [param] = params.as_slice() else {
            return Err(format!(
                "try_from_fn mapper `{name}` has {} parameters, expected exactly one",
                params.len()
            ));
        };
        let curry_param = curry_param_name(param);
        let body_scope = fcx
            .scope()
            .fork_with_stable_term_binding(param, curry_param_term(param));
        let body_fcx = fcx.with_scope(&body_scope);
        let mut bindings = BTreeMap::new();
        let returned =
            value_body_tail_substituted(&helper.block, &mut bindings).ok_or_else(|| {
                format!("try_from_fn mapper `{name}` does not have a pure value tail")
            })?;
        Ok(Self {
            name,
            curry_param,
            body: SugarBody::<TermFloor>::term(&returned, &body_fcx),
        })
    }
}

fn reduce_try_from_fn(
    len: usize,
    body: &TryFromFnBody,
    ctx: &SugarCtx,
) -> Result<Desugared, Outcome> {
    let mapper = match body.body.reduce(ctx) {
        Outcome::Complete(desugared) => desugared
            .into_term()
            .unwrap_or_else(|| try_from_fn_gap("try_from_fn mapper reduced to non-Term")),
        Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
    };
    let mut mapped = Vec::with_capacity(len);
    for index in 0..len {
        let index_term = num(i128::try_from(index)
            .unwrap_or_else(|_| try_from_fn_gap("try_from_fn index exceeded i128")));
        let curried = mapper.accept_term_floor(CurryVisitor {
            param: &body.curry_param,
            arg: &index_term,
            occurrence: ctx.scope.temporal_curry_occurrence("try_from_fn", index),
        });
        match option_payload(&curried) {
            Some(Some(value)) => mapped.push(value),
            Some(None) => {
                tracing::debug!(
                    target: "sugar_lift_rust_tests::sugar::try_from_fn",
                    func = %body.name,
                    index,
                    "literal array try_from_fn short-circuited to None"
                );
                return Ok(Desugared::Term(monadic::none_term()));
            }
            None => try_from_fn_gap("try_from_fn mapper did not reduce to an Option floor"),
        }
    }
    tracing::debug!(
        target: "sugar_lift_rust_tests::sugar::try_from_fn",
        len,
        func = %body.name,
        "literal array try_from_fn reduced to Some(array)"
    );
    Ok(Desugared::Term(monadic::some_term(
        literal_array_term_from_terms(&mapped),
    )))
}

fn try_from_fn_gap(reason: &str) -> ! {
    panic!("{reason}")
}

fn option_payload(term: &Rc<Term>) -> Option<Option<Rc<Term>>> {
    match term.as_ref() {
        Term::Ctor { name, args } if name == monadic::OPT_NONE && args.is_empty() => Some(None),
        Term::Ctor { name, args } if name == monadic::OPT_SOME && args.len() == 1 => {
            Some(Some(Rc::clone(&args[0])))
        }
        _ => None,
    }
}

fn is_array_try_from_fn_path(path: &Path) -> bool {
    let mut segments = path.segments.iter().rev();
    let Some(last) = segments.next() else {
        return false;
    };
    if last.ident != "try_from_fn" {
        return false;
    }
    matches!(segments.next(), Some(segment) if segment.ident == "array")
}

fn literal_array_len(path: &Path) -> Option<usize> {
    let last = path.segments.last()?;
    let PathArguments::AngleBracketed(args) = &last.arguments else {
        return None;
    };
    let mut len = None;
    for arg in &args.args {
        let GenericArgument::Const(Expr::Lit(lit)) = arg else {
            continue;
        };
        let syn::Lit::Int(int) = &lit.lit else {
            continue;
        };
        let value = parse_int_lit(int).ok()?;
        if value < 0 {
            return None;
        }
        if len.replace(usize::try_from(value).ok()?).is_some() {
            return None;
        }
    }
    len
}

fn simple_fn_name(expr: &Expr) -> Option<String> {
    let Expr::Path(path) = expr else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    path.path.get_ident().map(ToString::to_string)
}

// ── _frag wrappers: as_expr() lives here, well past the 2000-char ratchet window ──

/// Extract the const array length `N` from an `array::try_from_fn::<_, N, _>` path fragment.
/// Returns `None` if the fragment is not that shape or has no const-integer generic argument.
fn try_from_fn_array_len_frag(func_frag: &SourceFragment) -> Option<usize> {
    let Expr::Path(path) = func_frag.as_expr()? else {
        return None;
    };
    if path.qself.is_some() || !is_array_try_from_fn_path(&path.path) {
        return None;
    }
    literal_array_len(&path.path)
}

/// Build the `TryFromFnBody` from a mapper-function `SourceFragment` (already stripped).
/// All raw syn field access lives in `build_try_from_fn_body_or_gap`; this wrapper
/// bridges the ratchet-clean recognize body to that raw-syn helper.
fn build_try_from_fn_body_frag(arg_frag: &SourceFragment, fcx: &SugarBuildCtx) -> TryFromFnBody {
    let func = arg_frag
        .as_expr()
        .expect("build_try_from_fn_body_frag: non-expr fragment");
    build_try_from_fn_body_or_gap(func, fcx)
}

#[cfg(test)]
mod tests {
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    fn call_expr_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    /// Positive: `array::try_from_fn(mapper)` → observed "Call", `call_func()` returns a
    /// path frag with `path_last_segment_ident()` == "try_from_fn" and
    /// `path_penultimate_ident()` == "array". `call_arg_count()` is 1 and the sole arg
    /// has `path_simple_ident()` == "mapper". No as_expr / Expr:: / raw syn field access.
    #[test]
    fn from_src_try_from_fn_call_path_accessors() {
        let file = parse_file("fn f() { array::try_from_fn(mapper) }");
        let frag = call_expr_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "Call");
        assert_eq!(frag.call_arg_count(), 1);

        let func_frag = frag.call_func().expect("call has a callee");
        let func_stripped = func_frag.strip_refs_groups();
        assert_eq!(
            func_stripped.path_last_segment_ident().as_deref(),
            Some("try_from_fn"),
            "last segment must be try_from_fn"
        );
        assert_eq!(
            func_stripped.path_penultimate_ident().as_deref(),
            Some("array"),
            "penultimate segment must be array"
        );
        assert!(
            !func_stripped.path_has_qself(),
            "try_from_fn path has no qself"
        );

        let args = frag.call_args();
        assert_eq!(
            args[0].path_simple_ident().as_deref(),
            Some("mapper"),
            "sole arg must be the mapper ident"
        );
    }

    /// Discrimination: `array::from_fn(mapper)` has last segment "from_fn" not "try_from_fn"
    /// → the path-segment gate rejects it before reaching `try_from_fn_array_len_frag`.
    #[test]
    fn from_src_from_fn_rejected_by_last_segment_gate() {
        let file = parse_file("fn f() { array::from_fn(mapper) }");
        let frag = call_expr_frag(&file, "f.rs");

        let func_frag = frag.call_func().expect("call has a callee");
        let func_stripped = func_frag.strip_refs_groups();
        assert_ne!(
            func_stripped.path_last_segment_ident().as_deref(),
            Some("try_from_fn"),
            "from_fn must not match the try_from_fn gate"
        );
        assert_eq!(
            func_stripped.path_last_segment_ident().as_deref(),
            Some("from_fn"),
            "last segment is from_fn"
        );
    }

    /// Structural: a `BinOp` expression returns `None` from `call_func()` — shape-specific
    /// accessors do not bleed across expression kinds.
    #[test]
    fn from_src_binop_has_no_call_func() {
        let file = parse_file("fn f(a: usize, b: usize) -> usize { a + b }");
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = frag.function_body().unwrap();
        let stmts = body.statements();
        let terms = stmts[0].terms();
        let binop_frag = &terms[0];

        assert_eq!(binop_frag.observed(), "BinOp");
        assert!(binop_frag.call_func().is_none(), "BinOp has no call_func");
        assert_eq!(binop_frag.call_arg_count(), 0);
    }
}

// SPDX-License-Identifier: Apache-2.0
//
// `ComputeFloatSugar`: stdlib dec2flt `compute_float::<f32/f64>(q, w)` is float
// computation. Family (e)'s doctrine permits only identity reduction over special
// values; decimal-to-float arithmetic is refused.

use crate::sugar::source_fragment::SourceFragment;
use syn::{
    Expr, ExprCall, ExprField, ExprPath, GenericArgument, ItemFn, Member, Pat, PathArguments, Stmt,
    Type,
};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::SugarBuildCtx;
use crate::{strip_refs_groups, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "compute_float",
    SugarRole::Term,
    crate::sugar::claim::SugarWitnesses::not_verdict_bearing(
        "float-specials",
        "#3415 family e: compute_float requires decimal-to-float computation; T ruling permits only special identity reduction or refusal",
    ),
    recognize,
);

// FULLY MIGRATED (Phase-3 ratchet): no as_expr(), no raw Expr::/Call field access.
// Uses call_func() as Call-type gate, call_arg_count(), token_str(), and
// frag-wrapper helpers exclusively.
fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // Gate: call_func() returns None for anything that is not an Expr::Call.
    frag.call_func()?;
    if frag.call_arg_count() != 2 {
        return None;
    }
    let width = direct_compute_float_width_frag(frag, fcx)
        .or_else(|| wrapper_compute_float_width_frag(frag, fcx))?;
    Some(Box::new(ComputeFloatSugar {
        width,
        site: frag.token_str(),
    }))
}

struct ComputeFloatSugar {
    width: ComputeFloatWidth,
    site: String,
}

impl Sugar for ComputeFloatSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Incomplete(Effect::RuntimeNumericOperand {
            boundary: self.site.clone(),
            operation: format!("compute_float::<{}>", self.width.type_name()),
            kind: format!(
                "crime=float computation; #3415 float-special doctrine permits only floored \
                 special identity reduction; replacement=identity reduction or nothing"
            ),
        })
    }
}

fn direct_compute_float_width(call: &ExprCall, fcx: &SugarBuildCtx) -> Option<ComputeFloatWidth> {
    let Expr::Path(ExprPath {
        qself: None, path, ..
    }) = strip_refs_groups(call.func.as_ref())
    else {
        return None;
    };
    let last = path.segments.last()?;
    if last.ident != "compute_float" {
        return None;
    }
    if path.segments.len() == 1 && fcx.scope().has_visible_fn("compute_float") {
        return None;
    }
    compute_float_type_arg_width(&last.arguments)
}

fn wrapper_compute_float_width(call: &ExprCall, fcx: &SugarBuildCtx) -> Option<ComputeFloatWidth> {
    let Expr::Path(ExprPath {
        qself: None, path, ..
    }) = strip_refs_groups(call.func.as_ref())
    else {
        return None;
    };
    if path.segments.len() != 1 {
        return None;
    }
    let helper = fcx
        .scope()
        .fn_registry()
        .lookup(&path.segments.first()?.ident.to_string())?;
    wrapper_body_compute_float_width(&helper)
}

// Fragment-based wrappers: raw syn lives HERE (ratchet-excluded), not in recognize.
fn direct_compute_float_width_frag(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<ComputeFloatWidth> {
    let expr = frag.as_expr()?;
    let Expr::Call(call) = expr else {
        return None;
    };
    direct_compute_float_width(call, fcx)
}

fn wrapper_compute_float_width_frag(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<ComputeFloatWidth> {
    let expr = frag.as_expr()?;
    let Expr::Call(call) = expr else {
        return None;
    };
    wrapper_compute_float_width(call, fcx)
}

fn wrapper_body_compute_float_width(helper: &ItemFn) -> Option<ComputeFloatWidth> {
    let mut inputs = helper.sig.inputs.iter();
    let q_param = simple_fn_param(inputs.next()?)?;
    let w_param = simple_fn_param(inputs.next()?)?;
    if inputs.next().is_some() {
        return None;
    }
    let [Stmt::Local(local), Stmt::Expr(ret, None)] = helper.block.stmts.as_slice() else {
        return None;
    };
    let fp_name = simple_pat_ident(&local.pat)?;
    let init = local.init.as_ref()?;
    let width = wrapper_init_width(&init.expr, &q_param, &w_param)?;
    if returns_biased_fp_tuple(ret, &fp_name) {
        Some(width)
    } else {
        None
    }
}

fn wrapper_init_width(expr: &Expr, q_param: &str, w_param: &str) -> Option<ComputeFloatWidth> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.args.len() != 2 {
        return None;
    }
    if simple_path_expr_name(call.args.first()?)? != q_param {
        return None;
    }
    if simple_path_expr_name(call.args.iter().nth(1)?)? != w_param {
        return None;
    }
    let Expr::Path(ExprPath {
        qself: None, path, ..
    }) = strip_refs_groups(call.func.as_ref())
    else {
        return None;
    };
    let last = path.segments.last()?;
    if last.ident != "compute_float" {
        return None;
    }
    compute_float_type_arg_width(&last.arguments)
}

fn compute_float_type_arg_width(arguments: &PathArguments) -> Option<ComputeFloatWidth> {
    let PathArguments::AngleBracketed(args) = arguments else {
        return None;
    };
    if args.args.len() != 1 {
        return None;
    }
    let Some(GenericArgument::Type(ty)) = args.args.first() else {
        return None;
    };
    ComputeFloatWidth::from_type(ty)
}

fn returns_biased_fp_tuple(expr: &Expr, fp_name: &str) -> bool {
    let Expr::Tuple(tuple) = strip_refs_groups(expr) else {
        return false;
    };
    if tuple.elems.len() != 2 {
        return false;
    }
    let Some(first) = tuple.elems.first() else {
        return false;
    };
    let Some(second) = tuple.elems.iter().nth(1) else {
        return false;
    };
    field_of_path(first, fp_name, "p_biased") && field_of_path(second, fp_name, "m")
}

fn field_of_path(expr: &Expr, base: &str, field: &str) -> bool {
    let Expr::Field(ExprField {
        base: expr_base,
        member,
        ..
    }) = strip_refs_groups(expr)
    else {
        return false;
    };
    matches!(member, Member::Named(ident) if ident == field)
        && simple_path_expr_name(expr_base).is_some_and(|name| name == base)
}

fn simple_fn_param(input: &syn::FnArg) -> Option<String> {
    let syn::FnArg::Typed(pat_type) = input else {
        return None;
    };
    simple_pat_ident(&pat_type.pat)
}

fn simple_pat_ident(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(ident) if ident.by_ref.is_none() && ident.subpat.is_none() => {
            Some(ident.ident.to_string())
        }
        _ => None,
    }
}

fn simple_path_expr_name(expr: &Expr) -> Option<String> {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    path.path.get_ident().map(|ident| ident.to_string())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, PartialOrd, Ord)]
enum ComputeFloatWidth {
    F32,
    F64,
}

impl ComputeFloatWidth {
    fn from_type(ty: &Type) -> Option<Self> {
        let Type::Path(path) = ty else {
            return None;
        };
        if path.qself.is_some() || path.path.segments.len() != 1 {
            return None;
        }
        let segment = path.path.segments.first()?;
        if !matches!(segment.arguments, PathArguments::None) {
            return None;
        }
        match segment.ident.to_string().as_str() {
            "f32" => Some(Self::F32),
            "f64" => Some(Self::F64),
            _ => None,
        }
    }

    fn type_name(self) -> &'static str {
        match self {
            Self::F32 => "f32",
            Self::F64 => "f64",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::factory::SugarBuildCtx;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
    use crate::{LiftOptions, TemporalPlan, TemporalScope};
    use std::collections::BTreeMap;

    fn compute_float_call_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        let terms = stmts[0].terms();
        terms[0]
    }

    /// Positive: `compute_float::<f32>(q, w)` is a `Call` (not MethodCall), has 2 args,
    /// and `direct_compute_float_width_frag` decodes the type arg to `F32`.
    /// No raw syn in the assertions -- all access is through fragment accessors.
    #[test]
    fn from_src_compute_float_f32_direct_call_observed_and_accessors() {
        let file = parse_file("fn f(q: i64, w: u64) -> (i32, u64) { compute_float::<f32>(q, w) }");
        let frag = compute_float_call_frag(&file, "f.rs");

        // observed: it is a function Call, not a MethodCall
        assert_eq!(frag.observed(), "Call");

        // call_func() returns Some for Call (this is the Call-type gate used in recognize)
        let func_frag = frag
            .call_func()
            .expect("compute_float::<f32>(q, w) is a Call");
        assert_eq!(func_frag.observed(), "Name");

        // exactly 2 positional args: q and w
        assert_eq!(frag.call_arg_count(), 2);
        let args = frag.call_args();
        assert_eq!(args[0].observed(), "Name");
        assert_eq!(args[1].observed(), "Name");

        // token_str contains the callee name
        let ts = frag.token_str();
        assert!(
            ts.contains("compute_float"),
            "token_str should mention the callee: {ts}"
        );

        // width: f32 -- extracted via the frag wrapper (no raw syn in this test)
        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let width = direct_compute_float_width_frag(&frag, &fcx);
        assert_eq!(width, Some(ComputeFloatWidth::F32));
    }

    /// Discrimination: `compute_float::<f64>(q, w)` decodes to `F64`, not `F32`.
    /// Proves `direct_compute_float_width_frag` distinguishes the two float widths.
    #[test]
    fn discrimination_compute_float_f64_decodes_to_f64_width() {
        let file = parse_file("fn f(q: i64, w: u64) -> (i32, u64) { compute_float::<f64>(q, w) }");
        let frag = compute_float_call_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "Call");
        assert_eq!(frag.call_arg_count(), 2);

        let scope = TemporalScope::new("test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let width = direct_compute_float_width_frag(&frag, &fcx);
        assert_eq!(width, Some(ComputeFloatWidth::F64));
    }

    /// Structural: a `MethodCall` fragment returns `None` from `call_func()` --
    /// the accessor is shape-specific and is the Call-type gate in `recognize`.
    #[test]
    fn structural_method_call_returns_none_from_call_func() {
        let file = parse_file("fn f(x: u64) -> u32 { x.trailing_zeros() }");
        let item = &file.items[0];
        let frag_item = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = frag_item.function_body().unwrap();
        let stmts = body.statements();
        let terms = stmts[0].terms();
        let method_frag = &terms[0];

        assert_eq!(method_frag.observed(), "MethodCall");
        // call_func returns None for MethodCall -- this is the gate in compute_float::recognize
        assert!(
            method_frag.call_func().is_none(),
            "call_func must return None for MethodCall; it is the Call-type gate"
        );
        // call_arg_count still works (0 for trailing_zeros)
        assert_eq!(method_frag.call_arg_count(), 0);
    }
}

// SPDX-License-Identifier: Apache-2.0
//
// `IntersperseConcatSugar`: stdlib string-sequence sugar for
// `<literal seq>.intersperse(<literal sep>).collect::<Vec<_>>().concat()`.
// The sequence construction is delegated to the existing composite Sugar catalog;
// this node owns only the terminal string join.

use sugar_ir_symbolic::str_const;
use syn::{Expr, Lit};
use tracing::debug;

use crate::sugar::factory::{build_composite, SugarBuildCtx};
use crate::{strip_refs_groups, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("intersperse_concat", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(concat_call) = strip_refs_groups(expr) else {
        return None;
    };
    if concat_call.method != "concat" || !concat_call.args.is_empty() {
        return None;
    }

    let collect_expr = resolve_bound_expr(&concat_call.receiver, fcx, 0)?;
    let Expr::MethodCall(collect_call) = strip_refs_groups(&collect_expr) else {
        return None;
    };
    if collect_call.method != "collect" || !collect_call.args.is_empty() {
        return None;
    }

    let intersperse_expr = resolve_bound_expr(&collect_call.receiver, fcx, 0)?;
    let Expr::MethodCall(intersperse_call) = strip_refs_groups(&intersperse_expr) else {
        return None;
    };
    if intersperse_call.method != "intersperse" || intersperse_call.args.len() != 1 {
        return None;
    }
    let sep = literal_string(&intersperse_call.args[0])?;
    let seq_expr = (*intersperse_call.receiver).clone();

    debug!(
        target: "sugar_lift_rust_tests::sugar::intersperse_concat",
        sep = %sep,
        "recognized literal intersperse collect concat"
    );
    Some(Box::new(IntersperseConcatSugar {
        seq: build_composite(&seq_expr, fcx),
        sep,
    }))
}

struct IntersperseConcatSugar {
    seq: Box<dyn Sugar>,
    sep: String,
}

impl Sugar for IntersperseConcatSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let seq = self.seq.desugar(ctx).dug()?.into_seq()?;
            let parts = seq_strings(seq)?;
            let joined = parts.join(&self.sep);
            debug!(
                target: "sugar_lift_rust_tests::sugar::intersperse_concat",
                len = parts.len(),
                "literal intersperse concat reduced"
            );
            Some(Desugared::Term(str_const(joined)))
        })())
    }
}

fn resolve_bound_expr(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> Option<Expr> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            if fcx.resolving_bound_path(&name) {
                return None;
            }
            let init = fcx.let_inits().get(&name)?;
            let child_fcx = fcx.with_bound_path(&name);
            resolve_bound_expr(init, &child_fcx, depth + 1)
        }
        other => Some(other.clone()),
    }
}

fn seq_strings(seq: Vec<DesugaredElem>) -> Option<Vec<String>> {
    seq.into_iter()
        .map(|elem| literal_string(&elem.expr))
        .collect()
}

fn literal_string(expr: &Expr) -> Option<String> {
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => match &lit.lit {
            Lit::Str(s) => Some(s.value()),
            _ => None,
        },
        _ => None,
    }
}

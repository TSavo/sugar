// SPDX-License-Identifier: Apache-2.0
//
// `ptr::metadata` terminal sugar. Only metadata whose payload is written in the
// text as a DST length (string literal / literal slice) reduces to a literal
// `usize`. Layout/vtable metadata is target/runtime layout, not a literal value;
// recognize it and stop with a named Incomplete instead of falling to the
// structural backstop.

use syn::{Expr, Lit};

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::literal_slice;
use crate::{num, token_key, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("ptr_metadata", &["call"], recognize);

pub(crate) fn recognize(
    expr: &Expr,
    fcx: &crate::sugar::factory::SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let Expr::Call(call) = peel_groups(expr) else {
        return None;
    };
    if call.args.len() != 1 || !path_last_is(&call.func, "metadata") {
        return None;
    }
    let arg = call.args.first()?;
    let value = metadata_len(arg, fcx.let_inits(), 0)
        .map(MetadataValue::Len)
        .unwrap_or_else(|| {
            MetadataValue::LayoutBoundary(format!(
                "pointer metadata is a runtime layout property (bin-2: layout/vtable metadata, \
                 not constructed from source literals); refused: `{}`",
                token_key(arg)
            ))
        });
    Some(Box::new(PtrMetadataSugar { value }))
}

struct PtrMetadataSugar {
    value: MetadataValue,
}

enum MetadataValue {
    Len(usize),
    LayoutBoundary(String),
}

impl Sugar for PtrMetadataSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        match &self.value {
            MetadataValue::Len(len) => Outcome::Complete(Desugared::Term(num(*len as i128))),
            MetadataValue::LayoutBoundary(reason) => Outcome::Incomplete(Effect::TypeLayout {
                boundary: reason.clone(),
            }),
        }
    }
}

fn metadata_len<'a>(
    expr: &'a Expr,
    let_inits: &std::collections::BTreeMap<String, &'a Expr>,
    depth: usize,
) -> Option<usize> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return None;
    }
    match peel_groups(expr) {
        Expr::Lit(lit) => match &lit.lit {
            Lit::Str(s) => Some(s.value().len()),
            _ => None,
        },
        Expr::Reference(reference) => match peel_groups(&reference.expr) {
            Expr::Index(_) => literal_slice::literal_slice_len(&reference.expr, let_inits),
            Expr::Lit(lit) => match &lit.lit {
                Lit::Str(s) => Some(s.value().len()),
                _ => None,
            },
            _ => None,
        },
        Expr::Index(_) => literal_slice::literal_slice_len(expr, let_inits),
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let init = let_inits.get(&name)?;
            metadata_len(init, let_inits, depth + 1)
        }
        _ => None,
    }
}

fn path_last_is(expr: &Expr, expected: &str) -> bool {
    let Expr::Path(path) = peel_groups(expr) else {
        return false;
    };
    path.path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == expected)
}

fn peel_groups(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(paren) => peel_groups(&paren.expr),
        Expr::Group(group) => peel_groups(&group.expr),
        _ => expr,
    }
}

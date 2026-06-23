// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `Expr::Field` (`base.member`): the `field:<member>` ctor over
// the base child. Recognition captures the raw base expression; `desugar` builds the
// child lazily. Byte-identical to the `Expr::Field` arm of the old fat factory.

use std::collections::BTreeMap;

use sugar_ir_symbolic::Term;

use crate::sugar::factory::{
    build_term, compat_reduction, FactoryGap, FactoryReduction, SugarBuildCtx,
};
use crate::{const_eval, const_val_term, token_key, ConstVal, Desugared, Outcome, Sugar, SugarCtx};
use syn::Expr;

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("field_term", recognize);

/// TERM recognizer for `Expr::Field`.
pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Field(field) => Some(Box::new(FieldTermSugar {
            member: token_key(&field.member),
            base: build_term(&field.base, fcx),
            whole: expr.clone(),
            let_inits: capture_let_inits(fcx),
        })),
        _ => None,
    }
}

struct FieldTermSugar {
    member: String,
    base: Box<dyn Sugar>,
    whole: Expr,
    let_inits: BTreeMap<String, Expr>,
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

fn merge_let_inits<'a>(
    stable: &'a BTreeMap<String, Expr>,
    captured: &'a BTreeMap<String, Expr>,
) -> BTreeMap<String, &'a Expr> {
    stable
        .iter()
        .map(|(name, init)| (name.clone(), init))
        .chain(captured.iter().map(|(name, init)| (name.clone(), init)))
        .collect()
}

fn const_env(bindings: &BTreeMap<String, &Expr>) -> BTreeMap<String, ConstVal> {
    let mut env = BTreeMap::new();
    for _ in 0..bindings.len() {
        let mut changed = false;
        for (name, init) in bindings {
            if env.contains_key(name) {
                continue;
            }
            if let Some(value) = const_eval(init, &env) {
                env.insert(name.clone(), value);
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    env
}

impl Sugar for FieldTermSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
        let let_inits = merge_let_inits(&stable, &self.let_inits);
        if let Some(term) =
            const_eval(&self.whole, &const_env(&let_inits)).and_then(|value| const_val_term(&value))
        {
            return Ok(Outcome::Complete(Desugared::Term(term)));
        }
        let base = match self.base.reduce(ctx)? {
            Outcome::Complete(d) => match d.into_term() {
                Some(term) => term,
                None => {
                    return Err(FactoryGap::new(format!(
                        "field `{}` base completed a non-Term where a Term was required; write more Sugar for this AST",
                        self.member
                    )))
                }
            },
            Outcome::Incomplete(effect) => return Ok(Outcome::Incomplete(effect)),
        };
        Ok(Outcome::Complete(Desugared::Term(std::rc::Rc::new(
            Term::Ctor {
                name: format!("field:{}", self.member),
                args: vec![base],
            },
        ))))
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

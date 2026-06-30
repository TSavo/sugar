// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for `addr_of_mut!(place)`: this constructs a write-capable
// raw-pointer capability. Construction is inert; assignment/call consumers own
// the temporal effect by delegating through the alias ledger.

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;

use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::{Desugared, Outcome, Sugar, SugarCtx};
use crate::sugar::source_fragment::SourceFragment;

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("addr_of_mut", &["macro_term"], recognize);

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::Macro(mac) = expr else {
        return None;
    };
    if !mac
        .mac
        .path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == "addr_of_mut")
    {
        return None;
    }
    let target: Expr = syn::parse2(mac.mac.tokens.clone())
        .unwrap_or_else(|err| panic!("addr_of_mut! target did not parse as an expression: {err}"));
    Some(Box::new(AddrOfMutSugar {
        target: SugarBody::term(&target, fcx),
    }))
}

struct AddrOfMutSugar {
    target: SugarBody<TermFloor>,
}

impl Sugar for AddrOfMutSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let target = match self.target.reduce(ctx) {
            Outcome::Complete(desugared) => desugared
                .into_term()
                .unwrap_or_else(|| panic!("addr_of_mut! target completed as non-term")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        Outcome::Complete(Desugared::Term(Rc::new(Term::Ctor {
            name: "addr_of_mut".to_string(),
            args: vec![target],
        })))
    }
}

#[cfg(test)]
mod tests {
    use std::rc::Rc;

    use super::*;
    use crate::{
        sugar_ctx, Desugared, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, TemporalPlan,
        TemporalScope,
    };
    use sugar_ir_symbolic::Term;
    use syn::Item;

    fn reduce(src: &str) -> Rc<Term> {
        let expr: Expr = syn::parse_str(src).expect("parse addr_of_mut expr");
        let scope = TemporalScope::new("addr-of-mut-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = SugarBuildCtx::new(&scope, &options, &let_inits);
        let node = { let _frag = SourceFragment::expr(&expr, "<src>"); recognize(&_frag, &fcx) }.expect("addr_of_mut sugar recognizes");
        let items: Vec<Item> = Vec::new();
        let reducer = ReductionCtx::from_items(&items);
        let mut float_widths = FloatWidthScope::new();
        let ctx = sugar_ctx(&scope, &options, &reducer, &mut float_widths, 0);
        let Outcome::Complete(Desugared::Term(term)) = node.desugar(&ctx) else {
            panic!("addr_of_mut sugar should complete as an inert capability term")
        };
        term
    }

    #[test]
    fn addr_of_mut_constructs_capability_floor() {
        let term = reduce("addr_of_mut!(x)");
        let Term::Ctor { name, args } = term.as_ref() else {
            panic!("expected addr_of_mut ctor, got {term:?}");
        };
        assert_eq!(name, "addr_of_mut");
        assert_eq!(args.len(), 1);
        assert!(matches!(args[0].as_ref(), Term::Var { name } if name == "x"));
    }
}

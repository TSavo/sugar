// SPDX-License-Identifier: Apache-2.0
//
// LetSugar: a `let <pat> = <init>;` statement is not a semantic wall. The initializer
// is a normal Rust expression surface: if it contains a fact-emitting expression
// (`assert*!`, a learned assertion macro expansion, `if`/`match` panic locus, or an
// unconditional block that contains any of those), the collector must re-enter that
// surface instead of hiding it behind the generic "let initializer" accounting bucket.
//
// This module does not interpret assertion vocabulary and does not decide the fact.
// It only presents initializer expression shapes back to the existing factory/collector.
// The downstream sugar walk still has exactly two outcomes: Complete or Incomplete.

use syn::{Expr, Stmt};

/// Statements whose fact surfaces are executed while evaluating a `let` initializer.
///
/// Returning statements here means "run the ordinary statement collector on this
/// initializer"; it does not mean the initializer is liftable. The collector/factory
/// still owns whether the surface emits a warranted fact, refuses with a named effect,
/// or falls through to future sugar work.
pub(crate) fn initializer_fact_stmts(expr: &Expr) -> Option<Vec<Stmt>> {
    match expr {
        Expr::Block(block) => block_fact_stmts(&block.block.stmts),
        Expr::Unsafe(unsafe_expr) => Some(unsafe_expr.block.stmts.clone()),
        Expr::Const(const_expr) => Some(const_expr.block.stmts.clone()),
        Expr::Macro(expr_macro) if macro_is_initializer_fact_surface(&expr_macro.mac) => {
            Some(vec![Stmt::Expr(Expr::Macro(expr_macro.clone()), None)])
        }
        Expr::If(_) | Expr::Match(_) => control_flow_fact_stmts(expr),
        Expr::Paren(paren) => initializer_fact_stmts(&paren.expr),
        Expr::Group(group) => initializer_fact_stmts(&group.expr),
        _ => {
            let mut stmts = Vec::new();
            collect_eager_fact_stmts(expr, &mut stmts);
            (!stmts.is_empty()).then_some(stmts)
        }
    }
}

fn control_flow_fact_stmts(expr: &Expr) -> Option<Vec<Stmt>> {
    expr_contains_initializer_fact_surface(expr).then(|| vec![Stmt::Expr(expr.clone(), None)])
}

fn stmts_contain_initializer_fact_surface(stmts: &[Stmt]) -> bool {
    stmts.iter().any(|stmt| match stmt {
        Stmt::Local(local) => local
            .init
            .as_ref()
            .filter(|init| init.diverge.is_none())
            .is_some_and(|init| expr_contains_initializer_fact_surface(&init.expr)),
        Stmt::Expr(expr, _) => expr_contains_initializer_fact_surface(expr),
        Stmt::Macro(stmt_macro) => macro_is_initializer_fact_surface(&stmt_macro.mac),
        Stmt::Item(_) => false,
    })
}

fn macro_is_initializer_fact_surface(mac: &syn::Macro) -> bool {
    crate::macro_is_assertion_surface(mac)
        || mac.path.segments.last().is_some_and(|segment| {
            matches!(
                segment.ident.to_string().as_str(),
                "panic" | "unreachable" | "todo" | "unimplemented"
            )
        })
}

fn expr_contains_initializer_fact_surface(expr: &Expr) -> bool {
    match expr {
        Expr::Macro(expr_macro) => macro_is_initializer_fact_surface(&expr_macro.mac),
        Expr::Block(block) => stmts_contain_initializer_fact_surface(&block.block.stmts),
        Expr::Unsafe(unsafe_expr) => {
            stmts_contain_initializer_fact_surface(&unsafe_expr.block.stmts)
        }
        Expr::Const(const_expr) => stmts_contain_initializer_fact_surface(&const_expr.block.stmts),
        Expr::If(if_expr) => {
            expr_contains_initializer_fact_surface(&if_expr.cond)
                || stmts_contain_initializer_fact_surface(&if_expr.then_branch.stmts)
                || if_expr
                    .else_branch
                    .as_ref()
                    .is_some_and(|(_, expr)| expr_contains_initializer_fact_surface(expr))
        }
        Expr::Match(match_expr) => {
            expr_contains_initializer_fact_surface(&match_expr.expr)
                || match_expr.arms.iter().any(|arm| {
                    arm.guard
                        .as_ref()
                        .is_some_and(|(_, guard)| expr_contains_initializer_fact_surface(guard))
                        || expr_contains_initializer_fact_surface(&arm.body)
                })
        }
        Expr::MethodCall(method) => {
            expr_contains_initializer_fact_surface(&method.receiver)
                || method
                    .args
                    .iter()
                    .any(expr_contains_initializer_fact_surface)
        }
        Expr::Call(call) => {
            expr_contains_initializer_fact_surface(&call.func)
                || call.args.iter().any(expr_contains_initializer_fact_surface)
        }
        Expr::Field(field) => expr_contains_initializer_fact_surface(&field.base),
        Expr::Index(index) => {
            expr_contains_initializer_fact_surface(&index.expr)
                || expr_contains_initializer_fact_surface(&index.index)
        }
        Expr::Await(await_expr) => expr_contains_initializer_fact_surface(&await_expr.base),
        Expr::Try(try_expr) => expr_contains_initializer_fact_surface(&try_expr.expr),
        Expr::Reference(reference) => expr_contains_initializer_fact_surface(&reference.expr),
        Expr::Unary(unary) => expr_contains_initializer_fact_surface(&unary.expr),
        Expr::Cast(cast) => expr_contains_initializer_fact_surface(&cast.expr),
        Expr::Binary(binary) => {
            expr_contains_initializer_fact_surface(&binary.left)
                || expr_contains_initializer_fact_surface(&binary.right)
        }
        Expr::Assign(assign) => {
            expr_contains_initializer_fact_surface(&assign.left)
                || expr_contains_initializer_fact_surface(&assign.right)
        }
        Expr::Range(range) => {
            range
                .start
                .as_ref()
                .is_some_and(|expr| expr_contains_initializer_fact_surface(expr))
                || range
                    .end
                    .as_ref()
                    .is_some_and(|expr| expr_contains_initializer_fact_surface(expr))
        }
        Expr::Array(array) => array
            .elems
            .iter()
            .any(expr_contains_initializer_fact_surface),
        Expr::Repeat(repeat) => {
            expr_contains_initializer_fact_surface(&repeat.expr)
                || expr_contains_initializer_fact_surface(&repeat.len)
        }
        Expr::Tuple(tuple) => tuple
            .elems
            .iter()
            .any(expr_contains_initializer_fact_surface),
        Expr::Struct(struct_expr) => {
            struct_expr
                .fields
                .iter()
                .any(|field| expr_contains_initializer_fact_surface(&field.expr))
                || struct_expr
                    .rest
                    .as_ref()
                    .is_some_and(|rest| expr_contains_initializer_fact_surface(rest))
        }
        Expr::Paren(paren) => expr_contains_initializer_fact_surface(&paren.expr),
        Expr::Group(group) => expr_contains_initializer_fact_surface(&group.expr),
        // A closure / async block body is not executed while evaluating the initializer.
        // Driver/handoff sugar owns those boundaries.
        Expr::Closure(_) | Expr::Async(_) => false,
        _ => false,
    }
}

fn block_fact_stmts(stmts: &[Stmt]) -> Option<Vec<Stmt>> {
    let mut out = Vec::new();
    for stmt in stmts {
        match stmt {
            Stmt::Local(local) => {
                let Some(init) = local.init.as_ref().filter(|init| init.diverge.is_none()) else {
                    continue;
                };
                collect_eager_fact_stmts(&init.expr, &mut out);
            }
            Stmt::Expr(expr, _) => collect_eager_fact_stmts(expr, &mut out),
            Stmt::Macro(stmt_macro) if crate::macro_is_assertion_surface(&stmt_macro.mac) => {
                out.push(Stmt::Macro(stmt_macro.clone()));
            }
            Stmt::Item(_) | Stmt::Macro(_) => {}
        }
    }
    (!out.is_empty()).then_some(out)
}

fn collect_eager_fact_stmts(expr: &Expr, out: &mut Vec<Stmt>) {
    match expr {
        Expr::Macro(expr_macro) if macro_is_initializer_fact_surface(&expr_macro.mac) => {
            out.push(Stmt::Expr(Expr::Macro(expr_macro.clone()), None));
        }
        Expr::MethodCall(method) => {
            collect_eager_fact_stmts(&method.receiver, out);
            for arg in &method.args {
                collect_eager_fact_stmts(arg, out);
            }
        }
        Expr::Call(call) => {
            collect_eager_fact_stmts(&call.func, out);
            for arg in &call.args {
                collect_eager_fact_stmts(arg, out);
            }
        }
        Expr::Field(field) => collect_eager_fact_stmts(&field.base, out),
        Expr::Index(index) => {
            collect_eager_fact_stmts(&index.expr, out);
            collect_eager_fact_stmts(&index.index, out);
        }
        Expr::Await(await_expr) => collect_eager_fact_stmts(&await_expr.base, out),
        Expr::Try(try_expr) => collect_eager_fact_stmts(&try_expr.expr, out),
        Expr::Reference(reference) => collect_eager_fact_stmts(&reference.expr, out),
        Expr::Unary(unary) => collect_eager_fact_stmts(&unary.expr, out),
        Expr::Cast(cast) => collect_eager_fact_stmts(&cast.expr, out),
        Expr::Binary(binary) => {
            collect_eager_fact_stmts(&binary.left, out);
            collect_eager_fact_stmts(&binary.right, out);
        }
        Expr::Assign(assign) => {
            collect_eager_fact_stmts(&assign.left, out);
            collect_eager_fact_stmts(&assign.right, out);
        }
        Expr::Range(range) => {
            if let Some(start) = &range.start {
                collect_eager_fact_stmts(start, out);
            }
            if let Some(end) = &range.end {
                collect_eager_fact_stmts(end, out);
            }
        }
        Expr::Array(array) => {
            for elem in &array.elems {
                collect_eager_fact_stmts(elem, out);
            }
        }
        Expr::Repeat(repeat) => {
            collect_eager_fact_stmts(&repeat.expr, out);
            collect_eager_fact_stmts(&repeat.len, out);
        }
        Expr::Tuple(tuple) => {
            for elem in &tuple.elems {
                collect_eager_fact_stmts(elem, out);
            }
        }
        Expr::Struct(struct_expr) => {
            for field in &struct_expr.fields {
                collect_eager_fact_stmts(&field.expr, out);
            }
            if let Some(rest) = &struct_expr.rest {
                collect_eager_fact_stmts(rest, out);
            }
        }
        Expr::Paren(paren) => collect_eager_fact_stmts(&paren.expr, out),
        Expr::Group(group) => collect_eager_fact_stmts(&group.expr, out),
        // A closure / async block body is not executed while evaluating the initializer.
        // Driver/handoff sugar owns those boundaries.
        Expr::Closure(_) | Expr::Async(_) => {}
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use quote::ToTokens;
    use syn::parse_quote;

    #[test]
    fn macro_initializer_is_a_fact_surface() {
        let expr: Expr = parse_quote!(assert_eq!(1, 1));
        let stmts = initializer_fact_stmts(&expr).expect("macro initializers are surfaced");
        assert_eq!(stmts.len(), 1);
        assert_eq!(
            stmts[0].to_token_stream().to_string(),
            "assert_eq ! (1 , 1)"
        );
    }

    #[test]
    fn plain_call_initializer_is_not_a_fact_surface() {
        let expr: Expr = parse_quote!(make_value(1));
        assert!(initializer_fact_stmts(&expr).is_none());
    }

    #[test]
    fn match_initializer_is_a_fact_surface() {
        let expr: Expr = parse_quote!(match x {
            Ok(v) => v,
            Err(e) => panic!("{e:?}"),
        });
        let stmts = initializer_fact_stmts(&expr).expect("match initializers are surfaced");
        assert_eq!(stmts.len(), 1);
        assert!(matches!(&stmts[0], Stmt::Expr(Expr::Match(_), None)));
    }

    #[test]
    fn value_if_initializer_without_facts_is_not_a_fact_surface() {
        let expr: Expr = parse_quote!(if cfg!(miri) {
            char::from_u32(0xD800 - 10).unwrap()
        } else {
            '\0'
        });
        assert!(
            initializer_fact_stmts(&expr).is_none(),
            "a value-only conditional initializer must stay lazy for its owning parent sugar"
        );
    }

    #[test]
    fn if_initializer_with_assertion_is_a_fact_surface() {
        let expr: Expr = parse_quote!(if ready() {
            assert!(x > 0)
        } else {
            assert!(x <= 0)
        });
        let stmts = initializer_fact_stmts(&expr).expect("asserting if initializers are surfaced");
        assert_eq!(stmts.len(), 1);
        assert!(matches!(&stmts[0], Stmt::Expr(Expr::If(_), None)));
    }

    #[test]
    fn method_chain_unknown_macro_receiver_is_not_an_eager_fact_surface() {
        let expr: Expr = parse_quote!(assert_ok!(read().await).unwrap());
        assert!(
            initializer_fact_stmts(&expr).is_none(),
            "unknown value macros in chains need source expansion; no name-prefix promotion"
        );
    }

    #[test]
    fn field_access_unknown_macro_receiver_is_not_an_eager_fact_surface() {
        let expr: Expr = parse_quote!(assert_ok!(listener.accept()).0);
        assert!(
            initializer_fact_stmts(&expr).is_none(),
            "unknown value macros in field bases need source expansion; no name-prefix promotion"
        );
    }

    #[test]
    fn closure_body_assertion_macro_is_not_eager_fact_surface() {
        let expr: Expr = parse_quote!(thread::spawn(move || assert_ok!(listener.accept()).0));
        assert!(initializer_fact_stmts(&expr).is_none());
    }

    #[test]
    fn value_builder_block_without_assertions_is_not_eager_fact_surface() {
        let expr: Expr = parse_quote!({
            let mut xs = vec![];
            let mut x: u8 = !0;
            let mut w = u8::BITS;
            while w > 0 {
                w >>= 1;
                xs.push(x);
                xs.push(!x);
                x ^= x << w;
            }
            xs
        });
        assert!(initializer_fact_stmts(&expr).is_none());
    }
}

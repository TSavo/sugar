// SPDX-License-Identifier: Apache-2.0
//
// `DormantMutRefSugar`: the stdlib-internal BTree borrow axiom.
//
// This is deliberately not raw-pointer sugar. It recognizes the narrow
// `alloc::collections::btree::borrow::DormantMutRef` contract:
//
//   DormantMutRef::new(rr) -> (reborrow_rr, dormant(rr_base))
//   dormant(rr_base).awaken() -> rr_base
//
// Over a bounded literal stack replay, that lets a final read of the base local
// bottom out in a literal instead of the generic "ambiguous temporal identity"
// refusal. Unknown aliases, unknown containers, and non-literal factors decline.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{num, Term};
use syn::{BinOp, Expr, Pat, Stmt};

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_leaf::resolved_term;
use crate::{parse_int_lit, simple_path_name, strip_refs_groups, Sugar};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "dormant_mut_ref",
        &["bound_path", "path"],
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // `path_simple_ident` returns the bare ident for an `Expr::Path` with a single
    // unqualified segment -- identical gate to the former `let Expr::Path(path) = expr;
    // path.path.get_ident()?.to_string()` shim, with no raw-syn escape.
    let name = frag.path_simple_ident()?;
    fcx.scope().dormant_mut_ref_term(&name).map(resolved_term)
}

#[derive(Clone, Debug)]
struct StackEntry {
    base: String,
    factor: i128,
}

#[derive(Clone, Debug, Default)]
pub(crate) struct DormantMutRefState {
    base_values: BTreeMap<String, i128>,
    aliases: BTreeMap<String, String>,
    stacks: BTreeMap<String, Vec<StackEntry>>,
    resolved_values: BTreeMap<String, i128>,
}

impl DormantMutRefState {
    pub(crate) fn term_for(&self, name: &str) -> Option<Rc<Term>> {
        self.resolved_values.get(name).copied().map(num)
    }

    pub(crate) fn advance_stmt(&mut self, stmt: &Stmt) {
        match stmt {
            Stmt::Local(local) => {
                if let (Some(name), Some(value)) = (
                    simple_mut_pat_ident(&local.pat),
                    local
                        .init
                        .as_ref()
                        .and_then(|init| literal_int_expr(&init.expr)),
                ) {
                    self.base_values.insert(name.clone(), value);
                    self.resolved_values.remove(&name);
                    return;
                }

                if let (Some(alias), Some(base)) = (
                    simple_mut_pat_ident(&local.pat),
                    local
                        .init
                        .as_ref()
                        .and_then(|init| mut_reference_target(&init.expr)),
                ) {
                    if self.base_values.contains_key(&base) {
                        self.aliases.insert(alias, base);
                    }
                    return;
                }

                if let (Some(stack), true) = (
                    simple_mut_pat_ident(&local.pat),
                    local
                        .init
                        .as_ref()
                        .is_some_and(|init| is_empty_vec_macro(&init.expr)),
                ) {
                    self.stacks.entry(stack).or_default();
                }
            }
            Stmt::Expr(Expr::ForLoop(for_loop), _) => self.advance_for_loop(for_loop),
            Stmt::Expr(Expr::While(while_loop), _) => self.advance_while_loop(while_loop),
            Stmt::Expr(expr, _) => self.clear_direct_mutation(expr),
            _ => {}
        }
    }

    fn advance_for_loop(&mut self, for_loop: &syn::ExprForLoop) {
        let Some(loop_var) = simple_pat_ident(&for_loop.pat) else {
            return;
        };
        let Some(factors) = literal_int_iter_domain(&for_loop.expr) else {
            return;
        };

        let mut dormant_bases: BTreeMap<String, String> = BTreeMap::new();
        let mut reborrow_bases: BTreeMap<String, String> = BTreeMap::new();
        let mut rebound_aliases: BTreeMap<String, String> = BTreeMap::new();

        for stmt in &for_loop.body.stmts {
            if let Some((reborrow, dormant, base)) = dormant_new_binding(stmt, &self.aliases) {
                reborrow_bases.insert(reborrow, base.clone());
                dormant_bases.insert(dormant, base);
                continue;
            }

            if let Some((alias, reborrow)) = alias_reassignment(stmt) {
                if let Some(base) = reborrow_bases.get(&reborrow) {
                    self.aliases.insert(alias.clone(), base.clone());
                    rebound_aliases.insert(alias, base.clone());
                }
                continue;
            }

            let Some((stack, factor, dormant)) = stack_push_tuple(stmt) else {
                continue;
            };
            if factor != loop_var {
                continue;
            }
            let Some(base) = dormant_bases.get(&dormant) else {
                continue;
            };
            if !rebound_aliases.values().any(|rebound| rebound == base) {
                continue;
            }
            let entries = self.stacks.entry(stack).or_default();
            entries.extend(factors.iter().copied().map(|factor| StackEntry {
                base: base.clone(),
                factor,
            }));
        }
    }

    fn advance_while_loop(&mut self, while_loop: &syn::ExprWhile) {
        let Some((stack, factor_var, dormant_var)) = while_pop_binding(&while_loop.cond) else {
            return;
        };
        if !while_body_awaken_multiply(&while_loop.body, &factor_var, &dormant_var) {
            return;
        }
        let Some(entries) = self.stacks.remove(&stack) else {
            return;
        };
        for entry in entries.iter().rev() {
            let Some(value) = self.base_values.get_mut(&entry.base) else {
                continue;
            };
            let Some(next) = value.checked_mul(entry.factor) else {
                self.resolved_values.remove(&entry.base);
                continue;
            };
            *value = next;
            self.resolved_values.insert(entry.base.clone(), next);
        }
    }

    fn clear_direct_mutation(&mut self, expr: &Expr) {
        if let Some(name) = assigned_simple_name(expr) {
            self.resolved_values.remove(&name);
            self.base_values.remove(&name);
        }
    }
}

fn simple_mut_pat_ident(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(ident) if ident.mutability.is_some() && ident.subpat.is_none() => {
            Some(ident.ident.to_string())
        }
        Pat::Type(typed) => simple_mut_pat_ident(&typed.pat),
        Pat::Paren(paren) => simple_mut_pat_ident(&paren.pat),
        _ => None,
    }
}

fn simple_pat_ident(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(ident) if ident.subpat.is_none() => Some(ident.ident.to_string()),
        Pat::Type(typed) => simple_pat_ident(&typed.pat),
        Pat::Paren(paren) => simple_pat_ident(&paren.pat),
        _ => None,
    }
}

fn literal_int_expr(expr: &Expr) -> Option<i128> {
    match strip_refs_groups(expr) {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Int(lit),
            ..
        }) => parse_int_lit(lit).ok(),
        _ => None,
    }
}

fn mut_reference_target(expr: &Expr) -> Option<String> {
    let Expr::Reference(reference) = strip_parens_groups(expr) else {
        return None;
    };
    reference.mutability?;
    simple_path_name(&reference.expr)
}

fn strip_parens_groups(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(paren) => strip_parens_groups(&paren.expr),
        Expr::Group(group) => strip_parens_groups(&group.expr),
        _ => expr,
    }
}

fn is_empty_vec_macro(expr: &Expr) -> bool {
    let Expr::Macro(mac) = strip_refs_groups(expr) else {
        return false;
    };
    mac.mac
        .path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == "vec")
        && mac.mac.tokens.is_empty()
}

fn literal_int_iter_domain(expr: &Expr) -> Option<Vec<i128>> {
    match strip_refs_groups(expr) {
        Expr::MethodCall(call)
            if call.args.is_empty()
                && matches!(call.method.to_string().as_str(), "iter" | "into_iter") =>
        {
            literal_int_array(&call.receiver)
        }
        Expr::Array(_) => literal_int_array(expr),
        _ => None,
    }
}

fn literal_int_array(expr: &Expr) -> Option<Vec<i128>> {
    let Expr::Array(array) = strip_refs_groups(expr) else {
        return None;
    };
    array.elems.iter().map(literal_int_expr).collect()
}

fn dormant_new_binding(
    stmt: &Stmt,
    aliases: &BTreeMap<String, String>,
) -> Option<(String, String, String)> {
    let Stmt::Local(local) = stmt else {
        return None;
    };
    let Pat::Tuple(tuple) = &local.pat else {
        return None;
    };
    if tuple.elems.len() != 2 {
        return None;
    }
    let reborrow = simple_pat_ident(&tuple.elems[0])?;
    let dormant = simple_pat_ident(&tuple.elems[1])?;
    let call = local
        .init
        .as_ref()
        .and_then(|init| dormant_new_call(&init.expr))?;
    let base = aliases.get(&call)?.clone();
    Some((reborrow, dormant, base))
}

fn dormant_new_call(expr: &Expr) -> Option<String> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.args.len() != 1 {
        return None;
    }
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    let mut segments = path.path.segments.iter().rev();
    let method = segments.next()?;
    let ty = segments.next()?;
    if method.ident != "new" || ty.ident != "DormantMutRef" {
        return None;
    }
    simple_path_name(&call.args[0])
}

fn alias_reassignment(stmt: &Stmt) -> Option<(String, String)> {
    let Stmt::Expr(Expr::Assign(assign), _) = stmt else {
        return None;
    };
    Some((
        simple_path_name(&assign.left)?,
        simple_path_name(&assign.right)?,
    ))
}

fn stack_push_tuple(stmt: &Stmt) -> Option<(String, String, String)> {
    let Stmt::Expr(Expr::MethodCall(call), _) = stmt else {
        return None;
    };
    if call.method != "push" || call.args.len() != 1 {
        return None;
    }
    let stack = simple_path_name(&call.receiver)?;
    let Expr::Tuple(tuple) = strip_refs_groups(&call.args[0]) else {
        return None;
    };
    if tuple.elems.len() != 2 {
        return None;
    }
    Some((
        stack,
        simple_path_name(&tuple.elems[0])?,
        simple_path_name(&tuple.elems[1])?,
    ))
}

fn while_pop_binding(cond: &Expr) -> Option<(String, String, String)> {
    let Expr::Let(expr_let) = strip_refs_groups(cond) else {
        return None;
    };
    let Pat::TupleStruct(some_pat) = &*expr_let.pat else {
        return None;
    };
    if !some_pat
        .path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == "Some")
        || some_pat.elems.len() != 1
    {
        return None;
    }
    let Pat::Tuple(tuple) = &some_pat.elems[0] else {
        return None;
    };
    if tuple.elems.len() != 2 {
        return None;
    }
    let factor = simple_pat_ident(&tuple.elems[0])?;
    let dormant = simple_pat_ident(&tuple.elems[1])?;

    let Expr::MethodCall(pop) = strip_refs_groups(&expr_let.expr) else {
        return None;
    };
    if pop.method != "pop" || !pop.args.is_empty() {
        return None;
    }
    Some((simple_path_name(&pop.receiver)?, factor, dormant))
}

fn while_body_awaken_multiply(block: &syn::Block, factor: &str, dormant: &str) -> bool {
    let [Stmt::Local(local), Stmt::Expr(Expr::Binary(binary), _)] = block.stmts.as_slice() else {
        return false;
    };
    let Some(reborrow) = simple_pat_ident(&local.pat) else {
        return false;
    };
    if local
        .init
        .as_ref()
        .and_then(|init| awaken_call(&init.expr))
        .as_deref()
        != Some(dormant)
    {
        return false;
    }
    if !matches!(binary.op, BinOp::MulAssign(_)) {
        return false;
    }
    deref_path_name(&binary.left).as_deref() == Some(reborrow.as_str())
        && simple_path_name(&binary.right).as_deref() == Some(factor)
}

fn awaken_call(expr: &Expr) -> Option<String> {
    let expr = strip_refs_groups(expr);
    let expr = match expr {
        Expr::Unsafe(unsafe_expr) => match unsafe_expr.block.stmts.as_slice() {
            [Stmt::Expr(inner, None)] => strip_refs_groups(inner),
            _ => return None,
        },
        other => other,
    };
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "awaken" || !call.args.is_empty() {
        return None;
    }
    simple_path_name(&call.receiver)
}

fn deref_path_name(expr: &Expr) -> Option<String> {
    let Expr::Unary(unary) = strip_refs_groups(expr) else {
        return None;
    };
    if !matches!(unary.op, syn::UnOp::Deref(_)) {
        return None;
    }
    simple_path_name(&unary.expr)
}

fn assigned_simple_name(expr: &Expr) -> Option<String> {
    match strip_refs_groups(expr) {
        Expr::Assign(assign) => simple_path_name(&assign.left),
        Expr::Binary(binary)
            if matches!(
                binary.op,
                BinOp::AddAssign(_)
                    | BinOp::SubAssign(_)
                    | BinOp::MulAssign(_)
                    | BinOp::DivAssign(_)
                    | BinOp::RemAssign(_)
                    | BinOp::BitXorAssign(_)
                    | BinOp::BitAndAssign(_)
                    | BinOp::BitOrAssign(_)
                    | BinOp::ShlAssign(_)
                    | BinOp::ShrAssign(_)
            ) =>
        {
            simple_path_name(&binary.left)
        }
        _ => None,
    }
}

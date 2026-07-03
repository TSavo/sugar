// SPDX-License-Identifier: Apache-2.0
//
// `dyn Any` type-identity sugar. The source of truth is the concrete type at a
// visible coercion site (`&expr as &dyn Any`, `Box::new(expr) as Box<dyn Any>`).
// The recognizer only captures the method shape; desugar resolves stable bindings
// lazily, then folds `.is::<T>()` / downcast presence predicates to a Bool literal.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::{Expr, GenericArgument, PathArguments, Type};

use crate::sugar::bound::BoundSugar;
use crate::sugar::claim::ExprSugarClaim;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    bool_const, strip_refs_groups, token_key, type_key, Desugared, Effect, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "dyn_any",
    &["option_predicate", "result_predicate", "method"],
    crate::sugar::claim::SugarWitnesses::Pending,
    recognize,
);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let kind = DynAnyPredicateKind::from_expr(expr)?;
    Some(Box::new(DynAnyPredicateSugar {
        kind,
        let_inits: capture_let_inits(fcx),
    }))
}

#[derive(Clone)]
enum DynAnyPredicateKind {
    Is {
        receiver: DynAnyReceiver,
        target: String,
    },
    DowncastRefIsSome {
        receiver: DynAnyReceiver,
        target: String,
    },
    DowncastBoxIsOk {
        receiver: DynAnyReceiver,
        target: String,
    },
}

impl DynAnyPredicateKind {
    fn from_expr(expr: &Expr) -> Option<Self> {
        let Expr::MethodCall(call) = expr else {
            return None;
        };
        let method = call.method.to_string();
        if !call.args.is_empty() {
            return None;
        }
        match method.as_str() {
            "is" => Some(Self::Is {
                receiver: DynAnyReceiver {
                    raw: (*call.receiver).clone(),
                },
                target: turbofish_type_key(&call.turbofish)?,
            }),
            "is_some" => {
                let Expr::MethodCall(inner) = strip_refs_groups(&call.receiver) else {
                    return None;
                };
                if inner.method != "downcast_ref" || !inner.args.is_empty() {
                    return None;
                }
                Some(Self::DowncastRefIsSome {
                    receiver: DynAnyReceiver {
                        raw: (*inner.receiver).clone(),
                    },
                    target: turbofish_type_key(&inner.turbofish)?,
                })
            }
            "is_ok" => {
                let Expr::MethodCall(inner) = strip_refs_groups(&call.receiver) else {
                    return None;
                };
                if inner.method != "downcast" || !inner.args.is_empty() {
                    return None;
                }
                Some(Self::DowncastBoxIsOk {
                    receiver: DynAnyReceiver {
                        raw: (*inner.receiver).clone(),
                    },
                    target: turbofish_type_key(&inner.turbofish)?,
                })
            }
            _ => None,
        }
    }

    fn receiver(&self) -> &DynAnyReceiver {
        match self {
            Self::Is { receiver, .. }
            | Self::DowncastRefIsSome { receiver, .. }
            | Self::DowncastBoxIsOk { receiver, .. } => receiver,
        }
    }

    fn target(&self) -> &str {
        match self {
            Self::Is { target, .. }
            | Self::DowncastRefIsSome { target, .. }
            | Self::DowncastBoxIsOk { target, .. } => target,
        }
    }
}

struct DynAnyPredicateSugar {
    kind: DynAnyPredicateKind,
    let_inits: BTreeMap<String, Expr>,
}

impl Sugar for DynAnyPredicateSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let source = DynAnyConcreteTypeSugar {
            receiver: self.kind.receiver().clone(),
            let_inits: merge_scope_let_inits(ctx, &self.let_inits),
            depth: 0,
        };
        let concrete = match source.desugar(ctx) {
            Outcome::Complete(d) => match d.into_term() {
                Some(term) => type_key_from_type_id_term(&term),
                None => None,
            },
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        let Some(concrete) = concrete else {
            dyn_any_gap("concrete type child completed as a non-type-id term");
        };
        Outcome::Complete(Desugared::Term(bool_const(concrete == self.kind.target())))
    }
}

struct DynAnyConcreteTypeSugar {
    receiver: DynAnyReceiver,
    let_inits: BTreeMap<String, Expr>,
    depth: usize,
}

#[derive(Clone)]
struct DynAnyReceiver {
    raw: Expr,
}

impl Sugar for DynAnyConcreteTypeSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if self.depth > 12 {
            return dyn_any_unknown();
        }
        if let Some((name, bound)) = let_bound_reference(&self.receiver.raw, &self.let_inits) {
            let child = DynAnyConcreteTypeSugar {
                receiver: DynAnyReceiver { raw: bound },
                let_inits: self.let_inits.clone(),
                depth: self.depth + 1,
            };
            return BoundSugar::new(name, Box::new(child)).desugar(ctx);
        }
        match concrete_type_from_dyn_any_receiver(
            &self.receiver.raw,
            &self.let_inits,
            ctx,
            self.depth + 1,
        ) {
            Some(concrete) => Outcome::Complete(Desugared::Term(type_id_term(&concrete))),
            None => dyn_any_unknown(),
        }
    }
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

fn merge_scope_let_inits(
    ctx: &SugarCtx,
    captured: &BTreeMap<String, Expr>,
) -> BTreeMap<String, Expr> {
    let mut merged = captured.clone();
    for (name, init) in ctx.scope.let_bindings_iter() {
        merged.insert(name.clone(), init.clone());
    }
    merged
}

fn turbofish_type_key(args: &Option<syn::AngleBracketedGenericArguments>) -> Option<String> {
    let args = args.as_ref()?;
    if args.args.len() != 1 {
        return None;
    }
    let Some(GenericArgument::Type(ty)) = args.args.first() else {
        return None;
    };
    Some(type_key(ty))
}

fn concrete_type_from_dyn_any_receiver(
    receiver: &Expr,
    let_inits: &BTreeMap<String, Expr>,
    ctx: &SugarCtx,
    depth: usize,
) -> Option<String> {
    if depth > 12 {
        return None;
    }
    if let Some((_, bound)) = let_bound_reference(receiver, let_inits) {
        return concrete_type_from_dyn_any_receiver(&bound, let_inits, ctx, depth + 1);
    }
    match receiver {
        Expr::Cast(cast) if is_ref_dyn_any_type(&cast.ty) => {
            concrete_type_from_ref_coercion_source(&cast.expr, let_inits, ctx, depth + 1)
        }
        Expr::Cast(cast) if is_box_dyn_any_type(&cast.ty) => {
            concrete_type_from_box_coercion_source(&cast.expr, let_inits, ctx, depth + 1)
        }
        Expr::Paren(paren) => {
            concrete_type_from_dyn_any_receiver(&paren.expr, let_inits, ctx, depth + 1)
        }
        Expr::Group(group) => {
            concrete_type_from_dyn_any_receiver(&group.expr, let_inits, ctx, depth + 1)
        }
        _ => None,
    }
}

fn concrete_type_from_ref_coercion_source(
    source: &Expr,
    let_inits: &BTreeMap<String, Expr>,
    ctx: &SugarCtx,
    depth: usize,
) -> Option<String> {
    match source {
        Expr::Reference(reference) => {
            static_type_of_value(&reference.expr, let_inits, ctx, depth + 1)
        }
        Expr::Paren(paren) => {
            concrete_type_from_ref_coercion_source(&paren.expr, let_inits, ctx, depth + 1)
        }
        Expr::Group(group) => {
            concrete_type_from_ref_coercion_source(&group.expr, let_inits, ctx, depth + 1)
        }
        _ => None,
    }
}

fn concrete_type_from_box_coercion_source(
    source: &Expr,
    let_inits: &BTreeMap<String, Expr>,
    ctx: &SugarCtx,
    depth: usize,
) -> Option<String> {
    match strip_refs_groups(source) {
        Expr::Call(call) if path_ends_with(&call.func, &["Box", "new"]) && call.args.len() == 1 => {
            static_type_of_value(call.args.first()?, let_inits, ctx, depth + 1)
        }
        Expr::Paren(paren) => {
            concrete_type_from_box_coercion_source(&paren.expr, let_inits, ctx, depth + 1)
        }
        Expr::Group(group) => {
            concrete_type_from_box_coercion_source(&group.expr, let_inits, ctx, depth + 1)
        }
        _ => None,
    }
}

fn static_type_of_value(
    expr: &Expr,
    let_inits: &BTreeMap<String, Expr>,
    ctx: &SugarCtx,
    depth: usize,
) -> Option<String> {
    if depth > 12 {
        return None;
    }
    match expr {
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            if let Some(bound) = let_inits.get(&name) {
                return static_type_of_value(bound, let_inits, ctx, depth + 1);
            }
            if let Some(ty) = ctx.scope.value_type_for_path(&path.path) {
                return Some(ty);
            }
            name.chars()
                .next()
                .is_some_and(char::is_uppercase)
                .then(|| path_to_type_key(&path.path))
        }
        Expr::Lit(lit) => literal_type_key(&lit.lit),
        Expr::Array(array) => {
            let mut elems = array.elems.iter();
            let first = static_type_of_value(elems.next()?, let_inits, ctx, depth + 1)?;
            elems
                .all(|elem| {
                    static_type_of_value(elem, let_inits, ctx, depth + 1).as_deref()
                        == Some(first.as_str())
                })
                .then(|| format!("[{};{}]", first, array.elems.len()))
        }
        Expr::Repeat(repeat) => {
            let elem = static_type_of_value(&repeat.expr, let_inits, ctx, depth + 1)?;
            Some(format!("[{};{}]", elem, token_key(&repeat.len)))
        }
        Expr::Reference(reference) => {
            let inner = static_type_of_value(&reference.expr, let_inits, ctx, depth + 1)?;
            if reference.mutability.is_some() {
                Some(format!("&mut {inner}"))
            } else {
                Some(format!("&{inner}"))
            }
        }
        Expr::Paren(paren) => static_type_of_value(&paren.expr, let_inits, ctx, depth + 1),
        Expr::Group(group) => static_type_of_value(&group.expr, let_inits, ctx, depth + 1),
        _ => None,
    }
}

fn literal_type_key(lit: &syn::Lit) -> Option<String> {
    match lit {
        syn::Lit::Int(int) => {
            let suffix = int.suffix();
            Some(if suffix.is_empty() { "i32" } else { suffix }.to_string())
        }
        syn::Lit::Bool(_) => Some("bool".to_string()),
        syn::Lit::Char(_) => Some("char".to_string()),
        syn::Lit::Str(_) => Some("&'static str".to_string()),
        _ => None,
    }
}

fn let_bound_reference(
    receiver: &Expr,
    let_inits: &BTreeMap<String, Expr>,
) -> Option<(String, Expr)> {
    match receiver {
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let bound = let_inits.get(&name)?;
            Some((name, bound.clone()))
        }
        Expr::Paren(paren) => let_bound_reference(&paren.expr, let_inits),
        Expr::Group(group) => let_bound_reference(&group.expr, let_inits),
        _ => None,
    }
}

fn is_ref_dyn_any_type(ty: &Type) -> bool {
    let Type::Reference(reference) = ty else {
        return false;
    };
    type_is_dyn_any_trait_object(&reference.elem)
}

fn is_box_dyn_any_type(ty: &Type) -> bool {
    let Type::Path(path) = ty else {
        return false;
    };
    let Some(segment) = path.path.segments.last() else {
        return false;
    };
    if segment.ident != "Box" {
        return false;
    }
    let PathArguments::AngleBracketed(args) = &segment.arguments else {
        return false;
    };
    matches!(args.args.first(), Some(GenericArgument::Type(ty)) if type_is_dyn_any_trait_object(ty))
}

fn type_is_dyn_any_trait_object(ty: &Type) -> bool {
    let Type::TraitObject(trait_object) = ty else {
        return false;
    };
    trait_object.bounds.iter().any(|bound| {
        let syn::TypeParamBound::Trait(trait_bound) = bound else {
            return false;
        };
        trait_bound
            .path
            .segments
            .last()
            .is_some_and(|segment| segment.ident == "Any")
    })
}

fn path_ends_with(expr: &Expr, suffix: &[&str]) -> bool {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return false;
    };
    let segments = path
        .path
        .segments
        .iter()
        .map(|segment| segment.ident.to_string())
        .collect::<Vec<_>>();
    segments.ends_with(&suffix.iter().map(|s| s.to_string()).collect::<Vec<_>>())
}

fn path_to_type_key(path: &syn::Path) -> String {
    path.segments
        .iter()
        .map(|segment| {
            let mut name = segment.ident.to_string();
            match &segment.arguments {
                PathArguments::None => {}
                _ => name.push_str(&token_key(&segment.arguments)),
            }
            name
        })
        .collect::<Vec<_>>()
        .join("::")
}

fn type_id_term(ty: &str) -> Rc<Term> {
    Rc::new(Term::Ctor {
        name: format!("type_id::{ty}"),
        args: Vec::new(),
    })
}

fn type_key_from_type_id_term(term: &Rc<Term>) -> Option<String> {
    let Term::Ctor { name, args } = term.as_ref() else {
        return None;
    };
    args.is_empty()
        .then(|| name.strip_prefix("type_id::").map(str::to_string))
        .flatten()
}

fn dyn_any_unknown() -> Outcome {
    Outcome::Incomplete(Effect::DynAnyConcreteType {
        boundary: "dyn Any concrete type not statically determined".to_string(),
    })
}

fn dyn_any_gap(reason: &str) -> ! {
    panic!("dyn_any did not reach a lawful type identity floor: {reason}")
}

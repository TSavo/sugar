// SPDX-License-Identifier: Apache-2.0
//
// COMPOSITE recognizer for literal range constructor values used as statement/let
// surfaces. The recognizer only captures the raw bound expressions; desugar builds
// each bound lazily and either emits construction field facts or propagates the
// child's named Incomplete unchanged.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, Term};
use syn::{Expr, Member};

use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
use crate::{AssertionFactKind, Desugared, Outcome, Sugar, SugarCtx, Warrant};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("range_construct", recognize);

pub(crate) fn is_range_construct_expr(expr: &Expr) -> bool {
    match expr {
        Expr::Struct(s) => {
            s.rest.is_none() && RangeConstructKind::from_struct_path(&s.path).is_some()
        }
        Expr::Call(call) => {
            let Expr::Path(path) = call.func.as_ref() else {
                return false;
            };
            call.args.len() == 2 && RangeConstructKind::from_call_path(&path.path).is_some()
        }
        _ => false,
    }
}

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Struct(s) => {
            if s.rest.is_some() {
                return None;
            }
            let kind = RangeConstructKind::from_struct_path(&s.path)?;
            let mut fields = Vec::new();
            for field in &s.fields {
                let name = match &field.member {
                    Member::Named(id) => id.to_string(),
                    Member::Unnamed(idx) => idx.index.to_string(),
                };
                if kind.accepts_field(&name) {
                    fields.push((name, field.expr.clone()));
                }
            }
            if !kind.has_required_fields(&fields) {
                return None;
            }
            Some(Box::new(RangeConstructSugar {
                kind,
                fields,
                let_inits: capture_let_inits(fcx),
            }))
        }
        Expr::Call(call) => {
            let Expr::Path(path) = call.func.as_ref() else {
                return None;
            };
            let kind = RangeConstructKind::from_call_path(&path.path)?;
            if call.args.len() != 2 {
                return None;
            }
            Some(Box::new(RangeConstructSugar {
                kind,
                fields: vec![
                    ("start".to_string(), call.args[0].clone()),
                    ("end".to_string(), call.args[1].clone()),
                ],
                let_inits: capture_let_inits(fcx),
            }))
        }
        _ => None,
    }
}

#[derive(Clone, Copy)]
enum RangeConstructKind {
    Range,
    RangeFrom,
    RangeTo,
    RangeToInclusive,
    RangeInclusive,
}

impl RangeConstructKind {
    fn from_struct_path(path: &syn::Path) -> Option<Self> {
        match path.segments.last()?.ident.to_string().as_str() {
            "Range" => Some(Self::Range),
            "RangeFrom" => Some(Self::RangeFrom),
            "RangeTo" => Some(Self::RangeTo),
            "RangeToInclusive" => Some(Self::RangeToInclusive),
            _ => None,
        }
    }

    fn from_call_path(path: &syn::Path) -> Option<Self> {
        let mut segments = path.segments.iter().map(|seg| seg.ident.to_string());
        let penultimate = segments.next_back()?;
        let ultimate = segments.next_back()?;
        (penultimate == "new" && ultimate == "RangeInclusive").then_some(Self::RangeInclusive)
    }

    fn accepts_field(self, field: &str) -> bool {
        match self {
            Self::Range | Self::RangeInclusive => matches!(field, "start" | "end"),
            Self::RangeFrom => field == "start",
            Self::RangeTo | Self::RangeToInclusive => field == "end",
        }
    }

    fn has_required_fields(self, fields: &[(String, Expr)]) -> bool {
        match self {
            Self::Range | Self::RangeInclusive => {
                has_field(fields, "start") && has_field(fields, "end")
            }
            Self::RangeFrom => has_field(fields, "start"),
            Self::RangeTo | Self::RangeToInclusive => has_field(fields, "end"),
        }
    }

    fn ctor_name(self) -> &'static str {
        match self {
            Self::Range => "struct:Range",
            Self::RangeFrom => "struct:RangeFrom",
            Self::RangeTo => "struct:RangeTo",
            Self::RangeToInclusive => "struct:RangeToInclusive",
            Self::RangeInclusive => "range_incl",
        }
    }

    fn warrant_name(self) -> &'static str {
        match self {
            Self::Range => "range-construct:Range",
            Self::RangeFrom => "range-construct:RangeFrom",
            Self::RangeTo => "range-construct:RangeTo",
            Self::RangeToInclusive => "range-construct:RangeToInclusive",
            Self::RangeInclusive => "range-construct:RangeInclusive",
        }
    }
}

fn has_field(fields: &[(String, Expr)], want: &str) -> bool {
    fields.iter().any(|(field, _)| field == want)
}

struct RangeConstructSugar {
    kind: RangeConstructKind,
    fields: Vec<(String, Expr)>,
    let_inits: BTreeMap<String, Expr>,
}

impl Sugar for RangeConstructSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let stable = stable_let_bindings(ctx.scope);
        let let_inits = merge_let_inits(&stable, &self.let_inits);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let mut fields = Vec::new();
        for (name, expr) in &self.fields {
            let term = match build_term(expr, &fcx).desugar(ctx) {
                Outcome::Complete(d) => match d.into_term() {
                    Some(term) => term,
                    None => return Outcome::from_opt(None),
                },
                Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
            };
            fields.push((name.clone(), term));
        }
        fields.sort_by(|a, b| a.0.cmp(&b.0));
        let subject = self.subject_term(&fields);
        let atoms = fields
            .iter()
            .map(|(name, term)| {
                eq(
                    Rc::new(Term::Ctor {
                        name: format!("field:{name}"),
                        args: vec![subject.clone()],
                    }),
                    term.clone(),
                )
            })
            .collect::<Vec<_>>();
        let n = atoms.len();
        if n == 0 {
            return Outcome::from_opt(None);
        }
        Outcome::Complete(Desugared::Constraints {
            atom: and_(atoms),
            n,
            kind: AssertionFactKind::Warranted,
            warrant: Warrant {
                name: Some(self.kind.warrant_name().to_string()),
            },
        })
    }
}

impl RangeConstructSugar {
    fn subject_term(&self, fields: &[(String, Rc<Term>)]) -> Rc<Term> {
        match self.kind {
            RangeConstructKind::RangeInclusive => {
                let args = ["start", "end"]
                    .iter()
                    .filter_map(|want| {
                        fields
                            .iter()
                            .find(|(field, _)| field == want)
                            .map(|(_, term)| term.clone())
                    })
                    .collect();
                Rc::new(Term::Ctor {
                    name: "range_incl".to_string(),
                    args,
                })
            }
            _ => {
                let args = fields
                    .iter()
                    .map(|(field, term)| {
                        Rc::new(Term::Ctor {
                            name: format!("field:{field}"),
                            args: vec![term.clone()],
                        })
                    })
                    .collect();
                Rc::new(Term::Ctor {
                    name: self.kind.ctor_name().to_string(),
                    args,
                })
            }
        }
    }
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

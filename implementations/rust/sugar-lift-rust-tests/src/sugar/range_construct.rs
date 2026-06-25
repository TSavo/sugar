// SPDX-License-Identifier: Apache-2.0
//
// COMPOSITE recognizer for literal range constructor values used as statement/let
// surfaces. The recognizer constructs each field's child body without reducing it;
// desugar/reduce emits construction field facts or propagates the child's terminal
// answer unchanged.

use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, Term};
use syn::{Expr, Member};

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::term_dispatch::{DesugaredFloorAccept, RequiredTermVisitor};
use crate::{AssertionFactKind, Desugared, Outcome, Sugar, SugarCtx, Warrant};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("range_construct", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Struct(s) => {
            if s.rest.is_some() {
                return None;
            }
            let kind = RangeConstructKind::from_struct_path(&s.path)?;
            let mut raw_fields = Vec::new();
            for field in &s.fields {
                let name = match &field.member {
                    Member::Named(id) => id.to_string(),
                    Member::Unnamed(idx) => idx.index.to_string(),
                };
                if kind.accepts_field(&name) {
                    raw_fields.push((name, &field.expr));
                }
            }
            let field_names = raw_fields
                .iter()
                .map(|(name, _)| name.clone())
                .collect::<Vec<_>>();
            if !kind.has_required_field_names(&field_names) {
                return None;
            }
            let fields = raw_fields
                .into_iter()
                .map(|(name, expr)| (name, SugarBody::term(expr, fcx)))
                .collect();
            Some(RangeConstructSugar::new(kind, fields))
        }
        Expr::Call(call) => {
            let Expr::Path(path) = call.func.as_ref() else {
                return None;
            };
            let kind = RangeConstructKind::from_call_path(&path.path)?;
            if call.args.len() != 2 {
                return None;
            }
            Some(RangeConstructSugar::new(
                kind,
                vec![
                    ("start".to_string(), SugarBody::term(&call.args[0], fcx)),
                    ("end".to_string(), SugarBody::term(&call.args[1], fcx)),
                ],
            ))
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

    fn has_required_field_names(self, fields: &[String]) -> bool {
        match self {
            Self::Range | Self::RangeInclusive => {
                has_field_name(fields, "start") && has_field_name(fields, "end")
            }
            Self::RangeFrom => has_field_name(fields, "start"),
            Self::RangeTo | Self::RangeToInclusive => has_field_name(fields, "end"),
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

fn has_field_name(fields: &[String], want: &str) -> bool {
    fields.iter().any(|field| field == want)
}

struct RangeConstructSugar {
    kind: RangeConstructKind,
    fields: Vec<(String, SugarBody<TermFloor>)>,
}

impl Sugar for RangeConstructSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let mut fields = Vec::new();
        for (name, body) in &self.fields {
            let term = match body.reduce(ctx) {
                Outcome::Complete(d) => d.accept_desugared_floor(RequiredTermVisitor {
                    owner: "range construct field",
                }),
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
            panic!("range construct has no fields");
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

impl RangeConstructSugar {
    fn new(
        kind: RangeConstructKind,
        fields: Vec<(String, SugarBody<TermFloor>)>,
    ) -> Box<dyn Sugar> {
        Box::new(Self { kind, fields })
    }
}

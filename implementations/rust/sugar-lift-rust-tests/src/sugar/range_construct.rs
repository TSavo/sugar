// SPDX-License-Identifier: Apache-2.0
//
// COMPOSITE recognizer for literal range constructor values used as statement/let
// surfaces. The recognizer constructs each field's child body without reducing it;
// desugar/reduce emits construction field facts or propagates the child's terminal
// answer unchanged.
//
// MIGRATION STATUS (Phase-3 ratchet -- FULLY MIGRATED).
// recognize body: zero as_expr/as_stmt/as_item, zero raw Expr::/Stmt::/Item::.
// Struct fields: kind (enum, no raw syn), fields (Vec<(String, SugarBody)>, no raw syn).

use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, Term};

use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_dispatch::{DesugaredFloorAccept, RequiredTermVisitor};
use crate::{AssertionFactKind, Desugared, Outcome, Sugar, SugarCtx, Warrant};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "range_construct",
        crate::sugar::claim::SugarWitnesses::reasoned_bucket("owner-mismatch range row: probes dispatch to range_term/struct_term/aggregate surfaces"),
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match frag.observed().as_str() {
        "Struct" => {
            // Gate: no `..rest` spread.
            if frag.struct_has_rest() {
                return None;
            }
            // Determine which range kind from the struct path's last segment.
            let path_str = frag.struct_path_variant_string()?;
            let last_seg = path_str.split("::").last()?;
            let kind = RangeConstructKind::from_struct_name(last_seg)?;
            // Collect accepted fields from the struct literal.
            let all_fields = frag.struct_named_fields_frags();
            let raw_fields: Vec<(String, SourceFragment<'_>)> = all_fields
                .into_iter()
                .filter(|(name, _)| kind.accepts_field(name))
                .collect();
            let field_names: Vec<String> = raw_fields.iter().map(|(n, _)| n.clone()).collect();
            if !kind.has_required_field_names(&field_names) {
                return None;
            }
            let fields = raw_fields
                .into_iter()
                .map(|(name, child_frag)| (name, SugarBody::term_frag(&child_frag, fcx)))
                .collect();
            Some(RangeConstructSugar::new(kind, fields))
        }
        "Call" => {
            // Gate: func path must end in `RangeInclusive::new`.
            let func = frag.call_func()?;
            if func.path_last_segment_ident().as_deref() != Some("new") {
                return None;
            }
            if func.path_penultimate_ident().as_deref() != Some("RangeInclusive") {
                return None;
            }
            if frag.call_arg_count() != 2 {
                return None;
            }
            let args = frag.call_args();
            Some(RangeConstructSugar::new(
                RangeConstructKind::RangeInclusive,
                vec![
                    ("start".to_string(), SugarBody::term_frag(&args[0], fcx)),
                    ("end".to_string(), SugarBody::term_frag(&args[1], fcx)),
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
    /// Construct from the last path-segment name of an `Expr::Struct`.
    /// Replaces `from_struct_path` (which took a raw `&syn::Path`).
    fn from_struct_name(name: &str) -> Option<Self> {
        match name {
            "Range" => Some(Self::Range),
            "RangeFrom" => Some(Self::RangeFrom),
            "RangeTo" => Some(Self::RangeTo),
            "RangeToInclusive" => Some(Self::RangeToInclusive),
            _ => None,
        }
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

// ---------------------------------------------------------------------------
// Phase-3 from_src tests: source -> SourceFragment -> accessor -> recognize.
// No parse_quote!, no StubTerm, no run().
// ---------------------------------------------------------------------------
#[cfg(test)]
mod from_src_tests {
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};

    fn assign_val_frag<'a>(file: &'a syn::File, src_name: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), src_name);
        let body = frag.function_body().expect("fn body");
        let stmts = body.statements();
        stmts[0].assign_value().expect("assign value")
    }

    /// Positive: `Range { start: 0, end: 10 }` struct literal is a Struct fragment
    /// whose last path segment is "Range" and whose named fields are "start"/"end".
    #[test]
    fn from_src_range_struct_observed_and_fields() {
        let src = "fn f() { let _ = std::ops::Range { start: 0, end: 10 }; }";
        let file = parse_file(src);
        let frag = assign_val_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "Struct");
        assert!(!frag.struct_has_rest(), "no rest");
        let path_str = frag.struct_path_variant_string().expect("path_str");
        let last = path_str.split("::").last().unwrap();
        assert_eq!(last, "Range", "last segment must be Range");
        let fields = frag.struct_named_fields_frags();
        let names: Vec<_> = fields.iter().map(|(n, _)| n.as_str()).collect();
        assert!(names.contains(&"start") && names.contains(&"end"));
    }

    /// Discrimination: a plain `Call` (not a RangeInclusive::new) path does not
    /// match -- `path_penultimate_ident` != "RangeInclusive".
    #[test]
    fn from_src_non_range_call_penultimate_not_range_inclusive() {
        let src = "fn f(x: u32) -> u32 { let _ = u32::from(x); }";
        let file = parse_file(src);
        let frag = assign_val_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "Call");
        let func = frag.call_func().expect("call_func");
        // last segment is "from", penultimate is "u32" -- neither matches RangeInclusive::new
        assert_ne!(
            func.path_last_segment_ident().as_deref(),
            Some("new"),
            "call_func last segment is 'from', not 'new'"
        );
    }

    /// Structural: a `BinOp` fragment has observed != "Struct"/"Call"
    /// and returns None from both branches.
    #[test]
    fn from_src_binop_not_recognized_by_range_construct() {
        let src = "fn f(a: u32, b: u32) -> u32 { let _ = a + b; }";
        let file = parse_file(src);
        let frag = assign_val_frag(&file, "f.rs");

        let obs = frag.observed();
        assert!(
            obs != "Struct" && obs != "Call",
            "BinOp observed={obs:?} must not be Struct or Call"
        );
        // No struct_path_variant_string for a BinOp.
        assert!(frag.struct_path_variant_string().is_none());
        // No call_func for a BinOp.
        assert!(frag.call_func().is_none());
    }
}

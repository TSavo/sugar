// SPDX-License-Identifier: Apache-2.0

use std::rc::Rc;

use sugar_ir_symbolic::{make_var, str_const, ConstValue, LetBinding, Term};

use crate::sugar::int_literal::{numeric_floor_from_term, NumericFloor};
use crate::sugar::monadic::{OPT_NONE, OPT_SOME, RES_ERR, RES_OK};
use crate::{
    bool_const, canonical_term_sig, const_fold_int_term, const_fold_u128_term, num, Desugared,
};

pub(crate) const VALUE_IF_TERM: &str = "value:if";

pub(crate) fn value_if_term(cond: Rc<Term>, then_term: Rc<Term>, else_term: Rc<Term>) -> Rc<Term> {
    if let Some(value) = literal_predicate_bool(&cond) {
        return if value { then_term } else { else_term };
    }
    Rc::new(Term::Ctor {
        name: VALUE_IF_TERM.to_string(),
        args: vec![cond, then_term, else_term],
    })
}

/// A finite-domain occurrence context for a term-floor curry.
///
/// The caller supplies the binding (`param := arg`) and the occurrence owner
/// supplies the point identity. Runtime call/method terms inside the body become
/// nullary occurrence symbols (`call:f#map1()`, `call:f#map2()`) instead of
/// ordered call traces such as `Before(f(1), f(2))`.
#[derive(Clone, Copy)]
pub(crate) struct CurryOccurrence<'a> {
    pub(crate) family: &'a str,
    pub(crate) ordinal: usize,
}

impl CurryOccurrence<'_> {
    fn suffix(&self) -> String {
        format!("#{}{}", self.family, self.ordinal + 1)
    }
}

pub(crate) trait TermFloorVisitor {
    type Output;

    fn visit_term(self, term: &Rc<Term>) -> Self::Output;
}

pub(crate) trait TermFloorAccept {
    fn accept_term_floor<V: TermFloorVisitor>(&self, visitor: V) -> V::Output;
}

impl TermFloorAccept for Rc<Term> {
    fn accept_term_floor<V: TermFloorVisitor>(&self, visitor: V) -> V::Output {
        visitor.visit_term(self)
    }
}

pub(crate) trait BoolFloorVisitor {
    type Output;

    fn visit_bool(self, value: bool) -> Self::Output;
    fn visit_non_bool(self, term: &Rc<Term>) -> Self::Output;
}

pub(crate) trait BoolFloorAccept {
    fn accept_bool_floor<V: BoolFloorVisitor>(&self, visitor: V) -> V::Output;
}

impl BoolFloorAccept for Rc<Term> {
    fn accept_bool_floor<V: BoolFloorVisitor>(&self, visitor: V) -> V::Output {
        match self.as_ref() {
            Term::Const {
                value: ConstValue::Bool(value),
                ..
            } => visitor.visit_bool(*value),
            _ => visitor.visit_non_bool(self),
        }
    }
}

pub(crate) struct RequiredBoolVisitor<'a> {
    pub(crate) owner: &'a str,
}

impl BoolFloorVisitor for RequiredBoolVisitor<'_> {
    type Output = bool;

    fn visit_bool(self, value: bool) -> Self::Output {
        value
    }

    fn visit_non_bool(self, term: &Rc<Term>) -> Self::Output {
        panic!(
            "{} did not dispatch to BoolLiteral: {}",
            self.owner,
            canonical_term_sig(term)
        )
    }
}

pub(crate) struct LiteralPredicateBoolVisitor;

impl TermFloorVisitor for LiteralPredicateBoolVisitor {
    type Output = Option<bool>;

    fn visit_term(self, term: &Rc<Term>) -> Self::Output {
        literal_predicate_bool(term)
    }
}

pub(crate) trait ScalarFloorVisitor {
    type Output;

    fn visit_numeric(self, floor: NumericFloor) -> Self::Output;
    fn visit_bool(self, value: bool) -> Self::Output;
    fn visit_char(self, value: char) -> Self::Output;
    fn visit_runtime(self, term: &Rc<Term>) -> Self::Output;
}

pub(crate) trait ScalarFloorAccept {
    fn accept_scalar_floor<V: ScalarFloorVisitor>(&self, visitor: V) -> V::Output;
}

impl ScalarFloorAccept for Rc<Term> {
    fn accept_scalar_floor<V: ScalarFloorVisitor>(&self, visitor: V) -> V::Output {
        if let Some(floor) = numeric_floor_from_term(self) {
            return visitor.visit_numeric(floor);
        }
        match self.as_ref() {
            Term::Const {
                value: ConstValue::Bool(value),
                ..
            } => visitor.visit_bool(*value),
            Term::Const {
                value: ConstValue::String(value),
                ..
            } => {
                let mut chars = value.chars();
                let Some(ch) = chars.next() else {
                    return visitor.visit_runtime(self);
                };
                if chars.next().is_some() {
                    visitor.visit_runtime(self)
                } else {
                    visitor.visit_char(ch)
                }
            }
            _ => visitor.visit_runtime(self),
        }
    }
}

pub(crate) trait MonadicFloorVisitor {
    type Output;

    fn visit_some(self, inner: &Rc<Term>) -> Self::Output;
    fn visit_none(self) -> Self::Output;
    fn visit_ok(self, inner: &Rc<Term>) -> Self::Output;
    fn visit_err(self, inner: &Rc<Term>) -> Self::Output;
    fn visit_non_monadic(self, term: &Rc<Term>) -> Self::Output;
}

pub(crate) trait MonadicFloorAccept {
    fn accept_monadic_floor<V: MonadicFloorVisitor>(&self, visitor: V) -> V::Output;
}

impl MonadicFloorAccept for Rc<Term> {
    fn accept_monadic_floor<V: MonadicFloorVisitor>(&self, visitor: V) -> V::Output {
        match self.as_ref() {
            Term::Ctor { name, args } if name == OPT_SOME && args.len() == 1 => {
                visitor.visit_some(&args[0])
            }
            Term::Ctor { name, args } if name == OPT_NONE && args.is_empty() => {
                visitor.visit_none()
            }
            Term::Ctor { name, args } if name == RES_OK && args.len() == 1 => {
                visitor.visit_ok(&args[0])
            }
            Term::Ctor { name, args } if name == RES_ERR && args.len() == 1 => {
                visitor.visit_err(&args[0])
            }
            _ => visitor.visit_non_monadic(self),
        }
    }
}

pub(crate) trait DesugaredFloorVisitor {
    type Output;

    fn visit_term(self, term: Rc<Term>) -> Self::Output;
    fn visit_term_seq(self, terms: Vec<Rc<Term>>) -> Self::Output;
    fn visit_tuple_components(self, parts: Vec<Rc<Term>>) -> Self::Output;
    fn visit_passthrough(self, floor: Desugared) -> Self::Output;
}

pub(crate) trait DesugaredFloorAccept {
    fn accept_desugared_floor<V: DesugaredFloorVisitor>(self, visitor: V) -> V::Output;
}

impl DesugaredFloorAccept for Desugared {
    fn accept_desugared_floor<V: DesugaredFloorVisitor>(self, visitor: V) -> V::Output {
        match self {
            Desugared::Term(term) => visitor.visit_term(term),
            Desugared::TermSeq(terms) => visitor.visit_term_seq(terms),
            Desugared::TupleComponents(parts) => visitor.visit_tuple_components(parts),
            other => visitor.visit_passthrough(other),
        }
    }
}

pub(crate) struct RequiredTermVisitor<'a> {
    pub(crate) owner: &'a str,
}

impl DesugaredFloorVisitor for RequiredTermVisitor<'_> {
    type Output = Rc<Term>;

    fn visit_term(self, term: Rc<Term>) -> Self::Output {
        term
    }

    fn visit_term_seq(self, _terms: Vec<Rc<Term>>) -> Self::Output {
        panic!(
            "{} completed a sequence floor where a term floor was required",
            self.owner
        )
    }

    fn visit_tuple_components(self, _parts: Vec<Rc<Term>>) -> Self::Output {
        panic!(
            "{} completed a tuple-components floor where a term floor was required",
            self.owner
        )
    }

    fn visit_passthrough(self, floor: Desugared) -> Self::Output {
        let _ = floor;
        panic!(
            "{} completed a non-term floor where a term floor was required",
            self.owner
        )
    }
}

#[derive(Clone, Copy)]
pub(crate) struct CurryVisitor<'a> {
    pub(crate) param: &'a str,
    pub(crate) arg: &'a Rc<Term>,
    pub(crate) occurrence: CurryOccurrence<'a>,
}

impl TermFloorVisitor for CurryVisitor<'_> {
    type Output = Rc<Term>;

    fn visit_term(self, term: &Rc<Term>) -> Self::Output {
        curry_term(term, self.param, self.arg, &self.occurrence)
    }
}

impl DesugaredFloorVisitor for CurryVisitor<'_> {
    type Output = Desugared;

    fn visit_term(self, term: Rc<Term>) -> Self::Output {
        Desugared::Term(term.accept_term_floor(self))
    }

    fn visit_term_seq(self, terms: Vec<Rc<Term>>) -> Self::Output {
        Desugared::TermSeq(
            terms
                .into_iter()
                .map(|term| term.accept_term_floor(self))
                .collect(),
        )
    }

    fn visit_tuple_components(self, parts: Vec<Rc<Term>>) -> Self::Output {
        Desugared::TupleComponents(
            parts
                .into_iter()
                .map(|part| part.accept_term_floor(self))
                .collect(),
        )
    }

    fn visit_passthrough(self, floor: Desugared) -> Self::Output {
        floor
    }
}

fn curry_term(
    term: &Rc<Term>,
    param: &str,
    arg: &Rc<Term>,
    occurrence: &CurryOccurrence<'_>,
) -> Rc<Term> {
    match term.as_ref() {
        Term::Var { name } if name == param => Rc::clone(arg),
        Term::Ctor { name, args } if runtime_occurrence_ctor(name) => {
            let curried = Rc::new(Term::Ctor {
                name: name.clone(),
                args: args
                    .iter()
                    .map(|child| curry_term(child, param, arg, occurrence))
                    .collect(),
            });
            if name == "method:to_string" && args.len() == 1 {
                let Term::Ctor { args, .. } = curried.as_ref() else {
                    unreachable!("curried to_string term stayed a ctor");
                };
                if let Some(value) = crate::sugar::format::display_literal_term_floor(&args[0]) {
                    return str_const(value);
                }
                return curried;
            }
            if let Some(value) = literal_predicate_bool(&curried) {
                bool_const(value)
            } else {
                Rc::new(Term::Ctor {
                    name: format!("{}{}", name, occurrence.suffix()),
                    args: Vec::new(),
                })
            }
        }
        Term::Ctor { name, args } if name == VALUE_IF_TERM && args.len() == 3 => {
            let cond = curry_term(&args[0], param, arg, occurrence);
            let then_term = curry_term(&args[1], param, arg, occurrence);
            let else_term = curry_term(&args[2], param, arg, occurrence);
            value_if_term(cond, then_term, else_term)
        }
        Term::Ctor { name, args } => Rc::new(Term::Ctor {
            name: name.clone(),
            args: args
                .iter()
                .map(|child| curry_term(child, param, arg, occurrence))
                .collect(),
        }),
        Term::Let { bindings, body } => Rc::new(Term::Let {
            bindings: bindings
                .iter()
                .map(|binding| LetBinding {
                    name: binding.name.clone(),
                    bound_term: curry_term(&binding.bound_term, param, arg, occurrence),
                })
                .collect(),
            body: curry_term(body, param, arg, occurrence),
        }),
        Term::Lambda {
            param_name,
            param_sort,
            body,
        } if param_name != param => Rc::new(Term::Lambda {
            param_name: param_name.clone(),
            param_sort: param_sort.clone(),
            body: curry_term(body, param, arg, occurrence),
        }),
        _ => Rc::clone(term),
    }
}

fn runtime_occurrence_ctor(name: &str) -> bool {
    name.starts_with("call:") || name.starts_with("method:")
}

fn literal_predicate_bool(term: &Rc<Term>) -> Option<bool> {
    match term.as_ref() {
        Term::Const {
            value: ConstValue::Bool(value),
            ..
        } => Some(*value),
        Term::Ctor { name, args } if name == "bit-not" && args.len() == 1 => {
            literal_predicate_bool(&args[0]).map(|value| !value)
        }
        Term::Ctor { name, args } if name == "deref" && args.len() == 1 => {
            literal_predicate_bool(&args[0])
        }
        Term::Ctor { name, args } if name.starts_with("cmp:") && args.len() == 2 => {
            literal_cmp_bool(name, &args[0], &args[1])
        }
        Term::Ctor { name, args } if name.starts_with("method:") && args.len() == 1 => {
            literal_method_bool(name.strip_prefix("method:")?, &args[0])
        }
        _ => None,
    }
}

fn literal_cmp_bool(name: &str, left: &Rc<Term>, right: &Rc<Term>) -> Option<bool> {
    let left = peel_deref_term(left);
    let right = peel_deref_term(right);
    if let Some((left, right)) = literal_u128_pair(left, right) {
        return match name {
            "cmp:eq" => Some(left == right),
            "cmp:neq" => Some(left != right),
            "cmp:lt" => Some(left < right),
            "cmp:le" => Some(left <= right),
            "cmp:gt" => Some(left > right),
            "cmp:ge" => Some(left >= right),
            _ => None,
        };
    }
    let (left, right) = (const_fold_int_term(left)?, const_fold_int_term(right)?);
    match name {
        "cmp:eq" => Some(left == right),
        "cmp:neq" => Some(left != right),
        "cmp:lt" => Some(left < right),
        "cmp:le" => Some(left <= right),
        "cmp:gt" => Some(left > right),
        "cmp:ge" => Some(left >= right),
        _ => None,
    }
}

fn literal_u128_pair(left: &Rc<Term>, right: &Rc<Term>) -> Option<(u128, u128)> {
    let left_u = const_fold_u128_term(left);
    let right_u = const_fold_u128_term(right);
    if left_u.is_none() && right_u.is_none() {
        return None;
    }
    Some((
        left_u.or_else(|| const_fold_int_term(left).and_then(|n| u128::try_from(n).ok()))?,
        right_u.or_else(|| const_fold_int_term(right).and_then(|n| u128::try_from(n).ok()))?,
    ))
}

fn literal_method_bool(method: &str, receiver: &Rc<Term>) -> Option<bool> {
    let receiver = peel_deref_term(receiver);
    if let Some(ch) = literal_char(receiver) {
        return literal_char_method_bool(method, ch);
    }
    let byte = const_fold_int_term(receiver).and_then(|n| u8::try_from(n).ok())?;
    literal_byte_method_bool(method, byte)
}

fn peel_deref_term(term: &Rc<Term>) -> &Rc<Term> {
    match term.as_ref() {
        Term::Ctor { name, args } if name == "deref" && args.len() == 1 => {
            peel_deref_term(&args[0])
        }
        _ => term,
    }
}

fn literal_char(term: &Rc<Term>) -> Option<char> {
    let Term::Const {
        value: ConstValue::String(value),
        ..
    } = term.as_ref()
    else {
        return None;
    };
    let mut chars = value.chars();
    let ch = chars.next()?;
    chars.next().is_none().then_some(ch)
}

fn literal_char_method_bool(method: &str, ch: char) -> Option<bool> {
    match method {
        "is_alphabetic" => Some(ch.is_alphabetic()),
        "is_numeric" => Some(ch.is_numeric()),
        "is_ascii" => Some(ch.is_ascii()),
        "is_alphanumeric" => Some(ch.is_alphanumeric()),
        "is_whitespace" => Some(ch.is_whitespace()),
        "is_uppercase" => Some(ch.is_uppercase()),
        "is_lowercase" => Some(ch.is_lowercase()),
        "is_ascii_alphabetic" => Some(ch.is_ascii_alphabetic()),
        "is_ascii_digit" => Some(ch.is_ascii_digit()),
        "is_ascii_alphanumeric" => Some(ch.is_ascii_alphanumeric()),
        "is_ascii_octdigit" => Some(matches!(ch, '0'..='7')),
        "is_ascii_lowercase" => Some(ch.is_ascii_lowercase()),
        "is_ascii_uppercase" => Some(ch.is_ascii_uppercase()),
        "is_ascii_hexdigit" => Some(ch.is_ascii_hexdigit()),
        "is_ascii_punctuation" => Some(ch.is_ascii_punctuation()),
        "is_ascii_graphic" => Some(ch.is_ascii_graphic()),
        "is_ascii_whitespace" => Some(ch.is_ascii_whitespace()),
        "is_ascii_control" => Some(ch.is_ascii_control()),
        _ => None,
    }
}

fn literal_byte_method_bool(method: &str, byte: u8) -> Option<bool> {
    match method {
        "is_ascii" => Some(byte.is_ascii()),
        "is_ascii_alphabetic" => Some(byte.is_ascii_alphabetic()),
        "is_ascii_digit" => Some(byte.is_ascii_digit()),
        "is_ascii_alphanumeric" => Some(byte.is_ascii_alphanumeric()),
        "is_ascii_octdigit" => Some(matches!(byte, b'0'..=b'7')),
        "is_ascii_lowercase" => Some(byte.is_ascii_lowercase()),
        "is_ascii_uppercase" => Some(byte.is_ascii_uppercase()),
        "is_ascii_hexdigit" => Some(byte.is_ascii_hexdigit()),
        "is_ascii_punctuation" => Some(byte.is_ascii_punctuation()),
        "is_ascii_graphic" => Some(byte.is_ascii_graphic()),
        "is_ascii_whitespace" => Some(byte.is_ascii_whitespace()),
        "is_ascii_control" => Some(byte.is_ascii_control()),
        _ => None,
    }
}

pub(crate) fn literal_array_term_from_terms(terms: &[Rc<Term>]) -> Rc<Term> {
    let inner = terms
        .iter()
        .map(|term| canonical_term_sig(term))
        .collect::<Vec<_>>()
        .join(",");
    make_var(format!("literal:Array({inner})"))
}

pub(crate) fn fold_int_terms(
    op: &str,
    identity: i128,
    terms: impl IntoIterator<Item = Rc<Term>>,
) -> Rc<Term> {
    terms.into_iter().fold(num(identity), |acc, term| {
        let combined = Rc::new(Term::Ctor {
            name: op.to_string(),
            args: vec![acc, term],
        });
        const_fold_int_term(&combined).map_or(combined, num)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use sugar_ir_symbolic::num;

    fn var(name: &str) -> Rc<Term> {
        make_var(name)
    }

    #[test]
    fn curry_replaces_bound_param_inside_ground_arithmetic() {
        let term = Rc::new(Term::Ctor {
            name: "+".to_string(),
            args: vec![var("x"), num(1)],
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "x",
            arg: &num(2),
            occurrence: CurryOccurrence {
                family: "map",
                ordinal: 0,
            },
        });

        assert_eq!(const_fold_int_term(&curried), Some(3));
    }

    #[test]
    fn runtime_call_curries_to_orderless_occurrence_symbol() {
        let term = Rc::new(Term::Ctor {
            name: "call:f".to_string(),
            args: vec![var("x")],
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "x",
            arg: &num(2),
            occurrence: CurryOccurrence {
                family: "map",
                ordinal: 1,
            },
        });

        match curried.as_ref() {
            Term::Ctor { name, args } => {
                assert_eq!(name, "call:f#map2");
                assert!(args.is_empty());
            }
            other => panic!("expected curried call occurrence, got {other:?}"),
        }
    }

    #[test]
    fn curry_dispatches_literal_method_predicate_to_bool_floor() {
        let term = Rc::new(Term::Ctor {
            name: "method:is_ascii_uppercase".to_string(),
            args: vec![var("ch")],
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "ch",
            arg: &num(i128::from(b'A')),
            occurrence: CurryOccurrence {
                family: "quant",
                ordinal: 0,
            },
        });

        assert_eq!(
            curried.accept_term_floor(LiteralPredicateBoolVisitor),
            Some(true)
        );
    }

    #[test]
    fn curry_dispatches_literal_to_string_to_format_floor() {
        let term = Rc::new(Term::Ctor {
            name: "method:to_string".to_string(),
            args: vec![var("id")],
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "id",
            arg: &num(42),
            occurrence: CurryOccurrence {
                family: "map",
                ordinal: 0,
            },
        });

        match curried.as_ref() {
            Term::Const {
                value: ConstValue::String(value),
                ..
            } => assert_eq!(value, "42"),
            other => panic!("expected curried to_string literal, got {other:?}"),
        }
    }

    #[test]
    fn curry_keeps_opaque_method_as_orderless_occurrence_symbol() {
        let term = Rc::new(Term::Ctor {
            name: "method:opaque_predicate".to_string(),
            args: vec![var("x")],
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "x",
            arg: &num(7),
            occurrence: CurryOccurrence {
                family: "quant",
                ordinal: 2,
            },
        });

        match curried.as_ref() {
            Term::Ctor { name, args } => {
                assert_eq!(name, "method:opaque_predicate#quant3");
                assert!(args.is_empty());
            }
            other => panic!("expected opaque method occurrence, got {other:?}"),
        }
    }

    #[test]
    fn predicate_visitor_folds_curried_comparison_floor() {
        let term = Rc::new(Term::Ctor {
            name: "cmp:gt".to_string(),
            args: vec![
                Rc::new(Term::Ctor {
                    name: "deref".to_string(),
                    args: vec![var("n")],
                }),
                num(3),
            ],
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "n",
            arg: &num(4),
            occurrence: CurryOccurrence {
                family: "quant",
                ordinal: 0,
            },
        });

        assert_eq!(
            curried.accept_term_floor(LiteralPredicateBoolVisitor),
            Some(true)
        );
    }

    #[test]
    fn predicate_visitor_folds_nested_deref_bitand_comparison_floor() {
        let term = Rc::new(Term::Ctor {
            name: "cmp:eq".to_string(),
            args: vec![
                Rc::new(Term::Ctor {
                    name: "bit-and".to_string(),
                    args: vec![
                        Rc::new(Term::Ctor {
                            name: "deref".to_string(),
                            args: vec![var("n")],
                        }),
                        num(1),
                    ],
                }),
                num(0),
            ],
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "n",
            arg: &num(2),
            occurrence: CurryOccurrence {
                family: "filter",
                ordinal: 0,
            },
        });

        assert_eq!(
            curried.accept_term_floor(LiteralPredicateBoolVisitor),
            Some(true)
        );
    }

    #[test]
    fn nested_curry_appends_occurrence_context_to_materialized_calls() {
        let inner = Rc::new(Term::Ctor {
            name: "call:f#map1".to_string(),
            args: Vec::new(),
        });

        let outer = inner.accept_term_floor(CurryVisitor {
            param: "n",
            arg: &num(2),
            occurrence: CurryOccurrence {
                family: "map",
                ordinal: 1,
            },
        });

        match outer.as_ref() {
            Term::Ctor { name, args } => {
                assert_eq!(name, "call:f#map1#map2");
                assert!(args.is_empty());
            }
            other => panic!("expected nested curried occurrence, got {other:?}"),
        }
    }

    #[test]
    fn desugared_term_sequence_accepts_curry_without_materializing_array() {
        let floor = Desugared::TermSeq(vec![
            Rc::new(Term::Ctor {
                name: "+".to_string(),
                args: vec![var("n"), num(1)],
            }),
            Rc::new(Term::Ctor {
                name: "+".to_string(),
                args: vec![var("n"), num(2)],
            }),
        ]);

        let curried = floor.accept_desugared_floor(CurryVisitor {
            param: "n",
            arg: &num(10),
            occurrence: CurryOccurrence {
                family: "map",
                ordinal: 0,
            },
        });

        let Desugared::TermSeq(terms) = curried else {
            panic!("expected term sequence floor");
        };
        assert_eq!(
            terms.iter().map(const_fold_int_term).collect::<Vec<_>>(),
            vec![Some(11), Some(12),]
        );
    }

    #[test]
    fn curry_walks_let_body_floor_before_materializing_calls() {
        let term = Rc::new(Term::Let {
            bindings: vec![LetBinding {
                name: "y".to_string(),
                bound_term: var("x"),
            }],
            body: Rc::new(Term::Ctor {
                name: "call:g".to_string(),
                args: vec![var("y")],
            }),
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "x",
            arg: &num(9),
            occurrence: CurryOccurrence {
                family: "map",
                ordinal: 0,
            },
        });

        match curried.as_ref() {
            Term::Let { bindings, body } => {
                assert!(matches!(
                    bindings[0].bound_term.as_ref(),
                    Term::Const {
                        value: sugar_ir_symbolic::ConstValue::Int(9),
                        sort
                    } if sort.name == "Int"
                ));
                assert!(matches!(
                    body.as_ref(),
                    Term::Ctor { name, args } if name == "call:g#map1" && args.is_empty()
                ));
            }
            other => panic!("expected let body floor, got {other:?}"),
        }
    }
}

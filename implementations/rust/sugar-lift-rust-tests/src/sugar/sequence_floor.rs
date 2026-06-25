// SPDX-License-Identifier: Apache-2.0

use std::rc::Rc;

use sugar_ir_symbolic::Term;

use crate::sugar::term_dispatch::literal_array_term_from_terms;
use crate::{const_val_term, ConstVal, Desugared, DesugaredElem};

/// Dispatch a completed composite floor by whether it is a finite sequence.
pub(crate) trait SequenceFloorVisitor {
    type Output;

    fn visit_sequence(self, seq: Vec<DesugaredElem>) -> Self::Output;
    fn visit_non_sequence(self, floor: Desugared) -> Self::Output;
}

impl Desugared {
    pub(crate) fn accept_sequence_floor<V: SequenceFloorVisitor>(self, visitor: V) -> V::Output {
        match self {
            Desugared::Seq(seq) => visitor.visit_sequence(seq),
            other => visitor.visit_non_sequence(other),
        }
    }
}

#[derive(Clone, Copy)]
pub(crate) enum SequenceSelection {
    Elem(usize),
    Slice { start: usize, end: usize },
}

pub(crate) struct SequenceSelectionVisitor<'a> {
    pub(crate) owner: &'a str,
    pub(crate) selection: SequenceSelection,
}

impl SequenceFloorVisitor for SequenceSelectionVisitor<'_> {
    type Output = Rc<Term>;

    fn visit_sequence(self, seq: Vec<DesugaredElem>) -> Self::Output {
        match self.selection {
            SequenceSelection::Elem(index) => elem_term(
                seq.get(index).unwrap_or_else(|| {
                    panic!("{} selected element outside sequence floor", self.owner)
                }),
                self.owner,
            ),
            SequenceSelection::Slice { start, end } => {
                if start > end || end > seq.len() {
                    panic!("{} selected slice outside sequence floor", self.owner);
                }
                let terms = seq[start..end]
                    .iter()
                    .map(|elem| elem_term(elem, self.owner))
                    .collect::<Vec<_>>();
                literal_array_term_from_terms(&terms)
            }
        }
    }

    fn visit_non_sequence(self, floor: Desugared) -> Self::Output {
        let _ = floor;
        panic!(
            "{} completed a non-sequence floor where sequence selection was required",
            self.owner
        )
    }
}

pub(crate) struct RequiredSequenceVisitor<'a> {
    pub(crate) owner: &'a str,
}

impl SequenceFloorVisitor for RequiredSequenceVisitor<'_> {
    type Output = Vec<DesugaredElem>;

    fn visit_sequence(self, seq: Vec<DesugaredElem>) -> Self::Output {
        seq
    }

    fn visit_non_sequence(self, floor: Desugared) -> Self::Output {
        let _ = floor;
        panic!(
            "{} completed a non-sequence floor where a sequence floor was required",
            self.owner
        )
    }
}

/// Dispatch a completed sequence element by the literal floor it carries.
///
/// Sequence adaptors such as `flatten` and `kmerge` do not reconstruct nested
/// sugar from the element's raw expression. They ask the completed element floor
/// whether it is itself a finite sequence and compose the visitor's answer.
pub(crate) trait SequenceElementVisitor {
    type Output;

    fn visit_sequence(self, seq: Vec<DesugaredElem>) -> Self::Output;
    fn visit_runtime(self, elem: &DesugaredElem) -> Self::Output;
    fn visit_non_sequence_literal(self, elem: &DesugaredElem) -> Self::Output;
}

impl DesugaredElem {
    pub(crate) fn accept_sequence<V: SequenceElementVisitor>(&self, visitor: V) -> V::Output {
        match &self.value {
            Some(ConstVal::Array(items)) => {
                let seq = items
                    .iter()
                    .map(desugared_elem_from_const)
                    .collect::<Option<Vec<_>>>()
                    .unwrap_or_else(|| {
                        panic!("array literal floor contained an unmaterializable element")
                    });
                visitor.visit_sequence(seq)
            }
            Some(_) => visitor.visit_non_sequence_literal(self),
            None => visitor.visit_runtime(self),
        }
    }
}

fn desugared_elem_from_const(value: &ConstVal) -> Option<DesugaredElem> {
    Some(DesugaredElem {
        expr: value.to_expr()?,
        value: Some(value.clone()),
    })
}

fn elem_term(elem: &DesugaredElem, owner: &str) -> Rc<Term> {
    elem.value
        .as_ref()
        .and_then(const_val_term)
        .unwrap_or_else(|| {
            panic!("{owner} sequence element did not dispatch to a literal term floor")
        })
}

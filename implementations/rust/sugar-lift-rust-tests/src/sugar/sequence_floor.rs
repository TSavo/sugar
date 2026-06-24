// SPDX-License-Identifier: Apache-2.0

use crate::{ConstVal, Desugared, DesugaredElem};

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

pub(crate) struct RequiredSequenceVisitor<'a> {
    pub(crate) owner: &'a str,
}

impl SequenceFloorVisitor for RequiredSequenceVisitor<'_> {
    type Output = Vec<DesugaredElem>;

    fn visit_sequence(self, seq: Vec<DesugaredElem>) -> Self::Output {
        seq
    }

    fn visit_non_sequence(self, floor: Desugared) -> Self::Output {
        panic!(
            "{} completed a non-sequence floor where a sequence floor was required: {:?}",
            self.owner, floor
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

// SPDX-License-Identifier: MIT OR Apache-2.0

//! Term-level transport for discharged language morphisms.
//!
//! The morphism discharges live in the menagerie as content-addressed
//! artifacts. This module is the corresponding functorial lift on free terms:
//! rewrite each operation node through a discharged operation row and recurse
//! into the children, refusing when the source algebra contains an operation the
//! transport table does not cover.

use std::collections::BTreeMap;

use thiserror::Error;

use crate::core::{Cid, Term};

/// One discharged operation-level transport row.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OperationTransport {
    pub source_name: String,
    pub source_cid: Cid,
    pub target_name: String,
    pub target_cid: Cid,
}

impl OperationTransport {
    pub fn new(
        source_name: impl Into<String>,
        source_cid: Cid,
        target_name: impl Into<String>,
        target_cid: Cid,
    ) -> Self {
        Self {
            source_name: source_name.into(),
            source_cid,
            target_name: target_name.into(),
            target_cid,
        }
    }
}

/// A finite operation map for one source-to-target language transport.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct TermTransport {
    operations: BTreeMap<String, OperationTransport>,
}

impl TermTransport {
    pub fn new(rows: Vec<OperationTransport>) -> Self {
        Self {
            operations: rows
                .into_iter()
                .map(|row| (row.source_name.clone(), row))
                .collect(),
        }
    }

    pub fn operation(&self, source_name: &str) -> Option<&OperationTransport> {
        self.operations.get(source_name)
    }
}

/// Apply a discharged term transport by structural recursion.
pub fn transport_term(transport: &TermTransport, term: &Term) -> Result<Term, TransportError> {
    match term {
        Term::Op { op_cid, name, args } => {
            let row = transport.operation(name).ok_or_else(|| {
                TransportError::MissingOperationMorphism {
                    source_name: name.clone(),
                }
            })?;
            if &row.source_cid != op_cid {
                return Err(TransportError::OperationCidMismatch {
                    source_name: name.clone(),
                    expected: row.source_cid.clone(),
                    actual: op_cid.clone(),
                });
            }

            let args = args
                .iter()
                .map(|arg| transport_term(transport, arg))
                .collect::<Result<Vec<_>, _>>()?;
            Ok(Term::Op {
                op_cid: row.target_cid.clone(),
                name: row.target_name.clone(),
                args,
            })
        }
        Term::Var { name } => Ok(Term::Var { name: name.clone() }),
        Term::Const { value, sort } => Ok(Term::Const {
            value: value.clone(),
            sort: sort.clone(),
        }),
        Term::Unit => Ok(Term::Unit),
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum TransportError {
    #[error("missing discharged morphism for operation `{source_name}`")]
    MissingOperationMorphism { source_name: String },
    #[error("operation `{source_name}` CID mismatch: expected {expected}, got {actual}")]
    OperationCidMismatch {
        source_name: String,
        expected: Cid,
        actual: Cid,
    },
}

// SPDX-License-Identifier: MIT OR Apache-2.0
//
// GENERATED FILE: DO NOT EDIT
// Source: protocol/sugar-ir.cddl
// Generator: sugar-ir-codegen

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum IrFormula {
    #[serde(rename = "atomic")]
    AtomicFormula {
        pub name: AtomicPredicateName,
        pub args: Vec<IrTerm>,
    },
    #[serde(rename = "ConnectiveFormula")]
    ConnectiveFormula {
        pub operands: Vec<IrFormula>,
    },
    #[serde(rename = "QuantifierFormula")]
    QuantifierFormula {
        pub name: String,
        pub sort: Sort,
        pub body: IrFormula,
    },
    #[serde(rename = "choice")]
    ChoiceFormula {
        #[serde(rename = "varName")]
        pub var_name: String,
        pub sort: Sort,
        pub body: IrFormula,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AtomicFormula {
    pub kind: String,
    pub name: AtomicPredicateName,
    pub args: Vec<IrTerm>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LetTerm {
    pub kind: String,
    pub bindings: Vec<LetBinding>,
    pub body: IrTerm,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum Value {
    #[serde(rename = "text")]
    Text,
    #[serde(rename = "number")]
    Number,
    #[serde(rename = "bool")]
    Bool,
    #[serde(rename = "null")]
    Null,
}

pub type AtomicPredicateName = String;
// Known values for AtomicPredicateName:
//   "="
//   "≠"
//   "<"
//   "≤"
//   ">"
//   "≥"
//   "true"
//   "false"
//   "bvult"
//   "bvule"
//   "bvugt"
//   "bvuge"
//   "bvslt"
//   "bvsle"
//   "bvsgt"
//   "bvsge"

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PrimitiveSort {
    pub kind: String,
    pub name: PrimitiveSortName,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LetBinding {
    pub name: String,
    #[serde(rename = "boundTerm")]
    pub bound_term: IrTerm,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ContractDeclaration {
    pub kind: String,
    pub name: String,
    #[serde(rename = "outBinding")]
    pub out_binding: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pre: Option<IrFormula>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub post: Option<IrFormula>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub inv: Option<IrFormula>,
}

pub type Sort = PrimitiveSort;

pub type ConnectiveKind = String;
// Known values for ConnectiveKind:
//   "and"
//   "or"
//   "not"
//   "implies"

pub type Document = Vec<Declaration>;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct QuantifierFormula {
    pub kind: QuantifierKind,
    pub name: String,
    pub sort: Sort,
    pub body: IrFormula,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum Declaration {
    #[serde(rename = "contract")]
    ContractDeclaration {
        pub name: String,
        #[serde(rename = "outBinding")]
        pub out_binding: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        pub pre: Option<IrFormula>,
        #[serde(skip_serializing_if = "Option::is_none")]
        pub post: Option<IrFormula>,
        #[serde(skip_serializing_if = "Option::is_none")]
        pub inv: Option<IrFormula>,
    },
    #[serde(rename = "bridge")]
    BridgeDeclaration {
        pub name: String,
        #[serde(rename = "sourceSymbol")]
        pub source_symbol: String,
        #[serde(rename = "sourceLayer")]
        pub source_layer: String,
        #[serde(rename = "targetContractCid")]
        pub target_contract_cid: String,
        #[serde(rename = "targetLayer")]
        pub target_layer: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        pub notes: Option<String>,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ConstTerm {
    pub kind: String,
    pub value: serde_json::Value,
    pub sort: Sort,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChoiceFormula {
    pub kind: String,
    #[serde(rename = "varName")]
    pub var_name: String,
    pub sort: Sort,
    pub body: IrFormula,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum IrTerm {
    #[serde(rename = "var")]
    VarTerm {
        pub name: String,
    },
    #[serde(rename = "const")]
    ConstTerm {
        pub value: serde_json::Value,
        pub sort: Sort,
    },
    #[serde(rename = "ctor")]
    CtorTerm {
        pub name: String,
        pub args: Vec<IrTerm>,
    },
    #[serde(rename = "lambda")]
    LambdaTerm {
        #[serde(rename = "paramName")]
        pub param_name: String,
        #[serde(rename = "paramSort")]
        pub param_sort: Sort,
        pub body: IrTerm,
    },
    #[serde(rename = "let")]
    LetTerm {
        pub bindings: Vec<LetBinding>,
        pub body: IrTerm,
    },
}

pub type ProofType = String;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BridgeDeclaration {
    pub kind: String,
    pub name: String,
    #[serde(rename = "sourceSymbol")]
    pub source_symbol: String,
    #[serde(rename = "sourceLayer")]
    pub source_layer: String,
    #[serde(rename = "targetContractCid")]
    pub target_contract_cid: String,
    #[serde(rename = "targetLayer")]
    pub target_layer: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub notes: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CtorTerm {
    pub kind: String,
    pub name: String,
    pub args: Vec<IrTerm>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EvidenceTerm {
    pub kind: String,
    #[serde(rename = "proofType")]
    pub proof_type: ProofType,
    pub certificate: EvidenceCertificate,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EvidenceCertificate {
    pub tool: String,
    pub version: String,
    #[serde(rename = "formulaHash")]
    pub formula_hash: String,
    #[serde(rename = "proofData")]
    pub proof_data: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VarTerm {
    pub kind: String,
    pub name: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LambdaTerm {
    pub kind: String,
    #[serde(rename = "paramName")]
    pub param_name: String,
    #[serde(rename = "paramSort")]
    pub param_sort: Sort,
    pub body: IrTerm,
}

pub type PrimitiveSortName = String;
// Known values for PrimitiveSortName:
//   "Int"
//   "Real"
//   "Bool"
//   "String"

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ConnectiveFormula {
    pub kind: ConnectiveKind,
    pub operands: Vec<IrFormula>,
}

pub type QuantifierKind = String;
// Known values for QuantifierKind:
//   "forall"
//   "exists"

pub type Term = IrTerm;
pub type Formula = IrFormula;

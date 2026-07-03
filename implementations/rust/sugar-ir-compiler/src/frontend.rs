// SPDX-License-Identifier: Apache-2.0
//
// Typed ProofIR frontend adapter. This is the one legal transport-JSON decode
// point during the frontend-boundary campaign; backend drains move behind it.

use std::fmt;

use serde::{Deserialize, Serialize};
use serde_json::Value as Json;
use sugar_ir_types::{Formula, IrTerm, Term};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum CompilerInput {
    Formula(Formula),
    Term(Term),
    EquationalTheory(EquationalTheoryObligation),
}

impl CompilerInput {
    pub fn decode_json(ir: Json) -> Result<Self, FrontendError> {
        let Some(object) = ir.as_object() else {
            return Err(frontend_error(
                FrontendErrorKind::MalformedTransport,
                "$",
                "ProofIR compiler input must be a JSON object",
            ));
        };
        let Some(kind) = object.get("kind").and_then(|value| value.as_str()) else {
            return Err(frontend_error(
                FrontendErrorKind::MalformedTransport,
                "$.kind",
                "ProofIR compiler input must carry a string kind",
            ));
        };

        if is_legacy_raw_kind(kind) {
            return Err(frontend_error(
                FrontendErrorKind::UnsupportedLegacyVariant,
                "$.kind",
                format!("legacy raw frontend variant `{kind}` is not a typed CompilerInput"),
            ));
        }

        if is_equational_theory_object(object) {
            return serde_json::from_value::<EquationalTheoryObligation>(ir)
                .map(CompilerInput::EquationalTheory)
                .map_err(invalid_typed_ir);
        }

        if is_term_kind(kind) {
            return serde_json::from_value::<Term>(ir)
                .map(CompilerInput::Term)
                .map_err(invalid_typed_ir);
        }

        if is_formula_kind(kind) {
            return serde_json::from_value::<Formula>(ir)
                .map(CompilerInput::Formula)
                .map_err(invalid_typed_ir);
        }

        Err(frontend_error(
            FrontendErrorKind::UnknownInputKind,
            "$.kind",
            format!("unknown ProofIR compiler input kind `{kind}`"),
        ))
    }

    pub fn to_json_value(&self) -> Result<Json, FrontendError> {
        match self {
            CompilerInput::Formula(formula) => serde_json::to_value(formula),
            CompilerInput::Term(term) => serde_json::to_value(term),
            CompilerInput::EquationalTheory(obligation) => serde_json::to_value(obligation),
        }
        .map_err(|error| {
            frontend_error(
                FrontendErrorKind::InvalidTypedIr,
                "$",
                format!("failed to serialize typed CompilerInput: {error}"),
            )
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EquationalTheoryObligation {
    pub kind: String,
    pub name: Option<String>,
    pub theory: EquationalTheory,
    pub obligation: EquationalEquation,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EquationalTheory {
    pub name: String,
    #[serde(default)]
    pub sorts: Vec<String>,
    #[serde(default)]
    pub subsorts: Vec<EquationalSubsort>,
    #[serde(default)]
    pub operators: Vec<EquationalOperator>,
    #[serde(default)]
    pub variables: Vec<EquationalVariable>,
    #[serde(default)]
    pub equations: Vec<EquationalEquation>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EquationalSubsort {
    pub subsort: String,
    pub supersort: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EquationalOperator {
    pub name: String,
    #[serde(default)]
    pub maude: Option<String>,
    #[serde(default)]
    pub arity: Vec<String>,
    pub result: String,
    #[serde(default)]
    pub attrs: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EquationalVariable {
    pub name: String,
    pub sort: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EquationalEquation {
    #[serde(default)]
    pub label: Option<String>,
    pub lhs: IrTerm,
    pub rhs: IrTerm,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FrontendErrorKind {
    MalformedTransport,
    UnknownInputKind,
    InvalidTypedIr,
    UnsupportedLegacyVariant,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FrontendErrorPayload {
    pub kind: FrontendErrorKind,
    pub frontend: String,
    pub input_format: String,
    pub path: String,
    pub detail: String,
    pub retirement: String,
}

impl fmt::Display for FrontendErrorPayload {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{:?} at {} in {}: {} (retirement: {})",
            self.kind, self.path, self.input_format, self.detail, self.retirement
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FrontendError {
    pub payload: FrontendErrorPayload,
}

impl fmt::Display for FrontendError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.payload.fmt(f)
    }
}

impl std::error::Error for FrontendError {}

fn frontend_error(
    kind: FrontendErrorKind,
    path: impl Into<String>,
    detail: impl Into<String>,
) -> FrontendError {
    FrontendError {
        payload: FrontendErrorPayload {
            kind,
            frontend: "sugar-ir-compiler::frontend::CompilerInput::decode_json".to_string(),
            input_format: "proofir-json".to_string(),
            path: path.into(),
            detail: detail.into(),
            retirement:
                "S7 deletes the legacy compile(&Json) adapter once typed compiler inputs are universal"
                    .to_string(),
        },
    }
}

fn invalid_typed_ir(error: serde_json::Error) -> FrontendError {
    frontend_error(FrontendErrorKind::InvalidTypedIr, "$", error.to_string())
}

fn is_term_kind(kind: &str) -> bool {
    matches!(kind, "var" | "const" | "ctor" | "lambda" | "let")
}

fn is_formula_kind(kind: &str) -> bool {
    matches!(
        kind,
        "atomic"
            | "and"
            | "or"
            | "not"
            | "implies"
            | "forall"
            | "exists"
            | "choice"
            | "substitute"
            | "apply"
            | "divergence-between"
    )
}

fn is_equational_theory_object(object: &serde_json::Map<String, Json>) -> bool {
    let kind_is_equational = object
        .get("kind")
        .and_then(|value| value.as_str())
        .is_some_and(|kind| kind == "equational_theory");
    let name_is_equational = object
        .get("name")
        .and_then(|value| value.as_str())
        .is_some_and(|name| name == "equational_theory");
    (kind_is_equational || name_is_equational)
        && object.contains_key("theory")
        && object.contains_key("obligation")
}

fn is_legacy_raw_kind(kind: &str) -> bool {
    matches!(kind, "legacy_raw_json" | "legacy-json" | "raw_json")
}

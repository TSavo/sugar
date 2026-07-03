// SPDX-License-Identifier: Apache-2.0
//
// Typed ProofIR frontend adapter. This is the one legal transport-JSON decode
// point during the frontend-boundary campaign; backend drains move behind it.

use std::cmp::Ordering;
use std::fmt;

use serde::{Deserialize, Serialize};
use serde_json::{Map as JsonMap, Number as JsonNumber, Value as Json};
use sugar_ir_types::{Formula, IrTerm, Term};

const BINARY_FRONTEND_ID: &str = "sugar-ir-compiler::frontend::BinaryProofIrFrontend::decode";
const BINARY_INPUT_FORMAT: &str = "proofir-cbor-v1";
const BINARY_MAGIC: &[u8] = b"sugar-proofir-cbor-v1\0";

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

/// Binary ProofIR frontend over the canonical `proofir-cbor-v1` transport.
pub struct BinaryProofIrFrontend;

impl BinaryProofIrFrontend {
    pub fn decode(bytes: &[u8]) -> Result<CompilerInput, FrontendError> {
        let Some(payload) = bytes.strip_prefix(BINARY_MAGIC) else {
            return Err(binary_frontend_error(
                FrontendErrorKind::MalformedTransport,
                "$",
                "ProofIR binary input is missing the proofir-cbor-v1 magic prefix",
            ));
        };
        let json = decode_cbor_json(payload)?;
        CompilerInput::decode_json(json).map_err(remap_frontend_error_to_binary)
    }

    pub fn encode(input: &CompilerInput) -> Result<Vec<u8>, FrontendError> {
        let json = input
            .to_json_value()
            .map_err(remap_frontend_error_to_binary)?;
        let mut out = BINARY_MAGIC.to_vec();
        encode_cbor_json(&json, &mut out)?;
        Ok(out)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CompiledFormulaFieldPath {
    Preamble,
    Body,
    FreeVars,
    OpacityManifest,
    Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FrontendProvenancePolicy {
    pub owner: String,
    pub allowed_fields: Vec<CompiledFormulaFieldPath>,
    pub reason: String,
    pub retirement: Option<String>,
}

impl FrontendProvenancePolicy {
    pub fn admits(&self, field: CompiledFormulaFieldPath) -> bool {
        self.is_well_formed() && self.allowed_fields.contains(&field)
    }

    pub fn is_well_formed(&self) -> bool {
        !self.owner.trim().is_empty()
            && !self.reason.trim().is_empty()
            && self
                .retirement
                .as_deref()
                .is_some_and(|retirement| !retirement.trim().is_empty())
            && !self.allowed_fields.is_empty()
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
                "transport formats terminate at frontend decode; backends receive CompilerInput"
                    .to_string(),
        },
    }
}

fn binary_frontend_error(
    kind: FrontendErrorKind,
    path: impl Into<String>,
    detail: impl Into<String>,
) -> FrontendError {
    FrontendError {
        payload: FrontendErrorPayload {
            kind,
            frontend: BINARY_FRONTEND_ID.to_string(),
            input_format: BINARY_INPUT_FORMAT.to_string(),
            path: path.into(),
            detail: detail.into(),
            retirement: "binary ProofIR remains a typed frontend; backends receive CompilerInput"
                .to_string(),
        },
    }
}

fn remap_frontend_error_to_binary(error: FrontendError) -> FrontendError {
    FrontendError {
        payload: FrontendErrorPayload {
            frontend: BINARY_FRONTEND_ID.to_string(),
            input_format: BINARY_INPUT_FORMAT.to_string(),
            retirement: "binary ProofIR remains a typed frontend; backends receive CompilerInput"
                .to_string(),
            ..error.payload
        },
    }
}

fn invalid_typed_ir(error: serde_json::Error) -> FrontendError {
    frontend_error(FrontendErrorKind::InvalidTypedIr, "$", error.to_string())
}

fn encode_cbor_json(value: &Json, out: &mut Vec<u8>) -> Result<(), FrontendError> {
    match value {
        Json::Null => out.push(0xf6),
        Json::Bool(false) => out.push(0xf4),
        Json::Bool(true) => out.push(0xf5),
        Json::Number(number) => encode_cbor_number(number, out)?,
        Json::String(text) => encode_cbor_text(text, out),
        Json::Array(values) => {
            encode_cbor_type_and_len(out, 4, values.len() as u64);
            for value in values {
                encode_cbor_json(value, out)?;
            }
        }
        Json::Object(map) => {
            let mut entries = Vec::with_capacity(map.len());
            for (key, value) in map {
                let mut key_bytes = Vec::new();
                encode_cbor_text(key, &mut key_bytes);
                let mut value_bytes = Vec::new();
                encode_cbor_json(value, &mut value_bytes)?;
                entries.push((key_bytes, value_bytes));
            }
            entries.sort_by(|left, right| cbor_key_order(&left.0, &right.0));
            encode_cbor_type_and_len(out, 5, entries.len() as u64);
            for (key_bytes, value_bytes) in entries {
                out.extend_from_slice(&key_bytes);
                out.extend_from_slice(&value_bytes);
            }
        }
    }
    Ok(())
}

fn encode_cbor_number(number: &JsonNumber, out: &mut Vec<u8>) -> Result<(), FrontendError> {
    if let Some(unsigned) = number.as_u64() {
        encode_cbor_type_and_len(out, 0, unsigned);
        return Ok(());
    }
    if let Some(signed) = number.as_i64() {
        if signed >= 0 {
            encode_cbor_type_and_len(out, 0, signed as u64);
        } else {
            encode_cbor_type_and_len(out, 1, (-1i128 - signed as i128) as u64);
        }
        return Ok(());
    }
    let Some(float) = number.as_f64() else {
        return Err(binary_frontend_error(
            FrontendErrorKind::InvalidTypedIr,
            "$",
            "ProofIR number is not representable by proofir-cbor-v1",
        ));
    };
    out.push(0xfb);
    out.extend_from_slice(&float.to_bits().to_be_bytes());
    Ok(())
}

fn encode_cbor_text(text: &str, out: &mut Vec<u8>) {
    encode_cbor_type_and_len(out, 3, text.len() as u64);
    out.extend_from_slice(text.as_bytes());
}

fn encode_cbor_type_and_len(out: &mut Vec<u8>, major: u8, len: u64) {
    let prefix = major << 5;
    match len {
        0..=23 => out.push(prefix | len as u8),
        24..=0xff => {
            out.push(prefix | 24);
            out.push(len as u8);
        }
        0x100..=0xffff => {
            out.push(prefix | 25);
            out.extend_from_slice(&(len as u16).to_be_bytes());
        }
        0x1_0000..=0xffff_ffff => {
            out.push(prefix | 26);
            out.extend_from_slice(&(len as u32).to_be_bytes());
        }
        _ => {
            out.push(prefix | 27);
            out.extend_from_slice(&len.to_be_bytes());
        }
    }
}

fn cbor_key_order(left: &[u8], right: &[u8]) -> Ordering {
    left.len().cmp(&right.len()).then_with(|| left.cmp(right))
}

fn decode_cbor_json(bytes: &[u8]) -> Result<Json, FrontendError> {
    let mut cursor = CborCursor { bytes, pos: 0 };
    let value = cursor.decode_value("$")?;
    if cursor.pos != cursor.bytes.len() {
        return Err(binary_frontend_error(
            FrontendErrorKind::MalformedTransport,
            "$",
            "ProofIR binary input has trailing bytes after the CBOR value",
        ));
    }
    Ok(value)
}

struct CborCursor<'a> {
    bytes: &'a [u8],
    pos: usize,
}

impl CborCursor<'_> {
    fn decode_value(&mut self, path: &str) -> Result<Json, FrontendError> {
        let (major, arg) = self.read_head(path)?;
        match major {
            0 => Ok(Json::Number(JsonNumber::from(arg))),
            1 => {
                if arg > i64::MAX as u64 {
                    return Err(self.malformed(
                        path,
                        "negative CBOR integer is outside serde_json's i64 range",
                    ));
                }
                Ok(Json::Number(JsonNumber::from(
                    (-1i128 - arg as i128) as i64,
                )))
            }
            3 => {
                let bytes = self.read_bytes(arg, path)?;
                let text = std::str::from_utf8(bytes).map_err(|error| {
                    binary_frontend_error(
                        FrontendErrorKind::MalformedTransport,
                        path,
                        format!("CBOR text string is not UTF-8: {error}"),
                    )
                })?;
                Ok(Json::String(text.to_string()))
            }
            4 => {
                let len = self.len_to_usize(arg, path)?;
                let mut values = Vec::with_capacity(len);
                for index in 0..len {
                    values.push(self.decode_value(&format!("{path}[{index}]"))?);
                }
                Ok(Json::Array(values))
            }
            5 => {
                let len = self.len_to_usize(arg, path)?;
                let mut map = JsonMap::new();
                let mut previous_key: Option<Vec<u8>> = None;
                for _ in 0..len {
                    let key_start = self.pos;
                    let key_value = self.decode_value(path)?;
                    let key_end = self.pos;
                    let Json::String(key) = key_value else {
                        return Err(self.malformed(path, "CBOR map key is not a text string"));
                    };
                    let encoded_key = self.bytes[key_start..key_end].to_vec();
                    if let Some(previous) = previous_key.as_deref() {
                        if cbor_key_order(previous, &encoded_key) != Ordering::Less {
                            return Err(self.malformed(
                                path,
                                "CBOR map keys are not in canonical order or contain a duplicate",
                            ));
                        }
                    }
                    previous_key = Some(encoded_key);
                    let value = self.decode_value(&format!("{path}.{key}"))?;
                    if map.insert(key, value).is_some() {
                        return Err(self.malformed(path, "CBOR map contains a duplicate key"));
                    }
                }
                Ok(Json::Object(map))
            }
            7 if arg == 20 => Ok(Json::Bool(false)),
            7 if arg == 21 => Ok(Json::Bool(true)),
            7 if arg == 22 => Ok(Json::Null),
            7 if arg == 27 => {
                let bytes = self.read_bytes(8, path)?;
                let mut raw = [0u8; 8];
                raw.copy_from_slice(bytes);
                let float = f64::from_bits(u64::from_be_bytes(raw));
                let Some(number) = JsonNumber::from_f64(float) else {
                    return Err(self.malformed(path, "CBOR float is not a finite JSON number"));
                };
                Ok(Json::Number(number))
            }
            _ => Err(self.malformed(
                path,
                "proofir-cbor-v1 supports only JSON-compatible CBOR primitives",
            )),
        }
    }

    fn read_head(&mut self, path: &str) -> Result<(u8, u64), FrontendError> {
        let initial = self.read_u8(path)?;
        let major = initial >> 5;
        let additional = initial & 0x1f;
        let arg = match additional {
            0..=23 => additional as u64,
            24 => {
                let value = self.read_u8(path)? as u64;
                if value < 24 {
                    return Err(self.malformed(path, "CBOR integer uses non-canonical width"));
                }
                value
            }
            25 if major == 7 => {
                return Err(self.malformed(path, "short CBOR floats are not proofir-cbor-v1"));
            }
            25 => {
                let value = self.read_be_u16(path)? as u64;
                if value <= 0xff {
                    return Err(self.malformed(path, "CBOR integer uses non-canonical width"));
                }
                value
            }
            26 if major == 7 => {
                return Err(self.malformed(path, "short CBOR floats are not proofir-cbor-v1"));
            }
            26 => {
                let value = self.read_be_u32(path)? as u64;
                if value <= 0xffff {
                    return Err(self.malformed(path, "CBOR integer uses non-canonical width"));
                }
                value
            }
            27 if major == 7 => 27,
            27 => self.read_be_u64(path)?,
            _ => return Err(self.malformed(path, "indefinite-length CBOR is not canonical")),
        };
        Ok((major, arg))
    }

    fn read_u8(&mut self, path: &str) -> Result<u8, FrontendError> {
        let Some(byte) = self.bytes.get(self.pos) else {
            return Err(self.malformed(path, "unexpected end of proofir-cbor-v1 input"));
        };
        self.pos += 1;
        Ok(*byte)
    }

    fn read_be_u16(&mut self, path: &str) -> Result<u16, FrontendError> {
        let bytes = self.read_bytes(2, path)?;
        Ok(u16::from_be_bytes([bytes[0], bytes[1]]))
    }

    fn read_be_u32(&mut self, path: &str) -> Result<u32, FrontendError> {
        let bytes = self.read_bytes(4, path)?;
        Ok(u32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
    }

    fn read_be_u64(&mut self, path: &str) -> Result<u64, FrontendError> {
        let bytes = self.read_bytes(8, path)?;
        Ok(u64::from_be_bytes([
            bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5], bytes[6], bytes[7],
        ]))
    }

    fn read_bytes(&mut self, len: u64, path: &str) -> Result<&[u8], FrontendError> {
        let len = self.len_to_usize(len, path)?;
        let end = self
            .pos
            .checked_add(len)
            .ok_or_else(|| self.malformed(path, "proofir-cbor-v1 length overflows usize"))?;
        if end > self.bytes.len() {
            return Err(self.malformed(path, "unexpected end of proofir-cbor-v1 input"));
        }
        let bytes = &self.bytes[self.pos..end];
        self.pos = end;
        Ok(bytes)
    }

    fn len_to_usize(&self, len: u64, path: &str) -> Result<usize, FrontendError> {
        usize::try_from(len)
            .map_err(|_| self.malformed(path, "proofir-cbor-v1 length exceeds usize"))
    }

    fn malformed(&self, path: &str, detail: impl Into<String>) -> FrontendError {
        binary_frontend_error(FrontendErrorKind::MalformedTransport, path, detail)
    }
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

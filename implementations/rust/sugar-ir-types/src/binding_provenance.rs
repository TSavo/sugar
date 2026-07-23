use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BindingProvenanceError {
    Malformed(String),
    CidMismatch(&'static str),
}

impl std::fmt::Display for BindingProvenanceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Malformed(message) => write!(f, "malformed binding provenance: {message}"),
            Self::CidMismatch(field) => write!(f, "binding provenance CID mismatch: {field}"),
        }
    }
}

impl std::error::Error for BindingProvenanceError {}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceSpanV1 {
    pub start: u64,
    pub end: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceMementoV1 {
    pub file: String,
    pub span: SourceSpanV1,
    pub source_cid: String,
    pub cid: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum ProjectionPathPartV1 {
    Name(String),
    Index(i64),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum BindingCoordinateKindV1 {
    #[serde(rename = "binding-coordinate")]
    BindingCoordinate,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BindingCoordinateV1 {
    pub kind: BindingCoordinateKindV1,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "scopeOwnerCid")]
    pub scope_owner_cid: String,
    #[serde(rename = "bindingSite")]
    pub binding_site: SourceMementoV1,
    #[serde(rename = "projectionPath")]
    pub projection_path: Vec<ProjectionPathPartV1>,
    #[serde(rename = "bindingCoordinateCid")]
    pub binding_coordinate_cid: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ConstructedValueTestimonyKindV1 {
    #[serde(rename = "constructed-value-testimony")]
    ConstructedValueTestimony,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ConstructedValueTestimonyV1 {
    pub kind: ConstructedValueTestimonyKindV1,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "sourceFragmentCid")]
    pub source_fragment_cid: String,
    #[serde(rename = "semanticValueCid")]
    pub semantic_value_cid: String,
    #[serde(rename = "constructedValueTestimonyCid")]
    pub constructed_value_testimony_cid: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", deny_unknown_fields)]
pub enum BindingStateV1 {
    #[serde(rename = "bound")]
    Bound {
        testimony: ConstructedValueTestimonyV1,
    },
    #[serde(rename = "unbound")]
    Unbound {
        #[serde(rename = "causeFragmentCid")]
        cause_fragment_cid: String,
    },
    #[serde(rename = "guarded")]
    Guarded {
        #[serde(rename = "guardFormulaCid")]
        guard_formula_cid: String,
        #[serde(rename = "whenTrueStateCid")]
        when_true_state_cid: String,
        #[serde(rename = "whenFalseStateCid")]
        when_false_state_cid: String,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BindingEntryV1 {
    pub coordinate: BindingCoordinateV1,
    pub state: BindingStateV1,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SubstitutionTraceRecordKindV1 {
    #[serde(rename = "substitution-trace-record")]
    SubstitutionTraceRecord,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SubstitutionTraceRecordV1 {
    pub kind: SubstitutionTraceRecordKindV1,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "statementSource")]
    pub statement_source: SourceMementoV1,
    #[serde(rename = "preEntries")]
    pub pre_entries: Vec<BindingEntryV1>,
    #[serde(rename = "postEntries")]
    pub post_entries: Vec<BindingEntryV1>,
    #[serde(rename = "recordCid")]
    pub record_cid: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SubstitutionTraceKindV1 {
    #[serde(rename = "substitution-trace")]
    SubstitutionTrace,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SubstitutionTraceV1 {
    pub kind: SubstitutionTraceKindV1,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "scopeOwnerCid")]
    pub scope_owner_cid: String,
    pub records: Vec<SubstitutionTraceRecordV1>,
    #[serde(rename = "traceCid")]
    pub trace_cid: String,
}

fn canonical(value: serde_json::Value) -> sugar_canonicalizer::Value {
    match value {
        serde_json::Value::Null => sugar_canonicalizer::Value::Null,
        serde_json::Value::Bool(value) => sugar_canonicalizer::Value::Bool(value),
        serde_json::Value::Number(value) => sugar_canonicalizer::Value::Integer(
            value
                .as_i64()
                .map(i128::from)
                .or_else(|| value.as_u64().map(i128::from))
                .expect("binding provenance integers fit i64/u64"),
        ),
        serde_json::Value::String(value) => sugar_canonicalizer::Value::String(value),
        serde_json::Value::Array(values) => sugar_canonicalizer::Value::Array(
            values
                .into_iter()
                .map(canonical)
                .map(std::sync::Arc::new)
                .collect(),
        ),
        serde_json::Value::Object(values) => sugar_canonicalizer::Value::Object(
            values
                .into_iter()
                .map(|(key, value)| (key, std::sync::Arc::new(canonical(value))))
                .collect(),
        ),
    }
}

fn validate_cid<T: Serialize>(
    value: &T,
    field: &'static str,
    observed: &str,
) -> Result<(), BindingProvenanceError> {
    let mut json = serde_json::to_value(value)
        .map_err(|error| BindingProvenanceError::Malformed(error.to_string()))?;
    json.as_object_mut()
        .ok_or_else(|| BindingProvenanceError::Malformed("record is not an object".into()))?
        .remove(field)
        .ok_or_else(|| BindingProvenanceError::Malformed(format!("missing {field}")))?;
    let expected = sugar_canonicalizer::blake3_512_of(
        sugar_canonicalizer::encode_jcs(&canonical(json)).as_bytes(),
    );
    if expected != observed {
        return Err(BindingProvenanceError::CidMismatch(field));
    }
    Ok(())
}

fn require_cid(value: &str, field: &str) -> Result<(), BindingProvenanceError> {
    if value.starts_with("blake3-512:") {
        Ok(())
    } else {
        Err(BindingProvenanceError::Malformed(format!(
            "{field} is not a CID"
        )))
    }
}

impl SubstitutionTraceV1 {
    pub fn decode(bytes: &[u8]) -> Result<Self, BindingProvenanceError> {
        let value: Self = serde_json::from_slice(bytes)
            .map_err(|error| BindingProvenanceError::Malformed(error.to_string()))?;
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), BindingProvenanceError> {
        if self.schema_version != "1" {
            return Err(BindingProvenanceError::Malformed(
                "unsupported trace schema version".into(),
            ));
        }
        require_cid(&self.scope_owner_cid, "scopeOwnerCid")?;
        validate_cid(self, "traceCid", &self.trace_cid)?;
        for record in &self.records {
            if record.schema_version != "1" {
                return Err(BindingProvenanceError::Malformed(
                    "unsupported record schema version".into(),
                ));
            }
            validate_cid(record, "recordCid", &record.record_cid)?;
            validate_entries(&record.pre_entries)?;
            validate_entries(&record.post_entries)?;
        }
        Ok(())
    }
}

fn validate_entries(entries: &[BindingEntryV1]) -> Result<(), BindingProvenanceError> {
    let mut prior: Option<&str> = None;
    for entry in entries {
        let coordinate = &entry.coordinate;
        if coordinate.schema_version != "1" || coordinate.projection_path.is_empty() {
            return Err(BindingProvenanceError::Malformed(
                "unsupported or empty binding coordinate".into(),
            ));
        }
        require_cid(&coordinate.scope_owner_cid, "scopeOwnerCid")?;
        validate_cid(
            coordinate,
            "bindingCoordinateCid",
            &coordinate.binding_coordinate_cid,
        )?;
        if prior.is_some_and(|value| value >= coordinate.binding_coordinate_cid.as_str()) {
            return Err(BindingProvenanceError::Malformed(
                "entries are not unique and CID-sorted".into(),
            ));
        }
        prior = Some(&coordinate.binding_coordinate_cid);
        match &entry.state {
            BindingStateV1::Bound { testimony } => {
                validate_cid(
                    testimony,
                    "constructedValueTestimonyCid",
                    &testimony.constructed_value_testimony_cid,
                )?;
                require_cid(&testimony.source_fragment_cid, "sourceFragmentCid")?;
                require_cid(&testimony.semantic_value_cid, "semanticValueCid")?;
            }
            BindingStateV1::Unbound { cause_fragment_cid } => {
                require_cid(cause_fragment_cid, "causeFragmentCid")?;
            }
            BindingStateV1::Guarded {
                guard_formula_cid,
                when_true_state_cid,
                when_false_state_cid,
            } => {
                require_cid(guard_formula_cid, "guardFormulaCid")?;
                require_cid(when_true_state_cid, "whenTrueStateCid")?;
                require_cid(when_false_state_cid, "whenFalseStateCid")?;
            }
        }
    }
    Ok(())
}

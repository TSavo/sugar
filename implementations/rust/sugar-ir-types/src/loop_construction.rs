use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

use crate::binding_provenance::{validate_entries, BindingEntryV1};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LoopWireError {
    Malformed(String),
    CidMismatch(String),
    MissingReference(String),
    TargetMismatch(String),
}

impl std::fmt::Display for LoopWireError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Malformed(value) => write!(f, "malformed loop wire: {value}"),
            Self::CidMismatch(value) => write!(f, "loop wire CID mismatch: {value}"),
            Self::MissingReference(value) => write!(f, "missing loop wire reference: {value}"),
            Self::TargetMismatch(value) => write!(f, "loop target mismatch: {value}"),
        }
    }
}

impl std::error::Error for LoopWireError {}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceFragmentCoordinateV1 {
    #[serde(rename = "sourceCid")]
    pub source_cid: String,
    #[serde(rename = "startLine")]
    pub start_line: u64,
    #[serde(rename = "startCol")]
    pub start_col: u64,
    #[serde(rename = "endLine")]
    pub end_line: u64,
    #[serde(rename = "endCol")]
    pub end_col: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LoopTargetCoordinateV1 {
    pub kind: LoopTargetKind,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "loopKind")]
    pub loop_kind: LoopKindV1,
    #[serde(rename = "sourceFragment")]
    pub source_fragment: SourceFragmentCoordinateV1,
    #[serde(rename = "targetCid")]
    pub target_cid: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LoopTargetKind {
    #[serde(rename = "python-loop-target")]
    PythonLoopTarget,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LoopKindV1 {
    For,
    AsyncFor,
    While,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BindingStateV1 {
    pub kind: BindingStateKind,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    pub entries: Vec<BindingEntryV1>,
    #[serde(rename = "stateCid")]
    pub state_cid: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum BindingStateKind {
    #[serde(rename = "binding-state")]
    BindingState,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum CompletionKindV1 {
    BodyFallthrough,
    NormalExhaustion,
    BreakExit,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LatchOperationKindV1 {
    ForNext,
    WhileTest,
}

macro_rules! record {
    ($name:ident { $($field:ident : $ty:ty => $wire:literal),* $(,)? }) => {
        #[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
        #[serde(deny_unknown_fields)]
        pub struct $name {
            $(#[serde(rename = $wire)] pub $field: $ty,)*
        }
    };
}

record!(LoopCompletedFaceV1 {
    schema_version: String => "schemaVersion",
    target_cid: String => "targetCid",
    completion_kind: CompletionKindV1 => "completionKind",
    guard_formula_cid: String => "guardFormulaCid",
    state_cid: String => "stateCid",
    completed_face_cid: String => "completedFaceCid",
});

record!(LoopOutwardHaltedFaceV1 {
    schema_version: String => "schemaVersion",
    target_cid: String => "targetCid",
    effect_cid: String => "effectCid",
    guard_formula_cid: String => "guardFormulaCid",
    state_cid: String => "stateCid",
    outward_halted_face_cid: String => "outwardHaltedFaceCid",
});

record!(LoopBinderTransformV1 {
    schema_version: String => "schemaVersion",
    target_cid: String => "targetCid",
    input_state_cid: String => "inputStateCid",
    element_value_cid: String => "elementValueCid",
    output_state_cid: String => "outputStateCid",
    binder_pattern_construction_cid: String => "binderPatternConstructionCid",
    binder_transform_cid: String => "binderTransformCid",
});

record!(LoopBodyTransformV1 {
    schema_version: String => "schemaVersion",
    target_cid: String => "targetCid",
    input_state_cid: String => "inputStateCid",
    binder_transform_cid: Option<String> => "binderTransformCid",
    body_source_fragment_cid: String => "bodySourceFragmentCid",
    body_exit_template_cid: String => "bodyExitTemplateCid",
    body_transform_cid: String => "bodyTransformCid",
});

record!(LoopTestTransformV1 {
    schema_version: String => "schemaVersion",
    target_cid: String => "targetCid",
    input_state_cid: String => "inputStateCid",
    test_value_construction_cid: String => "testValueConstructionCid",
    true_guard_formula_cid: String => "trueGuardFormulaCid",
    false_guard_formula_cid: String => "falseGuardFormulaCid",
    halted_face_cids: Vec<String> => "haltedFaceCids",
    test_transform_cid: String => "testTransformCid",
});

record!(LoopIteratorTestimonyV1 {
    schema_version: String => "schemaVersion",
    target_cid: String => "targetCid",
    iterable_value_construction_cid: String => "iterableValueConstructionCid",
    iterator_construction_cid: String => "iteratorConstructionCid",
    next_operation_cid: String => "nextOperationCid",
    exhaustion_operation_cid: String => "exhaustionOperationCid",
    iterator_testimony_cid: String => "iteratorTestimonyCid",
});

record!(ForOperationV1 {
    schema_version: String => "schemaVersion",
    target_cid: String => "targetCid",
    native_loop_term_cid: String => "nativeLoopTermCid",
    binder_transform_cid: String => "binderTransformCid",
    iterator_testimony_cid: String => "iteratorTestimonyCid",
    operation_cid: String => "operationCid",
});

record!(WhileOperationV1 {
    schema_version: String => "schemaVersion",
    target_cid: String => "targetCid",
    native_loop_term_cid: String => "nativeLoopTermCid",
    test_transform_cid: String => "testTransformCid",
    operation_cid: String => "operationCid",
});

record!(LoopLatchObligationV1 {
    schema_version: String => "schemaVersion",
    target_cid: String => "targetCid",
    input_completed_face_cid: String => "inputCompletedFaceCid",
    input_state_cid: String => "inputStateCid",
    operation_kind: LatchOperationKindV1 => "operationKind",
    successor_transform_cid: String => "successorTransformCid",
    latch_obligation_cid: String => "latchObligationCid",
});

record!(LoopBreakExitObligationV1 {
    schema_version: String => "schemaVersion",
    target_cid: String => "targetCid",
    break_effect_cid: String => "breakEffectCid",
    input_halted_face_cid: String => "inputHaltedFaceCid",
    output_completed_face_cid: String => "outputCompletedFaceCid",
    break_exit_obligation_cid: String => "breakExitObligationCid",
});

record!(LoopContinueLatchObligationV1 {
    schema_version: String => "schemaVersion",
    target_cid: String => "targetCid",
    continue_effect_cid: String => "continueEffectCid",
    input_halted_face_cid: String => "inputHaltedFaceCid",
    input_state_cid: String => "inputStateCid",
    successor_transform_cid: String => "successorTransformCid",
    continue_latch_obligation_cid: String => "continueLatchObligationCid",
});

record!(LoopExhaustionExitObligationV1 {
    schema_version: String => "schemaVersion",
    target_cid: String => "targetCid",
    operation_testimony_cid: String => "operationTestimonyCid",
    input_state_cid: String => "inputStateCid",
    output_completed_face_cid: String => "outputCompletedFaceCid",
    exhaustion_exit_obligation_cid: String => "exhaustionExitObligationCid",
});

record!(LoopElseExhaustionObligationV1 {
    schema_version: String => "schemaVersion",
    target_cid: String => "targetCid",
    input_completed_face_cid: String => "inputCompletedFaceCid",
    else_body_transform_cid: String => "elseBodyTransformCid",
    output_completed_face_cid: String => "outputCompletedFaceCid",
    else_exhaustion_obligation_cid: String => "elseExhaustionObligationCid",
});

record!(LoopPostBindingV1 {
    schema_version: String => "schemaVersion",
    target_cid: String => "targetCid",
    binding_coordinate_cid: String => "bindingCoordinateCid",
    incoming_state_cid: String => "incomingStateCid",
    completed_face_cid: String => "completedFaceCid",
    projected_state_cid: String => "projectedStateCid",
    post_binding_obligation_cid: String => "postBindingObligationCid",
});

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum LoopOperationV1 {
    #[serde(rename = "for-operation")]
    For(ForOperationV1),
    #[serde(rename = "while-operation")]
    While(WhileOperationV1),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum LoopRecordV1 {
    #[serde(rename = "binding-state")]
    BindingState {
        #[serde(rename = "schemaVersion")]
        schema_version: String,
        entries: Vec<BindingEntryV1>,
        #[serde(rename = "stateCid")]
        state_cid: String,
    },
    #[serde(rename = "loop-completed-face")]
    CompletedFace(LoopCompletedFaceV1),
    #[serde(rename = "loop-outward-halted-face")]
    OutwardHaltedFace(LoopOutwardHaltedFaceV1),
    #[serde(rename = "loop-binder-transform")]
    BinderTransform(LoopBinderTransformV1),
    #[serde(rename = "loop-body-transform")]
    BodyTransform(LoopBodyTransformV1),
    #[serde(rename = "loop-test-transform")]
    TestTransform(LoopTestTransformV1),
    #[serde(rename = "loop-iterator-testimony")]
    IteratorTestimony(LoopIteratorTestimonyV1),
    #[serde(rename = "for-operation")]
    ForOperation(ForOperationV1),
    #[serde(rename = "while-operation")]
    WhileOperation(WhileOperationV1),
    #[serde(rename = "loop-latch-obligation")]
    Latch(LoopLatchObligationV1),
    #[serde(rename = "loop-continue-latch-obligation")]
    ContinueLatch(LoopContinueLatchObligationV1),
    #[serde(rename = "loop-break-exit-obligation")]
    BreakExit(LoopBreakExitObligationV1),
    #[serde(rename = "loop-exhaustion-exit-obligation")]
    ExhaustionExit(LoopExhaustionExitObligationV1),
    #[serde(rename = "loop-else-exhaustion-obligation")]
    ElseExhaustion(LoopElseExhaustionObligationV1),
    #[serde(rename = "loop-post-binding")]
    PostBinding(LoopPostBindingV1),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LoopConstructionV1 {
    pub kind: LoopConstructionKind,
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    pub target: LoopTargetCoordinateV1,
    #[serde(rename = "preStateCid")]
    pub pre_state_cid: String,
    pub operation: LoopOperationV1,
    #[serde(rename = "bodyTransformCid")]
    pub body_transform_cid: String,
    #[serde(rename = "bodyExitTemplateCid")]
    pub body_exit_template_cid: String,
    #[serde(rename = "latchObligationCids")]
    pub latch_obligation_cids: Vec<String>,
    #[serde(rename = "continueLatchObligationCids")]
    pub continue_latch_obligation_cids: Vec<String>,
    #[serde(rename = "breakExitObligationCids")]
    pub break_exit_obligation_cids: Vec<String>,
    #[serde(rename = "exhaustionExitObligationCid")]
    pub exhaustion_exit_obligation_cid: String,
    #[serde(rename = "elseBodyCid")]
    pub else_body_cid: Option<String>,
    #[serde(rename = "elseExhaustionObligationCid")]
    pub else_exhaustion_obligation_cid: Option<String>,
    #[serde(rename = "completedFaceCids")]
    pub completed_face_cids: Vec<String>,
    #[serde(rename = "outwardHaltedFaceCids")]
    pub outward_halted_face_cids: Vec<String>,
    #[serde(rename = "postBindingObligationCids")]
    pub post_binding_obligation_cids: Vec<String>,
    #[serde(rename = "loopConstructionCid")]
    pub loop_construction_cid: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LoopConstructionKind {
    #[serde(rename = "loop-construction")]
    LoopConstruction,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LoopConstructionGraphV1 {
    pub root: LoopConstructionV1,
    pub records: Vec<LoopRecordV1>,
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
                .expect("loop wire numbers fit i64/u64"),
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

fn cid_without<T: Serialize>(value: &T, cid_field: &str) -> Result<String, LoopWireError> {
    let mut json =
        serde_json::to_value(value).map_err(|error| LoopWireError::Malformed(error.to_string()))?;
    let object = json
        .as_object_mut()
        .ok_or_else(|| LoopWireError::Malformed("record is not an object".into()))?;
    object.remove(cid_field).ok_or_else(|| {
        LoopWireError::Malformed(format!("record lacks terminal CID field {cid_field}"))
    })?;
    let value = canonical(json);
    Ok(sugar_canonicalizer::blake3_512_of(
        sugar_canonicalizer::encode_jcs(&value).as_bytes(),
    ))
}

fn validate_cid<T: Serialize>(
    value: &T,
    cid_field: &str,
    observed: &str,
) -> Result<(), LoopWireError> {
    let expected = cid_without(value, cid_field)?;
    if expected != observed {
        return Err(LoopWireError::CidMismatch(cid_field.into()));
    }
    Ok(())
}

impl LoopConstructionGraphV1 {
    pub fn decode(bytes: &[u8]) -> Result<Self, LoopWireError> {
        let graph: Self = serde_json::from_slice(bytes)
            .map_err(|error| LoopWireError::Malformed(error.to_string()))?;
        graph.validate()?;
        Ok(graph)
    }

    pub fn validate(&self) -> Result<(), LoopWireError> {
        validate_cid(&self.root.target, "targetCid", &self.root.target.target_cid)?;
        validate_cid(
            &self.root,
            "loopConstructionCid",
            &self.root.loop_construction_cid,
        )?;
        if self.root.schema_version != "1" || self.root.target.schema_version != "1" {
            return Err(LoopWireError::Malformed(
                "unsupported schema version".into(),
            ));
        }
        if self.root.else_body_cid.is_some() != self.root.else_exhaustion_obligation_cid.is_some() {
            return Err(LoopWireError::Malformed(
                "else body and exhaustion obligation must appear together".into(),
            ));
        }

        let target = &self.root.target.target_cid;
        let mut states = BTreeSet::new();
        let mut records = BTreeMap::<String, &LoopRecordV1>::new();
        for record in &self.records {
            let (cid, field, target_cid) = match record {
                LoopRecordV1::BindingState { state_cid, .. } => {
                    validate_cid(record, "stateCid", state_cid)?;
                    if let LoopRecordV1::BindingState { entries, .. } = record {
                        validate_entries(entries)
                            .map_err(|error| LoopWireError::Malformed(error.to_string()))?;
                    }
                    states.insert(state_cid.clone());
                    continue;
                }
                LoopRecordV1::CompletedFace(value) => (
                    &value.completed_face_cid,
                    "completedFaceCid",
                    Some(&value.target_cid),
                ),
                LoopRecordV1::OutwardHaltedFace(value) => (
                    &value.outward_halted_face_cid,
                    "outwardHaltedFaceCid",
                    Some(&value.target_cid),
                ),
                LoopRecordV1::BinderTransform(value) => (
                    &value.binder_transform_cid,
                    "binderTransformCid",
                    Some(&value.target_cid),
                ),
                LoopRecordV1::BodyTransform(value) => (
                    &value.body_transform_cid,
                    "bodyTransformCid",
                    Some(&value.target_cid),
                ),
                LoopRecordV1::TestTransform(value) => (
                    &value.test_transform_cid,
                    "testTransformCid",
                    Some(&value.target_cid),
                ),
                LoopRecordV1::IteratorTestimony(value) => (
                    &value.iterator_testimony_cid,
                    "iteratorTestimonyCid",
                    Some(&value.target_cid),
                ),
                LoopRecordV1::ForOperation(value) => (
                    &value.operation_cid,
                    "operationCid",
                    Some(&value.target_cid),
                ),
                LoopRecordV1::WhileOperation(value) => (
                    &value.operation_cid,
                    "operationCid",
                    Some(&value.target_cid),
                ),
                LoopRecordV1::Latch(value) => (
                    &value.latch_obligation_cid,
                    "latchObligationCid",
                    Some(&value.target_cid),
                ),
                LoopRecordV1::ContinueLatch(value) => (
                    &value.continue_latch_obligation_cid,
                    "continueLatchObligationCid",
                    Some(&value.target_cid),
                ),
                LoopRecordV1::BreakExit(value) => (
                    &value.break_exit_obligation_cid,
                    "breakExitObligationCid",
                    Some(&value.target_cid),
                ),
                LoopRecordV1::ExhaustionExit(value) => (
                    &value.exhaustion_exit_obligation_cid,
                    "exhaustionExitObligationCid",
                    Some(&value.target_cid),
                ),
                LoopRecordV1::ElseExhaustion(value) => (
                    &value.else_exhaustion_obligation_cid,
                    "elseExhaustionObligationCid",
                    Some(&value.target_cid),
                ),
                LoopRecordV1::PostBinding(value) => (
                    &value.post_binding_obligation_cid,
                    "postBindingObligationCid",
                    Some(&value.target_cid),
                ),
            };
            validate_cid(record, field, cid)?;
            if target_cid != Some(target) {
                return Err(LoopWireError::TargetMismatch(cid.clone()));
            }
            if records.insert(cid.clone(), record).is_some() {
                return Err(LoopWireError::Malformed("duplicate record CID".into()));
            }
        }

        if !states.contains(&self.root.pre_state_cid) {
            return Err(LoopWireError::MissingReference(
                self.root.pre_state_cid.clone(),
            ));
        }
        for cid in self
            .root
            .completed_face_cids
            .iter()
            .chain(self.root.latch_obligation_cids.iter())
            .chain(self.root.continue_latch_obligation_cids.iter())
            .chain(self.root.break_exit_obligation_cids.iter())
            .chain(std::iter::once(&self.root.exhaustion_exit_obligation_cid))
            .chain(self.root.outward_halted_face_cids.iter())
            .chain(self.root.post_binding_obligation_cids.iter())
            .chain(std::iter::once(&self.root.body_transform_cid))
            .chain(self.root.else_exhaustion_obligation_cid.iter())
        {
            if !records.contains_key(cid) {
                return Err(LoopWireError::MissingReference(cid.clone()));
            }
        }
        Ok(())
    }
}

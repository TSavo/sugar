// SPDX-License-Identifier: Apache-2.0
//
// ObjectValue floor.
//
// Python reference: `floor/object_value.py` dispatches `attribute_with` and
// `call_method_with` through the receiver floor, returning a held field/method
// floor when present and a coverage-gap-shaped miss when absent. Rust has no
// dynamic FloorValue class hierarchy, so this floor is an explicit `Desugared`
// variant and the operations are closed traits over `Desugared`.

use crate::sugar::factory_gap_info::CoverageGapInfo;
use crate::{Desugared, Effect, Outcome};

#[derive(Clone)]
pub(crate) struct ObjectField {
    name: String,
    value: Desugared,
}

impl ObjectField {
    pub(crate) fn new(name: impl Into<String>, value: Desugared) -> Self {
        Self {
            name: name.into(),
            value,
        }
    }

    fn matches(&self, name: &str) -> bool {
        self.name == name
    }
}

#[derive(Clone)]
pub(crate) struct ObjectMethodValue {
    name: String,
    parameters: Vec<String>,
    result: Desugared,
}

impl ObjectMethodValue {
    pub(crate) fn new<I, S>(name: impl Into<String>, parameters: I, result: Desugared) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        Self {
            name: name.into(),
            parameters: parameters.into_iter().map(Into::into).collect(),
            result,
        }
    }

    fn matches_call(&self, operation: &MethodCallOperation) -> bool {
        self.name == operation.name && self.parameters.len() == operation.arguments.len() + 1
    }
}

#[derive(Clone)]
pub(crate) struct ObjectValue {
    class_name: String,
    fields: Vec<ObjectField>,
    methods: Vec<ObjectMethodValue>,
}

impl ObjectValue {
    pub(crate) fn new(
        class_name: impl Into<String>,
        fields: Vec<ObjectField>,
        methods: Vec<ObjectMethodValue>,
    ) -> Self {
        Self {
            class_name: class_name.into(),
            fields,
            methods,
        }
    }

    fn attribute(self, operation: AttributeLookupOperation) -> Outcome {
        if let Some(field) = self
            .fields
            .into_iter()
            .rev()
            .find(|field| field.matches(&operation.name))
        {
            return Outcome::Complete(field.value);
        }

        Outcome::Incomplete(member_gap_effect(
            &operation.owner,
            &operation.blame,
            format!("{}.{}", self.class_name, operation.name),
            "ObjectAttribute",
            "sugar::object_value::ObjectField",
            "constructor-bound field",
        ))
    }

    fn call_method(self, operation: MethodCallOperation) -> Outcome {
        if let Some(method) = self
            .methods
            .into_iter()
            .rev()
            .find(|method| method.matches_call(&operation))
        {
            return Outcome::Complete(method.result);
        }

        Outcome::Incomplete(member_gap_effect(
            &operation.owner,
            &operation.blame,
            format!("{}.{}", self.class_name, operation.name),
            "ObjectMethod",
            "sugar::object_value::ObjectMethodValue",
            "constructor-bound method",
        ))
    }
}

pub(crate) struct AttributeLookupOperation {
    name: String,
    owner: String,
    blame: String,
}

impl AttributeLookupOperation {
    pub(crate) fn new(
        name: impl Into<String>,
        owner: impl Into<String>,
        blame: impl Into<String>,
    ) -> Self {
        Self {
            name: name.into(),
            owner: owner.into(),
            blame: blame.into(),
        }
    }
}

pub(crate) struct MethodCallOperation {
    name: String,
    arguments: Vec<Desugared>,
    owner: String,
    blame: String,
}

impl MethodCallOperation {
    pub(crate) fn new(
        name: impl Into<String>,
        arguments: Vec<Desugared>,
        owner: impl Into<String>,
        blame: impl Into<String>,
    ) -> Self {
        Self {
            name: name.into(),
            arguments,
            owner: owner.into(),
            blame: blame.into(),
        }
    }
}

pub(crate) trait AttributeWith {
    fn attribute_with(self, operation: AttributeLookupOperation) -> Outcome;
}

impl AttributeWith for Desugared {
    fn attribute_with(self, operation: AttributeLookupOperation) -> Outcome {
        match self {
            Desugared::ObjectValue(object) => object.attribute(operation),
            floor => Outcome::Complete(floor),
        }
    }
}

pub(crate) trait CallMethodWith {
    fn call_method_with(self, operation: MethodCallOperation) -> Outcome;
}

impl CallMethodWith for Desugared {
    fn call_method_with(self, operation: MethodCallOperation) -> Outcome {
        match self {
            Desugared::ObjectValue(object) => object.call_method(operation),
            floor => Outcome::Complete(floor),
        }
    }
}

fn member_gap_effect(
    owner: &str,
    blame: &str,
    observed: String,
    requested: &str,
    fix: &str,
    kind: &str,
) -> Effect {
    let gap = CoverageGapInfo {
        owner: owner.to_string(),
        blame: blame.to_string(),
        observed: observed.clone(),
        requested: requested.to_string(),
        fix: fix.to_string(),
        gap_kind: "ObjectValue".to_string(),
        gap_locus: kind.to_string(),
    };
    Effect::CoverageGap {
        boundary: observed,
        reason: gap.message(),
    }
}

#[cfg(test)]
mod tests {
    use std::rc::Rc;

    use sugar_ir_symbolic::{make_var, Term};

    use super::{
        AttributeLookupOperation, AttributeWith, CallMethodWith, MethodCallOperation, ObjectField,
        ObjectMethodValue, ObjectValue,
    };
    use crate::{Desugared, Outcome};

    fn term_floor(name: &str) -> Desugared {
        Desugared::Term(make_var(name))
    }

    fn term_name(floor: Desugared) -> String {
        let Desugared::Term(term) = floor else {
            panic!("expected term floor");
        };
        let Term::Var { name } = term.as_ref() else {
            panic!("expected var term");
        };
        name.clone()
    }

    #[test]
    fn object_attribute_dispatches_to_field_floor_value() {
        let field = term_floor("field-value");
        let object = Desugared::ObjectValue(ObjectValue::new(
            "Widget",
            vec![ObjectField::new("value", field)],
            Vec::new(),
        ));

        let outcome = object.attribute_with(AttributeLookupOperation::new(
            "value",
            "object_attribute_dispatches_to_field_floor_value",
            "object_value.rs:field",
        ));

        let Outcome::Complete(floor) = outcome else {
            panic!("expected field floor");
        };
        assert_eq!(term_name(floor), "field-value");
    }

    #[test]
    fn object_method_call_dispatches_to_method_floor_value() {
        let method = ObjectMethodValue::new("answer", vec!["self"], term_floor("method-value"));
        let object = Desugared::ObjectValue(ObjectValue::new("Widget", Vec::new(), vec![method]));

        let outcome = object.call_method_with(MethodCallOperation::new(
            "answer",
            Vec::new(),
            "object_method_call_dispatches_to_method_floor_value",
            "object_value.rs:method",
        ));

        let Outcome::Complete(floor) = outcome else {
            panic!("expected method floor");
        };
        assert_eq!(term_name(floor), "method-value");
    }

    #[test]
    fn missing_attribute_or_method_refuses_without_symbolic_residue() {
        let object = Desugared::ObjectValue(ObjectValue::new("Widget", Vec::new(), Vec::new()));

        let missing_attr = object.attribute_with(AttributeLookupOperation::new(
            "missing",
            "missing_attribute_or_method_refuses_without_symbolic_residue",
            "object_value.rs:missing-attr",
        ));
        let Outcome::Incomplete(effect) = missing_attr else {
            panic!("missing attribute must be an honest refusal");
        };
        let reason = effect.reason();
        assert!(
            reason.contains("constructor-bound field"),
            "reason={reason}"
        );
        assert!(reason.contains("Widget.missing"), "reason={reason}");

        let missing_method =
            Desugared::ObjectValue(ObjectValue::new("Widget", Vec::new(), Vec::new()))
                .call_method_with(MethodCallOperation::new(
                    "missing",
                    Vec::new(),
                    "missing_attribute_or_method_refuses_without_symbolic_residue",
                    "object_value.rs:missing-method",
                ));
        let Outcome::Incomplete(effect) = missing_method else {
            panic!("missing method must be an honest refusal");
        };
        let reason = effect.reason();
        assert!(
            reason.contains("constructor-bound method"),
            "reason={reason}"
        );
        assert!(reason.contains("Widget.missing"), "reason={reason}");
    }

    #[test]
    fn non_object_attribute_receiver_stays_on_existing_path() {
        let receiver_term: Rc<Term> = make_var("symbolic-receiver");
        let receiver = Desugared::Term(receiver_term.clone());

        let outcome = receiver.attribute_with(AttributeLookupOperation::new(
            "field",
            "non_object_attribute_receiver_stays_on_existing_path",
            "object_value.rs:non-object",
        ));

        let Outcome::Complete(Desugared::Term(term)) = outcome else {
            panic!("non-object receiver should remain with the caller-owned path");
        };
        assert!(Rc::ptr_eq(&receiver_term, &term));
    }

    #[test]
    fn nested_object_attributes_route_through_two_dispatches() {
        let child = Desugared::ObjectValue(ObjectValue::new(
            "Child",
            vec![ObjectField::new("answer", term_floor("nested-value"))],
            Vec::new(),
        ));
        let parent = Desugared::ObjectValue(ObjectValue::new(
            "Parent",
            vec![ObjectField::new("child", child)],
            Vec::new(),
        ));

        let child = match parent.attribute_with(AttributeLookupOperation::new(
            "child",
            "nested_object_attributes_route_through_two_dispatches",
            "object_value.rs:parent",
        )) {
            Outcome::Complete(floor) => floor,
            Outcome::Incomplete(effect) => panic!("first dispatch refused: {}", effect.reason()),
        };
        let answer = match child.attribute_with(AttributeLookupOperation::new(
            "answer",
            "nested_object_attributes_route_through_two_dispatches",
            "object_value.rs:child",
        )) {
            Outcome::Complete(floor) => floor,
            Outcome::Incomplete(effect) => panic!("second dispatch refused: {}", effect.reason()),
        };

        assert_eq!(term_name(answer), "nested-value");
    }
}

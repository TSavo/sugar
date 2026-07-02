use serde_json::{json, Value as Json};
use sugar_verifier::attribute_safety;
use sugar_verifier::{
    AttributeSafetyObligation, CallSite, MementoCid, MementoPool, ObligationVerdict,
};

fn var(name: &str) -> Json {
    json!({"kind": "var", "name": name})
}

fn str_const(value: &str) -> Json {
    json!({
        "kind": "const",
        "value": value,
        "sort": {"kind": "primitive", "name": "String"}
    })
}

fn attr_term(receiver: Json, attr: &str) -> Json {
    json!({"kind": "ctor", "name": "python:attribute", "args": [receiver, str_const(attr)]})
}

fn attribute_present(receiver: Json, attr: &str) -> Json {
    json!({"kind": "atomic", "name": "attribute_present", "args": [receiver, str_const(attr)]})
}

fn class_shape(
    class_name: &str,
    attributes: Vec<Json>,
    permitted: Vec<Json>,
    open_attrs: Vec<Json>,
    open_reasons: Vec<&str>,
) -> Json {
    json!({
        "schemaVersion": "1",
        "kind": "python:class-shape",
        "name": class_name.rsplit('.').next().unwrap_or(class_name),
        "qualname": class_name.rsplit_once('.').map(|(_, q)| q).unwrap_or(class_name),
        "className": class_name,
        "status": if open_reasons.is_empty() { "closed" } else { "open" },
        "attributes": attributes,
        "permittedAttributes": permitted,
        "openAttributes": open_attrs,
        "methods": [],
        "bases": [],
        "openReasons": open_reasons,
        "assumptions": [],
        "locus": {"line": 1, "col": 0}
    })
}

fn class_shape_without_open_reasons(class_name: &str, attributes: Vec<Json>) -> Json {
    let mut shape = class_shape(class_name, attributes, vec![], vec![], vec![]);
    shape
        .as_object_mut()
        .expect("class shape is object")
        .remove("openReasons");
    shape
}

fn guaranteed_attr(name: &str) -> Json {
    json!({
        "name": name,
        "memberKind": "instance-attribute",
        "presence": "guaranteed",
        "presenceSource": "unconditional-init-assignment",
        "sources": [{"kind": "unconditional-init-assignment", "line": 2, "col": 8}]
    })
}

fn permitted_slot(name: &str) -> Json {
    json!({
        "name": name,
        "memberKind": "slot",
        "presence": "permitted-only",
        "guaranteesPresence": false,
        "note": "slot-membership alone does not discharge presence",
        "sources": [{"kind": "slot-declaration", "line": 2, "col": 4}]
    })
}

fn open_attr(name: &str, reason: &str) -> Json {
    json!({
        "name": name,
        "memberKind": "instance-attribute",
        "presence": "open",
        "reasons": [reason],
        "sources": [{"kind": reason, "line": 3, "col": 8}]
    })
}

fn pool_with_shape(shape: Json) -> MementoPool {
    let mut pool = MementoPool::default();
    pool.index_class_shape_for_tests(shape);
    pool
}

fn memento_cid(seed: &str) -> MementoCid {
    MementoCid::try_parse(sugar_canonicalizer::blake3_512_of(seed.as_bytes()))
        .expect("test CID must parse")
}

fn callsite(class_name: Option<&str>, attr: &str, guard_facts: Vec<Json>) -> CallSite {
    CallSite {
        bridge_ir_name: "concept:panic-freedom.leaf.runtime-failure-site".into(),
        property_name: "shape.Box.read".into(),
        property_cid: Some(memento_cid("attribute-safety-property")),
        arg_term: Some(attr_term(var("self"), attr)),
        guard_facts,
        file: Some("shape.py".into()),
        line: Some(6),
        callee: Some("concept:panic-freedom.leaf.runtime-failure-site".into()),
        panic_site: true,
        attribute_safety: Some(AttributeSafetyObligation {
            receiver_class: class_name.map(str::to_string),
            receiver_qualname: class_name.map(|name| {
                name.rsplit_once('.')
                    .map(|(_, qualname)| qualname)
                    .unwrap_or(name)
                    .to_string()
            }),
            receiver_name: Some("self".into()),
            attribute: attr.into(),
        }),
        ..CallSite::default()
    }
}

fn verdict(pool: &MementoPool, cs: &CallSite) -> ObligationVerdict {
    attribute_safety::try_discharge(cs, pool)
        .expect("attribute-safety callsite should be handled")
        .verdict
}

#[test]
fn absent_open_reasons_does_not_discharge() {
    let pool = pool_with_shape(class_shape_without_open_reasons(
        "shape.Box",
        vec![guaranteed_attr("value")],
    ));
    let cs = callsite(Some("shape.Box"), "value", vec![]);

    let result = attribute_safety::try_discharge(&cs, &pool).expect("handled");

    assert_ne!(
        result.verdict,
        ObligationVerdict::Discharged,
        "missing openReasons must not be treated as closed evidence"
    );
    assert!(
        result.reason.contains("not a guaranteed-present"),
        "missing openReasons should fall through as open evidence, got {}",
        result.reason
    );
}

#[test]
fn empty_open_reasons_discharges() {
    let pool = pool_with_shape(class_shape(
        "shape.Box",
        vec![guaranteed_attr("value")],
        vec![],
        vec![],
        vec![],
    ));
    let cs = callsite(Some("shape.Box"), "value", vec![]);

    assert_eq!(
        verdict(&pool, &cs),
        ObligationVerdict::Discharged,
        "explicit empty openReasons remains closed evidence"
    );
}

#[test]
fn guaranteed_attribute_discharges_and_removed_guarantee_flips_to_unproven() {
    let safe = pool_with_shape(class_shape(
        "shape.Box",
        vec![guaranteed_attr("value")],
        vec![],
        vec![],
        vec![],
    ));
    let cs = callsite(Some("shape.Box"), "value", vec![]);

    let result = attribute_safety::try_discharge(&cs, &safe).expect("handled");
    assert_eq!(result.verdict, ObligationVerdict::Discharged);
    assert_eq!(result.discharge_method.as_deref(), Some("panic-safe"));
    assert!(
        result.reason.contains("guaranteed-present"),
        "reason should name the classShapes guarantee, got {}",
        result.reason
    );

    let broken = pool_with_shape(class_shape("shape.Box", vec![], vec![], vec![], vec![]));
    assert_ne!(
        verdict(&broken, &cs),
        ObligationVerdict::Discharged,
        "removing the guaranteed-present classShapes fact must flip the access to unproven"
    );
}

#[test]
fn open_attribute_on_same_class_does_not_discharge_falsepass_guard() {
    let pool = pool_with_shape(class_shape(
        "shape.Box",
        vec![guaranteed_attr("value")],
        vec![],
        vec![open_attr("late", "late-instance-attribute")],
        vec!["late-instance-attribute"],
    ));

    assert_ne!(
        verdict(&pool, &callsite(Some("shape.Box"), "late", vec![])),
        ObligationVerdict::Discharged,
        "an openAttribute on a class that also has another guaranteed attr must not discharge"
    );
}

#[test]
fn slots_are_permitted_but_never_presence_guarantees() {
    let pool = pool_with_shape(class_shape(
        "shape.Slotted",
        vec![],
        vec![permitted_slot("declared_only")],
        vec![],
        vec![],
    ));

    assert_ne!(
        verdict(
            &pool,
            &callsite(Some("shape.Slotted"), "declared_only", vec![])
        ),
        ObligationVerdict::Discharged,
        "__slots__ permittedAttributes with guaranteesPresence=false must not prove presence"
    );
}

#[test]
fn conditional_attribute_requires_matching_cf_guarded_fact() {
    let pool = pool_with_shape(class_shape(
        "shape.Maybe",
        vec![],
        vec![],
        vec![open_attr("maybe", "conditional-init-attribute")],
        vec!["conditional-init-attribute"],
    ));
    let unguarded = callsite(Some("shape.Maybe"), "maybe", vec![]);
    assert_ne!(
        verdict(&pool, &unguarded),
        ObligationVerdict::Discharged,
        "a conditional-init attribute must not discharge unguarded"
    );

    let guarded = callsite(
        Some("shape.Maybe"),
        "maybe",
        vec![attribute_present(var("self"), "maybe")],
    );
    assert_eq!(
        verdict(&pool, &guarded),
        ObligationVerdict::Discharged,
        "a matching cf_guarded attribute_present fact should discharge the conditional access"
    );

    let wrong_attr_guard = callsite(
        Some("shape.Maybe"),
        "maybe",
        vec![attribute_present(var("self"), "other")],
    );
    assert_ne!(
        verdict(&pool, &wrong_attr_guard),
        ObligationVerdict::Discharged,
        "a guard for a different attribute must not discharge"
    );
}

#[test]
fn unknown_receiver_type_is_loudly_unproven_not_silently_dropped() {
    let pool = MementoPool::default();
    let result = attribute_safety::try_discharge(&callsite(None, "name", vec![]), &pool)
        .expect("unknown typed attribute access remains a handled obligation");

    assert_ne!(result.verdict, ObligationVerdict::Discharged);
    assert!(
        result.reason.contains("unknown receiver type"),
        "unknown receiver should be surfaced explicitly, got {}",
        result.reason
    );
}

// SPDX-License-Identifier: MIT OR Apache-2.0
//
// AliasFloor campaign census (#3482).
//
// Instruments only. These rows name discipline-owned alias side tables and
// caller-side bind/read/write/consume decisions that must migrate to
// AliasFloor dispatch. Future drains delete rows by moving semantics into the
// floor; new rows are regressions unless they extend this pinned ledger in the
// same PR.

use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::json;

const OWNER: &str = "#3482";
const SIDE_REPLACEMENT: &str = "absorbed by AliasFloor dispatch";
const DISPATCH_REPLACEMENT: &str =
    "emit the bind/read/write/consume event and match only on the AliasFloor result enum";

const TARGET_FILES: &[&str] = &[
    "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
    "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
    "implementations/rust/sugar-lift-rust-tests/src/sugar/bound_path.rs",
    "implementations/rust/sugar-lift-rust-tests/src/sugar/dormant_mut_ref.rs",
    "implementations/rust/sugar-lift-rust-tests/src/sugar/method.rs",
];

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
struct Pattern {
    needle: &'static str,
    family: &'static str,
    why: &'static str,
}

const SIDE_TABLE_PATTERNS: &[Pattern] = &[
    Pattern {
        needle: "alias_deref_mutated: BTreeSet<String>",
        family: "alias-refusal-set",
        why: "static alias-deref mutation danger is a side set instead of an alias value effect",
    },
    Pattern {
        needle: "mutable_let_bindings: BTreeSet<String>",
        family: "binding-mutability-side-set",
        why: "binding severance/share policy is tracked beside the value instead of answered by the bound floor",
    },
    Pattern {
        needle: "dormant_mut_ref: sugar::dormant_mut_ref::DormantMutRefState",
        family: "dormant-alias-side-state",
        why: "stdlib dormant alias replay rides a request-local side object instead of alias floor dispatch",
    },
    Pattern {
        needle: "temporal_rewrite: std::cell::RefCell<sugar::assign_op::TemporalRewriteState>",
        family: "temporal-alias-side-state",
        why: "mutable-place rewrite authority is a request-local ledger instead of floor-owned identity",
    },
    Pattern {
        needle: "aliases: BTreeMap<String, RewritePlace>",
        family: "mutable-alias-map",
        why: "alias identity is keyed by source names instead of a first-class AliasFloor value",
    },
    Pattern {
        needle: "cell_values: BTreeMap<String, CellState>",
        family: "interior-mutable-side-map",
        why: "interior mutability is represented by side state instead of an InteriorMutableFloor effect",
    },
    Pattern {
        needle: "unknown_mutations: BTreeMap<String, String>",
        family: "unknown-mutation-side-map",
        why: "opaque write effects are stored as string reasons beside aliases instead of typed floor effects",
    },
    Pattern {
        needle: "rewritten_bases: BTreeSet<String>",
        family: "alias-replay-set",
        why: "write-through replay is remembered by base-name set instead of construction through the alias floor",
    },
    Pattern {
        needle: "alias: Option<RewritePlace>",
        family: "alias-snapshot-slot",
        why: "rollback snapshots carry alias side-table entries instead of floor-owned identity",
    },
    Pattern {
        needle: "rewritten_base: bool",
        family: "alias-replay-snapshot-flag",
        why: "rollback snapshots carry replay flags for side sets instead of floor-owned state",
    },
    Pattern {
        needle: "aliases: BTreeMap<String, String>",
        family: "dormant-alias-map",
        why: "DormantMutRef tracks aliases by string map instead of replaying through AliasFloor",
    },
    Pattern {
        needle: "let mut aliases: BTreeMap<String, String>",
        family: "alias-collector-local-map",
        why: "alias-deref prepass builds a parallel string map rather than floor-dispatched alias formation",
    },
    Pattern {
        needle: "let mut dormant_bases: BTreeMap<String, String>",
        family: "dormant-alias-local-map",
        why: "DormantMutRef loop replay builds alias side maps instead of reducing floor values",
    },
    Pattern {
        needle: "let mut reborrow_bases: BTreeMap<String, String>",
        family: "dormant-reborrow-local-map",
        why: "DormantMutRef loop replay stores reborrow identity outside the floor",
    },
    Pattern {
        needle: "let mut rebound_aliases: BTreeMap<String, String>",
        family: "dormant-rebound-local-map",
        why: "DormantMutRef loop replay stores rebound alias identity outside the floor",
    },
];

const BIND_EVENT_PATTERNS: &[Pattern] = &[
    Pattern {
        needle: "fn record_let_binding(",
        family: "bind-event",
        why: "plain let binding is decided by TemporalScope instead of dispatched to the bound value floor",
    },
    Pattern {
        needle: "fn record_let_value_binding(",
        family: "bind-event",
        why: "value binding records BoundVar state directly instead of sending a bind event to the source floor",
    },
    Pattern {
        needle: "fn record_legacy_let_value_binding(",
        family: "bind-event",
        why: "legacy binding rewrites source before floor dispatch can decide sever/share/refuse",
    },
    Pattern {
        needle: "pub(crate) fn bound_var_for_definition(",
        family: "bind-event",
        why: "binding projection is computed by the scope instead of the bound floor result",
    },
    Pattern {
        needle: "pub(crate) fn record_bound_var(",
        family: "bind-event",
        why: "caller installs a BoundVar directly rather than replaying a bind result",
    },
    Pattern {
        needle: "fn record_bound_var_value(",
        family: "bind-event",
        why: "scope mutates binding maps after deciding binding policy itself",
    },
    Pattern {
        needle: "pub(crate) fn record_let_term_binding(",
        family: "bind-event",
        why: "term bindings bypass a bind-event result and install a second name directly",
    },
    Pattern {
        needle: "fn record_runtime_destructured_binding(",
        family: "bind-event",
        why: "runtime destructuring installs a side classification instead of a floor bind result",
    },
    Pattern {
        needle: "fn record_unresolved_destructured_binding(",
        family: "bind-event",
        why: "unresolved destructuring installs a side classification instead of a floor bind result",
    },
    Pattern {
        needle: "fn record_temporal_rewrite_local(",
        family: "bind-event",
        why: "TemporalScope forwards local binding into a rewrite side ledger",
    },
    Pattern {
        needle: "fn record_temporal_rewrite_value(",
        family: "bind-event",
        why: "literal snapshots are copied into a rewrite ledger instead of granted by a Copy floor",
    },
    Pattern {
        needle: "pub(crate) fn record_literal_value(",
        family: "bind-event",
        why: "literal value snapshots default to copy in the rewrite ledger instead of floor-granted severance",
    },
    Pattern {
        needle: "pub(crate) fn record_local(",
        family: "bind-event",
        why: "local binding shape is classified by the rewrite walker instead of dispatched to the bound floor",
    },
    Pattern {
        needle: "fn record_get_disjoint_mut_aliases(",
        family: "bind-event",
        why: "disjoint mutable aliases are constructed in the walker rather than as AliasFloor values",
    },
    Pattern {
        needle: "scope.record_let_value_binding(",
        family: "bind-event",
        why: "block walker decides a value binding before floor dispatch",
    },
    Pattern {
        needle: "scope.record_legacy_let_value_binding(",
        family: "bind-event",
        why: "block walker decides a legacy value binding before floor dispatch",
    },
    Pattern {
        needle: "scope.record_let_binding(",
        family: "bind-event",
        why: "block walker snapshots a simple binding instead of asking the floor",
    },
    Pattern {
        needle: "scope.record_runtime_destructured_binding(",
        family: "bind-event",
        why: "block walker classifies destructuring side state instead of asking the floor",
    },
    Pattern {
        needle: "scope.record_unresolved_destructured_binding(",
        family: "bind-event",
        why: "block walker classifies unresolved destructuring side state instead of asking the floor",
    },
    Pattern {
        needle: "self.aliases.insert(name, RewritePlace::Scalar(base))",
        family: "bind-event",
        why: "mutable reference alias is inserted by name instead of constructing an AliasFloor",
    },
    Pattern {
        needle: "self.aliases.insert(binding, place)",
        family: "bind-event",
        why: "disjoint mutable alias is inserted by name instead of constructing an AliasFloor",
    },
    Pattern {
        needle: "self.aliases.insert(alias, base)",
        family: "bind-event",
        why: "DormantMutRef alias is inserted by name instead of floor dispatch",
    },
    Pattern {
        needle: "self.aliases.insert(alias.clone(), base.clone())",
        family: "bind-event",
        why: "DormantMutRef rebound alias is inserted by name instead of floor dispatch",
    },
    Pattern {
        needle: "fn target_for_lhs(",
        family: "write-through",
        why: "assignment target semantics branch on aliases in the walker instead of dispatching write-through",
    },
    Pattern {
        needle: "fn target_for_deref(",
        family: "write-through",
        why: "deref write target is resolved by alias map lookup instead of AliasFloor write-through",
    },
    Pattern {
        needle: "fn target_for_index(",
        family: "write-through",
        why: "index write target is resolved by alias map lookup instead of AliasFloor write-through",
    },
    Pattern {
        needle: "match self.aliases.get(&name)?",
        family: "write-through",
        why: "write target branches on alias shape by string lookup",
    },
    Pattern {
        needle: "match self.aliases.get(&base_name)?",
        family: "write-through",
        why: "indexed write target branches on alias shape by string lookup",
    },
    Pattern {
        needle: "self.rewritten_bases.insert(name.clone())",
        family: "write-through",
        why: "write-through success is remembered by base-name set instead of the alias value",
    },
    Pattern {
        needle: "self.rewritten_bases.insert(base.to_string())",
        family: "write-through",
        why: "aggregate write-through success is remembered by base-name set instead of the alias value",
    },
    Pattern {
        needle: "fn invalidate_unknown_assignment(",
        family: "write-through",
        why: "unknown assignment constructs string refusal side effects instead of typed AliasFloor effects",
    },
    Pattern {
        needle: "pub(crate) fn expr_for(",
        family: "read-through",
        why: "read-through is resolved by alias map lookup instead of dispatching read to the floor",
    },
    Pattern {
        needle: "pub(crate) fn term_for(",
        family: "read-through",
        why: "term read-through asks expression side tables before the floor can answer",
    },
    Pattern {
        needle: "pub(crate) fn expr_for_index(",
        family: "read-through",
        why: "indexed read-through is resolved by rewritten-base side sets",
    },
    Pattern {
        needle: "pub(crate) fn mutable_alias_base(",
        family: "read-through",
        why: "alias identity is exposed as a string base query instead of a typed floor result",
    },
    Pattern {
        needle: "fn alias_deref_mutated_refusal(",
        family: "read-through",
        why: "refuse-on-read is a side-table predicate instead of a typed alias read effect",
    },
    Pattern {
        needle: "fn unknown_mutation_refusal(",
        family: "read-through",
        why: "unknown mutation read refusal is pulled from string side state instead of floor effect",
    },
    Pattern {
        needle: "fcx.scope().is_alias_deref_mutated(name).then",
        family: "read-through",
        why: "bound-path read consults alias danger side set before dispatch",
    },
    Pattern {
        needle: ".unknown_mutation_reason(name)",
        family: "read-through",
        why: "bound-path read consults string mutation reason side state before dispatch",
    },
    Pattern {
        needle: "if self.is_alias_deref_mutated(&name)",
        family: "read-through",
        why: "path naming refuses from side-table alias danger instead of floor read result",
    },
    Pattern {
        needle: "if self.is_alias_deref_mutated(name)",
        family: "read-through",
        why: "path naming refuses from side-table alias danger instead of floor read result",
    },
    Pattern {
        needle: "fn alias_capability_base(",
        family: "consume",
        why: "call consumption asks whether an argument is an alias by string lookup instead of dispatch",
    },
    Pattern {
        needle: "if let Some(base) = self.mutable_alias_base(&name)",
        family: "consume",
        why: "iterator consumption through an alias resolves base identity in the walker",
    },
    Pattern {
        needle: "if let Some(name) = self.alias_capability_base(arg)",
        family: "consume",
        why: "opaque mut-borrow consumption through an alias resolves base identity in the walker",
    },
    Pattern {
        needle: "if let Some(base) = scope.mutable_alias_base(&receiver)",
        family: "consume",
        why: "method receiver consumption asks alias identity before dispatching",
    },
    Pattern {
        needle: "ctx.scope.temporal_consuming_rewrite_alias(name)",
        family: "consume",
        why: "consuming iterator read requests a temporal alias name instead of routing consume through the floor",
    },
];

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
struct Row {
    file: String,
    enclosing_fn: String,
    family: String,
    needle: String,
    why: String,
    replacement: String,
    owner: String,
}

#[derive(Debug, Clone)]
struct ObservedRow {
    row: Row,
    line: usize,
}

const EXPECTED_ALIAS_SIDE_TABLE_SETS: &[(&str, &str, &str, &str)] = &[
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "new",
        "dormant-alias-side-state",
        "dormant_mut_ref: sugar::dormant_mut_ref::DormantMutRefState",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "struct TemporalPlan",
        "alias-refusal-set",
        "alias_deref_mutated: BTreeSet<String>",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "struct TemporalScope",
        "binding-mutability-side-set",
        "mutable_let_bindings: BTreeSet<String>",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "struct TemporalScope",
        "dormant-alias-side-state",
        "dormant_mut_ref: sugar::dormant_mut_ref::DormantMutRefState",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "struct TemporalScope",
        "temporal-alias-side-state",
        "temporal_rewrite: std::cell::RefCell<sugar::assign_op::TemporalRewriteState>",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "struct TemporalBindingSnapshot",
        "alias-replay-snapshot-flag",
        "rewritten_base: bool",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "struct TemporalRewriteState",
        "alias-replay-set",
        "rewritten_bases: BTreeSet<String>",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "struct TemporalRewriteState",
        "interior-mutable-side-map",
        "cell_values: BTreeMap<String, CellState>",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "struct TemporalRewriteState",
        "unknown-mutation-side-map",
        "unknown_mutations: BTreeMap<String, String>",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/dormant_mut_ref.rs",
        "advance_for_loop",
        "dormant-alias-local-map",
        "let mut dormant_bases: BTreeMap<String, String>",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/dormant_mut_ref.rs",
        "advance_for_loop",
        "dormant-alias-map",
        "aliases: BTreeMap<String, String>",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/dormant_mut_ref.rs",
        "advance_for_loop",
        "dormant-reborrow-local-map",
        "let mut reborrow_bases: BTreeMap<String, String>",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/dormant_mut_ref.rs",
        "advance_for_loop",
        "dormant-rebound-local-map",
        "let mut rebound_aliases: BTreeMap<String, String>",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/dormant_mut_ref.rs",
        "struct DormantMutRefState",
        "dormant-alias-map",
        "aliases: BTreeMap<String, String>",
    ),
];
const EXPECTED_BIND_EVENTS_NOT_FLOOR_DISPATCHED: &[(&str, &str, &str, &str)] = &[
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "alias_deref_mutation_needs_refusal",
        "read-through",
        ".unknown_mutation_reason(name)",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "bound_var_for_definition",
        "bind-event",
        "pub(crate) fn bound_var_for_definition(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "mutable_alias_base",
        "read-through",
        "pub(crate) fn mutable_alias_base(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "panic_freedom_direct_method_callsite_effect",
        "consume",
        "if let Some(base) = scope.mutable_alias_base(&receiver)",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "path_name",
        "read-through",
        "if self.is_alias_deref_mutated(&name)",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "path_name_str",
        "read-through",
        "if self.is_alias_deref_mutated(name)",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "record_bound_var",
        "bind-event",
        "pub(crate) fn record_bound_var(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "record_bound_var_value",
        "bind-event",
        "fn record_bound_var_value(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "record_destructured_let_bindings",
        "bind-event",
        "scope.record_let_binding(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "record_destructured_let_bindings",
        "bind-event",
        "scope.record_runtime_destructured_binding(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "record_destructured_let_bindings",
        "bind-event",
        "scope.record_unresolved_destructured_binding(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "record_legacy_let_value_binding",
        "bind-event",
        "fn record_legacy_let_value_binding(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "record_let_binding",
        "bind-event",
        "fn record_let_binding(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "record_let_term_binding",
        "bind-event",
        "pub(crate) fn record_let_term_binding(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "record_let_value_binding",
        "bind-event",
        "fn record_let_value_binding(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "record_runtime_destructured_binding",
        "bind-event",
        "fn record_runtime_destructured_binding(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "record_simple_value_binding",
        "bind-event",
        "scope.record_let_value_binding(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "record_simple_value_binding_legacy_projection",
        "bind-event",
        "scope.record_legacy_let_value_binding(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "record_temporal_rewrite_value",
        "bind-event",
        "fn record_temporal_rewrite_value(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "record_unresolved_destructured_binding",
        "bind-event",
        "fn record_unresolved_destructured_binding(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/lib.rs",
        "unknown_mutation_reason",
        "read-through",
        ".unknown_mutation_reason(name)",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "alias_capability_base",
        "consume",
        "fn alias_capability_base(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "apply_consumption_expr",
        "consume",
        "if let Some(base) = self.mutable_alias_base(&name)",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "apply_consumption_expr",
        "consume",
        "if let Some(name) = self.alias_capability_base(arg)",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "expr_for",
        "read-through",
        "pub(crate) fn expr_for(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "expr_for_index",
        "read-through",
        "pub(crate) fn expr_for_index(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "invalidate_unknown_assignment",
        "write-through",
        "fn invalidate_unknown_assignment(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "mutable_alias_base",
        "read-through",
        "pub(crate) fn mutable_alias_base(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "record_get_disjoint_mut_aliases",
        "bind-event",
        "fn record_get_disjoint_mut_aliases(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "record_literal_value",
        "bind-event",
        "pub(crate) fn record_literal_value(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "record_local",
        "bind-event",
        "pub(crate) fn record_local(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "set_aggregate_element",
        "write-through",
        "self.rewritten_bases.insert(base.to_string())",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "set_target",
        "write-through",
        "self.rewritten_bases.insert(name.clone())",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "target_for_deref",
        "write-through",
        "fn target_for_deref(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "target_for_index",
        "write-through",
        "fn target_for_index(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "target_for_lhs",
        "write-through",
        "fn target_for_lhs(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/assign_op.rs",
        "term_for",
        "read-through",
        "pub(crate) fn term_for(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/bound_path.rs",
        "alias_deref_mutated_refusal",
        "read-through",
        "fcx.scope().is_alias_deref_mutated(name).then",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/bound_path.rs",
        "alias_deref_mutated_refusal",
        "read-through",
        "fn alias_deref_mutated_refusal(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/bound_path.rs",
        "unknown_mutation_refusal",
        "read-through",
        ".unknown_mutation_reason(name)",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/bound_path.rs",
        "unknown_mutation_refusal",
        "read-through",
        "fn unknown_mutation_refusal(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/dormant_mut_ref.rs",
        "advance_for_loop",
        "bind-event",
        "self.aliases.insert(alias.clone(), base.clone())",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/dormant_mut_ref.rs",
        "advance_stmt",
        "bind-event",
        "self.aliases.insert(alias, base)",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/dormant_mut_ref.rs",
        "term_for",
        "read-through",
        "pub(crate) fn term_for(",
    ),
    (
        "implementations/rust/sugar-lift-rust-tests/src/sugar/method.rs",
        "desugar",
        "consume",
        "ctx.scope.temporal_consuming_rewrite_alias(name)",
    ),
];

#[test]
fn alias_side_table_sets_match_pinned_frontier() {
    let observed = collect_alias_side_table_sets(&project_sources()).expect("collect side tables");
    assert_rows(
        "R(alias-side-table-sets)",
        &observed,
        EXPECTED_ALIAS_SIDE_TABLE_SETS,
    );
}

#[test]
fn bind_events_not_floor_dispatched_match_pinned_frontier() {
    let observed = collect_bind_events_not_floor_dispatched(&project_sources())
        .expect("collect bind dispatch sites");
    assert_rows(
        "R(bind-events-not-floor-dispatched)",
        &observed,
        EXPECTED_BIND_EVENTS_NOT_FLOOR_DISPATCHED,
    );
}

#[test]
fn alias_side_table_collector_detects_planted_source() {
    let sources = vec![Source {
        rel: "planted/alias_side_table.rs".to_string(),
        text: r#"
            struct TemporalRewriteState {
                aliases: BTreeMap<String, RewritePlace>,
                rewritten_bases: BTreeSet<String>,
            }
        "#
        .to_string(),
    }];
    let rows = collect_alias_side_table_sets(&sources).expect("collect planted side tables");
    let needles = row_needles(&rows);
    assert!(needles.contains("aliases: BTreeMap<String, RewritePlace>"));
    assert!(needles.contains("rewritten_bases: BTreeSet<String>"));
}

#[test]
fn bind_event_collector_detects_planted_source() {
    let sources = vec![Source {
        rel: "planted/bind_event.rs".to_string(),
        text: r#"
            impl TemporalRewriteState {
                pub(crate) fn record_literal_value(&mut self, name: &str, value: Expr) {}
                fn target_for_deref(&self, expr: &Expr) -> Option<Target> {
                    match self.aliases.get(&name)? {
                        RewritePlace::Scalar(base) => todo!(),
                    }
                }
                fn consume(&mut self, name: String) {
                    if let Some(base) = self.mutable_alias_base(&name) {}
                }
            }
        "#
        .to_string(),
    }];
    let rows =
        collect_bind_events_not_floor_dispatched(&sources).expect("collect planted bind events");
    let needles = row_needles(&rows);
    assert!(needles.contains("pub(crate) fn record_literal_value("));
    assert!(needles.contains("fn target_for_deref("));
    assert!(needles.contains("match self.aliases.get(&name)?"));
    assert!(needles.contains("if let Some(base) = self.mutable_alias_base(&name)"));
}

fn collect_alias_side_table_sets(sources: &[Source]) -> Result<Vec<ObservedRow>, String> {
    collect_matching_rows(sources, SIDE_TABLE_PATTERNS, SIDE_REPLACEMENT)
}

fn collect_bind_events_not_floor_dispatched(
    sources: &[Source],
) -> Result<Vec<ObservedRow>, String> {
    collect_matching_rows(sources, BIND_EVENT_PATTERNS, DISPATCH_REPLACEMENT)
}

fn collect_matching_rows(
    sources: &[Source],
    patterns: &[Pattern],
    replacement: &str,
) -> Result<Vec<ObservedRow>, String> {
    let mut rows = Vec::new();
    for source in sources {
        let mut enclosing_fn = "<module>".to_string();
        let mut in_cfg_test = false;
        for (idx, line) in source.text.lines().enumerate() {
            let line_no = idx + 1;
            let trimmed = line.trim_start();
            if trimmed.starts_with("#[cfg(test)]") {
                in_cfg_test = true;
                continue;
            }
            if in_cfg_test {
                continue;
            }
            if trimmed.starts_with("//") {
                continue;
            }
            if let Some(name) = enclosing_name(trimmed) {
                enclosing_fn = name;
            }
            for pattern in patterns {
                if line.contains(pattern.needle) {
                    rows.push(ObservedRow {
                        row: Row {
                            file: source.rel.clone(),
                            enclosing_fn: enclosing_fn.clone(),
                            family: pattern.family.to_string(),
                            needle: pattern.needle.to_string(),
                            why: pattern.why.to_string(),
                            replacement: replacement.to_string(),
                            owner: OWNER.to_string(),
                        },
                        line: line_no,
                    });
                }
            }
        }
    }
    rows.sort_by_key(|observed| (observed.row.clone(), observed.line));
    Ok(rows)
}

fn assert_rows(axis: &str, observed: &[ObservedRow], expected: &[(&str, &str, &str, &str)]) {
    let observed_rows: BTreeSet<Row> = observed
        .iter()
        .map(|observed| observed.row.clone())
        .collect();
    let expected_rows: BTreeSet<Row> = expected
        .iter()
        .map(|(file, enclosing_fn, family, needle)| Row {
            file: (*file).to_string(),
            enclosing_fn: (*enclosing_fn).to_string(),
            family: (*family).to_string(),
            needle: (*needle).to_string(),
            why: why_for(family, needle).to_string(),
            replacement: if axis == "R(alias-side-table-sets)" {
                SIDE_REPLACEMENT
            } else {
                DISPATCH_REPLACEMENT
            }
            .to_string(),
            owner: OWNER.to_string(),
        })
        .collect();

    let unexpected: Vec<_> = observed_rows.difference(&expected_rows).cloned().collect();
    let missing: Vec<_> = expected_rows.difference(&observed_rows).cloned().collect();
    if unexpected.is_empty() && missing.is_empty() {
        println!("{axis}: total={}", observed_rows.len());
        return;
    }

    let observed_with_lines: Vec<_> = observed
        .iter()
        .map(|entry| {
            json!({
                "file": entry.row.file,
                "line": entry.line,
                "enclosing_fn": entry.row.enclosing_fn,
                "family": entry.row.family,
                "needle": entry.row.needle,
                "why": entry.row.why,
                "owner": entry.row.owner,
                "replacement": entry.row.replacement,
            })
        })
        .collect();

    panic!(
        "{}\n",
        serde_json::to_string_pretty(&json!({
            "axis": axis,
            "observed_total": observed_rows.len(),
            "expected_total": expected_rows.len(),
            "unexpected": rows_json(&unexpected),
            "missing": rows_json(&missing),
            "observed": observed_with_lines,
        }))
        .expect("render alias floor census diff")
    );
}

fn rows_json(rows: &[Row]) -> Vec<serde_json::Value> {
    rows.iter()
        .map(|row| {
            json!({
                "file": row.file,
                "enclosing_fn": row.enclosing_fn,
                "family": row.family,
                "needle": row.needle,
                "why": row.why,
                "owner": row.owner,
                "replacement": row.replacement,
            })
        })
        .collect()
}

fn why_for(family: &str, needle: &str) -> &'static str {
    SIDE_TABLE_PATTERNS
        .iter()
        .chain(BIND_EVENT_PATTERNS.iter())
        .find(|pattern| pattern.family == family && pattern.needle == needle)
        .map(|pattern| pattern.why)
        .unwrap_or("row must be assigned a replacement rationale")
}

fn row_needles(rows: &[ObservedRow]) -> BTreeSet<&str> {
    rows.iter().map(|row| row.row.needle.as_str()).collect()
}

fn enclosing_name(trimmed: &str) -> Option<String> {
    if let Some(name) = item_name_after(trimmed, "struct ") {
        return Some(format!("struct {name}"));
    }
    if let Some(name) = item_name_after(trimmed, "enum ") {
        return Some(format!("enum {name}"));
    }
    if let Some(name) = item_name_after(trimmed, "impl ") {
        return Some(format!("impl {name}"));
    }
    fn_name(trimmed)
}

fn item_name_after(trimmed: &str, marker: &str) -> Option<String> {
    let pos = trimmed.find(marker)?;
    let after = &trimmed[pos + marker.len()..];
    let name: String = after
        .chars()
        .skip_while(|ch| ch.is_whitespace())
        .take_while(|ch| ch.is_ascii_alphanumeric() || *ch == '_')
        .collect();
    (!name.is_empty()).then_some(name)
}

fn fn_name(trimmed: &str) -> Option<String> {
    let fn_pos = trimmed.find("fn ")?;
    let after = &trimmed[fn_pos + 3..];
    let name: String = after
        .chars()
        .take_while(|ch| ch.is_ascii_alphanumeric() || *ch == '_')
        .collect();
    (!name.is_empty()).then_some(name)
}

#[derive(Debug, Clone)]
struct Source {
    rel: String,
    text: String,
}

fn project_sources() -> Vec<Source> {
    TARGET_FILES
        .iter()
        .map(|rel| {
            let path = repo_root().join(rel);
            let text = fs::read_to_string(&path)
                .unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
            Source {
                rel: (*rel).to_string(),
                text,
            }
        })
        .collect()
}

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("manifest has repo root ancestor")
        .to_path_buf()
}

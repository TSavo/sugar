// SPDX-License-Identifier: Apache-2.0

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::PathBuf;

use quote::ToTokens;
use serde_json::{json, Value};
use syn::visit::Visit;
use walkdir::WalkDir;

const LADDER_THRESHOLD: usize = 2;

const FLOOR_VARIANTS: &[&str] = &[
    "Seq",
    "TermSeq",
    "Constraints",
    "Term",
    "LiteralString",
    "LiteralCStr",
    "FormatValue",
    "TupleComponents",
    "ObjectValue",
    "PredicateValue",
    "StmtSupport",
    "StmtBound",
    "StmtReturn",
    "StmtGuarded",
    "StmtRaise",
    "StmtGuardedRaise",
    "StmtBlock",
];

const ALGEBRA_MODULES: &[(&str, &str)] = &[
    (
        "src/lib.rs",
        "Desugared definition plus owned projection helper methods",
    ),
    (
        "src/sugar/term_dispatch.rs",
        "closed visitors and FloorDispatch open-edge seam",
    ),
    (
        "src/sugar/control_flow_guard_operation.rs",
        "owned ControlFlowGuardOperation double-dispatch",
    ),
    (
        "src/sugar/route_raises_operation.rs",
        "owned RouteRaisesOperation double-dispatch",
    ),
    (
        "src/sugar/object_value.rs",
        "owned ObjectValue attribute/method double-dispatch",
    ),
];

#[derive(Debug, Clone, PartialEq, Eq)]
struct ExpectedProjectionLadder {
    file: &'static str,
    line: usize,
    enclosing_fn: &'static str,
    max_floor_arms: usize,
    patterns: &'static [&'static str],
    owner: &'static str,
    replacement: &'static str,
}

const EXPECTED_PROJECTION_LADDERS: &[ExpectedProjectionLadder] = &[
    ExpectedProjectionLadder {
        file: "src/sugar/block_sugar.rs",
        line: 166,
        enclosing_fn: "compose_statement_result",
        max_floor_arms: 7,
        patterns: &[
            "StmtSupport",
            "StmtBound",
            "StmtReturn",
            "StmtGuarded",
            "StmtRaise",
            "StmtGuardedRaise",
            "StmtBlock",
        ],
        owner: "BlockSugar statement composition",
        replacement: "route statement floors through a closed statement-floor visitor",
    },
    ExpectedProjectionLadder {
        file: "src/sugar/block_sugar.rs",
        line: 241,
        enclosing_fn: "statement_floor_name",
        max_floor_arms: 16,
        patterns: &[
            "Seq",
            "TermSeq",
            "Constraints",
            "Term",
            "LiteralString",
            "LiteralCStr",
            "FormatValue",
            "TupleComponents",
            "PredicateValue",
            "StmtSupport",
            "StmtBound",
            "StmtReturn",
            "StmtGuarded",
            "StmtRaise",
            "StmtGuardedRaise",
            "StmtBlock",
        ],
        owner: "BlockSugar diagnostic naming",
        replacement: "use an owned floor-name projection/visitor shared with term_dispatch",
    },
    ExpectedProjectionLadder {
        file: "src/sugar/block_sugar.rs",
        line: 269,
        enclosing_fn: "guard_raise",
        max_floor_arms: 2,
        patterns: &["StmtRaise", "StmtGuardedRaise"],
        owner: "BlockSugar raise guard composition",
        replacement: "route raise floors through RouteRaisesOperation/statement visitor",
    },
    ExpectedProjectionLadder {
        file: "src/sugar/chain.rs",
        line: 194,
        enclosing_fn: "sequence_from_body",
        max_floor_arms: 2,
        patterns: &["Seq", "TermSeq"],
        owner: "ChainSugar sequence projection",
        replacement: "introduce a SequenceFloor visitor instead of matching Seq/TermSeq/Term",
    },
    ExpectedProjectionLadder {
        file: "src/sugar/collect.rs",
        line: 263,
        enclosing_fn: "terms_from_body",
        max_floor_arms: 2,
        patterns: &["Seq", "TermSeq"],
        owner: "CollectSugar sequence projection",
        replacement: "introduce a SequenceFloor visitor instead of matching Seq/TermSeq/Term",
    },
    ExpectedProjectionLadder {
        file: "src/sugar/factory.rs",
        line: 821,
        enclosing_fn: "disposition_outcome",
        max_floor_arms: 17,
        patterns: &[
            "Constraints",
            "Term",
            "LiteralString",
            "LiteralCStr",
            "FormatValue",
            "TupleComponents",
            "PredicateValue",
            "TermSeq",
            "Seq",
            "Seq",
            "StmtSupport",
            "StmtBound",
            "StmtReturn",
            "StmtGuarded",
            "StmtRaise",
            "StmtGuardedRaise",
            "StmtBlock",
        ],
        owner: "factory disposition reporting",
        replacement: "move disposition classification behind an owned RoleDisposition visitor",
    },
    ExpectedProjectionLadder {
        file: "src/sugar/fold.rs",
        line: 161,
        enclosing_fn: "desugar",
        max_floor_arms: 2,
        patterns: &["Seq", "TermSeq"],
        owner: "FoldSugar receiver sequence projection",
        replacement: "introduce a SequenceFloor visitor instead of matching Seq/TermSeq/Term",
    },
    ExpectedProjectionLadder {
        file: "src/sugar/for_replay.rs",
        line: 1287,
        enclosing_fn: "emit_constraint_expr",
        max_floor_arms: 2,
        patterns: &["Constraints", "Constraints"],
        owner: "ForReplay constraint emission projection",
        replacement: "introduce a ConstraintFloor visitor/fact-emission operation",
    },
    ExpectedProjectionLadder {
        file: "src/sugar/for_replay.rs",
        line: 1818,
        enclosing_fn: "finite_domain_body_exprs",
        max_floor_arms: 2,
        patterns: &["Seq", "TermSeq"],
        owner: "ForReplay finite-domain body projection",
        replacement: "introduce a SequenceFloor visitor for finite-domain projection",
    },
    ExpectedProjectionLadder {
        file: "src/sugar/for_replay.rs",
        line: 1872,
        enclosing_fn: "finite_domain_exprs",
        max_floor_arms: 2,
        patterns: &["Seq", "TermSeq"],
        owner: "ForReplay nested finite-domain projection",
        replacement: "introduce a SequenceFloor visitor for finite-domain projection",
    },
    ExpectedProjectionLadder {
        file: "src/sugar/forall.rs",
        line: 536,
        enclosing_fn: "sequence_domain_terms",
        max_floor_arms: 2,
        patterns: &["Seq", "TermSeq"],
        owner: "ForallSugar domain term projection",
        replacement: "introduce a SequenceFloor visitor for quantified-domain projection",
    },
    ExpectedProjectionLadder {
        file: "src/sugar/function_map.rs",
        line: 245,
        enclosing_fn: "reduce_function_map",
        max_floor_arms: 2,
        patterns: &["Seq", "TermSeq"],
        owner: "FunctionMapSugar receiver sequence projection",
        replacement: "introduce a SequenceFloor visitor instead of matching Seq/TermSeq/Term",
    },
    ExpectedProjectionLadder {
        file: "src/sugar/identity.rs",
        line: 19,
        enclosing_fn: "desugar",
        max_floor_arms: 2,
        patterns: &["Seq", "TermSeq"],
        owner: "IdentitySugar adaptor projection",
        replacement: "introduce a SequenceFloor visitor instead of matching Seq/TermSeq/Term",
    },
    ExpectedProjectionLadder {
        file: "src/sugar/map.rs",
        line: 351,
        enclosing_fn: "reduce_map_body",
        max_floor_arms: 2,
        patterns: &["Seq", "TermSeq"],
        owner: "MapSugar receiver sequence projection",
        replacement: "introduce a SequenceFloor visitor instead of matching Seq/TermSeq/Term",
    },
];

#[derive(Debug, Clone, PartialEq, Eq)]
struct ProjectionLadder {
    file: String,
    line: usize,
    enclosing_fn: String,
    floor_arms: usize,
    patterns: Vec<String>,
}

impl ProjectionLadder {
    fn key(&self) -> String {
        format!(
            "{}:{}:{}",
            self.file,
            self.enclosing_fn,
            self.patterns.join("|")
        )
    }

    fn to_json(&self) -> Value {
        json!({
            "file": self.file,
            "line": self.line,
            "enclosingFn": self.enclosing_fn,
            "floorArms": self.floor_arms,
            "patterns": self.patterns,
        })
    }
}

impl ExpectedProjectionLadder {
    fn key(&self) -> String {
        format!(
            "{}:{}:{}",
            self.file,
            self.enclosing_fn,
            self.patterns.join("|")
        )
    }

    fn to_json(&self) -> Value {
        json!({
            "file": self.file,
            "line": self.line,
            "enclosingFn": self.enclosing_fn,
            "maxFloorArms": self.max_floor_arms,
            "patterns": self.patterns,
            "owner": self.owner,
            "replacement": self.replacement,
        })
    }
}

fn crate_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn is_algebra_module(rel: &str) -> bool {
    ALGEBRA_MODULES
        .iter()
        .any(|(allowed, _reason)| *allowed == rel)
}

fn has_cfg_test(attrs: &[syn::Attribute]) -> bool {
    attrs.iter().any(|attr| {
        let rendered = attr.meta.to_token_stream().to_string();
        rendered.split_whitespace().collect::<String>() == "cfg(test)"
    })
}

fn collect_repo_projection_ladders() -> Vec<ProjectionLadder> {
    let root = crate_root();
    let src_root = root.join("src");
    let mut ladders = Vec::new();
    for entry in WalkDir::new(&src_root).into_iter().filter_map(Result::ok) {
        let path = entry.path();
        if !path.is_file() || path.extension().and_then(|ext| ext.to_str()) != Some("rs") {
            continue;
        }
        let rel = path
            .strip_prefix(&root)
            .expect("source path under crate root")
            .to_string_lossy()
            .replace('\\', "/");
        if is_algebra_module(&rel) {
            continue;
        }
        let source = fs::read_to_string(path)
            .unwrap_or_else(|err| panic!("failed to read {}: {err}", path.display()));
        ladders.extend(collect_projection_ladders_from_source(&rel, &source));
    }
    ladders.sort_by(|a, b| a.key().cmp(&b.key()));
    ladders
}

fn collect_projection_ladders_from_source(file: &str, source: &str) -> Vec<ProjectionLadder> {
    let syntax = syn::parse_file(source)
        .unwrap_or_else(|err| panic!("failed to parse {file} for floor-projection gate: {err}"));
    let mut visitor = LadderVisitor {
        file,
        fn_stack: Vec::new(),
        ladders: Vec::new(),
    };
    visitor.visit_file(&syntax);
    visitor.ladders
}

struct LadderVisitor<'a> {
    file: &'a str,
    fn_stack: Vec<String>,
    ladders: Vec<ProjectionLadder>,
}

impl LadderVisitor<'_> {
    fn current_fn(&self) -> String {
        self.fn_stack
            .last()
            .cloned()
            .unwrap_or_else(|| "<module>".to_string())
    }
}

impl<'ast> Visit<'ast> for LadderVisitor<'_> {
    fn visit_item_mod(&mut self, node: &'ast syn::ItemMod) {
        if has_cfg_test(&node.attrs) {
            return;
        }
        syn::visit::visit_item_mod(self, node);
    }

    fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
        if has_cfg_test(&node.attrs) {
            return;
        }
        self.fn_stack.push(node.sig.ident.to_string());
        syn::visit::visit_item_fn(self, node);
        self.fn_stack.pop();
    }

    fn visit_impl_item_fn(&mut self, node: &'ast syn::ImplItemFn) {
        if has_cfg_test(&node.attrs) {
            return;
        }
        self.fn_stack.push(node.sig.ident.to_string());
        syn::visit::visit_impl_item_fn(self, node);
        self.fn_stack.pop();
    }

    fn visit_expr_match(&mut self, node: &'ast syn::ExprMatch) {
        let patterns = node
            .arms
            .iter()
            .flat_map(|arm| desugared_patterns(&arm.pat))
            .collect::<Vec<_>>();
        if patterns.len() >= LADDER_THRESHOLD {
            self.ladders.push(ProjectionLadder {
                file: self.file.to_string(),
                line: node.match_token.span.start().line,
                enclosing_fn: self.current_fn(),
                floor_arms: patterns.len(),
                patterns,
            });
        }
        syn::visit::visit_expr_match(self, node);
    }
}

fn desugared_patterns(pat: &syn::Pat) -> Vec<String> {
    let compact = pat.to_token_stream().to_string().replace(' ', "");
    FLOOR_VARIANTS
        .iter()
        .filter(|variant| pattern_mentions_variant(&compact, variant))
        .map(|variant| (*variant).to_string())
        .collect()
}

fn pattern_mentions_variant(compact: &str, variant: &str) -> bool {
    if contains_qualified_variant(compact, "Desugared", variant)
        || contains_qualified_variant(compact, "Self", variant)
    {
        return true;
    }
    let bare = format!("{variant}(");
    compact == variant
        || compact.starts_with(&bare)
        || compact.contains(&format!("|{bare}"))
        || compact.contains(&format!("({bare}"))
        || compact.contains(&format!(",{bare}"))
}

fn contains_qualified_variant(compact: &str, qualifier: &str, variant: &str) -> bool {
    let needle = format!("{qualifier}::{variant}");
    let mut haystack = compact;
    while let Some(pos) = haystack.find(&needle) {
        let after = &haystack[pos + needle.len()..];
        if after
            .chars()
            .next()
            .is_none_or(|ch| matches!(ch, '(' | '{' | ')' | '|' | ',' | ']'))
        {
            return true;
        }
        haystack = &after[1..];
    }
    false
}

fn expected_by_key() -> BTreeMap<String, &'static ExpectedProjectionLadder> {
    EXPECTED_PROJECTION_LADDERS
        .iter()
        .map(|expected| (expected.key(), expected))
        .collect()
}

fn observed_by_key(observed: &[ProjectionLadder]) -> BTreeMap<String, &ProjectionLadder> {
    observed
        .iter()
        .map(|ladder| (ladder.key(), ladder))
        .collect()
}

fn report_json(
    observed: &[ProjectionLadder],
    unexpected: &[ProjectionLadder],
    missing: &[&ExpectedProjectionLadder],
    over_threshold: &[(&ProjectionLadder, &ExpectedProjectionLadder)],
) -> Value {
    json!({
        "r": observed.len(),
        "threshold": LADDER_THRESHOLD,
        "algebraModules": ALGEBRA_MODULES.iter().map(|(file, reason)| {
            json!({"file": file, "reason": reason})
        }).collect::<Vec<_>>(),
        "expected": EXPECTED_PROJECTION_LADDERS.iter().map(ExpectedProjectionLadder::to_json).collect::<Vec<_>>(),
        "observed": observed.iter().map(ProjectionLadder::to_json).collect::<Vec<_>>(),
        "unexpected": unexpected.iter().map(ProjectionLadder::to_json).collect::<Vec<_>>(),
        "missing": missing.iter().map(|expected| expected.to_json()).collect::<Vec<_>>(),
        "overThreshold": over_threshold.iter().map(|(observed, expected)| {
            json!({
                "observed": observed.to_json(),
                "expected": expected.to_json(),
            })
        }).collect::<Vec<_>>(),
    })
}

fn assert_frontier_matches_expected(observed: &[ProjectionLadder]) {
    let expected = expected_by_key();
    let observed_map = observed_by_key(observed);
    let unexpected = observed
        .iter()
        .filter(|ladder| !expected.contains_key(&ladder.key()))
        .cloned()
        .collect::<Vec<_>>();
    let missing = EXPECTED_PROJECTION_LADDERS
        .iter()
        .filter(|expected| !observed_map.contains_key(&expected.key()))
        .collect::<Vec<_>>();
    let over_threshold = observed
        .iter()
        .filter_map(|ladder| {
            expected.get(&ladder.key()).and_then(|expected| {
                (ladder.floor_arms > expected.max_floor_arms).then_some((ladder, *expected))
            })
        })
        .collect::<Vec<_>>();

    if !unexpected.is_empty() || !missing.is_empty() || !over_threshold.is_empty() {
        panic!(
            "floor projection gate drifted: consumers must use visitors/perform-operation instead of matching Desugared floors directly\n{}",
            serde_json::to_string_pretty(&report_json(
                observed,
                &unexpected,
                &missing,
                &over_threshold
            ))
            .expect("floor projection report serializes")
        );
    }
}

#[test]
fn floor_projection_frontier_matches_expected_multiset() {
    let observed = collect_repo_projection_ladders();
    assert_frontier_matches_expected(&observed);
}

#[test]
#[ignore = "red-by-design: future drain target, not a default CI failure"]
fn floor_projection_frontier_is_zero() {
    let observed = collect_repo_projection_ladders();
    assert!(
        observed.is_empty(),
        "floor projection gate still has R={} ladder(s): {}",
        observed.len(),
        serde_json::to_string_pretty(&report_json(&observed, &observed, &[], &[]))
            .expect("floor projection report serializes")
    );
}

#[test]
fn collector_names_synthetic_consumer_ladder() {
    let source = r#"
        use crate::Desugared;

        fn consumer(floor: Desugared) -> &'static str {
            match floor {
                Desugared::Term(_) => "term",
                Desugared::PredicateValue(_) => "predicate",
                Desugared::ObjectValue(_) => "object",
                other => "other",
            }
        }
    "#;
    let observed =
        collect_projection_ladders_from_source("src/sugar/synthetic_consumer.rs", source);
    let keys = observed
        .iter()
        .map(ProjectionLadder::key)
        .collect::<BTreeSet<_>>();

    assert!(
        keys.iter()
            .any(|key| key.starts_with("src/sugar/synthetic_consumer.rs:consumer:")),
        "synthetic consumer ladder should be named by file:function:patterns; observed={observed:#?}"
    );
    assert_eq!(observed[0].floor_arms, 3);
}

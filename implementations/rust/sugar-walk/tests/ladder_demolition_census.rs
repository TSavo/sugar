// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Ladder-demolition census (#3435).
//
// This is an IDD instrument, not a drain. It names live walker match-ladders
// that classify Rust syntax or wire terms outside the catalog/algebra route.
// Later slices delete rows by routing families through the catalog; this test
// makes new ladders and unowned residue loud.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use quote::ToTokens;
use serde_json::json;
use syn::visit::Visit;

const TARGET_FILES: &[&str] = &[
    "implementations/rust/sugar-walk/src/lift.rs",
    "implementations/rust/sugar-walk/src/emit.rs",
    "implementations/rust/sugar-walk/src/walk.rs",
    "implementations/rust/sugar-walk/src/loops_and_exceptions.rs",
    "implementations/rust/sugar-lift/src/call_edges.rs",
];

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
struct Family {
    name: &'static str,
    owner: &'static str,
    replacement: &'static str,
}

const FAMILIES: &[Family] = &[
    Family {
        name: "tail-expr-ite",
        owner: "#3027 S2",
        replacement: "route tail-position lowering through build_term/build_expr_role and the algebra boundary",
    },
    Family {
        name: "predicates",
        owner: "#3027 S3",
        replacement: "route predicate lifting through PredicateValue/catalog claims",
    },
    Family {
        name: "guard-assertion-facts",
        owner: "#3027 S4",
        replacement: "route guard/assertion fact extraction through algebra guard operations",
    },
    Family {
        name: "value-kind-macros",
        owner: "#3027 S5",
        replacement: "route value classification and macro lowering through catalog recognizers",
    },
    Family {
        name: "wp-contract-seeds",
        owner: "#3027 S6",
        replacement: "route contract-surface lifting and seed facts through typed vocabulary/catalog claims",
    },
    Family {
        name: "panic-loop-effects",
        owner: "#3027 S7",
        replacement: "route panic/loop effect collection through Phase 2 effect routers",
    },
    Family {
        name: "patterns-types-call-edges",
        owner: "#3027 S7",
        replacement: "route patterns, types, and call edges through catalog claims",
    },
];

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
struct ExpectedLadderSite {
    file: &'static str,
    line: usize,
    enclosing_fn: &'static str,
    family: &'static str,
    max_signals: usize,
}

const EXPECTED_LADDER_SITES: &[ExpectedLadderSite] = &[
    ExpectedLadderSite {
        file: "implementations/rust/sugar-lift/src/call_edges.rs",
        line: 441,
        enclosing_fn: "callee_name_from_expr",
        family: "patterns-types-call-edges",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-lift/src/call_edges.rs",
        line: 277,
        enclosing_fn: "collect_call_sites_in_expr",
        family: "patterns-types-call-edges",
        max_signals: 39,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-lift/src/call_edges.rs",
        line: 248,
        enclosing_fn: "collect_call_sites_in_stmt",
        family: "patterns-types-call-edges",
        max_signals: 4,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-lift/src/call_edges.rs",
        line: 167,
        enclosing_fn: "walk_items_for_edges",
        family: "patterns-types-call-edges",
        max_signals: 15,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 849,
        enclosing_fn: "collect_ffi_declarations_in_items",
        family: "value-kind-macros",
        max_signals: 16,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 941,
        enclosing_fn: "collect_proc_macro_invocations_from_item",
        family: "value-kind-macros",
        max_signals: 5,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 934,
        enclosing_fn: "collect_proc_macro_invocations_from_item",
        family: "value-kind-macros",
        max_signals: 16,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 2599,
        enclosing_fn: "concept_sort_from_type",
        family: "value-kind-macros",
        max_signals: 15,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 764,
        enclosing_fn: "find_term_function_in_items",
        family: "value-kind-macros",
        max_signals: 16,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 1096,
        enclosing_fn: "literal_arg_term",
        family: "value-kind-macros",
        max_signals: 3,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 2803,
        enclosing_fn: "local_pat_type",
        family: "value-kind-macros",
        max_signals: 17,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 2787,
        enclosing_fn: "lower_local_let_pattern",
        family: "value-kind-macros",
        max_signals: 3,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 1678,
        enclosing_fn: "lower_match_arm_body_to_stmt",
        family: "value-kind-macros",
        max_signals: 2,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 2140,
        enclosing_fn: "lower_pat_to_pattern_term",
        family: "value-kind-macros",
        max_signals: 7,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 1202,
        enclosing_fn: "lower_stmts_to_stmt",
        family: "value-kind-macros",
        max_signals: 5,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 1526,
        enclosing_fn: "method_receiver_source_name",
        family: "value-kind-macros",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 1579,
        enclosing_fn: "mut_borrow_source_name",
        family: "value-kind-macros",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 2693,
        enclosing_fn: "partial_return_loss",
        family: "value-kind-macros",
        max_signals: 15,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 2537,
        enclosing_fn: "return_shape_from_return_type",
        family: "value-kind-macros",
        max_signals: 2,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 419,
        enclosing_fn: "return_sort_json",
        family: "value-kind-macros",
        max_signals: 4,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 410,
        enclosing_fn: "sort",
        family: "value-kind-macros",
        max_signals: 4,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 2559,
        enclosing_fn: "sort_from_type",
        family: "value-kind-macros",
        max_signals: 15,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 312,
        enclosing_fn: "surface",
        family: "value-kind-macros",
        max_signals: 9,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/emit.rs",
        line: 251,
        enclosing_fn: "to_json",
        family: "value-kind-macros",
        max_signals: 9,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 3277,
        enclosing_fn: "bind_pat_idents_lift",
        family: "patterns-types-call-edges",
        max_signals: 17,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 4227,
        enclosing_fn: "block_only_panics",
        family: "panic-loop-effects",
        max_signals: 3,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 998,
        enclosing_fn: "collect_assertion_guard_facts",
        family: "guard-assertion-facts",
        max_signals: 5,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 3140,
        enclosing_fn: "collect_assignment_roots_lift",
        family: "value-kind-macros",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 1353,
        enclosing_fn: "collect_assignment_target_roots_in_expr",
        family: "value-kind-macros",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 1497,
        enclosing_fn: "collect_assignment_target_roots_in_stmts",
        family: "value-kind-macros",
        max_signals: 4,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 2937,
        enclosing_fn: "collect_expr_roots_lift",
        family: "value-kind-macros",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 2002,
        enclosing_fn: "collect_guarded_panic_effects_in_expr",
        family: "panic-loop-effects",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 1901,
        enclosing_fn: "collect_guarded_panic_effects_in_stmt",
        family: "panic-loop-effects",
        max_signals: 4,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 1279,
        enclosing_fn: "collect_local_value_facts",
        family: "guard-assertion-facts",
        max_signals: 4,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 3225,
        enclosing_fn: "collect_pat_bound_idents_lift",
        family: "patterns-types-call-edges",
        max_signals: 17,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 894,
        enclosing_fn: "collect_pat_names",
        family: "patterns-types-call-edges",
        max_signals: 16,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 2162,
        enclosing_fn: "collect_statement_pure_free_guard_facts",
        family: "panic-loop-effects",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 3067,
        enclosing_fn: "collect_stmt_roots_lift",
        family: "value-kind-macros",
        max_signals: 4,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 2823,
        enclosing_fn: "expr_as_call_lift",
        family: "value-kind-macros",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 2725,
        enclosing_fn: "expr_as_method_call_lift",
        family: "value-kind-macros",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 1209,
        enclosing_fn: "expr_root_ident",
        family: "guard-assertion-facts",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 1529,
        enclosing_fn: "infer_value_kind",
        family: "value-kind-macros",
        max_signals: 4,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 1528,
        enclosing_fn: "infer_value_kind",
        family: "value-kind-macros",
        max_signals: 10,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 441,
        enclosing_fn: "is_pure_value_term",
        family: "wp-contract-seeds",
        max_signals: 5,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 2524,
        enclosing_fn: "keyset_source_from_borrowed_map_expr",
        family: "value-kind-macros",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 1153,
        enclosing_fn: "len_receiver_root_expr",
        family: "guard-assertion-facts",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 3929,
        enclosing_fn: "lift_expr_to_term_inner",
        family: "value-kind-macros",
        max_signals: 2,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 4019,
        enclosing_fn: "lift_expr_to_term_inner",
        family: "value-kind-macros",
        max_signals: 4,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 3764,
        enclosing_fn: "lift_expr_to_term_inner",
        family: "value-kind-macros",
        max_signals: 9,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 3763,
        enclosing_fn: "lift_expr_to_term_inner",
        family: "value-kind-macros",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 3450,
        enclosing_fn: "lift_predicate_value_inner",
        family: "predicates",
        max_signals: 41,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 3363,
        enclosing_fn: "lift_stmt_contribution",
        family: "value-kind-macros",
        max_signals: 4,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 1316,
        enclosing_fn: "local_binding_ident_for_pat",
        family: "guard-assertion-facts",
        max_signals: 17,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 2596,
        enclosing_fn: "local_pat_single_ident",
        family: "patterns-types-call-edges",
        max_signals: 17,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 4267,
        enclosing_fn: "negate",
        family: "value-kind-macros",
        max_signals: 3,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 941,
        enclosing_fn: "pat_contains_mut_ident",
        family: "patterns-types-call-edges",
        max_signals: 9,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 2623,
        enclosing_fn: "pat_single_ident",
        family: "patterns-types-call-edges",
        max_signals: 17,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 2676,
        enclosing_fn: "pat_type_mentions_ident",
        family: "patterns-types-call-edges",
        max_signals: 3,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 2886,
        enclosing_fn: "pure_free_guard_expr_is_pure_read",
        family: "guard-assertion-facts",
        max_signals: 13,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 2650,
        enclosing_fn: "tuple_first_pat_ident",
        family: "patterns-types-call-edges",
        max_signals: 17,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/lift.rs",
        line: 2685,
        enclosing_fn: "type_mentions_ident",
        family: "patterns-types-call-edges",
        max_signals: 5,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/loops_and_exceptions.rs",
        line: 357,
        enclosing_fn: "collect_assigned_root",
        family: "panic-loop-effects",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/loops_and_exceptions.rs",
        line: 204,
        enclosing_fn: "collect_mutated_in_expr",
        family: "panic-loop-effects",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/loops_and_exceptions.rs",
        line: 458,
        enclosing_fn: "lift_match_arm_postconditions",
        family: "panic-loop-effects",
        max_signals: 2,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/loops_and_exceptions.rs",
        line: 110,
        enclosing_fn: "visit_stmt_for_loops",
        family: "panic-loop-effects",
        max_signals: 4,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/walk.rs",
        line: 596,
        enclosing_fn: "collect_into",
        family: "patterns-types-call-edges",
        max_signals: 17,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/walk.rs",
        line: 568,
        enclosing_fn: "let_binding",
        family: "patterns-types-call-edges",
        max_signals: 4,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/walk.rs",
        line: 658,
        enclosing_fn: "pat_kind",
        family: "patterns-types-call-edges",
        max_signals: 17,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/walk.rs",
        line: 280,
        enclosing_fn: "walk_expr_for_callsites",
        family: "patterns-types-call-edges",
        max_signals: 40,
    },
    ExpectedLadderSite {
        file: "implementations/rust/sugar-walk/src/walk.rs",
        line: 260,
        enclosing_fn: "walk_stmt_for_callsites",
        family: "patterns-types-call-edges",
        max_signals: 4,
    },
];

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
struct LadderKey {
    file: String,
    enclosing_fn: String,
    family: String,
    signal_count: usize,
}

#[derive(Debug, Clone, Eq, PartialEq)]
struct LadderSite {
    key: LadderKey,
    line: usize,
    signals: Vec<String>,
}

impl LadderSite {
    fn to_json(&self) -> serde_json::Value {
        let family = family_by_name(&self.key.family);
        json!({
            "file": self.key.file,
            "line": self.line,
            "enclosingFn": self.key.enclosing_fn,
            "family": self.key.family,
            "signalCount": self.key.signal_count,
            "owner": family.map(|f| f.owner).unwrap_or("unowned"),
            "replacement": family.map(|f| f.replacement).unwrap_or("missing replacement route"),
            "signals": self.signals,
        })
    }
}

impl ExpectedLadderSite {
    fn key(&self) -> LadderKey {
        LadderKey {
            file: self.file.to_string(),
            enclosing_fn: self.enclosing_fn.to_string(),
            family: self.family.to_string(),
            signal_count: self.max_signals,
        }
    }

    fn to_json(&self) -> serde_json::Value {
        let family = family_by_name(self.family);
        json!({
            "file": self.file,
            "line": self.line,
            "enclosingFn": self.enclosing_fn,
            "family": self.family,
            "signalCount": self.max_signals,
            "maxSignals": self.max_signals,
            "owner": family.map(|f| f.owner).unwrap_or("unowned"),
            "replacement": family.map(|f| f.replacement).unwrap_or("missing replacement route"),
        })
    }
}

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-walk has rust workspace parent")
        .parent()
        .expect("rust workspace has implementations parent")
        .parent()
        .expect("implementations has repo root parent")
        .to_path_buf()
}

fn collect_ladder_sites(root: &Path) -> Vec<LadderSite> {
    let mut sites = Vec::new();
    for rel in TARGET_FILES {
        let path = root.join(rel);
        let source = fs::read_to_string(&path)
            .unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
        sites.extend(collect_ladder_sites_from_source(rel, &source));
    }
    sites.sort_by(|a, b| a.key.cmp(&b.key));
    sites
}

fn collect_ladder_sites_from_source(file: &str, source: &str) -> Vec<LadderSite> {
    let syntax = syn::parse_file(source)
        .unwrap_or_else(|err| panic!("parse {file} for ladder census: {err}"));
    let mut visitor = LadderVisitor {
        file,
        fn_stack: Vec::new(),
        sites: Vec::new(),
    };
    visitor.visit_file(&syntax);
    visitor.sites
}

struct LadderVisitor<'a> {
    file: &'a str,
    fn_stack: Vec<String>,
    sites: Vec<LadderSite>,
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
        let signals = match_ladder_signals(node);
        if signals.len() >= 2 {
            let line = node.match_token.span.start().line;
            let enclosing_fn = self.current_fn();
            let family = classify_family(self.file, &enclosing_fn, &signals);
            self.sites.push(LadderSite {
                key: LadderKey {
                    file: self.file.to_string(),
                    enclosing_fn,
                    family: family.name.to_string(),
                    signal_count: signals.len(),
                },
                line,
                signals,
            });
        }
        syn::visit::visit_expr_match(self, node);
    }
}

fn has_cfg_test(attrs: &[syn::Attribute]) -> bool {
    attrs.iter().any(|attr| {
        let rendered = attr.meta.to_token_stream().to_string();
        rendered.split_whitespace().collect::<String>() == "cfg(test)"
    })
}

fn match_ladder_signals(node: &syn::ExprMatch) -> Vec<String> {
    let mut signals = BTreeSet::new();
    for arm in &node.arms {
        let compact = arm.pat.to_token_stream().to_string().replace(' ', "");
        for (prefix, label) in SIGNAL_PREFIXES {
            collect_variants_with_prefix(&compact, prefix, label, &mut signals);
        }
    }
    signals.into_iter().collect()
}

const SIGNAL_PREFIXES: &[(&str, &str)] = &[
    ("Expr::", "Expr"),
    ("syn::Expr::", "Expr"),
    ("Pat::", "Pat"),
    ("syn::Pat::", "Pat"),
    ("Type::", "Type"),
    ("syn::Type::", "Type"),
    ("Stmt::", "Stmt"),
    ("syn::Stmt::", "Stmt"),
    ("Item::", "Item"),
    ("syn::Item::", "Item"),
    ("Lit::", "Lit"),
    ("syn::Lit::", "Lit"),
    ("ValueKind::", "ValueKind"),
    ("ReturnShape::", "ReturnShape"),
    ("IrTerm::", "IrTerm"),
    ("IrFormula::", "IrFormula"),
    ("AlgebraTerm::", "AlgebraTerm"),
];

fn collect_variants_with_prefix(
    compact: &str,
    prefix: &str,
    label: &str,
    signals: &mut BTreeSet<String>,
) {
    let mut rest = compact;
    while let Some(pos) = rest.find(prefix) {
        let after = &rest[pos + prefix.len()..];
        let variant = after
            .chars()
            .take_while(|ch| ch.is_ascii_alphanumeric() || *ch == '_')
            .collect::<String>();
        if !variant.is_empty() {
            signals.insert(format!("{label}::{variant}"));
        }
        rest = &after[variant.len()..];
    }
}

fn classify_family(file: &str, enclosing_fn: &str, signals: &[String]) -> &'static Family {
    if file.ends_with("call_edges.rs") {
        return family("patterns-types-call-edges");
    }
    if file.ends_with("walk.rs") {
        return family("patterns-types-call-edges");
    }
    if file.ends_with("loops_and_exceptions.rs") {
        return family("panic-loop-effects");
    }
    if file.ends_with("emit.rs") {
        if enclosing_fn.contains("tail") || enclosing_fn.contains("expr") {
            return family("tail-expr-ite");
        }
        return family("value-kind-macros");
    }
    if file.ends_with("lift.rs") {
        if matches!(
            enclosing_fn,
            "collect_assertion_guard_facts"
                | "collect_local_value_facts"
                | "expr_root_ident"
                | "len_receiver_root_expr"
                | "local_binding_ident_for_pat"
                | "pure_free_guard_expr_is_pure_read"
        ) {
            return family("guard-assertion-facts");
        }
        if enclosing_fn == "is_pure_value_term" {
            return family("wp-contract-seeds");
        }
        if enclosing_fn == "lift_stmt_contribution" {
            return family("value-kind-macros");
        }
        if enclosing_fn.contains("tail")
            || enclosing_fn.contains("ite")
            || enclosing_fn.contains("formula_to_term")
        {
            return family("tail-expr-ite");
        }
        if enclosing_fn.contains("predicate") {
            return family("predicates");
        }
        if enclosing_fn.contains("macro")
            || enclosing_fn.contains("value_kind")
            || enclosing_fn.contains("expr_to_term")
        {
            return family("value-kind-macros");
        }
        if enclosing_fn.contains("precondition")
            || enclosing_fn.contains("postcondition")
            || enclosing_fn.contains("contract")
            || enclosing_fn.contains("seed")
            || enclosing_fn.contains("return_kind")
        {
            return family("wp-contract-seeds");
        }
        // Named exceptions to the guard/panic name heuristics below: these
        // enclosing functions read as guard/assertion helpers by name but are
        // wired into the panic/loop effect family. Anchored by enclosing_fn,
        // not by a line coordinate, so unrelated line shifts in lift.rs never
        // reclassify them.
        const PANIC_LOOP_EFFECTS_NAME_EXCEPTIONS: &[&str] =
            &["collect_statement_pure_free_guard_facts"];
        if enclosing_fn.contains("panic")
            || enclosing_fn.contains("effect")
            || enclosing_fn.contains("partial")
            || PANIC_LOOP_EFFECTS_NAME_EXCEPTIONS.contains(&enclosing_fn)
        {
            return family("panic-loop-effects");
        }
        if enclosing_fn.contains("guard")
            || enclosing_fn.contains("assert")
            || enclosing_fn.contains("len_")
        {
            return family("guard-assertion-facts");
        }
        if signals.iter().any(|signal| {
            signal.starts_with("Pat::")
                || signal.starts_with("Type::")
                || signal.starts_with("Item::")
        }) {
            return family("patterns-types-call-edges");
        }
    }
    family("value-kind-macros")
}

fn family(name: &str) -> &'static Family {
    family_by_name(name).unwrap_or_else(|| panic!("unknown ladder-demolition family {name}"))
}

fn family_by_name(name: &str) -> Option<&'static Family> {
    FAMILIES.iter().find(|family| family.name == name)
}

fn expected_by_key() -> BTreeMap<LadderKey, &'static ExpectedLadderSite> {
    EXPECTED_LADDER_SITES
        .iter()
        .map(|site| (site.key(), site))
        .collect()
}

fn observed_by_key(observed: &[LadderSite]) -> BTreeMap<LadderKey, &LadderSite> {
    observed
        .iter()
        .map(|site| (site.key.clone(), site))
        .collect()
}

fn census_vector(observed: &[LadderSite]) -> BTreeMap<String, usize> {
    let mut vector = FAMILIES
        .iter()
        .map(|family| (family.name.to_string(), 0))
        .collect::<BTreeMap<_, _>>();
    for site in observed {
        *vector.entry(site.key.family.clone()).or_default() += 1;
    }
    vector
}

fn report_json(
    observed: &[LadderSite],
    unexpected: &[LadderSite],
    missing: &[&ExpectedLadderSite],
    over_threshold: &[(&LadderSite, &ExpectedLadderSite)],
) -> String {
    serde_json::to_string_pretty(&json!({
        "r": observed.len(),
        "vector": census_vector(observed),
        "families": FAMILIES.iter().map(|family| {
            json!({
                "family": family.name,
                "owner": family.owner,
                "replacement": family.replacement,
            })
        }).collect::<Vec<_>>(),
        "expected": EXPECTED_LADDER_SITES.iter().map(ExpectedLadderSite::to_json).collect::<Vec<_>>(),
        "observed": observed.iter().map(LadderSite::to_json).collect::<Vec<_>>(),
        "unexpected": unexpected.iter().map(LadderSite::to_json).collect::<Vec<_>>(),
        "missing": missing.iter().map(|site| site.to_json()).collect::<Vec<_>>(),
        "overThreshold": over_threshold.iter().map(|(observed, expected)| {
            json!({
                "observed": observed.to_json(),
                "expected": expected.to_json(),
            })
        }).collect::<Vec<_>>(),
    }))
    .expect("ladder census report serializes")
}

fn to_expected_literal(observed: &[LadderSite]) -> String {
    let mut out = String::from("const EXPECTED_LADDER_SITES: &[ExpectedLadderSite] = &[\n");
    for site in observed {
        out.push_str(&format!(
            "    ExpectedLadderSite {{ file: {:?}, line: {}, enclosing_fn: {:?}, family: {:?}, max_signals: {} }},\n",
            site.key.file,
            site.line,
            site.key.enclosing_fn,
            site.key.family,
            site.signals.len()
        ));
    }
    out.push_str("];\n");
    out
}

fn assert_ladder_census_matches_expected(observed: &[LadderSite]) {
    let expected = expected_by_key();
    let observed_map = observed_by_key(observed);
    let unexpected = observed
        .iter()
        .filter(|site| !expected.contains_key(&site.key))
        .cloned()
        .collect::<Vec<_>>();
    let missing = EXPECTED_LADDER_SITES
        .iter()
        .filter(|site| !observed_map.contains_key(&site.key()))
        .collect::<Vec<_>>();
    let over_threshold = observed
        .iter()
        .filter_map(|site| {
            expected.get(&site.key).and_then(|expected| {
                (site.signals.len() > expected.max_signals).then_some((site, *expected))
            })
        })
        .collect::<Vec<_>>();

    if !unexpected.is_empty() || !missing.is_empty() || !over_threshold.is_empty() {
        panic!(
            "ladder-demolition census drifted: route new walker ladders through the catalog/algebra boundary or extend the owned baseline in the same PR\n{}\n\nPasteable EXPECTED_LADDER_SITES:\n{}",
            report_json(observed, &unexpected, &missing, &over_threshold),
            to_expected_literal(observed)
        );
    }
}

#[test]
fn ladder_census_matches_expected_multiset() {
    let observed = collect_ladder_sites(&repo_root());
    assert_ladder_census_matches_expected(&observed);
}

#[test]
fn tail_expr_ite_family_is_drained() {
    let observed = collect_ladder_sites(&repo_root());
    let tail_sites = observed
        .iter()
        .filter(|site| site.key.family == "tail-expr-ite")
        .cloned()
        .collect::<Vec<_>>();

    assert!(
        tail_sites.is_empty(),
        "{}",
        report_json(&observed, &tail_sites, &[], &[])
    );
}

#[test]
#[ignore = "red-by-design: demolition slices delete rows until this reaches zero-or-declared"]
fn ladder_census_is_zero() {
    let observed = collect_ladder_sites(&repo_root());
    assert!(
        observed.is_empty(),
        "{}",
        report_json(&observed, &observed, &[], &[])
    );
}

#[test]
fn collector_names_planted_ladder_site() {
    let source = r#"
        fn planted_tail_expr_ladder(expr: &syn::Expr) {
            match expr {
                syn::Expr::If(_) => {}
                syn::Expr::Match(_) => {}
                syn::Expr::Call(_) => {}
                _ => {}
            }
        }
    "#;
    let observed =
        collect_ladder_sites_from_source("implementations/rust/sugar-walk/src/lift.rs", source);

    assert!(
        observed.iter().any(|site| {
            site.key.enclosing_fn == "planted_tail_expr_ladder"
                && site.key.family == "tail-expr-ite"
                && site.signals.contains(&"Expr::If".to_string())
                && site.signals.contains(&"Expr::Match".to_string())
        }),
        "planted un-routed ladder must be named with owner/replacement; observed={observed:#?}"
    );
}

#[test]
fn classify_family_survives_innocuous_line_shift() {
    // #3492: classify_family must anchor lift.rs family assignment by
    // enclosing_fn/signal content, never by the match arm's line number.
    // Prepend an unrelated comment block above the function so the match's
    // line number moves, and confirm the observed family is unchanged.
    let unshifted = r#"
        fn collect_statement_pure_free_guard_facts(stmt: &syn::Stmt) {
            match stmt {
                syn::Stmt::Local(_) => {}
                syn::Stmt::Expr(_, _) => {}
                _ => {}
            }
        }
    "#;
    let shifted = &format!(
        "{}\n{unshifted}",
        "// innocuous comment line\n".repeat(64)
    );

    let family_at = |source: &str| {
        collect_ladder_sites_from_source("implementations/rust/sugar-walk/src/lift.rs", source)
            .into_iter()
            .find(|site| site.key.enclosing_fn == "collect_statement_pure_free_guard_facts")
            .unwrap_or_else(|| panic!("planted ladder site not observed in source:\n{source}"))
    };

    let before = family_at(unshifted);
    let after = family_at(shifted);

    assert_ne!(
        before.line, after.line,
        "the planted comment block must actually move the match's line number for this to be a real test"
    );
    assert_eq!(
        before.key.family, after.key.family,
        "family classification must not depend on line coordinates: before={before:#?} after={after:#?}"
    );
    assert_eq!(before.key.family, "panic-loop-effects");
}

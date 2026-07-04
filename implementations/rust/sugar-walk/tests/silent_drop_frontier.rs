// SPDX-License-Identifier: Apache-2.0
//
// Silent-drop frontier auditor (#2997).
//
// This is an IDD instrument, not a drain. It scans the Rust lift kit source for
// silent catch-all/default shapes that can hide unhandled syn/LLBC surface:
// wildcard match arms that do nothing or return None, and Option/Result
// conversion/default calls that erase failure. Each offender remains visible
// until a later drain either makes it loud/total or sanctions the specific site.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use syn::spanned::Spanned;
use syn::visit::Visit;

const EXPECTED_FRONTIER: &[(&str, &str, &str, &str)] = &[];

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
struct ExpectedSanction {
    file: &'static str,
    line: usize,
    kind: &'static str,
    reason: &'static str,
    owner: &'static str,
    retirement: &'static str,
}

const NOT_MINE_RETIREMENT: &str =
    "retire when this recognized non-sugar miss is represented by a typed non-match path or leaves the silent-drop scan";
const DEFAULT_OK_RETIREMENT: &str =
    "retire when this benign default is represented by a typed absence/error path instead of a silent default call";

macro_rules! sanction {
    ($file:literal, $line:literal, $kind:literal, $reason:literal, $owner:literal, $retirement:expr) => {
        ExpectedSanction {
            file: $file,
            line: $line,
            kind: $kind,
            reason: $reason,
            owner: $owner,
            retirement: $retirement,
        }
    };
}

const EXPECTED_SANCTIONS: &[ExpectedSanction] = &[
    sanction!(
        "implementations/rust/sugar-walk/src/bin/hover_probe.rs",
        148,
        "not-mine",
        "debug-cli-verdict-keeps-unresolved-or-not-ready-as-no-final-stem",
        "sugar-walk::bin::hover_probe",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_demo.rs",
        92,
        "not-mine",
        "demo-helper-search-ignores-non-target-items",
        "sugar-walk::bin::walk_demo",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_emit.rs",
        261,
        "not-mine",
        "cli-helper-search-ignores-non-function-items",
        "sugar-walk::bin::walk_emit",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        544,
        "not-mine",
        "recognize tags are minted only from functions inside inline modules",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        564,
        "not-mine",
        "recognize templates only bind single-name parameters",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        567,
        "not-mine",
        "recognize targets are free functions; receivers have no template parameter name",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        2589,
        "not-mine",
        "only is_ok/is_some map to built-in std panic partial stems",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        2808,
        "not-mine",
        "local type name index only records type declarations and inline modules",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        2921,
        "not-mine",
        "struct field map only records struct declarations and inline modules",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        3029,
        "not-mine",
        "enum variant map only records enum declarations and inline modules",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        3162,
        "not-mine",
        "non-binding or schema-needed pattern forms cannot receive a sound value type here",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        3199,
        "not-mine",
        "option inner typing is only sound for Some-like destructuring",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        3236,
        "not-mine",
        "direct type binding cannot assign field element types without a schema",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        3312,
        "not-mine",
        "return-crate index only records functions, methods, and inline modules",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        3440,
        "not-mine",
        "callsite collection only descends through callable bodies and inline modules",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        3765,
        "not-mine",
        "pure-free guard facts are only && chains of is_some method calls",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        4768,
        "not-mine",
        "root extraction tracks pure expression containers that can feed stable guard args",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        4791,
        "not-mine",
        "assignment roots only exist on assignable path-field-index projections",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        4851,
        "not-mine",
        "non-binding pattern forms do not introduce local roots",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        4983,
        "default-ok",
        "crate root probing treats an unreadable Cargo.toml as absence, not proof evidence",
        "sugar-walk::bin::walk_rpc",
        DEFAULT_OK_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        5020,
        "default-ok",
        "raw crate tag probing treats an unreadable Cargo.toml as absence, not proof evidence",
        "sugar-walk::bin::walk_rpc",
        DEFAULT_OK_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        6492,
        "not-mine",
        "lift_post RPC targets top-level free functions by exact name",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        6517,
        "not-mine",
        "contract RPC targets top-level free functions by exact name",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        6603,
        "not-mine",
        "parse_fn helper targets top-level free functions by exact name",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        7649,
        "not-mine",
        "typed local binding name requires a single identifier pattern",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        7653,
        "not-mine",
        "local binding names only exist for single-name local patterns",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        8089,
        "not-mine",
        "local free-function index records only non-test free functions and inline modules",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        8146,
        "not-mine",
        "function contract targets are functions, liftable methods, and inline modules",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        8219,
        "not-mine",
        "bind lift targets are functions, liftable methods, and inline modules",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        8423,
        "not-mine",
        "unrecognized docstring pattern kinds carry no verifier role",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        8437,
        "not-mine",
        "only docstrings and type signatures infer evidence roles",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        8694,
        "not-mine",
        "sugar param_types describe typed value parameters, not receivers",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        8718,
        "not-mine",
        "original param_types describe typed value parameters, not receivers",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        8833,
        "not-mine",
        "body source lookup only searches functions in inline modules",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        9317,
        "not-mine",
        "#3017 item 2 leaves non-scalar literals outside operand symbols",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        9422,
        "not-mine",
        "local binding symbols only exist for single-name local patterns",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        9462,
        "not-mine",
        "local binding sorts only exist for single-name local patterns",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        10191,
        "not-mine",
        "#3017 item 2 leaves non-primitive type names outside scalar shape sorts",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        10506,
        "not-mine",
        "test fixture memento minting searches top-level free functions only",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        10538,
        "default-ok",
        "test tempdir cleanup is best-effort after assertions",
        "sugar-walk::bin::walk_rpc",
        DEFAULT_OK_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        10556,
        "default-ok",
        "test tempdir cleanup is best-effort after assertions",
        "sugar-walk::bin::walk_rpc",
        DEFAULT_OK_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        10585,
        "default-ok",
        "test tempdir cleanup is best-effort after assertions",
        "sugar-walk::bin::walk_rpc",
        DEFAULT_OK_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        10603,
        "default-ok",
        "test tempdir cleanup is best-effort after assertions",
        "sugar-walk::bin::walk_rpc",
        DEFAULT_OK_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        10642,
        "default-ok",
        "test tempdir cleanup is best-effort after assertions",
        "sugar-walk::bin::walk_rpc",
        DEFAULT_OK_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        10644,
        "default-ok",
        "test tempdir cleanup is best-effort after assertions",
        "sugar-walk::bin::walk_rpc",
        DEFAULT_OK_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        10667,
        "default-ok",
        "test tempdir cleanup is best-effort after assertions",
        "sugar-walk::bin::walk_rpc",
        DEFAULT_OK_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        10680,
        "default-ok",
        "test tempdir cleanup is best-effort after assertions",
        "sugar-walk::bin::walk_rpc",
        DEFAULT_OK_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        10693,
        "not-mine",
        "test body-source fixture reads its top-level free function",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        10729,
        "not-mine",
        "test panic-locus helper reads the first top-level free function fixture",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        11199,
        "not-mine",
        "test body-source fixture reads its top-level free function",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        11240,
        "not-mine",
        "test body-template fixture reads its top-level free function",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        12576,
        "not-mine",
        "test comment-surface walker only descends JSON object and array nodes",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        12613,
        "not-mine",
        "test forbidden-field assertion only descends JSON object and array nodes",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        12633,
        "not-mine",
        "test op_cid collector only descends JSON object and array nodes",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        12669,
        "not-mine",
        "test fn_name assertion only descends JSON object and array nodes",
        "sugar-walk::bin::walk_rpc",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        12775,
        "default-ok",
        "test tempdir cleanup is best-effort after assertions",
        "sugar-walk::bin::walk_rpc",
        DEFAULT_OK_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/bin/walk_rpc.rs",
        12826,
        "default-ok",
        "test tempdir cleanup is best-effort after assertions",
        "sugar-walk::bin::walk_rpc",
        DEFAULT_OK_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/contract.rs",
        518,
        "not-mine",
        "test-helper-search-ignores-non-function-items",
        "sugar-walk::contract",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/emit.rs",
        2511,
        "not-mine",
        "user-defined-type-names-flow-to-concept-sort-not-scalar-sort",
        "sugar-walk::emit",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/emit.rs",
        2620,
        "not-mine",
        "non-container-return-type-has-no-partial-loss-record",
        "sugar-walk::emit",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/emit.rs",
        2900,
        "not-mine",
        "non-single-tail-block-is-a-shape-miss-not-a-dropped-obligation",
        "sugar-walk::emit",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/emit.rs",
        2989,
        "not-mine",
        "test-helper-search-ignores-non-target-items",
        "sugar-walk::emit",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/envelope.rs",
        307,
        "not-mine",
        "test-helper-search-ignores-non-function-items",
        "sugar-walk::envelope",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/lift.rs",
        682,
        "not-mine",
        "unrecognized guard predicates deliberately carry no branch fact",
        "sugar-walk::lift",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/lift.rs",
        1875,
        "not-mine",
        "non-matching partial/guard pairs must not discharge",
        "sugar-walk::lift",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/lift.rs",
        3437,
        "not-mine",
        "only assert! contributes a checked precondition",
        "sugar-walk::lift",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/lift.rs",
        4291,
        "not-mine",
        "non-comparison predicates negate as explicit Not nodes",
        "sugar-walk::lift",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/lift.rs",
        4351,
        "not-mine",
        "test helper searches one top-level free function",
        "sugar-walk::lift",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/locus.rs",
        52,
        "not-mine",
        "test-helper-search-ignores-non-target-items",
        "sugar-walk::locus",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/loops_and_exceptions.rs",
        510,
        "not-mine",
        "test-helper-search-ignores-non-function-items",
        "sugar-walk::loops_and_exceptions",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        1131,
        "not-mine",
        "non-string-hover-array-member-has-no-markdown-text",
        "sugar-walk::ra_oracle",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        1141,
        "not-mine",
        "non-text-hover-contents-carry-no-markdown-body",
        "sugar-walk::ra_oracle",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/ra_oracle.rs",
        1340,
        "not-mine",
        "non-paren-character-does-not-affect-balance",
        "sugar-walk::ra_oracle",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/shadow.rs",
        573,
        "not-mine",
        "test-helper-search-ignores-non-target-items",
        "sugar-walk::shadow",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/signature.rs",
        61,
        "not-mine",
        "non-signature-operation-name-has-no-rust-op-cid",
        "sugar-walk::signature",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-walk/src/walk.rs",
        715,
        "not-mine",
        "test-helper-search-ignores-non-function-items",
        "sugar-walk::walk",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        1365,
        "not-mine",
        "non-contract-attributes-are-ignored-by-contract-classifier",
        "sugar-lift-contracts::lib",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        2347,
        "not-mine",
        "test-helper-only-selects-atomic-predicate-names",
        "sugar-lift-contracts::lib",
        NOT_MINE_RETIREMENT
    ),
    sanction!(
        "implementations/rust/sugar-lift-contracts/src/lib.rs",
        2389,
        "not-mine",
        "test-helper-only-selects-atomic-predicate-names",
        "sugar-lift-contracts::lib",
        NOT_MINE_RETIREMENT
    ),
];

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
struct FrontierKey {
    file: String,
    enclosing_fn: String,
    observed: String,
}

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
struct Site {
    kind: &'static str,
    key: FrontierKey,
    line: usize,
    replacement: &'static str,
}

#[derive(Debug, Clone)]
struct Report {
    offenders: Vec<Site>,
}

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
struct SanctionKey {
    file: String,
    kind: String,
    reason: String,
}

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd)]
struct ObservedSanction {
    key: SanctionKey,
    line: usize,
    comment: String,
}

impl Report {
    fn total(&self) -> usize {
        self.offenders.len()
    }

    fn is_zero(&self) -> bool {
        self.offenders.is_empty()
    }

    fn vector(&self) -> BTreeMap<&'static str, usize> {
        let mut vector = BTreeMap::from([
            ("ok", 0),
            ("unwrap_or", 0),
            ("unwrap_or_default", 0),
            ("wildcard_empty_block", 0),
            ("wildcard_none", 0),
        ]);
        for site in &self.offenders {
            *vector.entry(site.kind).or_insert(0) += 1;
        }
        vector
    }

    fn keys_with_kind(&self) -> Vec<(&str, &str, &str, &str)> {
        self.offenders
            .iter()
            .map(|site| {
                (
                    site.kind,
                    site.key.file.as_str(),
                    site.key.enclosing_fn.as_str(),
                    site.key.observed.as_str(),
                )
            })
            .collect()
    }

    fn to_json(&self) -> String {
        let offenders = self
            .offenders
            .iter()
            .map(|site| {
                serde_json::json!({
                    "kind": site.kind,
                    "file": site.key.file,
                    "enclosing_fn": site.key.enclosing_fn,
                    "observed": site.key.observed,
                    "line": site.line,
                    "replacement": site.replacement,
                })
            })
            .collect::<Vec<_>>();
        serde_json::to_string_pretty(&serde_json::json!({
            "total": self.total(),
            "is_zero": self.is_zero(),
            "vector": self.vector(),
            "offenders": offenders,
        }))
        .expect("serialize report")
    }

    fn to_expected_frontier_literal(&self) -> String {
        let mut out = String::new();
        out.push_str("const EXPECTED_FRONTIER: &[(&str, &str, &str, &str)] = &[\n");
        for site in &self.offenders {
            out.push_str(&format!(
                "    ({:?}, {:?}, {:?}, {:?}),\n",
                site.kind, site.key.file, site.key.enclosing_fn, site.key.observed
            ));
        }
        out.push_str("];\n");
        out
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

fn collect_silent_drop_frontier(root: &Path) -> Result<Report, String> {
    let source_roots = [
        root.join("implementations/rust/sugar-walk/src"),
        root.join("implementations/rust/sugar-lift/src"),
        root.join("implementations/rust/sugar-lift-contracts/src"),
    ];
    let mut offenders = Vec::new();
    for source_root in source_roots {
        let files = rust_files_under(&source_root)?;
        for path in files {
            let rel = path
                .strip_prefix(root)
                .map_err(|err| format!("strip {}: {err}", path.display()))?
                .to_string_lossy()
                .replace('\\', "/");
            let source = fs::read_to_string(&path)
                .map_err(|err| format!("read {}: {err}", path.display()))?;
            offenders.extend(collect_silent_drop_frontier_from_source(&rel, &source)?);
        }
    }
    offenders.sort();
    Ok(Report { offenders })
}

fn collect_silent_drop_frontier_from_source(file: &str, source: &str) -> Result<Vec<Site>, String> {
    let parsed = syn::parse_file(source).map_err(|err| format!("parse {file}: {err}"))?;
    let lines = source.lines().map(str::to_string).collect::<Vec<_>>();
    let mut collector = Collector {
        file: file.to_string(),
        lines,
        fn_stack: Vec::new(),
        offenders: Vec::new(),
    };
    collector.visit_file(&parsed);
    Ok(collector.offenders)
}

fn collect_sugar_audit_sanctions(root: &Path) -> Result<Vec<ObservedSanction>, String> {
    let source_roots = [
        root.join("implementations/rust/sugar-walk/src"),
        root.join("implementations/rust/sugar-lift/src"),
        root.join("implementations/rust/sugar-lift-contracts/src"),
    ];
    let mut sanctions = Vec::new();
    for source_root in source_roots {
        let files = rust_files_under(&source_root)?;
        for path in files {
            let rel = path
                .strip_prefix(root)
                .map_err(|err| format!("strip {}: {err}", path.display()))?
                .to_string_lossy()
                .replace('\\', "/");
            let source = fs::read_to_string(&path)
                .map_err(|err| format!("read {}: {err}", path.display()))?;
            sanctions.extend(collect_sugar_audit_sanctions_from_source(&rel, &source));
        }
    }
    sanctions.sort();
    Ok(sanctions)
}

fn collect_sugar_audit_sanctions_from_source(file: &str, source: &str) -> Vec<ObservedSanction> {
    source
        .lines()
        .enumerate()
        .filter_map(|(index, line)| {
            parse_sugar_audit_comment(line).map(|(kind, reason)| ObservedSanction {
                key: SanctionKey {
                    file: file.to_string(),
                    kind: kind.to_string(),
                    reason: reason.to_string(),
                },
                line: index + 1,
                comment: line.trim().to_string(),
            })
        })
        .collect()
}

fn rust_files_under(root: &Path) -> Result<Vec<PathBuf>, String> {
    if !root.is_dir() {
        return Err(format!("source root missing: {}", root.display()));
    }
    let mut files = Vec::new();
    collect_rust_files(root, &mut files)?;
    files.sort();
    Ok(files)
}

fn collect_rust_files(dir: &Path, files: &mut Vec<PathBuf>) -> Result<(), String> {
    for entry in fs::read_dir(dir).map_err(|err| format!("read dir {}: {err}", dir.display()))? {
        let entry = entry.map_err(|err| format!("read dir entry {}: {err}", dir.display()))?;
        let path = entry.path();
        if path.is_dir() {
            collect_rust_files(&path, files)?;
        } else if path.extension().and_then(|ext| ext.to_str()) == Some("rs") {
            files.push(path);
        }
    }
    Ok(())
}

struct Collector {
    file: String,
    lines: Vec<String>,
    fn_stack: Vec<String>,
    offenders: Vec<Site>,
}

impl Collector {
    fn enclosing_fn(&self) -> String {
        self.fn_stack
            .last()
            .cloned()
            .unwrap_or_else(|| "<module>".to_string())
    }

    fn is_sanctioned(&self, line: usize) -> bool {
        let Some(comment_line) = line.checked_sub(1) else {
            return false;
        };
        let Some(source_line) = comment_line
            .checked_sub(1)
            .and_then(|idx| self.lines.get(idx))
        else {
            return false;
        };
        parse_sugar_audit_comment(source_line)
            .is_some_and(|(kind, reason)| expected_sanction_for(&self.file, kind, reason).is_some())
    }

    fn push_site(
        &mut self,
        kind: &'static str,
        line: usize,
        observed: &'static str,
        replacement: &'static str,
    ) {
        if self.is_sanctioned(line) {
            return;
        }
        self.offenders.push(Site {
            kind,
            key: FrontierKey {
                file: self.file.clone(),
                enclosing_fn: self.enclosing_fn(),
                observed: observed.to_string(),
            },
            line,
            replacement,
        });
    }
}

impl<'ast> Visit<'ast> for Collector {
    fn visit_item_fn(&mut self, node: &'ast syn::ItemFn) {
        self.fn_stack.push(node.sig.ident.to_string());
        syn::visit::visit_item_fn(self, node);
        self.fn_stack.pop();
    }

    fn visit_impl_item_fn(&mut self, node: &'ast syn::ImplItemFn) {
        self.fn_stack.push(node.sig.ident.to_string());
        syn::visit::visit_impl_item_fn(self, node);
        self.fn_stack.pop();
    }

    fn visit_expr_match(&mut self, node: &'ast syn::ExprMatch) {
        for arm in &node.arms {
            if !matches!(arm.pat, syn::Pat::Wild(_)) {
                continue;
            }
            let line = arm.pat.span().start().line;
            if is_empty_block(&arm.body) {
                self.push_site(
                    "wildcard_empty_block",
                    line,
                    "_ => {}",
                    "replace silent catch-all with explicit variant handling or loud refusal",
                );
            } else if is_none_expr(&arm.body) {
                self.push_site(
                    "wildcard_none",
                    line,
                    "_ => None",
                    "replace silent classifier miss with explicit handling, refusal, or per-site sanction",
                );
            }
        }
        syn::visit::visit_expr_match(self, node);
    }

    fn visit_expr_method_call(&mut self, node: &'ast syn::ExprMethodCall) {
        let method = node.method.to_string();
        let line = node.method.span().start().line;
        match method.as_str() {
            "unwrap_or" => self.push_site(
                "unwrap_or",
                line,
                "unwrap_or",
                "replace silent default with typed error propagation or default-ok sanction",
            ),
            "unwrap_or_default" => self.push_site(
                "unwrap_or_default",
                line,
                "unwrap_or_default",
                "replace silent default with typed error propagation or default-ok sanction",
            ),
            "ok" => self.push_site(
                "ok",
                line,
                "ok",
                "preserve the error, make the refusal loud, or mark the specific miss not-mine/default-ok",
            ),
            _ => {}
        }
        syn::visit::visit_expr_method_call(self, node);
    }
}

fn is_empty_block(expr: &syn::Expr) -> bool {
    matches!(expr, syn::Expr::Block(block) if block.block.stmts.is_empty())
}

fn is_none_expr(expr: &syn::Expr) -> bool {
    matches!(expr, syn::Expr::Path(path) if path.path.is_ident("None"))
}

fn parse_sugar_audit_comment(line: &str) -> Option<(&str, &str)> {
    let trimmed = line.trim();
    let payload = trimmed.strip_prefix("// sugar-audit: ")?;
    let open = payload.find('(')?;
    let close = payload.strip_suffix(')')?;
    let kind = &payload[..open];
    let reason = &close[open + 1..];
    matches!(kind, "not-mine" | "default-ok").then_some((kind, reason))
}

fn expected_sanction_for(
    file: &str,
    kind: &str,
    reason: &str,
) -> Option<&'static ExpectedSanction> {
    EXPECTED_SANCTIONS.iter().find(|sanction| {
        sanction.file == file && sanction.kind == kind && sanction.reason == reason
    })
}

fn expected_sanction_keys() -> Vec<SanctionKey> {
    EXPECTED_SANCTIONS
        .iter()
        .map(|sanction| SanctionKey {
            file: sanction.file.to_string(),
            kind: sanction.kind.to_string(),
            reason: sanction.reason.to_string(),
        })
        .collect()
}

fn sanctions_report_json(
    observed: &[ObservedSanction],
    unexpected: &[ObservedSanction],
    missing: &[SanctionKey],
) -> String {
    let expected = EXPECTED_SANCTIONS
        .iter()
        .map(|sanction| {
            serde_json::json!({
                "file": sanction.file,
                "line": sanction.line,
                "kind": sanction.kind,
                "reason": sanction.reason,
                "owner": sanction.owner,
                "retirement": sanction.retirement,
            })
        })
        .collect::<Vec<_>>();
    let observed_json = observed
        .iter()
        .map(|sanction| {
            serde_json::json!({
                "file": sanction.key.file,
                "line": sanction.line,
                "kind": sanction.key.kind,
                "reason": sanction.key.reason,
                "comment": sanction.comment,
            })
        })
        .collect::<Vec<_>>();
    serde_json::to_string_pretty(&serde_json::json!({
        "total": observed.len(),
        "expectedTotal": EXPECTED_SANCTIONS.len(),
        "expected": expected,
        "observed": observed_json,
        "unexpected": unexpected.iter().map(|sanction| {
            serde_json::json!({
                "file": sanction.key.file,
                "line": sanction.line,
                "kind": sanction.key.kind,
                "reason": sanction.key.reason,
            })
        }).collect::<Vec<_>>(),
        "missing": missing.iter().map(|key| {
            serde_json::json!({
                "file": key.file,
                "kind": key.kind,
                "reason": key.reason,
            })
        }).collect::<Vec<_>>(),
    }))
    .expect("serialize sanctions report")
}

fn assert_sugar_audit_sanctions_match(observed: &[ObservedSanction]) {
    let expected_keys = expected_sanction_keys()
        .into_iter()
        .collect::<BTreeSet<_>>();
    let observed_keys = observed
        .iter()
        .map(|sanction| sanction.key.clone())
        .collect::<BTreeSet<_>>();
    let unexpected = observed
        .iter()
        .filter(|sanction| !expected_keys.contains(&sanction.key))
        .cloned()
        .collect::<Vec<_>>();
    let missing = expected_keys
        .difference(&observed_keys)
        .cloned()
        .collect::<Vec<_>>();
    let incomplete_expected = EXPECTED_SANCTIONS
        .iter()
        .filter(|sanction| sanction.owner.is_empty() || sanction.retirement.is_empty())
        .collect::<Vec<_>>();

    if !unexpected.is_empty() || !missing.is_empty() || !incomplete_expected.is_empty() {
        panic!(
            "sugar-audit sanctions drifted: exemption comments are anchors only; add/remove typed rows with owner, reason, and retirement\n{}\nincompleteExpected={incomplete_expected:#?}",
            sanctions_report_json(observed, &unexpected, &missing)
        );
    }
}

#[test]
fn silent_drop_frontier_matches_expected_multiset() {
    let report = collect_silent_drop_frontier(&repo_root()).expect("collect silent-drop frontier");
    let observed = report.keys_with_kind();

    assert_eq!(
        observed,
        EXPECTED_FRONTIER,
        "silent-drop frontier changed\n{}\n\nPasteable EXPECTED_FRONTIER:\n{}",
        report.to_json(),
        report.to_expected_frontier_literal()
    );
}

#[test]
fn silent_drop_frontier_is_red_report_only() {
    let report = collect_silent_drop_frontier(&repo_root()).expect("collect silent-drop frontier");
    eprintln!("{}", report.to_json());

    assert!(report.is_zero(), "{}", report.to_json());
    assert_eq!(
        report.total(),
        EXPECTED_FRONTIER.len(),
        "{}",
        report.to_json()
    );
}

#[test]
fn silent_drop_frontier_stable_zero_target() {
    let report = collect_silent_drop_frontier(&repo_root()).expect("collect silent-drop frontier");

    assert!(report.is_zero(), "{}", report.to_json());
}

#[test]
fn sugar_audit_sanctions_match_typed_table() {
    let observed =
        collect_sugar_audit_sanctions(&repo_root()).expect("collect sugar-audit comments");
    assert_sugar_audit_sanctions_match(&observed);
}

#[test]
fn collector_names_planted_offender_classifier_shapes() {
    let source = r#"
        fn planted_empty_block(value: Option<i32>) {
            match value {
                Some(_) => {}
                _ => {}
            }
        }

        fn planted_none(value: Option<i32>) -> Option<i32> {
            match value {
                Some(inner) => Some(inner),
                _ => None,
            }
        }

        fn planted_unwrap_or(value: Option<i32>) -> i32 {
            value.unwrap_or(0)
        }
    "#;
    let offenders = collect_silent_drop_frontier_from_source(
        "implementations/rust/sugar-walk/src/planted.rs",
        source,
    )
    .expect("collect planted silent drop");

    assert!(
        offenders.iter().any(|site| {
            site.kind == "wildcard_empty_block"
                && site.key.enclosing_fn == "planted_empty_block"
                && site.key.observed == "_ => {}"
        }),
        "planted wildcard empty block must red the stable-zero floor; offenders={offenders:#?}"
    );
    assert!(
        offenders.iter().any(|site| {
            site.kind == "wildcard_none"
                && site.key.enclosing_fn == "planted_none"
                && site.key.observed == "_ => None"
        }),
        "planted wildcard None must red the stable-zero floor; offenders={offenders:#?}"
    );
    assert!(
        offenders.iter().any(|site| {
            site.kind == "unwrap_or"
                && site.key.enclosing_fn == "planted_unwrap_or"
                && site.key.observed == "unwrap_or"
        }),
        "planted unwrap_or must red the stable-zero floor; offenders={offenders:#?}"
    );
}

#[test]
fn unlisted_sugar_audit_comment_is_rejected() {
    let observed = collect_sugar_audit_sanctions_from_source(
        "implementations/rust/sugar-walk/src/planted.rs",
        "// sugar-audit: not-mine(planted-comment)\nfn planted() {}\n",
    );
    let expected_keys = BTreeSet::<SanctionKey>::new();
    let unexpected = observed
        .iter()
        .filter(|sanction| !expected_keys.contains(&sanction.key))
        .collect::<Vec<_>>();

    assert_eq!(unexpected.len(), 1, "unlisted sanction comments must red");
}

#[test]
fn listed_sugar_audit_comment_requires_live_anchor() {
    let observed = collect_sugar_audit_sanctions_from_source(
        "implementations/rust/sugar-walk/src/planted.rs",
        "fn planted() {}\n",
    );
    let observed_keys = observed
        .iter()
        .map(|sanction| sanction.key.clone())
        .collect::<BTreeSet<_>>();
    let expected = SanctionKey {
        file: "implementations/rust/sugar-walk/src/planted.rs".to_string(),
        kind: "not-mine".to_string(),
        reason: "planted-comment".to_string(),
    };

    assert!(
        !observed_keys.contains(&expected),
        "listed sanctions without a live comment anchor must red"
    );
}

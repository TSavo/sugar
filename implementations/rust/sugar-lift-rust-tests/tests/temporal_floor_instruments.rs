// SPDX-License-Identifier: Apache-2.0
//
// Temporal floor campaign S1 (#3374): instruments only.
//
// These tests intentionally measure current debt. They pass with pinned R > 0
// and fail if a new unmeasured path appears, a row silently disappears, or the
// byte-compat harness stops proving replay stability.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use toml::Value;

const CATALOG_TOML: &str = include_str!("fixtures/temporal_floor_catalog.toml");

const EXPECTED_STDLIB_TEMPORAL_SURFACE_UNENROLLED: usize = 26;
const EXPECTED_OPERATION_FLOORS_UNLANDED_R: usize = 13;
const EXPECTED_EMBEDDINGS_R: usize = 0;

const REQUIRED_CATALOG_ROWS: &[&str] = &[
    "iterator-map",
    "iterator-fold",
    "iterator-take",
    "iterator-zip",
    "option-map",
    "option-unwrap",
    "result-map",
    "result-transpose",
    "try-question-mark",
    "operator-add-assign",
    "tokio-async-runtime-out",
];

const REQUIRED_ITER_MEMBERS: &[&str] = &[
    "ArrayLiteral",
    "TupleLiteral",
    "StringLiteral.chars",
    "StringLiteral.bytes",
    "RangeLiteral",
    "MapOutput",
    "FilterOutput",
    "FilterMapOutput",
    "ChainOutput",
    "ZipOutput",
    "EnumerateOutput",
    "TakeOutput",
    "SkipOutput",
    "TakeWhileOutput",
    "SkipWhileOutput",
    "InspectOutput",
    "StatedCollection",
    "DerivedCollection",
];

const EXPECTED_UNCOUNTED_COMPOSITION_PATHS: &[&str] = &[
    "aggregate_decomp.rs:283",
    "aggregate_decomp.rs:316",
    "aggregate_decomp.rs:318",
    "aggregate_decomp.rs:323",
    "assign_op.rs:1684",
    "assign_op.rs:2084",
    "assign_op.rs:2123",
    "assign_op.rs:2571",
    "char_range_filter_map.rs:91",
    "char_range_filter_map.rs:115",
    "collect.rs:42",
    "collect.rs:105",
    "collect.rs:129",
    "cycle.rs:98",
    "extract_if.rs:219",
    "flat_map.rs:46",
    "flatten.rs:39",
    "flatten.rs:61",
    "float_refinement.rs:252",
    "float_refinement.rs:299",
    "float_refinement.rs:311",
    "float_refinement.rs:336",
    "float_refinement.rs:364",
    "for_replay.rs:1641",
    "forall.rs:592",
    "forall.rs:668",
    "function_map.rs:85",
    "generic_body_sugar.rs:349",
    "identity_map.rs:34",
    "infinity_eq.rs:274",
    "insert.rs:220",
    "inspect.rs:63",
    "inspect.rs:105",
    "inspect.rs:249",
    "intersperse_collect_string.rs:160",
    "intersperse_collect_string.rs:178",
    "intersperse_concat.rs:121",
    "ip_addr.rs:309",
    "ip_addr.rs:312",
    "iter_terminal.rs:573",
    "iter_terminal.rs:714",
    "let_stmt.rs:65",
    "map.rs:76",
    "map.rs:103",
    "method_family.rs:484",
    "method_family.rs:650",
    "method_family.rs:663",
    "option_unwrap.rs:42",
    "peekable.rs:57",
    "peekable.rs:217",
    "primitive_int.rs:479",
    "primitive_int.rs:2016",
    "result_predicate.rs:59",
    "result_predicate.rs:279",
    "rev.rs:29",
    "scan.rs:72",
    "step_by.rs:34",
    "utf8_chunks.rs:264",
    "utf8_chunks.rs:273",
];

const EXPECTED_COMBINATOR_LOCAL_RENAMES: &[&str] = &[];

#[derive(Debug)]
struct Metrics {
    stdlib_temporal_surface_unenrolled: usize,
    operation_floors_unlanded_r: usize,
    embeddings_r: usize,
    catalog_methods: BTreeSet<String>,
    landed_counted_loci: BTreeSet<String>,
    operation_floor_rows: BTreeSet<String>,
    iter_members: BTreeMap<String, String>,
}

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-lift-rust-tests has rust workspace parent")
        .parent()
        .expect("rust workspace has implementations parent")
        .parent()
        .expect("implementations has repo root parent")
        .to_path_buf()
}

fn sugar_src_root() -> PathBuf {
    repo_root().join("implementations/rust/sugar-lift-rust-tests/src/sugar")
}

fn parse_catalog(text: &str) -> Result<Value, String> {
    text.parse::<Value>()
        .map_err(|err| format!("temporal floor catalog TOML parse error: {err}"))
}

fn table_rows<'a>(doc: &'a Value, name: &str) -> Result<&'a [Value], String> {
    doc.get(name)
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .ok_or_else(|| format!("catalog missing [[{name}]] rows"))
}

fn str_field<'a>(row: &'a Value, key: &str, row_name: &str) -> Result<&'a str, String> {
    row.get(key)
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| format!("{row_name} missing non-empty `{key}`"))
}

fn str_array_field<'a>(row: &'a Value, key: &str, row_name: &str) -> Result<Vec<&'a str>, String> {
    let values = row
        .get(key)
        .and_then(Value::as_array)
        .filter(|values| !values.is_empty())
        .ok_or_else(|| format!("{row_name} missing non-empty `{key}` array"))?;
    values
        .iter()
        .enumerate()
        .map(|(idx, value)| {
            value
                .as_str()
                .filter(|s| !s.is_empty())
                .ok_or_else(|| format!("{row_name} `{key}`[{idx}] must be a non-empty string"))
        })
        .collect()
}

fn validate_catalog(text: &str) -> Result<Metrics, String> {
    let doc = parse_catalog(text)?;
    let catalog = table_rows(&doc, "catalog")?;
    let floors = table_rows(&doc, "operation_floor")?;
    let embeddings = table_rows(&doc, "embedding")?;

    let mut catalog_ids = BTreeSet::new();
    let mut catalog_methods = BTreeSet::new();
    let mut landed_counted_loci = BTreeSet::new();
    let mut out_rows = Vec::new();
    let mut used_floors = BTreeSet::new();
    let mut stdlib_temporal_surface_unenrolled = 0usize;
    for row in catalog {
        let id = str_field(row, "id", "catalog row")?;
        if !catalog_ids.insert(id.to_string()) {
            return Err(format!("duplicate catalog id `{id}`"));
        }
        for required in [
            "trait_name",
            "method",
            "shape",
            "operation_floor",
            "doorway",
            "owner",
            "target_slice",
            "status",
        ] {
            str_field(row, required, id)?;
        }
        let status = str_field(row, "status", id)?;
        let doorway = str_field(row, "doorway", id)?;
        if !matches!(doorway, "bind" | "rewrite" | "curry" | "out") {
            return Err(format!("{id} has invalid doorway `{doorway}`"));
        }
        match status {
            "unenrolled" => {
                stdlib_temporal_surface_unenrolled += 1;
                catalog_methods.insert(str_field(row, "method", id)?.to_string());
                used_floors.insert(str_field(row, "operation_floor", id)?.to_string());
            }
            "landed" => {
                catalog_methods.insert(str_field(row, "method", id)?.to_string());
                used_floors.insert(str_field(row, "operation_floor", id)?.to_string());
                str_field(row, "counted_loci_reason", id)?;
                for locus in str_array_field(row, "counted_loci", id)? {
                    if !landed_counted_loci.insert(locus.to_string()) {
                        return Err(format!("duplicate landed counted locus `{locus}`"));
                    }
                }
            }
            "out" => {
                if doorway != "out" {
                    return Err(format!("{id} is out-of-scope but doorway is `{doorway}`"));
                }
                str_field(row, "reason", id)?;
                out_rows.push(id.to_string());
            }
            other => return Err(format!("{id} has unknown status `{other}`")),
        }
    }

    for required in REQUIRED_CATALOG_ROWS {
        if !catalog_ids.contains(*required) {
            return Err(format!("missing required catalog row `{required}`"));
        }
    }
    if out_rows != ["tokio-async-runtime-out"] {
        return Err(format!(
            "expected exactly the Tokio/async OUT manifest row, got {out_rows:?}"
        ));
    }

    let mut operation_floor_rows = BTreeSet::new();
    let mut operation_floors_unlanded_r = 0usize;
    for row in floors {
        let id = str_field(row, "id", "operation_floor row")?;
        let floor = str_field(row, "floor", id)?;
        if !operation_floor_rows.insert(floor.to_string()) {
            return Err(format!("duplicate operation floor `{floor}`"));
        }
        let status = str_field(row, "status", id)?;
        if status != "landed" {
            operation_floors_unlanded_r += 1;
        }
        str_field(row, "owner", id)?;
        str_field(row, "reason", id)?;
    }
    let missing_floors: Vec<_> = used_floors
        .difference(&operation_floor_rows)
        .cloned()
        .collect();
    if !missing_floors.is_empty() {
        return Err(format!(
            "catalog operation floors missing vector rows: {missing_floors:?}"
        ));
    }

    let mut iter_members = BTreeMap::new();
    let mut embedding_ids = BTreeSet::new();
    let mut embeddings_r = 0usize;
    for row in embeddings {
        let id = str_field(row, "id", "embedding row")?;
        if !embedding_ids.insert(id.to_string()) {
            return Err(format!("duplicate embedding id `{id}`"));
        }
        let floor = str_field(row, "floor", id)?;
        let member = str_field(row, "member", id)?;
        let provenance = str_field(row, "provenance", id)?;
        let status = str_field(row, "status", id)?;
        if status != "landed" {
            embeddings_r += 1;
        }
        if floor == "iter" {
            iter_members.insert(member.to_string(), provenance.to_string());
        }
        str_field(row, "owner", id)?;
    }
    let required_iter_members: BTreeSet<_> = REQUIRED_ITER_MEMBERS
        .iter()
        .map(|s| s.to_string())
        .collect();
    let observed_iter_members: BTreeSet<_> = iter_members.keys().cloned().collect();
    if observed_iter_members != required_iter_members {
        return Err(format!(
            "iter-floor members drifted: expected {required_iter_members:?}, got {observed_iter_members:?}"
        ));
    }
    for (member, expected_provenance) in [
        ("StatedCollection", "Stated"),
        ("DerivedCollection", "Derived"),
    ] {
        if iter_members.get(member).map(String::as_str) != Some(expected_provenance) {
            return Err(format!(
                "{member} must carry `{expected_provenance}` provenance in A-prime"
            ));
        }
    }

    Ok(Metrics {
        stdlib_temporal_surface_unenrolled,
        operation_floors_unlanded_r,
        embeddings_r,
        catalog_methods,
        landed_counted_loci,
        operation_floor_rows,
        iter_members,
    })
}

fn production_lines(path: &Path) -> Vec<(usize, String)> {
    let text =
        fs::read_to_string(path).unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
    let mut in_test_module = false;
    text.lines()
        .enumerate()
        .filter_map(|(idx, line)| {
            let trimmed = line.trim();
            if trimmed.starts_with("#[cfg(test)]") || trimmed.starts_with("mod tests") {
                in_test_module = true;
            }
            if in_test_module || trimmed.starts_with("//") || trimmed.starts_with("///") {
                None
            } else {
                Some((idx + 1, line.to_string()))
            }
        })
        .collect()
}

fn rust_files(root: &Path) -> Vec<PathBuf> {
    let mut files: Vec<_> = fs::read_dir(root)
        .unwrap_or_else(|err| panic!("read dir {}: {err}", root.display()))
        .map(|entry| entry.expect("read dir entry").path())
        .filter(|path| path.extension().and_then(|ext| ext.to_str()) == Some("rs"))
        .collect();
    files.sort();
    files
}

fn detect_uncounted_composition_paths(
    root: &Path,
    methods: &BTreeSet<String>,
    landed_counted_loci: &BTreeSet<String>,
) -> Vec<String> {
    let mut rows = Vec::new();
    for path in rust_files(root) {
        let rel = path
            .strip_prefix(root)
            .expect("file belongs to scan root")
            .display()
            .to_string();
        for (line_no, line) in production_lines(&path) {
            if ![
                "call.method",
                "call_method_key",
                "matches!",
                "method.as_str()",
            ]
            .iter()
            .any(|needle| line.contains(needle))
            {
                continue;
            }
            let hits: Vec<_> = methods
                .iter()
                .filter(|method| method.as_str() != "?")
                .filter(|method| line.contains(&format!("\"{method}\"")))
                .collect();
            if !hits.is_empty() {
                let row = format!("{rel}:{line_no}");
                if landed_counted_loci.contains(&row) {
                    continue;
                }
                rows.push(row);
            }
        }
    }
    rows.sort();
    rows
}

fn detect_combinator_local_renames(root: &Path) -> Vec<String> {
    let local_rename_needles = [
        "CurryOccurrence {",
        "bump_consuming_occurrence",
        "@adv{",
        "format!(\"#",
        "@def{",
    ];
    let mut rows = Vec::new();
    for path in rust_files(root) {
        let rel = path
            .strip_prefix(root)
            .expect("file belongs to scan root")
            .display()
            .to_string();
        if rel == "temporal_floor.rs" {
            continue;
        }
        for (line_no, line) in production_lines(&path) {
            if local_rename_needles
                .iter()
                .any(|needle| line.contains(needle))
            {
                rows.push(format!("{rel}:{line_no}"));
            }
        }
    }
    rows.sort();
    rows
}

fn as_set(rows: &[&str]) -> BTreeSet<String> {
    rows.iter().map(|row| row.to_string()).collect()
}

fn diff_message(label: &str, expected: &BTreeSet<String>, observed: &[String]) -> String {
    let observed_set: BTreeSet<_> = observed.iter().cloned().collect();
    let missing: Vec<_> = expected.difference(&observed_set).cloned().collect();
    let unexpected: Vec<_> = observed_set.difference(expected).cloned().collect();
    format!(
        "{label} drifted\nmissing={missing:#?}\nunexpected={unexpected:#?}\nobserved={observed:#?}"
    )
}

fn temp_root(label: &str) -> PathBuf {
    let root =
        std::env::temp_dir().join(format!("temporal-floor-s1-{label}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).expect("create temp root");
    root
}

fn write_fake_sugar(path: &Path, lift_ok: bool) {
    let lift_json = if lift_ok {
        r#"{"case":"lift","ok":true}"#
    } else {
        r#"{"case":"lift","ok":false}"#
    };
    let script = format!(
        r#"#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  verify) printf '%s\n' '{{"case":"verify","ok":true}}' ;;
  prove) printf '%s\n' '{{"case":"prove","ok":true}}' ;;
  lift) printf '%s\n' '{lift_json}' ;;
  *) exit 2 ;;
esac
"#
    );
    fs::write(path, script).expect("write fake sugar");
    let mut perms = fs::metadata(path)
        .expect("fake sugar metadata")
        .permissions();
    perms.set_mode(0o755);
    fs::set_permissions(path, perms).expect("chmod fake sugar");
}

fn drop_table_row_by_id(text: &str, table_name: &str, id: &str) -> String {
    let mut out = String::new();
    let mut current = String::new();
    let mut current_table: Option<String> = None;
    let flush = |buf: &mut String, table: &Option<String>, out: &mut String| {
        if buf.is_empty() {
            return;
        }
        let drop = table.as_deref() == Some(table_name) && buf.contains(&format!("id = \"{id}\""));
        if !drop {
            out.push_str(buf);
        }
        buf.clear();
    };

    for line in text.lines() {
        if line.starts_with("[[") && line.ends_with("]]") {
            flush(&mut current, &current_table, &mut out);
            current_table = Some(line.trim_matches(&['[', ']'][..]).to_string());
        }
        current.push_str(line);
        current.push('\n');
    }
    flush(&mut current, &current_table, &mut out);
    out
}

#[test]
fn temporal_catalog_and_membership_vectors_are_pinned() {
    let metrics = validate_catalog(CATALOG_TOML).expect("temporal floor catalog is valid");
    println!(
        "R(stdlib-temporal-surface-unenrolled) = {}",
        metrics.stdlib_temporal_surface_unenrolled
    );
    println!(
        "R(operation-floors-unlanded) = {}",
        metrics.operation_floors_unlanded_r
    );
    println!("R(embeddings) = {}", metrics.embeddings_r);
    println!("operation floors = {:#?}", metrics.operation_floor_rows);
    println!("iter floor members = {:#?}", metrics.iter_members);
    println!("landed counted loci = {:#?}", metrics.landed_counted_loci);
    assert_eq!(
        metrics.stdlib_temporal_surface_unenrolled,
        EXPECTED_STDLIB_TEMPORAL_SURFACE_UNENROLLED
    );
    assert_eq!(
        metrics.operation_floors_unlanded_r,
        EXPECTED_OPERATION_FLOORS_UNLANDED_R
    );
    assert_eq!(metrics.embeddings_r, EXPECTED_EMBEDDINGS_R);
    assert_eq!(
        metrics
            .iter_members
            .get("StatedCollection")
            .map(String::as_str),
        Some("Stated")
    );
    assert_eq!(
        metrics
            .iter_members
            .get("DerivedCollection")
            .map(String::as_str),
        Some("Derived")
    );
    assert_eq!(
        metrics.landed_counted_loci,
        as_set(&[
            "chain.rs:55",
            "enumerate.rs:49",
            "filter.rs:51",
            "filter_map.rs:60",
            "fold.rs:69",
            "fold.rs:70",
            "inspect.rs:61",
            "inspect.rs:103",
            "inspect.rs:247",
            "iter_terminal.rs:622",
            "iter_terminal.rs:623",
            "map.rs:74",
            "map.rs:101",
            "option_adaptor.rs:303",
            "option_adaptor.rs:308",
            "option_adaptor.rs:313",
            "option_adaptor.rs:318",
            "option_adaptor.rs:326",
            "option_adaptor.rs:331",
            "option_adaptor.rs:336",
            "option_adaptor.rs:341",
            "option_adaptor.rs:346",
            "option_adaptor.rs:351",
            "option_adaptor.rs:356",
            "option_adaptor.rs:361",
            "option_adaptor.rs:524",
            "option_adaptor.rs:528",
            "option_adaptor.rs:562",
            "skip.rs:47",
            "skip_while.rs:51",
            "take.rs:48",
            "take_while.rs:51",
            "zip.rs:62",
        ]),
        "landed count exemptions must be visible in the temporal catalog"
    );
}

#[test]
fn temporal_catalog_bad_twins_red_through_the_catalog_validator() {
    let missing_catalog_row = drop_table_row_by_id(CATALOG_TOML, "catalog", "iterator-map");
    let err = validate_catalog(&missing_catalog_row).expect_err("catalog row deletion must red");
    assert!(
        err.contains("missing required catalog row `iterator-map`"),
        "wrong catalog deletion error: {err}"
    );

    let missing_embedding = drop_table_row_by_id(CATALOG_TOML, "embedding", "iter-map-output");
    let err = validate_catalog(&missing_embedding).expect_err("missing iter embedding must red");
    assert!(
        err.contains("iter-floor members drifted"),
        "wrong embedding deletion error: {err}"
    );

    let no_target = format!(
        "{CATALOG_TOML}\n[[catalog]]\nid = \"planted-no-target\"\ntrait_name = \"Iterator\"\nmethod = \"map\"\nshape = \"planted\"\noperation_floor = \"map\"\ndoorway = \"curry\"\nowner = \"S1-bad-twin\"\nstatus = \"unenrolled\"\n"
    );
    let err = validate_catalog(&no_target).expect_err("missing target slice must red");
    assert!(
        err.contains("missing non-empty `target_slice`"),
        "wrong missing target error: {err}"
    );
}

#[test]
fn uncounted_composition_paths_are_row_pinned_with_planted_control() {
    let metrics = validate_catalog(CATALOG_TOML).expect("catalog");
    let observed = detect_uncounted_composition_paths(
        &sugar_src_root(),
        &metrics.catalog_methods,
        &metrics.landed_counted_loci,
    );
    let expected = as_set(EXPECTED_UNCOUNTED_COMPOSITION_PATHS);
    println!("R(uncounted-composition-paths) = {}", observed.len());
    println!("uncounted composition rows = {observed:#?}");
    assert_eq!(
        observed.iter().cloned().collect::<BTreeSet<_>>(),
        expected,
        "{}",
        diff_message("R(uncounted-composition-paths)", &expected, &observed)
    );

    let planted = temp_root("uncounted-planted");
    fs::write(
        planted.join("planted_map.rs"),
        r#"fn planted(call: &Call) { if call.method != "map" || call.args.len() != 1 {} }"#,
    )
    .expect("write planted catalog method");
    let planted_rows = detect_uncounted_composition_paths(
        &planted,
        &metrics.catalog_methods,
        &metrics.landed_counted_loci,
    );
    assert_eq!(
        planted_rows,
        vec!["planted_map.rs:1"],
        "planted in-catalog combinator should red through the B detector"
    );

    fs::write(
        planted.join("map.rs"),
        r#"fn planted(call: &Call) { if call.method != "map" || call.args.len() != 1 {} }"#,
    )
    .expect("write planted map implementation method");
    let planted_rows = detect_uncounted_composition_paths(
        &planted,
        &metrics.catalog_methods,
        &metrics.landed_counted_loci,
    );
    assert_eq!(
        planted_rows,
        vec!["map.rs:1", "planted_map.rs:1"],
        "planted uncounted map composition inside map.rs must still red; exemptions belong in catalog rows, not file-wide code"
    );

    fs::write(
        planted.join("tokio_spawn.rs"),
        r#"fn out(call: &Call) { if call.method != "spawn" || call.args.len() != 1 {} }"#,
    )
    .expect("write out-of-catalog method");
    let planted_rows = detect_uncounted_composition_paths(
        &planted,
        &metrics.catalog_methods,
        &metrics.landed_counted_loci,
    );
    assert_eq!(
        planted_rows,
        vec!["map.rs:1", "planted_map.rs:1"],
        "Tokio spawn is in the OUT manifest, while the planted map composition remains visible"
    );
}

#[test]
fn combinator_local_rename_axis_is_row_pinned_with_planted_control() {
    let observed = detect_combinator_local_renames(&sugar_src_root());
    let expected = as_set(EXPECTED_COMBINATOR_LOCAL_RENAMES);
    println!("R(combinator-local-renames) = {}", observed.len());
    println!("combinator local rename rows = {observed:#?}");
    println!(
        "Law-8 rung: auditor over representable local mint sites; retirement is S7 when the temporal floor owns a private alias-mint API and planted local mints fail to compile."
    );
    assert_eq!(
        observed.iter().cloned().collect::<BTreeSet<_>>(),
        expected,
        "{}",
        diff_message("R(combinator-local-renames)", &expected, &observed)
    );

    let planted = temp_root("local-rename-planted");
    fs::write(
        planted.join("planted_rename.rs"),
        r#"fn planted() { let _x = CurryOccurrence { family: "planted", ordinal: 0 }; }"#,
    )
    .expect("write planted local rename");
    let planted_rows = detect_combinator_local_renames(&planted);
    assert_eq!(
        planted_rows,
        vec!["planted_rename.rs:1"],
        "planted combinator-local occurrence mint should red through B-prime"
    );

    fs::write(
        planted.join("planted_def.rs"),
        r#"fn planted(name: &str, v: usize) -> String { format!("{name}@def{v}") }"#,
    )
    .expect("write planted @def rename");
    let planted_rows = detect_combinator_local_renames(&planted);
    assert_eq!(
        planted_rows,
        vec!["planted_def.rs:1", "planted_rename.rs:1"],
        "planted local @def mint should red through the expanded B-prime needle"
    );
}

#[test]
fn combinator_local_rename_mint_is_structurally_private() {
    let planted = temp_root("local-mint-compile-fail");
    let source = planted.join("planted_local_mint.rs");
    let temporal_floor = sugar_src_root().join("temporal_floor.rs");
    fs::write(
        &source,
        format!(
            r#"
            #[path = "{}"]
            mod temporal_floor;

            fn main() {{
                let _planted = temporal_floor::CurryOccurrence {{
                    family: "planted",
                    ordinal: 0,
                }};
            }}
            "#,
            temporal_floor.display()
        ),
    )
    .expect("write planted direct local mint");

    let output = Command::new("rustc")
        .arg("--edition=2021")
        .arg(&source)
        .arg("-o")
        .arg(planted.join("planted-local-mint"))
        .output()
        .expect("run rustc for planted direct local mint");
    let stderr = String::from_utf8_lossy(&output.stderr);
    println!("B-prime structural retirement compile-fail stderr:\n{stderr}");
    assert!(
        !output.status.success(),
        "planted direct CurryOccurrence construction must fail to compile"
    );
    assert!(
        stderr.contains("private") && stderr.contains("CurryOccurrence"),
        "compile failure must name the private CurryOccurrence mint, stderr:\n{stderr}"
    );
}

#[test]
fn temporal_floor_byte_harness_reports_zero_and_planted_drift() {
    let root = temp_root("byte");
    let project = root.join("project");
    let out = root.join("out");
    fs::create_dir_all(&project).expect("create project");
    let baseline = root.join("sugar-baseline");
    let changed = root.join("sugar-changed");
    write_fake_sugar(&baseline, true);
    write_fake_sugar(&changed, true);

    let script = repo_root().join("tools/irterm-boundary/byte-compat.sh");
    let zero = Command::new(&script)
        .args([
            "--project-root",
            project.to_str().unwrap(),
            "--baseline-sugar",
            baseline.to_str().unwrap(),
            "--changed-sugar",
            changed.to_str().unwrap(),
            "--out-dir",
            out.to_str().unwrap(),
            "--label",
            "temporal-s1-zero",
            "--case",
            "verify-json",
            "--case",
            "prove-json",
        ])
        .output()
        .unwrap_or_else(|err| panic!("run {} temporal byte harness: {err}", script.display()));
    println!(
        "temporal byte-compat zero stdout:\n{}",
        String::from_utf8_lossy(&zero.stdout)
    );
    assert!(
        zero.status.success(),
        "temporal byte harness should pass with identical outputs\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&zero.stdout),
        String::from_utf8_lossy(&zero.stderr)
    );
    assert!(
        String::from_utf8_lossy(&zero.stdout).contains("R(byte-drift) = 0"),
        "temporal byte harness must report R(byte-drift)=0\nstdout:\n{}",
        String::from_utf8_lossy(&zero.stdout)
    );

    write_fake_sugar(&changed, false);
    let drift = Command::new(&script)
        .args([
            "--project-root",
            project.to_str().unwrap(),
            "--baseline-sugar",
            baseline.to_str().unwrap(),
            "--changed-sugar",
            changed.to_str().unwrap(),
            "--out-dir",
            out.to_str().unwrap(),
            "--label",
            "temporal-s1-planted",
            "--case",
            "lift-json",
        ])
        .output()
        .unwrap_or_else(|err| panic!("run {} planted drift: {err}", script.display()));
    println!(
        "temporal byte-compat planted drift stdout:\n{}",
        String::from_utf8_lossy(&drift.stdout)
    );
    assert!(
        !drift.status.success(),
        "selected lift-json case should fail on planted byte drift"
    );
    assert!(
        String::from_utf8_lossy(&drift.stdout).contains("R(byte-drift) = 1"),
        "planted drift should report R(byte-drift)=1\nstdout:\n{}",
        String::from_utf8_lossy(&drift.stdout)
    );
}

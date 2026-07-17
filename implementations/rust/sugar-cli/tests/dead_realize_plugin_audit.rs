// SPDX-License-Identifier: MIT OR Apache-2.0
//
// IDD instrument for #3816.
//
// DEFECT: `cmd_materialize` was the only dispatcher of `kind = "realize"`
// plugin entries. After the recognize/materialize verb retirement (#3809 /
// #3811), those plugin trees and config registrations have no consumer.
// Stale docs that list `materialize` / `recognize` as live CLI verbs also
// reintroduce a retired surface in prose.
//
// Axes (R):
//   - dead_realize_plugin_trees: any `.sugar/realize/**` path still present
//   - kind_realize_config_entries: any project config with kind = "realize"
//   - retired_cli_verb_docs: live surface docs that still advertise the
//     deleted materialize/recognize subcommands
//
// Replacement architecture when red:
//   Delete the `.sugar/realize/` tree (or the `[[plugins]]` entry). Plugin
//   kinds that ship are `lift` and `emit` only. Rewrite docs against the
//   clap surface (`sugar --help`); do not resurrect materialize/recognize
//   as product verbs. Realize-era type metadata (RealizeRequest,
//   RealizedSource) belongs only while the type still exists in code.
//
// Stable zero is silence. R > 0 stays red. No threshold.

use std::fs;
use std::path::{Path, PathBuf};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("sugar-cli lives under implementations/rust/sugar-cli")
        .to_path_buf()
}

fn rel(root: &Path, path: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
}

fn skip_dir_name(name: &str) -> bool {
    matches!(
        name,
        "target"
            | ".git"
            | "node_modules"
            | "__pycache__"
            | ".venv"
            | "venv"
            | "dist"
            | "build"
            | "out"
    )
}

/// Live product/doc surfaces that must not re-advertise retired verbs.
/// Historical audits/papers/bootstrap receipts are out of scope.
const RETIRED_VERB_DOC_PATHS: &[&str] = &[
    "README.md",
    "docs/reference/cli.md",
    "examples/numpy-showcase/.sugar/config.toml",
];

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct Offender {
    axis: &'static str,
    path: String,
    detail: String,
}

fn collect_realize_trees(root: &Path, dir: &Path, out: &mut Vec<Offender>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let p = entry.path();
        if !p.is_dir() {
            continue;
        }
        let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
        if skip_dir_name(name) {
            continue;
        }
        // Match `.sugar/realize` as a path segment pair.
        if name == "realize" {
            let parent_is_sugar = p
                .parent()
                .and_then(|parent| parent.file_name())
                .and_then(|n| n.to_str())
                == Some(".sugar");
            if parent_is_sugar {
                out.push(Offender {
                    axis: "dead_realize_plugin_trees",
                    path: rel(root, &p),
                    detail: "cmd_materialize was the only kind=\"realize\" dispatcher; \
                             delete this tree. Live plugin dirs are .sugar/lift and \
                             .sugar/emit only."
                        .to_string(),
                });
                // Do not descend; the whole tree is one offender.
                continue;
            }
        }
        collect_realize_trees(root, &p, out);
    }
}

fn collect_config_tomls(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let p = entry.path();
        if p.is_dir() {
            let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
            if skip_dir_name(name) {
                continue;
            }
            collect_config_tomls(&p, out);
        } else if p.file_name().and_then(|n| n.to_str()) == Some("config.toml") {
            // Prefer project configs under .sugar/; still catch any config.toml
            // that re-registers kind = "realize".
            out.push(p);
        }
    }
}

fn kind_realize_line(line: &str) -> bool {
    let t = line.trim();
    // Exact registration form used by project configs; ignore prose comments
    // that merely mention the retired kind.
    if t.starts_with('#') {
        return false;
    }
    let lower = t.to_ascii_lowercase();
    lower == "kind = \"realize\""
        || lower == "kind = 'realize'"
        || lower.starts_with("kind=\"realize\"")
        || lower.starts_with("kind='realize'")
}

fn collect_kind_realize_entries(root: &Path, out: &mut Vec<Offender>) {
    let mut configs = Vec::new();
    collect_config_tomls(root, &mut configs);
    for path in configs {
        let Ok(text) = fs::read_to_string(&path) else {
            continue;
        };
        for (idx, line) in text.lines().enumerate() {
            if kind_realize_line(line) {
                out.push(Offender {
                    axis: "kind_realize_config_entries",
                    path: format!("{}:{}", rel(root, &path), idx + 1),
                    detail: format!(
                        "illegal plugin registration `{line}` — kind=\"realize\" has no \
                         dispatcher after materialize retirement. Use kind=\"lift\" or \
                         kind=\"emit\", or delete the entry."
                    ),
                });
            }
        }
    }
}

fn collect_retired_verb_docs(root: &Path, out: &mut Vec<Offender>) {
    for rel_path in RETIRED_VERB_DOC_PATHS {
        let path = root.join(rel_path);
        let Ok(text) = fs::read_to_string(&path) else {
            continue;
        };
        for (idx, line) in text.lines().enumerate() {
            let lower = line.to_ascii_lowercase();
            // Explicit retirement notes are allowed (they name the dead verbs
            // so agents know not to resurrect them). Live product claims are not.
            if lower.contains("retired")
                || lower.contains("deleted")
                || lower.contains("do not re-advertise")
                || lower.contains("were retired")
            {
                continue;
            }
            // Match product-surface claims of the retired verbs, not incidental
            // English ("materialized", "recognition", historical notes).
            let hits_materialize_verb = lower.contains("`materialize`")
                || lower.contains("| `materialize`")
                || lower.contains("sugar materialize")
                || (lower.contains("materialize")
                    && (lower.contains("subcommand") || lower.contains("verb")));
            let hits_recognize_verb = lower.contains("`recognize`")
                || lower.contains("| `recognize`")
                || lower.contains("sugar recognize")
                || (lower.contains("recognize")
                    && (lower.contains("subcommand")
                        || lower.contains("verb")
                        || lower.contains("drives recognize")
                        || lower.contains(": a production")));
            if hits_materialize_verb || hits_recognize_verb {
                out.push(Offender {
                    axis: "retired_cli_verb_docs",
                    path: format!("{rel_path}:{}", idx + 1),
                    detail: format!(
                        "retired verb advertised on live surface: `{}`. \
                         Rewrite against sugar --help (lift/mint/prove/verify/emit). \
                         materialize and recognize were deleted with their dispatchers.",
                        line.trim()
                    ),
                });
            }
        }
    }
}

fn census() -> Vec<Offender> {
    let root = repo_root();
    let mut offenders = Vec::new();
    collect_realize_trees(&root, &root, &mut offenders);
    collect_kind_realize_entries(&root, &mut offenders);
    collect_retired_verb_docs(&root, &mut offenders);
    offenders.sort();
    offenders.dedup();
    offenders
}

#[test]
fn dead_realize_plugin_registrations_and_stale_materialize_prose_are_gone() {
    let offenders = census();
    if offenders.is_empty() {
        return;
    }

    let mut by_axis: std::collections::BTreeMap<&str, usize> = std::collections::BTreeMap::new();
    for o in &offenders {
        *by_axis.entry(o.axis).or_default() += 1;
    }

    let mut report = String::new();
    report.push_str(
        "R>0: dead realize plugin registrations / stale materialize prose remain (#3816).\n",
    );
    report.push_str(
        "Replacement: delete .sugar/realize trees and kind=\"realize\" plugin entries; \
                     rewrite live docs against clap (lift/emit only; no materialize/recognize).\n",
    );
    report.push_str(&format!("R total = {}\n", offenders.len()));
    for (axis, n) in &by_axis {
        report.push_str(&format!("  R.{axis} = {n}\n"));
    }
    report.push_str("\nOffenders:\n");
    for o in &offenders {
        report.push_str(&format!(
            "  [{axis}] {path}\n    {detail}\n",
            axis = o.axis,
            path = o.path,
            detail = o.detail
        ));
    }
    panic!("{report}");
}

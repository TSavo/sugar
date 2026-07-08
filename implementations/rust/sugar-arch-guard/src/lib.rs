// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Dependency-closure guard (SEAM 0 of the compiler-shape plan).
//
// Reads every workspace crate's Cargo.toml, builds the path-dependency graph
// over [dependencies] + [build-dependencies] (dev-dependencies excluded: they
// do not ship in a published lib's closure), computes the transitive closure,
// and lets tests assert which arrows exist and which are forbidden.
//
// The guard encodes the REAL baseline of the tree, not a fiction:
// `sugar-linker -> sugar-verifier` is a live, allowed edge. What it forbids
// are the arrows that would invert the compiler DAG (see
// ~/.claude/plans/sugar-compiler-liftshift.md Part 1).

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

/// name -> set of workspace-path dependency names (direct edges only).
pub type DepGraph = BTreeMap<String, BTreeSet<String>>;

/// Locate `implementations/rust` from the guard crate's own manifest dir.
pub fn workspace_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-arch-guard sits directly under implementations/rust")
        .to_path_buf()
}

/// Build the direct-edge graph by parsing every `*/Cargo.toml` one level
/// under the workspace root. Only `path = "..."` dependencies count: those
/// are the workspace arrows; registry deps are outside the architecture.
pub fn direct_graph() -> DepGraph {
    let root = workspace_root();
    let mut graph = DepGraph::new();
    let entries = std::fs::read_dir(&root).expect("read workspace root");
    for entry in entries {
        let entry = entry.expect("read_dir entry");
        let manifest = entry.path().join("Cargo.toml");
        if !manifest.is_file() {
            continue;
        }
        let text = std::fs::read_to_string(&manifest)
            .unwrap_or_else(|e| panic!("read {}: {e}", manifest.display()));
        let doc: toml::Value = text
            .parse()
            .unwrap_or_else(|e| panic!("parse {}: {e}", manifest.display()));
        let Some(name) = doc
            .get("package")
            .and_then(|p| p.get("name"))
            .and_then(|n| n.as_str())
        else {
            continue; // the virtual workspace manifest itself
        };
        let mut deps = BTreeSet::new();
        for table in ["dependencies", "build-dependencies"] {
            let Some(section) = doc.get(table).and_then(|d| d.as_table()) else {
                continue;
            };
            for (dep_name, spec) in section {
                // A workspace arrow is a dependency declared with `path = ...`.
                // (`toml` values: either a table with a `path` key, or a bare
                // version string, which is a registry dep and ignored.)
                let is_path_dep = spec
                    .as_table()
                    .map(|t| t.contains_key("path"))
                    .unwrap_or(false);
                if is_path_dep {
                    deps.insert(dep_name.clone());
                }
            }
        }
        graph.insert(name.to_string(), deps);
    }
    assert!(
        graph.contains_key("libsugar") && graph.contains_key("sugar-verifier"),
        "guard failed to discover the workspace crates it exists to audit; \
         found: {:?}",
        graph.keys().collect::<Vec<_>>()
    );
    graph
}

/// Transitive closure of one crate's workspace dependencies.
pub fn closure(graph: &DepGraph, start: &str) -> BTreeSet<String> {
    let mut seen = BTreeSet::new();
    let mut stack: Vec<String> = graph
        .get(start)
        .map(|d| d.iter().cloned().collect())
        .unwrap_or_default();
    while let Some(next) = stack.pop() {
        if seen.insert(next.clone()) {
            if let Some(deps) = graph.get(&next) {
                stack.extend(deps.iter().cloned());
            }
        }
    }
    seen
}

/// Every crate whose closure contains `target` (reverse reachability).
pub fn dependents_of(graph: &DepGraph, target: &str) -> BTreeSet<String> {
    graph
        .keys()
        .filter(|name| closure(graph, name).contains(target))
        .cloned()
        .collect()
}

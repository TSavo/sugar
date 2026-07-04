// SPDX-License-Identifier: MIT OR Apache-2.0
//
// IDD guard: .proof authors use the typed graph API. Leaves are atoms, graph
// edges are typed mementos, and build_proof_envelope receives exactly one
// strongly typed ProofGraph. Raw catalog maps are the old side door.

use std::fs;
use std::path::{Path, PathBuf};

const SKIP_DIRS: &[&str] = &["target", ".git", ".jj", "node_modules"];

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .find(|path| path.join("implementations/rust").is_dir())
        .expect("repo root")
        .to_path_buf()
}

fn collect_rust_files(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if path.is_dir() {
            if !SKIP_DIRS.contains(&name.as_ref()) {
                collect_rust_files(&path, out);
            }
        } else if path.extension().and_then(|ext| ext.to_str()) == Some("rs") {
            out.push(path);
        }
    }
}

#[test]
fn proof_authoring_uses_typed_graph_not_raw_catalog_maps() {
    let root = repo_root();
    let rust_root = root.join("implementations/rust");
    let mut files = Vec::new();
    collect_rust_files(&rust_root, &mut files);

    let mut violations = Vec::new();
    for path in files {
        let relative = path.strip_prefix(&root).unwrap_or(&path).to_path_buf();
        if relative.ends_with(
            "implementations/rust/sugar-proof-envelope/tests/proof_graph_authoring_invariants.rs",
        ) {
            continue;
        }
        let text = fs::read_to_string(&path).expect("read rust source");
        if text.contains("RecognizeBridgeMemento")
            || text.contains("RecognizeContractMemento")
            || text.contains("push_recognize_")
        {
            violations.push(format!(
                "{}: recognize-specific proof wrappers are forbidden. Use BridgeMemento or ContractMemento/ClaimContractMemento and push them through ProofGraph.",
                relative.display()
            ));
        }

        let lines = text.lines().collect::<Vec<_>>();
        for (idx, line) in lines.iter().enumerate() {
            if !line.contains("ProofEnvelopeInput {") {
                continue;
            }
            let window = lines.iter().skip(idx).take(24).copied().collect::<Vec<_>>();
            let raw_field = window.iter().find_map(|candidate| {
                let trimmed = candidate.trim_start();
                ["members:", "members,", "atoms:", "body:"]
                    .iter()
                    .find(|field| trimmed.starts_with(**field))
                    .copied()
            });
            if let Some(field) = raw_field {
                violations.push(format!(
                    "{}:{}: ProofEnvelopeInput still sets `{field}`. Replacement: construct a ProofGraph, register FlatAtom leaves, register ContractBody composition nodes, push typed mementos, and pass only `graph` to build_proof_envelope.",
                    relative.display(),
                    idx + 1
                ));
            }
        }

        if relative.ends_with("implementations/rust/sugar-claim-envelope/src/lib.rs") {
            for forbidden in [
                "target_contract_cid:",
                "antecedent_cid:",
                "consequent_cid:",
                "parent_authority_cid:",
                "additional_input_cids:",
            ] {
                if text.contains(forbidden) {
                    violations.push(format!(
                        "{}: claim-envelope authoring API exposes `{forbidden}`. Replacement: accept the corresponding typed memento ref and render the CID only inside the envelope serializer.",
                        relative.display()
                    ));
                }
            }
        }
    }

    assert!(
        violations.is_empty(),
        "proof authoring has {} typed-graph invariant violation(s):\n{}",
        violations.len(),
        violations.join("\n")
    );
}

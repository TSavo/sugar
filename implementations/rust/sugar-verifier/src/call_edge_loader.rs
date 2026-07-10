// Call-edge helpers. Solve does **not** WalkDir `*.call-edges.json`
// (#3809 cut #3): discharge uses pool bridges + `enumerate_callsites`.
// `load_call_edge_files` remains a **client** helper for faces/showcases
// that still dual-write sidecars (e.g. panama mint emission checks).

use std::path::Path;

use serde_json::Value as Json;

use crate::types::MementoPool;

/// Client helper: WalkDir project for legacy `*.call-edges.json` sidecars.
/// Solve never calls this (#3809 cut #3).
pub fn load_call_edge_files(project_root: &Path) -> Vec<Json> {
    let mut edges = Vec::new();
    if !project_root.exists() {
        return edges;
    }
    for entry in walkdir::WalkDir::new(project_root)
        .follow_links(true)
        .into_iter()
        .filter_map(|e| e.ok())
    {
        if entry.file_type().is_file() {
            let fname = entry.file_name().to_string_lossy();
            if fname.ends_with(".call-edges.json") {
                if let Ok(bytes) = std::fs::read(entry.path()) {
                    if let Ok(v) = serde_json::from_slice::<Json>(&bytes) {
                        if let Some(arr) = v.get("edges").and_then(|e| e.as_array()) {
                            edges.extend(arr.iter().cloned());
                        }
                    }
                }
            }
        }
    }
    edges
}

/// Process call edges against the contract pool, resolving
/// target symbols and producing (source_cid, target_cid, locus) triples.
pub fn process_call_edges(
    edges: &[Json],
    pool: &MementoPool,
) -> Vec<(String, String, Option<Json>)> {
    let mut obligations = Vec::new();

    for edge in edges {
        let source_cid = edge
            .get("sourceContractCid")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let locus = edge.get("callSiteLocus").cloned();

        if source_cid.is_empty() {
            continue;
        }

        // Prefer a direct targetContractCid (CID-as-identity) before
        // falling back to symbol/name resolution. Direct CID is the
        // strong identity per the substrate's content-address principle;
        // name-based lookup is the lossy fallback used when the lifter
        // didn't resolve to a CID at extraction time.
        if let Some(tcid) = edge.get("targetContractCid").and_then(|v| v.as_str()) {
            if !tcid.is_empty() {
                obligations.push((source_cid.to_string(), tcid.to_string(), locus));
                continue;
            }
        }

        let target_symbol = edge
            .get("targetSymbol")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if target_symbol.is_empty() {
            continue;
        }

        let target_contract_name = if let Some(pos) = target_symbol.find(':') {
            &target_symbol[pos + 1..]
        } else {
            target_symbol
        };

        let target_cid = pool.name_to_cid.get(target_contract_name).cloned();

        if let Some(tcid) = target_cid {
            obligations.push((source_cid.to_string(), tcid.to_string(), locus));
        }
    }

    obligations
}

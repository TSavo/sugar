// SPDX-License-Identifier: Apache-2.0
//
// `?` operator detection (#383, Tier 2.4).
//
// The `?` operator desugars in MIR to:
//   1. Call to `Try::branch(x)` returning `ControlFlow<Residual, Continue>`.
//   2. `Switch::Match` on the ControlFlow's discriminant:
//        Continue arm: extracts the value, body falls through.
//        Break arm:    calls `from_residual`, returns early.
//
// Detection: a `Switch` whose payload is `Match` (3-element array
// `[discr_place, continue_block, break_block]` in Charon's encoding)
// where the discriminant traces back to a `Call` whose callee's name
// path ends in `Ident("branch")` (the Try-trait method).
//
// What we emit
//   - `Effect::EarlyReturn { try_cid }` with the JCS-byte BLAKE3-512
//     hash of the Switch::Match block. The substrate refuses
//     composition until a `TryBranchMemento` keyed by this try_cid
//     supplies the success-path / failure-path contract pair.
//
// What we DON'T do
//   - Lift any predicate atoms about the value. The caller may pass
//     any Result/Option; the success-path predicate is "x was Ok / x
//     was Some" which is the memento's job to encode.

use serde_json::Value;

use crate::canonical::{cid_of_value, serde_to_canonical};

/// One detected Try-branch (`?`) site in a function body.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TryBranchFingerprint {
    /// Content-addressed hash of the Switch::Match block.
    pub try_cid: String,
}

/// Walk a body's statements, returning a fingerprint for every Try-
/// branch site. Walks recursively into Switch::If branches, Loop
/// bodies, and Switch::Match arms (yes — nested `?` inside a match
/// arm). Source order.
pub fn extract_try_branches(
    stmts: &[&Value],
    fun_decls: Option<&Value>,
) -> Vec<TryBranchFingerprint> {
    let mut out = Vec::new();
    for s in stmts {
        collect_try_in_stmt(s, fun_decls, stmts, &mut out);
    }
    out
}

fn collect_try_in_stmt(
    stmt: &Value,
    fun_decls: Option<&Value>,
    siblings: &[&Value],
    out: &mut Vec<TryBranchFingerprint>,
) {
    let Some(kind) = stmt.get("kind") else {
        return;
    };

    if let Some(switch) = kind.get("Switch") {
        if let Some(match_arr) = switch.get("Match").and_then(|v| v.as_array()) {
            if match_arr.len() >= 2 {
                let discr_place = &match_arr[0];
                if discr_traces_to_try_branch(discr_place, siblings, fun_decls) {
                    let canonical = serde_to_canonical(stmt.clone());
                    out.push(TryBranchFingerprint {
                        try_cid: cid_of_value(&canonical),
                    });
                }
            }
            // Recurse into match arm blocks (a nested ? could appear
            // in a continue-arm body).
            for arm in match_arr.iter().skip(1) {
                if let Some(stmts) = arm.get("statements").and_then(|s| s.as_array()) {
                    let collected: Vec<&Value> = stmts.iter().collect();
                    for s in &collected {
                        collect_try_in_stmt(s, fun_decls, &collected, out);
                    }
                }
            }
            return;
        }
        // Switch::If — recurse into both branches.
        if let Some(if_arr) = switch.get("If").and_then(|v| v.as_array()) {
            if if_arr.len() == 3 {
                recurse_block(&if_arr[1], fun_decls, out);
                recurse_block(&if_arr[2], fun_decls, out);
            }
        }
        // Switch::SwitchInt — recurse into arm blocks + otherwise.
        if let Some(si) = switch.get("SwitchInt").and_then(|v| v.as_array()) {
            if si.len() == 4 {
                if let Some(arms) = si[2].as_array() {
                    for arm in arms {
                        if let Some(arr) = arm.as_array() {
                            if arr.len() == 2 {
                                recurse_block(&arr[1], fun_decls, out);
                            }
                        }
                    }
                }
                recurse_block(&si[3], fun_decls, out);
            }
        }
    }
    // Recurse into Loop bodies.
    if let Some(loop_block) = kind.get("Loop") {
        recurse_block(loop_block, fun_decls, out);
    }
}

fn recurse_block(block: &Value, fun_decls: Option<&Value>, out: &mut Vec<TryBranchFingerprint>) {
    if let Some(inner) = block.get("statements").and_then(|s| s.as_array()) {
        let collected: Vec<&Value> = inner.iter().collect();
        for s in &collected {
            collect_try_in_stmt(s, fun_decls, &collected, out);
        }
    }
}

/// True when the discriminant Place traces back to a Local whose
/// most recent assignment is a `Call` to a function whose path
/// contains `Ident("branch")`. That's the Try-branch shape Charon
/// emits for `?`.
fn discr_traces_to_try_branch(
    discr_place: &Value,
    siblings: &[&Value],
    fun_decls: Option<&Value>,
) -> bool {
    let Some(local) = discr_place
        .get("kind")
        .and_then(|k| k.get("Local"))
        .and_then(|v| v.as_u64())
        .map(|n| n as u32)
    else {
        return false;
    };
    // Find the most recent Call statement whose dest is `local`.
    for s in siblings.iter().rev() {
        let Some(kind) = s.get("kind") else {
            continue;
        };
        let Some(call) = kind.get("Call") else {
            continue;
        };
        let dest_local = call
            .get("dest")
            .and_then(|d| d.get("kind"))
            .and_then(|k| k.get("Local"))
            .and_then(|v| v.as_u64())
            .map(|n| n as u32);
        if dest_local != Some(local) {
            continue;
        }
        // Found the producing Call. Check if the callee's name path
        // ends in Ident("branch") — the Try-trait method.
        let Some(func_id) = call
            .get("func")
            .and_then(|f| f.get("Regular"))
            .and_then(|r| r.get("kind"))
            .and_then(|k| k.get("Fun"))
            .and_then(|f| f.get("Regular"))
            .and_then(|v| v.as_u64())
        else {
            return false;
        };
        return callee_is_try_branch(func_id, fun_decls);
    }
    false
}

fn callee_is_try_branch(func_id: u64, fun_decls: Option<&Value>) -> bool {
    let Some(fun_decls) = fun_decls else {
        return false;
    };
    let Some(arr) = fun_decls.as_array() else {
        return false;
    };
    let Some(decl) = arr
        .iter()
        .find(|d| d.get("def_id").and_then(|v| v.as_u64()) == Some(func_id))
    else {
        return false;
    };
    let Some(elems) = decl
        .get("item_meta")
        .and_then(|m| m.get("name"))
        .and_then(|n| n.as_array())
    else {
        return false;
    };
    // Look at the LAST Ident in the path.
    elems
        .iter()
        .rev()
        .find_map(|e| e.get("Ident").and_then(|v| v.as_array()))
        .and_then(|arr| arr.first())
        .and_then(|v| v.as_str())
        .is_some_and(|s| s == "branch")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::llbc::LlbcCrate;

    fn fixture_path(name: &str) -> std::path::PathBuf {
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests")
            .join("fixtures")
            .join(name)
    }

    #[test]
    fn extracts_try_branch_from_question_op_fixture() {
        // The question_op.llbc fixture contains `let v = x?;` which
        // desugars to a Try::branch call + Switch::Match. Detection
        // should yield exactly one fingerprint.
        let krate = LlbcCrate::from_path(fixture_path("question_op.llbc")).unwrap();
        let f = krate.function_by_name("f").unwrap();
        let fun_decls = krate.raw_translated().and_then(|t| t.get("fun_decls"));
        let stmts: Vec<&Value> = f.statements().map(|s| s.raw()).collect();
        let tries = extract_try_branches(&stmts, fun_decls);
        assert!(
            !tries.is_empty(),
            "question_op fixture must have at least one Try-branch site"
        );
        for t in &tries {
            assert!(t.try_cid.starts_with("blake3-512:"));
        }
    }

    #[test]
    fn no_try_branches_in_loopless_clean_fixture() {
        let krate = LlbcCrate::from_path(fixture_path("clean.llbc")).unwrap();
        let f = krate.function_by_name("f").unwrap();
        let fun_decls = krate.raw_translated().and_then(|t| t.get("fun_decls"));
        let stmts: Vec<&Value> = f.statements().map(|s| s.raw()).collect();
        let tries = extract_try_branches(&stmts, fun_decls);
        assert!(tries.is_empty());
    }
}

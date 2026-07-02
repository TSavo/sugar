// SPDX-License-Identifier: Apache-2.0
//
// LLBC loop detection + content-addressing (#383, Tier 1.3).
//
// Paper 07 §11 frames loops as deferred proof obligations: the lifter
// detects the loop, content-addresses its body shape (`loop_cid`), and
// stops. A separate `LoopInvariantMemento` keyed by `loop_cid` carries
// the user-supplied (or inference-tool-supplied) invariant + decreasing
// function, and the substrate's verifier discharges the three Hoare
// conditions (entry, preservation, exit) against that memento. The
// lifter never silently assumes a loop is well-behaved.
//
// What this module does
//   - `extract_loops(stmts)`: walk the body's statement list (and
//     recurse into nested blocks) finding every `StatementKind::Loop`.
//   - `loop_cid(loop_block)`: compute the JCS-byte BLAKE3-512 hash of
//     the loop's LLBC block. This is the same canonicalizer the
//     substrate uses everywhere; the loop_cid is a stable, hash-
//     equivalent identifier for the loop's body shape.
//
// What it doesn't do (intentionally)
//   - It does NOT compute or supply the loop invariant. That is the
//     LoopInvariantMemento's job; the lifter's only role is to detect
//     the loop, hash its body, and emit `Effect::OpaqueLoop` so the
//     substrate refuses composition until the invariant lands.
//   - It does NOT lift any predicate atoms FROM inside the loop body.
//     Asserts inside the loop (panic-on-overflow, etc.) hold per
//     iteration — they're part of the invariant, not the function's
//     entry-level pre. Conservative: skip them at the function level.

use serde_json::Value;

use crate::canonical::{cid_of_value, serde_to_canonical};
use crate::locus::Locus;

/// One detected loop in a function body.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LoopFingerprint {
    /// Content-addressed hash of the loop's LLBC body block.
    pub loop_cid: String,
    /// Source location of the loop (when available from the block's span).
    pub locus: Locus,
}

/// Walk a body's statements, returning a fingerprint for every Loop
/// statement encountered (including ones nested inside Switch::If
/// branches and other structured control-flow). Order is source-order.
pub fn extract_loops(stmts: &[&Value]) -> Vec<LoopFingerprint> {
    let mut out = Vec::new();
    for s in stmts {
        collect_loops_in_stmt(s, &mut out);
    }
    out
}

fn collect_loops_in_stmt(stmt: &Value, out: &mut Vec<LoopFingerprint>) {
    let Some(kind) = stmt.get("kind") else {
        return;
    };

    if let Some(loop_block) = kind.get("Loop") {
        out.push(LoopFingerprint {
            loop_cid: loop_cid(loop_block),
            locus: locus_of_block(loop_block),
        });
        // Recurse: a Loop body can contain nested Loops.
        if let Some(inner) = loop_block.get("statements").and_then(|s| s.as_array()) {
            for s in inner {
                collect_loops_in_stmt(s, out);
            }
        }
        return;
    }

    // Recurse into Switch::If's two branches and Switch::SwitchInt's
    // arms, since loops can hide inside conditional branches.
    if let Some(switch) = kind.get("Switch") {
        if let Some(if_arr) = switch.get("If").and_then(|v| v.as_array()) {
            if if_arr.len() == 3 {
                recurse_block(&if_arr[1], out);
                recurse_block(&if_arr[2], out);
            }
        }
        if let Some(si) = switch.get("SwitchInt").and_then(|v| v.as_array()) {
            // Shape: [discr, lit_ty, arms, otherwise_block]
            if si.len() == 4 {
                if let Some(arms) = si[2].as_array() {
                    for arm in arms {
                        if let Some(arr) = arm.as_array() {
                            if arr.len() == 2 {
                                recurse_block(&arr[1], out);
                            }
                        }
                    }
                }
                recurse_block(&si[3], out);
            }
        }
    }
}

fn recurse_block(block: &Value, out: &mut Vec<LoopFingerprint>) {
    if let Some(inner) = block.get("statements").and_then(|s| s.as_array()) {
        for s in inner {
            collect_loops_in_stmt(s, out);
        }
    }
}

/// Content-address a loop's body block. The full block (span +
/// statements) is JCS-canonicalized and hashed. Two loops with
/// byte-equal LLBC bodies share a loop_cid; inference tools and
/// invariant authors can supply ONE LoopInvariantMemento that
/// applies to every byte-equal occurrence.
pub fn loop_cid(loop_block: &Value) -> String {
    let canonical = serde_to_canonical(loop_block.clone());
    cid_of_value(&canonical)
}

/// Best-effort source locus from a block's `span` field. Returns
/// `Locus::unknown()` when the span is absent or malformed (charon
/// always emits one for real code; the unknown fallback covers
/// hand-built test fixtures).
fn locus_of_block(block: &Value) -> Locus {
    let Some(span) = block.get("span") else {
        return Locus::unknown();
    };
    let data = match span.get("data") {
        Some(data) => data,
        None => span,
    };
    let beg = data.get("beg");
    let line = match beg.and_then(|b| b.get("line")).and_then(|v| v.as_u64()) {
        Some(line) => line as usize,
        None => 0,
    };
    let col = match beg.and_then(|b| b.get("col")).and_then(|v| v.as_u64()) {
        Some(col) => col as usize,
        None => 0,
    };
    let file = data
        .get("file_id")
        .and_then(|v| v.as_u64())
        .map(|id| format!("file:{}", id));
    Locus { file, line, col }
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
    fn extracts_one_loop_from_while_loop_fixture() {
        let krate = LlbcCrate::from_path(fixture_path("loops.llbc")).unwrap();
        let f = krate.function_by_name("s").expect("s present");
        let stmts: Vec<&Value> = f.statements().map(|st| st.raw()).collect();
        let loops = extract_loops(&stmts);
        assert_eq!(loops.len(), 1, "while-loop produces one fingerprint");
        let lp = &loops[0];
        assert!(
            lp.loop_cid.starts_with("blake3-512:"),
            "loop_cid is well-formed: {}",
            lp.loop_cid
        );
        // Span should be non-zero — the loop was emitted from real source.
        assert!(lp.locus.line > 0, "locus carries real line: {:?}", lp.locus);
    }

    #[test]
    fn loop_cid_is_deterministic_across_calls() {
        let krate = LlbcCrate::from_path(fixture_path("loops.llbc")).unwrap();
        let f = krate.function_by_name("s").unwrap();
        let stmts: Vec<&Value> = f.statements().map(|st| st.raw()).collect();
        let a = extract_loops(&stmts);
        let b = extract_loops(&stmts);
        assert_eq!(a.len(), b.len());
        assert_eq!(a[0].loop_cid, b[0].loop_cid);
    }

    #[test]
    fn extracts_no_loops_from_loopless_function() {
        // The `clean.llbc` fixture has no loops — only an if-panic.
        let krate = LlbcCrate::from_path(fixture_path("clean.llbc")).unwrap();
        let f = krate.function_by_name("f").unwrap();
        let stmts: Vec<&Value> = f.statements().map(|st| st.raw()).collect();
        let loops = extract_loops(&stmts);
        assert!(loops.is_empty(), "loopless function: empty result");
    }
}

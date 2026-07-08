// SPDX-License-Identifier: MIT OR Apache-2.0
//
// The forbidden arrows (SEAM 0). Part 1 of the compiler-shape plan:
// the guard encodes the ACTUAL baseline (linker -> verifier is real and
// ALLOWED) and forbids the specific edges that would invert the DAG:
//
//   sugar-canonicalizer, sugar-ir-types            (leaves)
//           ^
//   sugar-proof-envelope   (ProofGraph data + feed/write/read)
//           ^
//   libsugar               (rendezvous engine, membrane; the calculus)
//           ^
//   sugar-verifier         (discharge)
//           ^
//   sugar-linker           (bind; linker -> verifier is a REAL allowed edge)
//           ^
//   sugar-compiler         (Kit + sign/solve + Outcome; future top)
//           ^
//   sugar-cli faces        (thin client)
//
// Every assertion here is a claim against the code, recomputed per run.

use sugar_arch_guard::{closure, dependents_of, direct_graph};

/// libsugar is the engine floor: it may depend on NOTHING above it.
/// Exact allowlist (the strongest honest baseline): adding a new downward
/// dep is a conscious edit here, never an accident.
#[test]
fn libsugar_closure_is_exactly_the_floor() {
    let graph = direct_graph();
    let reach = closure(&graph, "libsugar");
    let allowed = [
        "sugar-canonicalizer",
        "sugar-proof-envelope",
        "sugar-ir-types",
    ];
    let violations: Vec<&String> = reach
        .iter()
        .filter(|c| !allowed.contains(&c.as_str()))
        .collect();
    assert!(
        violations.is_empty(),
        "libsugar's dependency closure climbed above the floor: {violations:?}. \
         libsugar must never depend on the verifier, the linker, a kit, an \
         oracle, or a face. If this new edge is genuinely downward, add it to \
         the allowlist in this test with a comment saying why."
    );
}

/// The #3833 pull-back hazard and the D4 cycle, named as their own test so a
/// violation reads as what it is, not as an allowlist diff.
#[test]
fn libsugar_never_reaches_verifier_or_linker() {
    let graph = direct_graph();
    let reach = closure(&graph, "libsugar");
    for forbidden in ["sugar-verifier", "sugar-linker"] {
        assert!(
            !reach.contains(forbidden),
            "FORBIDDEN ARROW: libsugar -> {forbidden}. This inverts the \
             compiler DAG (verifier/linker sit ABOVE libsugar; the reverse \
             edge is the D4 cycle). Invert the dependency: define a trait in \
             libsugar and inject the concrete impl from above."
        );
    }
}

/// sugar-proof-envelope is the leaf home of the ProofGraph currency.
/// It reaches only the canonicalizer. A leaf stays a leaf.
#[test]
fn proof_envelope_stays_a_leaf() {
    let graph = direct_graph();
    let reach = closure(&graph, "sugar-proof-envelope");
    let extra: Vec<&String> = reach
        .iter()
        .filter(|c| c.as_str() != "sugar-canonicalizer")
        .collect();
    assert!(
        extra.is_empty(),
        "sugar-proof-envelope grew arrows above the canonicalizer: {extra:?}. \
         The currency's home must not depend on the machinery that consumes it."
    );
}

/// The canonicalizer is the bottom: zero workspace dependencies.
#[test]
fn canonicalizer_is_the_bottom() {
    let graph = direct_graph();
    let reach = closure(&graph, "sugar-canonicalizer");
    assert!(
        reach.is_empty(),
        "sugar-canonicalizer must have no workspace dependencies, found: {reach:?}"
    );
}

/// The baseline is REAL, not a fiction: linker -> verifier is a live edge
/// today and is ALLOWED. This test documents it so nobody "fixes" it and so
/// the guard fails loudly if the architecture around it silently changes.
#[test]
fn baseline_linker_depends_on_verifier() {
    let graph = direct_graph();
    assert!(
        closure(&graph, "sugar-linker").contains("sugar-verifier"),
        "baseline drift: sugar-linker no longer reaches sugar-verifier. If \
         this was deliberate (the discharge moved), update the plan and this \
         guard together."
    );
}

/// sugar-compiler (when it lands in SEAM 1) is a strict top under the faces:
/// nothing below it may ever depend on it. Written now so the rule is armed
/// the moment the crate appears.
#[test]
fn no_back_edges_into_sugar_compiler() {
    let graph = direct_graph();
    if !graph.contains_key("sugar-compiler") {
        return; // not born yet; rule arms itself on arrival
    }
    let faces = ["sugar-cli", "sugar-lsp", "sugar-lsp-rust"];
    let dependents = dependents_of(&graph, "sugar-compiler");
    let violations: Vec<&String> = dependents
        .iter()
        .filter(|c| !faces.contains(&c.as_str()))
        .collect();
    assert!(
        violations.is_empty(),
        "FORBIDDEN BACK-EDGE into sugar-compiler from below: {violations:?}. \
         Only faces (thin clients) may depend on the compiler crate."
    );
}

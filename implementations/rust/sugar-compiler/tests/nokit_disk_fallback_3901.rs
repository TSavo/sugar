// SPDX-License-Identifier: MIT OR Apache-2.0
//
// #3901 residual instrument: disk prove face requires an explicit NoKit witness.
//
// Law: `sugar prove` may load disk `.proof` only after constructing a named
// [`NoKit`] reason. Silent `Option<Kit>::None` → `solve_project` is the
// illegal shape — it loses whether the fold path was never chosen, skipped,
// or failed. Replacement: `ProveFace::{Kit, Disk(NoKit)}` exhaustive match.
//
// Axes (measured live; red while any > 0):
//   R_silent_option_kit_face  — try_rendezvous_prove_kit / Option<Kit> face
//   R_disk_without_nokit      — solve_project on prove path without NoKit/Disk
//   R_missing_prove_face      — resolve_prove_face / ProveFace types gone

use std::fs;
use std::path::{Path, PathBuf};

fn rust_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("sugar-compiler under implementations/rust")
        .to_path_buf()
}

fn read_rel(root: &Path, rel: &str) -> String {
    fs::read_to_string(root.join(rel)).unwrap_or_else(|e| panic!("read {rel}: {e}"))
}

fn production_half(src: &str) -> &str {
    // Strip unit-test module so instrument greps only the production face.
    src.split("#[cfg(test)]").next().unwrap_or(src)
}

#[derive(Debug)]
struct Offender {
    axis: &'static str,
    detail: String,
    replacement: &'static str,
}

#[test]
fn r_silent_disk_fallback_is_zero() {
    let root = rust_root();
    let rel = "sugar-cli/src/cmd_prove.rs";
    let full = read_rel(&root, rel);
    let production = production_half(&full);

    let mut offenders: Vec<Offender> = Vec::new();

    // Illegal face: Option-returning rendezvous that the caller maps None→disk.
    if production.contains("try_rendezvous_prove_kit") {
        offenders.push(Offender {
            axis: "R_silent_option_kit_face",
            detail: "try_rendezvous_prove_kit still present in production face".into(),
            replacement: "resolve_prove_face → ProveFace::{Kit, Disk(NoKit)}; no Option kit face",
        });
    }
    if production.contains("-> Option<sugar_compiler::kit::Kit>")
        || production.contains("-> Option<Kit>")
    {
        offenders.push(Offender {
            axis: "R_silent_option_kit_face",
            detail: "Option<Kit> prove face still present".into(),
            replacement: "ProveFace::Disk(NoKit) is the only disk constructor",
        });
    }
    // if let Some(kit) = ... else { solve_project } is the silent-loss shape.
    if production.contains("if let Some(kit)") && production.contains("solve_project") {
        offenders.push(Offender {
            axis: "R_silent_option_kit_face",
            detail: "if let Some(kit) … else solve_project still present".into(),
            replacement:
                "match resolve_prove_face { Kit => prove_from_kit, Disk(n) => solve_project }",
        });
    }

    // Required architecture: named witness + exhaustive face.
    if !production.contains("enum NoKit") {
        offenders.push(Offender {
            axis: "R_disk_without_nokit",
            detail: "NoKit witness type missing from production prove path".into(),
            replacement: "enum NoKit { NoLiftSurface, MultiSurface, EmptyCommand, … }",
        });
    }
    if !production.contains("ProveFace::Disk") {
        offenders.push(Offender {
            axis: "R_disk_without_nokit",
            detail: "production prove path never matches ProveFace::Disk".into(),
            replacement: "Disk(NoKit) arm is the only door to solve_project on prove",
        });
    }
    if !production.contains("resolve_prove_face") {
        offenders.push(Offender {
            axis: "R_missing_prove_face",
            detail: "resolve_prove_face missing".into(),
            replacement: "one constructor that returns ProveFace, never Option",
        });
    }
    if !production.contains("enum ProveFace") {
        offenders.push(Offender {
            axis: "R_missing_prove_face",
            detail: "ProveFace enum missing".into(),
            replacement: "enum ProveFace { Kit(Kit), Disk(NoKit) }",
        });
    }

    // Disk arm must still call the one production solve door (sugar#3859).
    if !production.contains("solve_project") {
        offenders.push(Offender {
            axis: "R_disk_without_nokit",
            detail: "cmd_prove lost solve_project disk face entirely".into(),
            replacement: "ProveFace::Disk(_) => orchestrate::solve_project(...)",
        });
    }
    if !production.contains("prove_from_kit") {
        offenders.push(Offender {
            axis: "R_missing_prove_face",
            detail: "cmd_prove lost prove_from_kit kit face".into(),
            replacement: "ProveFace::Kit(k) => orchestrate::prove_from_kit(...)",
        });
    }

    // Multi-surface must not first-match into a single Kit (prior first-match residual).
    // Production path constructs MultiSurface from slice match, not .first().
    let multi_surface_named = production.contains("MultiSurface");
    if !multi_surface_named {
        offenders.push(Offender {
            axis: "R_silent_option_kit_face",
            detail: "NoKit::MultiSurface missing — multi-surface may first-match".into(),
            replacement:
                "match lift_manifests { [] => NoLiftSurface, [one] => …, many => MultiSurface }",
        });
    }

    let r = offenders.len();
    eprintln!("#3901 NoKit disk-fallback membrane on {rel}");
    for o in &offenders {
        eprintln!(
            "  offender axis={} detail={} replacement={}",
            o.axis, o.detail, o.replacement
        );
    }
    eprintln!("R_silent_disk_fallback={r}");
    assert!(
        r == 0,
        "R_silent_disk_fallback={r} — disk prove requires explicit NoKit witness (#3901). \
         Silent Option::None → solve_project is the illegal shape. \
         Replacement: match resolve_prove_face(...) {{ Kit(k) => prove_from_kit, Disk(n) => solve_project }}."
    );
}

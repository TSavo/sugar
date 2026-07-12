use std::path::PathBuf;
use std::process::Command;

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

#[test]
fn construction_gap_continuation_requires_audit_frontier() {
    let rejected = Command::new(sugar_bin())
        .args(["lift", "--continue-on-construction-gaps"])
        .output()
        .expect("spawn sugar lift");
    assert!(!rejected.status.success());
    assert!(String::from_utf8_lossy(&rejected.stderr).contains("--audit-frontier"));
}

#[test]
fn audit_frontier_rejects_completed_lift_modes() {
    for completed_mode in ["--report", "--identify-only", "--library-bindings"] {
        let output = Command::new(sugar_bin())
            .args([
                "lift",
                "--audit-frontier",
                "--continue-on-construction-gaps",
                completed_mode,
            ])
            .output()
            .expect("spawn sugar lift");
        assert!(!output.status.success(), "accepted {completed_mode}");
    }
}

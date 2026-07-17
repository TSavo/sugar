use std::path::PathBuf;
use std::process::Command;

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

#[test]
fn allowed_broken_components_requires_audit_frontier() {
    let rejected = Command::new(sugar_bin())
        .args(["lift", "--allowed-broken-components", "python"])
        .output()
        .expect("spawn sugar lift");
    assert!(!rejected.status.success());
    assert!(String::from_utf8_lossy(&rejected.stderr).contains("--audit-frontier"));
}

#[test]
fn audit_frontier_requires_explicit_continue_override() {
    // #4203: recovery inventory needs the named override flag, not only the
    // kit allow-list. Silent/config recovery remains impossible.
    let rejected = Command::new(sugar_bin())
        .args([
            "lift",
            "--audit-frontier",
            "--allowed-broken-components",
            "python",
        ])
        .output()
        .expect("spawn sugar lift");
    assert!(!rejected.status.success());
    let stderr = String::from_utf8_lossy(&rejected.stderr);
    assert!(
        stderr.contains("--continue-on-construction-gaps"),
        "stderr={stderr}"
    );
}

#[test]
fn audit_frontier_rejects_completed_lift_modes() {
    for completed_mode in ["--report", "--identify-only", "--library-bindings"] {
        let output = Command::new(sugar_bin())
            .args([
                "lift",
                "--audit-frontier",
                "--continue-on-construction-gaps",
                "--allowed-broken-components",
                "python",
                completed_mode,
            ])
            .output()
            .expect("spawn sugar lift");
        assert!(!output.status.success(), "accepted {completed_mode}");
    }
}

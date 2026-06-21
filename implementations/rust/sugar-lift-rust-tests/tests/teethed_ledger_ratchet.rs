//! Teethed-ledger RATCHET (AGENTS.md stable-zero discipline).
//!
//! Pins the checked-in discharge numbers over the coretests corpus and asserts
//! the next run is STRICTLY BETTER — the instrument that turns "maximize proven,
//! drive fake dragons to zero" from hand-tracking into a test that goes RED the
//! moment a PR regresses the count.
//!
//! Ratchet direction (tighten the threshold IN THE SAME PR when a number moves):
//!   * `discharged   >= DISCHARGED_FLOOR`  — proven obligations only grow.
//!   * `refuted      <= REFUTED_CEIL`      — false refutations (the corpus is
//!       all TRUE assertions, so every `refuted` is a fake dragon) only shrink.
//!       TARGET 0.
//!   * `undecided    <= UNDECIDED_CEIL`    — the no-teeth bucket only shrinks.
//! NEVER loosen a ratchet the wrong way except in an explicit accounting-correction
//! PR (e.g. surfacing a panic-path-filtered value-teethedness reclassifies the split).
//!
//! `#[ignore]` by default: it runs the full corpus sweep (~5 min) and needs the
//! release `discharge_sweep` binary + z3. The ledger lane runs it explicitly:
//!   cargo test -p sugar-lift-rust-tests --test teethed_ledger_ratchet -- --ignored
//! It SKIPS (passes) when the binary, corpus, or z3 are absent — never a spurious red.

use std::path::PathBuf;

// ── Pinned thresholds (current main; tighten in-PR when a number improves). ──
const DISCHARGED_FLOOR: u64 = 138; // proven (teeth) — must not regress
const REFUTED_CEIL: u64 = 49; // false refutations (all-true corpus) — drive to 0
const UNDECIDED_CEIL: u64 = 4854; // congruence-only / no teeth — drive down

fn rust_dir() -> PathBuf {
    // CARGO_MANIFEST_DIR = <repo>/implementations/rust/sugar-lift-rust-tests
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf()
}

#[test]
#[ignore = "full-corpus sweep (~5 min) + release binary + z3; run in the ledger lane with --ignored"]
fn teethed_ledger_does_not_regress() {
    let rust = rust_dir();
    let bin = rust.join("target/release/discharge_sweep");
    let corpus = rust
        .parent()
        .unwrap()
        .join("examples/rust-coretests-report/corpus");
    let z3 = "/usr/local/bin/z3";
    if !bin.exists() || !corpus.is_dir() || !std::path::Path::new(z3).exists() {
        eprintln!(
            "teethed ratchet SKIPPED (bin={} corpus={} z3={})",
            bin.exists(),
            corpus.is_dir(),
            std::path::Path::new(z3).exists()
        );
        return;
    }

    let json = std::env::temp_dir().join("teethed_ratchet.json");
    let status = std::process::Command::new(&bin)
        .arg(&corpus)
        .arg("--json")
        .arg(&json)
        .stderr(std::process::Stdio::null())
        .status()
        .expect("run discharge_sweep");
    assert!(status.success(), "discharge_sweep exited non-zero");

    let doc: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&json).expect("read teethed json"))
            .expect("parse teethed json");
    let t = &doc["teethed_ledger"];
    let get = |k: &str| t[k].as_u64().unwrap_or_else(|| panic!("missing {k}: {t}"));
    let (discharged, refuted, undecided, warranted) = (
        get("discharged"),
        get("refuted"),
        get("undecided"),
        get("warranted_obligations"),
    );
    eprintln!(
        "teethed ledger: warranted={warranted} discharged={discharged} refuted={refuted} undecided={undecided}"
    );

    assert!(
        discharged >= DISCHARGED_FLOOR,
        "RATCHET REGRESSION: discharged {discharged} < floor {DISCHARGED_FLOOR} (proven obligations dropped). \
         If this is a legitimate accounting correction, lower the floor in THIS pr with a reason."
    );
    assert!(
        refuted <= REFUTED_CEIL,
        "RATCHET REGRESSION: refuted {refuted} > ceil {REFUTED_CEIL} (NEW false refutation -- a fake dragon, \
         inverse cardinal sin). The corpus is all-true; every refutation is a stale/wrong lift."
    );
    assert!(
        undecided <= UNDECIDED_CEIL,
        "RATCHET REGRESSION: undecided {undecided} > ceil {UNDECIDED_CEIL} (no-teeth bucket grew)."
    );

    // Tighten-in-PR reminder: when a number beats its threshold, move the const.
    if discharged > DISCHARGED_FLOOR || refuted < REFUTED_CEIL || undecided < UNDECIDED_CEIL {
        eprintln!(
            "RATCHET IMPROVED -- tighten thresholds in this PR: \
             DISCHARGED_FLOOR {DISCHARGED_FLOOR}->{discharged}, REFUTED_CEIL {REFUTED_CEIL}->{refuted}, \
             UNDECIDED_CEIL {UNDECIDED_CEIL}->{undecided}"
        );
    }
}

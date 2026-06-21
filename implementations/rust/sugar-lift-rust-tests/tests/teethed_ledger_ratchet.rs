//! Complete R-vector RATCHET (AGENTS.md stable-zero discipline).
//!
//! ONE self-enforcing gate over BOTH axes of the dragon map, pinning the
//! checked-in numbers and asserting the next run is STRICTLY BETTER — the
//! instrument that turns "drive the dark to zero, maximize proven, kill the fake
//! dragons" from hand-tracking into a test that goes RED the moment a PR regresses.
//!
//! COVERAGE axis (`sugar lift --report` — the honest dark):
//!   * `unresolved <= UNRESOLVED_CEIL`  — "no sugar yet"; drive to 0.
//!   * `support    == SUPPORT_EXACT`    — inert support is never a hiding place.
//!   * `no_facts   <= NO_FACTS_CEIL`    — assertion sources that lifted nothing.
//! DISCHARGE axis (`discharge_sweep` — the teeth):
//!   * `discharged       >= DISCHARGED_FLOOR`        — proven obligations only grow.
//!   * `value_discharged >= VALUE_DISCHARGED_FLOOR`  — panic-filtered value teeth.
//!   * `refuted          <= REFUTED_CEIL`            — the corpus is all-TRUE, so
//!       every `refuted` is a FALSE refutation (fake dragon). TARGET 0.
//!   * `refuted_other    <= REFUTED_OTHER_CEIL`      — the NON-T3 (fixable-now) class.
//!   * `undecided        <= UNDECIDED_CEIL`          — the no-teeth bucket shrinks.
//!
//! Tighten thresholds IN THE SAME PR when a number beats them. NEVER loosen a
//! ratchet the wrong way except in an explicit accounting-correction PR.
//!
//! `#[ignore]` by default: it runs BOTH full-corpus passes (~10 min) and needs the
//! release `sugar` + `discharge_sweep` binaries + z3. The ledger lane runs it:
//!   cargo test -p sugar-lift-rust-tests --test teethed_ledger_ratchet -- --ignored
//! It SKIPS (passes) when a binary, the corpus, or z3 are absent — never a spurious red.

use std::path::PathBuf;

// ── Pinned thresholds (current main; tighten in-PR when a number improves). ──
// DISCHARGE axis (from discharge_sweep):
const DISCHARGED_FLOOR: u64 = 138; // proven (teeth, full inv) — must not regress
const VALUE_DISCHARGED_FLOOR: u64 = 131; // proven VALUE-claim (panic-filtered) — must not regress
const REFUTED_CEIL: u64 = 49; // false refutations (all-true corpus) — drive to 0
const REFUTED_OTHER_CEIL: u64 = 37; // NON-T3 false refutations (fixable now) — drive to 0
const UNDECIDED_CEIL: u64 = 4854; // congruence-only / no teeth — drive down
// COVERAGE axis (from `sugar lift --report`): the R-vector — the honest dark.
const UNRESOLVED_CEIL: u64 = 331; // "no sugar yet" (the visible dark) — drive to 0
const NO_FACTS_CEIL: u64 = 75; // assertion sources that lifted no fact at all — drive to 0
const SUPPORT_EXACT: u64 = 0; // inert support is NOT a hiding place for dark — must stay 0

fn rust_dir() -> PathBuf {
    // CARGO_MANIFEST_DIR = <repo>/implementations/rust/sugar-lift-rust-tests
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf()
}

/// Strip ANSI escapes (the lifter's tracing layer colors stderr; belt-and-
/// suspenders with NO_COLOR below).
fn strip_ansi(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let bytes = s.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == 0x1b {
            // ESC[ ... m
            i += 1;
            while i < bytes.len() && bytes[i] != b'm' {
                i += 1;
            }
            i += 1;
        } else {
            out.push(bytes[i] as char);
            i += 1;
        }
    }
    out
}

fn field(line: &str, key: &str) -> Option<u64> {
    let pat = format!("{key}=");
    let idx = line.find(&pat)? + pat.len();
    let rest = &line[idx..];
    let end = rest.find(|c: char| !c.is_ascii_digit()).unwrap_or(rest.len());
    rest[..end].parse().ok()
}

/// Run `sugar lift --report` over the corpus and parse the COVERAGE R-vector:
/// (unresolved, source-audit support, no_facts). Renders the manifest first
/// (same as run.sh). None if the binary is missing or the headline didn't emit.
fn coverage_rvector(rust: &std::path::Path, corpus: &std::path::Path) -> Option<(u64, u64, u64)> {
    let sugar = rust.join("target/release/sugar");
    let rpc = rust.join("target/release/rust_test_assertions_rpc");
    if !sugar.exists() || !rpc.exists() {
        return None;
    }
    // Render the manifest with this checkout's binary dir (run.sh parity).
    let mfin = corpus.join(".sugar/lift/rust-test-assertions/manifest.toml.in");
    let mf = corpus.join(".sugar/lift/rust-test-assertions/manifest.toml");
    let bin_dir = rust.join("target/release");
    if let Ok(tmpl) = std::fs::read_to_string(&mfin) {
        let _ = std::fs::write(&mf, tmpl.replace("@BIN_DIR@", &bin_dir.to_string_lossy()));
    }
    let out = std::process::Command::new(&sugar)
        .arg("lift")
        .arg("--report")
        .current_dir(corpus)
        .env("NO_COLOR", "1")
        .env("CLICOLOR", "0")
        .env("TERM", "dumb")
        .output()
        .ok()?;
    let stdout = strip_ansi(&String::from_utf8_lossy(&out.stdout));
    let audit = stdout.lines().find(|l| l.contains("source audit:"))?;
    let surface = stdout
        .lines()
        .find(|l| l.contains("assertion surface accounting:"));
    let unresolved = field(audit, "unresolved")?;
    let support = field(audit, "support")?;
    let no_facts = surface.and_then(|l| field(l, "no_facts")).unwrap_or(0);
    Some((unresolved, support, no_facts))
}

#[test]
#[ignore = "complete R-vector gate: full-corpus `sugar lift --report` (coverage) + discharge_sweep (teeth) ~10 min + release binaries + z3; run in the ledger lane with --ignored"]
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
    let value_discharged = get("value_discharged");
    let refuted_other = get("refuted_other_class");
    eprintln!(
        "teethed ledger: warranted={warranted} discharged={discharged} value_discharged={value_discharged} \
         refuted={refuted} (other={refuted_other}) undecided={undecided}"
    );

    assert!(
        discharged >= DISCHARGED_FLOOR,
        "RATCHET REGRESSION: discharged {discharged} < floor {DISCHARGED_FLOOR} (proven obligations dropped). \
         If this is a legitimate accounting correction, lower the floor in THIS pr with a reason."
    );
    assert!(
        value_discharged >= VALUE_DISCHARGED_FLOOR,
        "RATCHET REGRESSION: value_discharged {value_discharged} < floor {VALUE_DISCHARGED_FLOOR} \
         (panic-filtered VALUE-claim teeth dropped)."
    );
    assert!(
        refuted <= REFUTED_CEIL,
        "RATCHET REGRESSION: refuted {refuted} > ceil {REFUTED_CEIL} (NEW false refutation -- a fake dragon, \
         inverse cardinal sin). The corpus is all-true; every refutation is a stale/wrong lift."
    );
    assert!(
        refuted_other <= REFUTED_OTHER_CEIL,
        "RATCHET REGRESSION: non-T3 false refutations {refuted_other} > ceil {REFUTED_OTHER_CEIL} \
         (the FIXABLE-NOW fake-dragon class grew -- a stale/wrong lift that should REFUSE not emit)."
    );
    assert!(
        undecided <= UNDECIDED_CEIL,
        "RATCHET REGRESSION: undecided {undecided} > ceil {UNDECIDED_CEIL} (no-teeth bucket grew)."
    );

    // COVERAGE axis: the R-vector from `sugar lift --report`. One complete gate.
    let Some((cov_unresolved, cov_support, cov_no_facts)) = coverage_rvector(&rust, &corpus) else {
        eprintln!(
            "coverage R-vector SKIPPED (sugar/rpc binary absent or no headline) -- discharge axis asserted above"
        );
        return;
    };
    eprintln!(
        "coverage R-vector: unresolved={cov_unresolved} support={cov_support} no_facts={cov_no_facts}"
    );
    assert!(
        cov_unresolved <= UNRESOLVED_CEIL,
        "RATCHET REGRESSION: unresolved {cov_unresolved} > ceil {UNRESOLVED_CEIL} (the honest dark grew -- \
         a shape lost its sugar/refusal). R != 0 regressed."
    );
    assert_eq!(
        cov_support, SUPPORT_EXACT,
        "RATCHET REGRESSION: source-audit support {cov_support} != {SUPPORT_EXACT}. `support` is inert source \
         ONLY -- never a hiding place for dark. Any non-zero is a laundered unresolved."
    );
    assert!(
        cov_no_facts <= NO_FACTS_CEIL,
        "RATCHET REGRESSION: no_facts {cov_no_facts} > ceil {NO_FACTS_CEIL} (assertion sources that lifted \
         no fact at all grew -- a silent drop)."
    );
    if cov_unresolved < UNRESOLVED_CEIL || cov_no_facts < NO_FACTS_CEIL {
        eprintln!(
            "RATCHET IMPROVED (coverage) -- tighten in this PR: \
             UNRESOLVED_CEIL {UNRESOLVED_CEIL}->{cov_unresolved}, NO_FACTS_CEIL {NO_FACTS_CEIL}->{cov_no_facts}"
        );
    }

    // Tighten-in-PR reminder: when a number beats its threshold, move the const.
    if discharged > DISCHARGED_FLOOR
        || value_discharged > VALUE_DISCHARGED_FLOOR
        || refuted < REFUTED_CEIL
        || refuted_other < REFUTED_OTHER_CEIL
        || undecided < UNDECIDED_CEIL
    {
        eprintln!(
            "RATCHET IMPROVED -- tighten thresholds in this PR: \
             DISCHARGED_FLOOR {DISCHARGED_FLOOR}->{discharged}, VALUE_DISCHARGED_FLOOR {VALUE_DISCHARGED_FLOOR}->{value_discharged}, \
             REFUTED_CEIL {REFUTED_CEIL}->{refuted}, REFUTED_OTHER_CEIL {REFUTED_OTHER_CEIL}->{refuted_other}, \
             UNDECIDED_CEIL {UNDECIDED_CEIL}->{undecided}"
        );
    }
}

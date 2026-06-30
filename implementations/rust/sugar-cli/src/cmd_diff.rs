//! `sugar diff <BEFORE> <AFTER>`: the behavior diff between two minted proof sets.
//!
//! Everything else in the suite mints proofs. `diff` is the verb that *reads*
//! two of them and reports what changed in terms of meaning, not text.
//!
//! Two modes, same comparison:
//!   default     BEFORE and AFTER are project roots holding minted proofs.
//!   --git       BEFORE and AFTER are git revisions; the project's proofs are
//!               extracted from each revision's tree and diffed. This is the
//!               behavioral-VCS hat: "when did this last change what it does."
//!
//! Each proof set lifts to a `{contract-name -> body CID}` table. The
//! body CID is a pointer carried by the contract memento in the `.proof`
//! file, not a diff-time guess rebuilt by stripping fields out of an envelope.
//! The verdict is driven by the CID SET, not the name set, because names are
//! sugar. We invert each table to `CID -> {names}`:
//!
//!   held      a CID present both sides under the same name(s)
//!   renamed   a CID present both sides, name(s) changed (a pure rename)
//!   new       a CID only in AFTER  (genuinely new behavior, additive)
//!   lost      a CID only in BEFORE (behavior actually gone, breaking)
//!
//! Exit nonzero iff a behavior is lost. A pure rename, an implementation rewrite,
//! a reformat of the world: as long as no body pointer appears or disappears,
//! the delta is none and the gate stays green. That one exit code makes the same
//! binary a CI gate, a pre-publish hook, and an install-time supply-chain hook.

use std::collections::{BTreeMap, BTreeSet};
use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};

use clap::Args;
use sugar_proof_envelope::ProofGraph;

use crate::{EXIT_OK, EXIT_USER_ERROR, EXIT_VERIFY_FAIL};

#[derive(Args, Debug)]
pub struct DiffArgs {
    /// BEFORE: a project root, or a git revision when --git is set.
    pub before: String,
    /// AFTER: a project root, or a git revision when --git is set.
    pub after: String,
    /// Treat BEFORE and AFTER as git revisions and diff a project's proofs
    /// across history ("when did this last change what it does").
    #[arg(long)]
    pub git: bool,
    /// In --git mode, the project subdirectory within each revision's tree.
    #[arg(long, default_value = ".")]
    pub path: String,
    /// Honest-semver gate: fail unless the behavior delta fits within this bump.
    /// none < minor < major. `--require minor` rejects a MAJOR delta (a behavior
    /// loss dressed up as a non-breaking release). The pre-publish hook.
    #[arg(long, value_name = "BUMP")]
    pub require: Option<String>,
    /// Supply-chain pin: fail on ANY behavior delta. A pinned dependency must
    /// denote byte-identical behavior; new, lost, or renamed all mean it mutated
    /// under a fixed version. The install-time hook. Overrides --require.
    #[arg(long)]
    pub frozen: bool,
    /// Sweep ledger JSON for BEFORE (as written by `coretests_sweep --json`).
    /// Adds the residual axis: the gates then also see the UNPROVEN set --
    /// silent drops, proof regressions, residual movement under a pin.
    #[arg(long, value_name = "LEDGER", requires = "ledger_after")]
    pub ledger_before: Option<std::path::PathBuf>,
    /// Sweep ledger JSON for AFTER. Required with --ledger-before.
    #[arg(long, value_name = "LEDGER", requires = "ledger_before")]
    pub ledger_after: Option<std::path::PathBuf>,
    /// Output format. `markdown` emits a PR-comment block (the verdict the
    /// CI bot posts); `human` is the default terminal report. The exit code
    /// is identical either way -- the gate is the gate.
    #[arg(long, value_enum, default_value_t = DiffFormat::Human)]
    pub format: DiffFormat,
}

/// How `sugar diff` renders its verdict. The gate (exit code) is the same;
/// only the prose differs.
#[derive(Clone, Copy, Debug, PartialEq, Eq, clap::ValueEnum)]
pub enum DiffFormat {
    Human,
    Markdown,
}

/// `name -> CID`, as loaded from a proof set.
type Table = BTreeMap<String, String>;
/// `CID -> {names}`: a behavior and every contract name that denotes it.
type ByCid = BTreeMap<String, BTreeSet<String>>;

fn invert(t: &Table) -> ByCid {
    let mut m: ByCid = BTreeMap::new();
    for (name, cid) in t {
        m.entry(cid.clone()).or_default().insert(name.clone());
    }
    m
}

/// Read every `.proof` under `dir` into a behavior table (`name -> bodyCid`) by
/// asking the typed graph for its contracts. Dead dumb: `ProofGraph::read` owns
/// reconstruction; diff just reads the contracts out and tabulates them. No
/// hand-decoding, no `MementoPool` detour.
fn behavior_table_from_dir(dir: &Path) -> Result<Table, String> {
    let mut table = Table::new();
    for path in proof_files(dir) {
        let bytes = std::fs::read(&path).map_err(|e| format!("read {}: {e}", path.display()))?;
        let graph = ProofGraph::read(&bytes)
            .map_err(|e| format!("read proof graph {}: {e}", path.display()))?;
        for c in graph.contracts() {
            table.insert(c.name, c.body_cid);
        }
    }
    Ok(table)
}

/// Recursively collect `*.proof` files under `dir`.
fn proof_files(dir: &Path) -> Vec<std::path::PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&d) else {
            continue;
        };
        for entry in entries.flatten() {
            let p = entry.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.extension().and_then(|e| e.to_str()) == Some("proof") {
                out.push(p);
            }
        }
    }
    out
}

/// The behavior delta between two proof sets, keyed by CID.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct Summary {
    pub new_behaviors: u32,
    pub lost_behaviors: u32,
    pub held: u32,
    pub renamed: u32,
    pub lines: Vec<String>,
}

impl Summary {
    /// A break is exactly "a behavior that existed no longer does." A rename is
    /// not a break: the behavior is still there under a new name.
    pub fn breaking(&self) -> bool {
        self.lost_behaviors > 0
    }

    /// Neither side contained any proof: the comparison proved nothing.
    /// Mirrors `report_exit_code`'s zero-callsite rule -- silence must never
    /// read as green, or a dependency with no proofs at all passes `--frozen`.
    pub fn vacuous(&self) -> bool {
        self.held == 0 && self.renamed == 0 && self.new_behaviors == 0 && self.lost_behaviors == 0
    }

    /// The honest-semver bump the behavior delta implies.
    pub fn bump(&self) -> &'static str {
        if self.lost_behaviors > 0 {
            "MAJOR"
        } else if self.new_behaviors > 0 {
            "minor"
        } else {
            "none"
        }
    }
}

/// One side's total accounting, as read from a sweep ledger: every assertion
/// macro in the corpus, binned. `assert_macros - discharged` is the residual
/// (the dark half); `unaccounted` is the silent drop count, which must be 0
/// for the ledger to mean anything at all. `unclassified_source` is the same
/// totality check over source loci: every source candidate must be classified as
/// warranted or refused, never silently outside the denominator.
/// Source count fields are optional for compatibility with assertion-only
/// ledgers; once present, the diff renders them as the coverage countdown.
/// `assertion_multiset_cid` is the content
/// identity of the whole assertion surface (None on pre-member-CID ledgers),
/// so the dark half is diffable by MEMBER, not only by cardinality: a
/// count-preserving swap moves the multiset-CID even when count and distinct-set both hold (multiplicity counts).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Residual {
    pub assert_macros: i64,
    pub discharged: i64,
    pub refused: i64,
    pub unaccounted: i64,
    pub source_loci: Option<i64>,
    pub source_warranted: Option<i64>,
    pub source_support: Option<i64>,
    pub source_refused: Option<i64>,
    pub source_inactive: Option<i64>,
    pub source_refuted: Option<i64>,
    pub unclassified_source: Option<i64>,
    pub assertion_multiset_cid: Option<String>,
}

impl Residual {
    pub fn from_ledger(v: &serde_json::Value) -> Result<Residual, String> {
        let field = |name: &str| -> Result<i64, String> {
            v.get(name)
                .and_then(|n| n.as_i64())
                .ok_or_else(|| format!("ledger missing integer field '{name}'"))
        };
        let optional_field = |name: &str| -> Option<i64> { v.get(name).and_then(|n| n.as_i64()) };
        let source_loci = optional_field("source_loci");
        let source_warranted = optional_field("source_warranted");
        let source_support = optional_field("source_support");
        let source_refused = optional_field("source_refused");
        let source_inactive = optional_field("source_inactive");
        let source_refuted = optional_field("source_refuted");
        let obsolete_source_work = optional_field("source_work");
        let unclassified_source =
            match (optional_field("unclassified_source"), obsolete_source_work) {
                (Some(unclassified), Some(backlog)) => Some(unclassified + backlog),
                (Some(unclassified), None) => Some(unclassified),
                (None, Some(backlog)) => Some(backlog),
                (None, None) => None,
            };
        let has_source_axis = source_loci.is_some()
            || source_warranted.is_some()
            || source_support.is_some()
            || source_refused.is_some()
            || source_inactive.is_some()
            || source_refuted.is_some()
            || obsolete_source_work.is_some()
            || unclassified_source.is_some();
        let assertion_field = |name: &str| -> Result<i64, String> {
            match optional_field(name) {
                Some(n) => Ok(n),
                None if has_source_axis => Ok(0),
                None => field(name),
            }
        };
        Ok(Residual {
            assert_macros: assertion_field("assert_macros")?,
            discharged: assertion_field("discharged")?,
            refused: assertion_field("refused")?,
            unaccounted: assertion_field("unaccounted")?,
            source_loci,
            source_warranted,
            source_support,
            source_refused,
            source_inactive,
            source_refuted,
            // Optional: absent on assertion-only ledgers. Once present, diff
            // treats it as a totality axis and fails if AFTER drops it.
            unclassified_source,
            // Optional: absent on ledgers minted before per-member CIDs.
            assertion_multiset_cid: v
                .get("assertion_multiset_cid")
                .and_then(|s| s.as_str())
                .map(|s| s.to_string()),
        })
    }

    /// The unproven set: assertions seen that did not lift to a discharged
    /// FOL atom. Refusals are inside it (loudly), silent drops are inside it
    /// (damningly).
    pub fn undischarged(&self) -> i64 {
        self.assert_macros - self.discharged
    }

    pub fn unclassified_source_count(&self) -> i64 {
        self.unclassified_source.unwrap_or(0)
    }

    pub fn source_axis_present(&self) -> bool {
        self.source_loci.is_some()
            || self.source_warranted.is_some()
            || self.source_support.is_some()
            || self.source_refused.is_some()
            || self.source_inactive.is_some()
            || self.source_refuted.is_some()
            || self.unclassified_source.is_some()
    }
}

/// Residual gate policy, parallel to `gate_ok` but over the dark half:
///   silent           fail always: AFTER has unaccounted assertions, so the
///                    ledger's own totality claim is broken. No flag bypasses
///                    a silent drop.
///   source-silent    fail always: AFTER has unclassified source loci, or AFTER
///                    dropped the source-classification axis that BEFORE had.
///                    Coverage cannot count down to zero if the denominator can
///                    silently shrink.
///   default          fail iff the residual grew (a proof regression).
///   --require BUMP    growth is MAJOR; `--require major` may accept it.
///   --frozen          fail iff the accounting moved at all, even improvement.
///                    This is where MEMBER identity bites: the derived `==`
///                    includes `assertion_multiset_cid`, so a count-preserving swap
///                    (and a cid-less/cid-present mismatch) fails fail-closed.
/// Magnitude gates (default/--require) stay cardinality-based on purpose: a
/// same-size member swap is not growth, so it fits a minor claim; identity
/// pinning is --frozen's job, not semver's.
pub fn residual_gate_ok(
    before: &Residual,
    after: &Residual,
    require: Option<&str>,
    frozen: bool,
) -> Result<bool, String> {
    if after.unaccounted > 0 {
        return Ok(false);
    }
    if before.source_axis_present() && !after.source_axis_present() {
        return Ok(false);
    }
    if after.unclassified_source_count() > 0 {
        return Ok(false);
    }
    if frozen {
        return Ok(before == after);
    }
    let grew = after.undischarged() > before.undischarged();
    if let Some(req) = require {
        let allowed =
            rank(req).ok_or_else(|| format!("invalid --require '{req}' (none|minor|major)"))?;
        let needed = if grew { rank("major") } else { rank("none") }.expect("static rank");
        return Ok(needed <= allowed);
    }
    Ok(!grew)
}

fn load_ledger(path: &Path) -> Result<Residual, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| format!("read ledger {}: {e}", path.display()))?;
    let json: serde_json::Value =
        serde_json::from_str(&text).map_err(|e| format!("parse ledger {}: {e}", path.display()))?;
    Residual::from_ledger(&json)
}

/// Render the diff verdict as a Markdown PR comment. Pure: the wording is the
/// product (the trojan-horse comment that rides Renovate/Dependabot), so it is
/// tested in-binary and the Action stays thin glue. Every claim here is
/// recomputable from the proofs -- the comment says so, because a verdict you
/// must trust is just another vendor.
pub fn render_markdown(
    s: &Summary,
    residual: Option<&(Residual, Residual)>,
    behavior_ok: bool,
    residual_ok: bool,
    require: Option<&str>,
    frozen: bool,
) -> String {
    let pass = behavior_ok && residual_ok;
    let verdict = if pass { "PASS ✅" } else { "FAIL ❌" };
    let mode = if frozen {
        "frozen (any change fails)".to_string()
    } else if let Some(req) = require {
        format!("require {req}")
    } else {
        "default (loss/growth fails)".to_string()
    };

    let mut out = String::new();
    out.push_str(&format!("### sugar diff — {verdict}\n\n"));
    out.push_str(&format!("**Mode:** `{mode}`\n\n"));

    if s.vacuous() {
        out.push_str(
            "**Behavior:** _vacuous_ — no proofs on either side. An empty comparison is not a green one; this dependency has nothing to pin.\n\n",
        );
    } else {
        out.push_str(&format!(
            "**Behavior:** {} new · {} lost · {} held · {} renamed — bump `{}`\n\n",
            s.new_behaviors,
            s.lost_behaviors,
            s.held,
            s.renamed,
            s.bump()
        ));
        if !s.lines.is_empty() {
            out.push_str("```\n");
            for line in &s.lines {
                out.push_str(line.trim_start());
                out.push('\n');
            }
            out.push_str("```\n\n");
        }
    }

    if let Some((rb, ra)) = residual {
        let members = if rb.assertion_multiset_cid == ra.assertion_multiset_cid {
            "held"
        } else {
            "**MOVED**"
        };
        let source = source_axis_summary(rb, ra);
        out.push_str(&format!(
            "**Residual (the unproven set):** undischarged {} → {} ({:+}) · silent {} → {}{} · members {}\n\n",
            rb.undischarged(),
            ra.undischarged(),
            ra.undischarged() - rb.undischarged(),
            rb.unaccounted,
            ra.unaccounted,
            source,
            members
        ));
    }

    out.push_str(
        "<sub>Recomputable, not trusted: this verdict is a hash you can reproduce from the proofs with `sugar diff`.</sub>\n",
    );
    out
}

/// Rank of a semver bump for ordering: none < minor < major.
fn rank(bump: &str) -> Option<u8> {
    match bump.to_ascii_lowercase().as_str() {
        "none" => Some(0),
        "minor" => Some(1),
        "major" => Some(2),
        _ => None,
    }
}

/// Does the delta pass the chosen exit gate? `Ok(true)` passes, `Ok(false)`
/// fails the gate, `Err` is bad input. This is the policy; `run` maps it to an
/// exit code. Pure, so it is unit-tested directly.
///   vacuous          fail always: no proofs on either side, nothing compared.
///   default          fail iff a behavior was lost (breaking).
///   --require BUMP    fail iff the required bump exceeds BUMP.
///   --frozen          fail iff anything changed at all (new/lost/renamed).
pub fn gate_ok(s: &Summary, require: Option<&str>, frozen: bool) -> Result<bool, String> {
    if s.vacuous() {
        return Ok(false);
    }
    if frozen {
        return Ok(s.new_behaviors == 0 && s.lost_behaviors == 0 && s.renamed == 0);
    }
    if let Some(req) = require {
        let allowed =
            rank(req).ok_or_else(|| format!("invalid --require '{req}' (none|minor|major)"))?;
        let needed = rank(s.bump()).expect("bump() returns a valid rank");
        return Ok(needed <= allowed);
    }
    Ok(!s.breaking())
}

fn short(cid: &str) -> String {
    let hex = cid.rsplit(':').next().unwrap_or(cid);
    format!("{}…", &hex[..hex.len().min(12)])
}

fn names(set: &BTreeSet<String>) -> String {
    set.iter().cloned().collect::<Vec<_>>().join(", ")
}

fn source_axis_summary(before: &Residual, after: &Residual) -> String {
    if !before.source_axis_present() && !after.source_axis_present() {
        return String::new();
    }
    let mut parts = Vec::new();
    push_source_axis_part(
        &mut parts,
        "source-loci",
        before.source_loci,
        after.source_loci,
    );
    push_source_axis_part(
        &mut parts,
        "warranted",
        before.source_warranted,
        after.source_warranted,
    );
    push_source_axis_part(
        &mut parts,
        "support",
        before.source_support,
        after.source_support,
    );
    push_source_axis_part(
        &mut parts,
        "refused",
        before.source_refused,
        after.source_refused,
    );
    push_source_axis_part(
        &mut parts,
        "inactive",
        before.source_inactive,
        after.source_inactive,
    );
    push_source_axis_part(
        &mut parts,
        "refuted",
        before.source_refuted,
        after.source_refuted,
    );
    push_source_axis_part(
        &mut parts,
        "unclassified",
        before.unclassified_source,
        after.unclassified_source,
    );
    format!(" · {}", parts.join(" · "))
}

fn push_source_axis_part(
    parts: &mut Vec<String>,
    label: &str,
    before: Option<i64>,
    after: Option<i64>,
) {
    if before.is_none() && after.is_none() {
        return;
    }
    parts.push(format!(
        "{label} {} → {}",
        source_axis_value(before, false),
        source_axis_value(after, true)
    ));
}

fn source_axis_value(value: Option<i64>, after: bool) -> String {
    match value {
        Some(n) => n.to_string(),
        None if after => "MISSING".into(),
        None => "n/a".into(),
    }
}

/// Pure comparison: classify every behavior CID across both tables. This is the
/// whole feature; everything else is IO around it.
pub fn summarize(before: &Table, after: &Table) -> Summary {
    let b = invert(before);
    let a = invert(after);
    let mut s = Summary::default();
    let cids: BTreeSet<&String> = b.keys().chain(a.keys()).collect();
    for cid in cids {
        match (b.get(cid), a.get(cid)) {
            (Some(bn), Some(an)) => {
                s.held += bn.intersection(an).count() as u32;
                if bn != an {
                    s.renamed += 1;
                    let from: Vec<String> = bn.difference(an).cloned().collect();
                    let to: Vec<String> = an.difference(bn).cloned().collect();
                    s.lines.push(format!(
                        "  renamed    {} -> {}   (behavior {} held)",
                        from.join(", "),
                        to.join(", "),
                        short(cid)
                    ));
                }
            }
            (Some(bn), None) => {
                s.lost_behaviors += 1;
                s.lines
                    .push(format!("  lost       {}   ({})", names(bn), short(cid)));
            }
            (None, Some(an)) => {
                s.new_behaviors += 1;
                s.lines
                    .push(format!("  new        {}   ({})", names(an), short(cid)));
            }
            (None, None) => unreachable!("cid came from the union of both key sets"),
        }
    }
    s
}

fn git_toplevel() -> Result<String, String> {
    let out = Command::new("git")
        .args(["rev-parse", "--show-toplevel"])
        .output()
        .map_err(|e| format!("git: {e}"))?;
    if !out.status.success() {
        return Err("not in a git repository (--git must run from inside one)".into());
    }
    Ok(String::from_utf8_lossy(&out.stdout).trim().to_string())
}

fn sanitize(s: &str) -> String {
    s.chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '_' })
        .collect()
}

/// Extract `rev:path` from `repo` into a temp dir via `git archive | tar`, load
/// its proofs, and clean up. No worktree state, no checkout of the live tree.
fn load_git(repo: &str, rev: &str, path: &str, label: &str) -> Result<Table, String> {
    let tmp = std::env::temp_dir().join(format!("sugar-diff-{label}-{}", sanitize(rev)));
    let _ = std::fs::remove_dir_all(&tmp);
    std::fs::create_dir_all(&tmp).map_err(|e| format!("mkdir {}: {e}", tmp.display()))?;

    let treeish = if path == "." || path.is_empty() {
        rev.to_string()
    } else {
        format!("{rev}:{path}")
    };
    let archive = Command::new("git")
        .args(["-C", repo, "archive", "--format=tar", &treeish])
        .output()
        .map_err(|e| format!("git archive: {e}"))?;
    if !archive.status.success() {
        return Err(format!(
            "git archive {treeish}: {}",
            String::from_utf8_lossy(&archive.stderr).trim()
        ));
    }
    let mut tar = Command::new("tar")
        .args(["-x", "-C", &tmp.to_string_lossy()])
        .stdin(Stdio::piped())
        .spawn()
        .map_err(|e| format!("tar: {e}"))?;
    tar.stdin
        .take()
        .expect("tar stdin")
        .write_all(&archive.stdout)
        .map_err(|e| format!("tar stdin: {e}"))?;
    if !tar.wait().map_err(|e| format!("tar wait: {e}"))?.success() {
        return Err(format!("tar extract failed for {treeish}"));
    }

    let table = behavior_table_from_dir(&tmp)?;
    let _ = std::fs::remove_dir_all(&tmp);
    Ok(table)
}

pub fn run(args: DiffArgs) -> u8 {
    let loaded = if args.git {
        match git_toplevel() {
            Ok(repo) => load_git(&repo, &args.before, &args.path, "before")
                .and_then(|b| load_git(&repo, &args.after, &args.path, "after").map(|a| (b, a))),
            Err(e) => Err(e),
        }
    } else {
        behavior_table_from_dir(Path::new(&args.before))
            .and_then(|b| behavior_table_from_dir(Path::new(&args.after)).map(|a| (b, a)))
    };
    let (before, after) = match loaded {
        Ok(p) => p,
        Err(e) => {
            eprintln!("error: {e}");
            return EXIT_USER_ERROR;
        }
    };

    let markdown = args.format == DiffFormat::Markdown;

    let s = summarize(&before, &after);
    if !markdown {
        for line in &s.lines {
            println!("{line}");
        }
        if !s.lines.is_empty() {
            println!();
        }
        println!(
            "behavior: {} new, {} lost, {} held, {} renamed",
            s.new_behaviors, s.lost_behaviors, s.held, s.renamed
        );
        println!("required bump: {}", s.bump());
    }

    let residual = match (&args.ledger_before, &args.ledger_after) {
        (Some(b), Some(a)) => {
            let pair = load_ledger(b).and_then(|rb| load_ledger(a).map(|ra| (rb, ra)));
            match pair {
                Ok((rb, ra)) => {
                    if !markdown {
                        let members = if rb.assertion_multiset_cid == ra.assertion_multiset_cid {
                            "held"
                        } else {
                            "MOVED"
                        };
                        println!(
                            "residual: undischarged {} -> {} ({:+}); silent {} -> {}{}; members {}",
                            rb.undischarged(),
                            ra.undischarged(),
                            ra.undischarged() - rb.undischarged(),
                            rb.unaccounted,
                            ra.unaccounted,
                            source_axis_summary(&rb, &ra),
                            members
                        );
                    }
                    Some((rb, ra))
                }
                Err(e) => {
                    eprintln!("error: {e}");
                    return EXIT_USER_ERROR;
                }
            }
        }
        _ => None,
    };

    let behavior_ok = match gate_ok(&s, args.require.as_deref(), args.frozen) {
        Ok(true) => true,
        Ok(false) => {
            if s.vacuous() {
                eprintln!(
                    "vacuous: no proofs on either side; an empty comparison is not a green one"
                );
            } else if args.frozen {
                eprintln!("frozen: dependency behavior changed under a fixed pin");
            } else if let Some(req) = &args.require {
                eprintln!(
                    "gate: behavior requires {}, exceeds claimed {req}",
                    s.bump()
                );
            }
            false
        }
        Err(e) => {
            eprintln!("error: {e}");
            return EXIT_USER_ERROR;
        }
    };

    let residual_ok = match &residual {
        None => true,
        Some((rb, ra)) => match residual_gate_ok(rb, ra, args.require.as_deref(), args.frozen) {
            Ok(true) => true,
            Ok(false) => {
                if ra.unaccounted > 0 {
                    eprintln!(
                        "silent: AFTER ledger has {} unaccounted assertion(s); a silent drop is never green",
                        ra.unaccounted
                    );
                } else if rb.source_axis_present() && !ra.source_axis_present() {
                    eprintln!(
                        "source-silent: AFTER ledger dropped the source-classification axis; source loci must be warranted or refused"
                    );
                } else if ra.unclassified_source_count() > 0 {
                    eprintln!(
                        "source-silent: AFTER ledger has {} unclassified source locus/loci; source must be warranted or refused",
                        ra.unclassified_source_count()
                    );
                } else if args.frozen {
                    if rb.assertion_multiset_cid != ra.assertion_multiset_cid {
                        eprintln!(
                            "frozen: assertion-multiset CID moved under a fixed pin (a member swap, even if every count held)"
                        );
                    } else {
                        eprintln!("frozen: residual accounting moved under a fixed pin");
                    }
                } else {
                    eprintln!(
                        "gate: residual grew (undischarged {} -> {})",
                        rb.undischarged(),
                        ra.undischarged()
                    );
                }
                false
            }
            Err(e) => {
                eprintln!("error: {e}");
                return EXIT_USER_ERROR;
            }
        },
    };

    if markdown {
        print!(
            "{}",
            render_markdown(
                &s,
                residual.as_ref(),
                behavior_ok,
                residual_ok,
                args.require.as_deref(),
                args.frozen,
            )
        );
    }

    if behavior_ok && residual_ok {
        EXIT_OK
    } else {
        EXIT_VERIFY_FAIL
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn table(pairs: &[(&str, &str)]) -> Table {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    // --- markdown comment: the literal text of the PR-bot verdict. Pure, so
    // the Action is thin glue and the wording is tested in-binary. ---

    #[test]
    fn markdown_pass_shows_check_and_bump() {
        let a = table(&[("f", "c1")]);
        let s = summarize(&a, &a);
        let md = render_markdown(&s, None, true, true, None, false);
        assert!(md.contains("PASS"), "{md}");
        assert!(md.contains("none"), "bump shown: {md}");
        assert!(!md.contains("undischarged"), "no residual section: {md}");
    }

    #[test]
    fn markdown_fail_names_lost_behavior() {
        let s = summarize(&table(&[("f", "c1"), ("g", "c2")]), &table(&[("f", "c1")]));
        let md = render_markdown(&s, None, false, true, None, false);
        assert!(md.contains("FAIL"), "{md}");
        assert!(md.contains("lost"), "lost detail surfaced: {md}");
    }

    #[test]
    fn markdown_includes_residual_with_members() {
        let a = table(&[("f", "c1")]);
        let s = summarize(&a, &a);
        let before = res_cid(100, 80, 20, 0, "blake3-512:AAA");
        let after = res_cid(100, 80, 20, 0, "blake3-512:BBB");
        let md = render_markdown(&s, Some(&(before, after)), true, false, None, true);
        assert!(md.contains("undischarged"), "{md}");
        assert!(md.contains("member"), "member status surfaced: {md}");
    }

    #[test]
    fn markdown_includes_source_accounting_countdown() {
        let a = table(&[("f", "c1")]);
        let s = summarize(&a, &a);
        let before = Residual::from_ledger(&serde_json::json!({
            "assert_macros": 100, "discharged": 80,
            "refused": 20, "unaccounted": 0,
            "source_loci": 48,
            "source_warranted": 8,
            "source_refused": 21,
            "source_inactive": 19,
            "source_refuted": 0,
            "unclassified_source": 2
        }))
        .unwrap();
        let after = Residual::from_ledger(&serde_json::json!({
            "assert_macros": 100, "discharged": 80,
            "refused": 20, "unaccounted": 0,
            "source_loci": 48,
            "source_warranted": 10,
            "source_refused": 22,
            "source_inactive": 16,
            "source_refuted": 0,
            "unclassified_source": 0
        }))
        .unwrap();
        let md = render_markdown(&s, Some(&(before, after)), true, true, None, false);
        assert!(md.contains("source-loci 48 → 48"), "{md}");
        assert!(md.contains("warranted 8 → 10"), "{md}");
        assert!(md.contains("refused 21 → 22"), "{md}");
        assert!(md.contains("inactive 19 → 16"), "{md}");
        assert!(md.contains("unclassified 2 → 0"), "{md}");
    }

    #[test]
    fn markdown_flags_vacuous_behavior_even_with_a_residual() {
        let empty = table(&[]);
        let s = summarize(&empty, &empty);
        let before = res(10, 8, 2, 0);
        let after = res(10, 8, 2, 0);
        let md = render_markdown(&s, Some(&(before, after)), false, true, None, true);
        assert!(
            md.to_lowercase().contains("vacuous"),
            "a proofless behavior must read as vacuous, not as '0 held': {md}"
        );
    }

    #[test]
    fn markdown_is_recomputable_disclaimer_present() {
        let a = table(&[("f", "c1")]);
        let s = summarize(&a, &a);
        let md = render_markdown(&s, None, true, true, None, false);
        assert!(
            md.to_lowercase().contains("recomput"),
            "the comment must say it is recomputable, not trusted: {md}"
        );
    }

    #[test]
    fn identity_holds_all_behaviors_no_bump() {
        let a = table(&[("f", "cid1"), ("g", "cid2")]);
        let s = summarize(&a, &a);
        assert_eq!(
            (s.held, s.new_behaviors, s.lost_behaviors, s.renamed),
            (2, 0, 0, 0)
        );
        assert!(!s.breaking());
        assert_eq!(s.bump(), "none");
    }

    #[test]
    fn pure_rename_is_renamed_not_breaking() {
        let s = summarize(
            &table(&[("old_name", "cidA")]),
            &table(&[("new_name", "cidA")]),
        );
        assert_eq!(
            (s.renamed, s.new_behaviors, s.lost_behaviors, s.held),
            (1, 0, 0, 0)
        );
        assert!(!s.breaking());
        assert_eq!(s.bump(), "none");
    }

    #[test]
    fn behavior_moved_under_stable_name_is_major() {
        let s = summarize(&table(&[("f", "cid1")]), &table(&[("f", "cid2")]));
        assert_eq!((s.lost_behaviors, s.new_behaviors), (1, 1));
        assert!(s.breaking());
        assert_eq!(s.bump(), "MAJOR");
    }

    #[test]
    fn added_only_is_minor() {
        let s = summarize(
            &table(&[("f", "cid1")]),
            &table(&[("f", "cid1"), ("g", "cid2")]),
        );
        assert_eq!((s.new_behaviors, s.lost_behaviors, s.held), (1, 0, 1));
        assert!(!s.breaking());
        assert_eq!(s.bump(), "minor");
    }

    #[test]
    fn lost_behavior_is_major_and_breaking() {
        let s = summarize(
            &table(&[("f", "cid1"), ("g", "cid2")]),
            &table(&[("f", "cid1")]),
        );
        assert_eq!((s.lost_behaviors, s.held), (1, 1));
        assert!(s.breaking());
        assert_eq!(s.bump(), "MAJOR");
    }

    // --- exit gates: --require (honest semver) and --frozen (supply-chain) ---

    fn lost() -> Summary {
        summarize(&table(&[("f", "c1"), ("g", "c2")]), &table(&[("f", "c1")]))
    }
    fn added() -> Summary {
        summarize(&table(&[("f", "c1")]), &table(&[("f", "c1"), ("g", "c2")]))
    }
    fn renamed() -> Summary {
        summarize(&table(&[("old", "cA")]), &table(&[("new", "cA")]))
    }
    fn identity() -> Summary {
        let a = table(&[("f", "c1")]);
        summarize(&a, &a)
    }

    #[test]
    fn default_gate_fails_on_loss_passes_on_addition() {
        assert_eq!(gate_ok(&lost(), None, false), Ok(false));
        assert_eq!(gate_ok(&added(), None, false), Ok(true));
    }

    #[test]
    fn require_minor_allows_addition_rejects_loss() {
        assert_eq!(gate_ok(&added(), Some("minor"), false), Ok(true));
        // a loss is MAJOR, which exceeds the claimed minor.
        assert_eq!(gate_ok(&lost(), Some("minor"), false), Ok(false));
    }

    #[test]
    fn require_none_rejects_even_an_addition() {
        assert_eq!(gate_ok(&added(), Some("none"), false), Ok(false));
        assert_eq!(gate_ok(&identity(), Some("none"), false), Ok(true));
    }

    #[test]
    fn require_major_allows_anything() {
        assert_eq!(gate_ok(&lost(), Some("major"), false), Ok(true));
    }

    #[test]
    fn frozen_fails_on_any_delta_including_rename() {
        assert_eq!(gate_ok(&identity(), None, true), Ok(true));
        assert_eq!(gate_ok(&added(), None, true), Ok(false));
        assert_eq!(gate_ok(&renamed(), None, true), Ok(false));
        assert_eq!(gate_ok(&lost(), None, true), Ok(false));
    }

    #[test]
    fn invalid_require_is_an_error() {
        assert!(gate_ok(&identity(), Some("patchy"), false).is_err());
    }

    // --- vacuity: two proofless trees prove nothing. An empty-vs-empty diff
    // must fail every gate, exactly as a zero-callsite verifier report fails
    // `report_exit_code`. Otherwise a dependency with NO proofs at all sails
    // through `--frozen` -- the naked node passes the supply-chain pin. ---

    fn vacuous() -> Summary {
        summarize(&table(&[]), &table(&[]))
    }

    #[test]
    fn empty_vs_empty_fails_default_gate() {
        assert_eq!(gate_ok(&vacuous(), None, false), Ok(false));
    }

    #[test]
    fn empty_vs_empty_fails_frozen() {
        assert_eq!(gate_ok(&vacuous(), None, true), Ok(false));
    }

    #[test]
    fn empty_vs_empty_fails_even_require_major() {
        assert_eq!(gate_ok(&vacuous(), Some("major"), false), Ok(false));
    }

    #[test]
    fn vacuous_summary_is_detectable() {
        assert!(vacuous().vacuous());
        assert!(!identity().vacuous());
        assert!(!added().vacuous());
    }

    // --- residual axis: diff the dark half too. A sweep ledger on each side
    // lets the gates see the unproven set -- silent drops, proof regressions,
    // residual movement under a pin -- not just the minted behaviors. ---

    fn res(assert_macros: i64, discharged: i64, refused: i64, unaccounted: i64) -> Residual {
        Residual {
            assert_macros,
            discharged,
            refused,
            unaccounted,
            source_loci: None,
            source_warranted: None,
            source_support: None,
            source_refused: None,
            source_inactive: None,
            source_refuted: None,
            unclassified_source: None,
            assertion_multiset_cid: None,
        }
    }

    #[test]
    fn residual_parses_sweep_ledger_fields() {
        let ledger = serde_json::json!({
            "corpus": "coretests/tests",
            "assert_macros": 6377, "discharged": 4773,
            "refused": 1604, "unaccounted": 0,
            "per_file": []
        });
        let r = Residual::from_ledger(&ledger).expect("parses");
        assert_eq!(r, res(6377, 4773, 1604, 0));
        assert_eq!(r.undischarged(), 1604);
    }

    #[test]
    fn residual_parses_unclassified_source_axis() {
        let ledger = serde_json::json!({
            "assert_macros": 10, "discharged": 7,
            "refused": 3, "unaccounted": 0,
            "unclassified_source": 4
        });
        let r = Residual::from_ledger(&ledger).expect("parses");
        assert_eq!(r.unclassified_source, Some(4));
    }

    #[test]
    fn residual_parses_source_only_kit_ledger() {
        let ledger = serde_json::json!({
            "source_loci": 48,
            "source_warranted": 10,
            "source_support": 3,
            "source_refused": 22,
            "source_inactive": 16,
            "source_refuted": 0,
            "unclassified_source": 0
        });
        let r = Residual::from_ledger(&ledger).expect("source-only kit ledger parses");
        assert_eq!(r.assert_macros, 0);
        assert_eq!(r.discharged, 0);
        assert_eq!(r.refused, 0);
        assert_eq!(r.unaccounted, 0);
        assert_eq!(r.source_loci, Some(48));
        assert_eq!(r.source_warranted, Some(10));
        assert_eq!(r.source_support, Some(3));
        assert_eq!(r.source_refused, Some(22));
        assert_eq!(r.source_inactive, Some(16));
        assert_eq!(r.unclassified_source, Some(0));
    }

    #[test]
    fn source_axis_summary_includes_support() {
        let before = Residual::from_ledger(&serde_json::json!({
            "source_loci": 4,
            "source_warranted": 1,
            "source_support": 0,
            "source_refused": 0,
            "source_inactive": 0,
            "source_refuted": 0,
            "unclassified_source": 3
        }))
        .expect("before parses");
        let after = Residual::from_ledger(&serde_json::json!({
            "source_loci": 4,
            "source_warranted": 1,
            "source_support": 2,
            "source_refused": 0,
            "source_inactive": 0,
            "source_refuted": 0,
            "unclassified_source": 1
        }))
        .expect("after parses");

        let summary = source_axis_summary(&before, &after);
        assert!(summary.contains("support 0 → 2"), "{summary}");
        assert!(summary.contains("unclassified 3 → 1"), "{summary}");
    }

    #[test]
    fn residual_missing_field_is_an_error() {
        let ledger = serde_json::json!({"assert_macros": 10, "discharged": 9});
        assert!(Residual::from_ledger(&ledger).is_err());
    }

    #[test]
    fn silent_drop_in_after_fails_every_residual_gate() {
        let before = res(100, 80, 20, 0);
        let after = res(100, 90, 9, 1);
        assert_eq!(residual_gate_ok(&before, &after, None, false), Ok(false));
        assert_eq!(residual_gate_ok(&before, &after, None, true), Ok(false));
        assert_eq!(
            residual_gate_ok(&before, &after, Some("major"), false),
            Ok(false)
        );
    }

    #[test]
    fn unclassified_source_in_after_fails_every_residual_gate() {
        let before = Residual::from_ledger(&serde_json::json!({
            "assert_macros": 100, "discharged": 80,
            "refused": 20, "unaccounted": 0,
            "unclassified_source": 0
        }))
        .unwrap();
        let after = Residual::from_ledger(&serde_json::json!({
            "assert_macros": 100, "discharged": 90,
            "refused": 10, "unaccounted": 0,
            "unclassified_source": 1
        }))
        .unwrap();
        assert_eq!(residual_gate_ok(&before, &after, None, false), Ok(false));
        assert_eq!(residual_gate_ok(&before, &after, None, true), Ok(false));
        assert_eq!(
            residual_gate_ok(&before, &after, Some("major"), false),
            Ok(false)
        );
    }

    #[test]
    fn dropping_source_classification_axis_fails_residual_gate() {
        let before = Residual::from_ledger(&serde_json::json!({
            "assert_macros": 100, "discharged": 80,
            "refused": 20, "unaccounted": 0,
            "unclassified_source": 3
        }))
        .unwrap();
        let after = res(100, 80, 20, 0);
        assert_eq!(residual_gate_ok(&before, &after, None, false), Ok(false));
        assert_eq!(
            residual_gate_ok(&before, &after, Some("major"), false),
            Ok(false)
        );
    }

    #[test]
    fn undischarged_growth_fails_default_residual_gate() {
        // a previously-discharged assertion fell back to refused: proof lost.
        let before = res(100, 80, 20, 0);
        let after = res(100, 70, 30, 0);
        assert_eq!(residual_gate_ok(&before, &after, None, false), Ok(false));
    }

    #[test]
    fn undischarged_shrink_passes_default_and_require_none() {
        let before = res(100, 80, 20, 0);
        let after = res(100, 90, 10, 0);
        assert_eq!(residual_gate_ok(&before, &after, None, false), Ok(true));
        assert_eq!(
            residual_gate_ok(&before, &after, Some("none"), false),
            Ok(true)
        );
    }

    #[test]
    fn frozen_fails_on_any_residual_movement_even_improvement() {
        let before = res(100, 80, 20, 0);
        let after = res(100, 90, 10, 0);
        assert_eq!(residual_gate_ok(&before, &after, None, true), Ok(false));
        assert_eq!(residual_gate_ok(&before, &before, None, true), Ok(true));
    }

    #[test]
    fn require_major_allows_growth_but_never_silence() {
        let grew = (res(100, 80, 20, 0), res(100, 70, 30, 0));
        assert_eq!(
            residual_gate_ok(&grew.0, &grew.1, Some("major"), false),
            Ok(true)
        );
        let silent = (res(100, 80, 20, 0), res(100, 80, 19, 1));
        assert_eq!(
            residual_gate_ok(&silent.0, &silent.1, Some("major"), false),
            Ok(false)
        );
    }

    // --- per-member identity: the count-preserving swap. Same cardinality,
    // different assertion-multiset CID -- one obligation swapped for a decoy. The
    // count gate is blind to this; the multiset-CID is the teeth, and --frozen is
    // where it bites (identity pin). The semver gate stays magnitude-based. ---

    fn res_cid(am: i64, d: i64, r: i64, u: i64, cid: &str) -> Residual {
        Residual {
            assert_macros: am,
            discharged: d,
            refused: r,
            unaccounted: u,
            source_loci: None,
            source_warranted: None,
            source_support: None,
            source_refused: None,
            source_inactive: None,
            source_refuted: None,
            unclassified_source: None,
            assertion_multiset_cid: Some(cid.to_string()),
        }
    }

    #[test]
    fn frozen_catches_count_preserving_member_swap() {
        let before = res_cid(100, 80, 20, 0, "blake3-512:AAA");
        let after = res_cid(100, 80, 20, 0, "blake3-512:BBB");
        assert_eq!(
            before.undischarged(),
            after.undischarged(),
            "the cardinality gate is blind here by construction"
        );
        assert_eq!(residual_gate_ok(&before, &after, None, true), Ok(false));
    }

    #[test]
    fn frozen_passes_when_member_set_identical() {
        let r = res_cid(100, 80, 20, 0, "blake3-512:AAA");
        assert_eq!(residual_gate_ok(&r, &r, None, true), Ok(true));
    }

    #[test]
    fn member_swap_fits_a_minor_claim_without_count_regression() {
        // --require is magnitude (semver); a same-size swap is not growth.
        let before = res_cid(100, 80, 20, 0, "blake3-512:AAA");
        let after = res_cid(100, 80, 20, 0, "blake3-512:BBB");
        assert_eq!(
            residual_gate_ok(&before, &after, Some("minor"), false),
            Ok(true)
        );
    }

    #[test]
    fn frozen_fails_closed_when_one_side_lacks_member_set() {
        // can't verify member identity -> not green. Mixing an old (cid-less)
        // ledger with a new one under --frozen fails rather than pretends.
        let new = res_cid(1, 1, 0, 0, "blake3-512:Z");
        let old = res(1, 1, 0, 0);
        assert_eq!(residual_gate_ok(&new, &old, None, true), Ok(false));
        assert_eq!(residual_gate_ok(&old, &new, None, true), Ok(false));
    }

    #[test]
    fn from_ledger_reads_member_set_cid_and_tolerates_absence() {
        let with = serde_json::json!({
            "assert_macros": 1, "discharged": 1, "refused": 0, "unaccounted": 0,
            "assertion_multiset_cid": "blake3-512:Z"
        });
        assert_eq!(
            Residual::from_ledger(&with)
                .unwrap()
                .assertion_multiset_cid
                .as_deref(),
            Some("blake3-512:Z")
        );
        let without = serde_json::json!({
            "assert_macros": 1, "discharged": 1, "refused": 0, "unaccounted": 0
        });
        assert_eq!(
            Residual::from_ledger(&without)
                .unwrap()
                .assertion_multiset_cid,
            None
        );
    }

    // --- git mode: build a throwaway repo, commit two disjoint proof sets,
    // and diff across the two refs. The proofs are synthesized here rather than
    // copied from `examples/`, because only run-receipts (no contract names)
    // are committed under the example trees and those don't populate
    // `name_to_cid` — the table the cross-ref diff actually compares. ---

    fn write_graph_contract_proof(
        dir: &Path,
        contracts: Vec<sugar_proof_envelope::ContractMemento>,
    ) {
        use sugar_canonicalizer::blake3_512_of;
        use sugar_proof_envelope::{
            build_proof_envelope, ed25519_pubkey_string, Ed25519Seed, ProofEnvelopeInput,
        };

        let signer_seed: Ed25519Seed = [0x42u8; 32];
        let signer_cid = blake3_512_of(ed25519_pubkey_string(&signer_seed).as_bytes());
        let mut graph = sugar_proof_envelope::ProofGraph::new();
        for contract in contracts {
            for atom in contract.body().atoms() {
                graph.register_atom(atom.clone());
            }
            graph.register_atom(contract.metadata().atom().clone());
            graph.register_body(contract.body().clone());
            graph.register_contract(contract);
        }
        let built = build_proof_envelope(&ProofEnvelopeInput {
            name: "@test/diff-graph".into(),
            version: "1.0.0".into(),
            binary_cid: None,
            metadata: None,
            graph,
            signer_cid,
            signer_seed,
            declared_at: "2026-04-30T00:00:00.000Z".into(),
        });
        let hex = built.cid.strip_prefix("blake3-512:").unwrap_or(&built.cid);
        assert!(!hex.contains(':'), "proof filename stem must be colon-free");
        std::fs::create_dir_all(dir).unwrap();
        std::fs::write(dir.join(format!("{hex}.proof")), &built.bytes).expect("write proof");
    }

    #[test]
    fn real_proof_rename_is_migration_not_behavior_delta() {
        let tmp = std::env::temp_dir().join(format!(
            "sugar-diff-real-rename-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let before_dir = tmp.join("before");
        let after_dir = tmp.join("after");
        use sugar_proof_envelope::{AtomMemento, ContractBody, ContractMemento, FlatAtom};
        let atom = FlatAtom::result_eq_int(7);
        let atom_memento = AtomMemento::new(&atom);
        let body = ContractBody::new(&atom_memento);
        let body_cid = body.cid().as_str().to_string();
        let before_contract = ContractMemento::new("src/lib.rs::diff::old_name", &body, [0x42; 32]);
        let after_contract = ContractMemento::new("src/lib.rs::diff::new_name", &body, [0x42; 32]);
        write_graph_contract_proof(&before_dir, vec![before_contract]);
        write_graph_contract_proof(&after_dir, vec![after_contract]);

        // diff reads behaviors by asking ProofGraph::read for the contracts --
        // the typed bodyCid pointer, not a hand-stripped envelope field.
        let before = behavior_table_from_dir(&before_dir).expect("read before");
        let after = behavior_table_from_dir(&after_dir).expect("read after");
        assert_eq!(
            before.get("src/lib.rs::diff::old_name"),
            Some(&body_cid),
            "diff must read the contract memento's typed bodyCid pointer out of the graph"
        );
        assert_eq!(
            after.get("src/lib.rs::diff::new_name"),
            Some(&body_cid),
            "a rename preserves behavior when the contract body pointer is unchanged"
        );

        let s = summarize(&before, &after);
        let _ = std::fs::remove_dir_all(&tmp);

        assert_eq!(
            (s.renamed, s.new_behaviors, s.lost_behaviors, s.held),
            (1, 0, 0, 0),
            "a real loaded proof with the same contract under a new name is a migration, not a behavior delta: {s:?}"
        );
        assert!(!s.breaking());
        assert_eq!(s.bump(), "none");
    }

    #[test]
    fn git_diff_across_two_commits_of_real_proofs() {
        let tmp = std::env::temp_dir().join(format!("sugar-diff-git-it-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        let git = |a: &[&str]| {
            Command::new("git")
                .args(["-C", &tmp.to_string_lossy()])
                .args(a)
                .output()
                .unwrap()
        };
        git(&["init", "-q"]);
        git(&["config", "user.email", "t@example.com"]);
        git(&["config", "user.name", "t"]);

        // commit 1: proj names contract `alpha`.
        use sugar_proof_envelope::{AtomMemento, ContractBody, ContractMemento, FlatAtom};
        let alpha_atom = FlatAtom::result_eq_int(0);
        let alpha_memento = AtomMemento::new(&alpha_atom);
        let alpha_body = ContractBody::new(&alpha_memento);
        write_graph_contract_proof(
            &tmp.join("proj"),
            vec![ContractMemento::new(
                "src/lib.rs::diff::alpha",
                &alpha_body,
                [0x42; 32],
            )],
        );
        git(&["add", "-Af"]);
        git(&["commit", "-qm", "c1"]);

        // commit 2: proj names contract `beta` — a disjoint contract set, so
        // `alpha`'s CID is lost and `beta`'s CID is new across the two refs.
        std::fs::remove_dir_all(tmp.join("proj")).unwrap();
        let beta_atom = FlatAtom::result_eq_int(1);
        let beta_memento = AtomMemento::new(&beta_atom);
        let beta_body = ContractBody::new(&beta_memento);
        write_graph_contract_proof(
            &tmp.join("proj"),
            vec![ContractMemento::new(
                "src/lib.rs::diff::beta",
                &beta_body,
                [0x42; 32],
            )],
        );
        git(&["add", "-Af"]);
        git(&["commit", "-qm", "c2"]);

        let repo = tmp.to_string_lossy().to_string();
        let before = load_git(&repo, "HEAD~1", "proj", "test_before").expect("load before");
        let after = load_git(&repo, "HEAD", "proj", "test_after").expect("load after");
        let s = summarize(&before, &after);
        let _ = std::fs::remove_dir_all(&tmp);

        // the two proof sets denote different behaviors, so the cross-ref diff
        // must show behaviors both appearing and disappearing.
        assert!(
            s.new_behaviors > 0 && s.lost_behaviors > 0,
            "expected a real behavior delta across the two committed proof sets, got {s:?}"
        );
        assert!(s.breaking());
    }
}

// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Solver-configuration model. Mirrors the `[solvers]` table in
// `.sugar/config.toml`:
//
//   [solvers]
//   default = "z3"                            # OR
//   chain = ["z3", "cvc5"]                    # OR
//   portfolio = ["maude", "z3", "cvc5", "bitwuzla"]    # OR
//   mode = "first-wins"  or  "consensus"
//
//   [solvers.z3]
//   binary = "z3"
//   ir_compiler = "smt-lib-v2.6"
//   timeout_seconds = 5
//   flags = ["-T:5"]
//
//   [solvers.maude]
//   binary = "maude"
//   ir_compiler = "maude"
//   ceta_gate = true
//   ceta_binary = "ceta"
//   termination_prover = "aprove"
//   confluence_checker = "csi"
//
//   [solvers.dispatch]
//   "strings" = "cvc5"
//   "bitvectors" = "bitwuzla"
//   "linear-arithmetic" = "z3"
//   "default" = "z3"
//
// Exactly one of {default, chain, portfolio, dispatch} should be set;
// `default` wins if multiple are present (single-solver fallback).

use std::collections::BTreeMap;
use std::fmt;
use std::path::Path;
use std::str::FromStr;

use serde::{de, Deserialize};
use sugar_proof_envelope::MementoCid;

#[derive(Debug, Clone, Deserialize, Default)]
pub struct SolverConfig {
    /// Path to the solver binary (or solver shorthand for builtin
    /// stubs: `stub:unsat`, `stub:sat`, `stub:undecidable`).
    #[serde(default)]
    pub binary: String,
    /// Logical IR compiler tag; the verifier uses this to pick which
    /// emitter to run. `smt-lib-v2.6` (default) goes through the
    /// existing in-Rust SMT emitter. The IR-compiler agent will land
    /// alternative compilers (e.g. `smt-lib-v2.6-bv`); when that lands
    /// the verifier dispatches by this string with no other code
    /// changes.
    #[serde(default = "default_ir_compiler")]
    pub ir_compiler: String,
    #[serde(default)]
    pub timeout_seconds: Option<u64>,
    #[serde(default)]
    pub flags: Vec<String>,
    /// Enables the certified termination and confluence gate used by
    /// Maude before a reduce-based equality can be trusted.
    #[serde(default)]
    pub ceta_gate: bool,
    /// Path to the CeTA checker binary.
    #[serde(default = "default_ceta_binary")]
    pub ceta_binary: String,
    /// Path to a termination prover that emits a CPF certificate.
    #[serde(default = "default_termination_prover")]
    pub termination_prover: String,
    /// Path to a confluence checker that emits a CPF certificate.
    #[serde(default = "default_confluence_checker")]
    pub confluence_checker: String,
    /// Optional version pin to surface in the report and in minted
    /// implication-memento `body.prover` strings. Defaults to `0`.
    #[serde(default = "default_version")]
    pub version: String,
    /// Optional Sugar CID for the solver artifact. This is the verifier's
    /// address for the thing being invoked; external package-manager hashes
    /// are carried in vendor-address mementos, not used as Sugar addresses.
    #[serde(default, alias = "binaryCid")]
    pub binary_cid: Option<String>,
    /// Optional vendor-published address for the solver artifact. The value is
    /// explicitly scheme-prefixed (`sha256:<hex>`, `sha512:<hex>`, `file:<path>`,
    /// `http:<url>`, `simon_says:true`, npm integrity, etc.). The scheme is a
    /// vendor namespace, not a whitelist. When paired with `binary_cid`, the
    /// registry emits a CID-addressed vendor-address memento mapping our
    /// artifact CID to the vendor pin. The verifier never guesses a scheme.
    #[serde(default, alias = "vendorPin")]
    pub vendor_pin: Option<String>,
    /// Optional path to a Lake project that has Mathlib pinned and
    /// cached. Used by the Lean adapter as its working directory.
    #[serde(default)]
    pub lake_project: Option<String>,
    /// Optional elan toolchain passed as `+toolchain` to lake and lean.
    #[serde(default)]
    pub lean_toolchain: Option<String>,
}

fn default_ir_compiler() -> String {
    "smt-lib-v2.6".into()
}
fn default_version() -> String {
    "0".into()
}
fn default_ceta_binary() -> String {
    "ceta".into()
}
fn default_termination_prover() -> String {
    "aprove".into()
}
fn default_confluence_checker() -> String {
    "csi".into()
}

#[derive(Debug, Clone, Copy, Default, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum PortfolioMode {
    #[default]
    FirstWins,
    Consensus,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SolverSeat {
    Maude,
    Z3,
    Cvc5,
    Vampire,
    Coq,
    Lean,
    Bitwuzla,
    Yices2,
    Mathsat,
}

impl SolverSeat {
    pub const ALL: [Self; 9] = [
        Self::Maude,
        Self::Z3,
        Self::Cvc5,
        Self::Vampire,
        Self::Coq,
        Self::Lean,
        Self::Bitwuzla,
        Self::Yices2,
        Self::Mathsat,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Maude => "maude",
            Self::Z3 => "z3",
            Self::Cvc5 => "cvc5",
            Self::Vampire => "vampire",
            Self::Coq => "coq",
            Self::Lean => "lean",
            Self::Bitwuzla => "bitwuzla",
            Self::Yices2 => "yices2",
            Self::Mathsat => "mathsat",
        }
    }

    pub fn valid_seats() -> String {
        Self::ALL
            .into_iter()
            .map(Self::as_str)
            .collect::<Vec<_>>()
            .join(", ")
    }
}

impl fmt::Display for SolverSeat {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for SolverSeat {
    type Err = String;

    fn from_str(raw: &str) -> Result<Self, Self::Err> {
        match raw {
            "maude" => Ok(Self::Maude),
            "z3" => Ok(Self::Z3),
            "cvc5" => Ok(Self::Cvc5),
            "vampire" => Ok(Self::Vampire),
            "coq" => Ok(Self::Coq),
            "lean" => Ok(Self::Lean),
            "bitwuzla" => Ok(Self::Bitwuzla),
            "yices2" => Ok(Self::Yices2),
            "mathsat" => Ok(Self::Mathsat),
            _ => Err(format!(
                "unknown solver seat `{raw}`; valid seats: {}",
                Self::valid_seats()
            )),
        }
    }
}

impl<'de> Deserialize<'de> for SolverSeat {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let raw = String::deserialize(deserializer)?;
        raw.parse().map_err(de::Error::custom)
    }
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct DispatchConfig {
    #[serde(rename = "equational-theory", default)]
    pub equational_theory: Option<SolverSeat>,
    #[serde(rename = "first-order", default)]
    pub first_order: Option<SolverSeat>,
    #[serde(default)]
    pub strings: Option<SolverSeat>,
    #[serde(default)]
    pub bitvectors: Option<SolverSeat>,
    #[serde(rename = "linear-arithmetic", default)]
    pub linear_arithmetic: Option<SolverSeat>,
    #[serde(rename = "dependent-type", default)]
    pub dependent_type: Option<SolverSeat>,
    #[serde(rename = "categorical-structure", default)]
    pub categorical_structure: Option<SolverSeat>,
    #[serde(default)]
    pub default: Option<SolverSeat>,
}

/// Top-level `[solvers]` table model.
#[derive(Debug, Clone, Default, Deserialize)]
pub struct SolversConfig {
    #[serde(default)]
    pub default: Option<SolverSeat>,
    #[serde(default)]
    pub chain: Option<Vec<SolverSeat>>,
    #[serde(default)]
    pub portfolio: Option<Vec<SolverSeat>>,
    #[serde(default)]
    pub mode: Option<PortfolioMode>,
    /// Min number of distinct solvers that must have signed an
    /// implication memento before a Tier-2 cache hit is honored. Spec
    /// only in v0; the verifier does not yet enforce this gate.
    #[serde(default)]
    pub min_solver_witnesses: Option<usize>,
    #[serde(default)]
    pub dispatch: Option<DispatchConfig>,
    /// Per-solver configs, keyed by logical solver name.
    #[serde(flatten)]
    pub solvers: BTreeMap<SolverSeat, SolverConfig>,
}

impl SolversConfig {
    /// Load from `.sugar/config.toml` under `project_root`. Returns
    /// `Ok(None)` if the file or `[solvers]` table is absent.
    pub fn load(project_root: &Path) -> Result<Option<Self>, String> {
        let path = project_root.join(".sugar").join("config.toml");
        if !path.exists() {
            return Ok(None);
        }
        let body =
            std::fs::read_to_string(&path).map_err(|e| format!("read {}: {e}", path.display()))?;
        #[derive(Deserialize)]
        struct Outer {
            #[serde(default)]
            solvers: Option<SolversConfig>,
        }
        let outer: Outer = toml::from_str(&body).map_err(|e| format!("parse toml: {e}"))?;
        if let Some(cfg) = &outer.solvers {
            validate_vendor_pins(cfg)?;
        }
        Ok(outer.solvers)
    }

    pub fn from_toml(body: &str) -> Result<Self, String> {
        #[derive(Deserialize)]
        struct Outer {
            #[serde(default)]
            solvers: Option<SolversConfig>,
        }
        let outer: Outer = toml::from_str(body).map_err(|e| format!("parse toml: {e}"))?;
        let cfg = outer.solvers.unwrap_or_default();
        validate_vendor_pins(&cfg)?;
        Ok(cfg)
    }
}

fn validate_vendor_pins(cfg: &SolversConfig) -> Result<(), String> {
    for (name, solver) in &cfg.solvers {
        if let Some(cid) = solver.binary_cid.as_deref() {
            MementoCid::try_parse(cid.to_string()).map_err(|raw| {
                format!(
                    "solver `{name}` binary_cid must be a blake3-512 CID with 128 hex characters, got `{raw}`"
                )
            })?;
        }
        let Some(pin) = solver.vendor_pin.as_deref() else {
            continue;
        };
        if !has_vendor_pin_scheme(pin) {
            return Err(format!(
                "solver `{name}` vendor_pin must be explicitly scheme-prefixed, e.g. `sha256:<hex>`, `file:<path>`, `http:<url>`, or `simon_says:true`"
            ));
        }
    }
    Ok(())
}

fn has_vendor_pin_scheme(pin: &str) -> bool {
    pin.split_once(':')
        .map(|(scheme, rest)| !scheme.is_empty() && !rest.is_empty())
        .unwrap_or(false)
}

/// Compiled execution plan derived from `SolversConfig`. The runner
/// matches on this directly.
#[derive(Debug, Clone)]
pub enum SolverPlan {
    Single(SolverSeat),
    Chain(Vec<SolverSeat>),
    Portfolio {
        names: Vec<SolverSeat>,
        mode: PortfolioMode,
    },
    Dispatch(DispatchConfig),
}

impl SolverPlan {
    /// Derive a plan from a parsed `SolversConfig`. Precedence (first
    /// match wins): `default` -> `chain` -> `portfolio` -> `dispatch`.
    /// If none are set we fall back to single-solver `"z3"`.
    pub fn from_config(cfg: &SolversConfig) -> Self {
        if let Some(d) = &cfg.default {
            return SolverPlan::Single(d.clone());
        }
        if let Some(c) = &cfg.chain {
            if !c.is_empty() {
                return SolverPlan::Chain(c.clone());
            }
        }
        if let Some(p) = &cfg.portfolio {
            if !p.is_empty() {
                return SolverPlan::Portfolio {
                    names: p.clone(),
                    mode: cfg.mode.unwrap_or_default(),
                };
            }
        }
        if let Some(d) = &cfg.dispatch {
            return SolverPlan::Dispatch(d.clone());
        }
        SolverPlan::Single(SolverSeat::Z3)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_default_only() {
        let s = r#"
[solvers]
default = "z3"

[solvers.z3]
binary = "z3"
"#;
        let c = SolversConfig::from_toml(s).unwrap();
        assert_eq!(c.default, Some(SolverSeat::Z3));
        assert_eq!(c.solvers.get(&SolverSeat::Z3).unwrap().binary, "z3");
        match SolverPlan::from_config(&c) {
            SolverPlan::Single(n) => assert_eq!(n, SolverSeat::Z3),
            _ => panic!("expected Single"),
        }
    }

    #[test]
    fn parse_solver_artifact_cid_and_vendor_pin() {
        let s = r#"
[solvers]
default = "z3"

[solvers.z3]
binary = "z3"
binary_cid = "blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
vendor_pin = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
"#;
        let c = SolversConfig::from_toml(s).unwrap();
        let z3 = c.solvers.get(&SolverSeat::Z3).unwrap();
        assert_eq!(
            z3.binary_cid.as_deref(),
            Some("blake3-512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        );
        assert_eq!(
            z3.vendor_pin.as_deref(),
            Some("sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        );
    }

    #[test]
    fn rejects_solver_artifact_cid_with_bad_prefix() {
        let s = r#"
[solvers]
default = "z3"

[solvers.z3]
binary = "z3"
binary_cid = "sha512:not-a-sugar-cid"
"#;
        let err = SolversConfig::from_toml(s).expect_err("bad solver artifact CID prefix rejected");
        assert!(
            err.contains("binary_cid") && err.contains("sha512:not-a-sugar-cid"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn rejects_solver_artifact_cid_with_bad_hex() {
        let s = format!(
            r#"
[solvers]
default = "z3"

[solvers.z3]
binary = "z3"
binary_cid = "blake3-512:{}g"
"#,
            "a".repeat(127)
        );
        let err = SolversConfig::from_toml(&s).expect_err("bad solver artifact CID hex rejected");
        assert!(
            err.contains("binary_cid") && err.contains("blake3-512:"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn rejects_unprefixed_vendor_pin() {
        let s = r#"
[solvers]
default = "z3"

[solvers.z3]
binary = "z3"
vendor_pin = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
"#;
        let err = SolversConfig::from_toml(s).expect_err("unprefixed vendor pin rejected");
        assert!(
            err.contains("vendor_pin must be explicitly scheme-prefixed"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn parse_chain() {
        let s = r#"
[solvers]
chain = ["z3", "cvc5"]
"#;
        let c = SolversConfig::from_toml(s).unwrap();
        match SolverPlan::from_config(&c) {
            SolverPlan::Chain(v) => assert_eq!(v, vec![SolverSeat::Z3, SolverSeat::Cvc5]),
            _ => panic!("expected Chain"),
        }
    }

    #[test]
    fn parse_portfolio_consensus() {
        let s = r#"
[solvers]
portfolio = ["z3", "cvc5", "bitwuzla"]
mode = "consensus"
"#;
        let c = SolversConfig::from_toml(s).unwrap();
        match SolverPlan::from_config(&c) {
            SolverPlan::Portfolio { names, mode } => {
                assert_eq!(names.len(), 3);
                assert_eq!(mode, PortfolioMode::Consensus);
            }
            _ => panic!("expected Portfolio"),
        }
    }

    #[test]
    fn parse_dispatch() {
        let s = r#"
[solvers]
[solvers.dispatch]
"first-order" = "vampire"
strings = "cvc5"
bitvectors = "bitwuzla"
"linear-arithmetic" = "z3"
default = "z3"
"#;
        let c = SolversConfig::from_toml(s).unwrap();
        match SolverPlan::from_config(&c) {
            SolverPlan::Dispatch(d) => {
                assert_eq!(d.first_order, Some(SolverSeat::Vampire));
                assert_eq!(d.strings, Some(SolverSeat::Cvc5));
                assert_eq!(d.bitvectors, Some(SolverSeat::Bitwuzla));
                assert_eq!(d.linear_arithmetic, Some(SolverSeat::Z3));
                assert_eq!(d.default, Some(SolverSeat::Z3));
            }
            _ => panic!("expected Dispatch"),
        }
    }

    #[test]
    fn unknown_dispatch_seat_refused_at_config_parse() {
        let s = r#"
[solvers]
[solvers.dispatch]
strings = "cvv5"
default = "z3"
"#;
        let err = SolversConfig::from_toml(s).expect_err("unknown dispatch seat refused");
        assert!(
            err.contains("unknown solver seat `cvv5`"),
            "unexpected error: {err}"
        );
        assert!(
            err.contains("valid seats:"),
            "error should list valid seats: {err}"
        );
        for seat in SolverSeat::ALL.map(SolverSeat::as_str) {
            assert!(
                err.contains(seat),
                "error should list valid seat `{seat}`: {err}"
            );
        }
    }

    #[test]
    fn no_solvers_table_yields_default_z3() {
        let s = "";
        let c = SolversConfig::from_toml(s).unwrap();
        match SolverPlan::from_config(&c) {
            SolverPlan::Single(n) => assert_eq!(n, SolverSeat::Z3),
            _ => panic!("expected Single z3 fallback"),
        }
    }

    #[test]
    fn load_without_solvers_table_returns_none() {
        let root = std::env::temp_dir().join(format!(
            "sugar-solvers-config-{}-{}",
            std::process::id(),
            "no-solvers"
        ));
        let sugar_dir = root.join(".sugar");
        std::fs::create_dir_all(&sugar_dir).expect("create .sugar");
        std::fs::write(
            sugar_dir.join("config.toml"),
            "[authoring]\nsurface = \"rust\"\n",
        )
        .expect("write config");

        let loaded = SolversConfig::load(&root).expect("load config");
        let _ = std::fs::remove_dir_all(&root);

        assert!(
            loaded.is_none(),
            "a project config without [solvers] must fall back to the default z3 registry"
        );
    }
}

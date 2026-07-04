// SPDX-License-Identifier: MIT OR Apache-2.0

use sugar_ir_types::IrFormula;

use super::primitives::address;
use super::traits::{DischargeMode, Domain, DomainError, Kit, KitError, Portfolio, SolverVerdict};
use super::types::{
    any_sort, formula_true, memento_from_parts, Boundary, Contract, Dialect, DomainClaim,
    DomainKind, Input, Term, Verdict, Witness,
};

/// No-op solver portfolio for the initial pass.
///
/// This keeps primitive 7 well-typed while real solver orchestration remains
/// outside `libsugar`. It always returns `Unknown`.
#[derive(Debug, Clone, Copy, Default)]
pub struct NoopPortfolio;

impl Portfolio for NoopPortfolio {
    fn solve(&self, smt: &str) -> SolverVerdict {
        SolverVerdict::Unknown {
            transcript: serde_json::json!({
                "portfolio": "noop",
                "inputBytes": smt.len(),
            }),
        }
    }
}

/// Function-contract semantic domain.
///
/// `project` is a small WP-shaped stub: it handles trivial faithful terms by
/// building a `FunctionContractMemento` whose post states `result = <term>`.
/// `discharge(Search)` delegates to the supplied portfolio, while
/// `discharge(Check)` validates that a resolved claim carries a witness.
#[derive(Debug, Clone, Copy, Default)]
pub struct FunctionContractDomain;

impl Domain for FunctionContractDomain {
    fn name(&self) -> DomainKind {
        DomainKind::FunctionContract
    }

    fn project(&self, term: &Term, _boundary: &Boundary) -> Result<Contract, DomainError> {
        let fn_name = term_name(term);
        let formals = term_formals(term);
        let formal_sorts = formals.iter().map(|_| any_sort()).collect();
        let return_sort = any_sort();
        let post = IrFormula::Atomic {
            name: "=".to_string(),
            args: vec![
                sugar_ir_types::IrTerm::Var {
                    name: "result".to_string(),
                },
                sugar_ir_types::IrTerm::from(term.clone()),
            ],
        };
        let body_cid = Some(super::primitives::address(term).into_string());
        Ok(memento_from_parts(
            fn_name,
            formals,
            formal_sorts,
            return_sort,
            formula_true(),
            post,
            body_cid,
        ))
    }

    fn discharge(
        &self,
        mut claim: DomainClaim,
        mode: DischargeMode<'_>,
    ) -> Result<DomainClaim, DomainError> {
        match mode {
            DischargeMode::Search { portfolio } => {
                let smt = "(set-logic ALL)\n; libsugar core initial-pass obligation\n(check-sat)\n";
                match portfolio.solve(smt) {
                    SolverVerdict::Proved { transcript } => {
                        claim.verdict = Verdict::Proved;
                        claim.witness = Some(Witness::Proof { tree: transcript });
                    }
                    SolverVerdict::Refuted { model } => {
                        claim.verdict = Verdict::Refuted;
                        claim.witness = Some(Witness::Counterexample { model });
                    }
                    SolverVerdict::Unknown { transcript } => {
                        claim.verdict = Verdict::Unknown;
                        claim.witness = Some(Witness::Unknown { transcript });
                    }
                }
                Ok(claim)
            }
            DischargeMode::Check => {
                if claim.witness.is_none() {
                    return Err(DomainError::MissingWitness {
                        domain: DomainKind::FunctionContract,
                    });
                }
                Ok(claim)
            }
        }
    }
}

/// Stub C kit.
///
/// It parses `Input::Term` losslessly, parses source bytes as JSON `IrTerm`
/// when possible, and otherwise wraps source bytes as a constant. This is a
/// typed stand-in for the real C lifter subprocess.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CKit {
    dialect: Dialect,
}

impl Default for CKit {
    fn default() -> Self {
        Self {
            dialect: Dialect::C,
        }
    }
}

impl Kit for CKit {
    fn dialect(&self) -> Dialect {
        self.dialect.clone()
    }

    fn transform(&self, input: &Input) -> Result<DomainClaim, KitError> {
        transform_stub_input(&self.dialect, input)
    }

    fn prove(&self, claim: DomainClaim) -> Result<DomainClaim, KitError> {
        prove_stub_claim(claim)
    }

    fn parse(&self, input: &Input) -> Result<Term, KitError> {
        parse_stub_input(&self.dialect, input)
    }

    fn serialize(&self, term: &Term) -> Result<Input, KitError> {
        serialize_stub_term(self.dialect.clone(), term)
    }
}

/// Stub Rust kit.
///
/// The Rust lifter already exists elsewhere in the workspace. This core pass
/// exposes the kit trait and supplies the same trivial behavior as `CKit`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RustKit {
    dialect: Dialect,
}

impl Default for RustKit {
    fn default() -> Self {
        Self {
            dialect: Dialect::Rust,
        }
    }
}

impl Kit for RustKit {
    fn dialect(&self) -> Dialect {
        self.dialect.clone()
    }

    fn transform(&self, input: &Input) -> Result<DomainClaim, KitError> {
        transform_stub_input(&self.dialect, input)
    }

    fn prove(&self, claim: DomainClaim) -> Result<DomainClaim, KitError> {
        prove_stub_claim(claim)
    }

    fn parse(&self, input: &Input) -> Result<Term, KitError> {
        parse_stub_input(&self.dialect, input)
    }

    fn serialize(&self, term: &Term) -> Result<Input, KitError> {
        serialize_stub_term(self.dialect.clone(), term)
    }
}

fn transform_stub_input(expected: &Dialect, input: &Input) -> Result<DomainClaim, KitError> {
    let term = parse_stub_input(expected, input)?;
    let domain = FunctionContractDomain;
    let contract = domain
        .project(&term, &Boundary::default())
        .map_err(|error| KitError::Transformation(error.to_string()))?;
    let to = address(&contract);

    Ok(DomainClaim {
        domain: domain.name(),
        contract,
        artifacts: vec![address(&term)],
        from: vec![address(input)],
        premises: vec![],
        to,
        witness: None,
        payload: Some(term),
        verdict: Verdict::Unresolved,
        attestation: None,
    })
}

fn prove_stub_claim(claim: DomainClaim) -> Result<DomainClaim, KitError> {
    let portfolio = NoopPortfolio;
    FunctionContractDomain
        .discharge(
            claim,
            DischargeMode::Search {
                portfolio: &portfolio,
            },
        )
        .map_err(|error| KitError::Transformation(error.to_string()))
}

fn parse_stub_input(expected: &Dialect, input: &Input) -> Result<Term, KitError> {
    match input {
        Input::Term(term) => Ok(term.clone()),
        Input::Claim(claim) => Ok(artifact_reference_term("claim", &claim.artifacts)),
        Input::Truth(truth) => Ok(artifact_reference_term("truth", &truth.claim().artifacts)),
        Input::Refutation(refutation) => Ok(artifact_reference_term(
            "refutation",
            &refutation.claim().artifacts,
        )),
        Input::Spec(value) => Ok(Term::Const {
            value: value.clone(),
            sort: any_sort(),
        }),
        Input::Path(path) => Ok(Term::Const {
            value: serde_json::json!({
                "kind": "path",
                "pathCid": path.cid().as_str(),
                "steps": path.algebra.len(),
            }),
            sort: any_sort(),
        }),
        Input::Source { dialect, bytes } => {
            if dialect != expected {
                return Err(KitError::UnsupportedInput {
                    dialect: expected.clone(),
                    message: format!("source dialect was {dialect:?}"),
                });
            }
            if let Ok(ir) = serde_json::from_slice::<sugar_ir_types::IrTerm>(bytes) {
                return Ok(Term::from(ir));
            }
            Ok(Term::Const {
                value: serde_json::json!({
                    "dialect": format!("{dialect:?}"),
                    "bytesUtf8": String::from_utf8_lossy(bytes),
                }),
                sort: any_sort(),
            })
        }
    }
}

fn artifact_reference_term(kind: &str, artifacts: &[super::types::Cid]) -> Term {
    Term::Const {
        value: serde_json::json!({
            "kind": kind,
            "artifacts": artifacts.iter().map(|cid| cid.as_str()).collect::<Vec<_>>(),
        }),
        sort: any_sort(),
    }
}

fn serialize_stub_term(dialect: Dialect, term: &Term) -> Result<Input, KitError> {
    let ir = sugar_ir_types::IrTerm::from(term.clone());
    let bytes = serde_json::to_vec(&ir).map_err(|error| {
        KitError::Serialization(format!("serialize stub IR term as JSON: {error}"))
    })?;
    Ok(Input::Source { dialect, bytes })
}

fn term_name(term: &Term) -> String {
    match term {
        Term::Op { name, .. } => name.clone(),
        Term::Var { name } => name.clone(),
        Term::Const { .. } => "const".to_string(),
        Term::Unit => "unit".to_string(),
    }
}

fn term_formals(term: &Term) -> Vec<String> {
    match term {
        Term::Op { args, .. } => {
            let formals: Vec<String> = args
                .iter()
                .filter_map(|arg| match arg {
                    Term::Var { name } => Some(name.clone()),
                    _ => None,
                })
                .collect();
            if formals.is_empty() {
                vec!["input".to_string()]
            } else {
                formals
            }
        }
        Term::Var { name } => vec![name.clone()],
        Term::Const { .. } | Term::Unit => vec!["input".to_string()],
    }
}

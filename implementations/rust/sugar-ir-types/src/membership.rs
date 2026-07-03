// SPDX-License-Identifier: Apache-2.0
//
// ProofIR membership layer. These wrappers keep the generated Formula/Term DTO
// bytes unchanged while making claim construction carry scope, sort, role, and
// provenance evidence before a formula can enter typed compiler/proof seats.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::marker::PhantomData;

use serde::{Deserialize, Deserializer, Serialize, Serializer};

use crate::{Formula, Sort, Term};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ConstructionError {
    EmptyVarName,
    EmptyCallName,
    ConflictingVarSort {
        name: String,
        left: Sort,
        right: Sort,
    },
    IllegalFreeVars {
        vars: Vec<String>,
    },
    UnsortedVars {
        vars: Vec<String>,
    },
    MismatchedVarSort {
        name: String,
        carried: Sort,
        scoped: Sort,
    },
    MissingProvenance {
        field: &'static str,
    },
    MissingClaimRole,
}

impl fmt::Display for ConstructionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ConstructionError::EmptyVarName => write!(f, "ProofIR variable name must be non-empty"),
            ConstructionError::EmptyCallName => {
                write!(f, "ProofIR call term callee name must be non-empty")
            }
            ConstructionError::ConflictingVarSort { name, left, right } => write!(
                f,
                "ProofIR variable `{name}` carries conflicting sorts {left:?} and {right:?}"
            ),
            ConstructionError::IllegalFreeVars { vars } => write!(
                f,
                "ProofIR formula has free vars outside its declared scope: {}",
                vars.join(", ")
            ),
            ConstructionError::UnsortedVars { vars } => write!(
                f,
                "ProofIR formula has free vars without carried sorts: {}",
                vars.join(", ")
            ),
            ConstructionError::MismatchedVarSort {
                name,
                carried,
                scoped,
            } => write!(
                f,
                "ProofIR variable `{name}` carries sort {carried:?} but scope declares {scoped:?}"
            ),
            ConstructionError::MissingProvenance { field } => {
                write!(f, "ProofIR provenance field `{field}` must be non-empty")
            }
            ConstructionError::MissingClaimRole => {
                write!(f, "ProofIR claim formula role must be non-empty")
            }
        }
    }
}

impl std::error::Error for ConstructionError {}

pub trait SortWitness: Clone + fmt::Debug + Eq + 'static {
    fn sort() -> Sort;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct IntSort;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RealSort;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BoolSort;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StringSort;

impl SortWitness for IntSort {
    fn sort() -> Sort {
        primitive_sort("Int")
    }
}

impl SortWitness for RealSort {
    fn sort() -> Sort {
        primitive_sort("Real")
    }
}

impl SortWitness for BoolSort {
    fn sort() -> Sort {
        primitive_sort("Bool")
    }
}

impl SortWitness for StringSort {
    fn sort() -> Sort {
        primitive_sort("String")
    }
}

fn primitive_sort(name: &str) -> Sort {
    Sort::Primitive {
        name: name.to_string(),
    }
}

fn unknown_sort() -> Sort {
    primitive_sort("Unknown")
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TypedTerm<S: SortWitness> {
    term: Term,
    free_var_sorts: BTreeMap<String, Sort>,
    _sort: PhantomData<S>,
}

impl<S: SortWitness> TypedTerm<S> {
    pub fn term(&self) -> &Term {
        &self.term
    }

    pub fn into_inner(self) -> Term {
        self.term
    }

    pub fn sort(&self) -> Sort {
        S::sort()
    }

    pub fn erased(&self) -> ErasedTerm {
        ErasedTerm {
            term: self.term.clone(),
            free_var_sorts: self.free_var_sorts.clone(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ErasedTerm {
    term: Term,
    free_var_sorts: BTreeMap<String, Sort>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VarTerm<S: SortWitness> {
    typed: TypedTerm<S>,
    name: String,
}

impl<S: SortWitness> VarTerm<S> {
    pub fn new(name: impl Into<String>) -> Result<Self, ConstructionError> {
        let name = name.into();
        if name.trim().is_empty() {
            return Err(ConstructionError::EmptyVarName);
        }
        let mut free_var_sorts = BTreeMap::new();
        free_var_sorts.insert(name.clone(), S::sort());
        Ok(Self {
            typed: TypedTerm {
                term: Term::Var { name: name.clone() },
                free_var_sorts,
                _sort: PhantomData,
            },
            name,
        })
    }

    pub fn into_typed(self) -> TypedTerm<S> {
        self.typed
    }

    pub fn name(&self) -> &str {
        &self.name
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConstTerm<S: SortWitness> {
    typed: TypedTerm<S>,
}

impl ConstTerm<IntSort> {
    pub fn int(value: i128) -> Self {
        Self {
            typed: const_term(json_int_value(value)),
        }
    }
}

impl ConstTerm<RealSort> {
    pub fn real(value: impl Into<String>) -> Self {
        Self {
            typed: const_term(serde_json::Value::String(value.into())),
        }
    }
}

impl ConstTerm<BoolSort> {
    pub fn bool(value: bool) -> Self {
        Self {
            typed: const_term(serde_json::Value::Bool(value)),
        }
    }
}

impl ConstTerm<StringSort> {
    pub fn string(value: impl Into<String>) -> Self {
        Self {
            typed: const_term(serde_json::Value::String(value.into())),
        }
    }
}

impl<S: SortWitness> ConstTerm<S> {
    pub fn into_typed(self) -> TypedTerm<S> {
        self.typed
    }
}

fn const_term<S: SortWitness>(value: serde_json::Value) -> TypedTerm<S> {
    TypedTerm {
        term: Term::Const {
            value,
            sort: S::sort(),
        },
        free_var_sorts: BTreeMap::new(),
        _sort: PhantomData,
    }
}

fn json_int_value(value: i128) -> serde_json::Value {
    if let Ok(value) = i64::try_from(value) {
        serde_json::Value::Number(value.into())
    } else if let Ok(value) = u64::try_from(value) {
        serde_json::Value::Number(value.into())
    } else {
        serde_json::Value::String(value.to_string())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CallTerm<S: SortWitness> {
    typed: TypedTerm<S>,
    callee_name: String,
    args: Vec<ErasedTerm>,
}

impl<S: SortWitness> CallTerm<S> {
    pub fn new(
        callee_name: impl Into<String>,
        args: Vec<ErasedTerm>,
    ) -> Result<Self, ConstructionError> {
        let callee_name = callee_name.into();
        if callee_name.trim().is_empty() {
            return Err(ConstructionError::EmptyCallName);
        }
        let free_var_sorts = merge_var_sorts(args.iter().map(|arg| &arg.free_var_sorts))?;
        let term = Term::Ctor {
            name: format!("call:{callee_name}"),
            args: args.iter().map(|arg| arg.term.clone()).collect(),
        };
        Ok(Self {
            typed: TypedTerm {
                term,
                free_var_sorts,
                _sort: PhantomData,
            },
            callee_name,
            args,
        })
    }

    pub fn sort(&self) -> Sort {
        S::sort()
    }

    pub fn into_typed(self) -> TypedTerm<S> {
        self.typed
    }

    pub fn callee_name(&self) -> &str {
        &self.callee_name
    }
}

impl<S: SortWitness> From<TypedTerm<S>> for ErasedTerm {
    fn from(value: TypedTerm<S>) -> Self {
        Self {
            term: value.term,
            free_var_sorts: value.free_var_sorts,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EqualityFact<S: SortWitness> {
    call_term: CallTerm<S>,
    rhs_term: TypedTerm<S>,
    open: OpenFormula,
}

impl<S: SortWitness> EqualityFact<S> {
    pub fn new(call_term: CallTerm<S>, rhs_term: TypedTerm<S>) -> Self {
        let (formula, free_var_sorts) = equality_formula(call_term.typed.clone(), rhs_term.clone());
        Self {
            call_term,
            rhs_term,
            open: OpenFormula {
                formula,
                free_var_sorts,
            },
        }
    }

    pub fn into_open_formula(self) -> OpenFormula {
        self.open
    }

    pub fn call_term(&self) -> &CallTerm<S> {
        &self.call_term
    }

    pub fn rhs_term(&self) -> &TypedTerm<S> {
        &self.rhs_term
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpenFormula {
    formula: Formula,
    free_var_sorts: BTreeMap<String, Sort>,
}

impl OpenFormula {
    pub fn from_equality_terms<S: SortWitness>(left: TypedTerm<S>, right: TypedTerm<S>) -> Self {
        let (formula, free_var_sorts) = equality_formula(left, right);
        Self {
            formula,
            free_var_sorts,
        }
    }

    pub fn from_ir_formula_with_sorts(
        formula: Formula,
        free_var_sorts: BTreeMap<String, Sort>,
    ) -> Self {
        Self {
            formula,
            free_var_sorts,
        }
    }

    pub fn scope(
        self,
        allowed_vars: BTreeMap<String, Sort>,
    ) -> Result<ScopedFormula, ConstructionError> {
        let free_vars = self.free_vars();
        let illegal = free_vars
            .difference(&allowed_vars.keys().cloned().collect())
            .cloned()
            .collect::<Vec<_>>();
        if !illegal.is_empty() {
            return Err(ConstructionError::IllegalFreeVars { vars: illegal });
        }

        let unsorted = free_vars
            .iter()
            .filter(|name| !self.free_var_sorts.contains_key(*name))
            .cloned()
            .collect::<Vec<_>>();
        if !unsorted.is_empty() {
            return Err(ConstructionError::UnsortedVars { vars: unsorted });
        }

        for name in &free_vars {
            let carried = self.free_var_sorts.get(name).expect("checked above");
            let scoped = allowed_vars.get(name).expect("checked illegal vars above");
            if carried != scoped {
                return Err(ConstructionError::MismatchedVarSort {
                    name: name.clone(),
                    carried: carried.clone(),
                    scoped: scoped.clone(),
                });
            }
        }

        Ok(ScopedFormula {
            open: self,
            allowed_vars,
        })
    }

    pub fn formula(&self) -> &Formula {
        &self.formula
    }

    pub fn free_vars(&self) -> BTreeSet<String> {
        free_vars_in_formula(&self.formula)
    }

    pub fn free_var_sorts(&self) -> &BTreeMap<String, Sort> {
        &self.free_var_sorts
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScopedFormula {
    open: OpenFormula,
    allowed_vars: BTreeMap<String, Sort>,
}

impl ScopedFormula {
    pub fn close(self) -> ClosedFormula {
        ClosedFormula { scoped: self }
    }

    pub fn formula(&self) -> &OpenFormula {
        &self.open
    }

    pub fn allowed_vars(&self) -> &BTreeMap<String, Sort> {
        &self.allowed_vars
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClosedFormula {
    scoped: ScopedFormula,
}

impl ClosedFormula {
    pub fn with_provenance(
        self,
        provenance: FormulaProvenance,
    ) -> Result<ProvenancedFormula, ConstructionError> {
        provenance.validate()?;
        Ok(ProvenancedFormula {
            closed: self,
            provenance,
        })
    }

    pub fn formula(&self) -> &Formula {
        self.scoped.open.formula()
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum ProvenanceKind {
    Stated,
    Derived,
    Source,
    FrontendTransport,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FormulaProvenance {
    kind: ProvenanceKind,
    owner: String,
    detail: String,
}

impl FormulaProvenance {
    pub fn new(
        kind: ProvenanceKind,
        owner: impl Into<String>,
        detail: impl Into<String>,
    ) -> Result<Self, ConstructionError> {
        let provenance = Self {
            kind,
            owner: owner.into(),
            detail: detail.into(),
        };
        provenance.validate()?;
        Ok(provenance)
    }

    pub fn kind(&self) -> ProvenanceKind {
        self.kind.clone()
    }

    pub fn owner(&self) -> &str {
        &self.owner
    }

    pub fn detail(&self) -> &str {
        &self.detail
    }

    fn validate(&self) -> Result<(), ConstructionError> {
        if self.owner.trim().is_empty() {
            return Err(ConstructionError::MissingProvenance { field: "owner" });
        }
        if self.detail.trim().is_empty() {
            return Err(ConstructionError::MissingProvenance { field: "detail" });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Eq)]
pub struct ProvenancedFormula {
    closed: ClosedFormula,
    provenance: FormulaProvenance,
}

impl PartialEq for ProvenancedFormula {
    fn eq(&self, other: &Self) -> bool {
        self.closed.formula() == other.closed.formula()
    }
}

impl ProvenancedFormula {
    pub fn claim(self, role: impl Into<String>) -> Result<ClaimFormula, ConstructionError> {
        ClaimFormula::from_provenanced(self, role)
    }

    pub fn formula(&self) -> &Formula {
        self.closed.formula()
    }

    pub fn provenance(&self) -> &FormulaProvenance {
        &self.provenance
    }
}

#[derive(Debug, Clone, Eq)]
pub struct ClaimFormula {
    provenanced: ProvenancedFormula,
    role: String,
}

impl PartialEq for ClaimFormula {
    fn eq(&self, other: &Self) -> bool {
        self.formula() == other.formula()
    }
}

impl ClaimFormula {
    pub fn from_provenanced(
        provenanced: ProvenancedFormula,
        role: impl Into<String>,
    ) -> Result<Self, ConstructionError> {
        let role = role.into();
        if role.trim().is_empty() {
            return Err(ConstructionError::MissingClaimRole);
        }
        Ok(Self { provenanced, role })
    }

    pub fn from_frontend_transport(
        formula: Formula,
        owner: impl Into<String>,
    ) -> Result<Self, ConstructionError> {
        let mut scope = BTreeMap::new();
        for name in free_vars_in_formula(&formula) {
            scope.insert(name, unknown_sort());
        }
        OpenFormula::from_ir_formula_with_sorts(formula, scope.clone())
            .scope(scope)?
            .close()
            .with_provenance(FormulaProvenance::new(
                ProvenanceKind::FrontendTransport,
                owner,
                "ProofIR transport formula decoded by typed frontend",
            )?)?
            .claim("compiler-input-formula")
    }

    pub fn formula(&self) -> &Formula {
        self.provenanced.formula()
    }

    pub fn into_formula(self) -> Formula {
        self.provenanced.closed.scoped.open.formula
    }

    pub fn provenance(&self) -> &FormulaProvenance {
        self.provenanced.provenance()
    }

    pub fn role(&self) -> &str {
        &self.role
    }
}

impl Serialize for ClaimFormula {
    fn serialize<T>(&self, serializer: T) -> Result<T::Ok, T::Error>
    where
        T: Serializer,
    {
        self.formula().serialize(serializer)
    }
}

impl<'de> Deserialize<'de> for ClaimFormula {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let formula = Formula::deserialize(deserializer)?;
        ClaimFormula::from_frontend_transport(formula, "serde::Deserialize")
            .map_err(serde::de::Error::custom)
    }
}

fn equality_formula<S: SortWitness>(
    left: TypedTerm<S>,
    right: TypedTerm<S>,
) -> (Formula, BTreeMap<String, Sort>) {
    let free_var_sorts = merge_var_sorts([&left.free_var_sorts, &right.free_var_sorts])
        .expect("TypedTerm construction prevents conflicting sorts");
    (
        Formula::Atomic {
            name: "=".to_string(),
            args: vec![left.term, right.term],
        },
        free_var_sorts,
    )
}

fn merge_var_sorts<'a>(
    maps: impl IntoIterator<Item = &'a BTreeMap<String, Sort>>,
) -> Result<BTreeMap<String, Sort>, ConstructionError> {
    let mut merged: BTreeMap<String, Sort> = BTreeMap::new();
    for map in maps {
        for (name, sort) in map {
            if let Some(previous) = merged.get(name) {
                if previous != sort {
                    return Err(ConstructionError::ConflictingVarSort {
                        name: name.clone(),
                        left: previous.clone(),
                        right: sort.clone(),
                    });
                }
            }
            merged.insert(name.clone(), sort.clone());
        }
    }
    Ok(merged)
}

fn free_vars_in_formula(formula: &Formula) -> BTreeSet<String> {
    match formula {
        Formula::Atomic { args, .. } => args.iter().flat_map(free_vars_in_term).collect(),
        Formula::And { operands }
        | Formula::Or { operands }
        | Formula::Not { operands }
        | Formula::Implies { operands } => operands.iter().flat_map(free_vars_in_formula).collect(),
        Formula::Forall { name, body, .. } | Formula::Exists { name, body, .. } => {
            let mut vars = free_vars_in_formula(body);
            vars.remove(name);
            vars
        }
        Formula::Choice { var_name, body, .. } => {
            let mut vars = free_vars_in_formula(body);
            vars.remove(var_name);
            vars
        }
        Formula::Substitute { target, term, var } => {
            let mut vars = free_vars_in_formula(target);
            vars.remove(var);
            vars.extend(free_vars_in_term(term));
            vars
        }
        Formula::Apply { args, .. } => args.iter().flat_map(free_vars_in_formula).collect(),
        Formula::DivergenceBetween { source, target } => {
            let mut vars = free_vars_in_formula(source);
            vars.extend(free_vars_in_formula(target));
            vars
        }
    }
}

fn free_vars_in_term(term: &Term) -> BTreeSet<String> {
    match term {
        Term::Var { name } => BTreeSet::from([name.clone()]),
        Term::Const { .. } => BTreeSet::new(),
        Term::Ctor { args, .. } => args.iter().flat_map(free_vars_in_term).collect(),
        Term::Lambda {
            param_name, body, ..
        } => {
            let mut vars = free_vars_in_term(body);
            vars.remove(param_name);
            vars
        }
        Term::Let { bindings, body } => {
            let mut vars = free_vars_in_term(body);
            for binding in bindings {
                vars.extend(free_vars_in_term(&binding.bound_term));
                vars.remove(&binding.name);
            }
            vars
        }
    }
}

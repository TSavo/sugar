// SPDX-License-Identifier: Apache-2.0
//
// Sugar-owned recognition claims. Each Sugar module exports the claim(s) for
// the source positions it owns; the factory only brokers over these claims.

use syn::{Expr, Item};

use crate::sugar::factory::SugarBuildCtx;
use crate::Sugar;

/// The source-position role a Sugar claim serves. Recognition itself lives in the
/// Sugar module that exports the claim.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum SugarRole {
    Term,
    Composite,
    Constraint,
    AssertionSurface,
    SupportConstraint,
    StatementEffect,
    ClosureAdaptorVerdict,
    MatchScrutineeVerdict,
    StatementItem,
}

/// Sugar-declared candidate priority. Lower is better: a specific method-call
/// decomposition outranks the generic `method:` fallback, while overlapping
/// specific sugars can still declare their own precedence.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum SugarPriority {
    Primary = 1,
    Secondary = 2,
    Tertiary = 3,
    Quaternary = 4,
    Fallback = 100,
}

type ExprRecognizer = fn(&Expr, &SugarBuildCtx) -> Option<Box<dyn Sugar>>;
type ItemRecognizer = fn(&Item, &SugarBuildCtx) -> Option<Box<dyn Sugar>>;

/// A Sugar's claim that it knows how to recognize one source-expression position.
#[derive(Clone, Copy)]
pub(crate) struct ExprSugarClaim {
    #[allow(dead_code)]
    name: &'static str,
    role: SugarRole,
    priority: SugarPriority,
    recognize: ExprRecognizer,
}

impl ExprSugarClaim {
    pub(crate) const fn new(
        name: &'static str,
        role: SugarRole,
        priority: SugarPriority,
        recognize: ExprRecognizer,
    ) -> Self {
        Self {
            name,
            role,
            priority,
            recognize,
        }
    }

    pub(crate) const fn term(name: &'static str, recognize: ExprRecognizer) -> Self {
        Self::new(name, SugarRole::Term, SugarPriority::Primary, recognize)
    }

    pub(crate) const fn composite(name: &'static str, recognize: ExprRecognizer) -> Self {
        Self::new(
            name,
            SugarRole::Composite,
            SugarPriority::Primary,
            recognize,
        )
    }

    pub(crate) const fn constraint(name: &'static str, recognize: ExprRecognizer) -> Self {
        Self::new(
            name,
            SugarRole::Constraint,
            SugarPriority::Primary,
            recognize,
        )
    }

    pub(crate) const fn statement_effect(name: &'static str, recognize: ExprRecognizer) -> Self {
        Self::new(
            name,
            SugarRole::StatementEffect,
            SugarPriority::Primary,
            recognize,
        )
    }

    pub(crate) const fn closure_adaptor_verdict(
        name: &'static str,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::new(
            name,
            SugarRole::ClosureAdaptorVerdict,
            SugarPriority::Primary,
            recognize,
        )
    }

    pub(crate) const fn match_scrutinee_verdict(
        name: &'static str,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::new(
            name,
            SugarRole::MatchScrutineeVerdict,
            SugarPriority::Primary,
            recognize,
        )
    }

    pub(crate) const fn fallback_term(name: &'static str, recognize: ExprRecognizer) -> Self {
        Self::new(name, SugarRole::Term, SugarPriority::Fallback, recognize)
    }

    pub(crate) const fn secondary_term(name: &'static str, recognize: ExprRecognizer) -> Self {
        Self::new(name, SugarRole::Term, SugarPriority::Secondary, recognize)
    }

    pub(crate) const fn secondary_composite(name: &'static str, recognize: ExprRecognizer) -> Self {
        Self::new(
            name,
            SugarRole::Composite,
            SugarPriority::Secondary,
            recognize,
        )
    }

    pub(crate) fn role(&self) -> SugarRole {
        self.role
    }
}

/// A Sugar's claim that it knows how to recognize one source-item position.
#[derive(Clone, Copy)]
pub(crate) struct ItemSugarClaim {
    #[allow(dead_code)]
    name: &'static str,
    role: SugarRole,
    priority: SugarPriority,
    recognize: ItemRecognizer,
}

impl ItemSugarClaim {
    pub(crate) const fn new(
        name: &'static str,
        role: SugarRole,
        priority: SugarPriority,
        recognize: ItemRecognizer,
    ) -> Self {
        Self {
            name,
            role,
            priority,
            recognize,
        }
    }

    pub(crate) const fn statement_item(name: &'static str, recognize: ItemRecognizer) -> Self {
        Self::new(
            name,
            SugarRole::StatementItem,
            SugarPriority::Primary,
            recognize,
        )
    }

    pub(crate) fn role(&self) -> SugarRole {
        self.role
    }

    pub(crate) fn candidate(
        &'static self,
        item: &Item,
        fcx: &SugarBuildCtx,
    ) -> Option<SugarCandidate> {
        (self.recognize)(item, fcx).map(|node| SugarCandidate {
            name: self.name,
            role: self.role,
            priority: self.priority,
            node,
        })
    }
}

/// One Sugar claim that matched a source position.
pub(crate) struct SugarCandidate {
    name: &'static str,
    role: SugarRole,
    priority: SugarPriority,
    node: Box<dyn Sugar>,
}

impl SugarCandidate {
    #[allow(dead_code)]
    pub(crate) fn name(&self) -> &'static str {
        self.name
    }

    pub(crate) fn role(&self) -> SugarRole {
        self.role
    }

    pub(crate) fn priority(&self) -> SugarPriority {
        self.priority
    }

    pub(crate) fn into_node(self) -> Box<dyn Sugar> {
        self.node
    }
}

impl ExprSugarClaim {
    pub(crate) fn candidate(
        &'static self,
        expr: &Expr,
        fcx: &SugarBuildCtx,
    ) -> Option<SugarCandidate> {
        (self.recognize)(expr, fcx).map(|node| SugarCandidate {
            name: self.name,
            role: self.role,
            priority: self.priority,
            node,
        })
    }
}

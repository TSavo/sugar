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

type ExprRecognizer = fn(&Expr, &SugarBuildCtx) -> Option<Box<dyn Sugar>>;
type ItemRecognizer = fn(&Item, &SugarBuildCtx) -> Option<Box<dyn Sugar>>;

/// A Sugar's claim that it knows how to recognize one source-expression position.
#[derive(Clone, Copy)]
pub(crate) struct ExprSugarClaim {
    #[allow(dead_code)]
    name: &'static str,
    role: SugarRole,
    comes_before: &'static [&'static str],
    fallback_well: bool,
    recognize: ExprRecognizer,
}

impl ExprSugarClaim {
    pub(crate) const fn new(
        name: &'static str,
        role: SugarRole,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::with_ordering(name, role, &[], recognize)
    }

    pub(crate) const fn with_ordering(
        name: &'static str,
        role: SugarRole,
        comes_before: &'static [&'static str],
        recognize: ExprRecognizer,
    ) -> Self {
        Self {
            name,
            role,
            comes_before,
            fallback_well: false,
            recognize,
        }
    }

    pub(crate) const fn fallback_with_ordering(
        name: &'static str,
        role: SugarRole,
        comes_before: &'static [&'static str],
        recognize: ExprRecognizer,
    ) -> Self {
        Self {
            name,
            role,
            comes_before,
            fallback_well: true,
            recognize,
        }
    }

    pub(crate) const fn term(name: &'static str, recognize: ExprRecognizer) -> Self {
        Self::new(name, SugarRole::Term, recognize)
    }

    pub(crate) const fn term_before(
        name: &'static str,
        comes_before: &'static [&'static str],
        recognize: ExprRecognizer,
    ) -> Self {
        Self::with_ordering(name, SugarRole::Term, comes_before, recognize)
    }

    pub(crate) const fn composite(name: &'static str, recognize: ExprRecognizer) -> Self {
        Self::new(name, SugarRole::Composite, recognize)
    }

    pub(crate) const fn composite_before(
        name: &'static str,
        comes_before: &'static [&'static str],
        recognize: ExprRecognizer,
    ) -> Self {
        Self::with_ordering(name, SugarRole::Composite, comes_before, recognize)
    }

    pub(crate) const fn constraint(name: &'static str, recognize: ExprRecognizer) -> Self {
        Self::new(name, SugarRole::Constraint, recognize)
    }

    pub(crate) const fn constraint_before(
        name: &'static str,
        comes_before: &'static [&'static str],
        recognize: ExprRecognizer,
    ) -> Self {
        Self::with_ordering(name, SugarRole::Constraint, comes_before, recognize)
    }

    pub(crate) const fn statement_effect(name: &'static str, recognize: ExprRecognizer) -> Self {
        Self::new(name, SugarRole::StatementEffect, recognize)
    }

    pub(crate) const fn statement_effect_before(
        name: &'static str,
        comes_before: &'static [&'static str],
        recognize: ExprRecognizer,
    ) -> Self {
        Self::with_ordering(name, SugarRole::StatementEffect, comes_before, recognize)
    }

    pub(crate) const fn closure_adaptor_verdict(
        name: &'static str,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::new(name, SugarRole::ClosureAdaptorVerdict, recognize)
    }

    pub(crate) const fn closure_adaptor_verdict_before(
        name: &'static str,
        comes_before: &'static [&'static str],
        recognize: ExprRecognizer,
    ) -> Self {
        Self::with_ordering(
            name,
            SugarRole::ClosureAdaptorVerdict,
            comes_before,
            recognize,
        )
    }

    pub(crate) const fn match_scrutinee_verdict(
        name: &'static str,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::new(name, SugarRole::MatchScrutineeVerdict, recognize)
    }

    pub(crate) const fn fallback_term(name: &'static str, recognize: ExprRecognizer) -> Self {
        Self::fallback_with_ordering(name, SugarRole::Term, &[], recognize)
    }

    pub(crate) const fn fallback_composite(name: &'static str, recognize: ExprRecognizer) -> Self {
        Self::fallback_with_ordering(name, SugarRole::Composite, &[], recognize)
    }

    pub(crate) const fn fallback_constraint(name: &'static str, recognize: ExprRecognizer) -> Self {
        Self::fallback_with_ordering(name, SugarRole::Constraint, &[], recognize)
    }

    pub(crate) const fn fallback_assertion_surface(
        name: &'static str,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::fallback_with_ordering(name, SugarRole::AssertionSurface, &[], recognize)
    }

    pub(crate) fn role(&self) -> SugarRole {
        self.role
    }

    pub(crate) fn name(&self) -> &'static str {
        self.name
    }
}

/// A Sugar's claim that it knows how to recognize one source-item position.
#[derive(Clone, Copy)]
pub(crate) struct ItemSugarClaim {
    #[allow(dead_code)]
    name: &'static str,
    role: SugarRole,
    comes_before: &'static [&'static str],
    fallback_well: bool,
    recognize: ItemRecognizer,
}

impl ItemSugarClaim {
    pub(crate) const fn new(
        name: &'static str,
        role: SugarRole,
        recognize: ItemRecognizer,
    ) -> Self {
        Self::with_ordering(name, role, &[], recognize)
    }

    pub(crate) const fn with_ordering(
        name: &'static str,
        role: SugarRole,
        comes_before: &'static [&'static str],
        recognize: ItemRecognizer,
    ) -> Self {
        Self {
            name,
            role,
            comes_before,
            fallback_well: false,
            recognize,
        }
    }

    pub(crate) const fn statement_item(name: &'static str, recognize: ItemRecognizer) -> Self {
        Self::new(name, SugarRole::StatementItem, recognize)
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
            comes_before: self.comes_before,
            fallback_well: self.fallback_well,
            node,
        })
    }
}

/// One Sugar claim that matched a source position.
pub(crate) struct SugarCandidate {
    name: &'static str,
    role: SugarRole,
    comes_before: &'static [&'static str],
    fallback_well: bool,
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

    pub(crate) fn comes_before(&self) -> &'static [&'static str] {
        self.comes_before
    }

    pub(crate) fn is_fallback_well(&self) -> bool {
        self.fallback_well
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
            comes_before: self.comes_before,
            fallback_well: self.fallback_well,
            node,
        })
    }
}

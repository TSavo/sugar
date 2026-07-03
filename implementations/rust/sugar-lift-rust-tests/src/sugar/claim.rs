// SPDX-License-Identifier: Apache-2.0
//
// Sugar-owned recognition claims. Each Sugar module exports the claim(s) for
// the source positions it owns; the factory only brokers over these claims.

use syn::{Expr, Item, Stmt};

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::SourceFragment;
use crate::Sugar;

/// The source-position role a Sugar claim serves. Recognition itself lives in the
/// Sugar module that exports the claim.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum SugarRole {
    Term,
    Composite,
    Constraint,
    AssertionSurface,
    TupleProducer,
    SupportConstraint,
    StatementEffect,
    Statement,
    ClosureAdaptorVerdict,
    MatchScrutineeVerdict,
    StatementItem,
}

type ExprRecognizer = fn(&SourceFragment, &SugarBuildCtx) -> Option<Box<dyn Sugar>>;
type ItemRecognizer = fn(&SourceFragment, &SugarBuildCtx) -> Option<Box<dyn Sugar>>;
type StmtRecognizer = fn(&SourceFragment, &SugarBuildCtx) -> Option<Box<dyn Sugar>>;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SugarWitnesses {
    Pair {
        truthful: &'static str,
        lying: &'static str,
    },
    NotVerdictBearing {
        floor: &'static str,
        reason: &'static str,
    },
    TemporalOptOut {
        floor: &'static str,
        reason: &'static str,
        retirement: &'static str,
    },
    ReasonedBucket {
        blocker: &'static str,
    },
    PinnedCatch {
        family: &'static str,
    },
    TemporalCampaign {
        slice: &'static str,
    },
}

impl SugarWitnesses {
    pub const fn pair(truthful: &'static str, lying: &'static str) -> Self {
        Self::Pair { truthful, lying }
    }

    pub const fn not_verdict_bearing(floor: &'static str, reason: &'static str) -> Self {
        Self::NotVerdictBearing { floor, reason }
    }

    pub const fn temporal_opt_out(
        floor: &'static str,
        reason: &'static str,
        retirement: &'static str,
    ) -> Self {
        Self::TemporalOptOut {
            floor,
            reason,
            retirement,
        }
    }

    pub const fn reasoned_bucket(blocker: &'static str) -> Self {
        Self::ReasonedBucket { blocker }
    }

    pub const fn pinned_catch(family: &'static str) -> Self {
        Self::PinnedCatch { family }
    }

    pub const fn temporal_campaign(slice: &'static str) -> Self {
        Self::TemporalCampaign { slice }
    }
}

/// A Sugar's claim that it knows how to recognize one source-expression position.
#[derive(Clone, Copy)]
pub struct ExprSugarClaim {
    #[allow(dead_code)]
    name: &'static str,
    role: SugarRole,
    comes_before: &'static [&'static str],
    fallback_well: bool,
    witnesses: SugarWitnesses,
    recognize: ExprRecognizer,
}

impl ExprSugarClaim {
    pub(crate) const fn new(
        name: &'static str,
        role: SugarRole,
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::with_ordering(name, role, &[], witnesses, recognize)
    }

    pub(crate) const fn with_ordering(
        name: &'static str,
        role: SugarRole,
        comes_before: &'static [&'static str],
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self {
            name,
            role,
            comes_before,
            fallback_well: false,
            witnesses,
            recognize,
        }
    }

    pub(crate) const fn fallback_with_ordering(
        name: &'static str,
        role: SugarRole,
        comes_before: &'static [&'static str],
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self {
            name,
            role,
            comes_before,
            fallback_well: true,
            witnesses,
            recognize,
        }
    }

    pub(crate) const fn term(
        name: &'static str,
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::new(name, SugarRole::Term, witnesses, recognize)
    }

    pub(crate) const fn term_before(
        name: &'static str,
        comes_before: &'static [&'static str],
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::with_ordering(name, SugarRole::Term, comes_before, witnesses, recognize)
    }

    pub(crate) const fn composite(
        name: &'static str,
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::new(name, SugarRole::Composite, witnesses, recognize)
    }

    pub(crate) const fn composite_before(
        name: &'static str,
        comes_before: &'static [&'static str],
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::with_ordering(
            name,
            SugarRole::Composite,
            comes_before,
            witnesses,
            recognize,
        )
    }

    pub(crate) const fn constraint(
        name: &'static str,
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::new(name, SugarRole::Constraint, witnesses, recognize)
    }

    pub(crate) const fn constraint_before(
        name: &'static str,
        comes_before: &'static [&'static str],
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::with_ordering(
            name,
            SugarRole::Constraint,
            comes_before,
            witnesses,
            recognize,
        )
    }

    pub(crate) const fn tuple_producer(
        name: &'static str,
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::new(name, SugarRole::TupleProducer, witnesses, recognize)
    }

    pub(crate) const fn statement_effect(
        name: &'static str,
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::new(name, SugarRole::StatementEffect, witnesses, recognize)
    }

    pub(crate) const fn statement_effect_before(
        name: &'static str,
        comes_before: &'static [&'static str],
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::with_ordering(
            name,
            SugarRole::StatementEffect,
            comes_before,
            witnesses,
            recognize,
        )
    }

    pub(crate) const fn closure_adaptor_verdict(
        name: &'static str,
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::new(name, SugarRole::ClosureAdaptorVerdict, witnesses, recognize)
    }

    pub(crate) const fn closure_adaptor_verdict_before(
        name: &'static str,
        comes_before: &'static [&'static str],
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::with_ordering(
            name,
            SugarRole::ClosureAdaptorVerdict,
            comes_before,
            witnesses,
            recognize,
        )
    }

    pub(crate) const fn match_scrutinee_verdict(
        name: &'static str,
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::new(name, SugarRole::MatchScrutineeVerdict, witnesses, recognize)
    }

    pub(crate) const fn fallback_term(
        name: &'static str,
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::fallback_with_ordering(name, SugarRole::Term, &[], witnesses, recognize)
    }

    pub(crate) const fn fallback_composite(
        name: &'static str,
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::fallback_with_ordering(name, SugarRole::Composite, &[], witnesses, recognize)
    }

    pub(crate) const fn fallback_constraint(
        name: &'static str,
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::fallback_with_ordering(name, SugarRole::Constraint, &[], witnesses, recognize)
    }

    pub(crate) const fn fallback_assertion_surface(
        name: &'static str,
        witnesses: SugarWitnesses,
        recognize: ExprRecognizer,
    ) -> Self {
        Self::fallback_with_ordering(name, SugarRole::AssertionSurface, &[], witnesses, recognize)
    }

    pub(crate) fn role(&self) -> SugarRole {
        self.role
    }

    pub fn name(&self) -> &'static str {
        self.name
    }

    pub fn witnesses(&self) -> SugarWitnesses {
        self.witnesses
    }
}

/// A Sugar's claim that it knows how to recognize one source-item position.
#[derive(Clone, Copy)]
pub struct ItemSugarClaim {
    #[allow(dead_code)]
    name: &'static str,
    role: SugarRole,
    comes_before: &'static [&'static str],
    fallback_well: bool,
    witnesses: SugarWitnesses,
    recognize: ItemRecognizer,
}

impl ItemSugarClaim {
    pub(crate) const fn new(
        name: &'static str,
        role: SugarRole,
        witnesses: SugarWitnesses,
        recognize: ItemRecognizer,
    ) -> Self {
        Self::with_ordering(name, role, &[], witnesses, recognize)
    }

    pub(crate) const fn with_ordering(
        name: &'static str,
        role: SugarRole,
        comes_before: &'static [&'static str],
        witnesses: SugarWitnesses,
        recognize: ItemRecognizer,
    ) -> Self {
        Self {
            name,
            role,
            comes_before,
            fallback_well: false,
            witnesses,
            recognize,
        }
    }

    pub(crate) const fn statement_item(
        name: &'static str,
        witnesses: SugarWitnesses,
        recognize: ItemRecognizer,
    ) -> Self {
        Self::new(name, SugarRole::StatementItem, witnesses, recognize)
    }

    pub(crate) fn role(&self) -> SugarRole {
        self.role
    }

    pub fn name(&self) -> &'static str {
        self.name
    }

    pub fn witnesses(&self) -> SugarWitnesses {
        self.witnesses
    }

    pub(crate) fn candidate(
        &'static self,
        item: &Item,
        fcx: &SugarBuildCtx,
    ) -> Option<SugarCandidate> {
        let frag = SourceFragment::item(item, "<src>");
        (self.recognize)(&frag, fcx).map(|node| SugarCandidate {
            name: self.name,
            role: self.role,
            comes_before: self.comes_before,
            fallback_well: self.fallback_well,
            node,
        })
    }
}

/// A Sugar's claim that it knows how to recognize one source-statement position.
/// The factory brokers over these exactly as it does `ExprSugarClaim`/`ItemSugarClaim`
/// -- a statement is lifted ONLY through a claim, never by a hand-rolled block walker.
#[derive(Clone, Copy)]
pub struct StmtSugarClaim {
    #[allow(dead_code)]
    name: &'static str,
    role: SugarRole,
    comes_before: &'static [&'static str],
    fallback_well: bool,
    witnesses: SugarWitnesses,
    recognize: StmtRecognizer,
}

#[allow(dead_code)]
impl StmtSugarClaim {
    pub(crate) const fn new(
        name: &'static str,
        role: SugarRole,
        witnesses: SugarWitnesses,
        recognize: StmtRecognizer,
    ) -> Self {
        Self::with_ordering(name, role, &[], witnesses, recognize)
    }

    pub(crate) const fn with_ordering(
        name: &'static str,
        role: SugarRole,
        comes_before: &'static [&'static str],
        witnesses: SugarWitnesses,
        recognize: StmtRecognizer,
    ) -> Self {
        Self {
            name,
            role,
            comes_before,
            fallback_well: false,
            witnesses,
            recognize,
        }
    }

    /// A statement-role claim (`return`, `let`, `if`, block) -- the Stmt analogue of
    /// `ExprSugarClaim::statement_effect`, mirroring the Python `SugarRole.STATEMENT`.
    pub(crate) const fn statement(
        name: &'static str,
        witnesses: SugarWitnesses,
        recognize: StmtRecognizer,
    ) -> Self {
        Self::new(name, SugarRole::Statement, witnesses, recognize)
    }

    pub(crate) const fn statement_before(
        name: &'static str,
        comes_before: &'static [&'static str],
        witnesses: SugarWitnesses,
        recognize: StmtRecognizer,
    ) -> Self {
        Self::with_ordering(
            name,
            SugarRole::Statement,
            comes_before,
            witnesses,
            recognize,
        )
    }

    /// A catch-all fallback claim. The factory selects this only when no
    /// non-fallback claim matched. Mirrors `ExprSugarClaim::fallback_term`.
    pub(crate) const fn fallback_statement(
        name: &'static str,
        witnesses: SugarWitnesses,
        recognize: StmtRecognizer,
    ) -> Self {
        Self {
            name,
            role: SugarRole::Statement,
            comes_before: &[],
            fallback_well: true,
            witnesses,
            recognize,
        }
    }

    pub(crate) fn role(&self) -> SugarRole {
        self.role
    }

    pub fn name(&self) -> &'static str {
        self.name
    }

    pub fn witnesses(&self) -> SugarWitnesses {
        self.witnesses
    }

    pub(crate) fn candidate(
        &'static self,
        stmt: &Stmt,
        fcx: &SugarBuildCtx,
    ) -> Option<SugarCandidate> {
        let frag = SourceFragment::stmt(stmt, "<src>");
        (self.recognize)(&frag, fcx).map(|node| SugarCandidate {
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
        let frag = SourceFragment::expr(expr, "<src>");
        (self.recognize)(&frag, fcx).map(|node| SugarCandidate {
            name: self.name,
            role: self.role,
            comes_before: self.comes_before,
            fallback_well: self.fallback_well,
            node,
        })
    }
}

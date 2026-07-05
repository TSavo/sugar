// SPDX-License-Identifier: MIT OR Apache-2.0
//
// BoundVar floor.
//
// Python reference: `floor/bound_var.py` carries `(name, source, scope)` and
// `NameSugar` recomposes `source` against the DEFINITION scope. Rust keeps that
// mechanism as an explicit captured `TemporalScope` snapshot because it has no
// runtime scope dictionary. The `projected_source` is a compatibility projection
// for pre-floor readers; the floor's recomposition path always uses `source` plus
// `definition_scope`.

use std::collections::BTreeMap;

use crate::sugar::claim::SugarRole;
use crate::sugar::factory::SugarBuildCtx;
use crate::{sugar_ctx_with_factory_audits, Outcome, Sugar, SugarCtx, TemporalScope};

#[derive(Debug, Clone)]
pub(crate) struct BoundVar {
    name: String,
    source: syn::Expr,
    projected_source: syn::Expr,
    projection_is_stable: bool,
    expected_type: Option<String>,
    definition_scope: Box<TemporalScope>,
}

impl BoundVar {
    pub(crate) fn new(
        name: impl Into<String>,
        source: syn::Expr,
        projected_source: syn::Expr,
        projection_is_stable: bool,
        expected_type: Option<String>,
        definition_scope: TemporalScope,
    ) -> Self {
        Self {
            name: name.into(),
            source,
            projected_source,
            projection_is_stable,
            expected_type,
            definition_scope: Box::new(definition_scope),
        }
    }

    pub(crate) fn name(&self) -> &str {
        &self.name
    }

    pub(crate) fn source(&self) -> &syn::Expr {
        &self.source
    }

    pub(crate) fn projected_source(&self) -> &syn::Expr {
        &self.projected_source
    }

    pub(crate) fn stable_projected_source(&self) -> Option<&syn::Expr> {
        self.projection_is_stable.then_some(&self.projected_source)
    }

    pub(crate) fn expected_type(&self) -> Option<&str> {
        self.expected_type.as_deref()
    }

    pub(crate) fn definition_scope(&self) -> &TemporalScope {
        &self.definition_scope
    }
}

pub(crate) struct BoundVarSugar {
    bound: BoundVar,
    role: SugarRole,
}

impl BoundVarSugar {
    pub(crate) fn new(bound: BoundVar, role: SugarRole) -> Box<dyn Sugar> {
        Box::new(Self { bound, role })
    }
}

impl Sugar for BoundVarSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let let_inits = BTreeMap::new();
        let mut fcx = SugarBuildCtx::new(self.bound.definition_scope(), ctx.options, &let_inits);
        if let Some(expected) = self.bound.expected_type() {
            fcx = fcx.with_expected_type(Some(expected.to_string()));
        }
        let node = crate::sugar::factory::build_expr(self.bound.source(), &fcx, self.role);
        let mut float_widths = ctx.float_widths.borrow_mut();
        let child_ctx = sugar_ctx_with_factory_audits(
            self.bound.definition_scope(),
            ctx.options,
            ctx.reducer,
            *float_widths,
            ctx.macro_depth,
            ctx.factory_audits,
        );
        node.reduce(&child_ctx)
    }
}

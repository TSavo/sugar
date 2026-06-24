// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for closed stdlib `format!(...)`. This is the specific
// format-surface owner; generic macro recursion only handles unresolved cases.

use std::collections::BTreeMap;

use sugar_ir_symbolic::str_const;
use syn::Expr;

use crate::sugar::factory::{
    compat_reduction, FactoryGap, FactoryReduction, FloorRead, FormatTemplateFloor,
    FormatValueFloor, LiteralStringFloor, SugarBody, SugarBuildCtx,
};
use crate::sugar::format::{
    is_format_macro_shape, literal_format_capture_names, parse_args, render_format_values,
    runtime_format_value_body,
};
use crate::{strip_refs_groups, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "format_macro",
        &["macro_term", "reference_term"],
        recognize,
    );

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if !is_format_macro_shape(expr) {
        return None;
    }
    Some(match build_literal_string_node(expr, fcx) {
        Ok(node) => Box::new(FormatMacroTermSugar {
            body: SugarBody::from_node(node),
        }),
        Err(reason) => Box::new(FormatMacroGap { reason }),
    })
}

pub(crate) fn build_literal_string_node(
    expr: &Expr,
    fcx: &SugarBuildCtx,
) -> Result<Box<dyn Sugar>, String> {
    build_format_macro(expr, fcx).map(|node| Box::new(node) as Box<dyn Sugar>)
}

struct FormatMacroTermSugar {
    body: SugarBody<LiteralStringFloor>,
}

struct FormatMacroStringSugar {
    fmt: SugarBody<FormatTemplateFloor>,
    positional: Vec<SugarBody<FormatValueFloor>>,
    explicit_named: BTreeMap<String, SugarBody<FormatValueFloor>>,
    captures: BTreeMap<String, SugarBody<FormatValueFloor>>,
}

struct FormatMacroGap {
    reason: String,
}

fn build_format_macro(expr: &Expr, fcx: &SugarBuildCtx) -> Result<FormatMacroStringSugar, String> {
    let Expr::Macro(mac) = strip_refs_groups(expr) else {
        return Err(
            "format macro recognizer received a non-macro site; write more Sugar for this AST"
                .to_string(),
        );
    };
    let args = parse_args(&mac.mac.tokens).ok_or_else(|| {
        "format macro arguments did not parse; write more Sugar for this AST".to_string()
    })?;
    let Some((fmt_expr, rest)) = args.split_first() else {
        return Err("format macro has no format string; write more Sugar for this AST".to_string());
    };

    let mut positional = Vec::new();
    let mut explicit_named = BTreeMap::new();
    for arg in rest {
        if let Some((name, value)) = explicit_named_arg(arg) {
            explicit_named.insert(name, SugarBody::format_value(value, fcx));
        } else {
            positional.push(SugarBody::format_value(arg, fcx));
        }
    }

    let captures = capture_bodies(fmt_expr, fcx, &explicit_named);

    Ok(FormatMacroStringSugar {
        fmt: SugarBody::format_template(fmt_expr, fcx),
        positional,
        explicit_named,
        captures,
    })
}

fn capture_bodies(
    fmt_expr: &Expr,
    fcx: &SugarBuildCtx,
    explicit_named: &BTreeMap<String, SugarBody<FormatValueFloor>>,
) -> BTreeMap<String, SugarBody<FormatValueFloor>> {
    match literal_format_capture_names(fmt_expr) {
        Some(names) => names
            .into_iter()
            .filter(|name| !explicit_named.contains_key(name))
            .map(|name| {
                let body = match fcx.scope().stable_let_binding_for_term(&name) {
                    Some(init) if !fcx.resolving_bound_path(&name) => {
                        let child_fcx = fcx.with_bound_path(&name);
                        SugarBody::format_value(init, &child_fcx)
                    }
                    _ => SugarBody::from_node(runtime_format_value_body(format!(
                        "runtime format argument `{name}`, not literal-determined (bin-2: runtime data, not constructed from source literals); refused"
                    ))),
                };
                (name, body)
            })
            .collect(),
        None => fcx
            .scope()
            .let_bindings_iter()
            .filter_map(|(name, _)| {
                if explicit_named.contains_key(name) {
                    return None;
                }
                let init = fcx.scope().stable_let_binding_for_term(name)?;
                if fcx.resolving_bound_path(name) {
                    return None;
                }
                let child_fcx = fcx.with_bound_path(name);
                Some((name.clone(), SugarBody::format_value(init, &child_fcx)))
            })
            .collect(),
    }
}

fn explicit_named_arg(expr: &Expr) -> Option<(String, &Expr)> {
    let Expr::Assign(assign) = expr else {
        return None;
    };
    let Expr::Path(path) = assign.left.as_ref() else {
        return None;
    };
    let ident = path.path.get_ident()?;
    Some((ident.to_string(), assign.right.as_ref()))
}

impl Sugar for FormatMacroTermSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        match self.body.reduce_literal_string(ctx)? {
            FloorRead::Complete(value) => Ok(Outcome::Complete(Desugared::Term(str_const(value)))),
            FloorRead::Incomplete(effect) => Ok(Outcome::Incomplete(effect)),
        }
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

impl Sugar for FormatMacroStringSugar {
    fn reduce(&self, ctx: &SugarCtx) -> FactoryReduction {
        let fmt = match self.fmt.reduce_format_template(ctx)? {
            FloorRead::Complete(value) => value,
            FloorRead::Incomplete(effect) => return Ok(Outcome::Incomplete(effect)),
        };

        let mut positional = Vec::new();
        for body in &self.positional {
            match body.reduce_format_value(ctx)? {
                FloorRead::Complete(value) => positional.push(value),
                FloorRead::Incomplete(effect) => return Ok(Outcome::Incomplete(effect)),
            }
        }

        let mut explicit_named = BTreeMap::new();
        for (name, body) in &self.explicit_named {
            match body.reduce_format_value(ctx)? {
                FloorRead::Complete(value) => {
                    explicit_named.insert(name.clone(), value);
                }
                FloorRead::Incomplete(effect) => return Ok(Outcome::Incomplete(effect)),
            }
        }

        let mut captures = BTreeMap::new();
        for (name, body) in &self.captures {
            match body.reduce_format_value(ctx)? {
                FloorRead::Complete(value) => {
                    captures.insert(name.clone(), value);
                }
                FloorRead::Incomplete(effect) => return Ok(Outcome::Incomplete(effect)),
            }
        }

        match render_format_values(&fmt, &positional, &explicit_named, &captures) {
            Ok(Some(value)) => Ok(Outcome::Complete(Desugared::LiteralString(value))),
            Ok(None) => Err(FactoryGap::new(
                "format macro did not reduce to a supported literal rendering; write more Sugar for this AST",
            )),
            Err(reason) => Ok(Outcome::Incomplete(Effect::Unsupported { reason })),
        }
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

impl Sugar for FormatMacroGap {
    fn reduce(&self, _ctx: &SugarCtx) -> FactoryReduction {
        Err(FactoryGap::new(self.reason.clone()))
    }

    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        compat_reduction(self.reduce(ctx))
    }
}

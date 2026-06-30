// SPDX-License-Identifier: Apache-2.0
//
// TERM recognizer for closed stdlib `format!(...)`. This is the specific
// format-surface owner; generic macro recursion only handles unresolved cases.

use std::collections::BTreeMap;

use sugar_ir_symbolic::str_const;
use syn::Expr;

use crate::sugar::factory::{
    FloorRead, FormatTemplateFloor, FormatValueFloor, LiteralStringFloor, SugarBody, SugarBuildCtx,
};
use crate::sugar::format::{literal_format_capture_names, parse_args, render_format_values};
use crate::sugar::source_fragment::SourceFragment;
use crate::{strip_refs_groups, token_key, Desugared, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term_before(
        "format_macro",
        &["macro_term", "reference_term"],
        recognize,
    );

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if frag.strip_refs_groups().macro_name().as_deref() != Some("format") {
        return None;
    }
    Some(Box::new(FormatMacroTermSugar {
        body: SugarBody::from_node(build_literal_string_node_frag(frag, fcx)),
    }))
}

pub(crate) fn build_literal_string_node(expr: &Expr, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    Box::new(build_format_macro(expr, fcx).unwrap_or_else(|reason| {
        panic!("format macro construction failed: {reason}");
    }))
}

struct FormatMacroTermSugar {
    body: SugarBody<LiteralStringFloor>,
}

struct FormatMacroStringSugar {
    source_memento: String,
    fmt: SugarBody<FormatTemplateFloor>,
    positional: Vec<SugarBody<FormatValueFloor>>,
    explicit_named: BTreeMap<String, SugarBody<FormatValueFloor>>,
    captures: BTreeMap<String, SugarBody<FormatValueFloor>>,
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

    let captures = capture_bodies(fmt_expr, fcx, &explicit_named)?;

    Ok(FormatMacroStringSugar {
        source_memento: token_key(expr),
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
) -> Result<BTreeMap<String, SugarBody<FormatValueFloor>>, String> {
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
                    Some(_) => {
                        return Err(format!(
                            "format capture `{name}` is self-referential; write more Sugar for this AST"
                        ));
                    }
                    None => {
                        let captured: Expr = syn::parse_str(&name).unwrap_or_else(|err| {
                            panic!("format capture `{name}` was not an expression path: {err}")
                        });
                        SugarBody::format_value(&captured, fcx)
                    }
                };
                Ok((name, body))
            })
            .collect(),
        None => Ok(fcx
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
            .collect()),
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
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.body.reduce_literal_string(ctx) {
            FloorRead::Complete(value) => Outcome::Complete(Desugared::Term(str_const(value))),
            FloorRead::Incomplete(effect) => Outcome::Incomplete(effect),
        }
    }
}

impl Sugar for FormatMacroStringSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let fmt = match self.fmt.reduce_format_template(ctx) {
            FloorRead::Complete(value) => value,
            FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
        };

        let mut positional = Vec::new();
        for body in &self.positional {
            match body.reduce_format_value(ctx) {
                FloorRead::Complete(value) => positional.push(value),
                FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
            }
        }

        let mut explicit_named = BTreeMap::new();
        for (name, body) in &self.explicit_named {
            match body.reduce_format_value(ctx) {
                FloorRead::Complete(value) => {
                    explicit_named.insert(name.clone(), value);
                }
                FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
            }
        }

        let mut captures = BTreeMap::new();
        for (name, body) in &self.captures {
            match body.reduce_format_value(ctx) {
                FloorRead::Complete(value) => {
                    captures.insert(name.clone(), value);
                }
                FloorRead::Incomplete(effect) => return Outcome::Incomplete(effect),
            }
        }

        match render_format_values(
            &fmt,
            &positional,
            &explicit_named,
            &captures,
            &self.source_memento,
        ) {
            FloorRead::Complete(value) => Outcome::Complete(Desugared::LiteralString(value)),
            FloorRead::Incomplete(effect) => Outcome::Incomplete(effect),
        }
    }
}

// -- fragment-based wrapper (outside 2000-char ratchet window) ----------------

/// Calls `build_literal_string_node` from a `SourceFragment`. All raw syn access
/// lives here; `recognize` sees only the `Box<dyn Sugar>` result.
fn build_literal_string_node_frag(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Box<dyn Sugar> {
    let expr = frag
        .as_expr()
        .expect("format_macro recognize verified format macro shape");
    build_literal_string_node(expr, fcx)
}

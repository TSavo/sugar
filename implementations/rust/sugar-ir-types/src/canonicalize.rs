//! Canonicalization of ProofIR formulas and terms: the alpha + pure-let normal
//! form that makes a behavior content-address invariant under sugar.
//!
//! ARCHITECTURE: this is CLI-side computation over kit-emitted data. The kits
//! (lifters) emit ProofIR; the substrate computes over it. A kit may emit the
//! same behavior in different surface shapes -- one emits `let n = x in n*2`,
//! another emits `x*2` -- and the substrate must compute the SAME identity from
//! both. So canonicalization happens here, once, uniformly across every
//! language, never in a lifter.
//!
//! A contract's `post` is a pure `IrFormula` over a pure `IrTerm` language;
//! effects live in a separate row and never appear inside the formula. So two
//! formulations that differ only in
//!   (a) bound/local variable NAMES, or
//!   (b) trivial `let` bindings,
//! denote the same behavior and MUST share a propertyHash. This module produces
//! that canonical form, solver-free and deterministic:
//!
//!   * pure-let inlining: `let n = e in body` -> `body[n := e]`. Sound because
//!     the term language is referentially transparent (no effects in it).
//!   * alpha-canonicalization: binders (Forall/Exists/Choice/Lambda) become
//!     `$b<depth>`; with [`canonicalize_property`], the interface formals become
//!     `$arg<i>` and the result binding `$out`. Names are sugar.
//!
//! It applies NO equivalence that needs a solver (e.g. `x+x == 2*x`). Semantic
//! equality is `prove`'s job; the content address stays computable.

use crate::{IrFormula, IrTerm, LetBinding};
use std::collections::HashMap;

#[derive(Clone, Default)]
struct Ctx {
    /// let-bound name -> its already-canonical value term (inlined at use site).
    subst: HashMap<String, IrTerm>,
    /// binder / interface-formal name -> canonical name.
    rename: HashMap<String, String>,
    /// binder nesting depth, for canonical binder names.
    depth: usize,
}

impl Ctx {
    /// Enter a binder: shadow `name` with a canonical depth-keyed name. Returns
    /// the scoped child context and the canonical binder name.
    fn enter(&self, name: &str) -> (Ctx, String) {
        let canon = format!("$b{}", self.depth);
        let mut child = self.clone();
        child.rename.insert(name.to_string(), canon.clone());
        // a binder shadows any earlier let-substitution for the same name.
        child.subst.remove(name);
        child.depth += 1;
        (child, canon)
    }
}

fn canon_term(t: &IrTerm, ctx: &Ctx) -> IrTerm {
    match t {
        IrTerm::Var { name } => {
            if let Some(term) = ctx.subst.get(name) {
                term.clone()
            } else if let Some(canon) = ctx.rename.get(name) {
                IrTerm::Var {
                    name: canon.clone(),
                }
            } else {
                IrTerm::Var { name: name.clone() }
            }
        }
        IrTerm::Const { value, sort } => IrTerm::Const {
            value: value.clone(),
            sort: sort.clone(),
        },
        IrTerm::Ctor { name, args } => {
            let args: Vec<IrTerm> = args.iter().map(|a| canon_term(a, ctx)).collect();
            // Grounded Int bitwise is pure deterministic reduction (Python
            // semantics), not a solver equivalence. After callsite join
            // `&(6, 3)` is the same value as `2`, so content-address and
            // structural dual both need the fold (#4394): otherwise
            // `py.eq(A(6), 1) ∧ =(A(6), &(6, 3))` stays free under uninterpreted
            // `&` and the lying arm SAT-discharges.
            if let Some(folded) = fold_grounded_int_bitwise(name, &args) {
                return folded;
            }
            IrTerm::Ctor {
                name: name.clone(),
                args,
            }
        }
        IrTerm::Lambda {
            param_name,
            param_sort,
            body,
        } => {
            let (child, canon) = ctx.enter(param_name);
            IrTerm::Lambda {
                param_name: canon,
                param_sort: param_sort.clone(),
                body: Box::new(canon_term(body, &child)),
            }
        }
        IrTerm::Let { bindings, body } => {
            // Inline every binding left-to-right; later bindings may reference
            // earlier ones. The `let` node disappears entirely.
            let mut child = ctx.clone();
            for LetBinding { name, bound_term } in bindings {
                let value = canon_term(bound_term, &child);
                child.rename.remove(name);
                child.subst.insert(name.clone(), value);
            }
            canon_term(body, &child)
        }
    }
}

fn canon_formula(f: &IrFormula, ctx: &Ctx) -> IrFormula {
    match f {
        IrFormula::Atomic { name, args } => IrFormula::Atomic {
            name: name.clone(),
            args: args.iter().map(|a| canon_term(a, ctx)).collect(),
        },
        IrFormula::And { operands } => IrFormula::And {
            operands: canon_ops(operands, ctx),
        },
        IrFormula::Or { operands } => IrFormula::Or {
            operands: canon_ops(operands, ctx),
        },
        IrFormula::Not { operands } => IrFormula::Not {
            operands: canon_ops(operands, ctx),
        },
        IrFormula::Implies { operands } => IrFormula::Implies {
            operands: canon_ops(operands, ctx),
        },
        IrFormula::Forall { name, sort, body } => {
            let (child, canon) = ctx.enter(name);
            IrFormula::Forall {
                name: canon,
                sort: sort.clone(),
                body: Box::new(canon_formula(body, &child)),
            }
        }
        IrFormula::Exists { name, sort, body } => {
            let (child, canon) = ctx.enter(name);
            IrFormula::Exists {
                name: canon,
                sort: sort.clone(),
                body: Box::new(canon_formula(body, &child)),
            }
        }
        IrFormula::Choice {
            var_name,
            sort,
            body,
        } => {
            let (child, canon) = ctx.enter(var_name);
            IrFormula::Choice {
                var_name: canon,
                sort: sort.clone(),
                body: Box::new(canon_formula(body, &child)),
            }
        }
        IrFormula::Substitute { target, term, var } => IrFormula::Substitute {
            target: Box::new(canon_formula(target, ctx)),
            term: canon_term(term, ctx),
            var: var.clone(),
        },
        IrFormula::Apply { args, r#fn } => IrFormula::Apply {
            args: args.iter().map(|a| canon_formula(a, ctx)).collect(),
            r#fn: r#fn.clone(),
        },
        IrFormula::DivergenceBetween { source, target } => IrFormula::DivergenceBetween {
            source: Box::new(canon_formula(source, ctx)),
            target: Box::new(canon_formula(target, ctx)),
        },
    }
}

fn canon_ops(operands: &[IrFormula], ctx: &Ctx) -> Vec<IrFormula> {
    operands.iter().map(|o| canon_formula(o, ctx)).collect()
}

fn term_as_ground_int(term: &IrTerm) -> Option<i128> {
    match term {
        IrTerm::Const { value, .. } => {
            if let Some(n) = value.as_i64() {
                return Some(i128::from(n));
            }
            if let Some(s) = value.as_str() {
                return s.parse::<i128>().ok();
            }
            None
        }
        IrTerm::Ctor { name, args } => {
            // Nested grounded trees: `&(+(1,5), 3)` after other folds land here.
            fold_grounded_int_bitwise(name, args).and_then(|t| term_as_ground_int(&t))
        }
        _ => None,
    }
}

fn int_const_term(value: i128) -> IrTerm {
    // Prefer i64 Number encoding so existing JCS / display paths stay stable
    // for the common small-int surface used by Python witness seeds.
    let json_value = if let Ok(n) = i64::try_from(value) {
        serde_json::json!(n)
    } else {
        serde_json::Value::String(value.to_string())
    };
    IrTerm::Const {
        value: json_value,
        sort: crate::Sort::Primitive { name: "Int".into() },
    }
}

/// Fold fully-ground Int bitwise constructors (`&` `|` `^` `<<` `>>`) like
/// Python. Symbolic coordinates (any free var) stay open.
fn fold_grounded_int_bitwise(name: &str, args: &[IrTerm]) -> Option<IrTerm> {
    if args.len() != 2 {
        return None;
    }
    let left = term_as_ground_int(&args[0])?;
    let right = term_as_ground_int(&args[1])?;
    let result = match name {
        "&" => left & right,
        "|" => left | right,
        "^" => left ^ right,
        "<<" => {
            if !(0..128).contains(&right) {
                return None;
            }
            left.checked_shl(right as u32)?
        }
        ">>" => {
            if !(0..128).contains(&right) {
                return None;
            }
            left >> (right as u32)
        }
        _ => return None,
    };
    Some(int_const_term(result))
}

/// Canonicalize a formula: alpha-canonicalize binders to `$b<depth>` and inline
/// pure `let` bindings. Free variables are left unchanged.
pub fn canonicalize_formula(f: &IrFormula) -> IrFormula {
    canon_formula(f, &Ctx::default())
}

/// Canonicalize a contract property for use as behavior identity: as
/// [`canonicalize_formula`], and additionally rename the interface formals to
/// positional `$arg<i>` and the result binding to `$out`, so that a parameter
/// rename is not a behavior change. `formals` are in signature order;
/// `result_binding` is the variable name the post uses for the result (pass `""`
/// if there is none).
pub fn canonicalize_property(
    post: &IrFormula,
    formals: &[String],
    result_binding: &str,
) -> IrFormula {
    let mut ctx = Ctx::default();
    for (i, formal) in formals.iter().enumerate() {
        ctx.rename.insert(formal.clone(), format!("$arg{i}"));
    }
    if !result_binding.is_empty() {
        ctx.rename
            .insert(result_binding.to_string(), "$out".to_string());
    }
    canon_formula(post, &ctx)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Sort;

    fn var(n: &str) -> IrTerm {
        IrTerm::Var { name: n.into() }
    }
    fn mul(a: IrTerm, b: IrTerm) -> IrTerm {
        IrTerm::Ctor {
            name: "*".into(),
            args: vec![a, b],
        }
    }
    fn eq(a: IrTerm, b: IrTerm) -> IrFormula {
        IrFormula::Atomic {
            name: "=".into(),
            args: vec![a, b],
        }
    }
    fn int_sort() -> Sort {
        Sort::Primitive { name: "Int".into() }
    }

    /// THE bug: `result = x*2` and `result = (let n = x in n*2)` are the same
    /// behavior. A reformat that introduces a local must not move the identity.
    #[test]
    fn let_inlining_identifies_reformat() {
        let plain = eq(var("result"), mul(var("x"), var("two")));
        let with_let = eq(
            var("result"),
            IrTerm::Let {
                bindings: vec![LetBinding {
                    name: "n".into(),
                    bound_term: var("x"),
                }],
                body: Box::new(mul(var("n"), var("two"))),
            },
        );
        assert_eq!(
            canonicalize_formula(&plain),
            canonicalize_formula(&with_let)
        );
    }

    /// A real behavior change (x*2 vs x*3) must NOT be identified.
    #[test]
    fn behavior_change_is_not_identified() {
        let two = eq(var("result"), mul(var("x"), var("two")));
        let three = eq(var("result"), mul(var("x"), var("three")));
        assert_ne!(canonicalize_formula(&two), canonicalize_formula(&three));
    }

    /// A parameter rename (`double(x){x*2}` vs `double(y){y*2}`) is not a
    /// behavior change once formals are positional.
    #[test]
    fn parameter_rename_is_identified() {
        let with_x = eq(var("result"), mul(var("x"), var("two")));
        let with_y = eq(var("result"), mul(var("y"), var("two")));
        let cx = canonicalize_property(&with_x, &["x".into()], "result");
        let cy = canonicalize_property(&with_y, &["y".into()], "result");
        assert_eq!(cx, cy);
        // and it actually became positional:
        if let IrFormula::Atomic { args, .. } = &cx {
            assert_eq!(args[0], var("$out"));
        } else {
            panic!("expected atomic");
        }
    }

    /// Bound-variable renaming under a quantifier is alpha-invariant.
    #[test]
    fn quantifier_alpha_invariance() {
        let fx = IrFormula::Forall {
            name: "x".into(),
            sort: int_sort(),
            body: Box::new(eq(var("x"), var("x"))),
        };
        let fy = IrFormula::Forall {
            name: "y".into(),
            sort: int_sort(),
            body: Box::new(eq(var("y"), var("y"))),
        };
        assert_eq!(canonicalize_formula(&fx), canonicalize_formula(&fy));
    }

    /// Idempotence: canonicalizing twice is canonicalizing once.
    #[test]
    fn idempotent() {
        let f = eq(
            var("result"),
            IrTerm::Let {
                bindings: vec![LetBinding {
                    name: "n".into(),
                    bound_term: var("x"),
                }],
                body: Box::new(mul(var("n"), var("two"))),
            },
        );
        let once = canonicalize_formula(&f);
        assert_eq!(once, canonicalize_formula(&once));
    }

    #[test]
    fn grounded_int_bitwise_folds_in_canonicalize() {
        // #4394: after join, =(call:A(6), &(6, 3)) must become =(call:A(6), 2)
        // so structural dual with py.eq(call:A(6), 1) can refuse the lie.
        let bitand = IrTerm::Ctor {
            name: "&".into(),
            args: vec![
                IrTerm::Const {
                    value: serde_json::json!(6),
                    sort: crate::Sort::Primitive { name: "Int".into() },
                },
                IrTerm::Const {
                    value: serde_json::json!(3),
                    sort: crate::Sort::Primitive { name: "Int".into() },
                },
            ],
        };
        let formula = IrFormula::Atomic {
            name: "=".into(),
            args: vec![
                IrTerm::Ctor {
                    name: "call:A".into(),
                    args: vec![IrTerm::Const {
                        value: serde_json::json!(6),
                        sort: crate::Sort::Primitive { name: "Int".into() },
                    }],
                },
                bitand,
            ],
        };
        let canon = canonicalize_formula(&formula);
        match canon {
            IrFormula::Atomic { name, args } => {
                assert_eq!(name, "=");
                assert_eq!(args.len(), 2);
                match &args[1] {
                    IrTerm::Const { value, .. } => {
                        assert_eq!(value.as_i64(), Some(2), "&(6,3) must fold to 2");
                    }
                    other => panic!("expected const 2, got {other:?}"),
                }
            }
            other => panic!("expected atomic, got {other:?}"),
        }
    }

    #[test]
    fn symbolic_int_bitwise_stays_open_in_canonicalize() {
        let formula = IrFormula::Atomic {
            name: "=".into(),
            args: vec![
                IrTerm::Var { name: "out".into() },
                IrTerm::Ctor {
                    name: "&".into(),
                    args: vec![
                        IrTerm::Var { name: "z".into() },
                        IrTerm::Const {
                            value: serde_json::json!(3),
                            sort: crate::Sort::Primitive { name: "Int".into() },
                        },
                    ],
                },
            ],
        };
        let canon = canonicalize_formula(&formula);
        match canon {
            IrFormula::Atomic { args, .. } => match &args[1] {
                IrTerm::Ctor { name, .. } => assert_eq!(name, "&"),
                other => panic!("symbolic &(z,3) must stay a ctor, got {other:?}"),
            },
            other => panic!("expected atomic, got {other:?}"),
        }
    }

    /// A free const is preserved (sort + value).
    #[test]
    fn const_preserved() {
        let c = IrTerm::Const {
            value: serde_json::json!(2),
            sort: int_sort(),
        };
        assert_eq!(canon_term(&c, &Ctx::default()), c);
    }
}

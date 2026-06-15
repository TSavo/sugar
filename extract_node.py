#!/usr/bin/env python3
"""Pure code-motion helper: move verbatim line ranges from lib.rs into a new
src/sugar/<name>.rs module, removing them from lib.rs. Zero text rewriting of the
moved bodies -- only a module header + `use` block are prepended.

Usage: python3 extract_node.py <node>
"""
import sys, os

ROOT = "implementations/rust/sugar-lift-rust-tests/src"
LIB = os.path.join(ROOT, "lib.rs")

# Each node: (output filename, header_text, use_block, [ (start,end) 1-based inclusive spans in ORIGINAL main lib.rs ])
# Spans are taken against the CURRENT lib.rs each run (we recompute by markers, see below).
NODES = {
    "literal": {
        "file": "literal.rs",
        "header": '''// SPDX-License-Identifier: Apache-2.0
//
// `LiteralSugar`: the BASE-CASE sequence node -- a finite literal domain (a literal
// array `[e0, e1, ...]` or a closed integer range `a..b` / `a..=b`). Relocated
// verbatim from the `lib.rs` monolith (pure code-motion, zero behavior change); the
// shared substrate it calls (`bounded_domain_from_expr`, `const_eval`, `term_as_int`,
// `strip_refs_groups`, `SUGAR_SEQ_CAP`) stays in `crate::` and is imported below.
''',
        "use": '''use std::collections::BTreeMap;

use syn::Expr;

use crate::{
    bounded_domain_from_expr, const_eval, strip_refs_groups, term_as_int, BoundedDomain, ConstVal,
    Desugared, DesugaredElem, Outcome, Sugar, SugarCtx, SUGAR_SEQ_CAP,
};
''',
        "markers": [
            ("/// BASE CASE: a finite literal domain", "struct LiteralSugar {"),
            ("impl Sugar for LiteralSugar {", None),
        ],
    },
    "fold": {
        "file": "fold.rs",
        "header": '''// SPDX-License-Identifier: Apache-2.0
//
// `FoldSugar` / `RFoldSugar` / `ForEachSugar`-as-fold: a finite-domain fold reduced to
// the finite conjunction of its per-iteration body (the construction axiom). Relocated
// verbatim from the `lib.rs` monolith (pure code-motion, zero behavior change). Carries
// its OWNED machinery: `decompose_seq` (the receiver adaptor-chain builder), the
// `FoldItemBinder` enum, and the `decompose_fold` / `decompose_for_each` constructors.
// Shared substrate (`peel_fold_adaptors`, `wrap_rev`, `capture_literal_arrays`, the
// collector, the term/const helpers) stays in `crate::` and is imported below; the base
// node `LiteralSugar` lives in the sibling `crate::sugar::literal`.
''',
        "use": '''use std::collections::{BTreeMap, HashSet};
use std::rc::Rc;

use sugar_ir_symbolic::{and_, num, Term};
use syn::{Expr, Pat, Stmt};

use crate::sugar::literal::LiteralSugar;
use crate::{
    closure_body_is_side_effecting, closure_single_param_ident, collect_assertion_entries,
    const_fold_acc_update, const_int_acc_init, count_asserts_in_stmts, peel_fold_adaptors,
    resolve_index_in_formula, strip_refs_groups, subst_var_in_formula, translate_term_in_scope,
    tuple_components, wrap_rev, ConstVal, Desugared, Outcome, Sugar, SugarCtx, Warrant,
    SUGAR_SEQ_CAP,
};
''',
        "markers": [
            ("/// Build the sequence-`Sugar` tree for a fold/for_each RECEIVER", None),
            ("/// The item-binder of a `fold`/`rfold` closure's second parameter", "enum FoldItemBinder {"),
            ("/// `FoldSugar` / `RFoldSugar` (and `ForEachSugar`", "struct FoldSugar {"),
            ("impl Sugar for FoldSugar {", None),
            ("/// Build a `FoldSugar` (or `RFoldSugar`) from a `.fold`/`.rfold`", None),
        ],
    },
    "forall": {
        "file": "forall.rs",
        "header": '''// SPDX-License-Identifier: Apache-2.0
//
// `ForAllSugar` / `ForEachSugar`: a bounded universal over a finite-construction domain
// (`for v in <lit> { body }` / `<lit>.iter().for_each(|v| body)`). Relocated verbatim
// from the `lib.rs` monolith (pure code-motion, zero behavior change). Carries its OWNED
// machinery: `lift_bounded_forall` (the shared verified core: literal-int-range unroll /
// literal-array conjunction / guarded forall) and the `decompose_for_loop` constructor.
// Shared substrate (the collector, the term/formula helpers, `bounded_domain_from_expr`,
// `capture_literal_arrays`, `SUGAR_SEQ_CAP`) stays in `crate::` and is imported below.
''',
        "use": '''use std::collections::{BTreeMap, HashSet};
use std::rc::Rc;

use sugar_ir_symbolic::{and_, forall, implies, lt, lte, num, Formula, Sort, Term};
use syn::{Expr, ExprForLoop, Pat, Stmt};

use crate::{
    bounded_domain_from_expr, capture_literal_arrays, collect_assertion_entries,
    count_asserts_in_stmts, iter_adaptor_base, loop_body_mutates, resolve_index_in_formula,
    subst_var_in_formula, term_as_int, translate_term_in_scope, BoundedDomain, Desugared,
    FloatWidthScope, LiftOptions, Outcome, ReductionCtx, Sugar, SugarCtx, TemporalScope, Warrant,
    SUGAR_SEQ_CAP,
};
''',
        "markers": [
            ("/// and `try_lift_for_each_forall` (a `.for_each(|var| body)` adaptor)", None),
            ("/// `ForEachSugar` / `ForAllSugar`: a bounded universal", "struct ForAllSugar {"),
            ("impl Sugar for ForAllSugar {", None),
            ("/// Build a `ForEachSugar` from a `<receiver>.for_each", None),
            ("/// Build a `ForAllSugar` from a `for <var> in <domain> { body }` loop", None),
        ],
    },
    "conditional": {
        "file": "conditional.rs",
        "header": '''// SPDX-License-Identifier: Apache-2.0
//
// `ConditionalSugar`: a guarded point-wise claim (`if cond { asserts } else { asserts }`)
// reduced to `cond => then-conj` and `!cond => else-conj`. Relocated verbatim from the
// `lib.rs` monolith (pure code-motion, zero behavior change). Carries its OWNED
// `decompose_if` constructor. Shared substrate (the collector, the bool-assertion
// translator, `const_fold_bool_guard`, the purity gates) stays in `crate::`.
''',
        "use": '''use std::collections::{BTreeMap, HashSet};
use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, implies, not_, Formula};
use syn::{Expr, Stmt};

use crate::{
    bool_const, closure_body_is_side_effecting, collect_assertion_entries, const_fold_bool_guard,
    count_asserts_in_stmts, loop_body_mutates, lower_assert_condition, Desugared, Outcome, Sugar,
    SugarCtx, Warrant,
};
''',
        "markers": [
            ("/// EXACT-OR-BAIL: the guard must translate to a Formula", "struct ConditionalSugar {"),
            ("impl Sugar for ConditionalSugar {", None),
            ("impl ConditionalSugar {", None),
            ("/// Build a `ConditionalSugar` from a `Stmt::Expr(Expr::If(..))`", None),
        ],
    },
    "match_node": {
        "file": "match_node.rs",
        "header": '''// SPDX-License-Identifier: Apache-2.0
//
// `MatchSugar`: an N-arm match reduced to the conjunction of `guard_i => body_i`, each
// `guard_i` the discriminant predicate the arm's pattern states over the scrutinee (the
// trailing `_` arm's guard is the negation of all prior guards). Relocated verbatim from
// the `lib.rs` monolith (pure code-motion, zero behavior change). Carries its OWNED
// machinery: the `MatchArmLift` struct, `match_arm_guard`, `arm_body_stmts`, and the
// `decompose_match` constructor. The shared `match_arm_discriminant` (called from the
// scrutinee-translation path OUTSIDE this node) stays in `crate::` and is imported.
''',
        "use": '''use std::collections::{BTreeMap, HashSet};
use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, implies, not_, or_, str_const, Formula, Term};
use syn::{Arm, Expr, ExprMatch, Lit, Pat, Path, Stmt};

use crate::{
    bool_const, cfg_eval_for_attrs, closure_body_is_side_effecting, collect_assertion_entries,
    count_asserts_in_stmts, loop_body_mutates, path_to_variant_string, strict_variant_path,
    translate_lit, translate_term_in_scope, wrapped_variant, CfgEval, Desugared, LiftOptions,
    Outcome, Sugar, SugarCtx, TemporalScope, Warrant,
};
''',
        "markers": [
            ("/// A match arm reduced to its discriminant guard + body statements", "struct MatchArmLift {"),
            ("/// guard_i = the discriminant predicate pat_i states over scrut", "struct MatchSugar {"),
            ("/// BAILS (Err analog = `Ok(None)` is the wildcard", "fn match_arm_guard("),
            ("/// The statements of a match arm body", "fn arm_body_stmts("),
            ("/// translate as a stable term (no mut local, no effect", "fn decompose_match("),
            ("impl Sugar for MatchSugar {", None),
            ("impl MatchSugar {", None),
        ],
    },
}


def find_block(lines, doc_marker, item_marker):
    """Return (start0, end0) 0-based inclusive span of a top-level item: from the
    line that startswith doc_marker (stripped) through the matching closing brace /
    statement of the item. item_marker (if given) must appear after the doc as the
    actual item line; otherwise doc_marker IS the item line."""
    n = len(lines)
    start = None
    for i, l in enumerate(lines):
        if l.strip().startswith(doc_marker.strip()):
            start = i
            break
    if start is None:
        raise SystemExit(f"doc marker not found: {doc_marker!r}")
    def strip_vis(s):
        s = s.lstrip()
        for pfx in ("pub(crate) ", "pub "):
            if s.startswith(pfx):
                s = s[len(pfx):]
        return s

    # locate item line
    if item_marker:
        item_i = None
        for j in range(start, min(start + 40, n)):
            if strip_vis(lines[j]).startswith(item_marker):
                item_i = j
                break
        if item_i is None:
            raise SystemExit(f"item marker not found after doc: {item_marker!r}")
    else:
        # the doc_marker line itself is (for fn/impl) the item OR leads attrs+item.
        # Find the first line at column 0 that is fn/impl/struct/enum/const/type after start
        item_i = None
        kw = ("fn ", "pub fn ", "pub(crate) fn ", "impl ", "struct ", "pub struct ",
              "pub(crate) struct ", "enum ", "const ", "pub const ", "type ", "#[")
        for j in range(start, min(start + 60, n)):
            s = lines[j]
            if s and not s.startswith("//") and not s.startswith("///") and not s[0].isspace():
                if any(s.startswith(k) for k in kw):
                    item_i = j
                    break
        # If doc_marker is itself the item line (starts with fn/impl/struct), item_i==start
        if item_i is None:
            item_i = start
    # Now find end: brace-balance from the item's opening brace; for `const`/`type`
    # it's a `;`-terminated single statement.
    # Determine if this item uses braces.
    # Scan from item_i for first '{' or ';' at top level.
    depth = 0
    end = None
    started = False
    for j in range(item_i, n):
        line = lines[j]
        if not started:
            if "{" in line:
                started = True
            elif line.rstrip().endswith(";") and depth == 0:
                end = j
                break
        for ch in line:
            if ch == "{":
                depth += 1
                started = True
            elif ch == "}":
                depth -= 1
                if started and depth == 0:
                    end = j
                    break
        if end is not None:
            break
    if end is None:
        raise SystemExit(f"could not find end of item starting at line {item_i+1}")
    return start, end


def main():
    node = sys.argv[1]
    spec = NODES[node]
    lines = open(LIB).read().split("\n")
    # Resolve all spans first against the SAME snapshot.
    spans = []
    for dm, im in spec["markers"]:
        s, e = find_block(lines, dm, im)
        spans.append((s, e))
    spans.sort()
    # Sanity: no overlap
    for k in range(1, len(spans)):
        if spans[k][0] <= spans[k - 1][1]:
            raise SystemExit(f"overlapping spans: {spans[k-1]} {spans[k]}")
    # Extract verbatim blocks
    blocks = []
    removed = set()
    for s, e in spans:
        blocks.append("\n".join(lines[s : e + 1]))
        for idx in range(s, e + 1):
            removed.add(idx)
    # Build new module file
    out = spec["header"] + "\n" + spec["use"] + "\n" + "\n\n".join(blocks) + "\n"
    out_path = os.path.join(ROOT, "sugar", spec["file"])
    with open(out_path, "w") as f:
        f.write(out)
    # Build new lib.rs: drop removed lines AND collapse the now-stranded blank lines
    # between removed blocks so we don't leave 3+ blank lines.
    new_lines = [l for i, l in enumerate(lines) if i not in removed]
    # collapse runs of 3+ blank lines to 1
    collapsed = []
    blank_run = 0
    for l in new_lines:
        if l.strip() == "":
            blank_run += 1
            if blank_run >= 3:
                continue
        else:
            blank_run = 0
        collapsed.append(l)
    with open(LIB, "w") as f:
        f.write("\n".join(collapsed))
    print(f"node={node} -> {out_path}")
    print("spans (1-based):", [(s + 1, e + 1) for s, e in spans])
    print("lines removed from lib.rs:", len(removed))
    print("new module bytes:", len(out), "lines:", out.count(chr(10)) + 1)


if __name__ == "__main__":
    main()

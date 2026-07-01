"""The grammar debt ledger: Δ(Python-as-FOL, lifted) made a named, pinned set.

Every bucket the census classifier (grammar_census.classify) can emit is
classified here into exactly one of THREE statuses — there is no fourth:

- ``lifted``    a shipping universe walk admits instances of this shape and
                emits conjuncts (refusal classes named inside the walk).
                ``symbol`` names the walk entry point in translate_universe
                and is resolved at import time: a "lifted" row that points
                at nothing refuses to import. ``residual`` names any
                unadmitted arms — those arms are debt, carried on the row,
                never shrugged.
- ``debt``      deterministically FOL-expressible, no shipping walk yet.
                ``owes`` names the lifter owed. This set is the worklist;
                it shrinks PR by PR and its content-address makes the
                shrinkage checkable.
- ``membrane``  the world refusing to hold still — suspension points,
                shared-scope mutation, environment boundaries, bodies
                CPython itself refuses to run. ``reason`` is mandatory:
                membrane rows are named residue, never silence.

Totality is STRUCTURAL, not asserted: the classifier's only non-named
buckets are parametric over the interpreter's own grammar
(``non-return:<stmt class>`` and ``return-other:<expr class>``), so at
import time this module enumerates all stmt and expr grammar classes from the running
interpreter and refuses to import if any reachable bucket lacks a row.
Grammar growth (a new Python release adding a node kind) is therefore a
LOUD RuntimeError here, not a silent zero — the same floor as
sugar_lift_python_source.value_pins.

The ledger's identity is the blake3-512 of its canonical encoding (the
system's one content-address function); joining a census report against
it yields the scoreboard: lifted / debt / membrane function counts and
the ranked debt worklist.
"""

from __future__ import annotations

import json
from typing import Optional

from .canonicalizer import blake3_512_of
from .factory.source_fragment import grammar_stmt_classes, grammar_expr_classes

from . import translate_universe as _walks

LIFTED = "lifted"
DEBT = "debt"
MEMBRANE = "membrane"


def _lifted(symbol: str, family: str, residual: Optional[str] = None) -> dict:
    entry = {"status": LIFTED, "symbol": symbol, "family": family}
    if residual:
        entry["residual"] = residual
    return entry


def _debt(owes: str) -> dict:
    return {"status": DEBT, "owes": owes}


def _membrane(reason: str) -> dict:
    return {"status": MEMBRANE, "reason": reason}


# ---------------------------------------------------------------------------
# Named return shapes (the classifier's explicit buckets).
# ---------------------------------------------------------------------------

_NAMED: dict = {
    "empty": _lifted(
        "constant_universe_for_callee",
        "implicit-None equality: falling off the end is None, " "unconditionally",
    ),
    "unparseable-file": _membrane(
        "not parseable as the pinned Python grammar; the file never enters "
        "the walk — counted as its own row, never silently dropped"
    ),
    "return-translate": _lifted(
        "translate_universe_for_callee",
        "chars-not-in-set complement universe over maketrans literals",
        residual="dict-form str.maketrans bindings refuse by name",
    ),
    "return-strip-literal": _lifted(
        "translate_universe_for_callee",
        "no-suffix/no-prefix universe (rstrip/lstrip totality)",
        residual="strip arms owed (both-sides twin)",
    ),
    "return-replace-literals": _lifted(
        "_replace_return_shape",
        "chars-not-in-set over the replaced character",
        residual="multi-char replace operands owed (needs full str.replace "
        "semantics, not charset complement)",
    ),
    "return-join": _lifted(
        "_table_loop_charset",
        "chars-in-set over the accumulated table union (acc/for/append/join)",
        residual="joins over non-loop operands owed (literal-sep concat " "universe)",
    ),
    "return-encode-decode": _debt(
        "codec universe: .encode/.decode with a pinned codec literal is "
        "deterministic; charset and length facts derivable"
    ),
    "return-format": _lifted(
        "_format_return_prefix",
        "prefix-of universe (leading literal of the template)",
        residual="full template concatenation owed (str.++ over lifted "
        "parts); only the leading-literal arm ships",
    ),
    "return-fstring": _lifted(
        "_format_return_prefix",
        "prefix-of universe (leading literal of the f-string)",
        residual="full concatenation owed; only the leading-literal arm " "ships",
    ),
    "return-case-method": _debt(
        "case-mapping universe: upper/lower/casefold/title over pinned "
        "unicode tables; charset-complement facts derivable"
    ),
    "return-method-call": _lifted(
        "delegation_universe_for_callee",
        "method-delegation equality: eq(subject, callval_<method>(recv, "
        "args...)) — ground instantiations only (no body backs a method "
        "delegate, so every mapped term must be concrete at the callsite)",
        residual="computed receivers, keyword forwarding, and symbolic "
        "instantiations refuse/skip by name; module-attr function calls "
        "through the receiver slot owed",
    ),
    "pure-delegation": _lifted(
        "delegation_universe_for_callee",
        "delegation equality universe: f(args) == g(mapped args) in EUF, "
        "zero new atoms — the composition-router edge",
        residual="keyword forwarding, imported/attribute delegates, and "
        "computed arguments refuse by name",
    ),
    "return-fn-call": _lifted(
        "delegation_universe_for_callee",
        "SSA-chain delegation: leading simple assigns form a "
        "substitution environment — `x = a; return g(x)` forwards "
        "exactly as `return g(a)`; shadowed params resolve to their "
        "rebound spec; chains feed identity/delegation/method kinds plus "
        "the chain-constant arm",
        residual="computed chain values and walrus assigns refuse by "
        "name; control flow and unpacking before the return stay "
        "non-candidates",
    ),
    "return-call-other": _debt(
        "callable-expression universe (subscripted/lambda callees), static "
        "subset; dynamic dispatch refuses by name"
    ),
    "return-table-subscript": _lifted(
        "_table_subscript_shape",
        "member-of-values disjunction over a pinned all-string tuple",
        residual="int-valued tables owed; mutable/mixed/rebound tables "
        "refuse by name (by design)",
    ),
    "return-constant": _lifted(
        "constant_universe_for_callee",
        "equality with the unconditioned literal",
        residual="non-ascii bytes literals refuse loudly (named); multi-return literal bodies lift via the branch-literal disjunction family",
    ),
    "return-name": _lifted(
        "delegation_universe_for_callee",
        "identity universe: return <param> swears the output IS the "
        "argument (eq(subject, call_args[i]))",
        residual="the value-pinned-local arm owed (return <local> "
        "resolved through value_pins)",
    ),
    "return-binop": _lifted(
        "delegation_universe_for_callee",
        "chain-expr: the returned arithmetic expression as structure — "
        "eq(subject, ctor('+', ...)) over the consumer side's own "
        "operator ctors; + - * lower to real Int math, / % stay EUF; "
        "all-Int-const instantiations only ('+' on strings is concat by "
        "dispatch — the cross-sort mislower)",
        residual="string concatenation universe owed (str.++ exists "
        "substrate-side); operators outside + - * / % refuse by name; "
        "symbolic instantiations skip",
    ),
    "return-predicate": _lifted(
        "predicate_universe_for_callee",
        "ground-evaluated boolean equality at concrete callsites",
        residual="predicates over attributes/calls/free names refuse "
        "(named); membership tests (in) owed",
    ),
    "return-ifexp": _lifted(
        "branch_literal_universe_for_callee",
        "branch-literal disjunction over the conditional expression's "
        "literal leaves — the statement branch shape in expression form, "
        "no condition evaluation",
        residual="computed leaves stay non-candidates; a ground-evaluated "
        "ite (exact branch selection at concrete callsites) owed",
    ),
    "return-collection": _lifted(
        "collection_literal_canonical",
        "collection-literal equality: one canonical content string shared "
        "with the consumer-side term translator — universe and claim are "
        "byte-identical by construction",
        residual="computed elements, unpacking, nesting, and multi-return "
        "collections stay non-candidates (literal-membership disjunction "
        "shipped: x in (1,2) lifts as equalities over tuple/list/set "
        "literals; str/dict/mixed-kind containers stay on the member "
        "atom by semantics)",
    ),
    "return-attribute": _debt(
        "attribute-projection universe: enum members pin today via "
        "value_pins enum pins; frozen-dataclass and module-constant "
        "attributes owed"
    ),
}

# ---------------------------------------------------------------------------
# Parametric buckets: non-return:<stmt> — one row per grammar class the
# running interpreter knows, import-time enforced below.
# ---------------------------------------------------------------------------

_NON_RETURN: dict = {
    "Expr": _debt(
        "effect-bearing tail (bare call): return-value None lifts "
        "trivially; the effect contract owes state-relation vocabulary; "
        "per-body IO markers route to membrane via "
        "callee_is_nondeterministic"
    ),
    "Assert": _lifted(
        "guard_universe_for_callee",
        "assert clauses — the vendor's in-body FOL as negated guard "
        "comparisons — plus the implicit-None equality for assert-only "
        "bodies",
        residual="bodies with non-guard statements before the asserts "
        "refuse as non-candidates; non-comparison assert tests skip "
        "clause-wise (pure tests); asserts assumed enabled (-O can only "
        "false-refuse)",
    ),
    "Assign": _debt(
        "binding tail: returns None; preceding bindings feed SSA for the "
        "other families; attribute/subscript targets owe state-relation "
        "vocabulary"
    ),
    "AugAssign": _debt("binding tail (see Assign)"),
    "AnnAssign": _debt("binding tail (see Assign)"),
    "If": _lifted(
        "branch_literal_universe_for_callee",
        "branch-literal disjunction: every Return a same-kind literal + "
        "terminal tail (Return|Raise|If both arms, recursively) — "
        "output ∈ {walked literals}, no condition evaluation",
        residual="computed branches, mixed kinds (cross-sort), bare "
        "returns, and loop/try tails refuse or stay non-candidates by "
        "name",
    ),
    "While": _debt("control tail (see If)"),
    "For": _debt("control tail (see If)"),
    "With": _debt(
        "context-manager tail: pure-CM subset liftable; resource CMs "
        "route to membrane per-body via nondeterminism markers"
    ),
    "Try": _debt(
        "exception-flow tail: raise-locus + handler join owed (the "
        "panic-locus twin exists rust-side)"
    ),
    "TryStar": _debt("exception-flow tail (see Try)"),
    "Raise": _lifted(
        "raise_locus_universe_for_callee",
        "raise locus: zero Return/Yield + terminal tail means every path "
        "raises — any sworn value equality carries the canonical "
        "contradiction (the guard family's complement, total)",
        residual="raise-tails behind non-terminal control (Try/With last "
        "statements, fall-off paths) stay non-candidates; the exception "
        "TYPE is not yet sworn (pytest.raises cross-check owed)",
    ),
    "Pass": _lifted(
        "constant_universe_for_callee",
        "implicit-None equality (a bare pass falls off the end)",
        residual="bodies with effect statements before the tail refuse "
        "as non-candidates",
    ),
    "Return": _lifted(
        "constant_universe_for_callee",
        "explicit-None equality (a bare return is None)",
        residual="bodies with effect statements before the tail refuse "
        "as non-candidates",
    ),
    "Match": _debt(
        "structural-match tail: variant_of/tag vocabulary exists "
        "rust-side; the python twin is owed"
    ),
    "FunctionDef": _debt(
        "definition tail: closure construction is deterministic source "
        "construction; returns None; nested-def vocabulary owed"
    ),
    "AsyncFunctionDef": _debt(
        "definition tail (defining an async fn is itself deterministic; "
        "async-ness bites at the CALL, where Await rows are membrane)"
    ),
    "ClassDef": _debt("definition tail (see FunctionDef)"),
    "Delete": _debt("del tail: deterministic scope mutation; state-relation owed"),
    "TypeAlias": _debt(
        "type-alias tail: deterministic annotation-level binding; returns "
        "None (annotations are not value semantics — constant-None arm)"
    ),
    "Import": _membrane(
        "dynamic import at function tail: environment boundary — module "
        "identity resolves at the package seam (kit-owns-resolution), "
        "never in-body"
    ),
    "ImportFrom": _membrane("dynamic import at function tail (see Import)"),
    "Global": _membrane(
        "declared shared-scope mutation: the body swears it punches "
        "through its own frame; cross-frame interleaving is not pinned by "
        "this body"
    ),
    "Nonlocal": _membrane("declared shared-scope mutation (see Global)"),
    "AsyncWith": _membrane(
        "suspension inside the tail: scheduler interleaving is not pinned "
        "by the body"
    ),
    "AsyncFor": _membrane("suspension inside the tail (see AsyncWith)"),
    "Break": _membrane(
        "compile-rejected placement: the parser admits a function-tail "
        "break, the compiler refuses it — no runnable witness can exist"
    ),
    "Continue": _membrane("compile-rejected placement (see Break)"),
}

# ---------------------------------------------------------------------------
# Parametric buckets: return-other:<expr>. Expr classes consumed ENTIRELY
# by named shapes never reach return-other and need no row here; UnaryOp
# and Subscript have fall-through arms, so they appear in BOTH vocabularies.
# ---------------------------------------------------------------------------

_NEVER_FALLS_THROUGH = frozenset(
    (
        "Call",
        "Constant",
        "Name",
        "BinOp",
        "Compare",
        "BoolOp",
        "IfExp",
        "JoinedStr",
        "Tuple",
        "List",
        "Dict",
        "Set",
        "Attribute",
    )
)

_RETURN_OTHER: dict = {
    "UnaryOp": _debt(
        "negation/invert over a lifted operand (`not` already routes to "
        "the predicate family; USub literals fold in vectors; symbolic "
        "arms owed)"
    ),
    "Subscript": _debt(
        "general select universe: expression-subject subscripts; "
        "Name-subject tables lift via member-of-values"
    ),
    "NamedExpr": _debt("walrus tail: the universe of the assigned value"),
    "Lambda": _debt(
        "returned-closure universe: β-reduce at apply sites (function "
        "names are sugar)"
    ),
    "ListComp": _debt(
        "bounded comprehension universe: fold over a lifted iterable; "
        "needs sequence vocabulary"
    ),
    "SetComp": _debt("bounded comprehension universe (see ListComp)"),
    "DictComp": _debt("bounded comprehension universe (see ListComp)"),
    "GeneratorExp": _debt(
        "lazy comprehension as a sequence universe (deterministic when "
        "the body is pure)"
    ),
    "Yield": _debt(
        "generator protocol: deterministic when the body is pure; needs "
        "sequence vocabulary"
    ),
    "YieldFrom": _debt("generator protocol (see Yield)"),
    "Await": _membrane(
        "await: suspension point — resumption order and the awaited IO "
        "are not pinned by this body"
    ),
    "Starred": _debt(
        "unpack forwarding (grammar-marginal: 2/1.5M corpus functions); "
        "lifts with tuple vocabulary"
    ),
    "Slice": _debt(
        "slice literal (grammar-marginal; legal only inside subscripts in " "practice)"
    ),
    "FormattedValue": _debt(
        "occurs only inside JoinedStr in legal parses; covered by the "
        "format family when reachable"
    ),
    "Ellipsis": _debt(
        "legacy Ellipsis compatibility class: parser-normalized "
        "ellipsis constants route through return-constant; if this alias "
        "ever reaches return-other as its own node, map it to the "
        "constant-singleton universe"
    ),
    "TemplateStr": _debt(
        "t-string template universe (PEP 750): deterministic template "
        "construction; interpolation vocabulary owed"
    ),
    "Interpolation": _debt(
        "occurs only inside TemplateStr in legal parses (see TemplateStr)"
    ),
}

# ---------------------------------------------------------------------------
# Orthogonal flags (census prefix detectors, not last-statement shapes).
# ---------------------------------------------------------------------------

_FLAGS: dict = {
    "guard-then-raise-prefix": _lifted(
        "guard_universe_for_callee",
        "negated guard comparisons instantiated at concrete callsite args",
    ),
    "table-loop": _lifted(
        "_table_loop_charset",
        "chars-in-set over the accumulated table union",
    ),
}


def _build_ledger() -> dict:
    ledger: dict = {}
    ledger.update(_NAMED)
    for name, entry in _NON_RETURN.items():
        ledger[f"non-return:{name}"] = entry
    for name, entry in _RETURN_OTHER.items():
        ledger[f"return-other:{name}"] = entry
    return ledger


LEDGER: dict = _build_ledger()
FLAG_LEDGER: dict = dict(_FLAGS)


# ---------------------------------------------------------------------------
# Import-time floor. Three checks, all structural:
#   1) every stmt grammar class has a non-return row;
#   2) every expr grammar class outside _NEVER_FALLS_THROUGH has a
#      return-other row (and _NEVER_FALLS_THROUGH names only real classes);
#   3) every row is well-formed (status vocabulary; debt has owes;
#      membrane has reason; lifted has a symbol that RESOLVES in
#      translate_universe — a lifted claim pointing at nothing refuses
#      to import).
# ---------------------------------------------------------------------------


def unaccounted_buckets(
    ledger: Optional[dict] = None,
    stmt_classes: Optional[frozenset] = None,
    expr_classes: Optional[frozenset] = None,
) -> list:
    """Every parametric bucket the classifier could emit on this
    interpreter that the ledger does not classify. Empty list = the floor
    holds. Parameterized so tests can feed synthetic grammar growth."""
    ledger = LEDGER if ledger is None else ledger
    stmt_classes = grammar_stmt_classes() if stmt_classes is None else stmt_classes
    expr_classes = grammar_expr_classes() if expr_classes is None else expr_classes
    holes = []
    for cls in stmt_classes:
        if f"non-return:{cls.__name__}" not in ledger:
            holes.append(f"non-return:{cls.__name__}")
    for cls in expr_classes:
        if cls.__name__ in _NEVER_FALLS_THROUGH:
            continue
        if f"return-other:{cls.__name__}" not in ledger:
            holes.append(f"return-other:{cls.__name__}")
    return sorted(holes)


def malformed_rows(ledger: Optional[dict] = None) -> list:
    """Rows whose status vocabulary or obligations are broken, and lifted
    rows whose symbol does not resolve in translate_universe."""
    ledger = LEDGER if ledger is None else ledger
    bad = []
    for shape, entry in sorted(ledger.items()):
        status = entry.get("status")
        if status == LIFTED:
            symbol = entry.get("symbol", "")
            if not entry.get("family"):
                bad.append(f"{shape}: lifted without family")
            if not hasattr(_walks, symbol):
                bad.append(
                    f"{shape}: lifted symbol {symbol!r} does not resolve "
                    "in translate_universe"
                )
        elif status == DEBT:
            if not entry.get("owes"):
                bad.append(f"{shape}: debt without owes")
        elif status == MEMBRANE:
            if not entry.get("reason"):
                bad.append(f"{shape}: membrane without reason")
        else:
            bad.append(f"{shape}: unknown status {status!r}")
    return bad


_HOLES = unaccounted_buckets()
_GHOST = sorted(
    name
    for name in _NEVER_FALLS_THROUGH
    if name not in {c.__name__ for c in grammar_expr_classes()}
)
_BAD = malformed_rows(LEDGER) + malformed_rows(FLAG_LEDGER)
if _HOLES or _BAD or _GHOST:
    raise RuntimeError(
        "grammar ledger is not total/well-formed over this interpreter's "
        f"grammar: unclassified buckets {_HOLES}, ghost never-falls-through "
        f"names {_GHOST}, malformed rows {_BAD}. Classify every bucket as "
        "lifted, debt, or membrane before the ledger is admissible; a "
        "best-effort ledger is an asserted silence."
    )
del _HOLES, _BAD, _GHOST


def ledger_cid() -> str:
    """The classification's content address (counts excluded: the ledger
    is the CLAIM about the grammar; a census report is evidence joined
    against it)."""
    canonical = json.dumps(
        {"entries": LEDGER, "flags": FLAG_LEDGER},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return blake3_512_of(canonical.encode("utf-8"))


def join_report(report: dict) -> dict:
    """Score a census report against the ledger. Raises LookupError on any
    report shape the ledger does not classify — an unclassified shape in
    real corpus data is exactly the silence this module exists to refuse."""
    totals = {LIFTED: 0, DEBT: 0, MEMBRANE: 0}
    rows = []
    for row in report["shapes_ranked"]:
        shape, count = row["shape"], row["count"]
        entry = LEDGER.get(shape)
        if entry is None:
            raise LookupError(
                f"census shape {shape!r} ({count} functions) is not "
                "classified in the grammar ledger — that is a silent "
                "bucket, which the ledger refuses to carry"
            )
        totals[entry["status"]] += count
        rows.append({"shape": shape, "count": count, **entry})
    classified = sum(totals.values())
    debt_rows = [r for r in rows if r["status"] == DEBT]
    residual_rows = [
        {"shape": r["shape"], "count": r["count"], "residual": r["residual"]}
        for r in rows
        if r["status"] == LIFTED and r.get("residual")
    ]
    return {
        "ledger_cid": ledger_cid(),
        "census": {k: report[k] for k in ("packages", "files", "functions")},
        "classified": classified,
        "totals": totals,
        "pct": {k: round(100 * v / max(1, classified), 2) for k, v in totals.items()},
        "debt_ranked": sorted(debt_rows, key=lambda r: r["count"], reverse=True),
        "lifted_residuals": residual_rows,
        "membrane": [r for r in rows if r["status"] == MEMBRANE],
    }


def main(argv: Optional[list] = None) -> int:
    import sys

    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(
            "usage: python -m sugar_lift_py_tests.grammar_ledger "
            "<census-report.json>",
            file=sys.stderr,
        )
        return 2
    report = json.load(open(args[0], encoding="utf-8"))
    print(json.dumps(join_report(report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

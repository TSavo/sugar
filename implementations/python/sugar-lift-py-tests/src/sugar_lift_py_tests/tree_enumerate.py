"""Enumeration served by the AST tree, not the factory.

The wire protocol's levels below `functions` — call_sites, assertions, facts —
were serviced by lifting the whole file through the factory and reading its IR
rows. Here they are serviced by walking the tree the parser produces and
asking each Assert node for its sugar and its desugared fact. The RPC drives
AST walking directly; the factory is not consulted.

For `assert <test>`: the assertion IS the Assert node; its fact is the InvValue
its sugar desugars to (formula on the wire via formula_to_value). A bare
assertion carries no call site — call_sites and assertions are the same locus,
1:1, exactly as the factory's protocol Section 4 already had them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile
from sugar_source_tree.nodes import Assert, AsyncFunctionDef, FunctionDef


def source_file(full_path: Path) -> SourceFile:
    """The file's tree, over oracle-pinned source."""
    return SourceFile(path_source(str(full_path)))


def functions_of(sf: SourceFile):
    return list(sf.functions())


def asserts_of(node) -> list:
    """Every Assert in a function body, in source order."""
    return [n for n in node.walk() if isinstance(n, Assert)]


def find_function(sf: SourceFile, name: Optional[str], span: Optional[dict]):
    for fn in sf.functions():
        if name is not None and fn.name != name:
            continue
        if span and not _span_matches(fn, span):
            continue
        return fn
    return None


def find_function_by_name(sf: SourceFile, name: str):
    """The function definition with this exact name, or None. Direct name
    resolution -- the callee a cue names is found by that name."""
    for fn in sf.functions():
        if fn.name == name:
            return fn
    return None


def call_target_names(sf: SourceFile, span: Optional[dict]) -> list:
    """The callee names cued by the assertion at `span`: the func-name of every
    plain Call inside it. This is how a call-site cue resolves to the callee(s)
    whose universe it digs -- by NAME, directly, no bridge-matching heuristics
    (the tree kept the names the factory had to reconstruct)."""
    from sugar_source_tree.nodes import Call, Name

    _source, node = temporally_rewritten_assert(sf, span)
    if node is None:
        return []
    names = []
    for call in node.walk():
        if isinstance(call, Call) and isinstance(call.func, Name):
            if call.func.id not in names:
                names.append(call.func.id)
    return names


def find_assert(sf: SourceFile, span: Optional[dict]):
    for node in sf:
        if isinstance(node, Assert) and (span is None or _span_matches(node, span)):
            return node
    return None


def temporally_rewritten_assert(sf: SourceFile, span: Optional[dict]):
    """Return ``(source_assert, rewritten_assert)`` for an exact locus.

    An assertion is not a construction root.  Its meaning depends on every
    binding before it in the enclosing function (or module), so constructing
    its Sugar directly from the parser-backed tree is a temporal side door.
    Find the narrowest enclosing function, rewrite that scope as a block, and
    only then return the assertion on which callers may invoke ``sugar()``.

    The source node is returned separately because its fragment/memento is the
    durable address.  Shadow rewrites deliberately borrow that address, but
    keeping the two roles explicit prevents a future caller from mistaking
    source lookup for construction readiness.
    """
    source_assert = find_assert(sf, span)
    if source_assert is None:
        return None, None

    target = source_assert.line_col_span()

    def contains(node) -> bool:
        locus = node.line_col_span()
        return (
            locus.start_line <= target.start_line and locus.end_line >= target.end_line
        )

    owners = [fn for fn in sf.functions() if contains(fn)]
    if owners:
        # Nested functions are also yielded by SourceFile.functions(); temporal
        # ownership belongs to the narrowest one, never its enclosing function.
        owner = min(
            owners,
            key=lambda fn: (
                fn.line_col_span().end_line - fn.line_col_span().start_line,
                fn.line_col_span().end_col - fn.line_col_span().start_col,
            ),
        )
        rewritten_owner = owner.substitute({})
    else:
        # Module assertions are temporally owned by the module block.
        rewritten_owner = sf.root.substitute({})

    for node in rewritten_owner.walk():
        if isinstance(node, Assert) and _span_matches(node, span or {}):
            return source_assert, node
    return source_assert, None


def _span_matches(node, span: dict) -> bool:
    lc = node.line_col_span()
    return lc.start_line == span.get("start_line") and lc.start_col == span.get(
        "start_col"
    )


def assert_memento(node, file_rel: str) -> dict:
    """The Assert's own self-locating memento: file + its span + CID."""
    lc = node.line_col_span()
    sealed = node.fragment.seal()
    return {
        "kind": "source-memento",
        "file": file_rel,
        "function_name": "",
        "source_function_name": "",
        "span": {
            "start_line": lc.start_line,
            "start_col": lc.start_col,
            "end_line": lc.end_line,
            "end_col": lc.end_col,
        },
        "source_cid": sealed.cid,
    }


def fact_of(node) -> Optional[Any]:
    """Desugar the assertion; its InvValue's formula is the fact, on the wire.

    ``node`` must be the result of ``temporally_rewritten_assert``, never the
    parser-backed lookup node.  None when the assertion emits no fact (e.g.
    inert support). No factory and no ambient context: the enclosing tree has
    already expressed the temporal state.
    """
    import json

    from sugar_lift_py_tests.canonicalizer import encode_jcs
    from sugar_lift_py_tests.ir import formula_to_value

    outcome = node.sugar().desugar(None)
    inv = getattr(outcome, "value", None)
    formula = getattr(inv, "formula", None)
    if formula is None:
        return None
    # Same shape the factory's facts payload carried (ir.py `item["inv"]`):
    # the formula's JCS Value tree, flattened to a plain JSON dict.
    return json.loads(encode_jcs(formula_to_value(formula)))


# --- The recovered-construction frontier, re-homed onto the tree ------------
#
# The factory's corpus-wide R census is gone. Its replacement is here: walk the
# file with a CollectingReporter and ask every node for its sugar. A node whose
# OWN sugar() reaches the abstract base throw (SugarNotWritten) reports itself
# through the reporter before the throw fires; that report IS a frontier row.
# Coverage is the class hierarchy, so R = the count of nodes that self-reported.
#
# The frontier is served at MODULE granularity: one demanded body per file
# (function_name "<module>", whole-file span), whose audit leaf walks the entire
# file. One body per file means the census consistency (bodies == files) holds
# trivially and no gap is counted twice across a function/module split.


def audit_file_gaps(full_path: Path):
    """The file's frontier: ONE construction per top-level statement; the
    reporter witnesses every gap underneath it as it is built.

    Construction is correctness -- there is no other path, so there is nothing
    to re-ask. Each top-level statement's sugar() is called once; a gap anywhere
    in its subtree self-reports through the reporter DURING that construction.
    Linear in the file, never quadratic: asking every node separately would
    re-construct every subtree once per ancestor -- a second computation, the
    side door this replaces. Only ``SugarNotWritten`` is caught: a
    VocabularyMissing/BackendDefect is a different, louder failure and is left
    to propagate, never swallowed into the census.

    Returns ``(sf, [(node, panic), ...])`` deduped by SOURCE identity (kind +
    span): the tree materializes nodes fresh per access, so the same source gap
    reached twice is still one gap.
    """
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter

    reporter = CollectingReporter()
    sf = SourceFile.from_path(str(full_path), reporter=reporter)
    for stmt in sf.root.body:
        try:
            stmt.sugar()
        except SugarNotWritten:
            pass  # reported through the channel already; keep counting
    seen: dict[tuple, Any] = {}
    for node, panic in reporter.gaps:
        lc = node.line_col_span()
        key = (node.kind, lc.start_line, lc.start_col, lc.end_line, lc.end_col)
        seen[key] = (node, panic)
    return sf, list(seen.values())


def function_def_memento(fn, file_rel: str):
    """The function's own SourceMemento (the def warrant payload_rows needs)."""
    from sugar_lift_py_tests.kit_rpc.source_memento_dto import SourceMementoDto
    from sugar_lift_py_tests.kit_rpc.source_span_dto import SourceSpanDto

    lc = fn.line_col_span()
    return SourceMementoDto(
        file=file_rel,
        span=SourceSpanDto(lc.start_line, lc.start_col, lc.end_line, lc.end_col),
        source_cid=fn.fragment.seal().cid,
        source_function_name=fn.name,
        param_names=[p.name for p in fn.params],
    )


def function_contract_rows(fn, file_rel: str):
    """A function's contract DTO rows, produced from its TREE universe.

    `fn.sugar()` constructs the FunctionUniverseSugar; desugar reduces the body.
    Complete -> the UniverseValue projects its own DTO rows (one function-
    contract carrying the post, one contract per stated inv) via payload_rows --
    the exact rows the factory used to emit. Incomplete -> the def is an effect
    (a halt), returned as (def_memento, None) so the caller emits an effect, not
    a contract. A SugarNotWritten from an unported body statement propagates
    (the whole function is a frontier gap).
    """
    from sugar_lift_py_tests.outcome import Complete

    def_memento = function_def_memento(fn, file_rel)
    outcome = fn.sugar().desugar(None)
    if not isinstance(outcome, Complete):
        return def_memento, None  # an effect; not a contract
    return def_memento, outcome.value.payload_rows(def_memento)


def call_nodes_in_assert(sf: SourceFile, span: Optional[dict]) -> list:
    """The plain named Call nodes inside the assertion at `span`, in walk order.
    The cue's own AST: each carries the callee name AND the actual argument
    nodes -- the pre this call fills."""
    from sugar_source_tree.nodes import Call, Name

    _source, node = temporally_rewritten_assert(sf, span)
    if node is None:
        return []
    return [
        call
        for call in node.walk()
        if isinstance(call, Call) and isinstance(call.func, Name)
    ]


def _args_are_ground(call) -> bool:
    """True when every argument fills its pre with no remaining hole: no free
    Name inside any arg. A hole-bearing arg leaves the callee's contract
    curried (the abstract contract IS the callable floor); a ground arg set is
    a fill, and the dig applies it."""
    for arg in call.args:
        for n in arg.walk():
            if n.kind == "Name":
                return False
    return True


def applied_contract_rows(fn, arg_nodes: tuple, file_rel: str):
    """The callee's contract AS APPLIED at a call: a call IS substitution.

    Substitute the actual argument nodes for the formals into the body -- the
    same `_substitute_body` that threads a block; a concrete iterable arg makes
    a symbolic loop unroll here (`_Splice`), a filled name inlines. Then lift
    the applied body. `A(xs): total=0; for x in xs: total=total+x` dug at
    `A([1,2,3])` yields post `out == 6` -- the fold coordinate collapsed by the
    dig, exactly as `c[post]=5` collapses `b[post]`. The DTO keeps the callee's
    memento and formals (same wire shape; the post simply no longer mentions
    them). Incomplete -> (memento, None), an effect, as the abstract path."""
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        FunctionUniverseSugar,
    )

    def_memento = function_def_memento(fn, file_rel)
    scope = {p.name: a for p, a in zip(fn.params, arg_nodes)}
    applied_body, _changed = fn._substitute_body(fn.body, scope)
    sugar = FunctionUniverseSugar(
        name=fn.name,
        formals=tuple(p.name for p in fn.params),
        statements=tuple(stmt.sugar() for stmt in applied_body),
        site=fn.fragment,
    )
    outcome = sugar.desugar(None)
    if not isinstance(outcome, Complete):
        return def_memento, None
    return def_memento, outcome.value.payload_rows(def_memento)


def module_definition_memento(sf: SourceFile, file_rel: str, file_cid: str) -> dict:
    """The whole-file body the audit frontier demands one leaf for."""
    lc = sf.root.line_col_span()
    sealed = sf.fragment.seal()
    return {
        "kind": "source-memento",
        "file": file_rel,
        "function_name": "<module>",
        "source_function_name": "<module>",
        "span": {
            "start_line": lc.start_line,
            "start_col": lc.start_col,
            "end_line": lc.end_line,
            "end_col": lc.end_col,
        },
        "source_cid": sealed.cid,
        "file_cid": file_cid,
        "template_cid": None,
        "param_names": [],
    }


def _gap_locus(node, file_rel: str) -> tuple[str, str]:
    """(position locus, terminal gap locus) for a gap node.

    The terminal locus carries the full span AND the node kind so two distinct
    nodes never collide — the fold rejects duplicate owner identities loudly,
    and (demandedBody, demandedSource, terminalGapLocus) must be unique.
    """
    lc = node.line_col_span()
    pos = f"{file_rel}:{lc.start_line}:{lc.start_col}"
    terminal = (
        f"{file_rel}:{lc.start_line}:{lc.start_col}-"
        f"{lc.end_line}:{lc.end_col}[{node.kind}]"
    )
    return pos, terminal


def source_audit_from_roll_call(full_path: Path, file_rel: str) -> dict:
    """The report feed the Rust CLI renders, straight from the reporter's roll
    call. Construction registers every node; the discharge answers present
    (desugared -> Blue) or absent (the minority -> Yellow). Each roster entry
    becomes one source-audit locus keyed by its status; the CLI reads the source
    text for each locus from its span.

    ``warranted`` = present (accounted, Blue); ``unresolved`` = the minority
    (absent, Yellow). ``source_loci`` / ``source_warranted`` / ``source_unresolved``
    are the ledger counts the report summary measures.
    """
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.roll_call import discharge

    reporter = CollectingReporter()
    sf = SourceFile.from_path(str(full_path), reporter=reporter)
    report = discharge(sf)
    present_cids = {e.cid for e in report.present}
    loci = []
    for entry in report.roster:
        status = "warranted" if entry.cid in present_cids else "unresolved"
        loci.append(
            {
                "status": status,
                "kind": entry.kind,
                "name": entry.name,
                "source_cid": entry.cid,
                "locus": {
                    "file": file_rel,
                    "line": entry.start_line,
                    "col": entry.start_col,
                },
            }
        )
    warranted = sum(1 for locus in loci if locus["status"] == "warranted")
    unresolved = len(loci) - warranted
    return {
        "role": file_rel,
        "loci": loci,
        "totals": {
            "source_loci": len(loci),
            "source_warranted": warranted,
            "source_unresolved": unresolved,
        },
    }


def frontier_leaf_rpc(full_path: Path, file_rel: str) -> dict:
    """The recovered-construction audit leaf for one file, tree-walked.

    Emits the closed ``RecoveredAuditDto`` wire shape (status ``failed`` when
    the file has any unwritten-sugar gap, ``clean`` when it is fully sugared).
    ``demandedSource`` is the file's own content CID: stable per file, so gap
    uniqueness rides on each gap's terminal locus. It ALSO carries the
    ``sourceAudit`` -- the reporter's roll-call partition the Rust CLI renders
    (present Blue / absent Yellow), everything the report needs on the CLI side.
    """
    from sugar_lift_py_tests.kit_rpc.recovered_audit_dto import (
        AuditLeafEnvelopeDto,
        RecoveredAuditDto,
        RecoveredConstructionPanicDto,
    )

    sf, gaps = audit_file_gaps(full_path)
    demanded_source = f"module:{sf.unit.source_cid}"
    panics = []
    for node, panic in gaps:
        pos, terminal = _gap_locus(node, file_rel)
        reason = panic.observed or str(panic)
        panics.append(
            RecoveredConstructionPanicDto(
                locus=pos,
                demanded_source=demanded_source,
                terminal_gap_locus=terminal,
                reason=reason,
                gap={"blame": terminal, "kind": node.kind, "reason": reason},
            )
        )
    return AuditLeafEnvelopeDto.from_rpc({
        "semanticCore": RecoveredAuditDto(panics=panics).to_rpc(),
        "auxiliaryRows": {
            "sourceAudit": source_audit_from_roll_call(full_path, file_rel)
        },
    }).to_rpc()

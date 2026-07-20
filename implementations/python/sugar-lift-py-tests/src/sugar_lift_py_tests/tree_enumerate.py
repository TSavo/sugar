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


def find_assert(sf: SourceFile, span: Optional[dict]):
    for node in sf:
        if isinstance(node, Assert) and (span is None or _span_matches(node, span)):
            return node
    return None


def _span_matches(node, span: dict) -> bool:
    lc = node.line_col_span()
    return (
        lc.start_line == span.get("start_line")
        and lc.start_col == span.get("start_col")
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

    None when the assertion emits no fact (e.g. inert support). No factory,
    no context: a self-contained assertion desugars context-free.
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
    """Every node in the file whose own sugar() reaches the base throw.

    Returns ``(sf, [(node, panic), ...])`` deduped by node identity. Each node
    is asked directly, so it self-reports even when no ancestor's sugar() call
    reached it first; a gap reported while an ANCESTOR was under construction is
    the same node object, collapsed by identity here. Only ``SugarNotWritten``
    is caught: a VocabularyMissing/BackendDefect during the walk is a different,
    louder failure and is left to propagate, never swallowed into the census.
    """
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter

    reporter = CollectingReporter()
    sf = SourceFile.from_path(str(full_path), reporter=reporter)
    for node in sf.root.walk():
        try:
            node.sugar()
        except SugarNotWritten:
            pass  # reported through the channel already; keep counting
    # Dedup by SOURCE identity, never object id: the tree materializes a node
    # fresh on every access, so the same source node reached by the walk and
    # again by a parent's sugar() (e.g. FunctionDef resolving its body) are two
    # distinct objects. Their identity is the memento (kind + span), so a gap is
    # one gap however many times it was materialized.
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


def frontier_leaf_rpc(full_path: Path, file_rel: str) -> dict:
    """The recovered-construction audit leaf for one file, tree-walked.

    Emits the closed ``RecoveredAuditDto`` wire shape (status ``failed`` when
    the file has any unwritten-sugar gap, ``clean`` when it is fully sugared).
    ``demandedSource`` is the file's own content CID: stable per file, so gap
    uniqueness rides on each gap's terminal locus.
    """
    from sugar_lift_py_tests.kit_rpc.recovered_audit_dto import (
        RecoveredAuditDto,
        RecoveredFactoryPanicDto,
    )

    sf, gaps = audit_file_gaps(full_path)
    demanded_source = f"module:{sf.unit.source_cid}"
    panics = []
    for node, panic in gaps:
        pos, terminal = _gap_locus(node, file_rel)
        reason = panic.observed or str(panic)
        panics.append(
            RecoveredFactoryPanicDto(
                locus=pos,
                demanded_source=demanded_source,
                terminal_gap_locus=terminal,
                reason=reason,
                gap={"blame": terminal, "kind": node.kind, "reason": reason},
            )
        )
    return RecoveredAuditDto(panics=panics).to_rpc()

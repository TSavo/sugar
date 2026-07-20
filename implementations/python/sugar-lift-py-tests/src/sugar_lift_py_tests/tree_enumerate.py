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

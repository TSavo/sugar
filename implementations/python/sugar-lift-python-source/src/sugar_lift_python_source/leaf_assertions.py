"""Python Layer-0 leaf-assertion harvester (verify-facing).

The Python analog of Go's ``lifgotests.LiftLeafAssertions`` (PR #1445). It
harvests each single recognized ``assert`` statement in a pytest test function
into its own ``contract`` declaration whose ``inv`` is the lifted
``=(<call>, <expected>)`` formula::

    def test_double():
        assert double(3) == 6      ->  contract{ inv = =(double(3), 6) }

where ``double(3)`` is a ``ctor`` named ``double`` -- exactly the harvested
``=(<call>, <expected>)`` callsite the verifier's body-discharge seam
enumerates and reduces through the body-derived ``function-contract`` for
``double``. One contract per test function (``inv`` is the conjunction of that
test's recognized assertions; the common single-assertion case is the bare
``=( ... )``), so a function-contract bridge can match it.

Whitelist (v0), each side an operand (identifier var / int literal / single-arg
call ``f(arg)`` as a ctor / negative-int literal):

    assert <lhs> == <rhs>   -> = (lhs, rhs)
    assert <lhs> != <rhs>   -> ≠ (lhs, rhs)
    assert <lhs> <  <rhs>   -> < (lhs, rhs)        (and <=, >, >=)
    assert <lhs> is None    -> and(=(lhs, None), is_none(lhs))
    assert <lhs> is not None -> and(≠(lhs, None), is_some(lhs))

Anything else is skipped (a diagnostic, not a contract) so the harvester never
fabricates a callsite it cannot faithfully lift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Any

_tree_src = Path(__file__).resolve().parents[3] / "sugar-source-tree" / "src"
if _tree_src.is_dir() and str(_tree_src) not in sys.path:
    sys.path.insert(0, str(_tree_src))

from sugar_source_tree.backend import BackendCouldNotParse
from sugar_source_tree.leaf_assertion_product import (
    LeafAssertionUnsupported,
    _construct_leaf_assertion_product,
)
from sugar_source_tree.nodes import Assert, FunctionDef
from sugar_source_tree.tree import SourceFile

from .canonical import blake3_512_of

Json = dict[str, Any]

@dataclass
class HarvestResult:
    ir: list[Json] = field(default_factory=list)
    call_edges: list[Json] = field(default_factory=list)
    diagnostics: list[Json] = field(default_factory=list)


def harvest_source(source: str, source_path: str) -> HarvestResult:
    result = HarvestResult()
    try:
        source_file = SourceFile(
            (source, source_path, blake3_512_of(source.encode("utf-8")))
        )
    except (SyntaxError, BackendCouldNotParse) as exc:
        result.diagnostics.append(
            {
                "kind": "parse-error",
                "message": getattr(exc, "msg", str(exc)),
                "path": source_path,
                "line": getattr(exc, "lineno", None),
            }
        )
        return result

    for node in source_file.root.body:
        if not isinstance(node, FunctionDef):
            continue
        if not node.name.startswith("test_") and not node.name.startswith("test"):
            # Only pytest test functions harvest callsites. (Match `test*`.)
            if not node.name.startswith("test"):
                continue
        atoms: list[Json] = []
        for stmt in node.body:
            if not isinstance(stmt, Assert):
                continue
            try:
                atom, call_edges = _construct_leaf_assertion_product(
                    node, stmt
                ).project()
                atoms.append(atom)
                result.call_edges.extend(call_edges)
            except LeafAssertionUnsupported as exc:
                result.diagnostics.append(
                    {
                        "kind": "leaf-assertion-skipped",
                        "message": str(exc),
                        "path": source_path,
                        "line": exc.line,
                    }
                )
        if not atoms:
            continue
        inv = atoms[0] if len(atoms) == 1 else _and(atoms)
        result.ir.append(
            {
                "schemaVersion": "1",
                "kind": "contract",
                "name": node.name,
                "outBinding": "out",
                "inv": inv,
            }
        )
    return result


def _and(atoms: list[Json]) -> Json:
    return {"kind": "and", "operands": atoms}

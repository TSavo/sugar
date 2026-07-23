# SPDX-License-Identifier: MIT OR Apache-2.0
"""Construct embedded Python contract expressions through the source tree.

The CPython expression grammar stays below ``cpython_adapter``.  Above that
boundary this module sees one typed ``Expression`` and follows the ordinary
construction path: substitute, construct Sugar, reduce, then ask the resulting
floor value for its Python truth predicate.  Unsupported or effectful shapes
remain loud; there is no private formula evaluator.
"""

from __future__ import annotations

import textwrap

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.backend import BackendCouldNotParse, materialize
from sugar_source_tree.cpython_adapter import CPythonAstBackend
from sugar_source_tree.nodes import Expression, SourceUnit

from .context import ReduceContext
from .floor import PredicateValue
from .ir import Formula
from .outcome import Complete


def parse_contract_expression(expr: str, available_names: list[str]) -> Formula:
    """Build one contract predicate through the sole Python construction path.

    ``available_names`` describes the surrounding declaration's formals.  Name
    nodes are deliberately left as ordinary free formals during substitution;
    the declaration binder owns their scope when it installs this formula.
    """
    del available_names  # binder ownership is outside the expression body
    source = textwrap.dedent(expr).strip()
    source_cid = blake3_512_of(source.encode("utf-8"))
    try:
        unit = SourceUnit(
            filename="<contract-expression>", source=source, source_cid=source_cid
        )
    except SyntaxError as exc:
        raise ValueError(f"empty or invalid contract expression: {expr!r}") from exc
    backend = CPythonAstBackend()
    try:
        node = materialize(unit, backend.expression(unit))
    except BackendCouldNotParse as exc:
        raise ValueError(f"empty or invalid contract expression: {expr!r}") from exc
    if not isinstance(node, Expression):
        raise ValueError(
            f"contract expression adapter returned {type(node).__name__}, expected Expression"
        )

    constructed = node.substitute({}).sugar()
    outcome = constructed.desugar(ReduceContext.root(owner="contract-expression"))
    if not isinstance(outcome, Complete):
        raise ValueError(
            "contract expression did not complete through ordinary construction: "
            f"{type(outcome).__name__}"
        )
    truth = outcome.value.truth(node.fragment)
    if not isinstance(truth, Complete) or not isinstance(truth.value, PredicateValue):
        raise ValueError(
            "contract expression has no constructed truth predicate: "
            f"{type(truth).__name__}"
        )
    return truth.value.formula

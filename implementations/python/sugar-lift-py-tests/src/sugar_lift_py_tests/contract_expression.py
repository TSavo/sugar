# SPDX-License-Identifier: MIT OR Apache-2.0
"""Construct embedded Python contract expressions through the source tree.

The contract text is read through the one door a Python file is read by
(``SourceFile``): a unit always carries its typed tree, so every reader of the
expression (the builtin a name reaches, whether a name is bound anywhere)
answers off the binding, never off a unit with no tree (#7757).  Above that
door this module sees one typed ``Expression`` and follows the ordinary
construction path: substitute, construct Sugar, reduce, then ask the resulting
floor value for its Python truth predicate.  Unsupported or effectful shapes
remain loud; there is no private formula evaluator.
"""

from __future__ import annotations

import textwrap

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.backend import BackendCouldNotParse
from sugar_source_tree.nodes import Expr, Expression, Lambda
from sugar_source_tree.tree import SourceFile

from .context import ReduceContext
from .floor import PredicateValue
from .ir import Formula
from .outcome.exit_set import _require_exit_set


def _contract_body(expr: str, available_names: list[str]) -> Expression:
    """The contract expression as the body of ``lambda <formals>: <expr>``,
    read through ``SourceFile``.

    The declaration's formals are the lambda's formals, so a read of one is
    bound (by the lambda) and stays the formal's free name; the declaration
    binder owns their scope when it installs the formula.  Any text that is
    not one expression -- it does not parse, or the lambda is not the whole
    statement -- is refused.
    """
    text = textwrap.dedent(expr).strip()
    formals = ", ".join(dict.fromkeys(available_names))
    source = f"lambda {formals}: {text}\n"
    try:
        tree = SourceFile(
            (source, "<contract-expression>", blake3_512_of(source.encode("utf-8")))
        )
    except (SyntaxError, BackendCouldNotParse) as exc:
        raise ValueError(f"empty or invalid contract expression: {expr!r}") from exc
    body = tree.root.body
    if (
        not text
        or len(body) != 1
        or not isinstance(body[0], Expr)
        or not isinstance(body[0].value, Lambda)
    ):
        raise ValueError(f"empty or invalid contract expression: {expr!r}")
    node = body[0].value.body
    if not isinstance(node, Expression):
        raise ValueError(
            f"contract expression adapter returned {type(node).__name__}, expected Expression"
        )
    return node


def parse_contract_expression(expr: str, available_names: list[str]) -> Formula:
    """Build one contract predicate through the sole Python construction path.

    ``available_names`` describes the surrounding declaration's formals
    (``_contract_body``).
    """
    node = _contract_body(expr, available_names)
    constructed = node.substitute({}).sugar()
    # A contract predicate is read here, never retained for a caller: a
    # deferred native-operation carrier is refused by name.
    outcome = _require_exit_set(
        constructed.desugar(ReduceContext.root(owner="contract-expression")),
        owner="parse_contract_expression",
    )
    value = outcome.completed_value()
    if value is None:
        raise ValueError(
            "contract expression did not complete through ordinary construction: "
            f"ExitSet with {len(outcome.exits)} exits"
        )
    truth = _require_exit_set(
        value.truth(node.fragment), owner="parse_contract_expression"
    )
    predicate = truth.completed_value()
    if not isinstance(predicate, PredicateValue):
        raise ValueError(
            "contract expression has no constructed truth predicate: "
            f"{type(predicate).__name__}"
        )
    return predicate.formula

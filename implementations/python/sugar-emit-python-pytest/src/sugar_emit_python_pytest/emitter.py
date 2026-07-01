"""Emit a pytest test module from a contract's neutral predicates.

The output is a self-contained python module: an ``import pytest`` line (only
when needed), and one ``test_*`` function per supported predicate whose body
declares type-correct placeholder locals for every free variable the predicate
references and then asserts that predicate via the inline mapping in
:mod:`sugar_emit_python_pytest.predicate_table`.

Substrate-honest: predicates this kit cannot spell are NOT emitted as
vacuously-passing tests. They are collected as ``unsupported`` diagnostics so
the substrate can record an honest "emit-assertion-gap" per unhandled
predicate. The placeholder values are chosen per-predicate (see
:func:`predicate_table.placeholder_value`) so that an emitted ``test_*``
function PASSES when run standalone under pytest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import blake3

from . import predicate_table as pt


@dataclass(frozen=True)
class EmitPlan:
    """The emit request: a contract's neutral predicates plus the target

    function signature. Mirrors the realize ``params`` shape but smaller: this
    kit emits test assertions, not function bodies.

    JSON shape (the RPC ``params`` object)::

        {
          "contract_id": "blake3-512:...",      # contract/operator CID; informational
          "function":    "clamp",               # target function name
          "params":      ["x", "lo", "hi"],     # formal parameter names
          "param_types": ["int", "int", "int"], # python type hints (parallel)
          "predicates": [                         # neutral predicate terms
            {"kind":"op","name":"concept:ge","args":[
               {"kind":"var","name":"x"},{"kind":"var","name":"lo"}]}
          ]
        }
    """

    contract_id: str = ""
    function: str = "test"
    params: list[str] = field(default_factory=list)
    param_types: list[str] = field(default_factory=list)
    predicates: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def from_params(params: dict[str, Any]) -> "EmitPlan":
        if not isinstance(params, dict):
            return EmitPlan()
        contract_id = _first_str(params.get("contract_id"))
        function = (
            _first_str(params.get("function"), params.get("function_name")) or "test"
        )
        formals = _string_list(params.get("params"))
        formal_types = _string_list(params.get("param_types"))
        predicates = [p for p in _list(params.get("predicates")) if isinstance(p, dict)]
        return EmitPlan(contract_id, function, formals, formal_types, predicates)


@dataclass(frozen=True)
class Emission:
    """The emission result: source text, per-predicate gaps, and a CID."""

    source: str
    path: str
    artifact_cid: str
    emitted_predicates: list[str]
    unsupported_predicates: list[str]

    @property
    def is_complete(self) -> bool:
        return not self.unsupported_predicates and bool(self.emitted_predicates)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "pytest-test-emission",
            "source": self.source,
            "path": self.path,
            "extension": "py",
            "emitted_artifact_cid": self.artifact_cid,
            "emitted_predicates": list(self.emitted_predicates),
            "unsupported_predicates": list(self.unsupported_predicates),
            "is_complete": self.is_complete,
        }


def emit(plan: EmitPlan) -> Emission:
    """Emit a pytest test module for the contract described by ``plan``."""
    declared_types = {}
    for i, formal in enumerate(plan.params):
        t = plan.param_types[i] if i < len(plan.param_types) else ""
        declared_types[formal] = t or "int"

    emitted: list[str] = []
    unsupported: list[str] = []
    functions: list[str] = []
    needs_pytest = False

    for idx, predicate in enumerate(plan.predicates):
        head = pt.head_of(predicate)
        assertion = pt.render(predicate)
        if assertion is None:
            unsupported.append(head if head is not None else "<malformed>")
            continue
        emitted.append(head)
        if "pytest.raises" in assertion:
            needs_pytest = True
        declarations = _free_var_declarations(predicate, head)
        functions.append(
            _render_test_function(_function_name(head, idx), declarations, assertion)
        )

    source = _render_module(functions, needs_pytest)
    cid = "blake3-512:" + blake3.blake3(source.encode("utf-8")).digest(length=64).hex()
    return Emission(source, _module_path(plan.function), cid, emitted, unsupported)


def _module_path(function: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z_]+", "_", function or "").strip("_").lower()
    if not safe:
        safe = "contract"
    return f"test_{safe}_contract.py"


def _free_var_declarations(predicate: dict[str, Any], head: str | None) -> list[str]:
    """Placeholder local-variable assignments for every free var the predicate

    references, in deterministic encounter order. The placeholder VALUE is
    chosen per-predicate so the emitted assertion passes when run standalone.
    """
    variables = pt.free_vars(predicate)
    decls: list[str] = []
    for var_index, name in enumerate(variables):
        value = pt.placeholder_value(head, var_index)
        decls.append(f"{name} = {value}")
    return decls


def _render_test_function(name: str, declarations: list[str], assertion: str) -> str:
    lines = [f"def {name}():"]
    for decl in declarations:
        lines.append(f"    {decl}")
    # The assertion may itself be multi-line (e.g. a ``with`` block); indent
    # only its first line, the table already indents continuation lines.
    for i, asrt_line in enumerate(assertion.split("\n")):
        if i == 0:
            lines.append(f"    {asrt_line}")
        else:
            lines.append(asrt_line)
    return "\n".join(lines) + "\n"


def _render_module(functions: list[str], needs_pytest: bool) -> str:
    parts: list[str] = []
    if needs_pytest:
        parts.append("import pytest\n")
    if parts:
        parts.append("\n")
    parts.append("\n".join(functions))
    return "".join(parts)


def _function_name(head: str | None, idx: int) -> str:
    safe = (head or "predicate").replace("-", "_")
    return f"test_verifies_{safe}_{idx}"


def _first_str(*candidates: Any) -> str:
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c
    return ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []

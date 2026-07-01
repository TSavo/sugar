"""Emit a unittest test module from a contract's neutral predicates."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import blake3

from . import predicate_table as pt


@dataclass(frozen=True)
class EmitPlan:
    """The emit request: neutral predicates plus target function metadata."""

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
            "kind": "unittest-test-emission",
            "source": self.source,
            "path": self.path,
            "extension": "py",
            "emitted_artifact_cid": self.artifact_cid,
            "emitted_predicates": list(self.emitted_predicates),
            "unsupported_predicates": list(self.unsupported_predicates),
            "is_complete": self.is_complete,
        }


def emit(plan: EmitPlan) -> Emission:
    """Emit a native unittest module for the contract described by ``plan``."""
    emitted: list[str] = []
    unsupported: list[str] = []
    methods: list[str] = []

    for idx, predicate in enumerate(plan.predicates):
        head = pt.head_of(predicate)
        assertion = pt.render(predicate)
        if assertion is None:
            unsupported.append(head if head is not None else "<malformed>")
            continue
        emitted.append(head)
        declarations = _free_var_declarations(predicate, head)
        methods.append(
            _render_test_method(_method_name(head, idx), declarations, assertion)
        )

    class_name = _class_name(plan.function)
    source = _render_module(class_name, methods)
    cid = "blake3-512:" + blake3.blake3(source.encode("utf-8")).digest(length=64).hex()
    return Emission(source, _module_path(plan.function), cid, emitted, unsupported)


def _module_path(function: str) -> str:
    safe = _snake(function)
    if not safe:
        safe = "contract"
    return f"test_{safe}_contract.py"


def _class_name(function: str) -> str:
    safe = _snake(function)
    parts = [part for part in safe.split("_") if part]
    if not parts:
        parts = ["contract"]
    return "Test" + "".join(part.capitalize() for part in parts) + "Contract"


def _snake(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]+", "_", value or "").strip("_").lower()


def _free_var_declarations(predicate: dict[str, Any], head: str | None) -> list[str]:
    variables = pt.free_vars(predicate)
    decls: list[str] = []
    for var_index, name in enumerate(variables):
        value = pt.placeholder_value(head, var_index)
        decls.append(f"{name} = {value}")
    return decls


def _render_test_method(name: str, declarations: list[str], assertion: str) -> str:
    lines = [f"    def {name}(self):"]
    for declaration in declarations:
        lines.append(f"        {declaration}")
    lines.extend(_indent(assertion, "        "))
    return "\n".join(lines) + "\n"


def _render_module(class_name: str, methods: list[str]) -> str:
    body = "\n".join(methods) if methods else "    pass\n"
    return f"import unittest\n\n\nclass {class_name}(unittest.TestCase):\n{body}"


def _method_name(head: str | None, idx: int) -> str:
    safe = (head or "predicate").replace("-", "_")
    return f"test_verifies_{safe}_{idx}"


def _indent(block: str, prefix: str) -> list[str]:
    return [prefix + line if line else line for line in block.split("\n")]


def _first_str(*candidates: Any) -> str:
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []

"""Red instrument for references to the deleted ``sugar.floor_terms`` shim.

The removed helper was exactly ``value.to_term(owner=owner)``.  Every enrolled
offender must therefore call the receiving ``FloorValue.to_term`` directly;
recreating a compatibility module would hide, rather than retire, this axis.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import _Ctor, make_var
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_source_tree.tree import SourceFile

ROOT = Path(__file__).parents[1] / "src" / "sugar_lift_py_tests" / "floor"
TARGETS = (
    ROOT / "call_site_value.py",
    ROOT / "symbolic_value.py",
)
DELETED_MODULE = "sugar_lift_py_tests.sugar.floor_terms"


@dataclass(frozen=True)
class _Offender:
    path: str
    line: int
    kind: str
    replacement: str


def _dangling_floor_terms_offenders() -> tuple[_Offender, ...]:
    offenders: list[_Offender] = []
    for path in TARGETS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == DELETED_MODULE:
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)
                offenders.append(
                    _Offender(
                        path.name,
                        node.lineno,
                        "import",
                        "delete the import",
                    )
                )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in imported_names
            ):
                offenders.append(
                    _Offender(
                        path.name,
                        node.lineno,
                        "call",
                        "call the FloorValue's value.to_term(owner=owner) directly",
                    )
                )
    return tuple(sorted(offenders, key=lambda row: (row.path, row.line, row.kind)))


def test_dangling_floor_terms_residual_is_stable_zero() -> None:
    offenders = _dangling_floor_terms_offenders()
    imports = tuple(row for row in offenders if row.kind == "import")
    calls = tuple(row for row in offenders if row.kind == "call")
    audited = len(imports) + len(calls)
    discovered = len(offenders)

    assert discovered == audited
    assert not offenders, (
        "R_dangling_floor_terms is nonzero: "
        f"DISCOVERED={discovered} AUDITED={audited} "
        f"IMPORTS={len(imports)} CALLS={len(calls)}; "
        "replacement=delete each deleted-module import and call the exact "
        "FloorValue.to_term(owner=owner) receiver directly; "
        f"OFFENDERS={offenders!r}"
    )


def test_symbolic_isinstance_re_i_regexflag_projects_value_directly(tmp_path) -> None:
    regex_flag = SymbolicValue(make_var("RegexFlag"))
    imported_flag = SymbolicValue(make_var("re.I"))

    outcome = regex_flag.test_python_type(imported_flag, _sites(tmp_path)[0])

    assert isinstance(outcome, Incomplete)
    operation = outcome.effect.witness.operation
    assert isinstance(operation, _Ctor)
    assert operation.name == "adt.is_python_type"
    assert operation.args == (imported_flag.term, regex_flag.term)


@pytest.mark.parametrize("receiver_kind", ("symbolic", "callsite"))
def test_setitem_projects_index_and_value_directly(
    tmp_path, receiver_kind: str
) -> None:
    receiver = _receiver(receiver_kind)
    index = TermValue(0)
    value = TermValue(7)

    outcome = receiver.setitem(index, value, _sites(tmp_path)[1])

    assert isinstance(outcome, Complete)
    assert outcome.value.term.args[1:] == (
        index.to_term(owner=f"{type(receiver).__name__}.setitem index"),
        value.to_term(owner=f"{type(receiver).__name__}.setitem value"),
    )


def test_callsite_append_projects_appended_value_directly(tmp_path) -> None:
    receiver = _receiver("callsite")
    value = TermValue(7)

    outcome = receiver.append_with(value, _sites(tmp_path)[2])

    assert isinstance(outcome, Complete)
    assert outcome.value.term.args[1] == value.to_term(
        owner="CallSiteValue.append_with value"
    )


@pytest.mark.parametrize("receiver_kind", ("symbolic", "callsite"))
def test_delitem_projects_index_directly(tmp_path, receiver_kind: str) -> None:
    receiver = _receiver(receiver_kind)
    index = TermValue(0)

    outcome = receiver.delitem(index, _sites(tmp_path)[3])

    assert isinstance(outcome, Complete)
    assert outcome.value.term.args[1] == index.to_term(
        owner=f"{type(receiver).__name__}.delitem index"
    )


def _receiver(kind: str):
    if kind == "symbolic":
        return SymbolicValue(make_var("xs"))
    return CallSiteValue(
        target_name="list",
        arg_values=(),
        parameters=(),
        term=make_var("xs"),
        body=None,
        site="list-construction",
    )


def _sites(tmp_path):
    path = tmp_path / "floor_terms_reproducer.py"
    path.write_text(
        "import re\n"
        "from re import RegexFlag\n"
        "def exercise(xs):\n"
        "    isinstance(re.I, RegexFlag)\n"
        "    xs[0] = 7\n"
        "    xs.append(7)\n"
        "    del xs[0]\n",
        encoding="utf-8",
    )
    body = next(SourceFile.from_path(path).functions()).body
    return tuple(statement.fragment for statement in body)

from __future__ import annotations

import importlib.util
from pathlib import Path

_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "factory_zero_tolerance.py"
_SPEC = importlib.util.spec_from_file_location("factory_zero_tolerance", _SCANNER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)

scan_source = _SCANNER.scan_source
scan_package = _SCANNER.scan_package
format_offenders = _SCANNER.format_offenders


def test_scanner_names_every_forbidden_factory_construction_class() -> None:
    source = """
import ast
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.floor import SymbolicValue

class IncompleteFunctionBody(Exception):
    pass

class Visitor(ast.NodeVisitor):
    pass

def classify_demo(node, body, ctx, temporal):
    isinstance(node, ast.If)
    ast.walk(node)
    ctor("py.value", [])
    SymbolicValue(node)
    body.reduce(ctx)
    temporal.bind_value("x", node)
"""

    assert [
        (row.line, row.kind)
        for row in scan_source(
            source,
            "factory/source_fragment.py",
            scope="factory",
        )
    ] == [
        (6, "non-contract-third-result"),
        (9, "semantic-ast-classification"),
        (12, "semantic-ast-classification"),
        (15, "ir-construction"),
        (16, "floor-value-construction"),
        (17, "sugar-body-reduction"),
        (18, "temporal-binding-construction"),
    ]


def test_structural_source_fragment_child_projection_is_allowed() -> None:
    source = """
import ast

def binop_left(self):
    self._require(ast.BinOp)
    assert isinstance(self.node, ast.BinOp)
    return SourceFragment.from_node(self.node.left, self.filename)
"""

    assert (
        scan_source(
            source,
            "factory/source_fragment.py",
            scope="factory",
        )
        == []
    )


def test_semantic_factory_and_leaf_sugar_classifiers_are_loud() -> None:
    factory = """
import ast

def classify_loop_control_scope(self):
    return any(isinstance(node, ast.Break) for node in ast.walk(self.node))
"""
    match_sugar = """
import ast

def _match_ground(pattern, subject):
    if isinstance(pattern, ast.MatchValue):
        return pattern.value == subject
"""
    subscript = """
import ast

def _structural_target(node):
    while isinstance(node, ast.Subscript):
        node = node.value
    return node
"""

    assert [
        row.kind
        for row in scan_source(
            factory,
            "factory/source_fragment.py",
            scope="factory",
        )
    ] == ["semantic-ast-classification"]
    assert [
        row.kind
        for row in scan_source(
            match_sugar,
            "sugar/match_sugar.py",
            scope="sugar",
        )
    ] == ["semantic-ast-classification"]
    assert [
        row.kind
        for row in scan_source(
            subscript,
            "sugar/subscript_assign_sugar.py",
            scope="sugar",
        )
    ] == ["semantic-ast-classification"]


def test_node_kind_semantic_literal_classifier_is_loud() -> None:
    source = """
import ast

class NodeKind:
    @classmethod
    def of(cls, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, str)):
            return cls.PRIMITIVE_LITERAL
        return cls(type(node).__name__)
"""

    assert [
        row.kind
        for row in scan_source(
            source,
            "factory/node_kind.py",
            scope="factory",
        )
    ] == ["semantic-ast-classification"]


def test_install_source_dig_resolution_ast_is_not_construction() -> None:
    source = """
import ast

def resolve_external_source(node):
    return [child for child in ast.walk(node) if isinstance(child, ast.Name)]
"""

    assert (
        scan_source(
            source,
            "sugar/install_source_dig.py",
            scope="sugar",
        )
        == []
    )


def test_current_behavior_side_doors_are_stable_zero() -> None:
    """Law: R_behavior_side_doors > 0 ⇒ red. No baseline may green non-zero debt.

    Install-source dig AST inspection remains exempt only for re-entry classification
    (see scanner scope rules); every other reported locus is debt.
    """
    offenders = scan_package(_KIT / "src" / "sugar_lift_py_tests")

    assert not any(
        row.path == "sugar/install_source_dig.py"
        and row.kind == "semantic-ast-classification"
        for row in offenders
    )

    assert offenders == [], (
        "R>0 ⇒ CI red. Factory may only select Sugar | FactoryPanic; "
        f"R_behavior_side_doors={len(offenders)}; promote each locus into Sugar "
        "and delete factory/sugar helpers (do not relocate):\n"
        + format_offenders(offenders)
    )


def test_scanner_report_names_r_and_replacement_plans() -> None:
    report = _SCANNER.format_report(
        [
            _SCANNER.Offender("factory/sugar_constructors.py", 17, "ir-construction"),
            _SCANNER.Offender(
                "factory/sugar_constructors.py", 10, "non-contract-third-result"
            ),
        ]
    )
    assert "R_behavior_side_doors = 2" in report
    assert "ir-construction" in report
    assert "Promote IR operand" in report or "sugar_lift_py_tests.ir" in report
    assert "non-contract-third-result" in report
    assert "Sugar | FactoryPanic" in report

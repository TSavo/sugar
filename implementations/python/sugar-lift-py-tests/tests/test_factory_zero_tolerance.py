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
scan_factory = _SCANNER.scan_factory
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

def side_doors(node, body, ctx, temporal):
    isinstance(node, ast.If)
    ast.walk(node)
    ctor("py.value", [])
    SymbolicValue(node)
    body.reduce(ctx)
    temporal.bind_value("x", node)
"""

    assert [(row.line, row.kind) for row in scan_source(source, "factory/demo.py")] == [
        (6, "non-contract-third-result"),
        (9, "semantic-ast-classification"),
        (13, "semantic-ast-classification"),
        (14, "semantic-ast-classification"),
        (15, "ir-construction"),
        (16, "floor-value-construction"),
        (17, "sugar-body-reduction"),
        (18, "temporal-binding-construction"),
    ]


def test_current_factory_has_zero_behavior_construction_side_doors() -> None:
    offenders = scan_factory(_KIT / "src" / "sugar_lift_py_tests" / "factory")

    assert offenders == [], (
        "factory/ may only select a registered Sugar or raise FactoryPanic; "
        "promote every behavior constructor to Sugar:\n" + format_offenders(offenders)
    )

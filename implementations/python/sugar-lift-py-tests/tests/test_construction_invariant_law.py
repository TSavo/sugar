from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


_SCRIPT = (
    Path(__file__).parents[1] / "scripts" / "construction_invariant_law.py"
)
_SPEC = importlib.util.spec_from_file_location("construction_invariant_law", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
LAW = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = LAW
_SPEC.loader.exec_module(LAW)


def _classes(source: str) -> set[str]:
    return {finding.violation_class for finding in LAW.scan_python_source(source, "planted.py")}


def test_each_reject_class_has_a_structural_planted_twin() -> None:
    assert _classes(
        """
def decode(raw):
    content_cid = cid_of_json(raw)
    return AuthenticatedThing(raw=raw, cid=content_cid)
"""
    ) == {"SELF-HASHING-AS-AUTHORITY"}

    assert _classes(
        """
def resolve(symbol):
    if symbol == "pytest.raises":
        return EffectBoundary()
"""
    ) == {"NAME-SPELLING-OVERLOAD-GATE"}

    assert _classes(
        """
import ast
def _expr(node):
    if isinstance(node, ast.Constant):
        return StringValue(node.value)
    return ObjectValue("made", ())
"""
    ) == {"SECOND-CONSTRUCTION-PATH"}

    assert _classes(
        """
import ast
def transfer(statement: ast.stmt, state):
    if isinstance(statement, ast.If):
        return state
    if isinstance(statement, ast.For):
        return state
    return state
"""
    ) == {"NON-EXHAUSTIVE-VARIANT-COVERAGE"}

    assert _classes(
        """
def desugar(value):
    if value is None:
        return Complete(None)
    return Complete(value)
"""
    ) == {"FABRICATED-COMPLETION-FALLBACK"}


def test_discrimination_negatives_do_not_false_positive() -> None:
    source = """
import ast

def checksum(payload):
    return cid_of_json(payload)

def decode(raw, graph):
    reconstructed = graph.resolve(raw)
    if reconstructed.to_value() != raw:
        raise AuthenticationError("not byte-identical")
    return ResolvedThing(reconstructed)

def measure(node):
    if isinstance(node, ast.Constant):
        return type(node).__name__
    return "other"

STATEMENT_TYPES = frozenset(ast.stmt.__subclasses__())
def transfer(statement, state):
    if isinstance(statement, ast.If):
        return state
    raise UnsupportedStatement(type(statement).__name__)

def desugar(value):
    if value is None:
        raise TypedGap("opaque")
    return Complete(value)
"""
    assert LAW.scan_python_source(source, "clean.py") == []


def test_rust_benign_catchall_and_default_fallback_are_loud() -> None:
    source = """
fn decode(value: Value) -> Outcome {
    match value {
        Value::Known(v) => Outcome::Complete(v),
        _ => Outcome::Complete(Default::default()),
    }
}
"""
    findings = LAW.scan_rust_source(source, "planted.rs")
    assert {finding.violation_class for finding in findings} == {
        "FABRICATED-COMPLETION-FALLBACK",
        "NON-EXHAUSTIVE-VARIANT-COVERAGE",
    }


def test_report_names_file_line_class_and_required_fix() -> None:
    findings = LAW.scan_python_source(
        'def resolve(name):\n    return TABLE.get(name, "pytest.raises")\n',
        "construction/door.py",
    )
    rendered = LAW.format_report(findings)
    assert "construction/door.py:2" in rendered
    assert "NAME-SPELLING-OVERLOAD-GATE" in rendered
    assert "required fix:" in rendered
    assert "R_construction_invariant_violations = 1" in rendered


def test_cli_is_red_on_a_planted_violation_and_green_on_clean_source(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text(
        'def resolve(name):\n    return TABLE.get(name, "pytest.raises")\n',
        encoding="utf-8",
    )
    red = subprocess.run(
        [sys.executable, str(_SCRIPT), "--repo", str(tmp_path), str(planted)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert red.returncode == 1
    assert "NAME-SPELLING-OVERLOAD-GATE" in red.stdout

    planted.write_text("def identity(value):\n    return value\n", encoding="utf-8")
    green = subprocess.run(
        [sys.executable, str(_SCRIPT), "--repo", str(tmp_path), str(planted)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert green.returncode == 0
    assert "R_construction_invariant_violations = 0" in green.stdout

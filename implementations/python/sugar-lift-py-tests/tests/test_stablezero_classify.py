from __future__ import annotations

import importlib.util
from pathlib import Path

import sugar_lift_python_source.source_oracle as source_oracle
import sugar_source_tree.tree as source_tree

from sugar_lift_py_tests.gap.info import ConstructionGap
from sugar_lift_py_tests.gap.panic import ConstructionPanic


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_SCRIPT = sugar_lift_py_tests_package_root() / "scripts" / "stablezero_classify.py"
_SPEC = importlib.util.spec_from_file_location("stablezero_classify", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)


class _Span:
    start_line = 7


class _Sugar:
    def __init__(self, result):
        self._result = result

    def desugar(self, _ctx=None):
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


class _Function:
    def __init__(self, name: str, result):
        self._name = name
        self._result = result

    def line_col_span(self):
        return _Span()

    def name(self):
        return self._name

    def sugar(self):
        return _Sugar(self._result)


class _SourceFile:
    functions_in_file = ()

    def __init__(self, _identity):
        pass

    def functions(self):
        return iter(self.functions_in_file)


def _classify(monkeypatch, tmp_path: Path, functions: tuple) -> dict:
    source = tmp_path / "fixture.py"
    source.write_text("def fixture():\n    pass\n", encoding="utf-8")
    _SourceFile.functions_in_file = functions
    monkeypatch.setattr(source_oracle, "path_source", lambda _path: object())
    monkeypatch.setattr(source_tree, "SourceFile", _SourceFile)
    return _MOD.classify(source, deadline=1.0)


def test_clean_function_is_the_truthful_stable_zero_face(
    monkeypatch, tmp_path: Path
) -> None:
    payload = _classify(
        monkeypatch,
        tmp_path,
        (_Function("clean", object()),),
    )

    assert payload["statuses"] == {"clean": 1}
    assert payload["completed_denominator"] == 1
    assert payload["R(construction_panics)"] == 0
    assert payload["stableZero"] is True


def test_construction_panic_is_a_named_red_residual_not_clean(
    monkeypatch, tmp_path: Path
) -> None:
    panic = ConstructionPanic(
        ConstructionGap(
            owner="stablezero-test",
            blame="fixture.py:7:0",
            observed="missing construction",
            requested="source-owned construction",
            fix="implement the producer",
        )
    )
    payload = _classify(
        monkeypatch,
        tmp_path,
        (_Function("panic", panic),),
    )

    assert payload["statuses"] == {"ConstructionPanic": 1}
    assert payload["completed_denominator"] == 1
    assert payload["R(construction_panics)"] == 1
    assert payload["stableZero"] is False
    assert payload["residuals"][0]["testimony"]["info"]["owner"] == "stablezero-test"

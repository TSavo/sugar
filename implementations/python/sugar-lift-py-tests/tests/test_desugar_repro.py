from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = (
    Path(__file__).parents[1] / "scripts" / "desugar_repro.py"
)
_SPEC = importlib.util.spec_from_file_location("desugar_repro", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)


class _Sugar:
    def __init__(self, result):
        self._result = result

    def desugar(self, _ctx=None):
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


class _Function:
    def __init__(self, result):
        self._result = result

    def sugar(self):
        return _Sugar(self._result)

    def line_col_span(self):
        return type("Span", (), {"start_line": 7})()


def test_desugar_one_counts_success_and_construction_panic_as_completed_attempts():
    clean = _MOD._desugar_one(_Function(object()), name="clean")
    panic = _MOD._desugar_one(
        _Function(BaseException("construction panic")),
        name="panic",
    )

    assert clean["status"] == "clean"
    assert panic["status"] == "BaseException"
    assert clean["timedOut"] is False
    assert panic["timedOut"] is False


def test_report_names_timeout_residual_and_requires_nonempty_denominator():
    report = _MOD._report(
        file="core/generic.py",
        functions=[
            {"status": "clean", "timedOut": False},
            {"status": "timeout", "timedOut": True},
        ],
        elapsed_s=1.25,
        deadline_seconds=180,
    )

    assert report["discovered"] == 2
    assert report["completed"] == 2
    assert report["R(timeout)"] == 1
    assert report["stableZero"] is False

    empty = _MOD._report(
        file="core/generic.py",
        functions=[],
        elapsed_s=0.0,
        deadline_seconds=180,
    )
    assert empty["R(timeout)"] == 0
    assert empty["stableZero"] is False


def test_report_splits_nonclean_statuses_into_zero_expected_floor_axes():
    report = _MOD._report(
        file="core/generic.py",
        functions=[
            {"status": "clean", "timedOut": False},
            {"status": "ConstructionPanic", "timedOut": False},
            {"status": "ConstructionPanic", "timedOut": False},
            {"status": "ExitSetFactoringGap", "timedOut": False},
        ],
        elapsed_s=1.25,
        deadline_seconds=180,
    )

    assert report["R(timeout)"] == 0
    assert report["R(construction_panics)"] == 2
    assert report["R(factoring_gaps)"] == 1
    assert report["stableZero"] is False


def test_open_source_file_binds_construction_context(tmp_path):
    source = tmp_path / "fixture.py"
    source.write_text("def f(cm):\n    with cm:\n        pass\n")

    source_file = _MOD._open_source_file(source, root=tmp_path)

    assert source_file.unit.construction_context is not None

"""ConstructionPanic crosses ordinary census catches without reclassification.

Only the per-file enumerate membranes may translate a construction panic into
terminal testimony.  Outer census shells must preserve the exception object and
purely re-raise it; an ``instrumentFailure`` means the instrument was blind,
which is the opposite fact.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from sugar_lift_py_tests.gap.info import ConstructionGap
from sugar_lift_py_tests.gap.panic import ConstructionPanic

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str) -> ModuleType:
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    path = _SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CONSUMER = _load("recensus_enumerate_consumer")
RECENSUS = _load("control_effect_recensus")


def _planted_panic(owner: str) -> ConstructionPanic:
    return ConstructionPanic(
        ConstructionGap(
            owner=owner,
            blame=f"fixture.py:{owner}",
            observed="planted census catch",
            requested="pure ConstructionPanic propagation",
            fix="pure re-raise outside the sanctioned audit membrane",
        )
    )


def _raise(error: BaseException):
    def boom(*_args, **_kwargs):
        raise error

    return boom


def test_instrument_failure_renderer_names_its_testimony() -> None:
    row = {
        "instrumentFailure": {
            "stageId": "recensus-enumerate-file-terminal/v1",
            "phase": "roster",
            "message": "typed module seat mismatch",
        }
    }
    rendered = RECENSUS._render_terminal_category(row)
    assert "stageId=recensus-enumerate-file-terminal/v1" in rendered
    assert "phase=roster" in rendered
    assert "message=typed module seat mismatch" in rendered


def test_missing_category_without_instrument_failure_stays_explicit() -> None:
    assert RECENSUS._render_terminal_category({}) == "?"


def _fixture_file(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.py"
    path.write_text("def fixture():\n    return 1\n", encoding="utf-8")
    return path


def test_outer_roster_escape_purely_reraises_construction_panic(
    tmp_path: Path, monkeypatch
) -> None:
    path = _fixture_file(tmp_path)
    planted = _planted_panic("outer-roster-escape")
    monkeypatch.setattr(CONSUMER, "demand_function_roster", _raise(planted))

    with pytest.raises(ConstructionPanic) as caught:
        RECENSUS.terminal_after_measure_escape(
            path=path,
            relative=path.name,
            workspace_root=tmp_path,
            error=ValueError("earlier outer error"),
        )

    assert caught.value is planted


def test_source_identity_purely_reraises_construction_panic(
    tmp_path: Path, monkeypatch
) -> None:
    path = _fixture_file(tmp_path)
    planted = _planted_panic("source-identity")
    from sugar_lift_python_source import source_oracle

    monkeypatch.setattr(source_oracle, "path_source", _raise(planted))

    with pytest.raises(ConstructionPanic) as caught:
        CONSUMER.measure_file_via_enumerate(
            workspace_root=tmp_path,
            file_rel=path.name,
            contract_refs={},
        )

    assert caught.value is planted


def test_main_file_producer_purely_reraises_construction_panic(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "pkg"
    root.mkdir()
    path = root / "fixture.py"
    path.write_text("def fixture():\n    return 1\n", encoding="utf-8")

    from pandas_floor_summary import corpus_cid
    from sugar_lift_py_tests.corpus_pin import pin_corpus

    observed = pin_corpus(root, distribution=root.name, version="test-pin")
    RECENSUS._PANDAS_3_0_3_AGGREGATE_HASH = observed.aggregate_hash
    RECENSUS._PANDAS_3_0_3_MANIFEST_SHAPE_CID = corpus_cid(list(observed.paths))
    planted = _planted_panic("main-file-producer")
    monkeypatch.setattr(CONSUMER, "measure_file_via_enumerate", _raise(planted))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "control_effect_recensus.py",
            str(root),
            "--corpus-root",
            str(root),
            "--corpus-version",
            "test-pin",
            "--commit",
            "planted-main-file-producer",
            "--out-dir",
            str(tmp_path / "out"),
        ],
    )

    with pytest.raises(ConstructionPanic) as caught:
        RECENSUS.main()

    assert caught.value is planted


@pytest.mark.parametrize(
    "phase,demand_name",
    [
        ("roster", "demand_function_roster"),
        ("context-manager-resolutions", "demand_context_manager_resolution_events"),
        ("residual", "demand_construction_residual"),
    ],
)
def test_sanctioned_per_file_membranes_enroll_construction_panic(
    tmp_path: Path,
    monkeypatch,
    phase: str,
    demand_name: str,
) -> None:
    path = _fixture_file(tmp_path)
    planted = _planted_panic(f"sanctioned-{phase}")

    if phase != "roster":
        monkeypatch.setattr(
            CONSUMER,
            "demand_function_roster",
            lambda **_kwargs: ([], []),
        )
    if phase == "residual":
        monkeypatch.setattr(
            CONSUMER,
            "demand_context_manager_resolution_events",
            lambda **_kwargs: ([], []),
        )
    monkeypatch.setattr(CONSUMER, demand_name, _raise(planted))

    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=tmp_path,
        file_rel=path.name,
        contract_refs={},
    )

    assert row["category"] == "panic"
    assert row["terminalKind"] == "construction-panic"
    assert len(row["constructionPanics"]) == 1
    assert row["panic"]["owner"] == planted.info.owner
    assert row["panic"]["coordinate"] == planted.info.blame
    assert row["panic"]["entrance"] == f"sugar.enumerate:{phase}"

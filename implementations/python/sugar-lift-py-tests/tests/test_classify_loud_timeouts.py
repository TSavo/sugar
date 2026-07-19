"""Focused instrument tests for #4894 loud-timeout classification."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import classify_loud_timeouts as mod  # noqa: E402


def _completed(rel: str, bound: int, elapsed: float) -> dict[str, Any]:
    return {
        "file": rel,
        "category": "completed",
        "bound_seconds": bound,
        "elapsed_seconds": elapsed,
        "testimony": {
            "outcome": "completed",
            "file": rel,
            "facts": 1,
            "factory_walk_rows": 1,
            "effects": [],
        },
    }


def _panic(rel: str, bound: int, owner: str = "TemporalContext") -> dict[str, Any]:
    gap = {
        "owner": owner,
        "gap_kind": "construction",
        "gap_locus": "unit-test",
        "observed": "shape",
        "requested": "floor",
    }
    return {
        "file": rel,
        "category": "factory-construction-panic",
        "bound_seconds": bound,
        "elapsed_seconds": float(bound) * 0.5,
        "testimony": {
            "outcome": "factory-panic",
            "file": rel,
            "gap": gap,
        },
    }


def _timeout(rel: str, bound: int) -> dict[str, Any]:
    return {
        "file": rel,
        "category": "timeout-or-hang",
        "reason": f"child exceeded {bound}s",
        "bound_seconds": bound,
        "elapsed_seconds": float(bound),
    }


def test_sqlalchemy_is_a_supported_timeout_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[tuple[str, ...], bool, Path]] = []

    def fake_discover(args) -> int:  # noqa: ANN001
        captured.append((tuple(args.packages), args.all_python_files, args.source_root))
        return 0

    monkeypatch.setattr(mod, "run_discover_timeouts", fake_discover)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "classify_loud_timeouts.py",
            "sqlalchemy",
            "--all-python-files",
            "--source-root",
            "vendor/sqlalchemy",
            "--discover-timeouts",
            "unused.json",
        ],
    )

    assert mod.main() == 0
    assert captured == [(("sqlalchemy",), True, Path("vendor/sqlalchemy"))]


def test_bounded_child_uses_heartbeat_only_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_env: dict[str, str] = {}

    def fake_run(*args, **kwargs):  # noqa: ANN002, ANN003
        del args
        captured_env.update(kwargs["env"])
        return mod.subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        mod,
        "_classify_child",
        lambda **kwargs: {"category": "completed", "file": kwargs["rel"]},
    )

    mod.run_child_at_bound(
        script=tmp_path / "child.py",
        path=tmp_path / "source.py",
        rel="sqlalchemy/test_example.py",
        timeout_seconds=30,
    )

    assert captured_env["SUGAR_ENGINE_PROGRESS"] == "1"
    assert captured_env["SUGAR_ENGINE_TRACE_EVENTS"] == "0"


def test_discovery_finish_is_not_timeout_blob(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_run(*, script, path, rel, timeout_seconds):  # noqa: ANN001
        calls.append(timeout_seconds)
        return _completed(rel, timeout_seconds, elapsed=1.5)

    monkeypatch.setattr(mod, "run_child_at_bound", fake_run)
    row = mod.classify_file(
        script=Path("corpus_fatal_triage.py"),
        path=Path("x.py"),
        rel="numpy/x.py",
        discovery_bound=10,
        escalation_bounds=(60, 120, 300),
        skip_discovery=False,
    )
    assert row is None
    assert calls == [10]


def test_escalation_records_completes_at_60(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*, script, path, rel, timeout_seconds):  # noqa: ANN001
        if timeout_seconds == 10:
            return _timeout(rel, 10)
        if timeout_seconds == 60:
            return _completed(rel, 60, elapsed=22.0)
        raise AssertionError(f"unexpected bound {timeout_seconds}")

    monkeypatch.setattr(mod, "run_child_at_bound", fake_run)
    row = mod.classify_file(
        script=Path("corpus_fatal_triage.py"),
        path=Path("x.py"),
        rel="pandas/tests/slow.py",
        discovery_bound=10,
        escalation_bounds=(60, 120, 300),
        skip_discovery=False,
    )
    assert row is not None
    assert row["verdict"] == "completes-at-bound"
    assert row["bound_seconds"] == 60
    assert row["was_discovery_timeout"] is True
    assert row["perf_candidate"] is False
    assert row["cause_class"] == "A"
    assert row["cause_class_label"] == "bound-tight"
    assert len(row["attempts"]) == 2


def test_panic_after_escalation_attributes_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*, script, path, rel, timeout_seconds):  # noqa: ANN001
        if timeout_seconds <= 60:
            return _timeout(rel, timeout_seconds)
        return _panic(rel, timeout_seconds, owner="RaiseSugar")

    monkeypatch.setattr(mod, "run_child_at_bound", fake_run)
    row = mod.classify_file(
        script=Path("corpus_fatal_triage.py"),
        path=Path("x.py"),
        rel="numpy/y.py",
        discovery_bound=10,
        escalation_bounds=(60, 120, 300),
        skip_discovery=True,
    )
    assert row is not None
    assert row["verdict"] == "completes-with-panic"
    assert row["owner"] == "RaiseSugar"
    assert row["fingerprint"][0] == "RaiseSugar"
    assert row["cause_class"] == "B"
    assert row["cause_class_label"] == "hidden-panic"


def test_hang_at_max_bound_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*, script, path, rel, timeout_seconds):  # noqa: ANN001
        return _timeout(rel, timeout_seconds)

    monkeypatch.setattr(mod, "run_child_at_bound", fake_run)
    row = mod.classify_file(
        script=Path("corpus_fatal_triage.py"),
        path=Path("x.py"),
        rel="pandas/tests/io/formats/test_to_string.py",
        discovery_bound=10,
        escalation_bounds=(60, 120, 300),
        skip_discovery=False,
    )
    assert row is not None
    assert row["verdict"] == "hang-at-max-bound"
    assert row["bound_seconds"] == 300
    assert "budget-exceeded" in row["next_owner"]
    assert row["cause_class"] == "D"
    assert row["cause_class_label"] == "hang"
    # discovery + three escalations
    assert [a["bound_seconds"] for a in row["attempts"]] == [10, 60, 120, 300]


def test_cause_class_tags_A_B_C_D_E() -> None:
    """Every final verdict maps to exactly one A–E cause class."""
    assert (
        mod.cause_class_for_verdict(
            verdict="completes-at-bound",
            bound_seconds=60,
            elapsed_seconds=22.0,
            perf_candidate=False,
        )
        == "A"
    )
    assert (
        mod.cause_class_for_verdict(
            verdict="completes-with-panic",
            bound_seconds=60,
            elapsed_seconds=30.0,
        )
        == "B"
    )
    assert (
        mod.cause_class_for_verdict(
            verdict="completes-at-bound",
            bound_seconds=300,
            elapsed_seconds=150.0,
            perf_candidate=True,
        )
        == "C"
    )
    assert (
        mod.cause_class_for_verdict(
            verdict="completes-at-bound",
            bound_seconds=60,
            elapsed_seconds=130.0,
            perf_candidate=False,
        )
        == "C"
    )
    assert (
        mod.cause_class_for_verdict(
            verdict="hang-at-max-bound",
            bound_seconds=300,
            elapsed_seconds=300.0,
        )
        == "D"
    )
    assert (
        mod.cause_class_for_verdict(
            verdict="bare-exception",
            bound_seconds=120,
            elapsed_seconds=90.0,
        )
        == "E"
    )
    # Intermediate timeout and crash/signal are not A–E product-cause tags.
    assert mod.cause_class_for_verdict(verdict="timeout-at-bound") is None
    assert mod.cause_class_for_verdict(verdict="other:crash") is None


def test_perf_complete_class_C_on_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*, script, path, rel, timeout_seconds):  # noqa: ANN001
        if timeout_seconds < 300:
            return _timeout(rel, timeout_seconds)
        return _completed(rel, 300, elapsed=180.0)

    monkeypatch.setattr(mod, "run_child_at_bound", fake_run)
    row = mod.classify_file(
        script=Path("corpus_fatal_triage.py"),
        path=Path("x.py"),
        rel="pandas/tests/perf.py",
        discovery_bound=10,
        escalation_bounds=(60, 120, 300),
        skip_discovery=True,
    )
    assert row is not None
    assert row["verdict"] == "completes-at-bound"
    assert row["cause_class"] == "C"
    assert row["perf_candidate"] is True


def test_bare_exception_class_E(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*, script, path, rel, timeout_seconds):  # noqa: ANN001
        if timeout_seconds == 60:
            return {
                "file": rel,
                "category": "bare-exception",
                "bound_seconds": 60,
                "elapsed_seconds": 45.0,
                "testimony": {"exception_type": "RuntimeError"},
            }
        return _timeout(rel, timeout_seconds)

    monkeypatch.setattr(mod, "run_child_at_bound", fake_run)
    row = mod.classify_file(
        script=Path("corpus_fatal_triage.py"),
        path=Path("x.py"),
        rel="numpy/bare.py",
        discovery_bound=10,
        escalation_bounds=(60, 120, 300),
        skip_discovery=True,
    )
    assert row is not None
    assert row["verdict"] == "bare-exception"
    assert row["cause_class"] == "E"
    assert row["exception_type"] == "RuntimeError"


def test_summarize_ranks_panic_owners_and_keeps_hangs_loud() -> None:
    rows = [
        {
            "file": "a.py",
            "verdict": "completes-at-bound",
            "bound_seconds": 60,
            "elapsed_seconds": 18.0,
            "perf_candidate": False,
        },
        {
            "file": "b.py",
            "verdict": "completes-at-bound",
            "bound_seconds": 300,
            "elapsed_seconds": 150.0,
            "perf_candidate": True,
        },
        {
            "file": "c.py",
            "verdict": "completes-with-panic",
            "bound_seconds": 60,
            "owner": "TemporalContext",
            "fingerprint": [
                "TemporalContext",
                "construction",
                "locus",
                "obs",
                "req",
            ],
            "gap": {
                "owner": "TemporalContext",
                "gap_kind": "construction",
                "gap_locus": "locus",
                "observed": "obs",
                "requested": "req",
            },
        },
        {
            "file": "d.py",
            "verdict": "hang-at-max-bound",
            "bound_seconds": 300,
        },
        {
            "file": "e.py",
            "verdict": "bare-exception",
            "bound_seconds": 120,
            "exception_type": "ValueError",
        },
    ]
    summary = mod.summarize_ledger(rows)
    assert summary["verdict_counts"]["completes-at-bound"] == 2
    assert summary["verdict_counts"]["completes-with-panic"] == 1
    assert summary["verdict_counts"]["hang-at-max-bound"] == 1
    assert summary["verdict_counts"]["bare-exception"] == 1
    assert summary["cause_class_counts"] == {
        "A": 1,
        "B": 1,
        "C": 1,
        "D": 1,
        "E": 1,
    }
    assert summary["ranked_B_owners"][0]["owner"] == "TemporalContext"
    assert summary["ranked_B_owners"][0]["cause_class"] == "B"
    assert summary["perf_candidate_count"] == 1
    assert summary["hang_files"] == ["d.py"]
    assert summary["R_live_factory_panic_files"] == 1
    assert summary["owners"]["TemporalContext"] == 1


def test_summarize_residual_uses_recensus_floor() -> None:
    """Instrument stays red until recensus-scale blob + hang are drained."""
    rows = [
        {
            "file": "a.py",
            "verdict": "completes-with-panic",
            "bound_seconds": 60,
            "owner": "X",
            "fingerprint": ["X", "k", "l", "o", "r"],
            "gap": {
                "owner": "X",
                "gap_kind": "k",
                "gap_locus": "l",
                "observed": "o",
                "requested": "r",
            },
        }
    ]
    summary = mod.summarize_ledger(rows)
    # summarize_ledger alone does not compute residual; residual is main/run path.
    assert summary["cause_class_counts"]["B"] == 1
    assert mod.RECENSUS_TIMEOUT_BLOB_COUNT == 293
    assert max(0, mod.RECENSUS_TIMEOUT_BLOB_COUNT - 1) == 292


def test_ledger_resume_and_append(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    mod.append_ledger(
        ledger,
        {"file": "numpy/a.py", "verdict": "completes-at-bound", "bound_seconds": 60},
    )
    mod.append_ledger(
        ledger,
        {"file": "pandas/b.py", "verdict": "hang-at-max-bound", "bound_seconds": 300},
    )
    done = mod.already_classified(ledger)
    assert done == {"numpy/a.py", "pandas/b.py"}
    rows = mod.load_ledger_rows(ledger)
    assert len(rows) == 2
    # malformed lines must not corrupt resume
    ledger.write_text(
        ledger.read_text(encoding="utf-8") + "not-json\n", encoding="utf-8"
    )
    assert mod.already_classified(ledger) == {"numpy/a.py", "pandas/b.py"}


def test_load_file_list_txt_and_json(tmp_path: Path) -> None:
    txt = tmp_path / "files.txt"
    txt.write_text("# comment\nnumpy/a.py\npandas/b.py\n", encoding="utf-8")
    assert mod.load_file_list(txt) == ["numpy/a.py", "pandas/b.py"]
    js = tmp_path / "files.json"
    js.write_text(json.dumps({"timeout_files": ["numpy/c.py"]}), encoding="utf-8")
    assert mod.load_file_list(js) == ["numpy/c.py"]


def test_extract_progress_from_engine_log_ranks_sugar_hotspots(tmp_path: Path) -> None:
    """Macro hotspots: heartbeats name the stuck sugar without profiling guesswork."""
    log = tmp_path / "engine.jsonl"
    rows = [
        {
            "schema": "sugar.engine.log.v1",
            "event": "enter",
            "sugar": "ForSugar",
            "role": "statement",
            "site": "a.py:1",
            "fingerprint": "ForSugar|statement|a.py:1",
            "sequence": 1,
        },
        {
            "schema": "sugar.engine.log.v1",
            "event": "exit",
            "sugar": "ForSugar",
            "role": "factory.new.statement",
            "site": "a.py:1",
            "fingerprint": "ForSugar|factory.new.statement|a.py:1",
            "sequence": 1,
            "elapsed_ms": 100.0,
        },
        {
            "schema": "sugar.engine.log.v1",
            "event": "exit",
            "sugar": "numpy.ma.core.array",
            "role": "dig.resolve_value",
            "site": "numpy.ma.core.array",
            "fingerprint": "numpy.ma.core.array|dig.resolve_value|numpy.ma.core.array",
            "sequence": 2,
            "elapsed_ms": 400.0,
        },
        {
            "schema": "sugar.engine.log.v1",
            "event": "exit",
            "sugar": "module_seed",
            "role": "dig.module_seed",
            "site": "core.py:10",
            "fingerprint": "module_seed|dig.module_seed|core.py:10",
            "sequence": 3,
            "elapsed_ms": 200.0,
        },
        {
            "schema": "sugar.engine.log.v1",
            "event": "heartbeat",
            "sugar": "ForSugar",
            "role": "statement",
            "site": "a.py:1",
            "fingerprint": "ForSugar|statement|a.py:1",
            "sequence": 1,
            "oldest_elapsed_ms": 5000,
            "active_stack": ["ForSugar|statement|a.py:1"],
        },
        {
            "schema": "sugar.engine.log.v1",
            "event": "heartbeat",
            "sugar": "ForSugar",
            "role": "statement",
            "site": "a.py:1",
            "fingerprint": "ForSugar|statement|a.py:1",
            "sequence": 1,
            "oldest_elapsed_ms": 10000,
            "active_stack": ["ForSugar|statement|a.py:1", "NameSugar|term|a.py:2"],
        },
        {
            "schema": "sugar.engine.log.v1",
            "event": "heartbeat",
            "sugar": "TemporalContext",
            "role": "term",
            "site": "a.py:3",
            "fingerprint": "TemporalContext|term|a.py:3",
            "sequence": 2,
            "oldest_elapsed_ms": 12000,
            "active_stack": ["TemporalContext|term|a.py:3"],
        },
    ]
    log.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    progress = mod.extract_progress_from_engine_log(log)
    assert progress is not None
    assert progress["heartbeat_count"] == 3
    assert progress["sugar_hotspots"][0]["sugar"] == "ForSugar"
    assert progress["sugar_hotspots"][0]["heartbeat_count"] == 2
    assert progress["last_heartbeat"]["sugar"] == "TemporalContext"
    assert progress["last_heartbeat"]["active_stack"] == ["TemporalContext|term|a.py:3"]
    # Second-cut phases: dig vs factory_new vs reduce (from exit elapsed_ms).
    assert progress["phase_share"]["dig"] > progress["phase_share"]["factory_new"]
    assert progress["dig_target_ms"][0]["target"] == "numpy.ma.core.array"
    assert "dig.resolve_value" in progress["role_ms"]


def test_phase_from_role_bisects_factory_and_dig() -> None:
    assert mod._phase_from_role("dig.resolve_value") == "dig"
    assert mod._phase_from_role("dig.module_seed") == "dig"
    assert mod._phase_from_role("dig.build_body") == "dig"
    assert mod._phase_from_role("factory.select") == "factory_select"
    assert mod._phase_from_role("factory.new.statement") == "factory_new"
    assert mod._phase_from_role("statement") == "reduce"
    assert mod._phase_from_role("file") == "file"


def test_run_child_timeout_attaches_last_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On kill, ledger must carry last_progress — not only stopwatch reason."""
    import subprocess

    log_dir = tmp_path / "engine-logs"

    def fake_run(*args, **kwargs):  # noqa: ANN001, ANN002
        env = kwargs.get("env") or {}
        log_path = Path(env["SUGAR_ENGINE_LOG"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            json.dumps(
                {
                    "schema": "sugar.engine.log.v1",
                    "event": "heartbeat",
                    "sugar": "SequentialDigBody",
                    "role": "body",
                    "site": "slow.py:10",
                    "fingerprint": "SequentialDigBody|body|slow.py:10",
                    "sequence": 9,
                    "oldest_elapsed_ms": 9000,
                    "active_stack": ["SequentialDigBody|body|slow.py:10"],
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 10))

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    row = mod.run_child_at_bound(
        script=Path("corpus_fatal_triage.py"),
        path=Path("slow.py"),
        rel="numpy/slow.py",
        timeout_seconds=10,
        engine_log_dir=log_dir,
    )
    assert row["category"] == "timeout-or-hang"
    assert row["timeout_hotspot"] == "SequentialDigBody"
    assert row["timeout_last_sugar"] == "SequentialDigBody"
    assert row["timeout_last_site"] == "slow.py:10"
    assert row["last_progress"]["heartbeat_count"] == 1
    assert row["last_progress"]["sugar_hotspots"][0]["sugar"] == "SequentialDigBody"

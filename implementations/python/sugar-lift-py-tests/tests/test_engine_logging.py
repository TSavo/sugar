from __future__ import annotations

import json
import logging
import time

from sugar_lift_py_tests import engine_log


def _events(caplog):
    return [json.loads(record.message) for record in caplog.records]


def test_reduction_span_logs_nested_engine_progress(caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="sugar_lift_py_tests.engine")

    with engine_log.reduction_span(
        sugar="BlockSugar", role="statement", site="t.py:1:0"
    ):
        with engine_log.reduction_span(
            sugar="ReturnSugar", role="statement", site="t.py:2:4"
        ):
            pass

    events = _events(caplog)
    assert [event["event"] for event in events] == ["enter", "enter", "exit", "exit"]
    assert events[1]["depth"] == 2
    assert events[-1]["active_depth"] == 0
    assert events[-1]["elapsed_ms"] >= 0


def test_engine_heartbeat_reports_the_live_reduction_stack(caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="sugar_lift_py_tests.engine")

    with engine_log.reduction_span(sugar="AwaitSugar", role="term", site="t.py:3:11"):
        engine_log._emit_heartbeats(now=time.monotonic() + 1.0, minimum_seconds=0.01)

    heartbeat = next(
        event for event in _events(caplog) if event["event"] == "heartbeat"
    )
    assert heartbeat["oldest_elapsed_ms"] >= 1000
    assert heartbeat["active_stack"] == ["AwaitSugar|term|t.py:3:11"]


def test_engine_live_log_is_flushed_outside_log_capture(tmp_path) -> None:
    path = tmp_path / "engine.jsonl"
    previous = engine_log._LIVE_HANDLER
    engine_log._LIVE_HANDLER = None
    try:
        engine_log.configure_live_log(str(path))
        with engine_log.reduction_span(sugar="NameSugar", role="term", site="t.py:1:0"):
            pass
        payloads = [json.loads(line) for line in path.read_text().splitlines()]
        assert [payload["event"] for payload in payloads] == ["enter", "exit"]
    finally:
        if engine_log._LIVE_HANDLER is not None:
            engine_log.LOGGER.removeHandler(engine_log._LIVE_HANDLER)
            engine_log._LIVE_HANDLER.close()
        engine_log._LIVE_HANDLER = previous


def test_engine_log_serialization_cannot_break_deep_reduction(
    monkeypatch, caplog
) -> None:
    caplog.set_level(logging.DEBUG, logger="sugar_lift_py_tests.engine")

    def recursion_boundary(*args, **kwargs):
        raise RecursionError("no encoder stack remains")

    monkeypatch.setattr(engine_log.json, "dumps", recursion_boundary)

    with engine_log.reduction_span(sugar="ListSugar", role="term", site="deep.py:1:0"):
        pass

    assert engine_log._ACTIVE == {}

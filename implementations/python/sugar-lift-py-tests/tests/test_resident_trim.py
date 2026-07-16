from __future__ import annotations

import logging
from typing import Any

from sugar_lift_py_tests import lift_rpc


def _capture(monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []

    def _fake_info(msg: str, *args: Any, **kwargs: Any) -> None:
        events.append((msg, kwargs.get("extra") or {}))

    monkeypatch.setattr(lift_rpc._TRANSPORT_LOG, "info", _fake_info)
    return events


def test_trim_is_gated_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("SUGAR_KIT_TRIM_EVERY", raising=False)
    events = _capture(monkeypatch)
    lift_rpc._maybe_trim_resident(250)
    assert not any(name == "resident_trim" for name, _ in events)


def test_trim_only_fires_on_the_cadence(monkeypatch) -> None:
    monkeypatch.setenv("SUGAR_KIT_TRIM_EVERY", "250")
    events = _capture(monkeypatch)
    lift_rpc._maybe_trim_resident(249)  # not a multiple -> no-op
    assert not events
    lift_rpc._maybe_trim_resident(500)  # multiple -> trims (where malloc_trim exists)
    if lift_rpc._malloc_trim():
        assert [name for name, _ in events] == ["resident_trim"]
        extra = events[0][1]
        assert extra["request_count"] == 500
        assert "rss_before_kib" in extra and "rss_after_kib" in extra


def test_malloc_trim_returns_bool_and_never_raises() -> None:
    # Resolves libc once and caches; must be a plain bool on every platform.
    assert isinstance(lift_rpc._malloc_trim(), bool)
    assert isinstance(lift_rpc._malloc_trim(), bool)


def test_trim_no_op_when_malloc_trim_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("SUGAR_KIT_TRIM_EVERY", "10")
    monkeypatch.setattr(lift_rpc, "_malloc_trim", lambda: False)
    events = _capture(monkeypatch)
    lift_rpc._maybe_trim_resident(10)  # cadence hit, but trim unavailable
    assert not any(name == "resident_trim" for name, _ in events)


def test_malloc_trim_failure_is_surfaced_not_swallowed(monkeypatch) -> None:
    def _boom(_arg: int) -> int:
        raise OSError("trim exploded")

    monkeypatch.setattr(lift_rpc, "_MALLOC_TRIM", _boom)
    events = _capture(monkeypatch)
    warnings: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        lift_rpc._TRANSPORT_LOG,
        "warning",
        lambda msg, *a, **k: warnings.append((msg, k.get("extra") or {})),
    )
    assert lift_rpc._malloc_trim() is False
    assert [name for name, _ in warnings] == ["malloc_trim_failed"]


def test_trim_rss_fields_survive_the_transport_formatter() -> None:
    # The wall harvests rss_before/after from transport.jsonl; the structured
    # formatter serializes only a fixed field whitelist, so these must be on it.
    import json

    record = logging.LogRecord(
        "sugar.kit.transport", logging.INFO, __file__, 0, "resident_trim", (), None
    )
    record.stage = "resident.trim"
    record.request_count = 250
    record.rss_before_kib = 400000
    record.rss_after_kib = 300000
    payload = json.loads(lift_rpc._StructuredTransportFormatter().format(record))
    assert payload["rss_before_kib"] == 400000
    assert payload["rss_after_kib"] == 300000
    assert payload["request_count"] == 250


def test_transport_logger_name_unchanged() -> None:
    # Guards the logger the wall harvests trim/profile lines from.
    assert lift_rpc._TRANSPORT_LOG is logging.getLogger("sugar.kit.transport")

"""Teeth for the opt-in refusal trace (``refusal_trace``).

With ``SUGAR_KIT_TRACE_REFUSALS=1`` the one panic door writes, per refusal,
the testimony whole and the binding state at the refusing read; off, it
writes nothing and the refusal is the same.
"""

from __future__ import annotations

import json

import pytest

from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import refuse_unbound_evaluation
from sugar_lift_py_tests.temporal.temporal_context import TemporalContext


def _records(directory) -> list[dict]:
    return [
        json.loads(line)
        for path in sorted(directory.glob("refusals-*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _refuse(temporal) -> ConstructionPanic:
    with pytest.raises(ConstructionPanic) as caught:
        refuse_unbound_evaluation(
            name="x",
            key="evaluation:abc@loop:1",
            evaluation="evaluation:abc",
            site="pkg/m.py:3:4",
            temporal=temporal,
        )
    return caught.value


def test_the_trace_records_the_keys_bound_at_the_refusing_read(tmp_path, monkeypatch):
    monkeypatch.setenv("SUGAR_KIT_TRACE_REFUSALS", "1")
    monkeypatch.setenv("SUGAR_KIT_TRACE_DIR", str(tmp_path))
    temporal = (
        TemporalContext.empty()
        .bind_value("evaluation:abc", object(), blame="arm 1")
        .bind_value("evaluation:abc/y", object())
        .bind_value("evaluation:other", object())
    )
    panic = _refuse(temporal)
    assert panic.info.owner == "EvaluationRefSugar"
    (record,) = _records(tmp_path)
    assert record["owner"] == "EvaluationRefSugar"
    assert "evaluation:abc@loop:1" in record["observed"]
    assert record["detail"] == {
        "name": "x",
        "key": "evaluation:abc@loop:1",
        "evaluation": "evaluation:abc",
    }
    keys = [row["key"] for row in record["bindings"]]
    # Builtin names are omitted; every key the path bound is in view.
    assert keys == ["evaluation:abc", "evaluation:abc/y", "evaluation:other"]
    assert record["bindings"][0]["blame"] == "arm 1"
    assert record["near"] == ["evaluation:abc", "evaluation:abc/y"]
    assert record["trace"] and record["trace"][-1]["qualname"].endswith("construction_panic")


def test_the_trace_is_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SUGAR_KIT_TRACE_REFUSALS", raising=False)
    monkeypatch.setenv("SUGAR_KIT_TRACE_DIR", str(tmp_path))
    _refuse(TemporalContext.empty())
    assert _records(tmp_path) == []

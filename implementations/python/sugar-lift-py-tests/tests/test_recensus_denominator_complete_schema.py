"""The post-compose consumer must use the denominator testimony the seal owns."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_SCRIPT = _SCRIPTS / "control_effect_recensus.py"


def _load():
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "control_effect_recensus_denominator_schema", _SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_post_compose_consumer_uses_sealed_file_completeness() -> None:
    """A stale top-level spelling must not override sealed nested testimony."""
    module = _load()
    complete, refusal = module._consume_sealed_files_complete(
        {
            "planCid": "sha256:plan",
            "denominator": {
                "complete": False,
                "files": {"complete": True},
            },
        },
        measured_commit="227089c8",
    )

    assert complete is True
    assert refusal is None


def test_missing_sealed_file_completeness_refuses_without_width() -> None:
    """Missing testimony is instrument failure, never an assumed completion."""
    module = _load()
    complete, refusal = module._consume_sealed_files_complete(
        {
            "planCid": "sha256:plan",
            "frontierWidth": 7,
            "denominator": {"complete": True, "files": {}},
        },
        measured_commit="227089c8",
    )

    assert complete is None
    assert refusal is not None
    assert refusal["kind"] == "control-effect-recensus-unmeasured/v1"
    assert refusal["measured"] is False
    assert refusal["measuredCommit"] == "227089c8"
    assert refusal["planCid"] == "sha256:plan"
    assert refusal["missingShards"] == ["compose"]
    assert "frontierWidth" not in refusal
    assert refusal["instrumentFailures"] == [
        {
            "stageId": "compose-terminal-aggregate-seal/v1",
            "observedEventType": "builtins.KeyError",
            "phase": "post-compose-denominator-consumer",
            "reason": "sealed board missing denominator.files.complete testimony",
        }
    ]


def test_false_sealed_file_completeness_refuses_as_contradictory() -> None:
    """Compose cannot seal an incomplete file denominator; false is not a board."""
    module = _load()
    complete, refusal = module._consume_sealed_files_complete(
        {
            "planCid": "sha256:plan",
            "frontierWidth": 7,
            "denominator": {"files": {"complete": False}},
        },
        measured_commit="227089c8",
    )

    assert complete is None
    assert refusal is not None
    assert refusal["measured"] is False
    assert "frontierWidth" not in refusal
    assert refusal["instrumentFailures"][0]["observedEventType"] == (
        "builtins.ValueError"
    )
    assert refusal["instrumentFailures"][0]["reason"] == (
        "sealed board denominator.files.complete testimony is not true"
    )

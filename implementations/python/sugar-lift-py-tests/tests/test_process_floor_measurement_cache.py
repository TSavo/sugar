"""Teeth for content-addressed process-floor terminal cache.

No full corpus lift: these plant store/lookup only. Supervised-enum integration
stays in test_supervised_enum_supervisor.py.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"
_SPEC = importlib.util.spec_from_file_location(
    "process_floor_measurement_cache",
    _SCRIPTS / "process_floor_measurement_cache.py",
)
assert _SPEC is not None and _SPEC.loader is not None
CACHE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = CACHE
_SPEC.loader.exec_module(CACHE)


def _key(**overrides) -> CACHE.MeasurementKey:
    base = dict(
        tip="tip-aaa",
        corpus_manifest_cid="blake3-512:" + "a" * 128,
        axis=CACHE.DEFAULT_AXIS,
        file_content_cid="blake3-512:" + "b" * 128,
        demand_table_cid="demand:local-derivation",
        file_timeout_ms=30000,
    )
    base.update(overrides)
    return CACHE.MeasurementKey(**base)


def _terminal(*, file: str = "a.py", category: str = "completed") -> dict:
    return CACHE.terminal_to_payload(
        file=file,
        category=category,
        returncode=0,
        signal_name=None,
        stderr_tail="",
        terminal={"kind": "testimony", "outcome": category, "file": file},
    )


def test_hit_returns_same_terminal(tmp_path: Path) -> None:
    shelf = CACHE.ProcessFloorTerminalCache(tmp_path)
    key = _key()
    payload = _terminal()
    assert shelf.store(key, payload) is not None
    hit = shelf.lookup(key)
    assert hit is not None
    assert hit["category"] == "completed"
    assert hit["file"] == "a.py"
    assert hit["terminal"]["outcome"] == "completed"


def test_file_content_change_is_miss(tmp_path: Path) -> None:
    shelf = CACHE.ProcessFloorTerminalCache(tmp_path)
    key_a = _key(file_content_cid="blake3-512:" + "1" * 128)
    shelf.store(key_a, _terminal(file="a.py"))
    key_b = _key(file_content_cid="blake3-512:" + "2" * 128)
    assert shelf.lookup(key_b) is None
    # Original still hits.
    assert shelf.lookup(key_a) is not None


def test_axis_change_refuses_cross_axis_reuse(tmp_path: Path) -> None:
    shelf = CACHE.ProcessFloorTerminalCache(tmp_path)
    key = _key(axis="supervised_enum_terminal")
    shelf.store(key, _terminal())
    other = _key(axis="some-other-axis")
    assert shelf.lookup(other) is None


def test_corrupt_row_is_refused_not_served(tmp_path: Path) -> None:
    shelf = CACHE.ProcessFloorTerminalCache(tmp_path)
    key = _key()
    path = shelf.store(key, _terminal())
    assert path is not None
    # Flip a byte inside the key field.
    data = json.loads(path.read_text(encoding="utf-8"))
    data["key"]["tip"] = "tip-CORRUPTED"
    path.write_text(json.dumps(data), encoding="utf-8")
    try:
        shelf.lookup(key)
        raised = False
    except CACHE.CacheRefuse:
        raised = True
    assert raised, "corrupt key must refuse, not serve"


def test_timeout_and_native_crash_never_banked(tmp_path: Path) -> None:
    shelf = CACHE.ProcessFloorTerminalCache(tmp_path)
    key = _key()
    assert (
        shelf.store(
            key,
            CACHE.terminal_to_payload(
                file="t.py",
                category="timeout",
                returncode=None,
                signal_name=None,
                stderr_tail="exceeded",
                terminal=None,
            ),
        )
        is None
    )
    assert (
        shelf.store(
            key,
            CACHE.terminal_to_payload(
                file="t.py",
                category="native-crash",
                returncode=-11,
                signal_name="SIGSEGV",
                stderr_tail="",
                terminal=None,
            ),
        )
        is None
    )
    assert shelf.lookup(key) is None


def test_stored_row_carries_key_for_self_proof(tmp_path: Path) -> None:
    shelf = CACHE.ProcessFloorTerminalCache(tmp_path)
    key = _key()
    path = shelf.store(key, _terminal())
    assert path is not None
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == CACHE.SCHEMA
    assert data["key"] == key.to_json()

"""Teeth for the kit's opt-in stack sampler (#8416, slowness is the defect).

The CLI kills the kit with SIGKILL when one request outlives its response
deadline, so a profile written at exit never exists. The sampler writes its
aggregate while the kit runs; these tests pin what it counts and that a
SIGKILLed process still leaves a profile naming where the time went.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from sugar_lift_py_tests import kit_sample_profile
from sugar_lift_py_tests.kit_sample_profile import StackSampler


def _sampler(tmp_path: Path) -> StackSampler:
    return StackSampler(tmp_path / "p.json", thread_id=threading.get_ident())


def _leaf(sampler: StackSampler) -> None:
    sampler.sample_frame(sys._getframe())


def _middle(sampler: StackSampler) -> None:
    _leaf(sampler)


def _recurse(sampler: StackSampler, depth: int) -> None:
    if depth == 0:
        sampler.sample_frame(sys._getframe())
        return
    _recurse(sampler, depth - 1)


def _named(counts, suffix: str) -> int:
    return sum(n for name, n in counts.items() if name.endswith(suffix))


def test_a_sample_counts_the_leaf_every_frame_and_every_edge(tmp_path):
    sampler = _sampler(tmp_path)
    for _ in range(3):
        _middle(sampler)
    assert sampler.samples == 3
    assert _named(sampler.self_counts, ":_leaf") == 3
    assert _named(sampler.inclusive, ":_leaf") == 3
    assert _named(sampler.inclusive, ":_middle") == 3
    edges = [name for name in sampler.edges if name.endswith(":_leaf")]
    assert len(edges) == 1 and ":_middle -> " in edges[0]
    assert sampler.edges[edges[0]] == 3
    (stack,) = sampler.stacks
    assert stack.endswith(":_middle;" + next(k for k in sampler.self_counts))


def test_recursion_counts_a_frame_once_per_sample(tmp_path):
    sampler = _sampler(tmp_path)
    _recurse(sampler, 25)
    assert sampler.samples == 1
    assert _named(sampler.inclusive, ":_recurse") == 1
    assert sampler.max_depth >= 26
    assert len(sampler.last_stack) >= 26


def test_samples_are_tagged_by_the_request_in_flight(tmp_path):
    sampler = _sampler(tmp_path)
    sampler.note_request("sugar.enumerate:universe", 62)
    _middle(sampler)
    _middle(sampler)
    sampler.note_request(None)
    _middle(sampler)
    assert sampler.requests == {"sugar.enumerate:universe": 2, "(between requests)": 1}


def test_flush_replaces_the_file_with_the_aggregate(tmp_path):
    sampler = _sampler(tmp_path)
    sampler.note_request("sugar.enumerate:universe", 62)
    _middle(sampler)
    sampler.flush()
    _middle(sampler)
    sampler.flush()
    data = json.loads((tmp_path / "p.json").read_text())
    assert data["schema"] == kit_sample_profile.SCHEMA
    assert data["samples"] == 2
    assert data["request"]["inFlight"] == "sugar.enumerate:universe"
    assert data["request"]["id"] == 62
    assert data["self"][0]["frame"].endswith(":_leaf")
    assert data["self"][0]["share"] == 1.0
    assert [p.name for p in tmp_path.iterdir()] == ["p.json"]  # no .tmp left


def test_the_lists_keep_only_the_heaviest_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(kit_sample_profile, "TOP", 2)
    sampler = _sampler(tmp_path)
    _recurse(sampler, 3)
    _middle(sampler)
    data = sampler.snapshot()
    assert all(len(data[key]) <= 2 for key in ("self", "inclusive", "edges", "stacks"))


def test_nothing_starts_without_the_variable(monkeypatch):
    monkeypatch.setattr(kit_sample_profile, "_ACTIVE", None)
    assert kit_sample_profile.start_from_env({}) is None
    kit_sample_profile.note_request("initialize", 1)  # a no-op, never an error


def test_the_variable_starts_one_sampler_with_a_file_from_the_start(tmp_path, monkeypatch):
    monkeypatch.setattr(kit_sample_profile, "_ACTIVE", None)
    env = {
        kit_sample_profile.ENV_DIR: str(tmp_path),
        kit_sample_profile.ENV_INTERVAL_MS: "5",
        kit_sample_profile.ENV_FLUSH_S: "0.05",
    }
    sampler = kit_sample_profile.start_from_env(env)
    try:
        assert sampler is not None
        assert kit_sample_profile.start_from_env(env) is sampler
        assert sampler.interval_s == pytest.approx(0.005)
        assert sampler.flush_s == pytest.approx(0.05)
        assert sampler.out_path == tmp_path / f"kit-profile-{os.getpid()}.json"
        assert sampler.out_path.is_file()
    finally:
        sampler.stop()
        monkeypatch.setattr(kit_sample_profile, "_ACTIVE", None)


_BUSY_CHILD = textwrap.dedent(
    """
    import importlib.util, sys
    # The module alone, by path: the child needs none of the package.
    spec = importlib.util.spec_from_file_location("kit_sample_profile", sys.argv[1])
    kit_sample_profile = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kit_sample_profile)

    def stuck_in_the_universe_answer():
        total = 0
        while True:
            total += 1

    kit_sample_profile.start_from_env()
    kit_sample_profile.note_request("sugar.enumerate:universe", 62)
    print("ready", flush=True)
    stuck_in_the_universe_answer()
    """
)


def test_a_sigkilled_process_still_leaves_its_profile(tmp_path):
    env = {
        **os.environ,
        kit_sample_profile.ENV_DIR: str(tmp_path),
        kit_sample_profile.ENV_INTERVAL_MS: "5",
        kit_sample_profile.ENV_FLUSH_S: "0.1",
    }
    child = subprocess.Popen(
        [sys.executable, "-c", _BUSY_CHILD, kit_sample_profile.__file__],
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "ready"
        profile = tmp_path / f"kit-profile-{child.pid}.json"
        deadline = time.monotonic() + 30
        data: dict = {}
        while time.monotonic() < deadline:
            try:
                data = json.loads(profile.read_text())
            except (OSError, json.JSONDecodeError):
                data = {}
            if data.get("samples", 0) >= 5:
                break
            time.sleep(0.05)
    finally:
        child.send_signal(signal.SIGKILL)
        child.wait(timeout=10)
    assert child.returncode == -signal.SIGKILL
    data = json.loads(profile.read_text())
    assert data["samples"] >= 5
    assert data["self"][0]["frame"].endswith(":stuck_in_the_universe_answer")
    # The sampler may take one sample before the request is noted.
    assert data["requests"]["sugar.enumerate:universe"] >= data["samples"] - 1
    assert data["request"]["inFlight"] == "sugar.enumerate:universe"
    assert data["request"]["id"] == 62

"""File-open phase timers persist — not only painted then thrown away."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"
SCRIPT = _SCRIPTS / "control_effect_recensus.py"


def _load():
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location("control_effect_recensus", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_measure_file_persists_phase_timers(tmp_path: Path) -> None:
    consumer_path = _SCRIPTS / "recensus_enumerate_consumer.py"
    spec = importlib.util.spec_from_file_location(
        "recensus_enumerate_consumer", consumer_path
    )
    assert spec is not None and spec.loader is not None
    consumer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(consumer)

    path = tmp_path / "mod.py"
    path.write_text(
        "def a():\n    return 1\n\ndef b():\n    return 2\n",
        encoding="utf-8",
    )
    row = consumer.measure_file_via_enumerate(
        workspace_root=tmp_path,
        file_rel="mod.py",
    )

    # Module.sugar is the honest first terminal. Timing testimony must survive
    # on that red row; requiring completion would look past the frontier.
    assert row["category"] == "panic"
    timing = row["timing"]
    for key in (
        "t_open_s",
        "t_materialize_s",
        "materialize_calls",
        "t_populate_s",
        "t_enumerate_s",
        "t_sugar_loop_s",
        "dominant_phase",
        "module_materialize",
    ):
        assert key in timing, timing
    assert timing["sugar_fn_count"] == 2
    assert timing["module_materialize"]["materializeCalls"] >= 0
    assert float(timing["t_open_s"]) >= 0.0
    assert float(timing["t_sugar_loop_s"]) >= 0.0


def test_running_counts_line_includes_timing_fields(tmp_path: Path) -> None:
    """End-to-end: running-counts.jsonl carries phase breakdown for each file."""
    module = _load()
    from pandas_floor_summary import corpus_cid
    from sugar_lift_py_tests.corpus_pin import pin_corpus

    root = tmp_path / "pkg"
    root.mkdir()
    (root / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    observed = pin_corpus(root, distribution=root.name, version="test-pin")
    module._PANDAS_3_0_3_AGGREGATE_HASH = observed.aggregate_hash
    module._PANDAS_3_0_3_MANIFEST_SHAPE_CID = corpus_cid(list(observed.paths))
    out = tmp_path / "out"
    saved = sys.argv
    sys.argv = [
        "control_effect_recensus.py",
        str(root),
        "--corpus-root",
        str(root),
        "--corpus-version",
        "test-pin",
        "--commit",
        "profile-tip",
        "--out-dir",
        str(out),
    ]
    try:
        code = module.main()
    finally:
        sys.argv = saved
    assert code in (0, 1)
    lines = (out / "running-counts.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines, "running-counts.jsonl must have at least one file row"
    row = json.loads(lines[-1])
    assert "t_open_s" in row
    assert "t_materialize_s" in row
    assert "materialize_calls" in row
    assert "t_populate_s" in row
    assert "t_enumerate_s" in row
    assert "t_sugar_loop_s" in row
    assert "dominant_phase" in row
    assert "module_materialize" in row
    assert row["file_s"] is not None

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_TOOL = Path(__file__).parents[4] / "tools" / "wall_frontier_telemetry.py"
_SPEC = importlib.util.spec_from_file_location("wall_frontier_telemetry", _TOOL)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
frontier_vector = _MODULE.frontier_vector
markdown = _MODULE.markdown


def test_recovered_frontier_vector_carries_all_three_lanes(tmp_path) -> None:
    path = tmp_path / "frontier.json"
    path.write_text(
        json.dumps(
            {
                "kind": "recovered-construction-audit",
                "panics": [{}, {}],
                "suppressedDescendants": [{}],
                "effects": [{}, {}, {}],
            }
        ),
        encoding="utf-8",
    )

    vector = frontier_vector(path)
    assert vector == (2, 1, 3)
    assert "independent: 2" in markdown("pandas", "https://run", vector)
    assert "suppressed: 1" in markdown("pandas", "https://run", vector)
    assert "effects: 3" in markdown("pandas", "https://run", vector)


def test_fail_fast_or_incomplete_output_is_not_accepted_as_frontier(tmp_path) -> None:
    path = tmp_path / "frontier.json"
    path.write_text(json.dumps({"kind": "lift-report"}), encoding="utf-8")

    with pytest.raises(ValueError, match="recovered-construction-audit"):
        frontier_vector(path)

from __future__ import annotations

import json

import pytest

from tools.wall_frontier_telemetry import frontier_vector, markdown


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

from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _production_source_file import production_source_file  # noqa: E402
from sugar_source_tree.reporter import CollectingReporter  # noqa: E402


def test_preconstruction_phases_share_one_artifact_graph_cache(
    tmp_path: Path, monkeypatch
) -> None:
    import sugar_lift_python_source.manager_summary_derivation as summaries
    import sugar_lift_python_source.source_call_preconstruction as calls

    observed_graphs: list[dict] = []
    observed_frames: list[dict] = []

    def record_cache(
        *_args,
        artifact_graph_cache=None,
        source_frame_cache=None,
        **_kwargs,
    ) -> None:
        assert artifact_graph_cache is not None
        assert source_frame_cache is not None
        observed_graphs.append(artifact_graph_cache)
        observed_frames.append(source_frame_cache)

    monkeypatch.setattr(calls, "populate_source_visible_call_frames", record_cache)
    monkeypatch.setattr(summaries, "populate_source_derived_resource_refs", record_cache)
    source = tmp_path / "arbitrary_consumer.py"
    source.write_text("def constructed(value):\n    return value\n", encoding="utf-8")

    production_source_file(
        source,
        root=tmp_path,
        reporter=CollectingReporter(),
    )

    assert len(observed_graphs) == 2
    assert observed_graphs[0] is observed_graphs[1]
    assert observed_frames[0] is observed_frames[1]

"""Teeth for tools/scorecard_carry.py: the scorecard's totals count every test once."""

from __future__ import annotations

import repo_root_test_support  # noqa: F401 -- puts tools/ on sys.path

import scorecard_carry as carry


def test_summary_counts_are_full_totals(tmp_path):
    one = tmp_path / "shard-00.json"
    two = tmp_path / "shard-01.json"
    one.write_text(
        '{"items": {"a": {"buckets": ["passed"]}, "b": {"buckets": ["failed"]}}}',
        encoding="utf-8",
    )
    two.write_text(
        '{"items": {"c": {"buckets": ["skipped"]}, "e": {"buckets": ["error"]}},'
        ' "collectionErrors": ["d.py"]}',
        encoding="utf-8",
    )
    totals = carry.summarize([one, two], "suite")
    assert totals["counts"]["collected"] == 4
    assert totals["counts"]["passed"] == 1
    assert totals["counts"]["failed"] == 1
    assert totals["counts"]["error"] == 1
    assert totals["counts"]["collectionError"] == 1
    assert totals["failedNodeIds"] == ["b", "e"]
    assert totals["collectionErrorNodeIds"] == ["d.py"]


def test_filtered_summaries_count_only_the_listed_files(tmp_path):
    suite = tmp_path / "suite.json"
    suite.write_text(
        '{"items": {"pkg/tests/test_twin.py::t": {"buckets": ["passed"]},'
        ' "pkg/tests/test_other.py::t": {"buckets": ["failed"]}},'
        ' "collectionErrors": ["pkg/tests/test_other.py"]}',
        encoding="utf-8",
    )
    totals = carry.summarize(
        [], "twins", filtered=[suite], only_files=["python/pkg/tests/test_twin.py"]
    )
    assert totals["counts"]["collected"] == 1
    assert totals["counts"]["passed"] == 1
    assert totals["counts"]["collectionError"] == 0


def test_a_collection_error_is_one_failing_test_in_the_row(tmp_path):
    """A file that fails to import is in ``total`` and ``failed``: the row's
    passed/total cell shows it failing, never a smaller total (#8416)."""
    shard = tmp_path / "shard-00.json"
    shard.write_text(
        '{"items": {"a": {"buckets": ["passed"]}, "b": {"buckets": ["failed"]}},'
        ' "collectionErrors": ["pkg/tests/test_stale_import.py"]}',
        encoding="utf-8",
    )
    result = carry.scorecard_result(carry.summarize([shard], "source"))
    assert result == {"measured": True, "passed": 1, "total": 3, "failed": 2}


def test_a_shard_whose_every_file_failed_to_import_is_measured(tmp_path):
    shard = tmp_path / "shard-00.json"
    shard.write_text('{"items": {}, "collectionErrors": ["t.py"]}', encoding="utf-8")
    result = carry.scorecard_result(carry.summarize([shard], "source"))
    assert result == {"measured": True, "passed": 0, "total": 1, "failed": 1}

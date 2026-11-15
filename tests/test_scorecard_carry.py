"""Teeth for tools/scorecard_carry.py: a result is carried only on identical fingerprints."""

from __future__ import annotations

from pathlib import Path

import repo_root_test_support  # noqa: F401 -- puts tools/ on sys.path

import scorecard_carry as carry

SOURCE = '''
import os

LIMIT = 3


def alpha(x):
    return x + LIMIT


class Box:
    size = 1

    def beta(self):
        def inner():
            return 2
        return inner()

    @property
    def gamma(self):
        return self.size
'''


def test_function_fingerprint_ignores_line_shifts_and_comments():
    table, _ = carry.fingerprint_table(SOURCE)
    shifted, _ = carry.fingerprint_table("\n\n# a comment\n" + SOURCE)
    assert table == shifted


def test_a_body_edit_changes_only_that_function():
    table, _ = carry.fingerprint_table(SOURCE)
    edited, _ = carry.fingerprint_table(SOURCE.replace("return 2", "return 3"))
    assert edited["Box.beta"] != table["Box.beta"]
    assert edited["alpha"] == table["alpha"]
    assert edited[carry.MODULE_KEY] == table[carry.MODULE_KEY]


def test_skeleton_holds_module_level_statements_and_decorated_headers():
    table, _ = carry.fingerprint_table(SOURCE)
    constant, _ = carry.fingerprint_table(SOURCE.replace("LIMIT = 3", "LIMIT = 4"))
    assert constant[carry.MODULE_KEY] != table[carry.MODULE_KEY]
    added, _ = carry.fingerprint_table(SOURCE + "\n\ndef delta():\n    return 0\n")
    # An undecorated new def binds a name and nothing else at import.
    assert added[carry.MODULE_KEY] == table[carry.MODULE_KEY]
    decorated, _ = carry.fingerprint_table(SOURCE.replace("@property", "@staticmethod"))
    assert decorated[carry.MODULE_KEY] != table[carry.MODULE_KEY]


def test_code_keys_follow_the_owning_def():
    assert carry.code_key("Box.beta.<locals>.inner", carry.CO_OPTIMIZED) == "Box.beta"
    assert carry.code_key("alpha", carry.CO_OPTIMIZED) == "alpha"
    assert carry.code_key("<module>", 0) == carry.MODULE_KEY
    assert carry.code_key("Box", 0) == carry.MODULE_KEY
    assert carry.code_key("<lambda>", carry.CO_OPTIMIZED) == carry.MODULE_KEY


def _tree(root: Path, source: str) -> carry.Tree:
    (root / "mod.py").write_text(source, encoding="utf-8")
    return carry.Tree(str(root), {"mod.py": carry._sha(source.encode())}, True)


def test_store_carries_only_while_recorded_functions_are_unchanged(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    tree = _tree(work, SOURCE)
    store = carry.Store(tmp_path / "store", "k")
    session = carry.CarrySession(tree, store, None)
    sink = carry.Sink()
    sink.keys.add(("mod.py", "alpha"))
    depset = session._depset(sink)
    store.record("test", "t::a", store.put_object(depset), {"buckets": ["passed"]})

    assert store.lookup("test", "t::a", tree) == {"buckets": ["passed"]}

    # An edit to a function the test never ran: still carried.
    other = SOURCE.replace("return 2", "return 3")
    assert carry.Store(tmp_path / "store", "k").lookup(
        "test", "t::a", _tree(work, other)
    ) == {"buckets": ["passed"]}

    # An edit to the function it ran: rerun.
    changed = SOURCE.replace("return x + LIMIT", "return x - LIMIT")
    assert carry.Store(tmp_path / "store", "k").lookup(
        "test", "t::a", _tree(work, changed)
    ) is None


def test_summary_counts_are_full_totals(tmp_path):
    plan = tmp_path / "plan.json"
    run = tmp_path / "run.json"
    plan.write_text(
        '{"items": {"a": {"buckets": ["passed"], "how": "carried"},'
        ' "b": {"buckets": ["failed"], "how": "carried"}}}',
        encoding="utf-8",
    )
    run.write_text(
        '{"items": {"b": {"buckets": ["passed"], "how": "rerun"},'
        ' "c": {"buckets": ["skipped"], "how": "rerun"}}, "collectionErrors": ["d.py"]}',
        encoding="utf-8",
    )
    totals = carry.summarize([plan, run], "suite")
    assert totals["counts"]["collected"] == 3
    assert totals["counts"]["passed"] == 2
    assert totals["counts"]["failed"] == 0
    assert totals["counts"]["collectionError"] == 1
    assert totals["carry"] == {"rerun": 2, "carried": 1, "opaque": 0}

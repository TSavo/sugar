from __future__ import annotations

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile


def test_unchanged_if_mints_and_stores_its_branch_slot_once(monkeypatch, tmp_path):
    source = "def f(c):\n if c:\n  pass\n"
    path = tmp_path / "unchanged_if.py"
    path.write_text(source, encoding="utf-8")
    function = next(SourceFile(path_source(path)).functions())

    import sugar_source_tree.nodes as nodes

    mints = 0
    original = nodes.branch_result_slot

    def counted(test):
        nonlocal mints
        mints += 1
        return original(test)

    monkeypatch.setattr(nodes, "branch_result_slot", counted)
    sugar = function.sugar()

    assert mints == 1
    assert sugar.statements[0].branch_slot.slot_id.startswith("branch-result:")


def test_effectful_condition_is_constructed_once_and_one_slot_drives_all_faces(
    monkeypatch,
) -> None:
    source = "def f():\n x=1\n if predicate():\n  del x\n return x\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    reporter = CollectingReporter()
    function = next(SourceFile(path_source(path), reporter=reporter).functions())
    sugar = function.sugar()

    if_sugar = sugar.statements[1]
    read_sugar = sugar.statements[2].value
    assert read_sugar.state.slot == if_sugar.branch_slot
    assert read_sugar.state.when_true.cause.text == "x"
    assert all(
        type(value).__name__ != "Node" for value in vars(read_sugar.state).values()
    )

    from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar

    calls = 0
    original = CallSiteSugar.desugar

    def counted(self, ctx=None):
        nonlocal calls
        if self.target_name == "predicate":
            calls += 1
        return original(self, ctx)

    monkeypatch.setattr(CallSiteSugar, "desugar", counted)
    outcome = sugar.desugar()
    assert calls == 1

    exits = outcome.exits
    halted = next(exit_ for exit_ in exits if type(exit_).__name__ == "Halted")
    completed = next(exit_ for exit_ in exits if type(exit_).__name__ == "Completed")
    from sugar_lift_py_tests.floor.branch_result_coordinate import branch_result_guard

    assert halted.guard == branch_result_guard(if_sugar.branch_slot, if_sugar.site)
    assert completed.guard.kind == "not"

    predicate_cids = {
        node.fragment.seal().cid
        for node in reporter.present
        if node.kind == "Call" and node.fragment.text == "predicate()"
    }
    assert len(predicate_cids) == 1


def test_nested_function_reuses_source_if_slot_across_lexical_substitution(tmp_path):
    path = tmp_path / "nested_if.py"
    path.write_text(
        "def outer(captured):\n"
        " def inner(condition):\n"
        "  if condition:\n"
        "   return captured\n"
        "  return condition\n"
        " return inner(captured)\n",
        encoding="utf-8",
    )
    reporter = CollectingReporter()
    outer = next(SourceFile(path_source(path), reporter=reporter).functions())

    sugar = outer.sugar()

    inner = sugar.statements[0]
    nested_if = inner.statements[0]
    assert nested_if.branch_slot.slot_id.startswith("branch-result:")
    source_ifs = [node for node in reporter.present if node.kind == "If"]
    assert len({node.fragment.seal().cid for node in source_ifs}) == 1

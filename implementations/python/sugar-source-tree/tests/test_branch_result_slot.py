from __future__ import annotations

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.reporter import CollectingReporter
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def test_unchanged_if_mints_and_stores_its_branch_slot_once(monkeypatch, tmp_path):
    source = "def f(c):\n if c:\n  pass\n"
    path = tmp_path / "unchanged_if.py"
    path.write_text(source, encoding="utf-8")
    function = next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())

    import sugar_source_tree.nodes as nodes

    mints = 0
    original = nodes.branch_result_slot

    def counted(test, evaluation=None):
        nonlocal mints
        mints += 1
        return original(test, evaluation)

    monkeypatch.setattr(nodes, "branch_result_slot", counted)
    sugar = function.sugar()

    assert mints == 1
    assert sugar.statements[0].branch_slot.slot_id.startswith("branch-result:")


_LIVE_LOOP = "blake3-512:" + "ab" * 64


def test_each_live_loop_item_decides_its_own_slot_of_one_if(tmp_path):
    """A live loop's body is constructed once for every item, so its ``if``
    carries one construct-time slot.  At reduce each item decides its own
    qualification of it (``If.branch_slot`` with the item's key,
    ``branch_slot_here``): two items never share one decision."""
    from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment
    from sugar_lift_py_tests.sugar.evaluation_ref_sugar import branch_slot_here
    from sugar_source_tree.nodes import If

    source = (
        "def f(items, c):\n"
        "    total = 0\n"
        "    for item in items:\n"
        "        if c > 0:\n"
        "            x = 1\n"
        "        total = total + x\n"
        "    return total\n"
    )
    path = tmp_path / "live_loop_if.py"
    path.write_text(source, encoding="utf-8")
    function = next(
        SourceFile(
            path_source(path),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        ).functions()
    )
    (branch,) = [node for node in function.walk() if isinstance(node, If)]
    slot = branch.branch_slot({})

    assert branch_slot_here(slot) == slot
    items = []
    for index in (0, 1):
        segment = loop_iteration_segment(_LIVE_LOOP, index)
        with entered(segment):
            here = branch_slot_here(slot)
        assert here == branch.branch_slot({}, segment)
        items.append(here)
    assert items[0] != items[1], "two live items shared one branch decision"
    assert all(here != slot for here in items)


def test_a_reader_takes_the_slot_its_own_item_decided(tmp_path):
    """A reader in an inner loop's item reads the decision the outer item
    made; a decision made outside every item (a frame entry's module ``if``)
    is read inside an item too; anything else is undecided there."""
    from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment
    from sugar_lift_py_tests.sugar.evaluation_ref_sugar import branch_slot_here
    from sugar_source_tree.binding_state import BranchResultSlot

    slot = BranchResultSlot("branch-result:blake3-512:source@1:2#blake3-512:if")
    outer = loop_iteration_segment(_LIVE_LOOP, 0)
    inner = loop_iteration_segment("blake3-512:" + "cd" * 64, 3)
    with entered(outer):
        decided_outer = branch_slot_here(slot)
        with entered(inner):
            assert branch_slot_here(slot, {decided_outer.slot_id: True}) == (
                decided_outer
            )
            assert branch_slot_here(slot, {slot.slot_id: True}) == slot
            assert branch_slot_here(slot, {}) == branch_slot_here(slot)
            assert branch_slot_here(slot) != decided_outer
    other = BranchResultSlot("loop-wrote:blake3-512:post")
    with entered(outer):
        assert branch_slot_here(other) == other


def test_effectful_condition_is_constructed_once_and_one_slot_drives_all_faces(
    monkeypatch,
) -> None:
    source = "def f():\n x=1\n if predicate():\n  del x\n return x\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    reporter = CollectingReporter()
    function = next(SourceFile(path_source(path), reporter=reporter, construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())
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

    # ``predicate`` is unbound: its call may raise (its own halt), and every
    # other face stands where it completed.
    exits = outcome.exits
    halts = [exit_ for exit_ in exits if type(exit_).__name__ == "Halted"]
    (call_halt,) = [
        exit_
        for exit_ in halts
        if getattr(exit_.effect, "producer_node_owner", None)
        == "UnknownCallee:predicate"
    ]
    # The truth of what the call returned is the one truth rule's two faces
    # (#9018): its own halt stands beside the call's and the branch's.
    from sugar_lift_py_tests.effect import NameErrorEffect
    from sugar_lift_py_tests.outcome.exit_set import _are_exclusive, _conjuncts

    assert any(
        str(getattr(exit_.effect, "producer_node_owner", "")).endswith(".truth")
        for exit_ in halts
    ), halts
    (halted,) = [exit_ for exit_ in halts if isinstance(exit_.effect, NameErrorEffect)]
    completed = next(exit_ for exit_ in exits if type(exit_).__name__ == "Completed")
    from sugar_lift_py_tests.floor.branch_result_coordinate import branch_result_guard

    assert call_halt.guard.kind == "not"
    (completion,) = call_halt.guard.operands
    assert completion.name == "python:unknown_callee_call.completes"
    # The read halts beneath the call's completion under the ONE slot the
    # if decided; the completed face is the other side of that slot.
    assert completion in _conjuncts(halted.guard)
    assert branch_result_guard(if_sugar.branch_slot, if_sugar.site) in _conjuncts(
        halted.guard
    )
    assert completion in _conjuncts(completed.guard)
    assert _are_exclusive(halted.guard, completed.guard)

    predicate_cids = {
        node.fragment.seal().cid
        for node in reporter.present
        if node.kind == "Call" and node.fragment.text == "predicate()"
    }
    assert len(predicate_cids) == 1

"""D-class: retained If branch-result slot survives Name→bound-RHS rewrite.

Seal residual (7 files): ``If.substitute`` reported foreign branch-result slot
when ``if hashable:`` followed ``hashable = is_hashable(other)``.

Discriminator: hierarchy lie, not honest unwritten shape.
  - Slot identity is the SOURCE condition occurrence at first mint.
  - Name.substitute can replace the test Name with the bound RHS Node
    (Call span = assignment RHS), which is a different fragment seal.
  - Recomputing ``branch_result_slot(self.test)`` after that rewrite invents a
    foreign address for the same condition. The retained pair was correct.

Fix: when retained, reuse stored/authenticated pair; only defect if they
disagree with each other. Do not recompute expected from rewritten test.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.binding_state import branch_result_slot
from sugar_source_tree.nodes import FunctionDef, If
from sugar_source_tree.reporter import NULL_REPORTER
from sugar_source_tree.tree import SourceFile


def _open(tmp_path: Path, source: str) -> SourceFile:
    path = tmp_path / "m.py"
    path.write_text(source)
    return SourceFile(
        workspace_path_source(str(path), root=str(tmp_path)),
        reporter=NULL_REPORTER,
    )


def test_if_on_locally_bound_name_substitute_does_not_report_foreign_slot(
    tmp_path: Path,
) -> None:
    """``hashable = …; if hashable:`` must not BackendDefect on re-substitute."""
    source = (
        "def f(other):\n"
        "    hashable = is_hashable(other)\n"
        "    if hashable:\n"
        "        return 1\n"
        "    else:\n"
        "        return 2\n"
    )
    sf = _open(tmp_path, source)
    fn = next(n for n in sf.nodes() if isinstance(n, FunctionDef))
    # FunctionDef.substitute threads formals + body assigns — the production door.
    rewritten = fn.substitute({})
    assert rewritten is not None
    # Find the If that retained a slot (the hashable test).
    ifs = [n for n in rewritten.walk() if isinstance(n, If)]
    slotted = [
        n
        for n in ifs
        if getattr(n, "branch_result_slot_id", None) is not None
    ]
    assert slotted, "expected at least one If with a retained branch-result slot"
    target = slotted[0]
    stored = target.branch_result_slot_id
    auth = target.authenticated_branch_result_slot_id
    assert stored == auth
    # Second substitute must reuse the pair (not recompute from rewritten test).
    again = target.substitute({})
    if isinstance(again, type(target)):
        assert again.branch_result_slot_id == stored
        assert again.authenticated_branch_result_slot_id == auth


def test_first_mint_still_addresses_source_test_occurrence(tmp_path: Path) -> None:
    """First mint remains branch_result_slot of the source test Name."""
    source = (
        "def f(flag):\n"
        "    if flag:\n"
        "        return 1\n"
        "    else:\n"
        "        return 0\n"
    )
    sf = _open(tmp_path, source)
    fn = next(n for n in sf.nodes() if isinstance(n, FunctionDef))
    outer = next(n for n in fn.walk() if isinstance(n, If))
    expected = branch_result_slot(outer.test)
    out = outer.substitute({})
    node = out.statements[0] if hasattr(out, "statements") else out
    assert node.branch_result_slot_id == expected.slot_id
    assert node.authenticated_branch_result_slot_id == expected.slot_id

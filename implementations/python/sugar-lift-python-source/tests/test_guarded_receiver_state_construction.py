from dataclasses import replace

import pytest

from sugar_lift_py_tests.floor import (
    BlockValue,
    ObjectValue,
    TermValue,
    GuardedReceiverStateValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import and_, eq, make_var, num
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def test_guarding_a_snapshot_retains_and_conjoins_its_branch_not_an_unconditional_state():
    receiver = ObjectValue("Renamed", (), identity="owned")
    first = eq(make_var("first"), num(1))
    second = eq(make_var("second"), num(2))
    guarded = receiver.guarded(first).guarded(second)
    assert isinstance(guarded, GuardedReceiverStateValue)
    assert guarded.receiver is receiver
    assert guarded.guard == and_([second, first])
    assert guarded.to_term(owner="test") != receiver.to_term(owner="test")


def test_guarded_snapshot_rejects_a_non_receiver_instead_of_silently_ignoring_it():
    with pytest.raises(ConstructionPanic, match="GuardedReceiverStateValue"):
        GuardedReceiverStateValue(TermValue(7), and_([]))


@pytest.mark.parametrize("foreign", ["identity", "defining_class"])
def test_constructor_projection_refuses_a_foreign_guarded_snapshot(tmp_path, foreign):
    path = tmp_path / "classes.py"
    path.write_text("class Owned:\n    pass\nclass Foreign:\n    pass\n")
    tree = SourceFile(workspace_path_source(str(path), root=str(tmp_path)))
    owned, other = [
        node.sugar().desugar().completed_value()
        for node in tree.nodes()
        if node.kind == "ClassDef"
    ]
    receiver = owned.construct_receiver_state_from_block(None, "owned")
    alien = replace(
        receiver,
        **(
            {"identity": "alien"}
            if foreign == "identity"
            else {"defining_class": other}
        )
    )
    block = BlockValue((alien.guarded(eq(make_var("g"), num(1))),))
    with pytest.raises(ConstructionPanic) as caught:
        owned.construct_receiver_state_from_block(block, "owned")
    assert caught.value.info.owner == "ClassDefinitionValue.construct_receiver_state"
    assert caught.value.info.observed == "foreign constructed receiver snapshot"

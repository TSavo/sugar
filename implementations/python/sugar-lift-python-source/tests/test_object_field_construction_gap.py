"""A missing constructed field is a Floor gap, not an unknown receiver type."""

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import (
    ObjectField,
    ObjectValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.gap.info import GapKind, GapLocus
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor, make_var, str_const
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _site(tmp_path, member):
    path = tmp_path / "read_field.py"
    path.write_text(f"def read(receiver):\n    return receiver.{member}\n")
    return next(
        node.fragment
        for node in SourceFile(
            workspace_path_source(str(path), root=str(tmp_path))
        ).nodes()
        if node.kind == "Attribute"
    )


@pytest.mark.parametrize(
    "class_name, member", [("RenamedResource", "acquired"), ("Unrelated", "payload")]
)
def test_missing_field_panics_but_written_twin_projects(tmp_path, class_name, member):
    site = _site(tmp_path, member)
    receiver = ObjectValue(class_name, (ObjectField("marker", TermValue(3)),))
    written = receiver.with_field_store(member, TermValue(7))
    assert written.attribute(member, site, None) == ExitSet.completed(TermValue(7))

    # The write belongs to its own state, not to the original/other guard face.
    with pytest.raises(ConstructionPanic) as caught:
        receiver.attribute(member, site, None)
    assert not isinstance(caught.value, Exception)
    info = caught.value.info
    assert info.owner == "ObjectValue.attribute"
    assert info.observed == f"ObjectValue.{member}"
    assert info.gap_kind is GapKind.FLOOR
    assert info.gap_locus is GapLocus.CONSTRUCTION
    assert "read_field.py" in info.blame
    assert "source-authenticated" in info.requested


def test_deleted_field_keeps_authenticated_attribute_error(tmp_path):
    site = _site(tmp_path, "payload")
    receiver = ObjectValue("Renamed", (ObjectField("payload", TermValue(7)),))
    deleted = receiver.delattr("payload", site, None)
    deleted_value = deleted.completed_value()
    assert deleted_value is not None
    outcome = deleted_value.attribute("payload", site, None)
    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "AttributeError"


def test_deferred_helper_field_keeps_its_coordinate_not_a_missing_field_panic(tmp_path):
    site = _site(tmp_path, "payload")
    receiver = ObjectValue("Renamed", (), deferred_helper_fields=("payload",))
    outcome = receiver.attribute("payload", site, None)
    value = outcome.completed_value()
    assert value is not None
    assert value.to_term(owner="test") == ctor(
        "py.getattr", [receiver.to_term(owner="test"), str_const("payload")]
    )


def test_unknown_receiver_type_keeps_its_distinct_named_refusal(tmp_path):
    site = _site(tmp_path, "payload")
    receiver = SymbolicValue(make_var("unknown_receiver"))
    with pytest.raises(SugarNotWritten) as caught:
        receiver.attribute("payload", site, None)
    assert caught.value.owner == "SymbolicValue.attribute"

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor.builtin_class_member_value import (
    BuiltinClassMemberValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal
from sugar_source_tree.nodes import Attribute
from sugar_source_tree.tree import SourceFile


def _attribute_site(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "builtin_member.py"
    path.write_text("value = object.__str__\n", encoding="utf-8")
    tree = SourceFile.from_path(path.name)
    return next(node.fragment for node in tree.nodes() if isinstance(node, Attribute))


def test_builtin_object_str_member_retains_receiver_runtime_and_use(
    tmp_path, monkeypatch
) -> None:
    site = _attribute_site(tmp_path, monkeypatch)
    receiver = builtin_name_temporal().value_if_bound("object")

    outcome = receiver.attribute("__str__", site)

    assert type(outcome) is Complete
    assert type(outcome.value) is BuiltinClassMemberValue
    assert outcome.value.receiver is receiver
    assert outcome.value.member_name == "__str__"
    assert outcome.value.use_site is site
    assert outcome.value.runtime == receiver.runtime_identity


def test_builtin_object_member_authority_does_not_cross_class_member_or_use(
    tmp_path, monkeypatch
) -> None:
    site = _attribute_site(tmp_path, monkeypatch)
    temporal = builtin_name_temporal()
    receiver = temporal.value_if_bound("object")

    with pytest.raises(ConstructionPanic):
        temporal.value_if_bound("type").attribute("__str__", site)
    with pytest.raises(ConstructionPanic):
        receiver.attribute("__repr__", site)
    with pytest.raises(ConstructionPanic):
        receiver.attribute("__str__", "foreign-use")

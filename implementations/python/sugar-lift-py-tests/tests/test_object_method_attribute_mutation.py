from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.floor import ObjectMethodValue, TermValue
from sugar_lift_py_tests.floor.object_field import ObjectField
from sugar_lift_py_tests.floor.object_value import ObjectValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _tree(tmp_path, source):
    path = tmp_path / "object_method_attribute_mutation.py"
    path.write_text(source, encoding="utf-8")
    return SourceFile(workspace_path_source(str(path), root=str(tmp_path)))


def _sites(tmp_path):
    tree = _tree(
        tmp_path,
        "def mutate_method(method):\n"
        "    method.attr = 7\n"
        "    return method.attr\n"
        "def delete_method(method):\n"
        "    del method.attr\n",
    )
    functions = tuple(tree.functions())
    return functions[0].body[0].fragment, functions[0].body[1].fragment, functions[1].body[0].fragment


def _value(site):
    return ObjectMethodValue(
        "method",
        ("self",),
        TrueBoolLiteralSugar(site=site),
        "blake3-512:" + "5" * 128,
    )


@dataclass(frozen=True)
class _FloorSugar(ConstructedTermSugar):
    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)

    def to_term(self, *, owner):
        return self.value.to_term(owner=owner)


def test_store_read_overwrite_preserves_function_occurrence(tmp_path):
    store_site, read_site, _ = _sites(tmp_path)
    original = _value(store_site)

    first = original.setattr("attr", TermValue(7), store_site)
    assert isinstance(first, Complete)
    assert first.value.attribute("attr", read_site).value.value == 7
    second = first.value.setattr("attr", TermValue(9), store_site)

    assert second.value.attribute("attr", read_site).value.value == 9
    assert second.value.source_call_frame_cid == original.source_call_frame_cid
    assert second.value.to_term(owner="after") == original.to_term(owner="before")


def test_absent_dynamic_member_is_ground_attribute_error(tmp_path):
    _, read_site, _ = _sites(tmp_path)

    outcome = _value(read_site).attribute("value", read_site)

    assert outcome.value.effect.exception_name == "AttributeError"
    assert outcome.value.effect.producer_node_owner == "ObjectMethodValue.attribute"


def test_delete_stays_typed_loud_until_shadow_delete_publishes_state(tmp_path):
    store_site, _, delete_site = _sites(tmp_path)
    stored = _value(store_site).setattr("attr", TermValue(7), store_site).value

    with pytest.raises(ConstructionPanic) as raised:
        stored.delattr("attr", delete_site)

    assert raised.value.info.owner == "ObjectMethodValue.delattr"


def test_missing_source_frame_identity_stays_loud(tmp_path):
    store_site, read_site, _ = _sites(tmp_path)
    unauthenticated = ObjectMethodValue(
        "method", ("self",), TrueBoolLiteralSugar(site=store_site)
    )

    for operation in (
        lambda: unauthenticated.attribute("attr", read_site),
        lambda: unauthenticated.setattr("attr", TermValue(7), store_site),
    ):
        with pytest.raises(ConstructionPanic):
            operation()


def test_intrinsic_member_is_not_falsely_reported_absent(tmp_path):
    _, read_site, _ = _sites(tmp_path)

    with pytest.raises(ConstructionPanic) as raised:
        _value(read_site).attribute("__code__", read_site)

    assert raised.value.info.owner == "attribute"


def test_ordinary_object_value_field_is_unchanged(tmp_path):
    _, read_site, _ = _sites(tmp_path)
    ordinary = ObjectValue(
        "Thing", (ObjectField("value", TermValue(11)),), (), (), "thing-id"
    )

    assert ordinary.attribute("value", read_site).value.value == 11


def test_shadow_store_publishes_updated_method_receiver(tmp_path):
    tree = _tree(
        tmp_path,
        "def mutate_method(method):\n"
        "    method.attr = 7\n"
        "    return method.attr\n",
    )
    function = next(tree.functions())
    frame = function.source_visible_call_frame()
    site = function.fragment
    actual = _value(site)

    produced = CallSiteSugar(
        "mutate_method",
        (_FloorSugar(actual),),
        site,
        source_call_frame=frame,
    ).desugar(None)

    assert isinstance(produced, Complete)
    projected = produced.value.project_operation_receiver(None, owner="shadow-store")
    assert projected.value == 7

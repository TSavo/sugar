import pytest

from sugar_lift_py_tests.floor import ObjectMethodValue, TermValue
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "object_method_attribute_mutation.py"
    path.write_text(
        "def mutate_method(method):\n" "    method.attr = 7\n" "    del method.attr\n"
    )
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


def _value(site):
    return ObjectMethodValue("method", ("self",), TrueBoolLiteralSugar(site=site))


@pytest.mark.parametrize(
    ("operation", "owner", "site_index"),
    (
        ("setattr", "ObjectMethodValue.setattr", 0),
        ("delattr", "ObjectMethodValue.delattr", 1),
    ),
)
def test_object_method_attribute_mutations_have_exact_owner_occurrences(
    tmp_path, operation, owner, site_index
):
    sites = _sites(tmp_path)
    site = sites[site_index]
    value = _value(site)
    outcome = (
        value.setattr("attr", TermValue(7), site)
        if operation == "setattr"
        else value.delattr("attr", site)
    )
    assert outcome.value.effect.exception_name == "AttributeError"
    assert outcome.value.effect.producer_node_owner == owner
    assert outcome.value.effect.occurrence_id == str(site)


def test_object_method_attribute_mutations_reject_wrong_site(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    value = _value(store_site)
    store = value.setattr("attr", TermValue(7), store_site)
    delete = value.delattr("attr", delete_site)
    assert store.value.effect.occurrence_id != str(delete_site)
    assert delete.value.effect.occurrence_id != str(store_site)

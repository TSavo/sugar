import pytest

from sugar_lift_py_tests.floor import BlockValue, BuiltinExceptionClassValue, TermValue
from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
    AuthenticatedExceptionTypeValue,
)
from sugar_lift_py_tests.ir import str_const
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "authenticated_exception_type_attribute_mutation.py"
    path.write_text(
        "def mutate_exception_type(exc_type):\n    exc_type.attr = 7\n    del exc_type.attr\n"
    )
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


def _value():
    carried = BuiltinExceptionClassValue("ValueError", (), BlockValue(()))
    return AuthenticatedExceptionTypeValue(carried, str_const("exception-type"))


@pytest.mark.parametrize(
    ("operation", "owner", "site_index"),
    (
        ("setattr", "BuiltinExceptionClassValue.setattr", 0),
        ("delattr", "BuiltinExceptionClassValue.delattr", 1),
    ),
)
def test_authenticated_exception_type_attribute_mutations_dispatch_to_exact_carried_owner(
    tmp_path, operation, owner, site_index
):
    sites = _sites(tmp_path)
    site = sites[site_index]
    value = _value()
    outcome = (
        value.setattr("attr", TermValue(7), site)
        if operation == "setattr"
        else value.delattr("attr", site)
    )
    assert outcome.value.effect.exception_name == "TypeError"
    assert outcome.value.effect.producer_node_owner == owner
    assert outcome.value.effect.occurrence_id == str(site)


def test_authenticated_exception_type_attribute_mutations_reject_wrong_site(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    value = _value()
    store = value.setattr("attr", TermValue(7), store_site)
    delete = value.delattr("attr", delete_site)
    assert store.value.effect.occurrence_id != str(delete_site)
    assert delete.value.effect.occurrence_id != str(store_site)

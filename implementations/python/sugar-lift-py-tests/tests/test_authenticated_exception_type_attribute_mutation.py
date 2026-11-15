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


def _raised(outcome):
    """The effect of the one halt the mutation is.

    A raise is a halt of the ``ExitSet``, never a completed value: the set is
    that one halted arm and nothing else.
    """
    (halt,) = outcome.exits
    assert outcome.halts() == (halt,)
    return halt.effect


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
        value.setattr("attr", TermValue(7), site, None)
        if operation == "setattr"
        else value.delattr("attr", site, None)
    )
    effect = _raised(outcome)
    assert effect.exception_name == "TypeError"
    assert effect.producer_node_owner == owner
    assert effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


def test_authenticated_exception_type_attribute_mutations_reject_wrong_site(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    value = _value()
    store = value.setattr("attr", TermValue(7), store_site, None)
    delete = value.delattr("attr", delete_site, None)
    assert _raised(store).occurrence_id != f"{delete_site.filename}:{delete_site.line}:{delete_site.col}"
    assert _raised(delete).occurrence_id != f"{store_site.filename}:{store_site.line}:{store_site.col}"

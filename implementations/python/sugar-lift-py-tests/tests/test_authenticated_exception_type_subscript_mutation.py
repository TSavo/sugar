import pytest

from sugar_lift_py_tests.floor import ExceptionClassValue, TermValue
from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
    AuthenticatedExceptionTypeValue,
)
from sugar_lift_py_tests.ir import str_const
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "authenticated_exception_type_subscript_mutation.py"
    path.write_text(
        "def mutate_exception_type(exc_type):\n"
        "    exc_type[0] = 7\n"
        "    del exc_type[0]\n"
    )
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


def _value():
    carried = ExceptionClassValue("module.CustomError")
    return AuthenticatedExceptionTypeValue(carried, str_const("exception-type"))


def _only_halt(outcome):
    """The outcome is one unconditional halt and nothing else: its effect."""
    assert outcome.halts() == outcome.exits
    (halt,) = outcome.exits
    return halt.effect


@pytest.mark.parametrize(
    ("operation", "owner", "site_index"),
    (
        ("setitem", "ExceptionClassValue.setitem", 0),
        ("delitem", "ExceptionClassValue.delitem", 1),
    ),
)
def test_authenticated_exception_type_subscript_mutations_dispatch_to_exact_carried_owner(
    tmp_path, operation, owner, site_index
):
    sites = _sites(tmp_path)
    site = sites[site_index]
    value = _value()
    outcome = (
        value.setitem(TermValue(0), TermValue(7), site, None)
        if operation == "setitem"
        else value.delitem(TermValue(0), site, None)
    )
    effect = _only_halt(outcome)
    assert effect.exception_name == "TypeError"
    assert effect.producer_node_owner == owner
    assert effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


def test_authenticated_exception_type_subscript_mutations_reject_wrong_site(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    value = _value()
    store = value.setitem(TermValue(0), TermValue(7), store_site, None)
    delete = value.delitem(TermValue(0), delete_site, None)
    assert _only_halt(store).occurrence_id != f"{delete_site.filename}:{delete_site.line}:{delete_site.col}"
    assert _only_halt(delete).occurrence_id != f"{store_site.filename}:{store_site.line}:{store_site.col}"

import pytest

from sugar_lift_py_tests.floor import ExceptionClassValue, TermValue
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "exception_class_subscript_mutation.py"
    path.write_text(
        "def f(exc_type, replacement):\n    exc_type[0] = replacement\n    del exc_type[0]\n"
    )
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


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
        ("setitem", "ExceptionClassValue.setitem", 0),
        ("delitem", "ExceptionClassValue.delitem", 1),
    ),
)
def test_exception_class_subscript_mutations_have_exact_owner_occurrences(
    tmp_path, operation, owner, site_index
):
    sites = _sites(tmp_path)
    site = sites[site_index]
    value = ExceptionClassValue("module.CustomError")
    outcome = (
        value.setitem(TermValue(0), TermValue(7), site, None)
        if operation == "setitem"
        else value.delitem(TermValue(0), site, None)
    )
    effect = _raised(outcome)
    assert effect.exception_name == "TypeError"
    assert effect.producer_node_owner == owner
    assert effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


def test_exception_class_subscript_mutations_reject_wrong_site(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    value = ExceptionClassValue("module.CustomError")
    store = value.setitem(TermValue(0), TermValue(7), store_site, None)
    delete = value.delitem(TermValue(0), delete_site, None)
    assert _raised(store).occurrence_id != f"{delete_site.filename}:{delete_site.line}:{delete_site.col}"
    assert _raised(delete).occurrence_id != f"{store_site.filename}:{store_site.line}:{store_site.col}"

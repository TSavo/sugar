import pytest

from sugar_lift_py_tests.floor import SetLiteralValue, TermValue
from sugar_lift_py_tests.ir import num
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "set_literal_subscript_mutation.py"
    path.write_text(
        "def f(target, replacement):\n    target[0] = replacement\n    del target[0]\n"
    )
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


def _the_raise(outcome):
    """The store raises and nothing else: one halt, no completion."""
    (halt,) = outcome.exits
    assert outcome.halts() == (halt,)
    return halt.effect


@pytest.mark.parametrize(
    ("operation", "owner", "site_index"),
    (
        ("setitem", "SetLiteralValue.setitem", 0),
        ("delitem", "SetLiteralValue.delitem", 1),
    ),
)
def test_set_literal_subscript_mutations_have_exact_owner_occurrences(
    tmp_path, operation, owner, site_index
):
    sites = _sites(tmp_path)
    site = sites[site_index]
    value = SetLiteralValue((num(1),))
    outcome = (
        value.setitem(TermValue(0), TermValue(7), site, None)
        if operation == "setitem"
        else value.delitem(TermValue(0), site, None)
    )
    effect = _the_raise(outcome)
    assert effect.exception_name == "TypeError"
    assert effect.producer_node_owner == owner
    assert effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


def test_set_literal_subscript_mutations_reject_wrong_site(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    value = SetLiteralValue((num(1),))
    store = _the_raise(value.setitem(TermValue(0), TermValue(7), store_site, None))
    delete = _the_raise(value.delitem(TermValue(0), delete_site, None))
    assert store.occurrence_id != f"{delete_site.filename}:{delete_site.line}:{delete_site.col}"
    assert delete.occurrence_id != f"{store_site.filename}:{store_site.line}:{store_site.col}"

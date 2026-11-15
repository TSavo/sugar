import pytest

from sugar_lift_py_tests.floor import TermValue, TupleLiteralValue
from sugar_lift_py_tests.outcome import ExitSet, Halted
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _effect(outcome):
    """The mutation is one halt and nothing else: no arm completes."""
    assert isinstance(outcome, ExitSet)
    (halt,) = outcome.exits
    assert isinstance(halt, Halted)
    return halt.effect


def _sites(tmp_path):
    path = tmp_path / "tuple_literal_subscript_mutation.py"
    path.write_text(
        "def f(target, replacement):\n    target[0] = replacement\n    del target[0]\n"
    )
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


@pytest.mark.parametrize(
    ("operation", "owner", "site_index"),
    (
        ("setitem", "TupleLiteralValue.setitem", 0),
        ("delitem", "TupleLiteralValue.delitem", 1),
    ),
)
def test_tuple_literal_subscript_mutations_have_exact_owner_occurrences(
    tmp_path, operation, owner, site_index
):
    sites = _sites(tmp_path)
    site = sites[site_index]
    value = TupleLiteralValue((TermValue(1),))
    outcome = (
        value.setitem(TermValue(0), TermValue(7), site, None)
        if operation == "setitem"
        else value.delitem(TermValue(0), site, None)
    )
    effect = _effect(outcome)
    assert effect.exception_name == "TypeError"
    assert effect.producer_node_owner == owner
    assert effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


def test_tuple_literal_subscript_mutations_reject_wrong_site(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    value = TupleLiteralValue((TermValue(1),))
    store = value.setitem(TermValue(0), TermValue(7), store_site, None)
    delete = value.delitem(TermValue(0), delete_site, None)
    assert _effect(store).occurrence_id != f"{delete_site.filename}:{delete_site.line}:{delete_site.col}"
    assert _effect(delete).occurrence_id != f"{store_site.filename}:{store_site.line}:{store_site.col}"

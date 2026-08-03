import pytest

from sugar_lift_py_tests.floor import TermValue, TupleLiteralValue
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "tuple_literal_attribute_mutation.py"
    path.write_text(
        "def f(target, replacement):\n    target.attr = replacement\n    del target.attr\n"
    )
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


@pytest.mark.parametrize(
    ("operation", "owner", "site_index"),
    (
        ("setattr", "TupleLiteralValue.setattr", 0),
        ("delattr", "TupleLiteralValue.delattr", 1),
    ),
)
def test_tuple_literal_attribute_mutations_have_exact_owner_occurrences(
    tmp_path, operation, owner, site_index
):
    sites = _sites(tmp_path)
    site = sites[site_index]
    value = TupleLiteralValue((TermValue(1),))
    outcome = (
        value.setattr("attr", TermValue(7), site)
        if operation == "setattr"
        else value.delattr("attr", site)
    )
    assert outcome.value.effect.exception_name == "AttributeError"
    assert outcome.value.effect.producer_node_owner == owner
    assert outcome.value.effect.occurrence_id == str(site)


def test_tuple_literal_attribute_mutations_reject_wrong_site(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    value = TupleLiteralValue((TermValue(1),))
    store = value.setattr("attr", TermValue(7), store_site)
    delete = value.delattr("attr", delete_site)
    assert store.value.effect.occurrence_id != str(delete_site)
    assert delete.value.effect.occurrence_id != str(store_site)

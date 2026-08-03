import pytest

from sugar_lift_py_tests.floor import NamedExpressionValue, NoneValue, TermValue
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "named_expression_subscript_mutation.py"
    path.write_text(
        "def mutate(value):\n"
        "    (bound := None)[0] = value\n"
        "    del (bound := None)[0]\n"
    )
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


def _value():
    return NamedExpressionValue("bound", NoneValue())


@pytest.mark.parametrize(
    ("operation", "owner", "site_index"),
    (("setitem", "NoneValue.setitem", 0), ("delitem", "NoneValue.delitem", 1)),
)
def test_named_expression_subscript_mutations_dispatch_to_exact_presented_owner(
    tmp_path, operation, owner, site_index
):
    sites = _sites(tmp_path)
    site = sites[site_index]
    value = _value()
    outcome = (
        value.setitem(TermValue(0), TermValue(7), site)
        if operation == "setitem"
        else value.delitem(TermValue(0), site)
    )
    assert outcome.value.effect.exception_name == "TypeError"
    assert outcome.value.effect.producer_node_owner == owner
    assert outcome.value.effect.occurrence_id == str(site)


def test_named_expression_subscript_mutations_reject_wrong_site(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    value = _value()
    store = value.setitem(TermValue(0), TermValue(7), store_site)
    delete = value.delitem(TermValue(0), delete_site)
    assert store.value.effect.occurrence_id != str(delete_site)
    assert delete.value.effect.occurrence_id != str(store_site)

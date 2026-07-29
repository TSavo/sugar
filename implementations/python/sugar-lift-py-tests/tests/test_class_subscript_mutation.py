import pytest

from sugar_lift_py_tests.floor import BlockValue, ClassValue, TermValue
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "class_subscript_mutation.py"
    path.write_text(
        "def mutate_class(C):\n"
        "    C[0] = 7\n"
        "    del C[0]\n"
    )
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


@pytest.mark.parametrize(
    ("operation", "owner", "site_index"),
    (
        ("setitem", "ClassValue.setitem", 0),
        ("delitem", "ClassValue.delitem", 1),
    ),
)
def test_class_subscript_mutations_have_exact_owner_occurrences(
    tmp_path, operation, owner, site_index
):
    sites = _sites(tmp_path)
    site = sites[site_index]
    value = ClassValue("C", (), BlockValue(()))
    outcome = (
        value.setitem(TermValue(0), TermValue(7), site)
        if operation == "setitem"
        else value.delitem(TermValue(0), site)
    )
    assert outcome.value.effect.exception_name == "TypeError"
    assert outcome.value.effect.producer_node_owner == owner
    assert outcome.value.effect.occurrence_id == str(site)


def test_class_subscript_mutations_reject_wrong_site(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    value = ClassValue("C", (), BlockValue(()))
    store = value.setitem(TermValue(0), TermValue(7), store_site)
    delete = value.delitem(TermValue(0), delete_site)
    assert store.value.effect.occurrence_id != str(delete_site)
    assert delete.value.effect.occurrence_id != str(store_site)

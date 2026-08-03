from sugar_lift_py_tests.floor import ListIteratorValue, TermValue
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _outcomes(tmp_path):
    path = tmp_path / "list_iterator_attribute_mutation.py"
    path.write_text("def f(obj, value):\n    obj.attr = value\n    del obj.attr\n")
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    store_site, delete_site = body[0].fragment, body[1].fragment
    value = ListIteratorValue((TermValue(1),))
    return (
        (
            value.setattr("attr", TermValue(7), store_site),
            "ListIteratorValue.setattr",
            store_site,
        ),
        (value.delattr("attr", delete_site), "ListIteratorValue.delattr", delete_site),
    )


def test_list_iterator_attribute_mutations_have_exact_owner_occurrences(tmp_path):
    for outcome, owner, site in _outcomes(tmp_path):
        assert outcome.value.effect.exception_name == "AttributeError"
        assert outcome.value.effect.producer_node_owner == owner
        assert outcome.value.effect.occurrence_id == str(site)


def test_list_iterator_attribute_mutations_reject_wrong_site(tmp_path):
    store, _, store_site = _outcomes(tmp_path)[0]
    delete, _, delete_site = _outcomes(tmp_path)[1]
    assert store.value.effect.occurrence_id != str(delete_site)
    assert delete.value.effect.occurrence_id != str(store_site)

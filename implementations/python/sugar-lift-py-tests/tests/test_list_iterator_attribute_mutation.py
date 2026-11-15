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
            value.setattr("attr", TermValue(7), store_site, None),
            "ListIteratorValue.setattr",
            store_site,
        ),
        (
            value.delattr("attr", delete_site, None),
            "ListIteratorValue.delattr",
            delete_site,
        ),
    )


def _raise(outcome):
    """The mutation's one exit is its raise: a halt, never a completion."""
    (halt,) = outcome.exits
    assert outcome.halts() == (halt,)
    return halt.effect


def test_list_iterator_attribute_mutations_have_exact_owner_occurrences(tmp_path):
    for outcome, owner, site in _outcomes(tmp_path):
        effect = _raise(outcome)
        assert effect.exception_name == "AttributeError"
        assert effect.producer_node_owner == owner
        assert effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


def test_list_iterator_attribute_mutations_reject_wrong_site(tmp_path):
    store, _, store_site = _outcomes(tmp_path)[0]
    delete, _, delete_site = _outcomes(tmp_path)[1]
    assert _raise(store).occurrence_id != f"{delete_site.filename}:{delete_site.line}:{delete_site.col}"
    assert _raise(delete).occurrence_id != f"{store_site.filename}:{store_site.line}:{store_site.col}"

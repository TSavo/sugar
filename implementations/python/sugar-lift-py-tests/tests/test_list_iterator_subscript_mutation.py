from sugar_lift_py_tests.floor import ListIteratorValue, TermValue
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "list_iterator_subscript_mutation.py"
    path.write_text("def f(obj, value):\n    obj[0] = value\n    del obj[0]\n")
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


def _outcomes(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    value = ListIteratorValue((TermValue(1),))
    return (
        (
            value.setitem(TermValue(0), TermValue(7), store_site, None),
            "ListIteratorValue.setitem",
            store_site,
        ),
        (
            value.delitem(TermValue(0), delete_site, None),
            "ListIteratorValue.delitem",
            delete_site,
        ),
    )


def test_list_iterator_mutations_have_exact_owner_occurrences(tmp_path):
    for outcome, owner, site in _outcomes(tmp_path):
        effect = _raised(outcome)
        assert effect.exception_name == "TypeError"
        assert effect.producer_node_owner == owner
        assert effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


def test_list_iterator_mutations_reject_wrong_site(tmp_path):
    store, _, store_site = _outcomes(tmp_path)[0]
    delete, _, delete_site = _outcomes(tmp_path)[1]
    assert _raised(store).occurrence_id != f"{delete_site.filename}:{delete_site.line}:{delete_site.col}"
    assert _raised(delete).occurrence_id != f"{store_site.filename}:{store_site.line}:{store_site.col}"

from sugar_lift_py_tests.floor import ComplexValue, TermValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "complex_subscript_mutation.py"
    path.write_text("def f(obj, value):\n    obj[0] = value\n    del obj[0]\n")
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


def _outcomes(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    receiver = ComplexValue(1.0, 2.0)
    return (
        (
            receiver.setitem(TermValue(0), TermValue(7), store_site),
            "ComplexValue.setitem",
            store_site,
        ),
        (
            receiver.delitem(TermValue(0), delete_site),
            "ComplexValue.delitem",
            delete_site,
        ),
    )


def test_complex_subscript_mutations_have_exact_owner_occurrences(tmp_path):
    for outcome, owner, site in _outcomes(tmp_path):
        effect = outcome.value.effect
        assert effect.exception_name == "TypeError"
        assert effect.producer_node_owner == owner
        assert effect.occurrence_id == str(site)


def test_complex_subscript_mutations_cannot_fabricate_completion(tmp_path):
    for outcome, _, _ in _outcomes(tmp_path):
        assert not (
            isinstance(outcome, Complete) and not hasattr(outcome.value, "effect")
        )

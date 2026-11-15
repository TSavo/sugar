import pytest

from sugar_lift_py_tests.floor import SetLiteralValue, TermValue
from sugar_lift_py_tests.ir import num
from sugar_lift_py_tests.outcome.exit_set import Halted
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "set_literal_attribute_mutation.py"
    path.write_text(
        "def f(target, replacement):\n    target.attr = replacement\n    del target.attr\n"
    )
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


def _raised(outcome):
    """The effect of the mutation's one exit: a halted arm, never a completion."""
    (exit_,) = outcome.exits
    assert isinstance(exit_, Halted)
    return exit_.effect


@pytest.mark.parametrize(
    ("operation", "owner", "site_index"),
    (
        ("setattr", "SetLiteralValue.setattr", 0),
        ("delattr", "SetLiteralValue.delattr", 1),
    ),
)
def test_set_literal_attribute_mutations_have_exact_owner_occurrences(
    tmp_path, operation, owner, site_index
):
    sites = _sites(tmp_path)
    site = sites[site_index]
    value = SetLiteralValue((num(1),))
    outcome = (
        value.setattr("attr", TermValue(7), site, None)
        if operation == "setattr"
        else value.delattr("attr", site, None)
    )
    effect = _raised(outcome)
    assert effect.exception_name == "AttributeError"
    assert effect.producer_node_owner == owner
    assert effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


def test_set_literal_attribute_mutations_reject_wrong_site(tmp_path):
    store_site, delete_site = _sites(tmp_path)
    value = SetLiteralValue((num(1),))
    store = _raised(value.setattr("attr", TermValue(7), store_site, None))
    delete = _raised(value.delattr("attr", delete_site, None))
    assert store.occurrence_id != f"{delete_site.filename}:{delete_site.line}:{delete_site.col}"
    assert delete.occurrence_id != f"{store_site.filename}:{store_site.line}:{store_site.col}"

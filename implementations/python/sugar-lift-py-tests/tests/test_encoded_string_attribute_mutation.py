import pytest

from sugar_lift_py_tests.floor import EncodedStringValue, TermValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path, monkeypatch):
    path = tmp_path / "encoded_string_attribute_mutation.py"
    path.write_text("def f(value, replacement):\n    value.attr = replacement\n    del value.attr\n")
    monkeypatch.chdir(tmp_path)
    body = next(SourceFile.from_path(path.name).functions()).body
    return body[0].fragment, body[1].fragment


@pytest.mark.parametrize(
    ("operation", "owner", "site_index"),
    (
        ("setattr", "EncodedStringValue.setattr", 0),
        ("delattr", "EncodedStringValue.delattr", 1),
    ),
)
def test_encoded_string_attribute_mutations_have_exact_owner_occurrences(
    tmp_path, monkeypatch, operation, owner, site_index
):
    sites = _sites(tmp_path, monkeypatch)
    site = sites[site_index]
    value = EncodedStringValue((), ())
    outcome = (
        value.setattr("attr", TermValue(7), site)
        if operation == "setattr"
        else value.delattr("attr", site)
    )
    assert outcome.value.effect.exception_name == "AttributeError"
    assert outcome.value.effect.producer_node_owner == owner
    assert outcome.value.effect.occurrence_id == str(site)
    identity = lambda name: ctor(
        "python:exception_type_identity", [str_const("builtins"), str_const(name)]
    )
    assert outcome.value.effect.exception_type_coordinate == identity("AttributeError")
    assert outcome.value.effect.exception_type_mro == tuple(
        identity(name) for name in ("AttributeError", "Exception", "BaseException")
    )


def test_encoded_string_attribute_mutations_reject_wrong_site(tmp_path, monkeypatch):
    store_site, delete_site = _sites(tmp_path, monkeypatch)
    value = EncodedStringValue((), ())
    store = value.setattr("attr", TermValue(7), store_site)
    delete = value.delattr("attr", delete_site)
    assert store.value.effect.occurrence_id != str(delete_site)
    assert delete.value.effect.occurrence_id != str(store_site)

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import CallSiteValue, MutableGlobalValue, StringValue
from sugar_lift_py_tests.ir import _Ctor
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_source_tree.nodes import Name, Subscript
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path, source: str, filename: str):
    path = tmp_path / filename
    path.write_text(source)
    tree = SourceFile.from_path(filename)
    binding = next(
        node.fragment
        for node in tree.nodes()
        if isinstance(node, Name) and node.fragment.text == "OPTIONS"
    )
    lookup = next(node for node in tree.nodes() if isinstance(node, Subscript)).fragment
    return binding, lookup


def test_mutable_dict_global_lookup_preserves_complementary_value_and_keyerror_faces(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    binding, site = _sites(
        tmp_path,
        "OPTIONS = {}\nvalue = OPTIONS[key]\n", "mutable_global_truth.py"
    )
    value = MutableGlobalValue(
        "OPTIONS", "dict", binding.source_cid, binding.seal()
    )
    term = value.to_term(owner="test")

    exits = value.subscript(StringValue("display.max_rows"), site)

    assert isinstance(term, _Ctor)
    assert binding.source_cid in repr(term)
    assert binding.seal().cid in repr(term)
    assert len(exits.exits) == 2
    halted = next(exit for exit in exits.exits if isinstance(exit, Halted))
    completed = next(exit for exit in exits.exits if isinstance(exit, Completed))
    assert halted.effect.exception_name == "KeyError"
    assert halted.effect.occurrence_id == str(site)
    assert halted.effect.exception_type_coordinate is not None
    assert halted.effect.exception_type_mro is not None
    assert isinstance(completed.value, CallSiteValue)
    assert completed.value.target_name == "py.subscript"
    assert completed.value.site is site
    assert completed.guard.operands == (halted.guard,)
    assert halted.faces and completed.faces
    assert next(iter(halted.faces)).partition == next(iter(completed.faces)).partition


def test_mutable_dict_global_lookup_refuses_foreign_source_coordinate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    binding, truthful = _sites(
        tmp_path,
        "OPTIONS = {}\nvalue = OPTIONS[key]\n", "mutable_global_truth.py"
    )
    _foreign_binding, foreign = _sites(
        tmp_path,
        "OPTIONS = {}\nvalue = OPTIONS[other_key]\n", "mutable_global_foreign.py"
    )
    value = MutableGlobalValue(
        "OPTIONS", "dict", binding.source_cid, binding.seal()
    )

    assert truthful is not binding
    assert len(value.subscript(StringValue("display.max_rows"), truthful).exits) == 2

    with pytest.raises(SugarNotWritten) as raised:
        value.subscript(StringValue("display.max_rows"), foreign)

    assert raised.value.owner == "MutableGlobalValue.subscript"
    assert "foreign source" in raised.value.observed

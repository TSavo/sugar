from __future__ import annotations

from types import MappingProxyType

import pytest

from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests import lift_rpc
from sugar_source_tree.panic import SugarNotWritten

CATALOG_CID = "blake3-512:" + "3" * 128
TABLE_CID = "blake3-512:" + "6" * 128


def _call_use_rows(root):
    """Every enrolled file's imported call uses, by the one lexical import
    pass, against the identities of the modules the root lists."""
    from sugar_lift_py_tests.import_binding import (
        authenticated_import_uses,
        module_name_for_path,
    )
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.tree import SourceTree

    units = []
    for path in SourceTree(root).paths():
        source, _filename, source_cid = path_source(str(path))
        units.append((path, source, source_cid))
    identities = {
        module_name_for_path(root, path): {
            "kind": "authenticated-python-module",
            "schemaVersion": "1",
            "moduleName": module_name_for_path(root, path),
            "sourceCid": source_cid,
        }
        for path, _source, source_cid in units
    }
    rows = []
    for path, source, source_cid in units:
        enrolled, _outcomes = authenticated_import_uses(
            root, path, source, source_cid, identities
        )
        rows.extend(enrolled)
    return rows


def test_an_unresolved_reference_stays_loud():
    unresolved = CallSiteSugar(
        target_name="missing",
        args=(),
        site="consumer.py:2",
        contract_resolution_gap="unresolved-symbol",
    )
    with pytest.raises(SugarNotWritten, match="unresolved-symbol"):
        unresolved.desugar(None)


def test_off_population_call_desugars_to_a_callsite_not_a_gap():
    """stdlib ``re.compile(match)`` stays a coordinate, not a factory abort.

    Its body was never looked at, so the call is not bridged and is stated
    the one way, ``UnknownCalleeCallV1``: the coordinate completes only under
    ``python:unknown_callee_call.completes`` and the complement halts with an
    ``UndeterminedRaiseEffect``. A total completion would claim
    ``re.compile`` never raises.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor import CallSiteValue, StringValue
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
    from sugar_lift_py_tests.outcome.exit_set import complement_guard
    from sugar_lift_py_tests.sugar.string_literal_sugar import StringLiteralSugar
    from sugar_lift_py_tests.unanswered_calls import UnansweredCallV1, owed_calls

    sugar = CallSiteSugar(
        target_name="re.compile",
        args=(StringLiteralSugar("boom", site="raises.py:377"),),
        site=_CallFragment(),
        contract_resolution_gap="call-target-off-population:python:re.compile",
    )
    outcome = sugar.desugar(None)
    assert isinstance(outcome, ExitSet)
    (done,) = [face for face in outcome.exits if isinstance(face, Completed)]
    (halt,) = [face for face in outcome.exits if isinstance(face, Halted)]
    assert isinstance(done.value, CallSiteValue)
    assert done.value.arg_values == (StringValue("boom"),)
    assert done.guard.name == "python:unknown_callee_call.completes"
    assert halt.guard == complement_guard(done.guard)
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "UnknownCallee:re.compile"
    # Both arms owe the call at its own source coordinate.
    site = SourceFragmentCoordinateV1(_SOURCE_CID, 377, 4, 377, 20)
    assert owed_calls(outcome) == (UnansweredCallV1(None, site),)


_SOURCE_CID = "blake3-512:" + "7" * 128


class _CallFragment:
    """The call's fragment: its unit's source CID and its span, the two
    coordinates an unanswered call is owed at."""

    class _Span:
        start_line, start_col, end_line, end_col = 377, 4, 377, 20

    source_cid = _SOURCE_CID
    line_col_span = _Span()

    def __str__(self) -> str:
        return "raises.py:377"


def test_import_demand_enrollment_has_positional_arity_and_module_identity(tmp_path):
    (tmp_path / "producer.py").write_text("def pair(x):\n    return (x, x)\n")
    (tmp_path / "consumer.py").write_text(
        "from producer import pair\n" "value = pair(1)\n" "not_enrolled = pair(x=1)\n"
    )

    rows = _call_use_rows(tmp_path)

    assert len(rows) == 1
    assert rows[0]["targetSymbol"] == "python:producer.pair"
    assert rows[0]["importBindingCid"].startswith("blake3-512:")
    assert rows[0]["importSignature"] == {
        "formals": [],
        "sorts": [{"kind": "primitive", "name": "Value"}],
    }


def test_import_binding_authenticates_alias_and_module_identity(tmp_path):
    (tmp_path / "consumer.py").write_text(
        "from first import pair as renamed\n"
        "from second import pair as other\n"
        "a = renamed()\n"
        "b = other()\n"
        "def pair():\n    return (0, 0)\n"
        "c = pair()\n"
    )

    rows = _call_use_rows(tmp_path)

    assert [row["targetSymbol"] for row in rows] == [
        "python:first.pair",
        "python:second.pair",
    ]
    assert rows[0]["importBindingCid"] != rows[1]["importBindingCid"]


def test_import_binding_is_lexical_and_shadowing_never_inherits_import(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.import_binding import authenticated_import_uses

    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from producer import pair as renamed\n"
        "direct = renamed(0)\n"
        "def parameter(renamed):\n    return renamed(1)\n"
        "def assigned():\n    renamed(2)\n    renamed = local\n"
        "def nested():\n    def renamed(x): return x\n    return renamed(3)\n"
        "def branch(flag):\n"
        "    if flag:\n        from producer import pair as maybe\n"
        "    else:\n        maybe = local\n"
        "    return maybe(4)\n"
    )
    source, _filename, source_cid = path_source(str(consumer))
    rows, outcomes = authenticated_import_uses(tmp_path, consumer, source, source_cid)

    assert [row["targetSymbol"] for row in rows] == ["python:producer.pair"]
    assert "shadowed-non-import" in outcomes.values()
    assert "no-lexical-binding" in outcomes.values()
    assert "ambiguous-lexical-binding" in outcomes.values()


def test_global_and_method_lookup_never_inherit_enclosing_or_class_import(tmp_path):
    (tmp_path / "consumer.py").write_text(
        "from right import pair\n"
        "def outer():\n"
        "    from wrong import pair\n"
        "    def inner():\n"
        "        global pair\n"
        "        return pair(1)\n"
        "    return inner\n"
        "class C:\n"
        "    from wrong import pair\n"
        "    def method(self):\n"
        "        return pair(2)\n"
    )

    rows = _call_use_rows(tmp_path)

    assert [row["targetSymbol"] for row in rows] == [
        "python:right.pair",
        "python:right.pair",
    ]


def test_try_handler_sees_exceptional_prefix_rebind_and_never_authenticates_import(
    tmp_path,
):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.import_binding import authenticated_import_uses

    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from producer import pair\n"
        "try:\n"
        "    pair = local\n"
        "    raise E\n"
        "except E:\n"
        "    pair()\n"
    )
    source, _filename, source_cid = path_source(str(consumer))

    rows, outcomes = authenticated_import_uses(tmp_path, consumer, source, source_cid)

    assert rows == []
    assert "ambiguous-lexical-binding" in outcomes.values()


def test_loop_backedge_rebind_never_authenticates_import_use(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.import_binding import authenticated_import_uses

    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from producer import pair\n"
        "while cond:\n"
        "    pair()\n"
        "    pair = local\n"
    )
    source, _filename, source_cid = path_source(str(consumer))

    rows, outcomes = authenticated_import_uses(tmp_path, consumer, source, source_cid)

    assert rows == []
    assert "ambiguous-lexical-binding" in outcomes.values()


def test_spelling_without_authenticated_import_use_has_no_authority(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.import_binding import authenticated_import_uses

    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "def use(pair, pandas_magic):\n" "    pair(1)\n" "    pandas_magic(2)\n"
    )
    source, _filename, source_cid = path_source(str(consumer))
    rows, outcomes = authenticated_import_uses(tmp_path, consumer, source, source_cid)

    assert rows == []
    assert set(outcomes.values()) == {"shadowed-non-import"}


def test_relative_import_is_package_qualified_and_binding_coordinate_is_typed(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.import_binding import authenticated_import_uses

    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("")
    consumer = package / "consumer.py"
    consumer.write_text("from .producer import pair as renamed\nrenamed(1)\n")
    source, _filename, source_cid = path_source(str(consumer))
    rows, _ = authenticated_import_uses(tmp_path, consumer, source, source_cid)

    assert rows[0]["targetSymbol"] == "python:pkg.producer.pair"
    use = rows[0]["authenticatedImportUse"]
    assert use["kind"] == "authenticated-import-use"
    assert use["importBindingCid"] == rows[0]["importBindingCid"]
    assert use["cid"].startswith("blake3-512:")


def test_an_imported_call_takes_its_symbol_from_the_one_import_table(tmp_path):
    """Inventory item 26: there is one way to bind a call. The call carries
    the target symbol the one import table (#7837) holds at its callee's own
    coordinate, with nothing bound into the kit before construction; prove's
    join binds it to the imported proof (step 9). The symbol is what this
    source imported as written, so a keyword call (which makes no
    call-contract demand) carries it too. A local call carries none.
    """
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree.nodes import Call
    from sugar_source_tree.tree import SourceFile

    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "from producer import pair\n"
        "import producer as p\n"
        "value = pair(v)\n"
        "keyword = pair(x=v)\n"
        "dotted = p.pair(v)\n"
        "local(v)\n"
    )
    tree = SourceFile(
        path_source(str(consumer)),
        construction_context=TreeConstructionContextV1(workspace_root=str(tmp_path)),
    )
    calls = sorted(
        (node for node in tree.nodes() if isinstance(node, Call)),
        key=lambda node: node.line_col_span().start_line,
    )
    symbols = [call.sugar().import_target_symbol for call in calls]

    assert symbols == [
        "python:producer.pair",
        "python:producer.pair",
        "python:producer.pair",
        None,
    ]
    assert all(call.sugar().contract_resolution_gap is None for call in calls)


def test_producer_contract_exports_the_same_module_qualified_symbol(tmp_path):
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_py_tests.tree_enumerate import function_contract_rows

    producer = tmp_path / "producer.py"
    producer.write_text("def pair():\n    return (1, 2)\n")
    # The producer's symbol is read off its workspace-relative locus, so it
    # opens through the one construction door, never by absolute path.
    tree = open_source_file_for_construction(producer, root=tmp_path)
    function = next(tree.functions())

    _, rows = function_contract_rows(function, "producer.py")

    assert rows is not None
    assert rows[0].bridge_source_symbol == "python:producer.pair"
    # The contract is named by the same symbol: one string, not two.
    assert rows[0].name == "python:producer.pair"


def test_every_definition_publishes_its_one_join_symbol(tmp_path):
    """Every ``def`` states one join symbol, its contract's name too (#7757):
    a module ``def`` the symbol an import of it spells, a method the class
    that defines it, a local ``def`` its function's ``<locals>`` and its own
    coordinate. Two definitions of one bare name in one file never share it."""
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    producer = tmp_path / "producer.py"
    producer.write_text(
        "def pair():\n    return 1\n"
        "class C:\n    def pair(self):\n        return 2\n"
        "def outer():\n    def pair():\n        return 3\n    return pair()\n"
    )
    tree = open_source_file_for_construction(producer, root=tmp_path)
    functions = list(tree.functions())
    universes = [function.sugar() for function in functions]

    assert [universe.bridge_source_symbol for universe in universes] == [
        "python:producer.pair",
        "python:producer.C.pair",
        "python:producer.outer",
        "python:producer.outer.<locals>.pair@7:4",
    ]
    assert [universe.name for universe in universes] == [
        universe.bridge_source_symbol for universe in universes
    ]


def test_a_class_states_its_join_symbol(tmp_path):
    """A class's symbol is the one an import of it spells, read by the speller
    every definition's join reads (``SourceUnit.definition_symbol``)."""
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_source_tree.nodes import ClassDef

    producer = tmp_path / "producer.py"
    producer.write_text(
        "class Box:\n    def __init__(self, n):\n        self.n = n\n"
        "def make():\n    class Local:\n        pass\n    return Local\n"
    )
    tree = open_source_file_for_construction(producer, root=tmp_path)
    classes = [node for node in tree.root.walk() if isinstance(node, ClassDef)]

    assert [node.bridge_source_symbol() for node in classes] == [
        "python:producer.Box",
        "python:producer.make.<locals>.Local@5:4",
    ]

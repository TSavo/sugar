"""Import-bound dotted exception types construct without Attribute projection.

Mechanism: ``exception_type_identity`` joins the authenticated import
target with the static Attribute chain into one
``python:exception_type_identity(import, qualified)`` coordinate.  The CM
contract authenticates the operand's *role* as an exception type; this module
authenticates only the identity.  ``AuthenticatedExceptionTypeSugar`` projects
that coordinate as ``ExceptionClassValue`` and never re-asks the opaque module
receiver for a member (no spelling table, no ``py.getattr`` invent).

Pinned pandas residual (Owner 3 — external exception coordinates):

- four ``pa.ArrowInvalid`` With heads
- one ``pyarrow.ArrowException`` With head

Each site either routes with a matching authenticated type operand, or keeps a
later residual that is *not* ``SymbolicValue.attribute`` on the exception name.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    CallParameterV1,
    EffectBoundarySemanticsV1,
    ExceptionInfoBindingV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    KeywordOnlyV1,
    LiteralDefaultV1,
    NoDefaultV1,
    OptionalFormalArgumentProjectionV1,
    PositionalOrKeywordV1,
    RaiseEffectKindV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerContractRefV1,
    ImportSignatureV2,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
    _hash_json,
)
from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
    AuthenticatedExceptionTypeValue,
)
from sugar_lift_py_tests.floor.exception_class_value import ExceptionClassValue
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, str_const
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile

SIGNATURE = ImportSignatureV2(
    (
        CallParameterV1(
            "expected",
            PrimitiveSort("Value"),
            PositionalOrKeywordV1(),
            True,
            NoDefaultV1(),
        ),
        CallParameterV1(
            "match",
            PrimitiveSort("String"),
            KeywordOnlyV1(),
            False,
            LiteralDefaultV1({"kind": "ctor", "name": "None", "args": []}),
        ),
    )
)


def _cid(char: str) -> str:
    return "blake3-512:" + char * 128


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _raise_semantics():
    return EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(0),
        OptionalFormalArgumentProjectionV1(1),
        ExceptionInfoBindingV1(),
    )


def _ref(use_site, salt: str) -> ContextManagerContractRefV1:
    return ContextManagerContractRefV1(
        resolution_cid=_cid(salt),
        demand_cid=_cid("d"),
        use_site=use_site,
        use_site_cid=_hash_json(use_site.wire()),
        authenticated_import_use_cid=_cid("u"),
        import_binding_cid=_cid("i"),
        construction_context_generation_cid=_cid("g"),
        contract_cid=_cid("m"),
        payload_cid=_cid("p"),
        provenance_cid=_cid("v"),
        distribution_artifact_cid=_cid("a"),
        dependency_artifact_graph_cid=_cid("b"),
        module_source_cid=_cid("s"),
        resolved_definition_cid=_cid("f"),
        manager_construction_cid=_cid("n"),
        enter_testimony_cid=_cid("1"),
        exit_testimony_cid=_cid("2"),
        import_signature=SIGNATURE,
        semantics=_raise_semantics(),
    )


def _boundary(tmp_path: Path, source: str) -> WithEffectBoundarySugar:
    path = tmp_path / "site.py"
    path.write_text(source, encoding="utf-8")
    identity = path_source(str(path))
    probe = SourceFile(identity)
    with_node = next(node for node in probe.nodes() if node.kind == "With")
    coordinate = _coordinate(with_node.items[0].context_expr)
    context = TreeConstructionContextV1(
        ResolvedContractRefsV1(
            _cid("c"), _cid("t"), MappingProxyType({coordinate: _ref(coordinate, "r")})
        )
    )
    function = next(SourceFile(identity, construction_context=context).functions())
    sugar = function.sugar()
    boundaries: list[WithEffectBoundarySugar] = []

    def walk(node) -> None:
        if isinstance(node, WithEffectBoundarySugar):
            boundaries.append(node)
        for field in ("body", "statements", "entries", "then_body", "else_body"):
            for child in getattr(node, field, ()) or ():
                walk(child)
        manager = getattr(node, "manager", None)
        if manager is not None:
            walk(manager)

    walk(sugar)
    assert len(boundaries) == 1
    return boundaries[0]


def _attribute(tree: SourceFile, attr: str):
    return next(
        node for node in tree.nodes() if node.kind == "Attribute" and node.attr == attr
    )


def test_import_alias_arrow_invalid_identity_is_import_coordinate(tmp_path):
    """Truthful: ``import pyarrow as pa`` + ``pa.ArrowInvalid`` is one import identity."""
    path = tmp_path / "alias.py"
    path.write_text(
        "import pyarrow as pa\n"
        "def f():\n"
        "    with expect(pa.ArrowInvalid):\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))
    identity = tree.unit.exception_type_identity(
        _attribute(tree, "ArrowInvalid")
    )
    assert identity == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("pyarrow.ArrowInvalid")],
    )


def test_module_name_arrow_exception_identity_is_import_coordinate(tmp_path):
    """Truthful: bare ``import pyarrow`` + ``pyarrow.ArrowException`` is closed."""
    path = tmp_path / "mod.py"
    path.write_text(
        "import pyarrow\n"
        "def f():\n"
        "    with expect(pyarrow.ArrowException):\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))
    identity = tree.unit.exception_type_identity(
        _attribute(tree, "ArrowException")
    )
    assert identity == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("pyarrow.ArrowException")],
    )


def test_import_bound_exception_desugars_to_authenticated_type(tmp_path):
    """Truthful twin: manager arg is AuthenticatedExceptionTypeValue, not Attribute."""
    boundary = _boundary(
        tmp_path,
        "import pyarrow as pa\n"
        "def f():\n"
        "    with expect(pa.ArrowInvalid):\n"
        "        raise ValueError('x')\n",
    )
    call = boundary.manager.desugar().completed_value()
    expected = call.arg_values[0]
    assert isinstance(expected, AuthenticatedExceptionTypeValue)
    assert expected.exception_type_identity() == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("pyarrow.ArrowInvalid")],
    )
    assert isinstance(expected.value, ExceptionClassValue)
    assert expected.value.qualified_name == "pyarrow.ArrowInvalid"


def test_arrow_exception_module_attr_desugars_to_authenticated_type(tmp_path):
    """Truthful twin for the parquet residual spelling ``pyarrow.ArrowException``."""
    boundary = _boundary(
        tmp_path,
        "import pyarrow\n"
        "def f():\n"
        "    with expect(pyarrow.ArrowException):\n"
        "        raise ValueError('x')\n",
    )
    expected = boundary.manager.desugar().completed_value().arg_values[0]
    assert isinstance(expected, AuthenticatedExceptionTypeValue)
    assert expected.exception_type_identity() == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("pyarrow.ArrowException")],
    )
    assert isinstance(expected.value, ExceptionClassValue)
    assert expected.value.qualified_name == "pyarrow.ArrowException"


def test_nested_lib_export_uses_full_import_chain(tmp_path):
    """Mechanism: every static Attribute link joins the import coordinate."""
    path = tmp_path / "nested.py"
    path.write_text(
        "import pyarrow as pa\n"
        "def f():\n"
        "    with expect(pa.lib.ArrowInvalid):\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))
    identity = tree.unit.exception_type_identity(
        _attribute(tree, "ArrowInvalid")
    )
    assert identity == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("pyarrow.lib.ArrowInvalid")],
    )


def test_reassigned_import_head_has_no_exception_identity(tmp_path):
    """Lying twin: an intervening assignment defeats the import coordinate."""
    path = tmp_path / "shadowed.py"
    path.write_text(
        "import pyarrow as pa\n"
        "def f(replacement):\n"
        "    pa = replacement\n"
        "    with expect(pa.ArrowInvalid):\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))
    assert (
        tree.unit.exception_type_identity(_attribute(tree, "ArrowInvalid"))
        is None
    )


def test_no_pyarrow_spelling_arm_in_authenticator():
    """Guard: the desugar path never branches on vendor exception spellings."""
    from pathlib import Path

    sugar_path = (
        Path(__file__).resolve().parents[2]
        / "sugar-lift-py-tests"
        / "src"
        / "sugar_lift_py_tests"
        / "sugar"
        / "authenticated_exception_type_sugar.py"
    )
    text = sugar_path.read_text(encoding="utf-8")
    for forbidden in (
        "ArrowInvalid",
        "ArrowException",
        "pyarrow",
        "ArrowNotImplemented",
    ):
        assert forbidden not in text, forbidden


def test_importorskip_binding_authenticates_arrow_invalid(tmp_path):
    """Truthful: the manager operand role authenticates the import coordinate."""
    path = tmp_path / "skip.py"
    path.write_text(
        "import pytest\n"
        'pa = pytest.importorskip("pyarrow")\n'
        "def f():\n"
        "    with expect(pa.ArrowInvalid):\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))
    identity = tree.unit.exception_type_identity(
        _attribute(tree, "ArrowInvalid")
    )
    assert identity == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("pyarrow.ArrowInvalid")],
    )
    boundary = _boundary(tmp_path, path.read_text(encoding="utf-8"))
    expected = boundary.manager.desugar().completed_value().arg_values[0]
    assert isinstance(expected, AuthenticatedExceptionTypeValue)
    assert expected.exception_type_identity() == identity


def test_import_bound_attribute_body_does_not_invent_member_success(tmp_path):
    """Lying twin: an import coordinate alone is not member-existence testimony."""
    from sugar_source_tree.panic import SugarNotWritten

    path = tmp_path / "body.py"
    path.write_text(
        "import pandas as pd\n" "def f():\n" "    return pd.util.foo\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))

    with pytest.raises(SugarNotWritten, match="attribute"):
        _attribute(tree, "foo").sugar().desugar()


def test_try_import_optional_binding_authenticates_module_attr(tmp_path):
    """Truthful: try/import with unbound except path keeps the ImportDef alone."""
    path = tmp_path / "tryimp.py"
    path.write_text(
        "try:\n"
        "    import pyarrow\n"
        "except ImportError:\n"
        "    pass\n"
        "def f():\n"
        "    with expect(pyarrow.ArrowException):\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))
    identity = tree.unit.exception_type_identity(
        _attribute(tree, "ArrowException")
    )
    assert identity == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("pyarrow.ArrowException")],
    )


def test_try_import_with_except_rebind_stays_loud(tmp_path):
    """Lying: except rebinding the name defeats unique import identity."""
    path = tmp_path / "try_rebind.py"
    path.write_text(
        "try:\n"
        "    import pyarrow\n"
        "except ImportError:\n"
        "    pyarrow = None\n"
        "def f():\n"
        "    with expect(pyarrow.ArrowException):\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))
    assert (
        tree.unit.exception_type_identity(_attribute(tree, "ArrowException"))
        is None
    )


# ── One lookup for every exception class a reader names (#7757) ──
#
# ``raise``, ``except``, ``except*``, an expected-exception operand and a
# warning category all identify the class through
# ``SourceUnit.exception_type_identity``: a local class, a builtin exception
# class, or an imported symbol by its target symbol. A star import the lifter
# cannot read is the one undecided citation.


def _tree(tmp_path: Path, name: str, source: str) -> SourceFile:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return SourceFile(path_source(str(path)))


def _name(tree: SourceFile, identifier: str, line: int):
    return next(
        node
        for node in tree.nodes()
        if node.kind == "Name"
        and node.id == identifier
        and node.line_col_span().start_line == line
    )


def _import_identity(qualified: str):
    return ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const(qualified)],
    )


def _builtin_identity(name: str):
    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def test_from_imported_expected_exception_is_its_target_symbol(tmp_path):
    """``with pytest.raises(ImportedError)`` under ``from m import
    ImportedError``: the operand is identified by its target symbol, never
    refused for having no local class."""
    source = (
        "from pyarrow import ArrowInvalid\n"
        "def f():\n"
        "    with expect(ArrowInvalid):\n"
        "        raise ValueError('x')\n"
    )
    tree = _tree(tmp_path, "from_imported.py", source)
    operand = _name(tree, "ArrowInvalid", 3)
    assert tree.unit.exception_type_identity(operand) == _import_identity(
        "pyarrow.ArrowInvalid"
    )
    # Its ancestry is the defining proof's to state (step 9).
    assert tree.unit.exception_type_mro(operand) is None
    class_value = tree.unit.exception_class_value(operand)
    assert class_value == ExceptionClassValue("pyarrow.ArrowInvalid")

    boundary = _boundary(tmp_path, source)
    expected = boundary.manager.desugar().completed_value().arg_values[0]
    assert isinstance(expected, AuthenticatedExceptionTypeValue)
    assert expected.exception_type_identity() == _import_identity(
        "pyarrow.ArrowInvalid"
    )
    assert expected.value == ExceptionClassValue("pyarrow.ArrowInvalid")


def test_module_attribute_raise_and_from_imported_raise_meet_one_door(tmp_path):
    """``import m; raise m.E`` and ``from m import E; raise E``: the same
    lookup, the same target symbol."""
    tree = _tree(
        tmp_path,
        "raises.py",
        "import pyarrow\n"
        "from pyarrow import ArrowInvalid\n"
        "def f():\n"
        "    raise pyarrow.ArrowInvalid('x')\n"
        "def g():\n"
        "    raise ArrowInvalid('x')\n",
    )
    dotted = _attribute(tree, "ArrowInvalid")
    bare = _name(tree, "ArrowInvalid", 6)
    assert tree.unit.exception_type_identity(dotted) == _import_identity(
        "pyarrow.ArrowInvalid"
    )
    assert tree.unit.exception_type_identity(bare) == tree.unit.exception_type_identity(
        dotted
    )
    assert tree.unit.exception_class_value(bare) == tree.unit.exception_class_value(
        dotted
    )


def test_except_of_a_from_imported_class_constructs(tmp_path):
    """``except ImportedError`` authenticates through the one lookup instead of
    refusing for lacking an identity."""
    path = tmp_path / "handler.py"
    path.write_text(
        "from pyarrow import ArrowInvalid\n"
        "def f(g):\n"
        "    try:\n"
        "        return g()\n"
        "    except ArrowInvalid:\n"
        "        return None\n",
        encoding="utf-8",
    )
    next(SourceFile(path_source(str(path))).functions()).sugar()


def test_try_gated_from_builtins_import_is_the_builtin(tmp_path):
    """``try: from builtins import ValueError / except ImportError``: the name
    is read only where it is bound, so it is the builtin class."""
    tree = _tree(
        tmp_path,
        "gated.py",
        "try:\n"
        "    from builtins import ValueError\n"
        "except ImportError:\n"
        "    pass\n"
        "def f():\n"
        "    raise ValueError('x')\n",
    )
    operand = _name(tree, "ValueError", 6)
    assert tree.unit.exception_type_identity(operand) == _builtin_identity(
        "ValueError"
    )
    assert tree.unit.exception_type_mro(operand) is not None


# ── The undecided citation (#7757, follow-up to #8086) ──
#
# A name only a star import the lifter cannot read may bind is never refused
# and never answered: its identity is ``UndecidedExceptionClassV1``. Its read
# owes the ``undecided`` member (reason ``unanswered``, no symbol), a match
# against it is retained, and a call of it (or of a class with it as a base)
# is the one unanswered call. ``unreadable_star_m`` exists nowhere.

_STAR = "from unreadable_star_m import *\n"


def _function(tmp_path: Path, name: str, source: str):
    """The one function ``source`` defines, opened for construction."""
    from with_resolution_fixture import source_file_with_preconstruction

    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return next(source_file_with_preconstruction(path).functions())


def _owed_items(outcome):
    """Every unanswered item ``outcome`` owes: on its arms, and on the
    all-halting entries a completed arm's record carries."""
    from sugar_lift_py_tests.outcome import Completed, ExitSet
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    items = list(owed_calls(outcome))
    for face in outcome.exits:
        if not isinstance(face, Completed):
            continue
        record = getattr(face.value, "record", None)
        for entry in getattr(record, "statements", ()):
            if isinstance(entry, ExitSet):
                items.extend(owed_calls(entry))
    return items


def _halt_effects(outcome):
    """Every halt effect ``outcome`` leaves by: its halted arms, and the
    all-halting entries a completed arm's record carries."""
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    effects = []
    for face in outcome.exits:
        if isinstance(face, Halted):
            effects.append(face.effect)
        elif isinstance(face, Completed):
            record = getattr(face.value, "record", None)
            for entry in getattr(record, "statements", ()):
                if isinstance(entry, ExitSet):
                    effects.extend(halt.effect for halt in entry.halts())
    return effects


def _owed_at(items, line: int):
    return [
        item
        for item in items
        if item.symbol is None
        and item.site is not None
        and item.site.start_line == line
    ]


def test_star_imported_class_is_the_undecided_identity(tmp_path):
    """The one lookup answers the undecided citation, typed: no refusal, no
    class. Its coordinate is the read's own; it owes the member at the read;
    no ancestry and no class value are read through it, nor through a class
    whose base it is."""
    from sugar_source_tree.nodes import UndecidedExceptionClassV1

    tree = _tree(
        tmp_path,
        "star.py",
        _STAR
        + "class E(ArrowInvalid):\n"
        "    pass\n"
        "def f():\n"
        "    raise ArrowInvalid('x')\n"
        "def g():\n"
        "    raise E('y')\n",
    )
    operand = _name(tree, "ArrowInvalid", 5)
    identity = tree.unit.exception_type_identity(operand)
    assert isinstance(identity, UndecidedExceptionClassV1)
    assert identity.name == "ArrowInvalid"
    assert identity.coordinate() == ctor(
        "python:exception_type_identity",
        [str_const("undecided"), str_const(identity.read)],
    )
    # Two reads of the name never name one class.
    base = _name(tree, "ArrowInvalid", 2)
    assert tree.unit.exception_type_identity(base) != identity
    (item,) = identity.owed()
    assert item.symbol is None
    assert item.site.start_line == 5
    assert tree.unit.exception_type_mro(operand) is None
    assert tree.unit.exception_class_value(operand) is None

    # ``E`` is a source class; its only base is undecided, so its ancestry
    # and its class value are not read, and the module states nothing.
    local = _name(tree, "E", 7)
    assert tree.unit.exception_type_identity(local).args[0].value == "source-class"
    assert tree.unit.exception_type_mro(local) is None
    assert tree.unit.exception_class_value(local) is None
    assert tree.unit.exception_class_ancestry() == ()


def test_raise_of_a_star_imported_class_call_is_undetermined_and_owes(tmp_path):
    """``raise X('x')``: the call is the one unanswered class call, so the
    raise is of undetermined class and owes the member at the call."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    function = _function(
        tmp_path, "raise_star.py", _STAR + "def f():\n    raise ArrowInvalid('x')\n"
    )
    outcome = function.sugar().desugar()
    effects = _halt_effects(outcome)
    assert effects
    assert all(isinstance(effect, UndeterminedRaiseEffect) for effect in effects)
    assert _owed_at(_owed_items(outcome), 3)


def test_raise_of_a_class_with_an_undecided_base_is_the_unanswered_class_call(
    tmp_path,
):
    """``class E(X)`` with ``X`` undecided: ``raise E('y')`` constructs; the
    call of ``E`` is the one unanswered class call (``UnknownCalleeCallV1``)
    and owes the member."""
    function = _function(
        tmp_path,
        "base_star.py",
        _STAR + "class E(ArrowInvalid):\n    pass\ndef f():\n    raise E('y')\n",
    )
    outcome = function.sugar().desugar()
    assert any(
        getattr(effect, "producer_node_owner", None) == "UnknownCallee:E"
        for effect in _halt_effects(outcome)
    )
    assert _owed_at(_owed_items(outcome), 5)


def test_except_of_a_star_imported_class_is_retained_and_owes(tmp_path):
    """``except X``: the arm constructs; the match against the undecided
    class is retained over its coordinate, and every face that passed the
    arm owes the member at the arm's type."""
    function = _function(
        tmp_path,
        "except_star.py",
        _STAR
        + "def f(g):\n"
        "    try:\n"
        "        return g()\n"
        "    except ArrowInvalid:\n"
        "        return None\n",
    )
    outcome = function.sugar().desugar()
    rendered = repr(outcome)
    assert "adt.is_python_type" in rendered
    assert "value='undecided'" in rendered
    assert _owed_at(_owed_items(outcome), 5)


def test_expected_star_imported_class_is_retained_and_owes(tmp_path):
    """``with pytest.raises(X)``: the expected operand constructs with the
    undecided coordinate, owes the member, and a raise matched against it is
    retained, exactly as against an imported alias."""
    from sugar_lift_py_tests.authenticated_exception_matching import (
        MatchRetained,
        matches_raise_effect,
    )
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    boundary = _boundary(
        tmp_path,
        _STAR
        + "def f():\n"
        "    with expect(ArrowInvalid):\n"
        "        raise ValueError('x')\n",
    )
    outcome = boundary.manager.desugar()
    expected = outcome.completed_value().arg_values[0]
    assert isinstance(expected, AuthenticatedExceptionTypeValue)
    identity = expected.exception_type_identity()
    assert identity.args[0].value == "undecided"
    assert _owed_at(owed_calls(outcome), 3)
    probe = RaiseEffect.for_builtin("ValueError", occurrence="probe", blame="probe")
    assert isinstance(matches_raise_effect(probe, expected), MatchRetained)


def test_warning_category_star_imported_is_retained_and_owes(tmp_path):
    """A warning category a star import may bind: ``warnings.warn(m, X)``
    constructs; the category read owes the member, the observation carries
    the undecided coordinate, and matching it against a builtin category (or
    a builtin observation against it) is retained, never decided."""
    from sugar_lift_py_tests.authenticated_exception_matching import (
        MatchRetained,
        warning_effect_message_verdict,
    )
    from sugar_lift_py_tests.effect.warning_effect import WarningEffect
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.sugar.authenticated_exception_type_sugar import (
        AuthenticatedExceptionTypeSugar,
    )
    from sugar_lift_py_tests.sugar.warning_observation_producer import (
        warning_observation_from_operands,
    )
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    source = _STAR + "import warnings\ndef f():\n    warnings.warn('m', ArrowInvalid)\n"
    # The warning reader constructs instead of refusing.
    _function(tmp_path, "warn_star.py", source).sugar()

    tree = _tree(tmp_path, "warn_star.py", source)
    operand = _name(tree, "ArrowInvalid", 4)
    identity = tree.unit.exception_type_identity(operand)
    read = AuthenticatedExceptionTypeSugar(
        operand.sugar(), identity, site=operand.fragment
    ).desugar()
    assert _owed_at(owed_calls(read), 4)
    category = read.completed_value()
    observation = warning_observation_from_operands(
        (StringValue("m"), category), (), None
    )
    assert observation.effect.category_identity == identity.coordinate()

    user_warning = _builtin_identity("UserWarning")
    builtin = AuthenticatedExceptionTypeValue(
        SymbolicValue(user_warning), user_warning, None, None
    )
    assert isinstance(
        warning_effect_message_verdict(observation.effect, builtin, None),
        MatchRetained,
    )
    observed_builtin = WarningEffect(
        category_name="UserWarning",
        message=None,
        blame=None,
        category_identity=user_warning,
    )
    assert isinstance(
        warning_effect_message_verdict(observed_builtin, category, None),
        MatchRetained,
    )


def test_local_and_builtin_classes_keep_their_identities(tmp_path):
    """A local class is its ``source-class`` coordinate (with an imported base
    its class value carries the imported class); a builtin is the builtin."""
    from sugar_lift_py_tests.floor.local_exception_class_value import (
        LocalExceptionClassValue,
    )

    tree = _tree(
        tmp_path,
        "local.py",
        "from pyarrow import ArrowInvalid\n"
        "class E(ValueError):\n"
        "    pass\n"
        "class F(ArrowInvalid):\n"
        "    pass\n"
        "def f():\n"
        "    raise E('x')\n"
        "def g():\n"
        "    raise F('x')\n"
        "def h():\n"
        "    raise KeyError('x')\n",
    )
    local = _name(tree, "E", 7)
    identity = tree.unit.exception_type_identity(local)
    assert identity.args[0].value == "source-class"
    assert _builtin_identity("ValueError") in tree.unit.exception_type_mro(local)

    imported_base = _name(tree, "F", 9)
    assert tree.unit.exception_type_identity(imported_base).args[0].value == (
        "source-class"
    )
    # The imported base's ancestry is its own proof's: unknown here.
    assert tree.unit.exception_type_mro(imported_base) is None
    value = tree.unit.exception_class_value(imported_base)
    assert isinstance(value, LocalExceptionClassValue)
    assert value.bases == (ExceptionClassValue("pyarrow.ArrowInvalid"),)

    builtin = _name(tree, "KeyError", 11)
    assert tree.unit.exception_type_identity(builtin) == _builtin_identity(
        "KeyError"
    )

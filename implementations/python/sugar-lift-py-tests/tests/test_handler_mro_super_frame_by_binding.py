"""Three readers decided by binding, never by spelling (#7757, leftovers of #8107).

- The optional-provider gate ``try: import m`` / ``except ...``: the lexical
  pass records the gate unevaluated (``TryImportGate``), and it is decided once
  the table is complete: the handler's class by the one exception-class lookup
  (``SourceUnit.exception_type_identity``) and whether it catches the absent
  provider's ``ModuleNotFoundError`` by the one matcher
  (``matches_raise_effect``). A superclass handler (``Exception``, bare
  ``except``) gates; a rebound, imported or source class never does by
  spelling; an undecided handler leaves the plain join.
- A mapping object's dunders resolve through the class's MRO
  (``ClassDef.namespace_owner`` over the one base walk): a source override
  before ``dict`` wins, a source method after ``dict`` does not.
- A zero-argument ``super()`` reads the frame its call runs in: a lambda is
  its own frame (``lambda x: super().m()`` binds ``x``), and a frame with no
  positional formal is CPython's ``RuntimeError``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import CallSiteValue, MappingObjectValue
from sugar_lift_py_tests.floor.builtin_semantic_callable import (
    zero_argument_super_has_no_arguments,
    zero_argument_super_receiver,
)
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.import_binding import (
    TryImportGate,
    _ImportDef,
    _Pass,
    _PROVIDER_ABSENT,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str):
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


# --- the optional-provider gate: the handler by binding, the one matcher -----


def _row_after_the_try(source: str) -> tuple:
    """The one table's decided row for a reference ``m`` after the ``try``:
    with the gate fact admitted, and without it."""
    tree = _tree(source + "m\n", "gate.py")
    reference = next(
        node for node in tree.nodes() if node.kind == "Name" and node.id == "m"
    )
    return (
        tree.unit.import_reference_of(reference, admit_provider_gate=True),
        tree.unit.import_reference_of(reference),
    )


def _gated(source: str) -> bool:
    # The closed gate: the import where the provider exists, read only by a
    # reader that carries the provider-absent face.
    return _row_after_the_try(source) == ("python:m", None)


def _plain(source: str) -> bool:
    # The plain join: the import may have failed, so the name binds nothing.
    return _row_after_the_try(source) == (None, None)


def test_the_pass_records_the_gate_unevaluated() -> None:
    # The pass does not read the handler's class while the table is being
    # built: every handler shape carries the same unevaluated gate fact.
    source = "try:\n    import m\nexcept ValueError:\n    pass\n"
    tree = _tree(source, "gate.py")
    runner = _Pass(
        source_cid=tree.unit.source_cid,
        module_name="gate",
        module_is_package=False,
        module_identities={},
    )
    reaching = runner.statements(tree.root.body, {}, tree.root)["m"]
    (definition,) = (value for value in reaching if isinstance(value, _ImportDef))
    assert _PROVIDER_ABSENT in reaching
    assert isinstance(definition.provider_gate, TryImportGate)
    assert runner.gate_verdicts == {}


@pytest.mark.parametrize(
    "handler",
    [
        "except ImportError:",
        "except ModuleNotFoundError:",
        "except Exception:",
        "except BaseException:",
        "except:",
        "except (ValueError, ImportError):",
    ],
)
def test_a_handler_that_catches_the_absent_provider_gates(handler: str) -> None:
    source = f"try:\n    import m\n{handler}\n    pass\n"

    assert _gated(source)


def test_an_aliased_builtin_is_judged_by_its_binding() -> None:
    source = (
        "from builtins import ImportError as Missing\n"
        "try:\n    import m\nexcept Missing:\n    pass\n"
    )

    assert _gated(source)


@pytest.mark.parametrize(
    "source",
    [
        # A handler that catches something else: the import may escape.
        "try:\n    import m\nexcept ValueError:\n    pass\n",
        # The spelling ``ImportError`` rebound: the binding is ValueError's.
        "ImportError = ValueError\n"
        "try:\n    import m\nexcept ImportError:\n    pass\n",
        # An imported class: its identity names a path, the match is open.
        "from elsewhere import ImportError\n"
        "try:\n    import m\nexcept ImportError:\n    pass\n",
        # A source subclass of ImportError does not catch ModuleNotFoundError.
        "class Missing(ImportError):\n    pass\n"
        "try:\n    import m\nexcept Missing:\n    pass\n",
        # A star import may bind any name: the handler's class is undecided.
        "from os.path import *\n"
        "try:\n    import m\nexcept ImportError:\n    pass\n",
    ],
)
def test_an_undecided_or_missing_catch_keeps_the_plain_join(source: str) -> None:
    assert _plain(source)


# --- mapping objects: every dunder through the class's MRO -------------------

_MAPPINGS = (
    "class Mixin:\n"
    "    def __getitem__(self, key):\n"
    "        return 1\n"
    "\n"
    "class Override(dict):\n"
    "    def __getitem__(self, key):\n"
    "        return 7\n"
    "    def __delitem__(self, key):\n"
    "        pass\n"
    "\n"
    "class After(dict, Mixin):\n"
    "    pass\n"
)


def _receivers():
    tree = _tree(_MAPPINGS, "mapping_mro.py")
    context = ReduceContext.root(owner="test")
    receivers = {}
    for node in tree.root.body:
        if not isinstance(node, ClassDef):
            continue
        value = node.sugar().desugar(context).completed_value()
        context.temporal = context.temporal.bind_value(value.class_name, value)
        receivers[value.class_name] = value.construct_receiver_state_from_block(
            None, f"receiver-{value.class_name}"
        )
    return context, receivers


def test_a_source_override_before_dict_wins_every_dunder() -> None:
    _context, receivers = _receivers()
    override = receivers["Override"]
    assert type(override) is MappingObjectValue

    assert override.protocol_owner("__getitem__", "t") == "source"
    assert override.protocol_owner("__delitem__", "t") == "source"
    assert override.protocol_owner("__setitem__", "t") == "dict"
    assert override.protocol_owner("__len__", "t") == "dict"
    # ``dict`` binds no ``__bool__``: truth falls to ``__len__``.
    assert override.protocol_owner("__bool__", "t") is None


def test_a_source_method_after_dict_in_the_mro_does_not_win() -> None:
    _context, receivers = _receivers()
    after = receivers["After"]
    assert type(after) is MappingObjectValue
    # The roster holds Mixin's ``__getitem__``; the MRO reaches dict first.
    assert after.has_method("__getitem__")

    assert after.protocol_owner("__getitem__", "t") == "dict"


def test_getitem_dispatches_the_source_override() -> None:
    context, receivers = _receivers()

    outcome = receivers["Override"].call_method_value(
        "__getitem__",
        (StringValue("k"),),
        owner="test",
        blame="override-getitem",
        ctx=context,
    )

    assert isinstance(outcome.completed_value(), CallSiteValue)


def test_a_door_without_context_refuses_a_source_override() -> None:
    _context, receivers = _receivers()

    with pytest.raises(ConstructionPanic):
        receivers["Override"].subscript(StringValue("k"), "override-subscript")


# --- zero-argument super(): the frame the call runs in -----------------------


def _super_call_site(tree):
    for node in tree.root.walk():
        callee = getattr(getattr(node, "func", None), "id", None)
        if getattr(node, "kind", None) == "Call" and callee == "super":
            return SimpleNamespace(unit=node.unit, node=node)
    raise AssertionError("no super() call in the source")


def _method_with(body: str) -> str:
    return (
        "class Base:\n"
        "    def m(self):\n"
        "        return 1\n"
        "\n"
        "class Derived(Base):\n"
        "    def m(self):\n"
        f"        return {body}\n"
    )


def test_super_in_a_lambda_reads_the_lambdas_own_first_formal() -> None:
    site = _super_call_site(
        _tree(_method_with("(lambda x: super().m())(self)"), "lambda_x.py")
    )
    inner = StringValue("lambda formal")
    temporal = (
        ReduceContext.root(owner="test")
        .temporal.bind_value("self", StringValue("method self"))
        .bind_value("x", inner)
    )

    assert not zero_argument_super_has_no_arguments(site)
    assert zero_argument_super_receiver(site, temporal) is inner


def test_super_in_a_lambda_without_formals_is_the_runtime_error() -> None:
    site = _super_call_site(
        _tree(_method_with("(lambda: super().m())()"), "lambda_none.py")
    )
    temporal = ReduceContext.root(owner="test").temporal.bind_value(
        "self", StringValue("method self")
    )

    assert zero_argument_super_has_no_arguments(site)
    assert zero_argument_super_receiver(site, temporal) is None


def test_super_in_a_method_reads_the_method_formal() -> None:
    site = _super_call_site(_tree(_method_with("super().m()"), "method.py"))
    receiver = StringValue("method self")
    temporal = ReduceContext.root(owner="test").temporal.bind_value("self", receiver)

    assert not zero_argument_super_has_no_arguments(site)
    assert zero_argument_super_receiver(site, temporal) is receiver


def test_super_in_a_def_without_positional_formals_is_the_runtime_error() -> None:
    source = (
        "class Base:\n"
        "    def m(*args):\n"
        "        return 1\n"
        "\n"
        "class Derived(Base):\n"
        "    def m(*args):\n"
        "        return super().m()\n"
    )
    site = _super_call_site(_tree(source, "varargs.py"))

    assert zero_argument_super_has_no_arguments(site)

from __future__ import annotations

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.floor.builtin_super_value import BuiltinSuperValue
from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

from frame_fresh import FRAME_FRESH


def _constructed(source: str, tmp_path=None):
    """The class values of ``source``; under a workspace root (``tmp_path``)
    each class names its join symbol, so a ``super()`` call names where it
    is looked up (``py.lookup``)."""
    if tmp_path is None:
        tree = SourceFile(
            (source, "super_dispatch.py", blake3_512_of(source.encode())),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    else:
        from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

        path = tmp_path / "super_dispatch.py"
        path.write_text(source)
        tree = open_source_file_for_construction(path, root=tmp_path)
    context = ReduceContext.root(owner="test")
    values = []
    for node in tree.root.body:
        if not isinstance(node, ClassDef):
            continue
        value = node.sugar().desugar(context).completed_value()
        context.temporal = context.temporal.bind_value(value.class_name, value)
        values.append(value)
    return context, values


def _call_fragment(source: str, text: str):
    """The source fragment of the call spelled ``text`` in ``source``: the
    site the lifter hands a ``super().<name>(...)`` call (a ground exit
    cites the source it can re-read, never prose)."""
    from sugar_source_tree.nodes import Call

    tree = SourceFile(
        (source, "super_dispatch.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    return next(
        node.fragment
        for node in tree.nodes()
        if isinstance(node, Call) and node.fragment.text == text
    )


def _edge_call(outcome):
    """The call coordinate ``outcome`` completes with: a method call on a
    receiver whose class is decided is its coordinate and edge (#7757 step
    6, #8738), the unanswered call's two faces, completing under its
    ``completes`` atom and halting under the complement.  The method's body
    is never applied here."""
    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert outcome.halts(), outcome
    _binds, call = peel_walrus_binds(done.value)
    assert isinstance(call, CallSiteValue), type(call)
    return call


# --- truthful twin: zero-arg super() into a same-module source base -----------
_TRUTHFUL = (
    "class Base:\n"
    "    def __init__(self, x):\n"
    "        self.x = x\n"
    "\n"
    "class Derived(Base):\n"
    "    def __init__(self, x):\n"
    "        super().__init__(x)\n"
)


_LIAR = (
    "class Base:\n"
    "    def __init__(self, x):\n"
    "        self.x = x\n"
    "\n"
    "class Derived(Base):\n"
    "    def __init__(self, x):\n"
    "        super().greet(x)\n"
)


def test_super_naming_an_absent_method_is_the_attribute_error() -> None:
    # Derived's MRO is read whole (Derived, Base, object) and no class after
    # Derived binds ``greet``: CPython's AttributeError, never a base method.
    context, (_base, derived) = _constructed(_LIAR)
    receiver = derived.fresh_receiver("receiver", allocation=FRAME_FRESH)
    zuper = BuiltinSuperValue(current_class=derived, receiver=receiver)

    outcome = zuper.call_method_value(
        "greet",
        (StringValue("v"),),
        owner="test",
        blame=_call_fragment(_LIAR, "super().greet(x)"),
        ctx=context,
    )

    assert outcome.halts() == outcome.exits
    assert [halt.effect.exception_name for halt in outcome.halts()] == [
        "AttributeError"
    ]


# --- a method the selected class writes, never one it inherits -----------------
_OWN_METHOD_ONLY = (
    "class Base:\n"
    "    def __init__(self, x):\n"
    "        self.x = x\n"
    "\n"
    "class Middle(Base):\n"
    "    pass\n"
    "\n"
    "class Derived(Middle):\n"
    "    def __init__(self, x):\n"
    "        super().__init__(x)\n"
)


def test_super_is_looked_up_after_the_cell_at_prove(tmp_path) -> None:
    # ``Middle`` binds no ``__init__``: the first class after ``Derived``'s
    # cell that does is ``Base``.  Which class that is is looked up once, at
    # prove, on the order the receiver's class's own proof states
    # (``consistency::dispatched_target``, #7757 entry 6): the call is the
    # one dispatched call, naming where to look -- after ``Derived``, on the
    # receiver's class -- and never the function.  The store ``self.x = x``
    # the body makes on the receiver is joined from that contract at prove.
    context, (_base, _middle, derived) = _constructed(_OWN_METHOD_ONLY, tmp_path)
    receiver = derived.fresh_receiver("receiver", allocation=FRAME_FRESH)

    call = _edge_call(
        BuiltinSuperValue(current_class=derived, receiver=receiver).call_method_value(
            "__init__",
            (StringValue("v"),),
            owner="test",
            blame="super-init",
            ctx=context,
        )
    )

    assert call.target_name == "dispatch:__init__", call.target_name
    # The completion is stated over ``python:call_result(<call term>,
    # <occurrence>)`` (#8828): the dispatched call's own term is its first
    # argument.
    term = call.term
    if getattr(term, "name", None) == "python:call_result":
        term = term.args[0]
    (lookup,) = (arg for arg in term.args if getattr(arg, "name", None) == "py.lookup")
    assert [part.value for part in lookup.args] == [
        "",
        "python:super_dispatch.Derived",
    ]
    (receiver_class,) = (
        arg.args[1]
        for arg in term.args
        if getattr(arg, "name", None) == "py.class" and arg.args[0].value == "0"
    )
    assert receiver_class.args[0].value == "python:super_dispatch.Derived"
    assert call.arg_values[0] is receiver
    assert call.arg_values[-1] == StringValue("v")


_FIELD_BASE = (
    "class Base:\n"
    "    m = lambda self, n: n // 0\n"
    "\n"
    "class Derived(Base):\n"
    "    def m(self, n):\n"
    "        return super().m(n)\n"
)


def test_super_of_a_function_class_field_is_the_dispatched_call(tmp_path) -> None:
    # ``Base`` holds ``m`` as a lambda field.  ``super().m(3)`` is the same
    # one dispatched call a ``def`` there is, looked up after ``Derived`` at
    # prove and bound by the ``field`` kind ``Base``'s namespace row states
    # (#7757 entry 6): the receiver is the first operand, never the lambda
    # applied here.
    context, (_base, derived) = _constructed(_FIELD_BASE, tmp_path)
    receiver = derived.fresh_receiver("receiver", allocation=FRAME_FRESH)

    call = _edge_call(
        BuiltinSuperValue(current_class=derived, receiver=receiver).call_method_value(
            "m",
            (StringValue("v"),),
            owner="test",
            blame="super-m",
            ctx=context,
        )
    )

    assert call.target_name == "dispatch:m", call.target_name
    term = call.term
    if getattr(term, "name", None) == "python:call_result":
        term = term.args[0]
    (lookup,) = (arg for arg in term.args if getattr(arg, "name", None) == "py.lookup")
    assert [part.value for part in lookup.args] == [
        "",
        "python:super_dispatch.Derived",
    ]
    assert call.arg_values[0] is receiver
    assert call.arg_values[-1] == StringValue("v")


def test_super_names_no_function_without_a_join_symbol() -> None:
    # No workspace root: no class names a join symbol, so nothing can name
    # where the method is looked up -- the one unanswered call, owed.
    context, (_base, _middle, derived) = _constructed(_OWN_METHOD_ONLY)
    receiver = derived.fresh_receiver("receiver", allocation=FRAME_FRESH)

    call = _edge_call(
        BuiltinSuperValue(current_class=derived, receiver=receiver).call_method_value(
            "__init__",
            (StringValue("v"),),
            owner="test",
            blame="super-init",
            ctx=context,
        )
    )

    assert call.target_name == "super.__init__", call.target_name


_ANNOTATED = (
    "class Base:\n"
    "    def __init__(self, match=None):\n"
    "        self.match = match\n"
    "        self._fail_reason: str | None = None\n"
    "        self._nested: bool = False\n"
    "        self.is_baseexception = False\n"
    "\n"
    "class Derived(Base):\n"
    "    def __init__(self, match=None):\n"
    "        super().__init__(match=match)\n"
    "        self.expected_exceptions = ()\n"
)



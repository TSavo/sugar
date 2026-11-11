"""A class an interpreter-owned C module exports is a two-faced C constructor.

``io.TextIOWrapper`` is ``_io.TextIOWrapper``, a heap type of a built-in C
module with no authenticated source.  The C-function rule never admits it (it
keys on ``builtin_function_or_method``).  This is the separate type rule:

- ``T(...)`` completes under ``python:c_type.constructs(...)`` keyed on the
  call site, with an instance of exactly ``T``; it halts with an
  ``UndeterminedRaiseEffect`` (owner ``LanguageOwnedCType:<module>.<name>``)
  under the complement.
- ``isinstance(x, T)`` is decided True only when ``x`` was constructed from
  exactly ``T`` at a known site (CPython's ``Py_IS_TYPE`` fast path, which
  cannot raise).  It is never decided False from missing knowledge.  Otherwise
  it is undecided and two-faced, because the fallback reads ``x.__class__``.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_lift_python_source.language_owned_c_export import (
    floor_artifact_module_absent_export,
)

from test_undetermined_raise_except_matching import _exits


def _owners(exits):
    return sorted(
        face.effect.producer_node_owner
        for face in exits.exits
        if isinstance(face, Halted) and isinstance(face.effect, UndeterminedRaiseEffect)
    )


def _returns(exits):
    return [
        type(face.value.record.statements[-1].value).__name__
        for face in exits.exits
        if isinstance(face, Completed)
    ]


def test_construction_is_two_faced_under_the_c_type_atom(tmp_path):
    exits = _exits(tmp_path, "import io\ndef f(b):\n    return io.TextIOWrapper(b)\n")
    assert _owners(exits) == ["LanguageOwnedCType:_io.TextIOWrapper"]
    (completed,) = [face for face in exits.exits if isinstance(face, Completed)]
    assert "python:c_type.constructs" in repr(completed.guard)
    assert "python:c_extension.call_completes" not in repr(exits)


def test_isinstance_of_an_instance_constructed_from_exactly_t_is_true(tmp_path):
    exits = _exits(
        tmp_path,
        "import io\ndef f(b):\n    w = io.TextIOWrapper(b)\n"
        "    return isinstance(w, io.TextIOWrapper)\n",
    )
    # Only the construction may raise; the test itself is decided.
    assert _owners(exits) == ["LanguageOwnedCType:_io.TextIOWrapper"]
    assert _returns(exits) == ["TrueBoolLiteralSugar"]


def test_isinstance_without_construction_knowledge_stays_undecided(tmp_path):
    exits = _exits(
        tmp_path, "import io\ndef f(x):\n    return isinstance(x, io.TextIOWrapper)\n"
    )
    assert _owners(exits) == ["UndecidedIsinstance:_io.TextIOWrapper"]
    assert _returns(exits) == ["PredicateValue"]


def test_an_instance_of_another_c_class_is_never_decided_false(tmp_path):
    exits = _exits(
        tmp_path,
        "import io\ndef f(b):\n    w = io.TextIOWrapper(b)\n"
        "    return isinstance(w, io.BytesIO)\n",
    )
    assert _owners(exits) == [
        "LanguageOwnedCType:_io.TextIOWrapper",
        "UndecidedIsinstance:_io.BytesIO",
    ]
    assert "FalseBoolLiteralSugar" not in _returns(exits)


class _Absent:
    kind = "artifact-module-absent"

    def __init__(self, module_name, exported_name):
        self.module_name = module_name
        self.exported_name = exported_name


def test_only_c_heap_classes_of_interpreter_owned_modules_qualify():
    from sugar_lift_py_tests.floor.language_owned_c_type import (
        LanguageOwnedCTypeValue,
    )
    from sugar_lift_py_tests.floor.language_owned_contextvar import (
        LanguageOwnedCExtensionCallableValue,
    )

    assert type(floor_artifact_module_absent_export(_Absent("_io", "TextIOWrapper"))) is (
        LanguageOwnedCTypeValue
    )
    # A C function stays with the C-function rule.
    assert type(floor_artifact_module_absent_export(_Absent("_io", "open"))) is (
        LanguageOwnedCExtensionCallableValue
    )
    # A Python module's class, a non-type, and a static builtin type are not.
    assert floor_artifact_module_absent_export(_Absent("json", "JSONDecoder")) is None
    assert floor_artifact_module_absent_export(_Absent("_io", "DEFAULT_BUFFER_SIZE")) is None
    assert floor_artifact_module_absent_export(_Absent("builtins", "int")) is None


def test_a_static_c_type_of_an_interpreter_owned_module_is_floored(tmp_path):
    """Truthful twin (#7735): ``decimal.Decimal`` is ``_decimal``'s static C type.

    No class statement can make a static type, so the interpreter's own flag
    proves it is C; its dotted ``tp_name`` names the extension module that
    declares it.  The call completes with an opaque instance or raises.
    """
    from sugar_lift_py_tests.floor.language_owned_c_type import (
        LanguageOwnedCTypeValue,
    )

    floored = floor_artifact_module_absent_export(_Absent("_decimal", "Decimal"))
    assert type(floored) is LanguageOwnedCTypeValue
    exits = _exits(
        tmp_path, "from decimal import Decimal\ndef f(v):\n    return Decimal(v)\n"
    )
    assert _owners(exits) == ["LanguageOwnedCType:_decimal.Decimal"]
    (completed,) = [face for face in exits.exits if isinstance(face, Completed)]
    assert "python:c_type.constructs" in repr(completed.guard)


def test_source_classes_core_types_and_absent_modules_are_not_floored():
    """Lying twin (#7735): only a C type with no Python source is cited."""
    # A class with Python source (the pure-Python fallback's Decimal).
    assert floor_artifact_module_absent_export(_Absent("_pydecimal", "Decimal")) is None
    # A static core language type keeps its own floor.
    assert floor_artifact_module_absent_export(_Absent("builtins", "dict")) is None
    # A module that does not exist keeps the gap, named.
    assert (
        floor_artifact_module_absent_export(_Absent("_no_such_c_module", "Decimal"))
        is None
    )


@pytest.mark.parametrize(
    ("source", "owner"),
    [
        # A method, an attribute read, and a call on the instance each run
        # native code nothing testified to: each is two-faced.
        (
            "import io\ndef f(b):\n    w = io.TextIOWrapper(b)\n    return w.read()\n",
            "UnprojectedMethodCall:read",
        ),
        (
            "import io\ndef f(b):\n    w = io.TextIOWrapper(b)\n    return w.encoding\n",
            "CResultAttribute:_io.TextIOWrapper.encoding",
        ),
        (
            "import functools\ndef f(g):\n    p = functools.partial(g, 1)\n    return p(2)\n",
            "CResultCall:_functools.partial",
        ),
        # The same law covers an opaque C-function result, which used to
        # complete a method call with no raise face.
        (
            "import decimal\ndef f():\n    c = decimal.getcontext()\n    return c.copy()\n",
            "UnprojectedMethodCall:copy",
        ),
    ],
)
def test_operations_on_an_opaque_c_value_are_two_faced(tmp_path, source, owner):
    exits = _exits(tmp_path, source)
    assert owner in _owners(exits)
    assert any(isinstance(face, Completed) for face in exits.exits)


def test_subscripting_a_cited_c_type_is_two_faced(tmp_path):
    """Truthful twin: ``T[k]`` on a C class is an opaque cited operation.

    Its ``__class_getitem__`` is native and never looked inside: the symbolic
    ``py.subscript`` completes only under ``python:subscript.completes`` keyed
    on the site, and the complement halts with an undetermined raise.
    """
    exits = _exits(tmp_path, "import io\ndef f(k):\n    return io.TextIOWrapper[k]\n")
    assert _owners(exits) == ["LanguageOwnedCType.subscript:_io.TextIOWrapper"]
    (completed,) = [face for face in exits.exits if isinstance(face, Completed)]
    assert "python:subscript.completes" in repr(completed.guard)
    assert "py.subscript" in repr(completed.value)


def test_a_subscripted_c_type_stands_as_a_base_and_its_halt_is_kept(tmp_path):
    # The class statement evaluates the base first: the class exists on the
    # completed face, and the base's undetermined raise is sequenced, not
    # dropped (before, a base's non-Complete outcome was discarded whole and
    # this function had no raise face at all).
    exits = _exits(
        tmp_path,
        "import io\ndef f(k):\n"
        "    class W(io.TextIOWrapper[k]):\n        pass\n    return W\n",
    )
    assert _owners(exits) == ["LanguageOwnedCType.subscript:_io.TextIOWrapper"]
    assert len([face for face in exits.exits if isinstance(face, Completed)]) == 1


def test_subscripts_that_are_not_on_a_cited_c_type_keep_their_own_path(tmp_path):
    """Lying twin: only the cited C class itself takes the C-type subscript."""
    # An instance of a C class is a C result, not the type: its own law.
    exits = _exits(
        tmp_path,
        "import io\ndef f(b, k):\n    w = io.TextIOWrapper(b)\n    return w[k]\n",
    )
    owners = _owners(exits)
    assert "LanguageOwnedCExtensionResultValue.subscript" in owners
    assert not any(owner.startswith("LanguageOwnedCType.subscript") for owner in owners)


def test_the_same_subscript_on_a_class_with_python_source_is_not_cited(tmp_path):
    """Lying twin of test_subscripting_a_cited_c_type_is_two_faced (#7755).

    The one difference: ``_pyio.TextIOWrapper`` is the same class written in
    Python.  A class with Python source is never floored as a C type, so the
    same subscript takes its own path, never the opaque C-type law.
    """
    exits = _exits(tmp_path, "import _pyio\ndef f(k):\n    return _pyio.TextIOWrapper[k]\n")
    assert not any(
        owner.startswith("LanguageOwnedCType.subscript") for owner in _owners(exits)
    )

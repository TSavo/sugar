"""``with open(...)``: the head calls a builtin that is an interpreter C function.

``builtins.open`` is ``_io.open``, a ``builtin_function_or_method`` of the
built-in module ``_io``, with no source anywhere.  Import receipts never fire
for a builtin name, so the use was ``runtime-selected`` and ``With`` refused
(24 pandas sites, e.g. ``core/series.py:1573``).  When the module binds the
name nowhere, every load reads the builtin.  The ``with`` law then runs over
the opaque result of that C call exactly as it does for an imported C function
(``decimal.localcontext``): the head call, ``__enter__`` and ``__exit__`` are
two-faced, and suppression is ``py.truthy`` of the opaque exit result.
Nothing is claimed about the result's type.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import (
    LanguageOwnedContextManagerRefV1,
    SourceFragmentCoordinateV1,
)
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_lift_python_source.language_owned_c_manager import (
    mint_builtin_c_manager_ref,
)

from test_undetermined_raise_except_matching import _exits


def test_with_open_is_the_c_manager_law(tmp_path):
    exits = _exits(
        tmp_path,
        "def f(p):\n    with open(p, encoding='utf-8') as fh:\n"
        "        raise ValueError\n    return 1\n",
    ).exits
    owners = sorted(
        face.effect.producer_node_owner
        for face in exits
        if isinstance(face, Halted) and isinstance(face.effect, UndeterminedRaiseEffect)
    )
    assert owners == [
        "LanguageOwnedCExtensionCallableValue:_io.open",
        "LanguageOwnedCManagerProtocol:_io.open.__enter__",
        "LanguageOwnedCManagerProtocol:_io.open.__exit__",
    ]
    # The body's own raise stays a face, and an undecided exit result may
    # suppress it, so the function may also return.
    assert any(
        isinstance(face, Halted) and not isinstance(face.effect, UndeterminedRaiseEffect)
        for face in exits
    )
    assert any(isinstance(face, Completed) for face in exits)


_SITE = SourceFragmentCoordinateV1("blake3-512:x", 2, 9, 2, 16)


def test_the_unbound_builtin_is_minted():
    ref = mint_builtin_c_manager_ref(_SITE, "open", "def f(p):\n    with open(p):\n        pass\n")
    assert isinstance(ref, LanguageOwnedContextManagerRefV1)
    assert (ref.protocol.module_name, ref.protocol.exported_name) == ("_io", "open")
    assert ref.target_symbol == "python:builtins.open"


def test_a_name_the_module_binds_is_not_the_builtin():
    for source in (
        "open = print\ndef f(p):\n    with open(p):\n        pass\n",
        "def open(p):\n    return p\ndef f(p):\n    with open(p):\n        pass\n",
        "from os import *\ndef f(p):\n    with open(p):\n        pass\n",
        "def f(open):\n    with open(1):\n        pass\n",
        "def f(p):\n    for open in p:\n        pass\n    with open(p):\n        pass\n",
    ):
        assert mint_builtin_c_manager_ref(_SITE, "open", source) is None, source


def test_a_builtin_class_is_not_a_c_function():
    # ``memoryview`` is a type, not a builtin function: its protocol is its
    # class's, which this law does not read.
    source = "def f(b):\n    with memoryview(b):\n        pass\n"
    assert mint_builtin_c_manager_ref(_SITE, "memoryview", source) is None

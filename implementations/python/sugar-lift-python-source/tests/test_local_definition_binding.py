"""A function-local ``class``/``def`` statement binds its name.

Every local name is seeded unbound at function entry and each binder threads
its value for the statements after it. ``class`` and ``def`` threaded
nothing, so ``def f(): class ValueError(Exception): ...; raise ValueError()``
read an unbound local and tried to mint a NameError, which crashed because
``NameErrorEffect`` could not be constructed at all (no exception type
coordinate, no locus). Now an undecorated local definition binds its own
definition, a decorated one binds a loud refusal (its value is the
decorator's result, which is not constructed), and a genuinely unbound read
halts with a NameError carrying the builtins NameError identity.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.name_error_effect import NameErrorEffect
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.panic import SugarNotWritten

from test_contextlib_suppress_source_exit_faces import _corpus, _open


def _exits(tmp_path: Path, source: str):
    source_file = _open(_corpus(tmp_path, source))
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    return func.sugar().desugar()


def test_local_class_shadowing_a_builtin_raises_the_local_class(tmp_path) -> None:
    exits = _exits(
        tmp_path,
        "def f():\n    class ValueError(Exception):\n        pass\n"
        '    raise ValueError("x")\n',
    )
    assert "NameError" not in repr(exits)
    # The raised class is the local one, not the builtin ValueError.
    assert "'builtins'), _ConstStr(value='ValueError'" not in repr(exits)
    assert all(isinstance(face, Halted) for face in exits.exits)


def test_local_class_read_is_the_name_not_a_name_error(tmp_path) -> None:
    exits = _exits(tmp_path, "def f():\n    class C:\n        pass\n    return C\n")
    (face,) = exits.exits
    assert isinstance(face, Completed)
    assert "NameError" not in repr(exits)
    assert "ReturnValue(value=SymbolicValue(term=_Var(name='C')" in repr(face)


def test_local_function_read_is_not_a_name_error(tmp_path) -> None:
    exits = _exits(
        tmp_path,
        "def f():\n    def g():\n        return 1\n    h = g\n    return h\n",
    )
    assert "NameError" not in repr(exits)


def test_decorated_local_definition_read_stays_loud(tmp_path) -> None:
    with pytest.raises(SugarNotWritten, match="decorated"):
        _exits(
            tmp_path,
            "import functools\ndef f(k):\n    @functools.wraps(k)\n"
            "    def g():\n        return 1\n    return g\n",
        )


def test_name_error_effect_is_constructible_with_builtin_identity(tmp_path) -> None:
    source_file = _open(_corpus(tmp_path, "def f():\n    return x\n"))
    name = next(n for n in source_file.nodes() if n.kind == "Name" and n.id == "x")
    effect = NameErrorEffect.at(name="x", site=name.fragment)
    assert isinstance(effect, RaiseEffect)
    # ``x`` is not local to ``f``: an unbound global read is NameError.
    assert effect.exception_name == "NameError"
    assert "NameError" in repr(effect.exception_type_coordinate)
    assert effect.reason.startswith("NameError for unbound name 'x'")


def test_read_before_local_definition_is_a_name_error(tmp_path) -> None:
    exits = _exits(
        tmp_path, "def f():\n    y = C\n    class C:\n        pass\n    return y\n"
    )
    (face,) = exits.exits
    assert isinstance(face, Halted)
    assert isinstance(face.effect, NameErrorEffect)
    assert face.effect.name == "C"
    # An unbound function local is UnboundLocalError, a NameError subclass.
    assert face.effect.exception_name == "UnboundLocalError"
    assert "'NameError'" in repr(face.effect.exception_type_mro)

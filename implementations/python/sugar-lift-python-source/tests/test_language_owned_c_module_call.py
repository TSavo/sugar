"""A consumer module's own call to an interpreter C function is two-faced.

``decimal.getcontext`` resolves to ``_decimal.getcontext``, a builtin function
of a stdlib C extension with no source. Frame projection already floored such
a call inside a dependency frame; the consumer module's own call never passed
through it, so ``return decimal.getcontext()`` lifted as a bodiless
``CallSiteValue`` with a single Completed face. The call now applies the same
C-call law as everywhere else: an opaque completion under
``python:c_extension.call_completes`` or an ``UndeterminedRaiseEffect`` halt
under its complement. The floor is keyed on the runtime object, never a name.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset
from sugar_source_tree.nodes import FunctionDef

from test_contextlib_suppress_source_exit_faces import _corpus, _open


def _exits(tmp_path: Path, source: str):
    source_file = _open(_corpus(tmp_path, source))
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    return outcome_to_exitset(func.sugar().desugar())


def _owners(exits):
    return sorted(
        face.effect.producer_node_owner
        for face in exits.exits
        if isinstance(face, Halted) and isinstance(face.effect, UndeterminedRaiseEffect)
    )


def _completes_under_c_call_atom(exits, name: str) -> bool:
    completed = [face for face in exits.exits if isinstance(face, Completed)]
    return bool(completed) and all(
        "python:c_extension.call_completes" in repr(face.guard)
        and f"value='{name}'" in repr(face.guard)
        for face in completed
    )


@pytest.mark.parametrize(
    ("body", "name"),
    [
        ("return decimal.getcontext()", "getcontext"),
        ("return decimal.localcontext()", "localcontext"),
        ("decimal.getcontext()\n    return 1", "getcontext"),
    ],
)
def test_dotted_c_function_call_may_raise(tmp_path, body, name) -> None:
    exits = _exits(tmp_path, f"import decimal\ndef f():\n    {body}\n")
    assert _owners(exits) == [f"LanguageOwnedCExtensionCallableValue:_decimal.{name}"]
    assert _completes_under_c_call_atom(exits, name)
    assert "CallSiteValue(target_name='decimal." not in repr(exits)


def test_from_imported_c_function_call_may_raise(tmp_path) -> None:
    exits = _exits(
        tmp_path, "from decimal import getcontext\ndef f():\n    return getcontext()\n"
    )
    assert _owners(exits) == ["LanguageOwnedCExtensionCallableValue:_decimal.getcontext"]
    assert _completes_under_c_call_atom(exits, "getcontext")


def test_each_c_call_site_has_its_own_raise_face(tmp_path) -> None:
    exits = _exits(
        tmp_path,
        "import decimal\ndef f():\n    decimal.getcontext()\n    return decimal.getcontext()\n",
    )
    halts = [face for face in exits.exits if isinstance(face, Halted)]
    assert len(halts) == 2
    assert len({face.effect.blame for face in halts}) == 2


def test_c_type_construction_is_not_floored_as_a_c_function(tmp_path) -> None:
    # ``_decimal.Decimal`` is a C type, not a builtin function: runtime
    # identity does not admit the C-function floor, so no C-call face appears.
    # Constructing it is still a call whose body the lift does not hold, so it
    # may raise -- under its own unknown-callee face, never the C-call one.
    exits = _exits(tmp_path, "import decimal\ndef f():\n    return decimal.Decimal(1)\n")
    assert _owners(exits) == ["UnknownCallee:decimal.Decimal"]

"""A manager built by an interpreter C function has a C-owned protocol.

``decimal.localcontext`` resolves to ``_decimal.localcontext``, a builtin
function of a stdlib C extension. Its ``__enter__`` and ``__exit__`` have no
source, so each is a two-faced C call: an opaque result, or an
``UndeterminedRaiseEffect`` halt. Suppression of a body raise is decided only by
``py.truthy`` of the opaque exit result, so a raising body leaves both as a
possibly-suppressed completion and as the re-raised exception.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.context_manager_contract import (
    ContextManagerContractError,
    EnterResultContractV1,
    ExitContractV1,
    LanguageOwnedCCallFacesCompletionV1,
    ProtocolResourceSemanticsV1,
    ReturnTruthinessDispositionV1,
    _decode_protocol_resource,
    semantics_to_value,
)
from sugar_lift_py_tests.context_manager_resolution import (
    LanguageOwnedContextManagerRefV1,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.language_owned_c_manager import (
    LanguageOwnedCManagerProtocol,
    LanguageOwnedCSlotResultValue,
)
from sugar_lift_py_tests.ir import PrimitiveSort, py_truthy
from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset
from sugar_lift_py_tests.sugar.with_language_owned_resource_sugar import (
    WithLanguageOwnedResourceSugar,
)
from sugar_lift_python_source.language_owned_c_manager import (
    _interpreter_owned_c_function,
)
from sugar_source_tree.nodes import FunctionDef, With

from test_contextlib_suppress_source_exit_faces import _corpus, _open


def _localcontext(tmp_path: Path, body: str):
    source = (
        "import decimal\n"
        "def f():\n"
        "    with decimal.localcontext() as ctx:\n"
        f"        {body}\n"
    )
    source_file = _open(_corpus(tmp_path, source))
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    (ref,) = refs.values()
    assert type(ref) is LanguageOwnedContextManagerRefV1
    assert ref.exported_name == "localcontext"
    assert isinstance(ref.protocol, LanguageOwnedCManagerProtocol)
    assert ref.protocol.module_name == "_decimal"
    semantics = ref.semantics
    assert isinstance(semantics, ProtocolResourceSemanticsV1)
    assert isinstance(semantics.enter.completion, LanguageOwnedCCallFacesCompletionV1)
    assert isinstance(semantics.exit.completion, LanguageOwnedCCallFacesCompletionV1)
    assert isinstance(semantics.exit.disposition, ReturnTruthinessDispositionV1)
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    assert type(with_node.sugar()) is WithLanguageOwnedResourceSugar
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    # The function still reduces; the With's own faces are asserted below.
    func.sugar().desugar()
    return outcome_to_exitset(with_node.sugar().desugar())


def _halts(exits):
    return [face for face in exits.exits if isinstance(face, Halted)]


def _completed(exits):
    """Faces that leave the With normally (not halt-companion binding residue)."""
    return [
        face
        for face in exits.exits
        if isinstance(face, Completed) and face.value.can_fall_through
    ]


def _exit_site(face) -> str:
    import re

    (site,) = set(
        re.findall(r"__exit__', sort=PrimitiveSort\(name='String'\)\), _ConstStr\(value=\"([^\"]+)\"", repr(face.guard))
    )
    return site


def _undetermined_owners(exits):
    return sorted(
        face.effect.producer_node_owner
        for face in _halts(exits)
        if isinstance(face.effect, UndeterminedRaiseEffect)
    )


def test_c_function_identity_is_checked_at_runtime() -> None:
    import _decimal

    assert _interpreter_owned_c_function("_decimal", "localcontext") is (
        _decimal.localcontext
    )
    # A C type, a non-callable, a pure-Python module, and a missing name are not.
    assert _interpreter_owned_c_function("_decimal", "Decimal") is None
    assert _interpreter_owned_c_function("_decimal", "MAX_PREC") is None
    assert _interpreter_owned_c_function("json", "dumps") is None
    assert _interpreter_owned_c_function("_decimal", "no_such_name") is None


def test_empty_body_completes_or_halts_in_each_c_call(tmp_path: Path) -> None:
    exits = _localcontext(tmp_path, "pass")
    assert _completed(exits)
    # The constructor, __enter__ and __exit__ may each raise; none is total.
    assert _undetermined_owners(exits) == [
        "LanguageOwnedCExtensionCallableValue:_decimal.localcontext",
        "LanguageOwnedCManagerProtocol:_decimal.localcontext.__enter__",
        "LanguageOwnedCManagerProtocol:_decimal.localcontext.__exit__",
    ]
    assert not [h for h in _halts(exits) if isinstance(h.effect, RaiseEffect)]


def test_body_raise_is_suppressed_only_under_exit_truth(tmp_path: Path) -> None:
    exits = _localcontext(tmp_path, "raise ValueError('boom')")
    reraised = [
        face
        for face in _halts(exits)
        if isinstance(face.effect, RaiseEffect)
        and face.effect.exception_name == "ValueError"
    ]
    # Never assumed to propagate and never assumed to be swallowed: both faces.
    (reraise,) = reraised
    suppressed = _completed(exits)
    assert len(suppressed) == 1
    truthy = repr(
        py_truthy(
            LanguageOwnedCSlotResultValue(
                module_name="_decimal",
                exported_name="localcontext",
                slot="__exit__",
                site=_exit_site(suppressed[0]),
            ).to_term(owner="test")
        )
    )
    assert truthy in repr(suppressed[0].guard)
    assert f"not', operands=({truthy}" in repr(reraise.guard)
    assert f"not', operands=({truthy}" not in repr(suppressed[0].guard)
    assert _undetermined_owners(exits) == [
        "LanguageOwnedCExtensionCallableValue:_decimal.localcontext",
        "LanguageOwnedCManagerProtocol:_decimal.localcontext.__enter__",
        "LanguageOwnedCManagerProtocol:_decimal.localcontext.__exit__",
    ]


def test_c_call_faces_round_trips_and_stays_distinct_from_total() -> None:
    semantics = ProtocolResourceSemanticsV1(
        EnterResultContractV1(
            PrimitiveSort("Value"), LanguageOwnedCCallFacesCompletionV1()
        ),
        ExitContractV1(
            ReturnTruthinessDispositionV1(), LanguageOwnedCCallFacesCompletionV1()
        ),
    )
    raw = json.loads(encode_jcs(semantics_to_value(semantics)))
    assert raw["enter"]["completion"] == {"kind": "language-owned-c-call-faces"}
    assert raw["exit"]["completion"] == {"kind": "language-owned-c-call-faces"}
    assert _decode_protocol_resource(raw) == semantics
    raw["exit"]["completion"] = {"kind": "partial"}
    with pytest.raises(ContextManagerContractError):
        _decode_protocol_resource(raw)

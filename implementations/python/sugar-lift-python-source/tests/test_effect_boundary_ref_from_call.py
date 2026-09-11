"""Twins for the call-site Expects-Raise effect-boundary seal.

When constructing a pytest.raises factory over-seats the RaisesExc class span
(__enter__'s ExceptionInfo.for_later is unreachable from the constructor yet
voids the factory frame), the contract is sealed directly from the manager
CALL: the authenticated exception-type argument IS the contract. These pin that
the seal fires for authenticated exception-type calls and refuses otherwise.
"""

from __future__ import annotations

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_summary_derivation import (
    _effect_boundary_ref_from_call,
)
from sugar_lift_py_tests.context_manager_contract import (
    EffectBoundarySemanticsV1,
    ExpectsModeV1,
    NoMessagePatternV1,
    OptionalFormalArgumentProjectionV1,
    RaiseEffectKindV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    SourceDerivedContextManagerRefV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_source_tree.nodes import Call
from sugar_source_tree.tree import SourceFile


def _call(src: str) -> Call:
    tree = SourceFile(
        (src, "c.py", blake3_512_of(src.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    return next(n for n in tree.root.walk() if isinstance(n, Call))


def _coord(src: str):
    tree = SourceFile(
        (src, "c.py", blake3_512_of(src.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    return SourceFragmentCoordinateV1(tree.unit.source_cid, 1, 0, 1, 1)


def _seal(src: str):
    return _effect_boundary_ref_from_call(_coord(src), _call(src))


# --- fires: authenticated exception-type argument -----------------------------
def test_plain_raises_seals_expects_raise_no_message() -> None:
    ref = _seal("import pytest\ndef f():\n    with pytest.raises(ValueError):\n        pass\n")
    assert isinstance(ref, SourceDerivedContextManagerRefV1)
    sem = ref.semantics
    assert isinstance(sem, EffectBoundarySemanticsV1)
    assert isinstance(sem.mode, ExpectsModeV1)
    assert isinstance(sem.effect_kind, RaiseEffectKindV1)
    assert sem.expected_type_operand.parameter_index == 0
    assert isinstance(sem.message_pattern_operand, NoMessagePatternV1)
    assert len(ref.import_signature.parameters) == 1
    assert ref.protocol is None


def test_raises_with_match_seals_optional_message_projection() -> None:
    ref = _seal(
        "import pytest\ndef f():\n    with pytest.raises(ValueError, match='x'):\n        pass\n"
    )
    assert isinstance(ref, SourceDerivedContextManagerRefV1)
    assert ref.semantics.expected_type_operand.parameter_index == 0
    assert isinstance(
        ref.semantics.message_pattern_operand, OptionalFormalArgumentProjectionV1
    )
    assert ref.semantics.message_pattern_operand.parameter_index == 1
    assert len(ref.import_signature.parameters) == 2


def test_imported_exception_type_argument_seals() -> None:
    ref = _seal(
        "import numpy as np\ndef f():\n    with recwarn(np.AxisError):\n        pass\n"
    )
    # np.AxisError authenticates as an imported exception type -> seals.
    assert isinstance(ref, SourceDerivedContextManagerRefV1)
    assert ref.semantics.expected_type_operand.parameter_index == 0


# --- refuses: no authenticated exception-type argument ------------------------
def test_no_exception_type_argument_returns_none() -> None:
    assert _seal("def f():\n    with open('p'):\n        pass\n") is None


def test_non_exception_positional_returns_none() -> None:
    assert _seal("def f():\n    with ctx(123):\n        pass\n") is None



def test_tuple_of_exception_types_seals() -> None:
    ref = _seal(
        "import pytest\ndef f():\n    with pytest.raises((ValueError, TypeError), match='x'):\n        pass\n"
    )
    assert isinstance(ref, SourceDerivedContextManagerRefV1)
    assert ref.semantics.expected_type_operand.parameter_index == 0
    assert isinstance(
        ref.semantics.message_pattern_operand, OptionalFormalArgumentProjectionV1
    )


def test_tuple_with_one_non_exception_element_returns_none() -> None:
    # Not every element authenticates -> not a tuple of exception types.
    assert _seal("def f(x):\n    with ctx((ValueError, x)):\n        pass\n") is None

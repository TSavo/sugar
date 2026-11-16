"""UnaryOp ``not``: ``result = not value`` is ``not bool(value)``, always a bool.

Python semantic law made constructible here (distinct from BoolOp #6595):

  a. ``bool(value)`` MAY halt — truth dispatch can raise a source-authenticated
     exception type (synthetic Floor); pandas ``not NA`` / ``not obj1`` are the
     one truth rule's two faces until an NDFrame/NAType truth floor exists.
  b. Only the completed truth face is negated — a halt has no bool to flip.
  c. The result is always ``True``/``False``, never the operand.
  d. Exception type originates in the truth floor, never from an enclosing
     ``pytest.raises`` expectation.

Producer method: ``UnaryOpSugar.desugar`` (op_kind ``Not``).
Floor consumer methods: ``FloorValue.truth`` through the one truth rule
(``bool_op_sugar.truth_of``), and bool-literal ``negate``.  A parameter's
``not`` takes the same rule, its two faces: no carrier (#7757 NEW-1).

Corpus coordinates (pandas 3.0.3, verified by line content, not by path alone):

  - ``tests/scalar/test_na_scalar.py:48`` — ``not NA`` under ``pytest.raises(TypeError)``
  - ``tests/generic/test_generic.py:156`` — ``not obj1`` under ``pytest.raises(ValueError)``
    (both two-faced: ``bool(NA)`` and ``bool(obj1)`` are taken by the one
    truth rule)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    NativeOperationResolutionV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import FloorValue, NoneValue, SymbolicValue, TermValue
from sugar_lift_py_tests.floor.ground_exit import ground_type_error
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, make_var, str_const
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import UnaryOp
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _identity(name: str):
    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
NA_SITE_SHA256 = "e46445908318d803ea24ac6c8f09ba2347de6fc31e12f2459555a1ba1b15e703"
GENERIC_SITE_SHA256 = "cbc5383e8e1545537baedca85a6c62a487d3bea6942bb56e5e0c7479dd2f188d"


@dataclass(frozen=True)
class _Site:
    filename: str = "unary-not-law.py"
    line: int = 1
    col: int = 0
    source: str = "result = not value"
    unit: object = field(
        default_factory=lambda: type("_Unit", (), {"source": "result = not value\n"})()
    )


@dataclass(frozen=True)
class _ValueSugar(ConstructedTermSugar):
    """A constructed operand: every nested term slot admits only a
    ``ConstructedTermSugar`` (``require_constructed_term_sugar``)."""

    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value)

    def to_term(self, *, owner):
        return self.value.to_term(owner=owner)


@dataclass(frozen=True)
class _AmbiguousTruth(FloorValue):
    """Source-decided operand whose ``__bool__`` face is authenticated TypeError.

    Stands in for real bodies (``NAType.__bool__``, ``NDFrame.__bool__``) once a
    Floor law authenticates those types.  Until then, this probe exercises the
    UnaryOp ``not`` exceptional face against an *existing* ground TypeError door.
    """

    def denotes_value(self) -> bool:
        return True

    def runtime_type_is_decided(self) -> bool:
        return True

    def truth(self, site):
        return ground_type_error(site=site, owner="_AmbiguousTruth.truth")

    def to_term(self, *, owner: str):
        del owner
        return ctor("python:probe_ambiguous_truth", [])


@dataclass(frozen=True)
class _OperandReturningTruth(FloorValue):
    """LYING floor: truth returns the operand floor itself (not a bool)."""

    payload: FloorValue

    def denotes_value(self) -> bool:
        return True

    def runtime_type_is_decided(self) -> bool:
        return True

    def truth(self, site):
        del site
        return ExitSet.completed(self.payload)

    def to_term(self, *, owner: str):
        del owner
        return ctor("python:probe_operand_truth", [])


def _not_sugar(value) -> ExitSet:
    return UnaryOpSugar("Not", _ValueSugar(value), _Site()).desugar(None)


def _completed_value(outcome):
    exits = outcome.exits
    assert len(exits) == 1
    assert isinstance(exits[0], Completed)
    return exits[0].value


def _unary_node(source: str = "def f(value):\n    return not value\n") -> UnaryOp:
    tree = SourceFile(
        (source, "unary_not_demand.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, UnaryOp))


def _formal(node: UnaryOp) -> FormalParameterCoordinateV1:
    span = node.fragment.line_col_span
    owner = SourceFragmentCoordinateV1(
        node.fragment.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    return FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=node.fragment.source_cid,
        owner_definition_locus=owner,
        declaration_locus=owner,
        ordinal=0,
        parameter_kind="positional-or-keyword",
        declared_name="value",
        sort=PrimitiveSort("Value"),
    )


def _formal_not() -> tuple[ExitSet, FormalParameterCoordinateV1]:
    node = _unary_node()
    formal = _formal(node)
    outcome = UnaryOpSugar(
        "Not",
        _ValueSugar(SymbolicValue(make_var("value"), formal)),
        node.fragment,
    ).desugar(None)
    return outcome, formal


# ---------------------------------------------------------------------------
# Corpus coordinate verification (line numbers verified against file content)
# ---------------------------------------------------------------------------


def test_verified_pandas_303_not_reproducers_are_content_pinned() -> None:
    corpus = authenticated_pandas_corpus()
    assert corpus.manifest_cid == MANIFEST_CID
    assert corpus.file_count == 1421

    na_path = corpus.root / "tests/scalar/test_na_scalar.py"
    generic_path = corpus.root / "tests/generic/test_generic.py"
    assert hashlib.sha256(na_path.read_bytes()).hexdigest() == NA_SITE_SHA256
    assert hashlib.sha256(generic_path.read_bytes()).hexdigest() == GENERIC_SITE_SHA256

    na_lines = na_path.read_text(encoding="utf-8").splitlines()
    generic_lines = generic_path.read_text(encoding="utf-8").splitlines()
    # 1-indexed line 48 / 156 — verify content, not a remembered number.
    assert na_lines[47].strip() == "not NA"
    assert generic_lines[155].strip() == "not obj1"
    assert "pytest.raises(TypeError" in na_lines[46]
    assert "pytest.raises(ValueError" in generic_lines[154]


def test_corpus_not_over_an_import_member_is_the_two_faced_truth() -> None:
    """``not NA``: ``bool(NA)`` is not decided here, so it is the two faces.

    ``NA`` is ``from pandas._libs.missing import NA``: an import member, whose
    operand is the closed reference the import names,
    ``ref:pandas._libs.missing.NA`` (#7837) -- the module the source imports
    it from, never a re-export nobody read.  Its runtime type is not
    decided, so its truth is the undecided member, exactly as for a bare
    symbolic local (``test_corpus_not_over_a_symbolic_local_is_the_two_faced
    _truth``): it completes only under ``python:truth.completes`` over that
    reference, only the completed truth is negated, and the complement halts
    with an UndeterminedRaiseEffect.  TypeError is not minted from the
    surrounding ``pytest.raises``.
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.floor_value import undecided_predicate_result
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import not_

    corpus = authenticated_pandas_corpus()
    path = corpus.root / "tests/scalar/test_na_scalar.py"
    source = path.read_text(encoding="utf-8")
    tree = SourceFile(
        (source, str(path), blake3_512_of(source.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    (node,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, UnaryOp) and node.line_col_span().start_line == 48
    )
    assert "from pandas._libs.missing import NA\n" in source
    reference = ctor("ref:pandas._libs.missing.NA", [], symbol_kind="coordinate")
    outcome = node.sugar().desugar(None)
    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(halted) == 1 and len(completed) == 1
    assert type(halted[0].effect) is UndeterminedRaiseEffect
    assert halted[0].effect.producer_node_owner == "UnaryOpSugar.not"
    assert "python:truth.completes" in repr(halted[0].guard)
    assert repr(reference) in repr(halted[0].guard)
    assert "TypeError" not in repr(halted[0])
    assert isinstance(completed[0].value, PredicateValue)
    # The truth is keyed per evaluation, at the halt's own key (#7757 NEW-1).
    assert completed[0].value.formula == not_(
        undecided_predicate_result(
            "truth", (reference,), halted[0].effect.occurrence
        )
    )


def test_corpus_not_over_a_symbolic_local_is_the_two_faced_truth() -> None:
    """``not obj1``: ``bool(obj1)`` may run code, so it is the two faces.

    The truth completes only under ``python:truth.completes`` and only that
    completed truth is negated; the complement halts with an
    UndeterminedRaiseEffect.  ValueError is not minted from the surrounding
    ``pytest.raises``.
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.floor_value import undecided_predicate_result
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import not_

    corpus = authenticated_pandas_corpus()
    path = corpus.root / "tests/generic/test_generic.py"
    source = path.read_text(encoding="utf-8")
    tree = SourceFile(
        (source, str(path), blake3_512_of(source.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    (node,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, UnaryOp) and node.line_col_span().start_line == 156
    )
    outcome = node.sugar().desugar(None)
    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(halted) == 1 and len(completed) == 1
    assert type(halted[0].effect) is UndeterminedRaiseEffect
    assert halted[0].effect.producer_node_owner == "UnaryOpSugar.not"
    assert "ValueError" not in repr(halted[0])
    assert "python:truth.completes" in repr(completed[0].guard)
    assert isinstance(completed[0].value, PredicateValue)
    # The truth is keyed per evaluation, at the halt's own key (#7757 NEW-1).
    assert completed[0].value.formula == not_(
        undecided_predicate_result(
            "truth", (make_var("obj1"),), halted[0].effect.occurrence
        )
    )


# ---------------------------------------------------------------------------
# a–c: completed face is negated bool; halt is not negated
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected_type"),
    (
        (TermValue(0), TrueBoolLiteralSugar),
        (TermValue(1), FalseBoolLiteralSugar),
        (NoneValue(), TrueBoolLiteralSugar),
        (TrueBoolLiteralSugar(_Site()), FalseBoolLiteralSugar),
        (FalseBoolLiteralSugar(_Site()), TrueBoolLiteralSugar),
    ),
)
def test_not_completed_face_is_always_a_bool(value, expected_type) -> None:
    """Face (c): ``not x`` yields True/False, never the operand."""
    result = _completed_value(_not_sugar(value))
    assert isinstance(result, expected_type)
    assert result is not value


def test_not_never_returns_the_operand_itself() -> None:
    """Second lying twin target: an implementation that returns the operand."""
    operand = TermValue(0)
    result = _completed_value(_not_sugar(operand))
    assert result is not operand
    assert isinstance(result, TrueBoolLiteralSugar)


def test_halted_truth_is_not_negated() -> None:
    """Face (b): a halted ``bool(value)`` has no truth value to negate."""
    outcome = _not_sugar(_AmbiguousTruth())
    exits = outcome.exits
    assert len(exits) == 1
    # A raise is a Halted face: the effect is TypeError and not flipped.
    face = exits[0]
    assert isinstance(face, Halted)
    assert face.effect.exception_name == "TypeError"
    assert face.effect.exception_type_coordinate == _identity("TypeError")


def test_truthful_exceptional_face_carries_floor_type_not_boundary() -> None:
    """Face (a)+(d): TypeError coordinate comes from the truth floor."""
    outcome = _not_sugar(_AmbiguousTruth())
    exits = outcome.exits
    face = exits[0]
    if isinstance(face, Completed):
        effect = face.effect
    else:
        effect = face.effect
    floor_type = effect.exception_type_coordinate
    assert floor_type == ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("TypeError")],
    )
    # producer_node_owner cites the truth floor, not the assertion boundary.
    assert effect.producer_node_owner == "_AmbiguousTruth.truth"


# ---------------------------------------------------------------------------
# Formal: the one truth rule's two faces, then negate (#7757 NEW-1)
# ---------------------------------------------------------------------------


def test_formal_not_is_the_two_faced_truth_then_negate() -> None:
    """``not value`` on a parameter mints no carrier waiting on a caller's
    actual production never supplies: ``bool(value)`` is the one truth
    rule's two faces (``__bool__`` then ``__len__`` then ``True`` is a
    protocol no one dispatched method states), and only the completed
    truth is negated.  The halt is kept; no exception type is named."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.floor_value import undecided_predicate_result
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import not_

    outcome, _formal_coordinate = _formal_not()
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(halted) == 1 and len(completed) == 1
    assert type(halted[0].effect) is UndeterminedRaiseEffect
    assert halted[0].effect.producer_node_owner == "UnaryOpSugar.not"
    assert "TypeError" not in repr(halted[0])
    assert "python:truth.completes" in repr(completed[0].guard)
    assert isinstance(completed[0].value, PredicateValue)
    # The truth is keyed per evaluation, at the halt's own key (#7757 NEW-1).
    assert completed[0].value.formula == not_(
        undecided_predicate_result(
            "truth", (make_var("value"),), halted[0].effect.occurrence
        )
    )
    assert completed[0].owed and completed[0].owed == halted[0].owed


def test_formal_not_is_the_truth_a_free_symbol_takes() -> None:
    """One way: the formal's ``not`` is the same outcome a symbolic value
    with no formal coordinate takes over the same term."""
    node = _unary_node()
    outcome, _formal_coordinate = _formal_not()
    free = UnaryOpSugar(
        "Not", _ValueSugar(SymbolicValue(make_var("value"))), node.fragment
    ).desugar(None)
    assert outcome == free



# ---------------------------------------------------------------------------
# LYING twins that MUST FAIL
# ---------------------------------------------------------------------------


def test_lying_operand_return_is_not_the_not_law() -> None:
    """Lying twin: return the operand (BoolOp shape) instead of a bool.

    A correct ``not`` never yields the operand.  An implementation that skips
    coerce-to-bool and returns ``value`` would pass a weak ``is not None`` check
    but fails this exact-type assertion.
    """
    operand = TermValue(0)
    # Truthful path:
    truthful = _completed_value(_not_sugar(operand))
    assert isinstance(truthful, TrueBoolLiteralSugar)

    # Lying path: pretend truth returned the operand (skip bool coerce).
    lying_floor = _OperandReturningTruth(operand)
    lying_truth = lying_floor.truth(_Site())
    assert lying_truth.completed_value() is not None
    # The lying floor's truth is the operand — UnaryOp must not accept that as
    # the final ``not`` result.  Real desugar on a value whose truth is non-bool
    # and not a raise hits negate on a TermValue → construction panic (no
    # negate floor).  That is louder than a silent wrong bool.
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic, match="negate"):
        _not_sugar(lying_floor)


def test_lying_boundary_exception_type_is_not_truth_origin() -> None:
    """Lying twin: take TypeError from ``pytest.raises`` rather than ``__bool__``.

    Both coordinates may *denote* TypeError.  Origin is the operation occurrence
    and the floor's producer owner — not type equality.  Substituting the
    boundary's expected type while keeping a different occurrence must not be
    treated as the same authenticated exit as the truth-floor halt.
    """
    fragment = _unary_node().fragment
    # Truthful: exception type + occurrence from the truth floor / operation site.
    truthful_outcome = UnaryOpSugar(
        "Not", _ValueSugar(_AmbiguousTruth()), fragment
    ).desugar(None)
    truthful_exits = truthful_outcome.exits
    face = truthful_exits[0]
    if isinstance(face, Completed):
        truthful_effect = face.effect
    else:
        truthful_effect = face.effect
    floor_type = truthful_effect.exception_type_coordinate
    assert floor_type is not None
    assert truthful_effect.producer_node_owner == "_AmbiguousTruth.truth"

    # Boundary also "expects" TypeError — same type name, different origin story.
    boundary_type = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("TypeError")],
    )
    assert boundary_type == floor_type  # equality alone proves nothing

    operation_origin = fragment
    truthful_resolution = NativeOperationResolutionV1.exceptional(
        exception_type_coordinate=floor_type,
        operation_occurrence=operation_origin,
    )
    # Lying: same type coordinate content, but occurrence is the *assertion*
    # site (boundary), not the UnaryOp / truth raise occurrence.
    boundary_origin = _Site(line=fragment.line + 10)
    lying_resolution = NativeOperationResolutionV1.exceptional(
        exception_type_coordinate=boundary_type,
        operation_occurrence=boundary_origin,
    )

    truthful_halt = truthful_resolution.project(source_node=fragment).exits[0]
    lying_halt = lying_resolution.project(source_node=fragment).exits[0]
    assert isinstance(truthful_halt, Halted)
    assert isinstance(lying_halt, Halted)
    # Same type name — origin (occurrence) still distinguishes them.
    assert (
        truthful_halt.effect.exception_type_coordinate
        == lying_halt.effect.exception_type_coordinate
    )
    assert truthful_halt.effect.occurrence != lying_halt.effect.occurrence

    # An implementation that only checks type equality would treat these as
    # interchangeable.  The law requires the operation occurrence from the
    # truth dispatch site — the lying twin is therefore not the same exit.
    assert truthful_resolution.raise_occurrence_coordinate != (
        lying_resolution.raise_occurrence_coordinate
    )


def test_lying_expected_type_substitution_does_not_authenticate_nameless_halt() -> None:
    """If only the boundary type is substituted into a nameless halt, stay undischarged."""
    boundary_type = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("TypeError")],
    )
    # Nameless undischarged cannot be upgraded by stuffing the boundary type.
    nameless = NativeOperationResolutionV1.undischarged(
        "native operation exception identity unproven"
    )
    assert not nameless.has_authenticated_exception_type
    with pytest.raises(SugarNotWritten, match="identity unproven"):
        nameless.project(source_node=_Site())
    # Constructing exceptional requires *both* coordinates at mint time — there
    # is no door that accepts type-only from the boundary.
    with pytest.raises(ValueError, match="authenticated type and occurrence"):
        NativeOperationResolutionV1(
            kind="exceptional",
            exception_type_coordinate=boundary_type,
            raise_occurrence_coordinate=None,
        )


# ---------------------------------------------------------------------------
# Method wiring: producer / consumer names
# ---------------------------------------------------------------------------


def test_producer_and_consumer_methods_are_the_named_seams() -> None:
    """Document the exact methods this law owns."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        _NATIVE_OPERATION_PROJECTORS,
    )

    assert hasattr(UnaryOpSugar, "desugar")
    assert not hasattr(FloorValue, "unary_truth")
    assert hasattr(FloorValue, "truth")
    assert callable(getattr(TrueBoolLiteralSugar(_Site()), "negate"))
    assert callable(getattr(FalseBoolLiteralSugar(_Site()), "negate"))
    # ``not`` on a parameter mints no carrier, so it has no projector.
    assert "unary_truth" not in _NATIVE_OPERATION_PROJECTORS

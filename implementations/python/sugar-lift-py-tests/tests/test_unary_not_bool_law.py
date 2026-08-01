"""UnaryOp ``not``: ``result = not value`` is ``not bool(value)``, always a bool.

Python semantic law made constructible here (distinct from BoolOp #6595):

  a. ``bool(value)`` MAY halt — truth dispatch can raise a source-authenticated
     exception type (synthetic Floor; pandas ``not NA`` / ``not obj1`` stay
     undischarged until an NDFrame/NAType truth floor exists).
  b. Only the completed truth face is negated — a halt has no bool to flip.
  c. The result is always ``True``/``False``, never the operand.
  d. Exception type originates in the truth floor, never from an enclosing
     ``pytest.raises`` expectation.

Producer method: ``UnaryOpSugar.desugar`` (op_kind ``Not``).
Floor consumer methods: ``FloorValue.unary_truth`` (carrier adapter),
``FloorValue.truth``, and bool-literal ``negate``.
Carrier: existing ``NativeOperationExitCarrierV1`` / three-way resolution.

Corpus coordinates (pandas 3.0.3, verified by line content, not by path alone):

  - ``tests/scalar/test_na_scalar.py:48`` — ``not NA`` under ``pytest.raises(TypeError)``
  - ``tests/generic/test_generic.py:156`` — ``not obj1`` under ``pytest.raises(ValueError)``
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    NativeOperationResolutionV1,
    source_coordinate,
)
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import FloorValue, NoneValue, SymbolicValue, TermValue
from sugar_lift_py_tests.floor.ground_exit import ground_type_error
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, make_var, str_const
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted, outcome_to_exitset
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import UnaryOp
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
NA_SITE_SHA256 = "e46445908318d803ea24ac6c8f09ba2347de6fc31e12f2459555a1ba1b15e703"
GENERIC_SITE_SHA256 = (
    "cbc5383e8e1545537baedca85a6c62a487d3bea6942bb56e5e0c7479dd2f188d"
)


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
class _ValueSugar(Sugar):
    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)


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
        return Complete(self.payload)

    def to_term(self, *, owner: str):
        del owner
        return ctor("python:probe_operand_truth", [])


def _not_sugar(value) -> Outcome:
    return UnaryOpSugar("Not", _ValueSugar(value), _Site()).desugar(None)


def _completed_value(outcome):
    exits = outcome_to_exitset(outcome).exits
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


def _carrier() -> tuple[NativeOperationExitCarrierV1, FormalParameterCoordinateV1]:
    node = _unary_node()
    formal = _formal(node)
    outcome = UnaryOpSugar(
        "Not",
        _ValueSugar(SymbolicValue(make_var("value"), formal)),
        node.fragment,
    ).desugar(None)
    assert isinstance(outcome, NativeOperationExitCarrierV1)
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


def test_corpus_not_sites_remain_named_refusals_without_operand_type() -> None:
    """No admissible Floor for NAType/Series at the bare name yet — stay loud.

    Missing Floor law: authenticated ``NAType.__bool__`` / ``NDFrame.__bool__``
    that mints TypeError / ValueError from the real raise body, not from the
    surrounding ``pytest.raises``.  Until that Floor exists, the enrolled pair
    is undischarged (named refusal), which is the honest third value.
    """
    corpus = authenticated_pandas_corpus()
    cases = (
        ("tests/scalar/test_na_scalar.py", 48, "not"),
        ("tests/generic/test_generic.py", 156, "not"),
    )
    for rel, line, operator in cases:
        path = corpus.root / rel
        source = path.read_text(encoding="utf-8")
        source_cid = blake3_512_of(source.encode("utf-8"))
        tree = SourceFile(
            (source, str(path), source_cid),
            construction_context=TreeConstructionContextV1.for_source_call_construction(),
        )
        matches = tuple(
            node
            for node in tree.nodes()
            if isinstance(node, UnaryOp) and node.line_col_span().start_line == line
        )
        assert len(matches) == 1, (rel, line)
        with pytest.raises(SugarNotWritten) as raised:
            matches[0].sugar().desugar(None)
        refusal = raised.value
        assert refusal.owner == "unary_operation_exception_floor"
        assert refusal.observed == f"SymbolicValue {operator}"
        assert "TypeError" not in str(refusal)
        assert "ValueError" not in str(refusal)


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
    exits = outcome_to_exitset(outcome).exits
    assert len(exits) == 1
    # RaiseValue rides as Complete(RaiseValue) then ExitSet.halted on projection,
    # or as a Halted face — either way the effect is TypeError and not flipped.
    face = exits[0]
    if isinstance(face, Completed):
        from sugar_lift_py_tests.floor import RaiseValue

        assert isinstance(face.value, RaiseValue)
        assert face.value.effect.exception_name == "TypeError"
        assert face.value.effect.exception_type_coordinate == _identity('TypeError')
    else:
        assert isinstance(face, Halted)
        assert face.effect.exception_name == "TypeError"
        assert face.effect.exception_type_coordinate == _identity('TypeError')


def test_truthful_exceptional_face_carries_floor_type_not_boundary() -> None:
    """Face (a)+(d): TypeError coordinate comes from the truth floor."""
    outcome = _not_sugar(_AmbiguousTruth())
    exits = outcome_to_exitset(outcome).exits
    face = exits[0]
    if isinstance(face, Completed):
        effect = face.value.effect
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
# Formal carrier: unary_truth + negate continuation
# ---------------------------------------------------------------------------


def test_formal_not_defers_to_native_operation_carrier() -> None:
    carrier, formal = _carrier()
    assert carrier.demand.operator == "unary_truth"
    assert len(carrier.demand.operand_terms) == 2
    assert carrier.demand.operand_coordinate_cids[0] == formal.coordinate_cid
    assert carrier.demand.operand_coordinate_cids[1] is None


def test_formal_not_completes_to_bool_after_discharge() -> None:
    carrier, formal = _carrier()
    # Continuations include negate from UnaryOpSugar.desugar.
    exits = carrier.discharge({formal.coordinate_cid: TermValue(0)})
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    assert isinstance(exits.exits[0].value, TrueBoolLiteralSugar)

    exits = carrier.discharge({formal.coordinate_cid: TermValue(7)})
    assert isinstance(exits.exits[0].value, FalseBoolLiteralSugar)


def test_formal_not_halt_bypasses_negate_continuation() -> None:
    carrier, formal = _carrier()
    exits = carrier.discharge({formal.coordinate_cid: _AmbiguousTruth()})
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Halted)
    # Resolution.project keeps the authenticated type coordinate; name may be
    # omitted on the carrier path (type identity is the authority).
    assert exits.exits[0].effect.exception_type_coordinate == ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("TypeError")],
    )
    # Occurrence is the operation site, not a fabricated boundary locus.
    assert isinstance(exits.exits[0].effect.occurrence_id, str) and ":" in exits.exits[0].effect.occurrence_id, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {exits.exits[0].effect.occurrence_id!r}"
    )


def test_undecided_actual_stays_named_refusal_on_discharge() -> None:
    carrier, formal = _carrier()
    with pytest.raises(SugarNotWritten) as caught:
        carrier.discharge(
            {formal.coordinate_cid: SymbolicValue(make_var("still_unknown"))}
        )
    # Undecided actual has no unary_truth / truth completion — loud, not Halted.
    assert caught.value.owner == "unary_operation_exception_floor"
    assert "TypeError" not in str(caught.value)


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
    assert isinstance(lying_truth, Complete)
    # The lying floor's truth is the operand — UnaryOp must not accept that as
    # the final ``not`` result.  Real desugar on a value whose truth is non-bool
    # and non-RaiseValue hits negate on a TermValue → construction panic (no
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
    truthful_exits = outcome_to_exitset(truthful_outcome).exits
    face = truthful_exits[0]
    if isinstance(face, Completed):
        truthful_effect = face.value.effect
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

    operation_origin = source_coordinate(fragment)
    truthful_resolution = NativeOperationResolutionV1.exceptional(
        exception_type_coordinate=floor_type,
        operation_occurrence=operation_origin,
    )
    # Lying: same type coordinate content, but occurrence is the *assertion*
    # site (boundary), not the UnaryOp / truth raise occurrence.
    boundary_origin = type(operation_origin)(
        operation_origin.source_cid,
        operation_origin.start_line + 10,
        operation_origin.start_col,
        operation_origin.end_line + 10,
        operation_origin.end_col,
    )
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
    """Document the exact methods this PR owns (before any further edit)."""
    assert hasattr(UnaryOpSugar, "desugar")
    assert hasattr(FloorValue, "unary_truth")
    assert hasattr(FloorValue, "truth")
    assert callable(getattr(TrueBoolLiteralSugar(_Site()), "negate"))
    assert callable(getattr(FalseBoolLiteralSugar(_Site()), "negate"))
    # Adapter is a thin carrier door onto truth.
    probe = TermValue(0)
    assert probe.unary_truth(NoneValue(), _Site()) == probe.truth(_Site())

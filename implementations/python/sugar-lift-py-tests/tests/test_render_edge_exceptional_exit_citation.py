"""Render-edge fabrication law for exceptional-exit FOL emission.

LAW OF ONE (governs this cluster)
=================================
Exactly one way to do anything:

  AST TREE SHADOWS  ->  temporal rewrite and tree modification
  SUGAR             ->  meaning

That is it. NO OTHER MECHANISM.

Exception IDENTITY is meaning. It must come from Sugar / the tree — never
from a Python default that substitutes a literal at the boundary.
``or "reraise"``, ``x if c else "reraise"``, and field values equal to those
placeholders are second mechanisms inventing meaning outside the tree.
Doctrine: throwing is HONORABLE (code not written yet). The SIN is half-writing
an answer outside the tree. Fix = throw, never substitute a placeholder.

A nameless face must not reach FOL as a citable ``py.exceptional_exit``.
A face whose exception_name *is* a fabricated placeholder must not either.
Authenticated bare re-raise re-emits the in-flight effect's real identity
(from the tree); it does not mint the string ``"reraise"``.

GATE: truthful twin cites under real evidence; lying twins (nameless face,
fabricated-name face, missing citation) MUST FAIL.

LAW_OF_ONE AUDITOR BLIND SPOT
=============================
``tests/law_of_one_auditor.py`` + ``law_of_one_evidence.py`` audit SourceFile
owner paths, privacy closure, projection closure, and protocol zero-work.
They do **not** walk floor render edges, fabricated-meaning literal invention,
or exceptional-exit FOL emission. This module owns recognition of that class.
When the LAW_OF_ONE auditor gains a floor-render / meaning-invention axis that
names live offenders of this class, retire the blind-spot probe below.

Retirement path for the production denylist
(``FABRICATED_EXCEPTIONAL_EXIT_MEANING_LITERALS``): promote exception_name to a
typed constructor that can only be built from tree/Sugar testimony so the
placeholder strings become unrepresentable as identity.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.raise_value import (
    FABRICATED_EXCEPTIONAL_EXIT_MEANING_LITERALS,
    RaiseValue,
    _exceptional_exit_formula,
    _exceptional_exit_term,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor, str_const


_SHA = "a" * 64
_LOCUS = "pkg/mod.py:12:4"

_RAISE_VALUE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "sugar_lift_py_tests"
    / "floor"
    / "raise_value.py"
)


def _named_cited_effect(**overrides) -> RaiseEffect:
    fields = dict(
        exception_name="ValueError",
        blame=_LOCUS,
        source_sha256=_SHA,
        occurrence=_LOCUS,
    )
    fields.update(overrides)
    return RaiseEffect(occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_render_edge_exceptional_exit_citation.py:95:0'))


def _coordinate_cited_effect(**overrides) -> RaiseEffect:
    identity = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("TypeError")],
    )
    fields = dict(
        exception_type_coordinate=identity,
        blame=_LOCUS,
        source_sha256=_SHA,
        occurrence=_LOCUS,
    )
    fields.update(overrides)
    return RaiseEffect(occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_render_edge_exceptional_exit_citation.py:80:0'))


def _is_fabricated_constant(node: ast.AST) -> str | None:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in FABRICATED_EXCEPTIONAL_EXIT_MEANING_LITERALS
    ):
        return node.value
    return None


def fabricated_meaning_offenders(source: str, *, path: str = "<planted>") -> list[str]:
    """AST tooth: second-mechanism defaults that invent exceptional-exit meaning.

    LAW OF ONE: meaning comes from Sugar/the tree. Recognized shapes:
    - BoolOp ``or`` with a fabricated Constant (historical ``x or "reraise"``)
    - IfExp with a fabricated Constant on either branch
      (``x if c else "reraise"`` / ``"reraise" if c else x``)

    Retirement: when production types make these spellings unrepresentable as
    identity, this scanner becomes a pure reintroduction detector and may stay
    as a membrane over open Python source, or retire if the denylist does.
    """
    tree = ast.parse(source, filename=path)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            for operand in node.values:
                lit = _is_fabricated_constant(operand)
                if lit is not None:
                    offenders.append(
                        f"{path}:{getattr(node, 'lineno', 0)}: "
                        f"or {lit!r} invents exceptional-exit meaning"
                    )
        elif isinstance(node, ast.IfExp):
            for branch, label in ((node.body, "if-body"), (node.orelse, "if-else")):
                lit = _is_fabricated_constant(branch)
                if lit is not None:
                    offenders.append(
                        f"{path}:{getattr(node, 'lineno', 0)}: "
                        f"{label} {lit!r} invents exceptional-exit meaning"
                    )
    return offenders


# Back-compat alias used by older call sites in this module's history.
or_literal_meaning_offenders = fabricated_meaning_offenders


# ---------------------------------------------------------------------------
# LAW_OF_ONE auditor cannot see this sin — real probe, no tautological R pin
# ---------------------------------------------------------------------------


def test_law_of_one_auditor_cannot_see_render_edge_fabrication() -> None:
    """Probe: the product LAW_OF_ONE auditor still has no render-edge axis.

    Fails when auditor/evidence text gains the vocabulary of this class
    (exceptional_exit / reraise / RaiseValue on the evidence types) — that
    is the signal the stronger substrate arrived and this note can retire.
    There is no hard-coded R=1; the probe is the absence of those markers.
    """
    auditor = Path(__file__).resolve().parents[4] / "tests" / "law_of_one_auditor.py"
    evidence = Path(__file__).resolve().parents[4] / "tests" / "law_of_one_evidence.py"
    assert auditor.is_file(), auditor
    assert evidence.is_file(), evidence

    auditor_text = auditor.read_text(encoding="utf-8")
    evidence_text = evidence.read_text(encoding="utf-8")

    # Strings that would mean the auditor already owns *this* axis.
    assert "reraise" not in auditor_text, (
        "law_of_one_auditor mentions reraise — re-check whether it now owns "
        "render-edge fabrication and retire this module's blind-spot claim"
    )
    assert "exceptional_exit" not in auditor_text
    assert "or \"reraise\"" not in auditor_text
    assert "source-sha256" not in auditor_text
    assert "RenderEdge" not in evidence_text
    assert "exceptional_exit" not in evidence_text
    assert "RaiseValue" not in evidence_text
    assert "FABRICATED_EXCEPTIONAL_EXIT" not in auditor_text


# ---------------------------------------------------------------------------
# AST tooth: second-mechanism fabricated-meaning literals
# ---------------------------------------------------------------------------


def test_ast_tooth_lying_twin_or_reraise_is_visible() -> None:
    """Planted BoolOp ``or`` second mechanism must be recognized."""
    planted = '''
def _exceptional_exit_term(effect):
    name = effect.exception_name or "reraise"
    cite = effect.source_sha256 or "unavailable"
    locus = effect.blame or "<unknown raise locus>"
    return name, cite, locus
'''
    offenders = fabricated_meaning_offenders(planted, path="planted.py")
    assert len(offenders) == 3, offenders
    assert any("reraise" in row for row in offenders)
    assert any("unavailable" in row for row in offenders)
    assert any("unknown raise locus" in row for row in offenders)


def test_ast_tooth_lying_twin_ifexp_reraise_is_visible() -> None:
    """Planted IfExp default (if/else form of the same sin) must be recognized.

    The historical AST tooth only saw BoolOp ``or``. Reintroduction via
    ``x if c else "reraise"`` is the same second mechanism in different clothes.
    """
    planted = '''
def _exceptional_exit_term(effect):
    name = effect.exception_name if effect.exception_name is not None else "reraise"
    cite = "unavailable" if effect.source_sha256 is None else effect.source_sha256
    locus = effect.blame if effect.blame is not None else "<unknown raise locus>"
    return name, cite, locus
'''
    offenders = fabricated_meaning_offenders(planted, path="planted_ifexp.py")
    assert len(offenders) == 3, offenders
    assert any("reraise" in row for row in offenders)
    assert any("unavailable" in row for row in offenders)
    assert any("unknown raise locus" in row for row in offenders)


def test_ast_tooth_truthful_raise_value_has_zero_fabricated_meaning_defaults() -> None:
    """Production emission door: R=0 for fabricated-meaning default shapes."""
    source = _RAISE_VALUE_PATH.read_text(encoding="utf-8")
    offenders = fabricated_meaning_offenders(
        source, path=str(_RAISE_VALUE_PATH)
    )
    assert offenders == [], (
        "render-edge emission invents meaning via default literal; "
        "Law of One: identity comes from the tree only. Offenders:\n"
        + "\n".join(offenders)
    )


def test_ast_tooth_does_not_flag_boolean_existence_ors() -> None:
    """``name is not None or coord is not None`` is existence, not meaning."""
    clean = '''
def has_identity(effect):
    return (
        effect.exception_name is not None
        or effect.exception_type_coordinate is not None
    )
'''
    assert fabricated_meaning_offenders(clean) == []


def test_ast_tooth_does_not_flag_ifexp_without_fabricated_literal() -> None:
    clean = '''
def pick(a, b, c):
    return a if c else b
'''
    assert fabricated_meaning_offenders(clean) == []


# ---------------------------------------------------------------------------
# Truthful twin: authenticated identity + citation reach FOL
# ---------------------------------------------------------------------------


def test_truthful_named_face_emits_cited_exceptional_exit() -> None:
    """Named raise with real locus + source hash is a citable exit."""
    effect = _named_cited_effect()
    term = _exceptional_exit_term(effect)

    assert term == ctor(
        "py.exceptional_exit",
        [
            str_const("ValueError"),
            str_const(f"{_LOCUS}#source-sha256={_SHA}"),
        ],
    )


def test_truthful_type_coordinate_face_emits_cited_exceptional_exit() -> None:
    """Type-coordinate identity (no spelling name) is still authenticated."""
    effect = _coordinate_cited_effect()
    term = _exceptional_exit_term(effect)

    assert term.args[0] == effect.exception_type_coordinate
    assert term.args[1] == str_const(f"{_LOCUS}#source-sha256={_SHA}")


def test_truthful_raise_value_post_contribution_is_the_cited_formula() -> None:
    effect = _named_cited_effect()
    posts = RaiseValue(effect).post_contribution()

    assert len(posts) == 1
    # Same term path as the direct projector — no second spelling of identity.
    assert posts[0] == _exceptional_exit_formula(effect)


# ---------------------------------------------------------------------------
# Lying twin: nameless / uncited / fabricated-name faces MUST NOT emit
# ---------------------------------------------------------------------------


def test_nameless_face_cannot_reach_fol_emission() -> None:
    """THE GATE: nameless face rendering as a cited exit must FAIL.

    Before the fix this emitted:
      py.exceptional_exit(str_const("reraise"),
                          "<unknown raise locus>#source-sha256=unavailable")
    which is indistinguishable from a genuinely cited exit.
    """
    nameless = RaiseEffect(occurrence=AuthenticatedRaiseLocus.of('implementations/python/sugar-lift-py-tests/tests/test_render_edge_exceptional_exit_citation.py:305:0'))

    with pytest.raises(ConstructionPanic) as raised:
        _exceptional_exit_term(nameless)

    info = raised.value.info
    assert info.owner == "RaiseValue.exceptional_exit_term"
    assert "neither" in info.observed
    assert "exception_name" in info.observed
    assert "exception_type_coordinate" in info.observed
    assert "reraise" in info.fix


def test_nameless_raise_value_post_contribution_stays_loud() -> None:
    """post_contribution is the same door — nameless cannot soft-emit."""
    with pytest.raises(ConstructionPanic) as raised:
        RaiseValue(RaiseEffect(occurrence=AuthenticatedRaiseLocus.of(_LOCUS), blame=_LOCUS)).post_contribution()
    assert raised.value.info.owner == "RaiseValue.exceptional_exit_term"


def test_name_without_source_sha_cannot_cite_unavailable() -> None:
    """Placeholder ``#source-sha256=unavailable`` is absent evidence, not a cite."""
    effect = RaiseEffect(occurrence=AuthenticatedRaiseLocus.of(_LOCUS), exception_name='ValueError', blame=_LOCUS, source_sha256=None)

    with pytest.raises(ConstructionPanic) as raised:
        _exceptional_exit_term(effect)

    info = raised.value.info
    assert info.owner == "RaiseValue.exceptional_exit_term"
    assert "source_sha256" in info.observed
    assert "unavailable" in info.fix


def test_name_without_blame_cannot_cite_unknown_locus() -> None:
    """Placeholder ``<unknown raise locus>`` is not a re-readable citation."""
    effect = RaiseEffect(occurrence=AuthenticatedRaiseLocus.of(None), exception_name='ValueError', blame=None, source_sha256=_SHA)

    with pytest.raises(ConstructionPanic) as raised:
        _exceptional_exit_term(effect)

    info = raised.value.info
    assert info.owner == "RaiseValue.exceptional_exit_term"
    assert "blame" in info.observed
    assert "unknown raise locus" in info.fix


def test_fabricated_reraise_string_is_not_authenticated_bare_raise() -> None:
    """Nameless face with locus+sha (historical path that became 'reraise')."""
    effect = RaiseEffect(occurrence=AuthenticatedRaiseLocus.of(_LOCUS), blame=_LOCUS, source_sha256=_SHA)

    with pytest.raises(ConstructionPanic) as raised:
        _exceptional_exit_term(effect)

    info = raised.value.info
    assert info.owner == "RaiseValue.exceptional_exit_term"
    assert _LOCUS in info.blame
    assert "neither" in info.observed


def test_exception_name_reraise_placeholder_cannot_reach_fol() -> None:
    """LYING TWIN: relocating the sin onto the field must still be red.

    A face with exception_name='reraise' plus real blame/sha used to green a
    citable exit after the first refuse-placeholders shot. Fabricated
    identity is not authenticated identity.
    """
    effect = RaiseEffect(occurrence=AuthenticatedRaiseLocus.of(_LOCUS), exception_name='reraise', blame=_LOCUS, source_sha256=_SHA)

    with pytest.raises(ConstructionPanic) as raised:
        _exceptional_exit_term(effect)

    info = raised.value.info
    assert info.owner == "RaiseValue.exceptional_exit_term"
    assert "fabricated" in info.observed
    assert "reraise" in info.observed


@pytest.mark.parametrize(
    "placeholder",
    sorted(FABRICATED_EXCEPTIONAL_EXIT_MEANING_LITERALS),
)
def test_every_fabricated_meaning_literal_as_name_is_loud(placeholder: str) -> None:
    """Every denylist member as exception_name is an offender class, not a name."""
    effect = RaiseEffect(occurrence=AuthenticatedRaiseLocus.of(_LOCUS), exception_name=placeholder, blame=_LOCUS, source_sha256=_SHA)
    with pytest.raises(ConstructionPanic) as raised:
        _exceptional_exit_term(effect)
    assert placeholder in raised.value.info.observed
    assert raised.value.info.owner == "RaiseValue.exceptional_exit_term"


def test_empty_exception_name_cannot_reach_fol() -> None:
    """Empty spelling is not tree-authenticated identity."""
    effect = RaiseEffect(occurrence=AuthenticatedRaiseLocus.of(_LOCUS), exception_name='', blame=_LOCUS, source_sha256=_SHA)
    with pytest.raises(ConstructionPanic) as raised:
        _exceptional_exit_term(effect)
    assert "empty" in raised.value.info.observed
    assert raised.value.info.owner == "RaiseValue.exceptional_exit_term"


def test_kwarg_fabricated_name_cannot_bypass_face_check() -> None:
    """``_exceptional_exit_term(..., exception_name='reraise')`` is the same mouth."""
    effect = _coordinate_cited_effect()
    with pytest.raises(ConstructionPanic) as raised:
        _exceptional_exit_term(effect, exception_name="reraise")
    assert "reraise" in raised.value.info.observed

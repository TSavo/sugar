"""Render-edge fabrication law for exceptional-exit FOL emission.

LAW OF ONE (governs this cluster)
=================================
Exactly one way to do anything:

  AST TREE SHADOWS  ->  temporal rewrite and tree modification
  SUGAR             ->  meaning

That is it. NO OTHER MECHANISM.

Exception IDENTITY is meaning. It must come from Sugar / the tree — never
from a Python ``or`` fallback that substitutes a literal at the boundary.
``or "reraise"`` and ``or 'unavailable'`` are a second mechanism inventing
meaning outside the tree. Doctrine: throwing is HONORABLE (code not written
yet). The SIN is half-writing an answer outside the tree. Fix = throw, never
substitute a placeholder.

A nameless face must not reach FOL as a citable ``py.exceptional_exit``.
Authenticated bare re-raise re-emits the in-flight effect's real identity
(from the tree); it does not mint the string ``"reraise"``.

GATE: truthful twin cites under real evidence; lying twin (nameless face
rendered as a cited exit) MUST FAIL.

LAW_OF_ONE AUDITOR BLIND SPOT — SAY THIS LOUDLY
===============================================
``tests/law_of_one_auditor.py`` + ``law_of_one_evidence.py`` audit SourceFile
owner paths, privacy closure, projection closure, and protocol zero-work.
They do **not** walk floor render edges, BoolOp ``or``-literal meaning
invention, or exceptional-exit FOL emission.

  R_law_of_one_auditor_cannot_see_render_edge_fabrication = 1

This module is the instrument that can see the sin: a runtime twin for
nameless emission, plus an AST tooth for the second-mechanism shape
(``x or "reraise"`` / ``x or 'unavailable'``) on the emission door.
When the LAW_OF_ONE auditor gains a floor-render axis, retire this note.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.raise_value import (
    RaiseValue,
    _exceptional_exit_formula,
    _exceptional_exit_term,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor, str_const


_SHA = "a" * 64
_LOCUS = "pkg/mod.py:12:4"

# Literals that invent exceptional-exit meaning at the render edge.
# Identity / citation evidence must come from the tree, never these strings.
_FABRICATED_MEANING_LITERALS = frozenset(
    {
        "reraise",
        "unavailable",
        "<unknown raise locus>",
    }
)

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
    return RaiseEffect(**fields)


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
    return RaiseEffect(**fields)


def or_literal_meaning_offenders(source: str, *, path: str = "<planted>") -> list[str]:
    """AST tooth: ``or`` with a fabricated-meaning string is a second mechanism.

    LAW OF ONE: meaning comes from Sugar/the tree. A BoolOp ``or`` whose
    right-hand (or any operand after the first) is a Constant in the
    fabricated set invents exception identity / citation at the boundary.
    """
    tree = ast.parse(source, filename=path)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.Or):
            continue
        for operand in node.values:
            if (
                isinstance(operand, ast.Constant)
                and isinstance(operand.value, str)
                and operand.value in _FABRICATED_MEANING_LITERALS
            ):
                offenders.append(
                    f"{path}:{getattr(node, 'lineno', 0)}: "
                    f"or {operand.value!r} invents exceptional-exit meaning"
                )
    return offenders


# ---------------------------------------------------------------------------
# LAW_OF_ONE auditor cannot see this sin — pin the blind spot
# ---------------------------------------------------------------------------


def test_law_of_one_auditor_cannot_see_render_edge_fabrication() -> None:
    """LOUD: the independent LAW_OF_ONE product auditor is blind to this axis.

    Its evidence contract (owner path / privacy / projection / zero-work)
    has no field for floor FOL emission or ``or``-literal meaning invention.
    This tooth owns that recognition until a stronger substrate exists.
    """
    auditor = Path(__file__).resolve().parents[4] / "tests" / "law_of_one_auditor.py"
    evidence = Path(__file__).resolve().parents[4] / "tests" / "law_of_one_evidence.py"
    assert auditor.is_file(), auditor
    assert evidence.is_file(), evidence

    auditor_text = auditor.read_text(encoding="utf-8")
    evidence_text = evidence.read_text(encoding="utf-8")

    # Strings that would mean the auditor already owns *this* axis.
    # (Other reds may say "unavailable" about unrelated product gaps.)
    assert "reraise" not in auditor_text
    assert "exceptional_exit" not in auditor_text
    assert "or \"reraise\"" not in auditor_text
    assert "source-sha256" not in auditor_text
    # Evidence types are SourceFile-product only — no render-edge axis.
    assert "RenderEdge" not in evidence_text
    assert "exceptional_exit" not in evidence_text
    assert "RaiseValue" not in evidence_text

    # Receipt axis the existing auditor does not measure. R stays 1 until
    # law_of_one_auditor grows a floor-render / meaning-invention axis.
    R_law_of_one_auditor_cannot_see_render_edge_fabrication = 1
    assert R_law_of_one_auditor_cannot_see_render_edge_fabrication == 1, (
        "LAW_OF_ONE auditor still cannot see render-edge fabrication; "
        "this module remains the recognizing instrument"
    )


# ---------------------------------------------------------------------------
# AST tooth: second-mechanism ``or``-literal meaning (Law of One shape)
# ---------------------------------------------------------------------------


def test_ast_tooth_lying_twin_or_reraise_is_visible() -> None:
    """Planted second mechanism must be recognized — the historical sin shape."""
    planted = '''
def _exceptional_exit_term(effect):
    name = effect.exception_name or "reraise"
    cite = effect.source_sha256 or "unavailable"
    locus = effect.blame or "<unknown raise locus>"
    return name, cite, locus
'''
    offenders = or_literal_meaning_offenders(planted, path="planted.py")
    assert len(offenders) == 3, offenders
    assert any("reraise" in row for row in offenders)
    assert any("unavailable" in row for row in offenders)
    assert any("unknown raise locus" in row for row in offenders)


def test_ast_tooth_truthful_raise_value_has_zero_or_literal_meaning() -> None:
    """Production emission door: R=0 for fabricated-meaning ``or`` literals."""
    source = _RAISE_VALUE_PATH.read_text(encoding="utf-8")
    offenders = or_literal_meaning_offenders(
        source, path=str(_RAISE_VALUE_PATH)
    )
    assert offenders == [], (
        "render-edge emission invents meaning via or-literal; "
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
    assert or_literal_meaning_offenders(clean) == []


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
# Lying twin: nameless / uncited faces MUST NOT emit a citable exit
# ---------------------------------------------------------------------------


def test_nameless_face_cannot_reach_fol_emission() -> None:
    """THE GATE: nameless face rendering as a cited exit must FAIL.

    Before the fix this emitted:
      py.exceptional_exit(str_const("reraise"),
                          "<unknown raise locus>#source-sha256=unavailable")
    which is indistinguishable from a genuinely cited exit.
    """
    nameless = RaiseEffect()

    with pytest.raises(ConstructionPanic) as raised:
        _exceptional_exit_term(nameless)

    info = raised.value.info
    assert "neither" in info.observed or "no authenticated" in info.observed.lower()
    # Must not have produced a greened FOL term under a made-up name.
    with pytest.raises(ConstructionPanic):
        term = _exceptional_exit_term(nameless)
        assert term.args[0] == str_const("reraise")


def test_nameless_raise_value_post_contribution_stays_loud() -> None:
    """post_contribution is the same door — nameless cannot soft-emit."""
    with pytest.raises(ConstructionPanic):
        RaiseValue(RaiseEffect(blame=_LOCUS)).post_contribution()


def test_name_without_source_sha_cannot_cite_unavailable() -> None:
    """Placeholder ``#source-sha256=unavailable`` is absent evidence, not a cite."""
    effect = RaiseEffect(
        exception_name="ValueError",
        blame=_LOCUS,
        source_sha256=None,
    )

    with pytest.raises(ConstructionPanic) as raised:
        _exceptional_exit_term(effect)

    text = str(raised.value)
    assert "unavailable" not in text or "source" in text.lower()
    with pytest.raises(ConstructionPanic):
        term = _exceptional_exit_term(effect)
        assert "unavailable" in str(term.args[1])


def test_name_without_blame_cannot_cite_unknown_locus() -> None:
    """Placeholder ``<unknown raise locus>`` is not a re-readable citation."""
    effect = RaiseEffect(
        exception_name="ValueError",
        blame=None,
        source_sha256=_SHA,
    )

    with pytest.raises(ConstructionPanic) as raised:
        _exceptional_exit_term(effect)

    with pytest.raises(ConstructionPanic):
        term = _exceptional_exit_term(effect)
        assert "unknown raise locus" in str(term.args[1])


def test_fabricated_reraise_string_is_not_authenticated_bare_raise() -> None:
    """Bare re-raise re-emits the in-flight effect; it does not mint 'reraise'.

    A face whose only 'identity' would have been the render-edge default
    string stays unrepresentable at FOL emission.
    """
    # No name, no type coordinate — the historical path that became "reraise".
    effect = RaiseEffect(blame=_LOCUS, source_sha256=_SHA)

    with pytest.raises(ConstructionPanic) as raised:
        _exceptional_exit_term(effect)

    info = raised.value.info
    # Throw carries the blame coordinate — honorable named refusal.
    assert _LOCUS in info.blame or _LOCUS in str(raised.value)
    assert info.owner  # named owner, not an AttributeError

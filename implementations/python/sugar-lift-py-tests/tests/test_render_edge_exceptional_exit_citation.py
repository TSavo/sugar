"""Render-edge fabrication law for exceptional-exit FOL emission.

Doctrine: throwing is honorable — it means we have not written the code yet.
The sin is half-writing an answer outside the tree. At the render edge,
`RaiseValue` / `_exceptional_exit_term` must never invent:

  - exception identity ``"reraise"`` when name and type coordinate are absent
  - source citation ``#source-sha256=unavailable`` when the hash is absent
  - locus ``<unknown raise locus>`` when blame is absent

A nameless face must not reach FOL as a citable ``py.exceptional_exit``.
Authenticated bare re-raise re-emits the in-flight effect's real identity
(from the tree); it does not mint the string ``"reraise"``.

GATE: truthful twin cites under real evidence; lying twin (nameless face
rendered as a cited exit) MUST FAIL.
"""

from __future__ import annotations

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

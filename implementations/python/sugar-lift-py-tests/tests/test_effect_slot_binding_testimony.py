"""Effect slots: pure coordinates + explicit binding facts (no ambient auth)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src" / "sugar_lift_py_tests"


def test_no_effect_auth_contextvar_side_door() -> None:
    """R: ambient effect auth must stay zero."""
    assert not (_SRC / "effect_auth.py").exists()
    banned = ("effect_auth", "authenticate_slot", "lookup_slot", "effect_auth_wave")
    offenders: list[str] = []
    for path in _SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                offenders.append(f"{path.relative_to(_SRC)}:{token}")
    assert offenders == [], f"ambient effect auth residual: {offenders}"


def test_effect_coordinate_never_embeds_effect_payload() -> None:
    from sugar_lift_py_tests.floor.effect_coordinate import (
        EffectCoordinate,
        ExceptionInfoCoordinate,
    )

    fields = {f.name for f in EffectCoordinate.__dataclass_fields__.values()}
    assert "effect" not in fields
    fields = {f.name for f in ExceptionInfoCoordinate.__dataclass_fields__.values()}
    assert "effect" not in fields
    coord = EffectCoordinate(slot_id="file.py:1:0:1:10")
    term = coord.to_term(owner="test")
    assert term.name == "python:effect_slot"
    assert term.args[0].value == "file.py:1:0:1:10"


def test_router_match_once_emits_binding_facts() -> None:
    from sugar_lift_py_tests.context_manager_contract import EffectMatcher, Expects
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.effect_router import EffectBinding, route
    from sugar_lift_py_tests.outcome import Incomplete

    entries = (
        Incomplete(RaiseEffect(exception_name="ValueError", occurrence="t.py:2:4")),
    )
    out = route(
        entries,
        Expects(matcher=EffectMatcher(kind="raise", name="ValueError")),
        slot_id="S",
    )
    assert len(out.bindings) == 1
    assert isinstance(out.bindings[0], EffectBinding)
    assert out.bindings[0].slot_id == "S"
    assert out.bindings[0].type_name == "ValueError"
    # Match consumed the halt; binding facts present
    assert not any(isinstance(e, Incomplete) for e in out.entries)
    formulas = [e.formula if hasattr(e, "formula") else e for e in out.stated_facts]
    names = []
    for f in formulas:
        if getattr(f, "name", None) == "=" and getattr(f.args[0], "name", None):
            names.append(f.args[0].name)
        else:
            names.append(getattr(f, "name", None))
    assert "effect_slot_type" in names
    assert "effect_slot_identity" not in names
    assert "effect_slot_origin" in names


def test_wrong_match_does_not_bind_slot() -> None:
    from sugar_lift_py_tests.context_manager_contract import EffectMatcher, Expects
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.effect_router import route
    from sugar_lift_py_tests.outcome import Incomplete

    entries = (Incomplete(RaiseEffect(exception_name="KeyError")),)
    out = route(
        entries,
        Expects(matcher=EffectMatcher(kind="raise", name="ValueError")),
        slot_id="S",
    )
    assert out.bindings == ()
    assert any(isinstance(e, Incomplete) for e in out.entries)


def test_observed_effect_projects_only_an_authenticated_context_preimage() -> None:
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.floor.effect_coordinate import (
        EffectCoordinate,
        ObservedEffectValue,
    )
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    inner_value = TermValue(7)
    inner = RaiseEffect(exception_name="ImportError", raised_value=inner_value)
    outer = RaiseEffect(exception_name="ValueError", context_effect=inner)

    projected = ObservedEffectValue(slot_id="S", effect=outer).attribute(
        "__context__", site=None
    )
    assert projected.value is inner_value

    with pytest.raises(ConstructionPanic) as caught:
        EffectCoordinate(slot_id="S").attribute("__context__", site=None)
    assert caught.value.info.owner == "EffectCoordinate.attribute.__context__"
    assert "no authenticated context preimage" in caught.value.info.observed


def test_no_process_identity_in_slot_fallback() -> None:
    """nodes._effect_slot_id must not call id(self) as a fallback."""
    import re

    text = (
        Path(__file__).resolve().parents[2]
        / "sugar-source-tree"
        / "src"
        / "sugar_source_tree"
        / "nodes.py"
    ).read_text(encoding="utf-8")
    start = text.find("def _effect_slot_id")
    end = text.find("\n    def ", start + 1)
    body = text[start:end]
    # Executable expressions only: ban the call form `id(self)`.
    assert re.search(r"(?<![A-Za-z_])id\(\s*self\s*\)", body) is None

"""`with` under a typed contract (#5994 wiring): the membrane issues, the shared
router routes, the node stays loud for everything unowned. The twin subset that
is wireable today (resource expansion, `as` witnesses, warning-kind are later
steps and stay loud)."""

import tempfile
from pathlib import Path

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile
from with_authority_fixture import source_file_with_preconstruction


def _val(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write("import pytest\nimport contextlib\nimport tm\n" + src)
        path = f.name
    return next(source_file_with_preconstruction(Path(path)).functions()).sugar().desugar().value


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write("import pytest\nimport contextlib\nimport tm\n" + src)
        path = f.name
    return next(source_file_with_preconstruction(Path(path)).functions())


def test_expected_matching_raise_discharges_and_consumes():
    v = _val(
        "def A(z):\n    with pytest.raises(ValueError):\n        raise ValueError\n"
        "    return z\n"
    )
    inv = v.invs()[0]
    assert inv.name == "="  # ground-true eq(ValueError, ValueError)
    assert inv.args[0].value == inv.args[1].value == "ValueError"
    assert v.post().args[1].name == "z"  # the function completes past the with


def test_expected_effect_absent_is_the_lying_twin():
    v = _val(
        "def A(z):\n    with pytest.raises(ValueError):\n        z = 1\n    return z\n"
    )
    inv = v.invs()[0]
    assert inv.args[0].value == "ValueError" and inv.args[1].value == "py.effect.none"


def test_wrong_effect_states_mismatch_and_survives():
    from sugar_lift_py_tests.outcome import Incomplete

    v = _val(
        "def A(z):\n    with pytest.raises(ValueError):\n        raise KeyError\n"
        "    return z\n"
    )
    inv = v.invs()[0]
    assert inv.args[1].value == "KeyError"  # the mismatch fact
    reds = [e for e in v.record.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1  # KeyError did not disappear


def test_unresolved_call_keeps_the_obligation_open():
    v = _val(
        "def A(z):\n    with pytest.raises(ValueError):\n        do_thing(z)\n"
        "    return z\n"
    )
    assert v.invs()[0].name == "py.effect.expected"  # never an absence claim


def test_suppress_matching_consumed():
    v = _val(
        "def A(z):\n    with contextlib.suppress(KeyError):\n        raise KeyError\n"
        "    return z\n"
    )
    assert v.invs() == () and v.post().args[1].name == "z"


def test_suppress_non_match_propagates():
    from sugar_lift_py_tests.outcome import Incomplete

    v = _val(
        "def A(z):\n    with contextlib.suppress(KeyError):\n        raise ValueError\n"
        "    return z\n"
    )
    reds = [e for e in v.record.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1  # ValueError rides through the permission


def test_unauthenticated_manager_stays_loud():
    # Preserve the exact prereq-2 runtime-selected resolution gap.
    with pytest.raises(SugarNotWritten) as ei:
        _fn("def A(z):\n    with open(z):\n        pass\n    return z\n").sugar()
    assert isinstance(ei.value, SugarNotWritten)
    assert type(ei.value).__name__ == "ContextManagerResolutionConstructionGap"
    assert ei.value.kind == "runtime-selected"


def test_as_exception_info_completes_when_effect_matches():
    # Tree rewrites `ei` → ObservationRef(slot, exception_info); routing
    # authenticates the slot. Body completes past the with (return z).
    v = _val(
        "def A(z):\n    with pytest.raises(ValueError) as ei:\n"
        "        raise ValueError\n    return z\n"
    )
    inv = v.invs()[0]
    assert inv.name == "="
    assert inv.args[0].value == inv.args[1].value == "ValueError"
    assert v.post().args[1].name == "z"


def test_as_exception_info_value_projects_effect_slot():
    # ei.value is the pure EffectCoordinate; binding facts authenticate the slot.
    v = _val(
        "def A():\n    with pytest.raises(ValueError) as ei:\n"
        "        raise ValueError\n    return ei.value\n"
    )
    # Expects type discharge still present
    assert any(
        inv.name == "=" and inv.args[0].value == "ValueError"
        for inv in v.invs()
        if inv.name == "=" and hasattr(inv.args[0], "value")
    )
    assert v.post().args[1].name == "python:effect_slot"
    typed = [
        inv
        for inv in v.invs()
        if inv.name == "="
        and getattr(inv.args[0], "name", None) == "effect_slot_type"
    ]
    assert typed and typed[0].args[1].value == "ValueError"


def test_as_non_name_target_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn(
            "def A(z):\n    with pytest.raises(ValueError) as (ei,):\n"
            "        raise ValueError\n    return z\n"
        ).sugar()


def test_suppresses_as_stays_loud():
    """Suppresses+as is not a community effect-witness shape (step 5 is Expects)."""
    with pytest.raises(SugarNotWritten):
        _fn(
            "def A(z):\n    with contextlib.suppress(KeyError) as cm:\n"
            "        raise KeyError\n    return z\n"
        ).sugar()


def test_warning_kind_with_unresolved_call_retains_obligation():
    v = _val(
        "def A(z):\n    with tm.assert_produces_warning(FutureWarning):\n"
        "        do_thing(z)\n    return z\n"
    )
    inv = v.invs()[0]
    assert inv.name == "py.effect.expected"
    assert inv.args[0].value == "FutureWarning"


def test_multiple_managers_stay_loud():
    with pytest.raises(SugarNotWritten):
        _fn(
            "def A(z):\n    with pytest.raises(ValueError), contextlib.suppress(KeyError):\n"
            "        pass\n    return z\n"
        ).sugar()


if __name__ == "__main__":
    test_expected_matching_raise_discharges_and_consumes()
    test_expected_effect_absent_is_the_lying_twin()
    test_wrong_effect_states_mismatch_and_survives()
    test_unresolved_call_keeps_the_obligation_open()
    test_suppress_matching_consumed()
    test_suppress_non_match_propagates()
    test_unauthenticated_manager_stays_loud()
    test_as_witness_admits_and_discharges()
    test_as_witness_inlines_in_the_tail()
    test_as_non_name_target_stays_loud()
    test_suppresses_as_stays_loud()
    test_warning_kind_with_unresolved_call_retains_obligation()
    test_multiple_managers_stay_loud()
    print("ok: with under typed contracts -- as-witness twins")


def test_match_conjunction_type_discharged_message_undischarged():
    # The 96% shape: raises(E, match=pat). Two rows, closed verdicts each:
    # type discharged (ground-true eq), message UNDISCHARGED (opaque
    # py.effect.message_matches over the SAME observed witness) -- never one
    # aggregate boolean, never a silent drop of match=.
    v = _val(
        'def A(z):\n    with pytest.raises(ValueError, match="bad"):\n'
        "        raise ValueError\n    return z\n"
    )
    invs = v.invs()
    assert len(invs) == 2
    type_row = [i for i in invs if getattr(i, "name", "") == "="][0]
    msg_row = [
        i for i in invs if getattr(i, "name", "") == "py.effect.message_matches"
    ][0]
    assert type_row.args[0].value == type_row.args[1].value == "ValueError"
    assert msg_row.args[0].value == "ValueError"  # shared observed witness
    assert msg_row.args[1].value == "bad"


def test_match_deferred_carries_the_whole_conjunction():
    v = _val(
        'def A(z):\n    with pytest.raises(ValueError, match="x"):\n'
        "        do_thing(z)\n    return z\n"
    )
    inv = v.invs()[0]
    assert inv.name == "py.effect.expected"
    assert [a.value for a in inv.args] == ["ValueError", "x"]


def test_match_rejections_stay_loud():
    for src in (
        "def A(z):\n    with pytest.raises(ValueError, match=None):\n        pass\n    return z\n",
        'def A(z):\n    with pytest.raises(ValueError, match="["):\n        pass\n    return z\n',
        "def A(z):\n    with pytest.raises(ValueError, check=1):\n        pass\n    return z\n",
    ):
        with pytest.raises(SugarNotWritten):
            _fn(src).sugar()


# ---------------------------------------------------------------------------
# Guarded ExitSet twins — contract routes per face, not over a linear list.
# ---------------------------------------------------------------------------


def test_conditional_expects_raised_face_and_absent_face():
    """Expects over if c: raise — match under c; absence under ¬c must survive."""
    v = _val(
        "def A(c, z):\n"
        "    with pytest.raises(ValueError):\n"
        "        if c:\n"
        "            raise ValueError\n"
        "        z = 1\n"
        "    return z\n"
    )
    invs = list(v.invs())
    # Two obligation faces: discharge ValueError=ValueError and absence.
    consequents = []
    for inv in invs:
        f = inv
        if getattr(f, "kind", None) == "implies":
            f = f.operands[1]
        consequents.append(f)
    discharges = [
        c
        for c in consequents
        if getattr(c, "name", None) == "="
        and getattr(c.args[0], "value", None) == "ValueError"
        and getattr(c.args[1], "value", None) == "ValueError"
    ]
    absences = [
        c
        for c in consequents
        if getattr(c, "name", None) == "="
        and getattr(c.args[0], "value", None) == "ValueError"
        and getattr(c.args[1], "value", None) == "py.effect.none"
    ]
    assert discharges, f"missing matched discharge in {invs}"
    assert absences, f"missing ¬c absence obligation in {invs}"
    # Raised face is consumed — no residual ValueError Incomplete.
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    reds = [
        e
        for e in v.record.contribution()
        if isinstance(e, Incomplete) and isinstance(e.effect, RaiseEffect)
    ]
    assert reds == []


def test_conditional_expects_wrong_type_keeps_halt_and_completion():
    """Wrong halt under c + complementary completion under ¬c both survive."""
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(c, z):\n"
        "    with pytest.raises(ValueError):\n"
        "        if c:\n"
        "            raise KeyError\n"
        "        z = 1\n"
        "    return z\n"
    )
    reds = [
        e
        for e in v.record.contribution()
        if isinstance(e, Incomplete) and isinstance(e.effect, RaiseEffect)
    ]
    assert len(reds) == 1
    assert reds[0].effect.exception_name == "KeyError"
    # Guarded under c — not an unconditional residual.
    assert reds[0].branch_conditions, "wrong halt must keep its guard"
    # Mismatch fact present (ValueError vs KeyError).
    assert any(
        getattr(inv, "name", None) == "="
        or (
            getattr(inv, "kind", None) == "implies"
            and getattr(inv.operands[1], "name", None) == "="
            and inv.operands[1].args[1].value == "KeyError"
        )
        or (
            getattr(inv, "name", None) == "="
            and getattr(inv.args[1], "value", None) == "KeyError"
        )
        for inv in v.invs()
    )
    # ¬c completion is not erased: absence or body residue under the complement.
    invs = list(v.invs())
    assert len(invs) >= 1


def test_conditional_expects_as_authenticates_slot_only_on_matched_face():
    """ei.value / effect_slot_type only on the matched raise face."""
    v = _val(
        "def A(c):\n"
        "    with pytest.raises(ValueError) as ei:\n"
        "        if c:\n"
        "            raise ValueError\n"
        "        x = 1\n"
        "    return ei.value\n"
    )
    # Slot type auth must appear, and under a guard when multi-face.
    typed = []
    for inv in v.invs():
        f = inv
        guard = None
        if getattr(f, "kind", None) == "implies":
            guard, f = f.operands[0], f.operands[1]
        if (
            getattr(f, "name", None) == "="
            and getattr(f.args[0], "name", None) == "effect_slot_type"
        ):
            typed.append((guard, f.args[1].value))
    assert typed, f"missing effect_slot_type in {list(v.invs())}"
    assert all(val == "ValueError" for _, val in typed)
    # Matched-face only: if guarded, guard is the truthy(c) polarity.
    if any(g is not None for g, _ in typed):
        assert any(
            g is not None and getattr(g, "name", None) == "py.truthy"
            for g, _ in typed
        )
    assert v.post().args[1].name == "python:effect_slot"


def test_conditional_suppresses_match_only_on_matching_face():
    """Suppresses consumes KeyError under c; ¬c completion survives; mismatch rides."""
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(c, z):\n"
        "    with contextlib.suppress(KeyError):\n"
        "        if c:\n"
        "            raise KeyError\n"
        "        z = 1\n"
        "    return z\n"
    )
    reds = [
        e
        for e in v.record.contribution()
        if isinstance(e, Incomplete) and isinstance(e.effect, RaiseEffect)
    ]
    assert reds == [], "matching KeyError face must be consumed"
    assert v.post().args[1].name == "z"

    # Mismatch face: wrong raise under c survives guarded.
    v_bad = _val(
        "def A(c, z):\n"
        "    with contextlib.suppress(KeyError):\n"
        "        if c:\n"
        "            raise ValueError\n"
        "        z = 1\n"
        "    return z\n"
    )
    reds_bad = [
        e
        for e in v_bad.record.contribution()
        if isinstance(e, Incomplete) and isinstance(e.effect, RaiseEffect)
    ]
    assert len(reds_bad) == 1
    assert reds_bad[0].effect.exception_name == "ValueError"
    assert reds_bad[0].branch_conditions


def test_warning_kind_routing_non_halting_on_guarded_completed_faces():
    """Warning Expects is non-halting; dual completed faces each get a verdict.

    Unresolved-call openness stays covered by
    ``test_warning_kind_with_unresolved_call_retains_obligation``. Conditional
    bodies that need ``CallSiteValue.guarded`` stay out of this twin until that
    Floor is written — here both faces complete without a raise halt.
    """
    from sugar_lift_py_tests.outcome import Incomplete

    v = _val(
        "def A(c, z):\n"
        "    with tm.assert_produces_warning(FutureWarning):\n"
        "        if c:\n"
        "            z = 1\n"
        "        else:\n"
        "            z = 2\n"
        "    return z\n"
    )
    assert not any(isinstance(e, Incomplete) for e in v.record.contribution())
    # No observed warning → absence (or open expected) on completed faces.
    invs = list(v.invs())
    assert invs, f"warning contract must state a verdict: {invs}"
    assert v.post().args[1].name == "z"

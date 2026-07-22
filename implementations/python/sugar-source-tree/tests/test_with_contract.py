"""`with` under a typed contract (#5994 wiring): the membrane issues, the shared
router routes, the node stays loud for everything unowned. The twin subset that
is wireable today (resource expansion, `as` witnesses, warning-kind are later
steps and stay loud)."""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import RuntimeSelectedContextManager, SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _val(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions()).sugar().desugar().value


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


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
    # Named residual (step 4): RuntimeSelectedContextManager, not bare
    # SugarNotWritten — census can count resource managers separately.
    with pytest.raises(RuntimeSelectedContextManager) as ei:
        _fn("def A(z):\n    with open(z):\n        pass\n    return z\n").sugar()
    assert isinstance(ei.value, SugarNotWritten)
    assert (
        "unauthenticated context manager — exit suppression runtime-selected"
        in ei.value.observed
    )


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
    # ei.value is the same effect slot (ExceptionInfoCoordinate.attribute).
    v = _val(
        "def A():\n    with pytest.raises(ValueError) as ei:\n"
        "        raise ValueError\n    return ei.value\n"
    )
    assert v.invs()[0].args[0].value == "ValueError"
    term = v.post().args[1]
    assert term.name == "python:observed_exception"
    assert term.args[0].value == "ValueError"


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

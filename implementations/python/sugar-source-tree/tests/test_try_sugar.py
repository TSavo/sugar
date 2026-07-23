"""`try` as the STRUCTURAL surface of the effect router: except clauses match
by exact kind+name (the same rule with-contracts ride), matching handlers
consume the Incomplete, non-matches propagate, else/finally splice, and the
loud residuals stay loud. Mirror of test_with_contract.py for the native-syntax
twin."""

import tempfile
from pathlib import Path

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile
from with_resolution_fixture import source_file_with_preconstruction


def _val(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write("import pytest\nimport contextlib\nimport tm\n" + src)
        path = f.name
    return (
        next(source_file_with_preconstruction(Path(path)).functions())
        .sugar()
        .desugar()
        .value
    )


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write("import pytest\nimport contextlib\nimport tm\n" + src)
        path = f.name
    return next(source_file_with_preconstruction(Path(path)).functions())


def _incompletes(v):
    from sugar_lift_py_tests.outcome import Incomplete

    return [e for e in v.record.contribution() if isinstance(e, Incomplete)]


def test_matching_except_consumes_raise_and_try_completes():
    # Matching except ValueError consumes the body's raise; the function
    # completes past the try (post out == z), same discharge shape as
    # with-raises under Suppresses/Expects consume.
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        pass\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


def test_handler_own_raise_propagates():
    # A matching handler that itself raises: the body's raise is consumed, the
    # handler's raise rides out as red testimony (does not disappear).
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        raise KeyError\n"
        "    return z\n"
    )
    reds = _incompletes(v)
    assert len(reds) == 1
    assert isinstance(reds[0].effect, RaiseEffect)
    assert reds[0].effect.exception_name == "KeyError"


def test_except_keyerror_does_not_catch_valueerror():
    # Exact-match discrimination (the mismatch twin): except KeyError does NOT
    # silently catch a ValueError body -- the Incomplete survives.
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except KeyError:\n"
        "        pass\n"
        "    return z\n"
    )
    reds = _incompletes(v)
    assert len(reds) == 1
    assert isinstance(reds[0].effect, RaiseEffect)
    assert reds[0].effect.exception_name == "ValueError"


def test_except_valueerror_does_catch_valueerror():
    # Positive twin of the discrimination: except ValueError consumes a
    # ValueError body raise -- zero red raises survive.
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        pass\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


def test_else_runs_when_body_is_raise_free():
    # Body with no observed raise reduces else; the else return is the exit.
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError:\n"
        "        pass\n"
        "    else:\n"
        "        return z\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


def test_else_does_not_run_when_raise_is_caught():
    # Caught raise takes the handler path, not else: handler return wins.
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        return z\n"
        "    else:\n"
        "        return 0\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


def test_finally_reduces_on_caught_path():
    # finally always runs: after a matching except, finally's return is the
    # exit (Python: finally return is the function exit).
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        pass\n"
        "    finally:\n"
        "        return z\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


def test_finally_reduces_on_uncaught_path():
    # Cleanup halt supersedes the incoming uncaught raise (Python: only
    # RuntimeError propagates; ValueError does not also ride).
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except KeyError:\n"
        "        pass\n"
        "    finally:\n"
        "        raise RuntimeError\n"
        "    return z\n"
    )
    reds = _incompletes(v)
    names = {r.effect.exception_name for r in reds if isinstance(r.effect, RaiseEffect)}
    assert names == {"RuntimeError"}


def test_finally_pass_restores_uncaught_raise():
    """Cleanup fall-through restores the incoming halt (ValueError survives)."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except KeyError:\n"
        "        pass\n"
        "    finally:\n"
        "        z = z\n"
        "    return z\n"
    )
    reds = _incompletes(v)
    assert len(reds) == 1
    assert isinstance(reds[0].effect, RaiseEffect)
    assert reds[0].effect.exception_name == "ValueError"


def test_finally_return_supersedes_caught_path():
    """Return in finally is the function exit after a matching except."""
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        x = 1\n"
        "    finally:\n"
        "        return z\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


def test_finally_on_normal_completion():
    """finally runs on the no-raise path; fall-through keeps body completion."""
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        x = z\n"
        "    finally:\n"
        "        y = 1\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


def test_conditional_raise_both_exits_survive_through_finally():
    """Pressure twin: body -> ExitSet -> route Halted -> finally over every exit.

    ``if c: raise`` / ``return 1`` / ``except: return 2`` / ``finally`` must keep
    both guarded completions — not consume the raise into an unconditional
    handler while only the ¬c return rides as residual testimony.
    """
    v = _val(
        "def A(c):\n"
        "    try:\n"
        "        if c:\n"
        "            raise ValueError\n"
        "        return 1\n"
        "    except ValueError:\n"
        "        return 2\n"
        "    finally:\n"
        "        y = 0\n"
    )
    assert _incompletes(v) == []
    # Same dual post shape as ``if c: return 2\\nelse: return 1``.
    ideal = _val(
        "def A(c):\n"
        "    if c:\n"
        "        return 2\n"
        "    else:\n"
        "        return 1\n"
    )
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.ir import not_

    returns = [e for e in v.record.contribution() if isinstance(e, GuardedReturn)]
    assert len(returns) == 2
    assert {entry.value.value for entry in returns} == {1, 2}
    assert returns[1].guards[0] == not_(returns[0].guards[0])
    values = {r.value.value for r in returns}
    assert values == {1, 2}


def test_conditional_raise_assign_paths_through_finally_no_residual_halt():
    """User surface: assign on both faces + cleanup; raise must not leak red.

    Temporal phi for ``x`` across try/except is separate substitute work; this
    twin locks that conditional routing + finally does not leave a bare raise.
    """
    v = _val(
        "def A(c):\n"
        "    try:\n"
        "        if c:\n"
        "            raise ValueError\n"
        "        x = 1\n"
        "    except ValueError:\n"
        "        x = 2\n"
        "    finally:\n"
        "        y = 0\n"
        "    return x\n"
    )
    assert _incompletes(v) == []
    post = v.post()
    assert post.kind == "and"
    assert {face.operands[1].args[1].value for face in post.operands} == {1, 2}
    by_value = {
        face.operands[1].args[1].value: face.operands[0] for face in post.operands
    }
    assert by_value[2].name == "py.truthy"
    assert by_value[1].kind == "not"


def test_false_arm_conditional_raise_routes_with_reverse_polarity():
    v = _val(
        "def A(c):\n"
        "    try:\n"
        "        if c:\n"
        "            pass\n"
        "        else:\n"
        "            raise ValueError\n"
        "        x = 1\n"
        "    except ValueError:\n"
        "        x = 2\n"
        "    return x\n"
    )
    assert _incompletes(v) == []
    post = v.post()
    assert post.kind == "and"
    by_value = {
        face.operands[1].args[1].value: face.operands[0] for face in post.operands
    }
    assert by_value[1].name == "py.truthy"
    assert by_value[2].kind == "not"


def test_except_as_binds_matching_raise_witness_in_handler():
    # Tree rewrites `error` → EffectRef(slot); routing emits EffectBinding facts.
    # Coordinate stays effect-slot(S); identity lives in constructed testimony.
    v = _val(
        "def A():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as error:\n"
        "        return error\n"
    )
    assert _incompletes(v) == []
    post = v.post()
    assert post.args[0].name == "out"
    assert post.args[1].name == "python:effect_slot"
    # Authentication is explicit record testimony (not ambient seal).
    inv_names = [inv.name for inv in v.invs()]
    assert "effect_slot_type" in inv_names or any(
        getattr(inv, "name", None) == "effect_slot_type"
        or (hasattr(inv, "args") and inv.name == "=")
        for inv in v.invs()
    )
    # Find effect_slot_type fact: atomic effect_slot_type(S) = "ValueError"
    typed = [
        inv
        for inv in v.invs()
        if inv.name == "=" and getattr(inv.args[0], "name", None) == "effect_slot_type"
    ]
    assert (
        typed
    ), f"missing effect_slot_type in {[i.name for i in v.invs()]}: {v.invs()}"
    assert typed[0].args[1].value == "ValueError"
    # Witness identity is the slot itself (post), not a type-derived equation.
    assert not any(
        inv.name == "=" and getattr(inv.args[0], "name", None) == "effect_slot_identity"
        for inv in v.invs()
    )
    origins = [
        inv
        for inv in v.invs()
        if inv.name == "="
        and getattr(inv.args[0], "name", None) == "effect_slot_origin"
    ]
    assert origins, "effect_slot_origin must link slot to raise occurrence"
    assert origins[0].args[1].name == "python:raise_effect_occurrence"


def test_except_as_does_not_bind_on_uncaught_path():
    # Wrong-type handler is unreachable; its EffectRef is never authenticated.
    # Body raise propagates (mismatch twin).
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except KeyError as error:\n"
        "        return error\n"
        "    return 0\n"
    )
    reds = _incompletes(v)
    assert len(reds) == 1
    assert isinstance(reds[0].effect, RaiseEffect)
    assert reds[0].effect.exception_name == "ValueError"


def test_tuple_except_catches_any_exactly_listed_type():
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except (KeyError, ValueError):\n"
        "        pass\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


def test_tuple_except_does_not_catch_unlisted_type():
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except (KeyError, IndexError):\n"
        "        pass\n"
        "    return z\n"
    )
    reds = _incompletes(v)
    assert len(reds) == 1
    assert isinstance(reds[0].effect, RaiseEffect)
    assert reds[0].effect.exception_name == "ValueError"


def test_tuple_except_as_binds_the_matched_type_witness():
    v = _val(
        "def A():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except (KeyError, ValueError) as error:\n"
        "        return error\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "python:effect_slot"
    typed = [
        inv
        for inv in v.invs()
        if inv.name == "=" and getattr(inv.args[0], "name", None) == "effect_slot_type"
    ]
    assert typed and typed[0].args[1].value == "ValueError"


def test_bare_except_catches_arbitrary_raise():
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise ArbitraryProjectHalt\n"
        "    except:\n"
        "        pass\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


def test_except_star_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn(
            "def A(z):\n"
            "    try:\n"
            "        raise ValueError\n"
            "    except* ValueError:\n"
            "        pass\n"
            "    return z\n"
        ).sugar()


def test_non_name_except_type_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn(
            "def A(z):\n"
            "    try:\n"
            "        raise ValueError\n"
            "    except exception_type():\n"
            "        pass\n"
            "    return z\n"
        ).sugar()


def test_dotted_except_type_matches():
    # Dotted Name exception types are in the tractable core (same structural
    # walk as raise's exception_name).
    v = _val(
        "def A(z):\n"
        "    try:\n"
        "        raise os.error\n"
        "    except os.error:\n"
        "        pass\n"
        "    return z\n"
    )
    assert _incompletes(v) == []
    assert v.post().args[1].name == "z"


def test_two_raise_valueerror_sites_have_distinct_origins_same_type():
    """Two raise ValueError sites: equal type testimony, distinct origins."""
    v = _val(
        "def A():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as first:\n"
        "        a = first\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as second:\n"
        "        return (a, second)\n"
    )
    assert _incompletes(v) == []
    types = [
        inv.args[1].value
        for inv in v.invs()
        if inv.name == "=" and getattr(inv.args[0], "name", None) == "effect_slot_type"
    ]
    assert types.count("ValueError") >= 2
    origins = [
        inv.args[1].args[0].value
        for inv in v.invs()
        if inv.name == "="
        and getattr(inv.args[0], "name", None) == "effect_slot_origin"
    ]
    assert len(origins) >= 2
    assert len(set(origins)) == len(origins), f"origins must be distinct: {origins}"


if __name__ == "__main__":
    test_matching_except_consumes_raise_and_try_completes()
    test_handler_own_raise_propagates()
    test_except_keyerror_does_not_catch_valueerror()
    test_except_valueerror_does_catch_valueerror()
    test_else_runs_when_body_is_raise_free()
    test_else_does_not_run_when_raise_is_caught()
    test_finally_reduces_on_caught_path()
    test_finally_reduces_on_uncaught_path()
    test_except_as_binds_matching_raise_witness_in_handler()
    test_except_as_does_not_bind_on_uncaught_path()
    test_tuple_except_catches_any_exactly_listed_type()
    test_tuple_except_does_not_catch_unlisted_type()
    test_tuple_except_as_binds_the_matched_type_witness()
    test_bare_except_catches_arbitrary_raise()
    test_except_star_stays_loud()
    test_non_name_except_type_stays_loud()
    test_dotted_except_type_matches()
    print("ok: try sugar -- structural effect routing")

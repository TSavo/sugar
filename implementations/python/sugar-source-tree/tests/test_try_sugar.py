"""`try` as the STRUCTURAL surface of the effect router: except clauses match
by exact kind+name (the same rule with-contracts ride), matching handlers
consume the Incomplete, non-matches propagate, else/finally splice, and the
loud residuals stay loud. Mirror of test_with_contract.py for the native-syntax
twin."""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
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
    # finally still reduces when the raise is NOT caught: the body's
    # Incomplete survives AND finally's raise is spliced (both effects ride).
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
    assert "ValueError" in names  # uncaught body raise survives
    assert "RuntimeError" in names  # finally reduced and spliced


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
        if inv.name == "="
        and getattr(inv.args[0], "name", None) == "effect_slot_type"
    ]
    assert typed, f"missing effect_slot_type in {[i.name for i in v.invs()]}: {v.invs()}"
    assert typed[0].args[1].value == "ValueError"
    identity = [
        inv
        for inv in v.invs()
        if inv.name == "="
        and getattr(inv.args[0], "name", None) == "effect_slot_identity"
    ]
    assert identity
    assert identity[0].args[1].name == "python:observed_exception"
    assert identity[0].args[1].args[0].value == "ValueError"


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
        if inv.name == "="
        and getattr(inv.args[0], "name", None) == "effect_slot_type"
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

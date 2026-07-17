"""Part of #4103: requests recognition residual drain instruments.

Measures lifted_cited ΔR after try continuing-path join, CallSiteValue.delitem,
relative ExceptionClass import resolution, and exception kwargs construction.
No soft refuse: silence stays illegal; remaining package residual is loud.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    ImportAliasValue,
    ExceptionClassValue,
    RaiseValue,
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.lift_rpc import audit_lift_file

VENDOR = (
    Path(__file__).resolve().parent / "vendor" / "requests-2.34.2" / "requests"
)


def _axis(source: str, filename: str) -> dict:
    payload, _gaps = audit_lift_file(source, filename)
    return account_lift_coverage(
        census_source(source, file=filename), payload.to_rpc()
    ).to_json()["assertions"]


def test_try_bind_with_terminal_handler_raise_joins_body_binding() -> None:
    """try-body bind + except raise must not poison the post-try name."""
    binds = {
        "pair": SymbolicValue(make_var("pair")),
        "request": SymbolicValue(make_var("request")),
        "InvalidURL": ImportAliasValue(
            "InvalidURL",
            "InvalidURL",
            import_target="requests.exceptions.InvalidURL",
            resolved_value=ExceptionClassValue("requests.exceptions.InvalidURL"),
        ),
    }
    block = compose_block(
        "    try:\n"
        "        a, b = pair\n"
        "    except ValueError as e:\n"
        "        raise InvalidURL(e, request=request)\n"
        "    return a\n",
        binds=binds,
    )
    assert isinstance(block, BlockValue)
    assert isinstance(block.statements[-1], ReturnValue)


def test_callsite_delitem_rebinds_through_py_delitem() -> None:
    """Opaque dict_class(...) receivers rebind after del xs[k], never panic."""
    record = compose_block(
        "    xs = dict_class(items)\n" "    del xs[key]\n" "    return xs\n",
        binds={
            "dict_class": SymbolicValue(make_var("dict_class")),
            "items": SymbolicValue(make_var("items")),
            "key": SymbolicValue(make_var("key")),
        },
    )
    assert isinstance(record, BlockValue)
    returned = record.statements[-1]
    assert isinstance(returned, ReturnValue)
    assert isinstance(returned.value, CallSiteValue)
    assert returned.value.target_name == "delitem"
    assert returned.value.term.name == "py.delitem"


def test_requests_check_cryptography_try_bind_does_not_poison_module() -> None:
    """Full __init__.py audits after try-bind (was TemporalContext panic)."""
    source = (VENDOR / "__init__.py").read_text(encoding="utf-8")
    axis = _axis(source, "requests/__init__.py")
    assert axis["stated"] == 5
    assert axis["lifted_cited"] == 5
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0
    assert [locus["line"] for locus in axis["lifted_loci"]] == [66, 76, 78, 85, 90]


def test_requests_cookies_assert_lifts() -> None:
    source = (VENDOR / "cookies.py").read_text(encoding="utf-8")
    axis = _axis(source, "requests/cookies.py")
    assert axis["stated"] == 1
    assert axis["lifted_cited"] == 1
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0
    assert axis["lifted_loci"][0]["line"] == 46


def test_requests_adapters_asserts_lift() -> None:
    source = (VENDOR / "adapters.py").read_text(encoding="utf-8")
    axis = _axis(source, "requests/adapters.py")
    assert axis["stated"] == 4
    assert axis["lifted_cited"] == 4
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0
    assert [locus["line"] for locus in axis["lifted_loci"]] == [375, 481, 581, 659]


def test_requests_sessions_four_of_five_lifts_one_refused_residual() -> None:
    """send() assert after isinstance(Request) remains refused residual."""
    source = (VENDOR / "sessions.py").read_text(encoding="utf-8")
    axis = _axis(source, "requests/sessions.py")
    assert axis["stated"] == 5
    assert axis["lifted_cited"] == 4
    assert axis["refused_loud"] == 1
    assert axis["silently_unaccounted"] == 0
    assert [locus["line"] for locus in axis["lifted_loci"]] == [320, 321, 353, 640]
    assert [locus["line"] for locus in axis["refused_loci"]] == [773]


def test_requests_package_key_files_lifted_cited_delta() -> None:
    """Measurable package R: 15 lifted / 1 refused / 0 silent on key assert files.

    Full package still has non-assert residual panics (auth AugAssign, help
    TemporalContext, structures RecursionError, utils NoneValue.subtract) that
    do not host the 16 stated assert loci. Leave open for that residual.
    """
    files = {
        "__init__.py": (5, 5, 0),
        "_internal_utils.py": (1, 1, 0),
        "cookies.py": (1, 1, 0),
        "adapters.py": (4, 4, 0),
        "sessions.py": (5, 4, 1),
    }
    stated = lifted = refused = silent = 0
    for name, expected in files.items():
        source = (VENDOR / name).read_text(encoding="utf-8")
        axis = _axis(source, f"requests/{name}")
        exp_stated, exp_lifted, exp_refused = expected
        assert axis["stated"] == exp_stated, name
        assert axis["lifted_cited"] == exp_lifted, name
        assert axis["refused_loud"] == exp_refused, name
        assert axis["silently_unaccounted"] == 0, name
        stated += axis["stated"]
        lifted += axis["lifted_cited"]
        refused += axis["refused_loud"]
        silent += axis["silently_unaccounted"]
    assert (stated, lifted, refused, silent) == (16, 15, 1, 0)


def test_keyword_exception_constructor_routes_raise() -> None:
    binds = {
        "e": SymbolicValue(make_var("e")),
        "request": SymbolicValue(make_var("request")),
        "InvalidURL": ImportAliasValue(
            "InvalidURL",
            "InvalidURL",
            import_target="requests.exceptions.InvalidURL",
            resolved_value=ExceptionClassValue("requests.exceptions.InvalidURL"),
        ),
    }
    block = compose_block(
        "    raise InvalidURL(e, request=request)\n", binds=binds
    )
    raised = block.statements[0]
    assert isinstance(raised, RaiseValue)
    assert raised.effect.exception_name == "requests.exceptions.InvalidURL"


def test_missing_try_bind_path_stays_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    try:\n"
            "        result = 5\n"
            "    except ValueError:\n"
            "        pass\n"
            "    return result\n"
        )
    assert raised.value.info.owner == "TemporalContext"
    assert raised.value.info.observed == "result"

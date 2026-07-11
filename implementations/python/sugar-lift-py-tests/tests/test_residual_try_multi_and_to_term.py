# SPDX-License-Identifier: MIT OR Apache-2.0
"""Residual refuse: multi-type try, collection to_term, attachable dig widen."""

from __future__ import annotations

from sugar_lift_py_tests.floor import ClassValue, DictValue, ListValue, TermValue
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.sugar.install_source_dig import (
    build_dig_body,
    method_body_is_attachable,
    resolve_install_source_funcdef,
)
from sugar_lift_py_tests.sugar.try_sugar import TrySugar
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
import ast

from sugar_lift_py_tests.factory.source_fragment import SourceFragment


def test_try_sugar_owns_multi_type_except() -> None:
    src = (
        "try:\n"
        "    return x\n"
        "except (TypeError, ValueError) as e:\n"
        "    raise RuntimeError from e\n"
    )
    site = SourceFragment.from_node(ast.parse(src).body[0], "t.py")
    assert TrySugar.owns(site)


def test_list_dict_class_to_term_projects() -> None:
    lv = ListValue((TermValue(1), TermValue(2)))
    def _name(term):
        return term.name if hasattr(term, "name") else term.get("name")

    t = lv.to_term(owner="t")
    assert _name(t) == "array"
    dv = DictValue(((TermValue(0), TermValue(1)),))
    t2 = dv.to_term(owner="t")
    assert _name(t2) == "python:dict"
    from sugar_lift_py_tests.floor import BlockValue

    cv = ClassValue(name="C", bases=(), record=BlockValue(()))
    t3 = cv.to_term(owner="t")
    assert _name(t3) == "python:type"


def test_encoding_base64_decode_attachable_and_dig_body() -> None:
    fn = resolve_install_source_funcdef("itsdangerous.encoding.base64_decode")
    assert fn is not None
    assert method_body_is_attachable(fn)
    ctx = FactoryBuildContext(catalog=default_catalog(), filename="enc.py")
    body = build_dig_body(fn, ctx)
    assert body is not None


def test_encoding_sdist_asserts_all_lifted() -> None:
    from pathlib import Path

    f = Path(
        "/opt/data/tmp/sugar-sources-cache/itsdangerous/2.2.0/src/tests/"
        "test_itsdangerous/test_encoding.py"
    )
    if not f.is_file():
        return
    src = f.read_text(encoding="utf-8")
    rpc = lift_file_payload(src, str(f)).to_rpc()
    ax = account_lift_coverage(census_source(src, file=str(f)), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["refused_loud"] == 0
    assert ax["lifted_cited"] == ax["stated"]


def test_signer_sdist_asserts_all_lifted() -> None:
    from pathlib import Path

    f = Path(
        "/opt/data/tmp/sugar-sources-cache/itsdangerous/2.2.0/src/tests/"
        "test_itsdangerous/test_signer.py"
    )
    if not f.is_file():
        return
    src = f.read_text(encoding="utf-8")
    rpc = lift_file_payload(src, str(f)).to_rpc()
    ax = account_lift_coverage(census_source(src, file=str(f)), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["refused_loud"] == 0
    assert ax["lifted_cited"] == ax["stated"]

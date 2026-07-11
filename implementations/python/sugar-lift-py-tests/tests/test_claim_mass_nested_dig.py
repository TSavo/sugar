# SPDX-License-Identifier: MIT OR Apache-2.0
"""Claim mass: attribute-on-self + nested method dig under budget.

itsdangerous sdist is already 57/57/0. Next residual is body-dig depth:

- ``self.attr`` after ``self.attr = value`` (AttributeAssign ScopeRebind) must
  dig to the bound value — not opaque ``call:attr(self)`` forever.
- Nested ``self.inner(...)`` inside an attachable outer method must attach dig
  body under budget (systemic class resolve — not vendor-only ``name==sign``).

Panic-is-correct: missing floors stay refuse-loud / opaque; never silent invent.
DualGroundEqFace remains the sole py.eq dual door (untouched here).
"""

from __future__ import annotations

from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.floor.object_field import ObjectField
from sugar_lift_py_tests.floor.object_value import ObjectValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.outcome import Incomplete, complete_value
from sugar_lift_py_tests.sugar.install_source_dig import (
    _receiver_class_name,
    build_dig_body,
    dig_parameters_for_body,
    method_body_is_attachable,
    resolve_install_source_class_method,
    resolve_method_funcdef,
)


def _class_resolver(src: str, filename: str = "t.py") -> dict:
    parsed = SourceFragment.from_source(src, filename)
    resolver: dict = {}
    for child in parsed.walk():
        if child.observed != "ClassDef":
            continue
        cname = child.class_name()
        for stmt in child.class_body():
            if stmt.observed != "FunctionDef":
                continue
            mname = stmt.function_name()
            resolver[f"{cname}.{mname}"] = stmt.node
            stmt.node._sugar_file = filename  # type: ignore[attr-defined]
            stmt.node._sugar_source = src  # type: ignore[attr-defined]
            stmt.node._sugar_bridge_name = f"{cname}.{mname}"  # type: ignore[attr-defined]
    return resolver


def _dig_method(
    src: str,
    *,
    class_name: str,
    method: str,
    self_floor: CallSiteValue | ObjectValue,
    arg_floors: tuple = (),
    filename: str = "t.py",
):
    resolver = _class_resolver(src, filename)
    ctx = FactoryBuildContext(
        filename=filename,
        catalog=default_catalog(),
        name_resolver=resolver,
    )
    fn = resolve_method_funcdef(method, self_floor, ctx)
    assert fn is not None, f"resolve {class_name}.{method}"
    assert method_body_is_attachable(fn), f"attachable {class_name}.{method}"
    body = build_dig_body(fn, ctx, require_attachable=True)
    assert body is not None
    arg_values = (self_floor, *arg_floors)
    params = dig_parameters_for_body(fn, len(arg_values), ())
    assert params and len(params) == len(arg_values), (params, arg_values)
    csv = CallSiteValue(
        target_name=method,
        arg_values=arg_values,
        parameters=params,
        term=ctor(
            f"call:{method}",
            [a.to_term(owner=filename) for a in arg_values],
        ),
        body=body,
        site=None,
    )
    return csv._dig_floor_or_none(ctx, owner="claim-mass-nested-dig"), csv, ctx


def test_attribute_on_self_dig_resolves_scope_rebind() -> None:
    """self.n = x; return self.n → dig yields ground x (was opaque call:n)."""
    src = (
        "class Box:\n"
        "    def set_get(self, x):\n"
        "        self.n = x\n"
        "        return self.n\n"
        "def test_b():\n"
        "    b = Box()\n"
        "    assert b.set_get(3) == 3\n"
    )
    box = CallSiteValue(
        target_name="Box",
        arg_values=(),
        parameters=(),
        term=ctor("call:Box", []),
        body=None,
        site=None,
    )
    dug, _csv, _ctx = _dig_method(
        src,
        class_name="Box",
        method="set_get",
        self_floor=box,
        arg_floors=(TermValue(3),),
    )
    assert dug is not None, "attribute-on-self dig must not stay opaque"
    assert isinstance(dug, TermValue), type(dug)
    assert dug.value == 3


def test_attribute_on_self_unbound_stays_coordinate_not_invent() -> None:
    """return self.n with no prior assign → coordinate / opaque dig (lawful)."""
    src = (
        "class Box:\n"
        "    def get(self):\n"
        "        return self.n\n"
    )
    box = CallSiteValue(
        target_name="Box",
        arg_values=(),
        parameters=(),
        term=ctor("call:Box", []),
        body=None,
        site=None,
    )
    dug, csv, ctx = _dig_method(
        src, class_name="Box", method="get", self_floor=box
    )
    # No ScopeRebind → dig of call:n(self) has no body → opaque None.
    assert dug is None
    # Body reduce still completes as coordinate CallSiteValue (not panic invent).
    from sugar_lift_py_tests.floor.call_site_value import _ctx_with_curried_args

    rctx = _ctx_with_curried_args(ctx, csv.parameters, csv.arg_values)
    out = csv.body.reduce(rctx)
    assert not isinstance(out, Incomplete)
    val = complete_value(out, owner="claim-mass")
    assert isinstance(val, CallSiteValue)
    assert val.target_name == "n"
    assert val.body is None


def test_object_value_field_attribute_resolves() -> None:
    """ObjectValue.fields resolve via AttributeSugar (interface field table)."""
    src = (
        "class Box:\n"
        "    def get(self):\n"
        "        return self.n\n"
    )
    obj = ObjectValue(
        class_name="Box",
        fields=(ObjectField(name="n", value=TermValue(9)),),
    )
    dug, _csv, _ctx = _dig_method(
        src, class_name="Box", method="get", self_floor=obj  # type: ignore[arg-type]
    )
    assert isinstance(dug, TermValue)
    assert dug.value == 9


def test_nested_method_dig_attaches_and_reduces_under_budget() -> None:
    """outer → self.inner(x) attaches nested body and digs to ground."""
    src = (
        "class Box:\n"
        "    def inner(self, x):\n"
        "        return x\n"
        "    def outer(self, x):\n"
        "        return self.inner(x)\n"
        "def test_b():\n"
        "    b = Box()\n"
        "    assert b.outer(7) == 7\n"
    )
    box = CallSiteValue(
        target_name="Box",
        arg_values=(),
        parameters=(),
        term=ctor("call:Box", []),
        body=None,
        site=None,
    )
    dug, csv, ctx = _dig_method(
        src,
        class_name="Box",
        method="outer",
        self_floor=box,
        arg_floors=(TermValue(7),),
    )
    assert isinstance(dug, TermValue), dug
    assert dug.value == 7

    # Nested attach at reduce time: MethodCallSugar body for inner is present.
    from sugar_lift_py_tests.floor.call_site_value import _ctx_with_curried_args
    from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar

    rctx = _ctx_with_curried_args(ctx, csv.parameters, csv.arg_values)
    captured: list[tuple[str, bool]] = []
    orig = MethodCallSugar._collect

    def _wrap(self, remaining, accumulated, collect_ctx):
        result = orig(self, remaining, accumulated, collect_ctx)
        if not isinstance(result, Incomplete):
            try:
                val = complete_value(result, owner="nested-capture")
            except Exception:
                return result
            if isinstance(val, CallSiteValue):
                captured.append((val.target_name, val.body is not None))
        return result

    MethodCallSugar._collect = _wrap  # type: ignore[method-assign]
    try:
        csv.body.reduce(rctx)
    finally:
        MethodCallSugar._collect = orig  # type: ignore[method-assign]
    assert ("inner", True) in captured, captured


def test_receiver_class_name_from_object_value() -> None:
    obj = ObjectValue(class_name="Signer", fields=())
    assert _receiver_class_name(obj) == "Signer"
    csv = CallSiteValue(
        target_name="Box",
        arg_values=(),
        parameters=(),
        term=ctor("call:Box", []),
        body=None,
        site=None,
    )
    assert _receiver_class_name(csv) == "Box"


def test_signer_nested_get_signature_body_attaches_systemic() -> None:
    """Signer.sign dig attaches nested get_signature body (not name==sign only)."""
    ctx = FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        from_imports={"Signer": ("itsdangerous", "Signer")},
    )
    signer = CallSiteValue(
        target_name="Signer",
        arg_values=(),
        parameters=(),
        term=ctor("call:Signer", []),
        body=None,
        site=None,
    )
    fn_sign = resolve_method_funcdef("sign", signer, ctx)
    assert fn_sign is not None
    assert method_body_is_attachable(fn_sign)
    body = build_dig_body(fn_sign, ctx, require_attachable=True)
    assert body is not None

    from sugar_lift_py_tests.floor.call_site_value import _ctx_with_curried_args
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar

    params = dig_parameters_for_body(fn_sign, 2, ())
    args = (signer, StringValue("value"))
    rctx = _ctx_with_curried_args(ctx, params, args)
    captured: list[tuple[str, bool]] = []
    orig = MethodCallSugar._collect

    def _wrap(self, remaining, accumulated, collect_ctx):
        result = orig(self, remaining, accumulated, collect_ctx)
        if not isinstance(result, Incomplete):
            try:
                val = complete_value(result, owner="signer-nested")
            except Exception:
                return result
            if isinstance(val, CallSiteValue):
                captured.append((val.target_name, val.body is not None))
        return result

    MethodCallSugar._collect = _wrap  # type: ignore[method-assign]
    try:
        body.reduce(rctx)
    finally:
        MethodCallSugar._collect = orig  # type: ignore[method-assign]

    assert any(
        name == "get_signature" and attached for name, attached in captured
    ), captured

    # Direct resolve of nested method is install-source class method (systemic).
    fn_gs = resolve_install_source_class_method(
        "itsdangerous.Signer", "get_signature"
    )
    assert fn_gs is not None
    assert method_body_is_attachable(fn_gs)


def test_lift_attribute_on_self_and_nested_stay_lifted_silent_zero() -> None:
    """Stated asserts on both residual shapes lift; silent remains illegal."""
    src = (
        "class Box:\n"
        "    def inner(self, x):\n"
        "        return x\n"
        "    def outer(self, x):\n"
        "        return self.inner(x)\n"
        "    def set_get(self, x):\n"
        "        self.n = x\n"
        "        return self.n\n"
        "def test_nested():\n"
        "    assert Box().outer(7) == 7\n"
        "def test_attr():\n"
        "    assert Box().set_get(3) == 3\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0, ax
    assert ax["lifted_cited"] == 2, ax
    assert ax["refused_loud"] == 0, ax

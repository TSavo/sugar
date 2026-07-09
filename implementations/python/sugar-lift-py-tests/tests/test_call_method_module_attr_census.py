"""Census: importable module.attr(...) must not gap as call-method:* (#3939).

Law
---
When the call receiver is a bare Name that ``importlib.import_module`` can load,
``CallSugar._module_attr_import_target`` treats ``mod.attr(...)`` as an import-
bound target (``mod.attr``). Classification must resolve to Bridge /
ExternalBridge / install-source dig — never FactoryGap with
``observed=call-method:<attr>``.

Why a ratchet
-------------
#3939 fixed ``base64.urlsafe_b64encode`` (and kin) so vendor body dig does not
re-poison as method-frontier gaps when the *callee module's* imports were never
threaded into the dig ctx. Without this instrument the classification can
quietly regress to ``call-method:urlsafe_b64encode`` while logo / strip tests
still pass for other reasons.

Fixed fixture list: zero call-method FactoryGaps on the importable-module subset.
Non-importable receivers (``buffer.decode()``) stay on the method frontier —
that discrimination is part of the law, not a bug.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import FactoryGapEffect
from sugar_lift_py_tests.factory.build import FactoryBuildContext, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.call_sugar import (
    CallSugar,
    FactoryGapStrategy,
    _module_attr_import_target,
)


# Importable module.attr callsites — no surrounding ``import`` in build ctx.
# Receiver Name must be a real importable module (stdlib).
_IMPORTABLE_MODULE_ATTR_CALLSITES: tuple[str, ...] = (
    "base64.urlsafe_b64encode(b'x')",
    "base64.b64encode(b'x')",
    "json.dumps({})",
    "math.sqrt(4)",
    "os.getcwd()",
    "hashlib.md5(b'x')",
)

# Same shapes reachable via explicit import aliases (pre-#3939 path still valid).
_ALIASED_MODULE_ATTR_CALLSITES: tuple[tuple[str, dict[str, str]], ...] = (
    ("math.sqrt(4)", {"math": "math"}),
    ("base64.urlsafe_b64encode(b'x')", {"base64": "base64"}),
    ("json.dumps({})", {"json": "json"}),
)


@dataclass(frozen=True)
class _CallsiteClassification:
    expr: str
    import_target: str | None
    strategy_name: str
    target_name: str | None
    gap_observed: str | None
    reduce_gap_observed: str | None

    @property
    def is_call_method_factory_gap(self) -> bool:
        for observed in (self.gap_observed, self.reduce_gap_observed):
            if observed is not None and observed.startswith("call-method:"):
                return True
        return False


def _frag(expr: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(expr, mode="eval").body, "t.py")


def _classify(
    expr: str, *, import_aliases: dict[str, str] | None = None
) -> _CallsiteClassification:
    """Build + reduce one callsite; record strategy and any call-method gap label."""
    ctx = FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        import_aliases=import_aliases or {},
    )
    fragment = _frag(expr)
    body = ctx.build_body(fragment, SugarRole.TERM)
    assert isinstance(body.sugar, CallSugar), (
        f"{expr!r}: expected CallSugar, got {type(body.sugar).__name__}"
    )
    strategy = body.sugar.strategy
    strategy_name = type(strategy).__name__
    target_name: str | None = getattr(strategy, "target_name", None)
    gap_observed: str | None = None
    if isinstance(strategy, FactoryGapStrategy):
        gap_observed = strategy.info.observed

    reduce_gap_observed: str | None = None
    outcome = body.reduce(ctx)
    if isinstance(outcome, Incomplete) and isinstance(outcome.effect, FactoryGapEffect):
        reduce_gap_observed = outcome.effect.observed

    return _CallsiteClassification(
        expr=expr,
        import_target=_module_attr_import_target(fragment),
        strategy_name=strategy_name,
        target_name=target_name,
        gap_observed=gap_observed,
        reduce_gap_observed=reduce_gap_observed,
    )


def _census_importable_module_attr() -> list[_CallsiteClassification]:
    rows = [_classify(expr) for expr in _IMPORTABLE_MODULE_ATTR_CALLSITES]
    for expr, aliases in _ALIASED_MODULE_ATTR_CALLSITES:
        rows.append(_classify(expr, import_aliases=aliases))
    return rows


# --- ratchet: zero call-method FactoryGaps on the importable-module subset -------------


def test_importable_module_attr_call_method_factory_gap_count_is_zero() -> None:
    """Census count: no call-method:* FactoryGap among fixed importable module.attr sites."""
    rows = _census_importable_module_attr()
    call_method_gaps = [row for row in rows if row.is_call_method_factory_gap]
    assert len(call_method_gaps) == 0, (
        "importable module.attr regressed to call-method FactoryGap "
        f"(#3939): {[row.expr + '→' + (row.gap_observed or row.reduce_gap_observed or '?') for row in call_method_gaps]}"
    )


@pytest.mark.parametrize("expr", _IMPORTABLE_MODULE_ATTR_CALLSITES)
def test_importable_module_attr_resolves_import_target_not_call_method_gap(
    expr: str,
) -> None:
    """Each bare module.attr without import_aliases is an import target, not call-method gap."""
    row = _classify(expr)
    assert row.import_target is not None, (
        f"{expr!r}: _module_attr_import_target returned None "
        "(receiver Name should be importable)"
    )
    assert not row.is_call_method_factory_gap, (
        f"{expr!r}: FactoryGap observed call-method frontier; "
        f"strategy={row.strategy_name} gap={row.gap_observed!r} "
        f"reduce_gap={row.reduce_gap_observed!r} import_target={row.import_target!r}"
    )
    # Acceptable after #3939: Bridge / ExternalBridge / dig TypedEffect, or a
    # non-call-method FactoryGap when the *body* cannot open (call-local /
    # call-external). Method-frontier classification is the regression.
    if row.strategy_name == "FactoryGapStrategy":
        assert row.gap_observed is not None
        assert not row.gap_observed.startswith("call-method:"), row


@pytest.mark.parametrize("expr,aliases", _ALIASED_MODULE_ATTR_CALLSITES)
def test_aliased_module_attr_also_avoids_call_method_gap(
    expr: str, aliases: dict[str, str]
) -> None:
    """Import-alias path and module-attr path share the no-call-method law."""
    row = _classify(expr, import_aliases=aliases)
    assert not row.is_call_method_factory_gap, (
        f"{expr!r} with aliases={aliases}: call-method FactoryGap "
        f"strategy={row.strategy_name} gap={row.gap_observed!r}"
    )


def test_preferred_resolutions_include_bridge_or_external_for_stdlib() -> None:
    """At least one site in the census lands on Bridge or ExternalBridge (not all dig-fail).

    Guards a silent total collapse where every site becomes a non-method gap of
    another kind while the import-target path is dead.
    """
    rows = [_classify(expr) for expr in _IMPORTABLE_MODULE_ATTR_CALLSITES]
    bridge_like = {
        "BridgeStrategy",
        "ExternalBridgeStrategy",
    }
    landed = [row for row in rows if row.strategy_name in bridge_like]
    assert landed, (
        "expected at least one Bridge/ExternalBridge among importable module.attr "
        f"sites; got {[(r.expr, r.strategy_name, r.gap_observed) for r in rows]}"
    )


def test_base64_urlsafe_and_b64encode_are_never_call_method_gap() -> None:
    """Named #3939 victims: base64.urlsafe_b64encode / base64.b64encode."""
    for expr in (
        "base64.urlsafe_b64encode(b'provekit')",
        "base64.b64encode(b'provekit')",
    ):
        row = _classify(expr)
        assert row.import_target in {
            "base64.urlsafe_b64encode",
            "base64.b64encode",
        }, row
        assert not row.is_call_method_factory_gap, row
        assert row.gap_observed is None or not row.gap_observed.startswith(
            "call-method:"
        ), row


# --- discrimination: non-importable Name receiver stays call-method frontier ------------


def test_non_importable_name_receiver_still_call_method_frontier() -> None:
    """``buffer.decode()`` is not an importable module — still call-method:decode."""
    row = _classify("buffer.decode()")
    assert row.import_target is None
    assert row.strategy_name == "FactoryGapStrategy", row
    assert row.gap_observed == "call-method:decode" or row.reduce_gap_observed == (
        "call-method:decode"
    ), row


def test_module_attr_import_target_helper_on_fixtures() -> None:
    """Unit pin for ``_module_attr_import_target`` on the census fixtures."""
    for expr in _IMPORTABLE_MODULE_ATTR_CALLSITES:
        target = _module_attr_import_target(_frag(expr))
        assert target is not None and "." in target, (expr, target)
    assert _module_attr_import_target(_frag("buffer.decode()")) is None
    assert _module_attr_import_target(_frag("not_a_real_module_xyz.foo()")) is None

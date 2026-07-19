"""InstallSourceValueOracle: sole constructor for install-source floor values.

SourceOracle remains the sole interface for source text. Values wrap its CID;
they do not extend SourceOracle. Construction is correctness because no other
constructor exists for cited ``module.attr`` floors.
"""

from __future__ import annotations

import importlib
from dataclasses import replace

import pytest

from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.sugar.install_source_dig import (
    INSTALL_SOURCE_VALUE_ORACLE,
    resolve_install_source_value,
)


def _ctx() -> FactoryBuildContext:
    return FactoryBuildContext(filename="consumer.py", catalog=default_catalog())


def test_public_door_delegates_to_sole_constructor() -> None:
    """resolve_install_source_value is a name for InstallSourceValueOracle.resolve."""
    import inspect

    source = inspect.getsource(resolve_install_source_value)
    assert "INSTALL_SOURCE_VALUE_ORACLE.resolve" in source
    assert "_construct_install_source_value" not in source


def test_value_oracle_constructs_once_for_same_source_identity(
    tmp_path, monkeypatch
) -> None:
    """Second ask for the same CID+name is the same construction, not a redo."""
    (tmp_path / "oracle_once.py").write_text("ANSWER = 7\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    INSTALL_SOURCE_VALUE_ORACLE.clear()

    ctx = _ctx()
    first = resolve_install_source_value("oracle_once.ANSWER", ctx)
    constructs_after_first = INSTALL_SOURCE_VALUE_ORACLE.construct_count
    hits_after_first = INSTALL_SOURCE_VALUE_ORACLE.hit_count

    second = resolve_install_source_value("oracle_once.ANSWER", ctx)

    assert first == TermValue(7)
    assert second is first
    assert INSTALL_SOURCE_VALUE_ORACLE.construct_count == constructs_after_first
    assert INSTALL_SOURCE_VALUE_ORACLE.hit_count == hits_after_first + 1


def test_value_oracle_keys_through_source_oracle_cid(tmp_path, monkeypatch) -> None:
    """Identity wraps SourceOracle content CID + name — does not re-discover source."""
    (tmp_path / "oracle_cid.py").write_text("FLAG = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    INSTALL_SOURCE_VALUE_ORACLE.clear()

    key = INSTALL_SOURCE_VALUE_ORACLE.identity_key("oracle_cid.FLAG")
    assert key is not None
    source_cid, attr = key
    assert attr == "FLAG"
    assert source_cid != "target"
    assert len(source_cid) >= 32  # blake3 pin from SourceOracle


def test_value_oracle_cycle_guard_is_typed_loud(tmp_path, monkeypatch) -> None:
    """#5368: cycle detection is a terminal, never provisional opacity."""
    (tmp_path / "oracle_cycle.py").write_text("X = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    INSTALL_SOURCE_VALUE_ORACLE.clear()

    with pytest.raises(FactoryPanic) as panic:
        resolve_install_source_value(
            "oracle_cycle.X",
            _ctx(),
            _resolving=frozenset({"oracle_cycle.X"}),
        )
    assert panic.value.info.owner == "install_source_cycle_guard"
    assert panic.value.info.observed == "value-oracle cycle: oracle_cycle.X"
    key = INSTALL_SOURCE_VALUE_ORACLE.identity_key("oracle_cycle.X")
    assert key is not None
    assert INSTALL_SOURCE_VALUE_ORACLE.construct_count == 0
    assert not any(item[:2] == key for item in INSTALL_SOURCE_VALUE_ORACLE._table)


def test_value_oracle_does_not_publish_unresolved_none() -> None:
    """None is provisional: a later consumer must be allowed to reconstruct."""
    INSTALL_SOURCE_VALUE_ORACLE.clear()
    key = ("source-cid", "MAPPING", ())

    INSTALL_SOURCE_VALUE_ORACLE._publish(key, None)

    assert key not in INSTALL_SOURCE_VALUE_ORACLE._table


def test_stdlib_typing_literal_second_resolve_is_identity_hit() -> None:
    """Timeout-blob hot path: typing.Literal has one construction identity."""
    INSTALL_SOURCE_VALUE_ORACLE.clear()
    ctx = _ctx()
    first = resolve_install_source_value("typing.Literal", ctx)
    n = INSTALL_SOURCE_VALUE_ORACLE.construct_count
    second = resolve_install_source_value("typing.Literal", ctx)
    assert first is not None
    assert second is first
    assert INSTALL_SOURCE_VALUE_ORACLE.construct_count == n
    assert INSTALL_SOURCE_VALUE_ORACLE.hit_count >= 1


def test_same_module_prior_is_sole_constructor_across_sibling_resolves(
    tmp_path, monkeypatch
) -> None:
    """Module seed must not re-factory shared priors outside the value oracle.

    Eager defaults force FLAG into seed for each function; the second function
    must hit FLAG's construction identity rather than re-factory it.
    """
    (tmp_path / "sibling_seed.py").write_text(
        "FLAG = 40\n"
        "def left(x=FLAG):\n"
        "    return x\n"
        "def right(x=FLAG):\n"
        "    return x + 2\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    INSTALL_SOURCE_VALUE_ORACLE.clear()

    ctx = _ctx()
    left = resolve_install_source_value("sibling_seed.left", ctx)
    after_left = INSTALL_SOURCE_VALUE_ORACLE.construct_count
    right = resolve_install_source_value("sibling_seed.right", ctx)
    after_right = INSTALL_SOURCE_VALUE_ORACLE.construct_count

    assert left is not None and right is not None
    # FLAG + left constructed; second seed hits FLAG, only right is new.
    assert after_left >= 2  # FLAG and left
    assert after_right == after_left + 1  # only right; FLAG is identity hit
    assert INSTALL_SOURCE_VALUE_ORACLE.hit_count >= 1


def test_value_oracle_wrong_context_rebuilds_and_matches_fresh_second(
    tmp_path, monkeypatch
) -> None:
    """A recognition-context change is a cache miss, never a stale success.

    Consumer temporal is *not* a recognition input for install-source values
    (construct reseeds from empty). Partition on a field construct consumes —
    here ``name_resolver`` — so a different recognition context rebuilds.
    """
    (tmp_path / "oracle_context.py").write_text("ANSWER = 7\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    INSTALL_SOURCE_VALUE_ORACLE.clear()

    ctx_one = _ctx()
    ctx_two = replace(_ctx(), name_resolver="partition-b")

    import sugar_lift_py_tests.sugar.install_source_dig as module

    def construct(_target, ctx, *, _resolving=frozenset()):
        return TermValue(id(ctx.name_resolver) if ctx.name_resolver is not None else 0)

    monkeypatch.setattr(module, "_construct_install_source_value", construct)
    first = resolve_install_source_value("oracle_context.ANSWER", ctx_one)
    second = resolve_install_source_value("oracle_context.ANSWER", ctx_two)
    constructs = INSTALL_SOURCE_VALUE_ORACLE.construct_count

    INSTALL_SOURCE_VALUE_ORACLE.clear()
    fresh_second = resolve_install_source_value("oracle_context.ANSWER", ctx_two)

    assert second != first
    assert constructs == 2
    assert second == fresh_second


def test_value_oracle_ignores_consumer_temporal_partition(
    tmp_path, monkeypatch
) -> None:
    """Module-seed frames must not re-factory the same CID+name.

    ``_ctx_with_required_module_bindings`` opens every seed with a fresh empty
    temporal (and may bind priors). Consumer temporal identity is discarded
    before build_body, so successive seed frames hit the value oracle.
    """
    (tmp_path / "seed_frame.py").write_text("FLAG = 3\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    INSTALL_SOURCE_VALUE_ORACLE.clear()

    from sugar_lift_py_tests.temporal import TemporalContext

    base = _ctx()
    seed_a = replace(
        base,
        temporal=TemporalContext.empty(),
        module_temporal=TemporalContext.empty(),
    )
    seed_b = replace(
        base,
        temporal=TemporalContext.empty().bind_value("prior", TermValue(1)),
        module_temporal=TemporalContext.empty(),
    )

    first = resolve_install_source_value("seed_frame.FLAG", seed_a)
    constructs = INSTALL_SOURCE_VALUE_ORACLE.construct_count
    second = resolve_install_source_value("seed_frame.FLAG", seed_b)

    assert first == TermValue(3)
    assert second is first
    assert INSTALL_SOURCE_VALUE_ORACLE.construct_count == constructs
    assert INSTALL_SOURCE_VALUE_ORACLE.hit_count >= 1


def test_stdlib_typing_seed_frames_reuse_tp_cache_construction() -> None:
    """stata module_seed cascade tip: typing._tp_cache is one identity.

    Product hang re-entered StatementFunctionDefSugar for typing.py:376 under
    successive dig.module_seed frames. Consumer temporal must not multiply
    construction of the same stdlib source name.
    """
    from sugar_lift_py_tests.temporal import TemporalContext

    INSTALL_SOURCE_VALUE_ORACLE.clear()
    base = _ctx()
    frames = [
        replace(
            base,
            temporal=TemporalContext.empty(),
            module_temporal=TemporalContext.empty(),
        )
        for _ in range(5)
    ]
    # Distinct bound frames (as after seeding prior imports) still share.
    frames.append(
        replace(
            base,
            temporal=TemporalContext.empty().bind_value("marker", TermValue(9)),
            module_temporal=TemporalContext.empty(),
        )
    )

    first = resolve_install_source_value("typing._tp_cache", frames[0])
    constructs = INSTALL_SOURCE_VALUE_ORACLE.construct_count
    assert first is not None
    assert constructs >= 1

    for frame in frames[1:]:
        again = resolve_install_source_value("typing._tp_cache", frame)
        assert again is first

    assert INSTALL_SOURCE_VALUE_ORACLE.construct_count == constructs
    assert INSTALL_SOURCE_VALUE_ORACLE.hit_count >= len(frames) - 1


def test_class_bases_negative_is_not_published_and_context_is_partitioned(
    monkeypatch,
):
    """Failed context cannot poison a later successful class-bases construction."""
    import sugar_lift_py_tests.sugar.install_source_dig as module

    module._CLASS_BASES_CACHE.clear()
    calls = []

    def resolve(_qualified, _resolving, ctx=None):
        calls.append(ctx)
        return None if ctx.name_resolver == "fail" else ("builtins.object",)

    monkeypatch.setattr(module, "_resolve_install_source_class_bases", resolve)
    failed = replace(_ctx(), name_resolver="fail")
    succeeded = _ctx()
    assert module.resolve_install_source_class_bases("example.C", failed) is None
    assert module.resolve_install_source_class_bases("example.C", succeeded) == (
        "builtins.object",
    )
    assert len(calls) == 2

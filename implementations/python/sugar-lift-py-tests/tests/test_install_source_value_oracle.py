"""InstallSourceValueOracle: sole constructor for install-source floor values.

SourceOracle remains the sole interface for source text. Values wrap its CID;
they do not extend SourceOracle. Construction is correctness because no other
constructor exists for cited ``module.attr`` floors.
"""

from __future__ import annotations

import importlib

from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
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

    first = resolve_install_source_value("oracle_once.ANSWER", _ctx())
    constructs_after_first = INSTALL_SOURCE_VALUE_ORACLE.construct_count
    hits_after_first = INSTALL_SOURCE_VALUE_ORACLE.hit_count

    second = resolve_install_source_value("oracle_once.ANSWER", _ctx())

    assert first == TermValue(7)
    assert second is first
    assert INSTALL_SOURCE_VALUE_ORACLE.construct_count == constructs_after_first
    assert INSTALL_SOURCE_VALUE_ORACLE.hit_count == hits_after_first + 1


def test_value_oracle_keys_through_source_oracle_cid(
    tmp_path, monkeypatch
) -> None:
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


def test_value_oracle_does_not_publish_cycle_breaks(
    tmp_path, monkeypatch
) -> None:
    """Cycle None is not published as the system's answer for that name."""
    (tmp_path / "oracle_cycle.py").write_text("X = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    INSTALL_SOURCE_VALUE_ORACLE.clear()

    cycle = resolve_install_source_value(
        "oracle_cycle.X",
        _ctx(),
        _resolving=frozenset({"oracle_cycle.X"}),
    )
    assert cycle is None
    key = INSTALL_SOURCE_VALUE_ORACLE.identity_key("oracle_cycle.X")
    assert key is not None
    assert INSTALL_SOURCE_VALUE_ORACLE.construct_count == 0
    assert key not in INSTALL_SOURCE_VALUE_ORACLE._table


def test_stdlib_typing_literal_second_resolve_is_identity_hit() -> None:
    """Timeout-blob hot path: typing.Literal has one construction identity."""
    INSTALL_SOURCE_VALUE_ORACLE.clear()
    first = resolve_install_source_value("typing.Literal", _ctx())
    n = INSTALL_SOURCE_VALUE_ORACLE.construct_count
    second = resolve_install_source_value("typing.Literal", _ctx())
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

    left = resolve_install_source_value("sibling_seed.left", _ctx())
    after_left = INSTALL_SOURCE_VALUE_ORACLE.construct_count
    right = resolve_install_source_value("sibling_seed.right", _ctx())
    after_right = INSTALL_SOURCE_VALUE_ORACLE.construct_count

    assert left is not None and right is not None
    # FLAG + left constructed; second seed hits FLAG, only right is new.
    assert after_left >= 2  # FLAG and left
    assert after_right == after_left + 1  # only right; FLAG is identity hit
    assert INSTALL_SOURCE_VALUE_ORACLE.hit_count >= 1

from __future__ import annotations

import importlib

from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import CallSiteValue, TermValue
from sugar_lift_py_tests.sugar.install_source_dig import resolve_install_source_value
from sugar_lift_py_tests.temporal import TemporalContext


def _ctx() -> FactoryBuildContext:
    return FactoryBuildContext(filename="consumer.py", catalog=default_catalog())


def test_install_source_value_control_constructs_direct_literal(
    tmp_path, monkeypatch
) -> None:
    """Control twin: a directly literal module value already constructs."""
    (tmp_path / "direct_value.py").write_text("ANSWER = 42\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    resolved = resolve_install_source_value("direct_value.ANSWER", _ctx())

    assert resolved == TermValue(42)


def test_install_source_value_constructs_required_prior_module_global(
    tmp_path, monkeypatch
) -> None:
    """Bad twin: a resolved assignment must inherit its module's prior globals."""
    (tmp_path / "dependent_value.py").write_text(
        "FLAG = 40\nANSWER = FLAG + 2\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    resolved = resolve_install_source_value("dependent_value.ANSWER", _ctx())

    assert resolved == TermValue(42)


def test_defining_module_global_shadows_consumer_temporal(
    tmp_path, monkeypatch
) -> None:
    """Bad twin: module construction must not borrow a same-named consumer value."""
    (tmp_path / "lexical_value.py").write_text(
        "FLAG = 40\nANSWER = FLAG + 2\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    consumer = FactoryBuildContext(
        filename="consumer.py",
        catalog=default_catalog(),
        temporal=TemporalContext.empty().bind_value("FLAG", TermValue(1000)),
    )

    resolved = resolve_install_source_value("lexical_value.ANSWER", consumer)

    assert resolved == TermValue(42)


def test_install_source_value_does_not_construct_unneeded_prior_global(
    tmp_path, monkeypatch
) -> None:
    """Control twin: need-driven seeding must not let unrelated gaps poison it."""
    (tmp_path / "need_driven_value.py").write_text(
        "UNRELATED = lambda *, x: x\nFLAG = 40\nANSWER = FLAG + 2\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    resolved = resolve_install_source_value("need_driven_value.ANSWER", _ctx())

    assert resolved == TermValue(42)


def test_install_source_value_leaves_runtime_selected_prerequisite_unresolved(
    tmp_path, monkeypatch
) -> None:
    """A runtime conditional is an effect boundary, never a value to force-read."""
    (tmp_path / "runtime_selected_value.py").write_text(
        "import os\nFLAG = 40 if os else 41\nANSWER = FLAG + 2\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    resolved = resolve_install_source_value("runtime_selected_value.ANSWER", _ctx())

    assert resolved is None


def test_stdlib_future_annotations_constructs_compiler_flag_from_module_source() -> (
    None
):
    """The pandas import shape resolves without fabricating the compiler flag."""
    resolved = resolve_install_source_value("__future__.annotations", _ctx())

    assert isinstance(resolved, CallSiteValue)
    assert resolved.target_name == "_Feature"
    assert resolved.arg_values[2] == TermValue(0x1000000)

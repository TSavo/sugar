from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.idd.collect_getattr_default_context_frontier import (
    collect_getattr_default_context_frontier,
    render_text,
)

ROOT = Path(__file__).resolve().parents[4]


def test_context_getattr_default_frontier_is_stable_zero() -> None:
    report = collect_getattr_default_context_frontier(ROOT)

    assert report.r == {
        "ctx": 0,
        "source": 0,
        "temporal": 0,
        "total": 0,
    }, render_text(report)
    assert report.is_zero


def test_context_getattr_default_frontier_flags_planted_context_default(
    tmp_path: Path,
) -> None:
    kit_src = tmp_path / "src" / "sugar_lift_py_tests" / "sugar"
    kit_src.mkdir(parents=True)
    (kit_src / "planted_context_default.py").write_text(
        "def leak(ctx):\n" "    return getattr(ctx, 'name_resolver', {})\n",
        encoding="utf-8",
    )

    report = collect_getattr_default_context_frontier(tmp_path)

    assert report.r == {
        "ctx": 1,
        "source": 0,
        "temporal": 0,
        "total": 1,
    }
    assert len(report.sites) == 1
    site = report.sites[0]
    assert site.path == "sugar/planted_context_default.py"
    assert site.receiver == "ctx"
    assert site.field == "name_resolver"
    assert site.observed == "getattr(ctx, 'name_resolver', {})"
    assert site.fix == (
        "replace with ctx.name_resolver; declare name_resolver on the owning "
        "context with an explicit default, or raise before this access if "
        "absence is a bug"
    )


def test_context_getattr_default_frontier_ignores_non_context_reflection(
    tmp_path: Path,
) -> None:
    kit_src = tmp_path / "src" / "sugar_lift_py_tests" / "factory"
    kit_src.mkdir(parents=True)
    (kit_src / "ast_position.py").write_text(
        "def line_for(node):\n" "    return getattr(node, 'lineno', 0)\n",
        encoding="utf-8",
    )

    report = collect_getattr_default_context_frontier(tmp_path)

    assert report.is_zero

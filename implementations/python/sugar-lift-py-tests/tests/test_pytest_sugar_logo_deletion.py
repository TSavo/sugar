"""#5603: pytest fail/skip/raises logo owns-paths are DELETED.

Bucket (b): externally-loaded testing kit/bridge contract — not hard-coded
vendor spelling. Deletion-verification mirrors the SQLAlchemy #5613 pattern:
prove the logo compare is gone; authentic-looking forms stay loud.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.sugar.pytest_fail_sugar import PytestFailSugar
from sugar_lift_py_tests.sugar.pytest_raises_with_sugar import (
    PytestRaisesWithSugar,
    _is_raises_context,
)
from sugar_lift_py_tests.sugar.pytest_skip_sugar import PytestSkipSugar


def _call_site(source: str, leaf: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == leaf)
            or (isinstance(node.func, ast.Name) and node.func.id == leaf)
        )
    )
    return SourceFragment.from_node(call, f"{leaf}_call.py", source=source)


def _with_site(source: str) -> SourceFragment:
    with_node = next(
        node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.With)
    )
    return SourceFragment.from_node(with_node, "raises_with.py", source=source)


def test_pytest_fail_logo_owns_is_deleted() -> None:
    """Deletion-verification: owns never authenticates via ``pytest.fail`` spelling."""
    source = (
        "import pytest\n"
        "\n"
        "def test_it():\n"
        "    pytest.fail('nope')\n"
    )
    site = _call_site(source, "fail")
    assert PytestFailSugar.owns(site) is False
    # Source of owns must not reintroduce a Compare against a vendor spelling.
    owns_src = inspect.getsource(PytestFailSugar.owns)
    assert "call_qualified_target_name" not in owns_src
    assert "==" not in owns_src


def test_pytest_skip_logo_owns_is_deleted() -> None:
    source = (
        "import pytest\n"
        "\n"
        "def test_it():\n"
        "    pytest.skip('nope')\n"
    )
    site = _call_site(source, "skip")
    assert PytestSkipSugar.owns(site) is False
    owns_src = inspect.getsource(PytestSkipSugar.owns)
    assert "call_qualified_target_name" not in owns_src
    assert "==" not in owns_src


def test_pytest_raises_logo_context_is_deleted() -> None:
    source = (
        "import pytest\n"
        "\n"
        "def test_it():\n"
        "    with pytest.raises(ValueError):\n"
        "        raise ValueError('x')\n"
    )
    with_site = _with_site(source)
    assert PytestRaisesWithSugar.owns(with_site) is False
    ctx = with_site.with_context_expr(0)
    assert _is_raises_context(ctx) is False
    helper_src = inspect.getsource(_is_raises_context)
    # No vendor-root spelling and no Compare on a name id in the body.
    assert "pytest" not in helper_src
    assert "name_id" not in helper_src
    assert "==" not in helper_src


@pytest.mark.parametrize(
    ("source", "leaf", "owner"),
    [
        (
            "import pytest\n\ndef test_it():\n    pytest.fail('x')\n",
            "fail",
            PytestFailSugar,
        ),
        (
            "import pytest\n\ndef test_it():\n    pytest.skip('x')\n",
            "skip",
            PytestSkipSugar,
        ),
        (
            "from pytest import fail\n\ndef test_it():\n    fail('x')\n",
            "fail",
            PytestFailSugar,
        ),
        (
            "from pytest import skip\n\ndef test_it():\n    skip('x')\n",
            "skip",
            PytestSkipSugar,
        ),
    ],
)
def test_authentic_looking_fail_skip_stays_outside_logo_owner(
    source: str, leaf: str, owner
) -> None:
    """Even import-looking forms must not select the logo-deleted Sugar."""
    site = _call_site(source, leaf)
    assert owner.owns(site) is False
    ctx = FactoryBuildContext(filename=f"{leaf}_call.py", catalog=default_catalog())
    built = build_node(site, filename=f"{leaf}_call.py", role=SugarRole.TERM, ctx=ctx)
    assert built.audit_row.selected != owner.__name__


def test_authentic_looking_pytest_raises_with_stays_loud() -> None:
    source = (
        "import pytest\n"
        "\n"
        "def test_it():\n"
        "    with pytest.raises(ValueError):\n"
        "        raise ValueError('x')\n"
    )
    site = _with_site(source)
    assert PytestRaisesWithSugar.owns(site) is False
    ctx = FactoryBuildContext(filename="raises_with.py", catalog=default_catalog())
    # With may fall through to WithSugar or panic — never PytestRaisesWithSugar.
    try:
        built = build_node(
            site, filename="raises_with.py", role=SugarRole.STATEMENT, ctx=ctx
        )
        assert built.audit_row.selected != "PytestRaisesWithSugar"
    except FactoryPanic as raised:
        assert raised.info.observed in {"With", "Call"}


@pytest.mark.parametrize(
    "source",
    [
        # Lookalike: local name pytest, not the package
        (
            "class pytest:\n"
            "    @staticmethod\n"
            "    def fail(msg):\n"
            "        raise RuntimeError(msg)\n"
            "\n"
            "def test_it():\n"
            "    pytest.fail('x')\n"
        ),
        (
            "def fail(msg):\n"
            "    raise RuntimeError(msg)\n"
            "\n"
            "def test_it():\n"
            "    fail('x')\n"
        ),
        (
            "class pytest:\n"
            "    @staticmethod\n"
            "    def raises(exc):\n"
            "        return nullcontext()\n"
            "\n"
            "def test_it():\n"
            "    with pytest.raises(ValueError):\n"
            "        pass\n"
        ),
    ],
)
def test_lookalike_fail_skip_raises_never_owned_by_logo_sugar(source: str) -> None:
    """Lying twin: lookalikes must not authenticate even if logos returned."""
    if "with " in source:
        site = _with_site(source)
        assert PytestRaisesWithSugar.owns(site) is False
    elif "skip" in source:
        site = _call_site(source, "skip")
        assert PytestSkipSugar.owns(site) is False
    else:
        site = _call_site(source, "fail")
        assert PytestFailSugar.owns(site) is False

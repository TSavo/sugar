"""Enumerate panics must not erase the authenticated function denominator.

Night finding: _json.py constructed 49 functions, then populate hit SNW on a
transitive decorated FunctionDef and recensus returned BEFORE functionsTotal,
banking 0 for a file that just built ~50. 14/14 sampled SNW files had fns>0
after SourceFile. The refusal stays loud; the zero-function board answer dies.

The current consumer authenticates the AST function population before opening
the typed tree.  Even an open-path panic therefore preserves that denominator;
zero is not an honest answer for a parseable file containing a function.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root
from sugar_source_tree.panic import SugarNotWritten

_SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"


def _load(name: str):
    path = _SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_populate_snw_preserves_function_denominator(
    tmp_path: Path, monkeypatch
) -> None:
    """SourceFile succeeds with N functions; populate SNWs; bank N + residual."""
    module = _load("recensus_enumerate_consumer")
    path = tmp_path / "target.py"
    path.write_text(
        "def one():\n"
        "    return 1\n"
        "\n"
        "def two():\n"
        "    return 2\n"
        "\n"
        "def three():\n"
        "    return 3\n",
        encoding="utf-8",
    )

    def boom_populate(source_file, **_k):
        # Real coordinate required by SugarNotWritten — use the constructed root.
        blame = source_file.root.fragment
        raise SugarNotWritten(
            blame=blame,
            owner="module function definition execution",
            observed="decorated FunctionDef has no completed publication",
            requested="the exact final decorated function Floor",
            fix="execute and authenticate the function decorator chain",
        )

    monkeypatch.setattr(
        "sugar_lift_python_source.manager_summary_derivation."
        "populate_source_derived_resource_refs",
        boom_populate,
    )

    row = module.measure_file_via_enumerate(
        workspace_root=tmp_path,
        file_rel="target.py",
        contract_refs={},
    )

    # The product gap is the first terminal, never an instrument failure.
    assert row["category"] == "panic"
    assert row["panic"]["owner"] == "module function definition execution"
    # The independently authenticated population survives even though D2 could
    # not return its function mementos after populate raised.
    assert row["functionsTotal"] == 3
    assert row["functionsEnumerated"] == 0
    assert row["functionsNotEnumerated"] == 3


def test_open_snw_preserves_authenticated_ast_function_denominator(
    tmp_path: Path, monkeypatch
) -> None:
    """Open-path SNW preserves the AST-authenticated function population."""
    module = _load("recensus_enumerate_consumer")
    path = tmp_path / "broken.py"
    path.write_text("def a():\n    return 1\n", encoding="utf-8")

    # Plant a real fragment via a tiny successful SourceFile first, then
    # make SourceFile.__init__ raise with that coordinate as blame.
    seed = tmp_path / "seed.py"
    seed.write_text("x = 1\n", encoding="utf-8")
    from sugar_source_tree.tree import SourceFile as SF

    seed_sf = SF.from_path(seed)
    blame = seed_sf.root.fragment

    def boom_init(self, *_a, **_k):
        raise SugarNotWritten(
            blame=blame,
            owner="open-path-gap",
            observed="SourceFile never constructed",
            requested="a constructed module",
            fix="repair open",
        )

    import sugar_source_tree.tree as tree_mod

    monkeypatch.setattr(tree_mod.SourceFile, "__init__", boom_init)
    row = module.measure_file_via_enumerate(
        workspace_root=tmp_path,
        file_rel="broken.py",
        contract_refs={},
    )
    assert row["category"] == "panic"
    assert row["panic"]["owner"] == "open-path-gap"
    assert row["functionsTotal"] == 1
    assert row["functionsEnumerated"] == 0
    assert row["functionsNotEnumerated"] == 1

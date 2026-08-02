"""Populate SNW must not erase a successful SourceFile function denominator.

Night finding: _json.py constructed 49 functions, then populate hit SNW on a
transitive decorated FunctionDef and recensus returned BEFORE functionsTotal,
banking 0 for a file that just built ~50. 14/14 sampled SNW files had fns>0
after SourceFile. The refusal stays loud; the zero-function board answer dies.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sugar_source_tree.panic import SugarNotWritten

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


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
    module = _load("control_effect_recensus")
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

    row = module._measure_file(
        path,
        relative="target.py",
        workspace_root=tmp_path,
        contract_refs={},
    )

    assert row["category"] == "completed"
    # Successful construction survives.
    assert row["functionsTotal"] == 3
    assert row["functionsEnumerated"] == 3
    assert row["functionsNotEnumerated"] == 0
    # Populate gap stays LOUD as its own residual — not a zero-function lie.
    assert row["R_populate_residuals"] == 1
    residuals = row["populateResiduals"]
    assert len(residuals) == 1
    assert residuals[0]["phase"] == "populate"
    assert residuals[0]["owner"] == "module function definition execution"
    assert "decorated FunctionDef" in residuals[0]["observed"]
    # Family key is owner-qualified so the refusal is named in families too.
    assert row["families"].get(
        "populate:module function definition execution", 0
    ) >= 1


def test_open_snw_still_zero_functions_when_sourcefile_never_builds(
    tmp_path: Path, monkeypatch
) -> None:
    """Open-path SNW (no SourceFile) remains a true empty denominator."""
    module = _load("control_effect_recensus")
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
    row = module._measure_file(
        path, relative="broken.py", workspace_root=tmp_path, contract_refs={}
    )
    assert row["functionsTotal"] == 0
    assert row["R_populate_residuals"] == 0
    assert row["families"].get("SugarNotWritten", 0) >= 1

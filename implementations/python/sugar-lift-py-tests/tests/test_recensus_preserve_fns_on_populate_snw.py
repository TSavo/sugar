"""Enumerate panics must not erase the authenticated function denominator.

The current consumer authenticates the AST function population before opening
the typed tree.  Even an open-path panic therefore preserves that denominator;
zero is not an honest answer for a parseable file containing a function.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root
from sugar_source_tree.panic import SugarNotWritten

_SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"


def _load(name: str):
    """The script ``name``, loaded as the sibling recensus tests load it: its
    scripts directory on the path, since the consumer imports the board
    composer (``compose_control_effect_board``) beside it.  Without it this
    test passed only when an earlier test in the same process had put the
    directory there."""
    path = _SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec.loader.exec_module(module)
    return module


def test_open_snw_preserves_authenticated_ast_function_denominator(
    tmp_path: Path, monkeypatch
) -> None:
    """Open-path SNW preserves the AST-authenticated function population."""
    module = _load("recensus_enumerate_consumer")
    path = tmp_path / "broken.py"
    path.write_text("def a():\n    return 1\n", encoding="utf-8")

    # Plant a real fragment via a tiny successful SourceFile first, then make
    # the residency door every open walks (``_open_at_seat`` ->
    # ``_source_file_from_identity``) raise with that coordinate as blame.
    seed = tmp_path / "seed.py"
    seed.write_text("x = 1\n", encoding="utf-8")
    from sugar_lift_py_tests.lift_rpc import _open_at_seat

    seed_sf = _open_at_seat(seed, root=tmp_path)
    blame = seed_sf.root.fragment
    fired = {"n": 0}

    def boom_open(*_a, **_k):
        fired["n"] += 1
        raise SugarNotWritten(
            blame=blame,
            owner="open-path-gap",
            observed="SourceFile never constructed",
            requested="a constructed module",
            fix="repair open",
        )

    import sugar_source_tree.process_resident_file as residency

    monkeypatch.setattr(residency, "_source_file_from_identity", boom_open)
    row = module.measure_file_via_enumerate(
        workspace_root=tmp_path,
        file_rel="broken.py",
    )
    # The plant must be on the path the open walks; a move of the entry turns
    # this red instead of letting the row below pass for another reason.
    assert fired["n"] > 0
    assert row["category"] == "panic"
    assert row["panic"]["owner"] == "open-path-gap"
    assert row["functionsTotal"] == 1
    assert row["functionsEnumerated"] == 0
    assert row["functionsNotEnumerated"] == 1

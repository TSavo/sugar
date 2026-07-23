# SPDX-License-Identifier: MIT OR Apache-2.0
import os
from pathlib import Path
import sys

import pytest

from sugar_lift_python_source import typed_node_api as typed
from sugar_lift_python_source.bind_lifter import (
    _body_source_locator,
    lift_source,
    source_memento_of,
)
from sugar_lift_python_source.ast_template import function_param_names, stmt_to_template
from sugar_lift_python_source.canonical import blake3_512_of, template_cid_of_json
from sugar_lift_python_source.source_oracle import (
    SourceUnavailable,
    installed_module_source,
    resolve_source_memento,
)


def _memento(tmp_path: Path, rel: str, source: str) -> dict:
    """Lift `source` and return a SourceMemento: locus + CIDs, ZERO content."""
    (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(source, encoding="utf-8")
    entry = next(
        e
        for e in lift_source(source, rel, layer="library-bindings").ir
        if e.get("kind") == "library-sugar-binding-entry"
    )
    bs = entry["body_source"]
    return {
        "source_function_name": entry["source_function_name"],
        "file": bs["file"],
        "span": bs["span"],
        "source_cid": bs["source_cid"],
        "template_cid": bs["template_cid"],
    }


def test_oracle_resolves_when_source_aligns(tmp_path: Path) -> None:
    src = "def add(x, y):\n    return x + y\n"
    memento = _memento(tmp_path, "pkg/calc.py", src)
    assert "body_text" not in memento and "ast_template" not in memento

    out = resolve_source_memento(str(tmp_path), memento)
    assert out["body_text"] == "return x + y"
    assert out["ast_template"] is not None
    # the oracle is the AST-walk site: recomputed CIDs equal the pinned ones
    assert out["source_cid"] == memento["source_cid"]
    assert out["template_cid"] == memento["template_cid"]


def test_installed_source_resolves_nested_module_without_importing_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "outer"
    child = package / "inner"
    child.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (child / "__init__.py").write_text("", encoding="utf-8")
    (child / "module.py").write_text("VALUE = 7\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("outer", "outer.inner", "outer.inner.module"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    installed_module_source.cache_clear()

    resolved = installed_module_source("outer.inner.module")

    assert resolved is not None
    source, filename, _cid = resolved
    assert source == "VALUE = 7\n"
    assert filename.endswith("outer/inner/module.py")


def test_installed_source_same_bytes_different_seats_do_not_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "seatpkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mod.py").write_text("VALUE = 7\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    installed_module_source.cache_clear()
    first = installed_module_source("seatpkg.mod", source_seat="seat/one.py")
    second = installed_module_source("seatpkg.mod", source_seat="seat/two.py")
    assert first is not None and second is not None
    assert first is not second
    assert first[0] == second[0] and first[2] == second[2]


def test_installed_source_content_drift_is_not_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive cache hits revalidate by source CID after re-reading disk."""
    package = tmp_path / "driftpkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    module_path = package / "mod.py"
    module_path.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    installed_module_source.cache_clear()

    first = installed_module_source("driftpkg.mod")
    assert first is not None
    assert first[0] == "VALUE = 1\n"
    same = installed_module_source("driftpkg.mod")
    assert same is first

    module_path.write_text("VALUE = 2\n", encoding="utf-8")
    second = installed_module_source("driftpkg.mod")
    assert second is not None
    assert second[0] == "VALUE = 2\n"
    assert second is not first


def test_installed_source_absence_is_not_negative_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A miss must not poison a later successful construction of the same name."""
    package = tmp_path / "latepkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    installed_module_source.cache_clear()

    assert installed_module_source("latepkg.mod") is None
    (package / "mod.py").write_text("VALUE = 9\n", encoding="utf-8")
    # PathFinder may have cached the prior miss; invalidate so discovery is honest.
    import importlib

    importlib.invalidate_caches()
    resolved = installed_module_source("latepkg.mod")
    assert resolved is not None
    assert resolved[0] == "VALUE = 9\n"


def test_oracle_resolves_dotted_method_envelope_name(tmp_path: Path) -> None:
    src = 'class Algo:\n    def get_signature(self, key, value):\n        return b""\n'
    rel = "pkg/signer.py"
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src, encoding="utf-8")
    tree = typed.parse(src, filename=rel)
    fn = next(
        n
        for n in typed.walk(tree)
        if isinstance(n, (typed.FunctionDef, typed.AsyncFunctionDef))
        and n.name == "get_signature"
    )
    full = _body_source_locator(fn, rel, src.splitlines(keepends=True))
    memento = dict(source_memento_of(full))
    memento["source_function_name"] = "Algo.get_signature"

    out = resolve_source_memento(str(tmp_path), memento)

    assert out["body_text"] == 'return b""'
    assert out["source_cid"] == memento["source_cid"]
    assert out["template_cid"] == memento["template_cid"]


def test_oracle_resolves_statement_memento_exactly(tmp_path: Path) -> None:
    src = (
        "def test_array_map_sugar():\n"
        "    assert [1, 2, 3].map(lambda x: x + 1) == [2, 3, 4]\n"
    )
    rel = "tests/test_array_map.py"
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src, encoding="utf-8")
    tree = typed.parse(src, filename=rel)
    fn = tree.body[0]
    assert isinstance(fn, typed.FunctionDef)
    stmt = fn.body[0]
    source = "assert [1, 2, 3].map(lambda x: x + 1) == [2, 3, 4]"
    template = stmt_to_template(stmt, function_param_names(fn))
    memento = {
        "kind": "source-memento",
        "source_kind": "python.ast-stmt",
        "source_function_name": "test_array_map_sugar",
        "file": rel,
        "span": {
            "start_line": stmt.lineno,
            "start_col": stmt.col_offset,
            "end_line": stmt.end_lineno,
            "end_col": stmt.end_col_offset,
        },
        "source_cid": blake3_512_of(source.encode("utf-8")),
        "template_cid": template_cid_of_json(template),
    }

    out = resolve_source_memento(str(tmp_path), memento)

    assert out["body_text"] == source
    assert out["source_cid"] == memento["source_cid"]
    assert out["template_cid"] == memento["template_cid"]


def test_oracle_refuses_loudly_when_source_drifts(tmp_path: Path) -> None:
    memento = _memento(tmp_path, "pkg/calc.py", "def add(x, y):\n    return x + y\n")
    # tamper the on-disk source: the bytes you'd run are no longer the bytes proven
    (tmp_path / "pkg" / "calc.py").write_text(
        "def add(x, y):\n    return x - y\n", encoding="utf-8"
    )
    with pytest.raises(SourceUnavailable) as exc:
        resolve_source_memento(str(tmp_path), memento)
    assert "misaligned" in str(exc.value)


def test_lean_lift_omits_inline_source_but_keeps_cids(tmp_path: Path) -> None:
    src = "def add(x, y):\n    return x + y\n"
    (tmp_path / "calc.py").write_text(src, encoding="utf-8")
    os.environ["SUGAR_LEAN_SOURCE"] = "1"
    try:
        entry = next(
            e
            for e in lift_source(src, "calc.py", layer="library-bindings").ir
            if e.get("kind") == "library-sugar-binding-entry"
        )
    finally:
        os.environ.pop("SUGAR_LEAN_SOURCE", None)
    bs = entry["body_source"]
    assert "body_text" not in bs and "ast_template" not in bs  # signs the real code
    assert bs["source_cid"] and bs["template_cid"] and bs["span"]  # by CID + locus


# ---------------------------------------------------------------------------
# Path-addressed doors (#5940 tree): path_source / resolve_span_memento
# ---------------------------------------------------------------------------


def test_path_source_mints_the_identity_triple(tmp_path: Path) -> None:
    from sugar_lift_python_source.source_oracle import path_source

    p = tmp_path / "m.py"
    p.write_text("x = 1\n", encoding="utf-8")
    source, filename, cid = path_source(str(p))
    assert source == "x = 1\n"
    assert filename == str(p)
    assert cid == blake3_512_of(b"x = 1\n")


def test_path_source_refuses_loudly_never_none(tmp_path: Path) -> None:
    from sugar_lift_python_source.source_oracle import path_source

    with pytest.raises(SourceUnavailable):
        path_source(str(tmp_path / "absent.py"))
    bad = tmp_path / "bad.py"
    bad.write_bytes(b"\xff\xfe\x00x")
    with pytest.raises(SourceUnavailable):
        path_source(str(bad))


def test_resolve_span_memento_recomputes_or_refuses(tmp_path: Path) -> None:
    from sugar_lift_python_source.source_oracle import (
        path_source,
        resolve_span_memento,
    )

    p = tmp_path / "m.py"
    p.write_text("a = 1\nb = 2\n", encoding="utf-8")
    source, filename, cid = path_source(str(p))
    memento = {
        "file": filename,
        "span": {"start": 6, "end": 11},
        "source_cid": cid,
        "cid": blake3_512_of(b"b = 2"),
    }
    resolved = resolve_span_memento(memento)
    assert resolved["segment"] == "b = 2"
    assert resolved["source_cid"] == cid

    p.write_text("a = 1\nc = 3\n", encoding="utf-8")
    with pytest.raises(SourceUnavailable):
        resolve_span_memento(memento)

# SPDX-License-Identifier: Apache-2.0
import ast
import os
from pathlib import Path

import pytest

from sugar_lift_python_source.bind_lifter import (
    _body_source_locator,
    lift_source,
    source_memento_of,
)
from sugar_lift_python_source.ast_template import function_param_names, stmt_to_template
from sugar_lift_python_source.canonical import blake3_512_of, template_cid_of_json
from sugar_lift_python_source.source_oracle import (
    SourceOracleRefusal,
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


def test_oracle_resolves_dotted_method_envelope_name(tmp_path: Path) -> None:
    src = "class Algo:\n    def get_signature(self, key, value):\n        return b\"\"\n"
    rel = "pkg/signer.py"
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src, encoding="utf-8")
    tree = ast.parse(src, filename=rel)
    fn = next(n for n in ast.walk(tree) if getattr(n, "name", "") == "get_signature")
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
    tree = ast.parse(src, filename=rel)
    fn = tree.body[0]
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
    with pytest.raises(SourceOracleRefusal) as exc:
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

# SPDX-License-Identifier: Apache-2.0
#
# Recognize runs THROUGH the Source Oracle. The `.proof` carries the SourceMemento
# (locus + CIDs, NO inline ast_template/body_text -- the only shape a proof ever
# carries; there is no flag and no fat alternative). The recognizer's vendor-template
# path asks the Source Oracle to resolve the ast_template from the on-disk source at
# the pinned locus, CID-verified, and REFUSES LOUDLY on drift (bind_rpc
# `_resolve_via_source_oracle`). These tests lock that splice: the template the
# recognizer pattern-matches is reconstructed from source by the oracle -- byte-equal
# to what the source actually is -- and a tampered source yields nothing.
import ast
from pathlib import Path

from sugar_lift_python_source.ast_template import function_body_template
from sugar_lift_python_source.bind_lifter import lift_source
from sugar_lift_python_source.bind_rpc import _resolve_via_source_oracle


def _entry(tmp: Path, rel: str, src: str) -> dict:
    (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp / rel).write_text(src, encoding="utf-8")
    return next(
        e
        for e in lift_source(src, rel, layer="library-bindings").ir
        if e.get("kind") == "library-sugar-binding-entry"
    )


def test_oracle_reconstructs_the_template_from_source(tmp_path: Path) -> None:
    src = "def add(x, y):\n    return x + y\n"
    # the binding the proof carries is the SourceMemento: locus + CIDs, NO inline
    # template or body -- that is the only shape, there is no fat alternative.
    e = _entry(tmp_path / "lean", "pkg/calc.py", src)
    assert "ast_template" not in e["body_source"]
    assert "body_text" not in e["body_source"]
    assert e["body_source"]["source_cid"] and e["body_source"]["template_cid"]
    # the oracle reconstructs the EXACT template from the on-disk source.
    expected = function_body_template(ast.parse(src).body[0])
    resolved = _resolve_via_source_oracle(str(tmp_path / "lean"), e)
    assert resolved is not None, "oracle must resolve the SourceMemento"
    assert (
        resolved["ast_template"] == expected
    ), "the recognizer's oracle-resolved template must equal the on-disk source"


def test_recognizer_gets_nothing_when_the_source_drifts(tmp_path: Path) -> None:
    e = _entry(tmp_path, "pkg/calc.py", "def add(x, y):\n    return x + y\n")
    # clean source resolves...
    assert _resolve_via_source_oracle(str(tmp_path), e) is not None
    # ...tamper the on-disk source: the bytes you'd run no longer recompute to the
    # pinned CID, so the Source Oracle refuses -> the recognizer has no template.
    (tmp_path / "pkg" / "calc.py").write_text(
        "def add(x, y):\n    return x - y\n", encoding="utf-8"
    )
    assert _resolve_via_source_oracle(str(tmp_path), e) is None

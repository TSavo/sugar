"""literal_eval failure must refuse — never substitute raw source as value.

SIN CLUSTER 4 / coord 4 — parso_adapter (and the tree-sitter twin) caught
``literal_eval`` failure and set ``Constant.value`` to the raw source text.
A parse we could not perform became a value downstream trusts.

Replacement: ``backend_defect`` with owner + blame. No substituted value.
"""

from __future__ import annotations

import ast
from types import SimpleNamespace

import pytest

from sugar_source_tree.panic import BackendDefect, backend_defect


def test_truthful_backend_defect_refuses_decode_without_value():
    """Truthful twin: named BackendDefect carries owner/blame; no value minted."""
    text = r"'\x'"
    with pytest.raises(BackendDefect) as raised:
        backend_defect(
            blame=SimpleNamespace(filename="t.py", line=1, col=0),
            owner="parso_adapter._constant_leaf",
            observed=f"literal_eval failed; text={text!r}",
            requested="a successfully decoded Python string-literal value",
            fix="never substitute raw source as Constant.value",
        )
    assert raised.value.owner == "parso_adapter._constant_leaf"
    assert "never substitute raw source" in raised.value.fix


def test_lying_raw_source_substitution_is_the_crime():
    """Lying twin: except → value = text launders a parse failure into data.

    Keep the banned shape only as the instrument that must not reappear in
    production. The truthful path raises instead of returning a Constant.
    """
    text = r"'\x'"
    try:
        value = ast.literal_eval(text)
        pytest.fail(f"expected literal_eval to fail, got {value!r}")
    except Exception:
        lying_value = text  # the sin: raw source as Constant.value

    assert lying_value == text
    assert isinstance(lying_value, str)
    # Truthful refusal: no Constant.value is constructed from the failure.
    with pytest.raises(BackendDefect):
        backend_defect(
            blame=SimpleNamespace(filename="t.py", line=1, col=0),
            owner="parso_adapter._constant_leaf",
            observed=f"literal_eval failed; text={text!r}",
            requested="a successfully decoded Python string-literal value",
            fix="never substitute raw source as Constant.value",
        )


def test_parso_adapter_source_no_longer_substitutes_raw_on_literal_eval_failure():
    """Static twin: production source refuses decode failure by backend_defect.

    parso is an OPTIONAL_PROVIDER; this law reads the adapter source so it
    stays green without installing the provider, while still pinning the
    illegal ``value = text`` / ``value = unit.source[...]`` shape out.
    """
    from pathlib import Path

    adapter = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sugar_source_tree"
        / "parso_adapter.py"
    )
    source = adapter.read_text(encoding="utf-8")
    assert "backend_defect" in source
    assert "never substitute raw source as Constant.value" in source
    # Banned survivor shapes after a failed literal_eval:
    assert "value = text" not in source
    assert "value = unit.source[start:end]" not in source
    assert "value = unit.source[span.start : span.end]" not in source


def test_tree_sitter_adapter_source_no_longer_substitutes_raw_on_literal_eval_failure():
    """Same law for the tree-sitter twin adapter (same package, same sin)."""
    from pathlib import Path

    adapter = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sugar_source_tree"
        / "tree_sitter_python_adapter.py"
    )
    source = adapter.read_text(encoding="utf-8")
    assert "backend_defect" in source
    assert "value = text" not in source
    assert "value = unit.source[span.start : span.end]" not in source

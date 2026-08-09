# SPDX-License-Identifier: MIT OR Apache-2.0
"""FormalRef substitution keeps use-site geometry for source-order teeth.

``Name.substitute`` must not replace every formal use with the Param's
declaration-span FormalRef. Compare chains authenticate the operator by the
interval between adjacent *operand* spans; a declaration-span formal that sits
left of a later constant use falsifies a well-formed chain
(``assert 1 <= month <= 12`` inside a function after formal masking).

Lying twin: declaration-span FormalRef at a use would fail
``_comparison_leg_site``. Truthful: use-site FormalRef, chain constructs.
"""

from __future__ import annotations

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Assert, Compare, FunctionDef, Name
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _tree(source: str) -> SourceFile:
    return SourceFile((source, "formal_use_site.py", blake3_512_of(source.encode())), construction_context=TreeConstructionContextV1.for_test_without_workspace())


def test_formal_ref_at_use_keeps_use_site_span_not_param_span() -> None:
    source = "def f(month):\n" "    assert 1 <= month <= 12\n" "    return month\n"
    tree = _tree(source)
    fn = next(n for n in tree.nodes() if isinstance(n, FunctionDef) and n.name == "f")
    substituted = fn.substitute({})
    assert_stmt = next(n for n in substituted.body if isinstance(n, Assert))
    compare = assert_stmt.test
    assert isinstance(compare, Compare)
    month = compare.comparators[0]
    assert month.kind == "FormalRef"
    # Use site is col of `month` in `1 <= month`, not the param list.
    use = month.line_col_span()
    assert use.start_line == 2
    assert use.start_col > 10  # past "assert 1 <= "
    param = fn.params[0].line_col_span()
    assert (use.start_line, use.start_col) != (param.start_line, param.start_col)


def test_chained_compare_with_formal_constructs_after_masking() -> None:
    """THE product twin: function sugar must not refuse a well-formed chain."""
    source = (
        "def _days_in_month(year, month):\n"
        "    assert 1 <= month <= 12, month\n"
        "    return 30\n"
    )
    tree = _tree(source)
    fn = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    # Must not raise SugarNotWritten on Compare._comparison_leg_site
    sugar = fn.sugar()
    assert sugar is not None


def test_lying_twin_declaration_span_formal_breaks_leg_site() -> None:
    """Plant declaration-span operands; leg site must reject (tooth can fail)."""
    source = "def f(month):\n    assert 1 <= month <= 12\n"
    tree = _tree(source)
    fn = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    assert_stmt = next(n for n in fn.body if isinstance(n, Assert))
    compare = assert_stmt.test
    assert isinstance(compare, Compare)
    # Build operands as if formal kept param span (the old illegal shape).
    param = fn.params[0]
    operands = (compare.left, param, compare.comparators[1])
    from sugar_source_tree.panic import SugarNotWritten
    import pytest

    with pytest.raises(SugarNotWritten, match="Compare._comparison_leg_site"):
        compare._comparison_leg_site(0, operands)

"""The LibCST adapter, and the provider differential it exists to feed.

Two things are under test:

1. **The adapter maps LibCST onto the span spec** (spans.py). Each ruling
   the spec makes about a shape where providers differ gets a test that
   asserts OUR span, not LibCST's raw one.
2. **The two-arm law holds at the boundary.** A CST shape with no rule
   panics as a MISSING. There is no permissive fallback, so the negative
   arm is tested alongside the positive one.

The pinned differential test at the bottom is NOT a "clean diff" check.
It pins the CURRENT divergence set against the golden corpus so that any
movement — a divergence appearing, disappearing, or changing shape — is
loud. The divergences it pins are open findings, documented on the test.
"""

import pytest

libcst = pytest.importorskip("libcst", reason="LibCST provider not installed")

from sugar_node_membrane.construct import Membrane  # noqa: E402
from sugar_node_membrane.cpython_adapter import CPythonAstProvider  # noqa: E402
from sugar_node_membrane.differential import compare_source, DiffResult  # noqa: E402
from sugar_node_membrane.libcst_adapter import LibCSTProvider, _describe, _Ctx  # noqa: E402
from sugar_node_membrane import nodes  # noqa: E402
from sugar_node_membrane.panic import MembranePanic  # noqa: E402


def build(source: str):
    return Membrane(LibCSTProvider()).parse(source, filename="<test>")


def only(root, cls):
    found = [n for n in root.walk() if isinstance(n, cls)]
    assert found, f"no {cls.__name__} in tree"
    return found[0]


def segment_of(source: str, cls) -> str:
    return only(build(source), cls).segment()


# --------------------------------------------------------------------------
# The rulings LibCST satisfies natively — pinned so a provider upgrade that
# changes them is caught here rather than in a corpus diff.
# --------------------------------------------------------------------------


def test_columns_are_codepoints_not_bytes():
    """Our spec is codepoint offsets. A non-ASCII name before the node is
    the discriminator: byte columns would shift the Call right by one."""
    source = "é = f(ü)\n"
    assert segment_of(source, nodes.Call) == "f(ü)"


def test_grouping_parens_are_excluded():
    assert segment_of("(x + y)\n", nodes.BinOp) == "x + y"


def test_walrus_grouping_parens_are_excluded():
    assert segment_of("z = (n := 10)\n", nodes.NamedExpr) == "n := 10"


def test_decorated_def_starts_at_the_def_keyword():
    source = "@deco\ndef f():\n    pass\n"
    assert segment_of(source, nodes.FunctionDef) == "def f():\n    pass"


def test_decorator_expression_is_its_own_node():
    root = build("@deco\ndef f():\n    pass\n")
    fn = only(root, nodes.FunctionDef)
    assert [d.segment() for d in fn.decorators] == ["deco"]


# --------------------------------------------------------------------------
# The rulings the adapter has to translate, because LibCST differs
# --------------------------------------------------------------------------


def test_enclosed_tuple_display_includes_its_parens():
    """spans.py's one ruled exception to the grouping rule. LibCST's raw
    Tuple position excludes them; the adapter recovers them from lpar/rpar."""
    assert segment_of("t = (1, 2)\n", nodes.Tuple_) == "(1, 2)"


def test_bare_tuple_spans_its_elements():
    assert segment_of("u = 1, 2\n", nodes.Tuple_) == "1, 2"


def test_doubly_parenthesized_tuple_takes_the_innermost_parens():
    """The outer pair is grouping; the innermost pair delimits the display."""
    assert segment_of("t = ((1, 2))\n", nodes.Tuple_) == "(1, 2)"


def test_param_span_excludes_the_star_sigil():
    """Sigils are arity markers of the parameter LIST, not of the parameter
    (spans.py). LibCST's raw Param position includes them."""
    root = build("def g(a, *b, c=1, **d): pass\n")
    fn = only(root, nodes.FunctionDef)
    assert [p.segment() for p in fn.params] == ["a", "b", "c=1", "d"]


def test_param_span_includes_annotation_and_default():
    root = build("def g(a: int = 1): pass\n")
    fn = only(root, nodes.FunctionDef)
    assert [p.segment() for p in fn.params] == ["a: int = 1"]


def test_comprehension_clause_starts_at_the_for_keyword():
    """LibCST's CompFor position starts at the preceding whitespace."""
    assert segment_of("[i for i in xs if i]\n", nodes.Comprehension) == "for i in xs if i"


def test_async_comprehension_clause_starts_at_async():
    source = "async def f():\n    return [i async for i in xs]\n"
    assert segment_of(source, nodes.Comprehension) == "async for i in xs"


def test_nested_comprehension_clauses_are_flat_generators():
    root = build("[a for a in xs for b in ys]\n")
    comp = only(root, nodes.ListComp)
    assert [g.segment() for g in comp.generators] == ["for a in xs", "for b in ys"]


def test_format_spec_spans_the_text_after_the_colon():
    root = build('x = f"a{b!r:>{w}}c"\n')
    fmt = only(root, nodes.FormattedValue)
    assert fmt.segment() == "{b!r:>{w}}"
    assert fmt.format_spec is not None
    assert fmt.format_spec.segment() == ">{w}"


def test_conversion_is_the_cpython_code():
    root = build('x = f"{b!r}"\n')
    assert only(root, nodes.FormattedValue).conversion == 114


# --------------------------------------------------------------------------
# Vocabulary translation: CST shapes that are not in our inventory
# --------------------------------------------------------------------------


def test_true_false_none_become_constants_not_names():
    """LibCST spells them as Name; ours are Constant."""
    root = build("x = True\ny = None\n")
    values = [c.value for c in root.walk() if isinstance(c, nodes.Constant)]
    assert values == [True, None]
    assert not [n for n in root.walk() if isinstance(n, nodes.Name) and n.id == "True"]


def test_semicolon_separated_statements_flatten_into_the_body():
    root = build("a = 1; b = 2\n")
    assert len(root.body) == 2
    assert [s.segment() for s in root.body] == ["a = 1", "b = 2"]


def test_boolop_chain_is_flattened_n_ary():
    """``BoolOp.values`` is a tuple; LibCST left-nests the operation."""
    root = build("r = a and b and c\n")
    ops = [n for n in root.walk() if isinstance(n, nodes.BoolOp)]
    assert len(ops) == 1
    assert [v.segment() for v in ops[0].values] == ["a", "b", "c"]


def test_parenthesized_boolop_is_not_flattened_through():
    """A grouped sub-operation is its own expression, so the chain stops."""
    root = build("r = (a and b) and c\n")
    ops = [n for n in root.walk() if isinstance(n, nodes.BoolOp)]
    assert len(ops) == 2


def test_del_with_several_targets_is_n_ary():
    root = build("del a, b\n")
    delete = only(root, nodes.Delete)
    assert [t.segment() for t in delete.targets] == ["a", "b"]
    assert not [n for n in root.walk() if isinstance(n, nodes.Tuple_)]


def test_implicit_concatenation_is_one_constant():
    root = build("s = 'a' 'b'\n")
    const = only(root, nodes.Constant)
    assert const.segment() == "'a' 'b'"
    assert const.value == "ab"


def test_multi_element_subscript_becomes_one_tuple():
    root = build("v = a[1, 2]\n")
    tup = only(root, nodes.Tuple_)
    assert tup.segment() == "1, 2"


def test_call_arguments_split_into_args_and_keywords():
    root = build("f(a, *b, c=1, **d)\n")
    call = only(root, nodes.Call)
    assert [a.segment() for a in call.args] == ["a", "*b"]
    assert [(k.arg, k.segment()) for k in call.keywords] == [
        ("c", "c=1"),
        (None, "**d"),
    ]


def test_import_star_is_an_alias_named_star():
    root = build("from m import *\n")
    imp = only(root, nodes.ImportFrom)
    assert [(a.name, a.segment()) for a in imp.names] == [("*", "*")]


def test_relative_import_level_counts_the_dots():
    root = build("from ...pkg import a\n")
    assert only(root, nodes.ImportFrom).level == 3


def test_elif_nests_as_an_if_in_orelse():
    root = build("if a:\n    pass\nelif b:\n    pass\n")
    outer = only(root, nodes.If)
    assert len(outer.orelse) == 1
    assert isinstance(outer.orelse[0], nodes.If)


def test_async_shapes_resolve_to_their_own_classes():
    source = (
        "async def f():\n"
        "    async with a as b:\n"
        "        async for i in c:\n"
        "            await d\n"
    )
    root = build(source)
    kinds = {type(n).__name__ for n in root.walk()}
    assert {"AsyncFunctionDef", "AsyncWith", "AsyncFor", "Await"} <= kinds


# --------------------------------------------------------------------------
# The two-arm law at the boundary: resolved, or panic. Both arms run.
# --------------------------------------------------------------------------


def test_unmapped_cst_shape_panics_as_a_missing():
    """The negative arm. A CST node with no rule must NOT get a fallback."""
    unit = nodes.SourceUnit(filename="<test>", source="x = 1\n")
    ctx = _Ctx(unit, {})
    with pytest.raises(MembranePanic) as excinfo:
        _describe(ctx, libcst.Semicolon())
    assert "no adapter rule" in excinfo.value.observed


def test_mapped_cst_shape_resolves():
    """The positive arm of the same discriminator."""
    root = build("x = 1\n")
    assert isinstance(root, nodes.Module)


def test_unknown_operator_panics_rather_than_defaulting():
    from sugar_node_membrane.libcst_adapter import _op, _BINARY_OPS

    with pytest.raises(MembranePanic):
        _op(_BINARY_OPS, libcst.And(), "binop")


def test_provider_refusal_is_a_syntax_error_not_a_silent_empty_tree():
    with pytest.raises(Exception) as excinfo:
        build("def (:\n")
    assert not isinstance(excinfo.value, MembranePanic)


# --------------------------------------------------------------------------
# The differential: the instrument itself
# --------------------------------------------------------------------------


def _quirks_diff() -> DiffResult:
    from pathlib import Path

    goldens = Path(__file__).resolve().parents[1] / "goldens" / "quirks.py"
    source = goldens.read_text(encoding="utf-8")
    result = DiffResult()
    compare_source(
        Membrane(CPythonAstProvider()),
        Membrane(LibCSTProvider()),
        source,
        "quirks.py",
        result,
    )
    return result


def test_differential_runs_both_providers_without_failing_either():
    result = _quirks_diff()
    assert result.failures == []
    assert result.files_compared == 1


def test_cid_agreement_on_the_golden_corpus_is_pinned_with_its_open_findings():
    """The acceptance criterion is ZERO divergence. It is not met yet, and
    this test pins exactly which node paths are open so movement is loud.

    All four open divergences are findings ABOUT THE SPEC OR THE CPYTHON
    ADAPTER, not about this adapter (see the module docstring of
    libcst_adapter.py and the PR body for #5940):

    - ``...format_spec.values[1]``: CPython materializes a ZERO-WIDTH empty
      ``Constant`` inside an f-string format spec. spans.py's own envelope
      rule says "there is no such thing as a node with no source extent",
      so the node inventory contradicts the spec. Needs a ruling.
    - two ``GeneratorExp`` paths: spans.py rules that grouping parens are
      excluded from an expression's span; the CPython adapter includes them
      for a parenthesized generator expression. LibCST follows the written
      spec. The pinned golden encodes the violation.
    - ``cases[4]`` / ``cases[4].pattern``: whether a PARENTHESIZED SEQUENCE
      PATTERN (``case (a_, b_):``) includes its parens the way a tuple
      DISPLAY does is not ruled anywhere. Genuine spec gap; guessing is
      forbidden, so nothing is normalized here.
    """
    result = _quirks_diff()
    open_findings = {(d.path, d.category) for d in result.divergences}
    assert open_findings == {
        ("$.body[14].value.values[3].format_spec.values[1]", "missing_right"),
        ("$.body[32].value.body", "span"),
        ("$.body[32].value.orelse", "span"),
        ("$.body[45].body[0].cases[4]", "span"),
        ("$.body[45].body[0].cases[4].pattern", "span"),
    }


def test_the_vast_majority_of_the_corpus_already_agrees():
    """Not a substitute for zero — a floor under regression while the five
    open findings above are ruled on."""
    result = _quirks_diff()
    assert result.matched >= 537

"""The span spec (spans.py docstring), executed shape by shape.

Every assertion is on the SEGMENT the span selects — the observable — not
on raw numbers, so the tests read as the spec's worked examples.
"""

import pytest

from sugar_node_membrane import Membrane
from sugar_node_membrane.nodes import (
    Assign,
    BinOp,
    Call,
    Comprehension,
    Constant,
    FunctionDef,
    JoinedStr,
    FormattedValue,
    Keyword,
    Lambda,
    ListComp,
    Match,
    MatchCase,
    Module,
    Name,
    NamedExpr,
    Param,
    Starred,
    Tuple_,
)


def parse(source: str) -> Module:
    return Membrane().parse(source)


def only(root, cls):
    nodes = [n for n in root.walk() if type(n) is cls]
    assert len(nodes) == 1, f"expected exactly one {cls.__name__}, got {len(nodes)}"
    return nodes[0]


def segments(root, cls):
    return [n.segment() for n in root.walk() if type(n) is cls]


def test_codepoint_offsets_not_bytes():
    # 'é' is 2 UTF-8 bytes but ONE codepoint. If byte columns leaked past
    # the adapter, the Call span would be off by one and slice ' f(x'.
    src = "é = f(x)\n"
    root = parse(src)
    assert only(root, Call).segment() == "f(x)"
    assert segments(root, Name) == ["é", "f", "x"]


def test_grouping_parens_excluded_from_binop():
    root = parse("y = (x + 1)\n")
    assert only(root, BinOp).segment() == "x + 1"


def test_grouping_parens_excluded_from_walrus():
    root = parse("if (n := 10) > 5:\n    pass\n")
    assert only(root, NamedExpr).segment() == "n := 10"


def test_tuple_display_includes_its_parens():
    root = parse("t = (1, 2)\n")
    assert only(root, Tuple_).segment() == "(1, 2)"


def test_bare_tuple_spans_elements():
    root = parse("t = 1, 2\n")
    assert only(root, Tuple_).segment() == "1, 2"


def test_decorated_def_starts_at_def_keyword():
    src = "@decorate\ndef f():\n    pass\n"
    root = parse(src)
    fn = only(root, FunctionDef)
    assert fn.segment().startswith("def f()")
    assert fn.decorators[0].segment() == "decorate"


def test_fstring_spans_whole_literal_and_braces():
    src = 's = f"pre {value!r:>10} post"\n'
    root = parse(src)
    outer, spec = segments(root, JoinedStr)
    assert outer == '''f"pre {value!r:>10} post"'''
    assert spec == ">10"  # the format spec, colon excluded
    assert only(root, FormattedValue).segment() == "{value!r:>10}"
    assert [n.segment() for n in root.walk() if type(n) is Name] == ["s", "value"]


def test_nested_fstring():
    src = "s = f\"a {f'{x}'} b\"\n"
    root = parse(src)
    outer, inner = segments(root, JoinedStr)
    assert outer == '''f"a {f'{x}'} b"'''
    assert inner == "f'{x}'"


def test_implicit_string_concatenation_spans_all_pieces():
    src = 's = ("one "\n     "two")\n'
    root = parse(src)
    assert only(root, Constant).segment() == '"one "\n     "two"'


def test_multiline_call_spans_to_closing_paren():
    src = "r = f(\n    1,\n    2,\n)\n"
    root = parse(src)
    assert only(root, Call).segment() == "f(\n    1,\n    2,\n)"


def test_comprehension_clause_envelope():
    src = "r = [y for y in xs if y]\n"
    root = parse(src)
    assert only(root, ListComp).segment() == "[y for y in xs if y]"
    assert only(root, Comprehension).segment() == "for y in xs if y"


def test_lambda_spans_keyword_to_body_end():
    root = parse("g = lambda a, b=1: a + b\n")
    assert only(root, Lambda).segment() == "lambda a, b=1: a + b"


def test_walrus_lambda_param_with_default_envelope():
    root = parse("g = lambda a, b=1: a\n")
    params = [n.segment() for n in root.walk() if type(n) is Param]
    assert params == ["a", "b=1"]


def test_param_with_annotation_and_default_envelope():
    root = parse("def f(x: int = 3):\n    pass\n")
    assert only(root, Param).segment() == "x: int = 3"


def test_vararg_param_excludes_star():
    root = parse("def f(*args, **kw):\n    pass\n")
    params = {p.param_kind: p.segment() for p in root.walk() if type(p) is Param}
    assert params == {"vararg": "args", "kwarg": "kw"}


def test_starred_argument_includes_star():
    root = parse("f(*items)\n")
    assert only(root, Starred).segment() == "*items"


def test_double_star_keyword_includes_both_stars():
    root = parse("f(**extra)\n")
    kw = only(root, Keyword)
    assert kw.arg is None
    assert kw.segment() == "**extra"


def test_match_spans_and_case_envelope():
    src = (
        "match point:\n"
        "    case (0, y) if y:\n"
        "        pass\n"
        "    case _:\n"
        "        pass\n"
    )
    root = parse(src)
    m = only(root, Match)
    assert m.segment().startswith("match point:")
    assert m.segment().rstrip().endswith("pass")
    first_case = [n for n in root.walk() if type(n) is MatchCase][0]
    assert first_case.segment().startswith("(0, y) if y")


def test_module_spans_entire_source():
    src = "a = 1\nb = 2\n"
    root = parse(src)
    assert root.segment() == src


def test_line_col_projection_is_codepoints():
    src = "é = f(x)\n"
    root = parse(src)
    lc = only(root, Call).line_col_span()
    assert (lc.start_line, lc.start_col, lc.end_line, lc.end_col) == (1, 4, 1, 8)

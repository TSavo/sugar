from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_summary_derivation import (
    _projected_manager_call_uses,
    populate_source_derived_resource_refs,
)

PANDAS_SOURCE_CID = (
    "blake3-512:60e7b5ba2c971960e4d8edcaa85e916704dc8bfb977bc15dafb2f2b3e87458ff"
    "ba4b2f823e500c4c591a968b7c3e8ed436035aa171e8b3227055d9956147fae1"
)
PANDAS_MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda1"
    "c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)


def _pandas_root() -> Path:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.manifest_cid, corpus.file_count) == (
        "3.0.3",
        PANDAS_MANIFEST_CID,
        1421,
    )
    # Construction loci use the distribution-recorded seat (site-packages).
    # Corpus identity is over the package root; import binding seats one level up.
    return corpus.root.parent


def _real_tree():
    root = _pandas_root()
    path = root / "pandas/tests/io/formats/test_ipython_compat.py"
    assert path.is_file()
    assert blake3_512_of(path.read_bytes()) == PANDAS_SOURCE_CID
    return open_source_file_for_construction(
        path,
        root=root,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )


def _line_32_with(tree):
    return next(
        node
        for node in tree.nodes()
        if node.kind == "With" and node.line_col_span().start_line == 32
    )


def _nested_manager_sugars(site):
    """Both managers of a multi-item With, outer then inner, after nesting."""
    nested = site._nest_items()
    return nested.sugar(), nested.body[0].sugar()


def test_local_two_name_managers_project_both_reaching_calls(tmp_path: Path) -> None:
    source = tmp_path / "truthful.py"
    source.write_text(
        "def exercise(make_manager):\n"
        "    opt = make_manager()\n"
        "    with_latex = make_manager()\n"
        "    with opt, with_latex:\n"
        "        pass\n",
        encoding="utf-8",
    )
    tree = open_source_file_for_construction(
        source,
        root=tmp_path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )
    site = next(
        node
        for node in tree.nodes()
        if node.kind == "With" and node.line_col_span().start_line == 4
    )

    assert [item.context_expr.kind for item in site.items] == ["Name", "Name"]
    projected = _projected_manager_call_uses(tree)
    rows = sorted(
        (call.line_col_span().start_line, coordinate.start_line, coordinate.start_col)
        for coordinate, call, _exit_face in projected.values()
        if coordinate.start_line == 4
    )
    assert rows == [(2, 4, 9), (3, 4, 14)]


def test_pandas_303_two_name_managers_project_their_assignment_calls() -> None:
    """The verified corpus site consumes two distinct acquired managers."""
    tree = _real_tree()
    site = _line_32_with(tree)
    assert [item.context_expr.kind for item in site.items] == ["Name", "Name"]

    projected = _projected_manager_call_uses(tree)
    rows = sorted(
        (call.line_col_span().start_line, coordinate.start_line, coordinate.start_col)
        for coordinate, call, _exit_face in projected.values()
        if coordinate.start_line == 32
    )
    assert rows == [(21, 32, 13), (30, 32, 18)]


def test_local_single_name_manager_projects_reaching_call(tmp_path: Path) -> None:
    """Single-item ``with m:`` projects the same way multi-item does."""
    source = tmp_path / "single.py"
    source.write_text(
        "def exercise(make_manager):\n"
        "    opt = make_manager()\n"
        "    with opt:\n"
        "        pass\n",
        encoding="utf-8",
    )
    tree = open_source_file_for_construction(
        source,
        root=tmp_path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )
    projected = _projected_manager_call_uses(tree)
    rows = sorted(
        (call.line_col_span().start_line, coordinate.start_line, coordinate.start_col)
        for coordinate, call, _exit_face in projected.values()
    )
    assert rows == [(2, 3, 9)]


def test_pandas_303_single_assigned_manager_projects_reaching_call() -> None:
    """Same corpus file, single-item ``with opt:`` — general single-Name projection."""
    tree = _real_tree()
    site = next(
        node
        for node in tree.nodes()
        if node.kind == "With" and node.line_col_span().start_line == 53
    )
    assert len(site.items) == 1
    assert site.items[0].context_expr.kind == "Name"

    projected = _projected_manager_call_uses(tree)
    rows = sorted(
        (call.line_col_span().start_line, coordinate.start_line, coordinate.start_col)
        for coordinate, call, _exit_face in projected.values()
        if coordinate.start_line == 53
    )
    assert rows == [(51, 53, 13)]


def test_projection_is_a_transaction_and_does_not_mutate_the_source_tree() -> None:
    tree = _real_tree()
    site = _line_32_with(tree)
    before = tuple(item.context_expr for item in site.items)

    _projected_manager_call_uses(tree)

    assert tuple(item.context_expr for item in site.items) == before
    assert [item.context_expr.kind for item in site.items] == ["Name", "Name"]


def test_pandas_303_both_option_context_managers_construct_through_bindings() -> None:
    """Name → binding coordinate → provider Call → generator protocol edges.

    Before: populate raised SourceCallBindingGap("unconsumed call actual") while
    resolving OptionError constructors inside the provider module, so neither
    manager seated a frame.  After: both bare-Name heads construct as
    GeneratorWithSugar through their reaching option_context providers.
    """
    tree = _real_tree()
    root = _pandas_root()
    path = root / "pandas/tests/io/formats/test_ipython_compat.py"
    site = _line_32_with(tree)
    context = tree.root.unit.construction_context

    populate_source_derived_resource_refs(tree, root=root, path=path)

    seats = sorted(
        (coordinate.start_line, coordinate.start_col)
        for coordinate in context.source_manager_provider_calls
        if coordinate.start_line == 32
    )
    assert seats == [(32, 13), (32, 18)]
    frames = sorted(
        (
            coordinate.start_line,
            coordinate.start_col,
            frame.generator_steps is not None,
        )
        for coordinate, frame in context.source_call_frames.items()
        if coordinate.start_line in {21, 30}
    )
    assert frames == [(21, 14, True), (30, 21, True)]

    outer, inner = _nested_manager_sugars(site)
    assert isinstance(outer, GeneratorWithSugar)
    assert isinstance(inner, GeneratorWithSugar)
    assert isinstance(site.sugar(), GeneratorWithSugar)


def test_undecided_rebinding_does_not_invent_a_second_manager_call(
    tmp_path: Path,
) -> None:
    """Lying twin: the second Name no longer reaches acquired call state."""
    source = tmp_path / "twin.py"
    source.write_text(
        "def exercise(make_manager, undecided):\n"
        "    first = make_manager()\n"
        "    second = make_manager()\n"
        "    second = undecided\n"
        "    with first, second:\n"
        "        pass\n",
        encoding="utf-8",
    )
    tree = open_source_file_for_construction(
        source,
        root=tmp_path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )

    projected = _projected_manager_call_uses(tree)
    rows = [
        (coordinate.start_line, coordinate.start_col, call.line_col_span().start_line)
        for coordinate, call, _exit_face in projected.values()
        if coordinate.start_line == 5
    ]
    assert rows == [(5, 9, 2)]


def test_same_spelled_names_bound_elsewhere_do_not_authenticate(tmp_path: Path) -> None:
    """Lying twin: names cannot authorize managers independently of bindings."""
    source = tmp_path / "lying.py"
    source.write_text(
        "def exercise(opt_value, latex_value):\n"
        "    opt = opt_value\n"
        "    with_latex = latex_value\n"
        "    with opt, with_latex:\n"
        "        pass\n",
        encoding="utf-8",
    )
    tree = open_source_file_for_construction(
        source,
        root=tmp_path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )
    site = next(
        node
        for node in tree.nodes()
        if node.kind == "With" and node.line_col_span().start_line == 4
    )
    context = tree.root.unit.construction_context
    populate_source_derived_resource_refs(tree, root=tmp_path, path=source)

    assert context.source_manager_provider_calls == {}
    assert _projected_manager_call_uses(tree) == {}
    # No reaching provider Call: construction stays loud at the use coordinate.
    with pytest.raises(Exception) as caught:
        site.sugar()
    assert "no context-manager derivation" in str(caught.value)


def test_bare_name_construction_path_contains_no_vendor_name_literals() -> None:
    """The structural constructor cannot admit this site by manager spelling."""
    import ast
    import inspect
    import textwrap

    import sugar_lift_python_source.manager_summary_derivation as derivation

    module = ast.parse(textwrap.dedent(inspect.getsource(derivation)))
    literals = {
        node.value
        for node in ast.walk(module)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert literals.isdisjoint(
        {
            "opt",
            "with_latex",
            "option_context",
            "pytest.raises",
            "external_error_raised",
        }
    )


def test_exception_subclass_without_init_accepts_message_args(tmp_path: Path) -> None:
    """Inherited BaseException constructor law — not an empty zero-formal lie."""
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_source_tree.nodes import Call, ClassDef, FunctionDef
    from sugar_source_tree.tree import SourceFile

    source = (
        "class RenamedFault(AttributeError, KeyError):\n"
        "    pass\n"
        "def exercise():\n"
        '    raise RenamedFault("needle")\n'
    )
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, str(tmp_path / "fault.py"), blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )
    class_node = next(node for node in tree.nodes() if isinstance(node, ClassDef))
    call = next(node for node in tree.nodes() if isinstance(node, Call))
    frame = class_node.source_visible_constructor_frame()
    assert frame.parameters == ("args",)
    assert frame.parameter_kinds == ("vararg",)
    span = call.line_col_span()
    context.source_call_frames[
        SourceFragmentCoordinateV1(
            tree.root.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
    ] = frame
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    # Must not raise SourceCallBindingGap("unconsumed call actual").
    function.source_visible_call_frame()


def test_non_exception_class_without_init_still_refuses_extra_actuals(
    tmp_path: Path,
) -> None:
    """Lying twin: object construction does not inherit exception *args."""
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
    from sugar_source_tree.nodes import Call, ClassDef, FunctionDef
    from sugar_source_tree.tree import SourceFile

    source = (
        "class RenamedPlain:\n"
        "    pass\n"
        "def exercise():\n"
        "    return RenamedPlain(1)\n"
    )
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, str(tmp_path / "plain.py"), blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )
    class_node = next(node for node in tree.nodes() if isinstance(node, ClassDef))
    call = next(node for node in tree.nodes() if isinstance(node, Call))
    frame = class_node.source_visible_constructor_frame()
    assert frame.parameters == ()
    span = call.line_col_span()
    context.source_call_frames[
        SourceFragmentCoordinateV1(
            tree.root.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
    ] = frame
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    with pytest.raises(SourceCallBindingGap, match="unconsumed call actual"):
        function.source_visible_call_frame()

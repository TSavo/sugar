from __future__ import annotations

import ast
import tempfile
from dataclasses import dataclass
from pathlib import Path
import re

import pytest

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_provenance import ConstructedValueTestimonyV1
from sugar_source_tree.tree import SourceFile
from sugar_source_tree.tree import SourceTree

from sugar_lift_py_tests.fixture_resource_obligation import (
    FixtureResourceOutcome,
    FixtureResourceBindingRefusal,
    FixtureSuppliedResourceObligationV1,
    classify_fixture_resource_outcome,
)


@dataclass(frozen=True)
class _FormalResourceSite:
    relative_path: str
    function_name: str
    line: int
    has_with: bool
    load_references: int

    @property
    def coordinate(self) -> str:
        return f"{self.relative_path}:{self.line}:{self.function_name}"


@dataclass(frozen=True)
class _FormalResourceCensus:
    lexical_mentions: int
    formal_declarations: int
    load_references: int
    formal_functions: int
    functions_with_with: int
    bare_parameter_functions: int
    sites: tuple[_FormalResourceSite, ...]

    def render(self) -> str:
        return " ".join(
            (
                f"lexicalMentions={self.lexical_mentions}",
                f"formalDeclarations={self.formal_declarations}",
                f"loadReferences={self.load_references}",
                f"formalFunctions={self.formal_functions}",
                f"functionsWithWith={self.functions_with_with}",
                f"bareParameterFunctions={self.bare_parameter_functions}",
            )
        )


def _owned_function_nodes(function):
    owned = []
    stack = list(function.body)
    while stack:
        node = stack.pop()
        owned.append(node)
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return tuple(owned)


def _census_formal_parameter_resources(
    corpus_root: Path, formal_name: str
) -> _FormalResourceCensus:
    """Measurement-only spelling filter; it grants no construction semantics."""
    word = re.compile(rf"\b{re.escape(formal_name)}\b")
    lexical_mentions = formal_declarations = load_references = 0
    sites = []
    for path in SourceTree(corpus_root).paths():
        source = path.read_text(encoding="utf-8")
        lexical_mentions += len(word.findall(source))
        tree = ast.parse(source, filename=str(path))
        formal_declarations += sum(
            isinstance(node, ast.arg) and node.arg == formal_name
            for node in ast.walk(tree)
        )
        load_references += sum(
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id == formal_name
            for node in ast.walk(tree)
        )
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            declarations = (
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
                *((function.args.vararg,) if function.args.vararg else ()),
                *((function.args.kwarg,) if function.args.kwarg else ()),
            )
            if not any(parameter.arg == formal_name for parameter in declarations):
                continue
            owned = _owned_function_nodes(function)
            sites.append(
                _FormalResourceSite(
                    path.relative_to(corpus_root).as_posix(),
                    function.name,
                    function.lineno,
                    any(isinstance(node, (ast.With, ast.AsyncWith)) for node in owned),
                    sum(
                        isinstance(node, ast.Name)
                        and isinstance(node.ctx, ast.Load)
                        and node.id == formal_name
                        for node in owned
                    ),
                )
            )
    ordered = tuple(sorted(sites, key=lambda site: site.coordinate))
    with_with = sum(site.has_with for site in ordered)
    return _FormalResourceCensus(
        lexical_mentions,
        formal_declarations,
        load_references,
        len(ordered),
        with_with,
        len(ordered) - with_with,
        ordered,
    )


def _function_and_actual():
    source = "def consume(resource):\n    return resource\nactual = 'ready'\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(source)
        path = handle.name
    tree = SourceFile(path_source(path))
    function = next(tree.functions())
    actual = next(node for node in tree.nodes() if node.kind == "Constant")
    return function, actual


def test_fixture_resource_is_discharged_at_authenticated_formal_binding():
    """No local manager is invented: the caller-bound formal is the boundary."""
    function, actual = _function_and_actual()
    frame = function.source_visible_call_frame()
    testimony = ConstructedValueTestimonyV1.mint(
        actual.fragment,
        cid_of_json({"kind": "external-resource", "state": "ready"}),
    )
    bound = frame.bind_node_actuals((actual,), (), (testimony,))
    obligation = FixtureSuppliedResourceObligationV1.mint(
        bound.formal_coordinates[0]
    )

    discharge = obligation.discharge(bound.runtime_entries[0])

    assert discharge.formal_coordinate_cid == bound.formal_coordinates[0].cid
    assert discharge.constructed_value_testimony_cid == testimony.cid
    assert discharge.obligation_cid == obligation.obligation_cid


def test_fixture_resource_without_binding_testimony_is_a_named_refusal():
    """LYING TWIN: a supplied-looking formal cannot discharge itself."""
    function, actual = _function_and_actual()
    frame = function.source_visible_call_frame()
    bound = frame.bind_node_actuals((actual,), ())
    obligation = FixtureSuppliedResourceObligationV1.mint(
        bound.formal_coordinates[0]
    )

    with pytest.raises(FixtureResourceBindingRefusal) as caught:
        obligation.discharge(bound.runtime_entries[0])

    assert caught.value.coordinate == bound.formal_coordinates[0].cid
    assert "constructed-value testimony unavailable" in caught.value.detail


def test_fixture_resource_obligation_refuses_a_different_formal_coordinate():
    function, actual = _function_and_actual()
    frame = function.source_visible_call_frame()
    testimony = ConstructedValueTestimonyV1.mint(
        actual.fragment,
        cid_of_json({"kind": "external-resource", "state": "ready"}),
    )
    bound = frame.bind_node_actuals((actual,), (), (testimony,))
    other = function.source_visible_call_frame().formal_coordinates[0]
    obligation = FixtureSuppliedResourceObligationV1.mint(other)

    # Minting the same structural frame is deliberately the same coordinate;
    # mutate only the occurrence identity to model testimony from another formal.
    from dataclasses import replace

    wrong_entry = replace(
        bound.runtime_entries[0],
        coordinate=replace(
            bound.runtime_entries[0].coordinate,
            cid="blake3-512:" + "f" * 128,
        ),
    )
    with pytest.raises(FixtureResourceBindingRefusal) as caught:
        obligation.discharge(wrong_entry)
    assert caught.value.coordinate == obligation.formal_coordinate_cid
    assert "coordinate mismatch" in caught.value.detail


def _authenticated_obligation_and_entry():
    function, actual = _function_and_actual()
    frame = function.source_visible_call_frame()
    testimony = ConstructedValueTestimonyV1.mint(
        actual.fragment,
        cid_of_json({"kind": "external-resource", "state": "ready"}),
    )
    bound = frame.bind_node_actuals((actual,), (), (testimony,))
    return (
        FixtureSuppliedResourceObligationV1.mint(bound.formal_coordinates[0]),
        bound.runtime_entries[0],
    )


def test_population_outcomes_require_a_positive_authenticated_exceptional_exit():
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.outcome import Complete, Incomplete

    obligation, entry = _authenticated_obligation_and_entry()
    positive = classify_fixture_resource_outcome(
        obligation, entry, lambda: Incomplete(RaiseEffect("ValueError", "site"))
    )
    absent = classify_fixture_resource_outcome(
        obligation, entry, lambda: Complete("ordinary completion")
    )

    assert positive.outcome is FixtureResourceOutcome.AUTHENTICATED_EXCEPTIONAL_EXIT
    assert absent.outcome is FixtureResourceOutcome.NAMED_REFUSAL
    assert absent.coordinate == obligation.formal_coordinate_cid
    assert absent.detail == "positive-authenticated-exceptional-exit-absent"


def test_population_reraises_construction_panic_instead_of_attributing_success():
    from sugar_lift_py_tests.gap.panic import (
        ConstructionPanic,
        construction_panic_gap,
    )

    obligation, entry = _authenticated_obligation_and_entry()

    def panic():
        construction_panic_gap(
            owner="fixture-resource-test",
            blame="fixture.py:2:4",
            observed="missing producer",
            requested="authenticated exceptional exit",
            fix="implement the producer",
        )

    with pytest.raises(ConstructionPanic) as caught:
        classify_fixture_resource_outcome(obligation, entry, panic)

    assert caught.value.info.owner == "fixture-resource-test"
    assert caught.value.info.blame == "fixture.py:2:4"


def test_authenticated_pandas_303_temp_file_population_is_partitioned_by_formal():
    """Measurement-only spelling filter; it grants no production semantics."""
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_py_tests.no_call_body_attribution import (
        CANONICAL_CORPUS_MANIFEST_CID,
        SHARED_DEMAND_TABLE_CONTENT_KEY,
        pull_shared_demand_table,
    )

    corpus = authenticated_pandas_corpus()
    assert corpus.manifest_cid == CANONICAL_CORPUS_MANIFEST_CID
    with tempfile.TemporaryDirectory() as scratch:
        demand_table = pull_shared_demand_table(
            Path(__file__).resolve().parents[4],
            Path(scratch) / "python-demand-table.json",
        )
    assert demand_table["contentKey"] == SHARED_DEMAND_TABLE_CONTENT_KEY
    assert len(demand_table["rows"]) == 107_433
    census = _census_formal_parameter_resources(corpus.root, "temp_file")

    assert census.lexical_mentions == 1_002
    assert census.formal_declarations == 391
    assert census.load_references == 596
    assert census.formal_functions == 391
    assert census.functions_with_with == 149
    assert census.bare_parameter_functions == 242
    assert 391 == 149 + 242
    feather = [
        site
        for site in census.sites
        if site.relative_path == "tests/io/test_feather.py"
        and site.function_name == "check_error_on_write"
    ]
    assert len(feather) == 1
    assert feather[0].line == 29
    assert feather[0].has_with is True
    assert feather[0].load_references == 1
    print(census.render(), flush=True)
    print(f"concreteSite={feather[0].coordinate}", flush=True)

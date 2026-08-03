"""Consumer proof for the explicitly injected shared SOURCEFILE_CONSTRUCTION_DOOR evidence."""

import ast
import inspect
from pathlib import Path

import pytest

from sourcefile_construction_door_auditor import (
    audit_sourcefile_construction_door,
    discover_projection_callers,
    project_constructed_module,
)
from sourcefile_construction_door_evidence import (
    EvidenceSite,
    ProjectionClosureEvidence,
    SourceFileConstructionDoorEvidence,
    assert_test_owned_evidence,
)
from sourcefile_construction_door_fixture import sourcefile_construction_door_evidence
from sourcefile_construction_door_symbol_graph import SymbolGraph
from sugar_source_tree.backend import Backend
from sugar_source_tree.tree import SourceFile


def test_from_path_enters_source_file_constructor_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "VALUE = 1\n"
    path = tmp_path / "canonical-entry.py"
    path.write_text(source, encoding="utf-8")
    captured = []
    original_init = SourceFile.__init__

    def observe_init(self, identity, *args, **kwargs):
        captured.append(identity)
        return original_init(self, identity, *args, **kwargs)

    monkeypatch.setattr(SourceFile, "__init__", observe_init)
    SourceFile.from_path(path)

    assert len(captured) == 1
    captured_source, captured_filename, captured_source_cid = captured[0]
    assert captured_source == source
    assert captured_filename == str(path)
    assert isinstance(captured_source_cid, str) and captured_source_cid


def test_backend_materialize_module_is_the_canonical_event_owner() -> None:
    assert "materialize_module" in Backend.__dict__, (
        "R_missing_backend_materialize_module=1: Backend.materialize_module "
        "must own the sole SourceFile construction event"
    )


def test_shared_sourcefile_construction_door_evidence_is_typed_sealed_and_closed(
    sourcefile_construction_door_evidence: SourceFileConstructionDoorEvidence,
) -> None:
    assert (
        assert_test_owned_evidence(sourcefile_construction_door_evidence)
        is sourcefile_construction_door_evidence
    )


def test_projection_callers_are_discovered_not_self_seeded() -> None:
    """Truthful: real static callers of the test-owned projection door exist.

    Fails when: discovery returns empty (door unexercised) OR callers are the
    old self-seed shape (auditor def line fabricated as a caller).
    Both states are reachable — empty by deleting call sites; seed by the
    removed fallback — and both must stay red.

    Does not require the full door-evidence fixture: caller discovery is a pure
    static property of the owner module.
    """
    owner_path = Path(inspect.getsourcefile(project_constructed_module) or "").resolve()
    discovered = discover_projection_callers(owner_path=owner_path)
    assert discovered, (
        "R_missing_projection_callers: owner module has zero static callers of "
        "project_constructed_module"
    )
    # Old self-seed stamped the auditor *definition* line as a caller.
    # Real callers are call expression lines inside the function body.
    audit_def_line = inspect.getsourcelines(audit_sourcefile_construction_door)[1]
    assert not any(
        site.path.resolve() == owner_path
        and site.line == audit_def_line
        and site.symbol == audit_sourcefile_construction_door.__name__
        for site in discovered
    ), "callers must not be the self-seeded auditor definition site"
    # Every discovered caller must be a real call line (not the def of the door).
    door_line = inspect.getsourcelines(project_constructed_module)[1]
    assert all(site.line != door_line for site in discovered), discovered
    auditor_source = owner_path.read_text(encoding="utf-8")
    # The defect shape: empty → fabricate EvidenceSite from the auditor itself.
    assert "if not projection_calls:" not in auditor_source
    assert "EvidenceSite(Path(__file__).resolve(), audit_line" not in auditor_source


def test_lying_twin_empty_projection_callers_is_red() -> None:
    """Lying twin: hide every caller of the projection door; discovery stays empty.

    Fails when: discovery fabricates a caller (self-seed returns) or treats
    empty as success. Reachable by feeding a door definition with no call sites.
    """
    # Door exists; nobody calls it. Empty must remain empty.
    owner_source = (
        "def project_constructed_module(product):\n"
        "    return product.reporting_projection\n"
        "\n"
        "def other_work():\n"
        "    return 1\n"
    )
    callers = discover_projection_callers(
        owner_path=Path("synthetic_projection_owner.py"),
        owner_source=owner_source,
    )
    assert callers == (), (
        "empty caller set must stay empty; got fabricated callers: " f"{callers!r}"
    )

    # assert_closed projection axis refuses the empty measurement.
    projection = ProjectionClosureEvidence(
        definition=EvidenceSite(
            Path("synthetic_projection_owner.py"),
            1,
            (),
            "project_constructed_module",
        ),
        callers=(),
        dynamic_edges=(),
        aliases=(),
        reexports=(),
        wrappers=(),
        non_product_callers=(),
        legacy_doors=(),
        discovered_edges=0,
        audited_edges=0,
    )
    with pytest.raises(AssertionError, match="R_missing_projection_callers"):
        assert projection.callers, (
            "R_missing_projection_callers: zero static callers of the sole "
            "projection door; empty is a finding, never a self-seeded auditor site"
        )


def test_lying_twin_hidden_real_callers_reds_discovery() -> None:
    """Lying twin: strip every call site from the real owner source; reds.

    Fails when: the detector still reports callers after all call sites are
    removed (self-seed or stale residual). Reachable by erasing call AST nodes
    from the live auditor source text.
    """
    owner_path = Path(inspect.getsourcefile(project_constructed_module) or "").resolve()
    live = owner_path.read_text(encoding="utf-8")
    assert "project_constructed_module(" in live
    # Keep the definition; erase every call expression targeting the door.
    # Replace call-site spelling without touching the def line.
    hidden_lines: list[str] = []
    for line in live.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("def project_constructed_module"):
            hidden_lines.append(line)
            continue
        if "project_constructed_module(" in line:
            # Hide the call: rename the callee so the static graph no longer
            # resolves it to the projection door.
            hidden_lines.append(
                line.replace(
                    "project_constructed_module(",
                    "project_constructed_module_HIDDEN(",
                )
            )
        else:
            hidden_lines.append(line)
    hidden_source = "".join(hidden_lines)
    callers = discover_projection_callers(
        owner_path=owner_path,
        owner_source=hidden_source,
    )
    assert callers == (), (
        "after hiding every production/owner caller, discovery must report "
        f"empty; got {callers!r} (self-seed or residual)"
    )
    # Live source still has real callers — the tooth only fires on the lie.
    live_callers = discover_projection_callers(owner_path=owner_path)
    assert live_callers, "live owner module must still exercise the door"


def _graph(tmp_path: Path, sources: dict[str, str]) -> SymbolGraph:
    modules = {}
    for module, source in sources.items():
        path = tmp_path / f"{module.replace('.', '_')}.py"
        path.write_text(source, encoding="utf-8")
        modules[module] = (path, ast.parse(source, str(path)))
    return SymbolGraph(modules)


def test_symbol_graph_uses_source_ordered_reaching_definitions(tmp_path: Path) -> None:
    graph = _graph(
        tmp_path,
        {
            "m": (
                "def first(): pass\n"
                "def second(): pass\n"
                "def caller(flag, doomed):\n"
                "    target = first\n"
                "    if flag:\n"
                "        target = second\n"
                "    target()\n"
                "    del target\n"
                "    target()\n"
                "def loop_caller(flag):\n"
                "    target = first\n"
                "    while flag:\n"
                "        target = second\n"
                "        flag = False\n"
                "    target()\n"
                "def try_caller():\n"
                "    target = second\n"
                "    try:\n"
                "        target = first\n"
                "    except Exception:\n"
                "        target = second\n"
                "    finally:\n"
                "        target = first\n"
                "    target()\n"
            )
        },
    )
    calls = [edge for edge in graph.calls if edge.expression == "target"]
    assert {target.name for target in calls[0].targets} == {"first", "second"}
    assert calls[0].dynamic is False
    assert calls[1].targets == ()
    assert calls[1].dynamic is True
    assert {target.name for target in calls[2].targets} == {"first", "second"}
    assert {target.name for target in calls[3].targets} == {"first"}
    assert any("unresolved call edge 'target'" in row for row in graph.discovery_errors)


def test_symbol_graph_does_not_fall_through_a_later_local_rebind(
    tmp_path: Path,
) -> None:
    graph = _graph(
        tmp_path,
        {
            "m": (
                "def outer(): pass\n"
                "def caller():\n"
                "    outer()\n"
                "    outer = lambda: None\n"
            )
        },
    )
    call = next(edge for edge in graph.calls if edge.expression == "outer")
    assert call.targets == ()
    assert call.dynamic is True


def test_symbol_graph_resolves_fixed_point_reexports(tmp_path: Path) -> None:
    graph = _graph(
        tmp_path,
        {
            "a": "def owner(): pass\n",
            "b": "from a import *\nforwarded = owner\n",
            "c": "from b import forwarded as again\nagain()\n",
        },
    )
    call = next(edge for edge in graph.calls if edge.expression == "again")
    assert {(target.module, target.name) for target in call.targets} == {("a", "owner")}
    assert call.dynamic is False

    package = tmp_path / "pkg"
    package.mkdir()
    init_path = package / "__init__.py"
    inner_path = package / "inner.py"
    consumer_path = tmp_path / "consumer.py"
    init_source = "from .inner import owner as forwarded\n"
    inner_source = "def owner(): pass\n"
    consumer_source = "from pkg import forwarded\nforwarded()\n"
    for path, source in (
        (init_path, init_source),
        (inner_path, inner_source),
        (consumer_path, consumer_source),
    ):
        path.write_text(source, encoding="utf-8")
    relative_graph = SymbolGraph(
        {
            "pkg": (init_path, ast.parse(init_source, str(init_path))),
            "pkg.inner": (inner_path, ast.parse(inner_source, str(inner_path))),
            "consumer": (
                consumer_path,
                ast.parse(consumer_source, str(consumer_path)),
            ),
        }
    )
    relative_call = next(
        edge for edge in relative_graph.calls if edge.expression == "forwarded"
    )
    assert {(target.module, target.name) for target in relative_call.targets} == {
        ("pkg.inner", "owner")
    }


def test_symbol_graph_resolves_classmethod_cls_to_its_class(tmp_path: Path) -> None:
    graph = _graph(
        tmp_path,
        {
            "m": (
                "class SourceFile:\n"
                "    def __init__(self, identity): pass\n"
                "    @classmethod\n"
                "    def from_path(cls, identity):\n"
                "        return cls(identity)\n"
                "def invoke(callback=SourceFile.from_path):\n"
                "    return callback(('source', 'file.py', 'cid'))\n"
            )
        },
    )
    call = next(edge for edge in graph.calls if edge.expression == "cls")
    assert {(target.name, target.lexical) for target in call.targets} == {
        ("SourceFile", ())
    }
    assert call.dynamic is False
    callback_call = next(edge for edge in graph.calls if edge.expression == "callback")
    assert {(target.name, target.lexical) for target in callback_call.targets} == {
        ("from_path", ("SourceFile",))
    }

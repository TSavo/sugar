"""Executable independent, test-owned LAW_OF_ONE auditor."""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
import copy
import pickle
from dataclasses import is_dataclass
import inspect
from pathlib import Path
from typing import Callable

import pytest

from law_of_one_evidence import (
    EvidenceSite,
    LawOfOneEvidence,
    OwnerCallPathEvidence,
    PrivacyLeakEvidence,
    ProjectionClosureEvidence,
    ProtocolZeroWorkEvidence,
    SourceFileSurfaceEvidence,
    _mint_test_owned_evidence,
)
from law_of_one_symbol_graph import SymbolGraph


def _site(path: Path, node: ast.AST, owners: tuple[str, ...], symbol: str) -> EvidenceSite:
    return EvidenceSite(path, getattr(node, "lineno", 1), owners, symbol)


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _owners(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> tuple[str, ...]:
    names = []
    cursor = parents.get(node)
    while cursor is not None:
        if isinstance(cursor, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(cursor.name)
        cursor = parents.get(cursor)
    return tuple(reversed(names))


def _called_leaf(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _production_files(root: Path) -> tuple[Path, ...]:
    base = root / "implementations" / "python"
    files = tuple(sorted(
        path for path in base.rglob("*.py")
        if "tests" not in path.relative_to(base).parts
        and "__pycache__" not in path.relative_to(base).parts
    ))
    assert files
    return files


def _module_key(path: Path, root: Path) -> str:
    rel = path.relative_to(root / "implementations" / "python").with_suffix("")
    parts = rel.parts
    if "src" in parts:
        parts = parts[parts.index("src") + 1 :]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def audit_law_of_one(
    *,
    repository_root: Path,
    temporary_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_file_entry: Callable[..., object],
) -> LawOfOneEvidence:
    from sugar_source_tree.backend import Backend
    import sugar_source_tree.backend as backend_module
    from sugar_source_tree.nodes import Node
    from sugar_source_tree.fragment import SourceFragment
    from sugar_source_tree.reporter import AuditReporter, CollectingReporter
    from sugar_source_tree.tree import SourceFile
    import sugar_source_tree.tree as tree_module
    import sugar_lift_py_tests.tree_enumerate as tree_enumerate

    project_constructed_module = getattr(
        tree_enumerate, "project_constructed_module", None
    )

    discovered = _production_files(repository_root)
    parsed = {}
    errors = []
    modules: dict[str, list[Path]] = defaultdict(list)
    for path in discovered:
        try:
            parsed[path] = ast.parse(path.read_text(encoding="utf-8"), str(path))
            modules[_module_key(path, repository_root)].append(path)
        except (OSError, SyntaxError, UnicodeError) as error:
            errors.append(f"{path}: {error}")
    audited = tuple(sorted(parsed))
    unaudited = tuple(sorted(set(discovered) - set(audited)))
    duplicates = tuple(sorted(
        (name, tuple(paths)) for name, paths in modules.items() if len(paths) > 1
    ))

    graph_modules = {
        _module_key(path, repository_root): (path, tree)
        for path, tree in parsed.items()
    }
    assert len(graph_modules) == len(parsed), "cross-root duplicate module identity"
    graph = SymbolGraph(graph_modules)
    contract_reds: list[str] = []
    door = SourceFile.__init__
    door_file = Path(inspect.getsourcefile(door) or "").resolve()
    door_line = inspect.getsourcelines(door)[1]
    source_file_symbol = next(
        (
            symbol
            for symbol in graph.definitions.values()
            if symbol.path.resolve() == door_file
            and symbol.name == SourceFile.__name__
            and symbol.lexical == ()
        ),
        None,
    )
    init_symbols = tuple(
        symbol
        for symbol in graph.definitions.values()
        if symbol.path.resolve() == door_file
        and symbol.name == "__init__"
        and symbol.lexical == (SourceFile.__name__,)
    )
    if len(init_symbols) != 1:
        contract_reds.append(
            f"R_sourcefile_work_owner_definitions={len(init_symbols)}: expected exactly one"
        )
    from_path_symbol = next(
        (
            symbol
            for symbol in graph.definitions.values()
            if symbol.path.resolve() == door_file
            and symbol.name == "from_path"
            and symbol.lexical == (SourceFile.__name__,)
        ),
        None,
    )
    from_path_edges = tuple(
        edge for edge in graph.calls if edge.caller == from_path_symbol
    )
    from_path_construction_edges = tuple(
        edge
        for edge in from_path_edges
        if source_file_symbol is not None and source_file_symbol in edge.targets
    )
    if len(from_path_construction_edges) != 1:
        contract_reds.append(
            "R_from_path_constructor_edges="
            f"{len(from_path_construction_edges)}: expected exactly one cls(identity) edge"
        )
    runtime_owner_types = (Backend, Node, AuditReporter, SourceFragment)
    runtime_owner_locations = {
        Path(inspect.getsourcefile(owner_type) or "").resolve()
        for owner_type in runtime_owner_types
    }
    runtime_symbols = {
        symbol
        for symbol in graph.definitions.values()
        if symbol.path.resolve() in runtime_owner_locations
        and symbol.lexical
    }
    forbidden_from_path_edges = tuple(
        edge
        for edge in from_path_edges
        if set(edge.targets) & runtime_symbols
    )
    if forbidden_from_path_edges:
        contract_reds.append(
            f"R_from_path_work_edges={len(forbidden_from_path_edges)}"
        )

    # Observe the canonical from_path entry independently. No backend or
    # materialization work may occur before its one cls(identity) edge enters
    # SourceFile.__init__.
    observed_work: Counter[str] = Counter()
    premature_work: list[str] = []
    observation_path = temporary_root / "entry-observation.py"
    observation_path.write_text("VALUE = 1\n", encoding="utf-8")
    with monkeypatch.context() as observation_patch:
        backend_instance = tree_module._default_backend()
        backend_type = type(backend_instance)
        original_root = backend_type.root
        original_materialize = tree_module.materialize
        original_init = SourceFile.__init__
        original_backend_materialize = getattr(
            backend_type, "materialize_module", None
        )
        entered_init = False

        def observed_init(self, *args, **kwargs):
            nonlocal entered_init
            entered_init = True
            observed_work["constructor"] += 1
            return original_init(self, *args, **kwargs)

        def observed_root(self, *args, **kwargs):
            if not entered_init:
                premature_work.append("backend_root")
            observed_work["legacy_backend_root"] += 1
            return original_root(self, *args, **kwargs)

        def observed_materialize(*args, **kwargs):
            if not entered_init:
                premature_work.append("materialize")
            observed_work["legacy_materialize"] += 1
            return original_materialize(*args, **kwargs)

        def observed_backend_materialize(self, *args, **kwargs):
            if not entered_init:
                premature_work.append("backend_materialize_module")
            observed_work["backend_materialize_module"] += 1
            assert original_backend_materialize is not None
            return original_backend_materialize(self, *args, **kwargs)

        observation_patch.setattr(SourceFile, "__init__", observed_init)
        observation_patch.setattr(backend_type, "root", observed_root)
        observation_patch.setattr(tree_module, "materialize", observed_materialize)
        if original_backend_materialize is not None:
            observation_patch.setattr(
                backend_type,
                "materialize_module",
                observed_backend_materialize,
            )
        observed_reporter = CollectingReporter()
        source_file_entry(
            observation_path, backend_instance, observed_reporter
        )
        construction_snapshot = observed_work.copy()

    expected_entry_work = Counter(
        {"constructor": 1, "backend_materialize_module": 1}
    )
    legacy_entry_work = {
        name: count
        for name, count in construction_snapshot.items()
        if name.startswith("legacy_")
    }
    backend_event_measured = original_backend_materialize is not None
    if not backend_event_measured:
        contract_reds.append(
            "R_backend_materialize_event_unmeasured=1: canonical owner unavailable"
        )
    if premature_work:
        contract_reds.append(
            "R_from_path_premature_work=1: " + ", ".join(premature_work)
        )
    if legacy_entry_work:
        contract_reds.append(
            "R_legacy_sourcefile_work_events="
            f"{sum(legacy_entry_work.values())}: {legacy_entry_work}"
        )
    if backend_event_measured and construction_snapshot != expected_entry_work:
        contract_reds.append(
            "R_backend_materialize_event_mismatch=1: "
            f"work={dict(construction_snapshot)}"
        )
    if "constructed_module" not in SourceFile.__dict__:
        contract_reds.append(
            "R_missing_sourcefile_projection_entry=1: SourceFile.constructed_module"
        )
    if "closed_roll_call" not in SourceFile.__dict__:
        contract_reds.append(
            "R_missing_sourcefile_roll_call_entry=1: SourceFile.closed_roll_call"
        )
    source_file_leaf_projection = int("leaf_assertion_rows" in SourceFile.__dict__)
    if source_file_leaf_projection:
        contract_reds.append(
            "R_sourcefile_leaf_assertion_projection=1: downstream must consume "
            "ConstructedModule.leaf_assertion_rows directly"
        )
    if project_constructed_module is None:
        contract_reds.append(
            "R_missing_projection_definition=1: tree_enumerate.project_constructed_module"
        )
    projection_symbols = tuple(
        symbol
        for symbol in graph.definitions.values()
        if symbol.name == "project_constructed_module"
    )
    projection_call_edges = tuple(
        edge
        for edge in graph.calls
        if any(target in projection_symbols for target in edge.targets)
    )
    if not projection_symbols:
        contract_reds.append(
            "R_missing_projection_body=1: no semantic projection definition to audit"
        )
    elif len(projection_symbols) != 1:
        contract_reds.append(
            "R_projection_definition_count="
            f"{len(projection_symbols)}: expected exactly one canonical body"
        )
    projection_bindings = tuple(
        binding
        for binding in graph.bindings
        if set(binding.targets) & set(projection_symbols)
        and binding.kind in {"alias", "reexport"}
    )
    if projection_bindings:
        contract_reds.append(
            f"R_projection_alias_or_reexport={len(projection_bindings)}"
        )
    if not projection_call_edges:
        contract_reds.append(
            "R_missing_projection_callers=1: no resolved caller routes through projection"
        )
    backend_door = Backend.__dict__.get("materialize_module")
    backend_door_symbols = ()
    if backend_door is None:
        contract_reds.append(
            "R_missing_backend_materialize_owner=1: Backend.materialize_module"
        )
    else:
        backend_door_file = Path(inspect.getsourcefile(backend_door) or "").resolve()
        backend_door_line = inspect.getsourcelines(backend_door)[1]
        backend_door_symbols = tuple(
            symbol
            for symbol in graph.definitions.values()
            if symbol.path.resolve() == backend_door_file
            and symbol.line == backend_door_line
        )
        if len(backend_door_symbols) != 1:
            contract_reds.append(
                "R_backend_materialize_owner_definitions="
                f"{len(backend_door_symbols)}: expected exactly one"
            )
    legacy_materialize = backend_module.materialize
    legacy_materialize_file = Path(
        inspect.getsourcefile(legacy_materialize) or ""
    ).resolve()
    legacy_materialize_line = inspect.getsourcelines(legacy_materialize)[1]
    legacy_materialize_symbols = {
        symbol
        for symbol in graph.definitions.values()
        if symbol.path.resolve() == legacy_materialize_file
        and symbol.line == legacy_materialize_line
    }
    permitted_materialize_owners = {*init_symbols, *backend_door_symbols}
    legacy_materialize_wrappers = tuple(
        edge
        for edge in graph.calls
        if set(edge.targets) & legacy_materialize_symbols
        and edge.caller not in permitted_materialize_owners
    )
    if legacy_materialize_wrappers:
        contract_reds.append(
            "R_legacy_materialize_wrappers="
            f"{len(legacy_materialize_wrappers)}: "
            + ", ".join(
                f"{edge.path}:{edge.line}" for edge in legacy_materialize_wrappers
            )
        )

    semantic_roots = {
        symbol
        for symbol in (
            source_file_symbol,
            from_path_symbol,
            *init_symbols,
            *backend_door_symbols,
            *projection_symbols,
        )
        if symbol is not None
    }
    semantic_slice = set(semantic_roots)
    changed = True
    while changed:
        changed = False
        for edge in graph.calls:
            if edge.caller in semantic_slice and not set(edge.targets) <= semantic_slice:
                semantic_slice.update(edge.targets)
                changed = True
    relevant_dynamic = tuple(
        edge for edge in graph.calls
        if edge.dynamic
        and (
            edge.caller in semantic_slice
            or any(
                set(producers) & semantic_roots
                for producers in edge.argument_producers
            )
        )
    )
    errors.extend(
        f"{edge.path}:{edge.line}: unresolved semantic LAW_OF_ONE edge "
        f"{edge.expression!r} in {edge.caller.qualified}"
        for edge in relevant_dynamic
    )
    legacy_paths = tuple(sorted(repository_root.rglob(
        "test_roll_call_law_of_one_instrument.py"
    )))
    if legacy_paths:
        contract_reds.append(
            f"R_legacy_leaf_name_doors={len(legacy_paths)}: "
            + ", ".join(str(path) for path in legacy_paths)
        )
    if "constructed_module" not in SourceFile.__dict__:
        contract_reds.append(
            "R_unobserved_privacy_closure=1: opaque product types are unavailable"
        )
        contract_reds.extend((
            "R_protocol_closure_dormant=1: constructed product unavailable",
            "R_privacy_roster_dormant=1: constructed product unavailable",
            "R_reference_denominator_unmeasured=1: producer roster unavailable",
            "R_capability_denominator_unmeasured=1: producer roster unavailable",
            "R_projection_alias_closure_dormant=1: projection unavailable",
            "R_cross_product_refusal_dormant=1: projection unavailable",
        ))
    if relevant_dynamic:
        contract_reds.append(
            f"R_dynamic_or_unresolved_edges={len(relevant_dynamic)}"
        )
        contract_reds.extend(errors[-len(relevant_dynamic):])
    receipt = (
        f"discovered={len(discovered)}",
        f"audited={len(audited)}",
        f"unaudited={len(unaudited)}",
        f"R_duplicate_modules={len(duplicates)}",
        f"R_sourcefile_work_owner_definition_gap={abs(1 - len(init_symbols))}",
        f"R_from_path_constructor_edge_gap={abs(1 - len(from_path_construction_edges))}",
        f"R_from_path_work_edges={len(forbidden_from_path_edges)}",
        f"R_from_path_premature_work={int(bool(premature_work))}",
        f"R_legacy_sourcefile_work_events={sum(legacy_entry_work.values())}",
        "R_backend_materialize_event_unmeasured="
        f"{int(not backend_event_measured)}",
        "R_backend_materialize_event_mismatch="
        f"{int(backend_event_measured and construction_snapshot != expected_entry_work)}",
        f"R_backend_materialize_owner_gap={int(len(backend_door_symbols) != 1)}",
        f"R_legacy_materialize_wrappers={len(legacy_materialize_wrappers)}",
        f"R_dynamic_or_unresolved_edges={len(relevant_dynamic)}",
        f"R_legacy_leaf_name_doors={len(legacy_paths)}",
        f"R_sourcefile_leaf_assertion_projection={source_file_leaf_projection}",
        f"R_projection_alias_or_reexport={len(projection_bindings)}",
        "R_protocol_closure_dormant="
        f"{int('constructed_module' not in SourceFile.__dict__)}",
        "R_privacy_roster_dormant="
        f"{int('constructed_module' not in SourceFile.__dict__)}",
        "R_reference_denominator_unmeasured="
        f"{int('constructed_module' not in SourceFile.__dict__)}",
        "R_capability_denominator_unmeasured="
        f"{int('constructed_module' not in SourceFile.__dict__)}",
        "R_projection_closure_dormant="
        f"{int(project_constructed_module is None)}",
    )
    if contract_reds:
        raise AssertionError(
            "LAW_OF_ONE_RECEIPT\n"
            + "\n".join(receipt)
            + "\nLAW_OF_ONE_REDS\n"
            + "\n".join(contract_reds)
        )

    assert project_constructed_module is not None
    projection_file = Path(inspect.getsourcefile(project_constructed_module) or "").resolve()
    projection_line = inspect.getsourcelines(project_constructed_module)[1]
    owner = EvidenceSite(door_file, door_line, (SourceFile.__name__,), door.__name__)
    projection_def = EvidenceSite(projection_file, projection_line, (), project_constructed_module.__name__)

    def subclasses(cls):
        result = set(cls.__subclasses__())
        for child in tuple(result):
            result.update(subclasses(child))
        return result

    owner_defs = [
        EvidenceSite(symbol.path, symbol.line, symbol.lexical, symbol.name)
        for symbol in graph.definitions.values()
        if symbol.path.resolve() == door_file and symbol.line == door_line
    ]
    door_edges = [
        edge for edge in graph.calls
        if source_file_symbol is not None and source_file_symbol in edge.targets
    ]
    projection_edges = [
        edge for edge in graph.calls
        if any(target.path.resolve() == projection_file and target.line == projection_line for target in edge.targets)
    ]
    door_calls = [EvidenceSite(edge.path, edge.line, edge.caller.lexical, edge.caller.name) for edge in door_edges]
    projection_calls = [EvidenceSite(edge.path, edge.line, edge.caller.lexical, edge.caller.name) for edge in projection_edges]
    projection_semantic_owners = set(projection_symbols)
    changed = True
    while changed:
        changed = False
        for edge in graph.calls:
            if (
                edge.caller in projection_semantic_owners
                and not set(edge.targets) <= projection_semantic_owners
            ):
                projection_semantic_owners.update(edge.targets)
                changed = True
    projection_dynamic = tuple(
        EvidenceSite(edge.path, edge.line, edge.caller.lexical, edge.expression)
        for edge in relevant_dynamic
        if edge.caller in projection_semantic_owners
        or any(
            set(producers) & set(projection_symbols)
            for producers in edge.argument_producers
        )
    )
    overrides = []
    for source_file_type in subclasses(SourceFile):
        override = source_file_type.__dict__.get(door.__name__)
        if override is None:
            continue
        override_file = Path(inspect.getsourcefile(override) or "").resolve()
        override_line = inspect.getsourcelines(override)[1]
        overrides.append(
            EvidenceSite(
                override_file, override_line, (source_file_type.__name__,), door.__name__
            )
        )
    canonical_owner_symbols = set(init_symbols)
    door_target_symbols = {
        symbol for symbol in (source_file_symbol, *backend_door_symbols)
        if symbol is not None
    }
    forwarder_edges = tuple(
        edge
        for edge in graph.calls
        if edge.caller not in canonical_owner_symbols
        and set(edge.targets) & door_target_symbols
        and edge != from_path_construction_edges[0]
    )
    forwarders = [
        EvidenceSite(edge.path, edge.line, edge.caller.lexical, edge.caller.name)
        for edge in forwarder_edges
    ]
    assert len(owner_defs) == 1
    assert door_calls
    assert len(projection_calls) > 0
    canonical_edge = from_path_construction_edges[0]
    canonical_call = EvidenceSite(
        canonical_edge.path,
        canonical_edge.line,
        canonical_edge.caller.lexical,
        canonical_edge.caller.name,
    )
    assert from_path_symbol is not None
    source_entry = EvidenceSite(
        from_path_symbol.path,
        from_path_symbol.line,
        from_path_symbol.lexical,
        from_path_symbol.name,
    )
    work = Counter()
    original_seal = SourceFragment.seal

    def counted_seal(self, *args, **kwargs):
        work["seal"] += 1
        return original_seal(self, *args, **kwargs)

    monkeypatch.setattr(SourceFragment, "seal", counted_seal)
    original_door = door
    def counted_door(self, *args, **kwargs):
        work["constructor"] += 1
        return original_door(self, *args, **kwargs)
    monkeypatch.setattr(SourceFile, "__init__", counted_door)

    original_backend_door = Backend.materialize_module
    def counted_backend_door(self, *args, **kwargs):
        work["backend_materialize_module"] += 1
        return original_backend_door(self, *args, **kwargs)
    monkeypatch.setattr(Backend, "materialize_module", counted_backend_door)

    for cls in subclasses(Node) | {Node}:
        method = cls.__dict__.get("sugar")
        if not inspect.isfunction(method):
            continue
        def counted_sugar(self, *args, __method=method, **kwargs):
            work["sugar"] += 1
            work[
                f"sugar-operation:{__method.__module__}.{__method.__qualname__}"
            ] += 1
            return __method(self, *args, **kwargs)
        monkeypatch.setattr(cls, "sugar", counted_sugar)

    protocol_classes = {SourceFile, Node, *subclasses(Node)}
    for cls in protocol_classes:
        for name, method in tuple(cls.__dict__.items()):
            if not inspect.isfunction(method) or not inspect.isgeneratorfunction(method):
                continue
            def counted_enumeration(self, *args, __name=name, __method=method, **kwargs):
                work["enumeration"] += 1
                work[f"enumeration-operation:{__name}"] += 1
                yield from __method(self, *args, **kwargs)
            monkeypatch.setattr(cls, name, counted_enumeration)

    backend = SourceFile.__dict__.get("_default_backend", None)
    del backend
    materialize = backend_module.materialize
    def counted_materialize(*args, **kwargs):
        work["internal_materialize"] += 1
        return materialize(*args, **kwargs)
    monkeypatch.setattr(backend_module, "materialize", counted_materialize)
    monkeypatch.setattr(tree_module, "materialize", counted_materialize)
    backend_instance = tree_module._default_backend()
    backend_type = type(backend_instance)
    root_method = backend_type.root
    def counted_root(self, *args, **kwargs):
        work["backend_root"] += 1
        return root_method(self, *args, **kwargs)
    monkeypatch.setattr(backend_type, "root", counted_root)

    class Reporter(CollectingReporter):
        events: list[tuple[str, object]]
        def __init__(self):
            super().__init__()
            self.events = []

    for name, _ in inspect.getmembers(AuditReporter, inspect.isfunction):
        if name.startswith("_") or not hasattr(Reporter, name):
            continue
        method = getattr(Reporter, name)
        def observed(self, *args, __name=name, __method=method, **kwargs):
            self.events.append((__name, args[0] if args else None))
            work[f"reporter:{__name}"] += 1
            return __method(self, *args, **kwargs)
        monkeypatch.setattr(Reporter, name, observed)

    def construct(text: str, filename: str):
        path = temporary_root / filename
        path.write_text(text, encoding="utf-8")
        reporter = Reporter()
        return source_file_entry(path, backend_instance, reporter), reporter

    first, reporter = construct(
        "VALUE = 1\n"
        "def outer():\n"
        "    def child():\n"
        "        return VALUE\n"
        "    assert child() and external()\n",
        "first.py",
    )
    assert work["constructor"] == 1
    post_construction_work = work.copy()
    product = first.constructed_module
    assert product.leaf_assertion_rows, (
        "assertion-bearing source must testify an authentic leaf assertion "
        "during the sole SourceFile construction event"
    )
    authentic_leaf_assertion = product.leaf_assertion_rows[0]
    receipt = product.construction_event_receipt
    assert work == post_construction_work, (
        "constructed product, authentic assertion rows, and receipt must be "
        "stored projections of the sole SourceFile event"
    )
    assert sum(value is receipt for _, value in reporter.events) == 1
    truthful_constructor_events = work["constructor"]
    truthful_protocol = tuple(sorted(work.items()))
    work.clear()
    foreign, foreign_reporter = construct(
        "VALUE = 2\n"
        "def outer():\n"
        "    def child():\n"
        "        return VALUE\n"
        "    assert child() and foreign_external()\n",
        "foreign.py",
    )
    foreign_constructor_events = work["constructor"]
    foreign_product = foreign.constructed_module
    foreign_protocol = tuple(sorted(work.items()))
    relation_type = type(product.lexical_call_rows[0])
    member_type = type(product.provider_member_rows[0])
    leaf_assertion_type = type(authentic_leaf_assertion)
    product_type = type(product)
    assert dict(truthful_protocol)["backend_root"] == 1
    assert dict(foreign_protocol)["backend_root"] == 1
    assert dict(truthful_protocol)["backend_materialize_module"] == 1
    assert dict(foreign_protocol)["backend_materialize_module"] == 1
    assert dict(truthful_protocol).get("internal_materialize", 0) == 0
    assert dict(foreign_protocol).get("internal_materialize", 0) == 0
    assert work["sugar"] > 0
    assert dict(truthful_protocol)["enumeration"] == 1
    assert dict(foreign_protocol)["enumeration"] == 1
    assert dict(truthful_protocol)["seal"] == 1
    assert dict(foreign_protocol)["seal"] == 1
    truthful_reporter_counts = Counter(name for name, _ in reporter.events)
    foreign_reporter_counts = Counter(name for name, _ in foreign_reporter.events)
    assert truthful_reporter_counts == Counter({
        name.removeprefix("reporter:"): count
        for name, count in truthful_protocol
        if name.startswith("reporter:")
    })
    assert foreign_reporter_counts == Counter({
        name.removeprefix("reporter:"): count
        for name, count in foreign_protocol
        if name.startswith("reporter:")
    })
    assert sum(
        count for name, count in truthful_protocol
        if name.startswith("enumeration-operation:")
    ) == dict(truthful_protocol)["enumeration"]
    assert sum(
        count for name, count in foreign_protocol
        if name.startswith("enumeration-operation:")
    ) == dict(foreign_protocol)["enumeration"]
    assert sum(
        count for name, count in truthful_protocol
        if name.startswith("sugar-operation:")
    ) == dict(truthful_protocol)["sugar"]
    assert sum(
        count for name, count in foreign_protocol
        if name.startswith("sugar-operation:")
    ) == dict(foreign_protocol)["sugar"]

    assert is_dataclass(product), "constructed product must expose closed fields"

    producer_reachable = set(backend_door_symbols)
    changed = True
    while changed:
        changed = False
        for edge in graph.calls:
            if edge.caller in producer_reachable and not set(edge.targets) <= producer_reachable:
                producer_reachable.update(edge.targets)
                changed = True
    producer_roster = graph.class_symbols & producer_reachable

    def authentic_runtime_types(container: object) -> tuple[type, ...]:
        pending = [container]
        seen: set[int] = set()
        found: set[type] = set()
        while pending:
            value = pending.pop()
            if id(value) in seen:
                continue
            seen.add(id(value))
            value_type = type(value)
            location = Path(inspect.getsourcefile(value_type) or "").resolve()
            if any(
                symbol.path.resolve() == location
                and symbol.line == inspect.getsourcelines(value_type)[1]
                for symbol in producer_roster
            ):
                found.add(value_type)
            if isinstance(value, dict):
                pending.extend(value.keys())
                pending.extend(value.values())
            elif isinstance(value, (tuple, list, set, frozenset)):
                pending.extend(value)
            elif hasattr(value, "__dict__"):
                pending.extend(vars(value).values())
        return tuple(sorted(found, key=lambda item: (item.__module__, item.__qualname__)))

    product_relation_types = tuple(
        runtime_type
        for runtime_type in authentic_runtime_types(product)
        if runtime_type is not product_type
    )
    receipt_relation_types = authentic_runtime_types(receipt)
    discovered_closed_type_set = {
        product_type,
        *product_relation_types,
        *receipt_relation_types,
    }
    discovered_closed_types = tuple(
        sorted(
            discovered_closed_type_set,
            key=lambda runtime_type: (
                runtime_type.__module__, runtime_type.__qualname__
            ),
        )
    )

    type_locations = {}
    for runtime_type in discovered_closed_types:
        type_locations[runtime_type] = (
            Path(inspect.getsourcefile(runtime_type) or "").resolve(),
            inspect.getsourcelines(runtime_type)[1],
        )

    definitions = []
    constructions = []
    aliases = []
    reexports = []
    wrappers = []
    caches = []
    second_product_doors = []
    public = []
    serializers = []
    opaque_symbols = set(producer_roster)
    definitions.extend(EvidenceSite(s.path, s.line, s.lexical, s.name) for s in opaque_symbols)
    closed_factories = {
        symbol
        for symbol, producers in graph.return_producers.items()
        if set(producers) & opaque_symbols
    }
    closed_producers = opaque_symbols | closed_factories
    opaque_edges = [
        edge for edge in graph.calls if set(edge.targets) & closed_producers
    ]
    constructions.extend(EvidenceSite(e.path, e.line, e.caller.lexical, e.caller.name) for e in opaque_edges)
    function_owners = {
        binding.owner
        for binding in graph.bindings
        if binding.kind in {"parameter", "default-parameter", "classmethod"}
    }
    opaque_bindings = tuple(
        binding
        for binding in graph.bindings
        if set(binding.targets) & opaque_symbols
    )
    for binding in opaque_bindings:
        site = EvidenceSite(
            binding.path, binding.line, binding.owner.lexical, binding.name
        )
        if binding.kind == "alias":
            aliases.append(site)
        elif binding.kind == "reexport":
            reexports.append(site)
        if (
            binding.owner not in function_owners
            and any(
                read.owner != binding.owner
                and read.name == binding.name
                and set(read.producers) & opaque_symbols
                for read in graph.reads
            )
        ):
            caches.append(site)
    for symbol in opaque_symbols:
        if not symbol.name.startswith("_"):
            public.append(EvidenceSite(symbol.path, symbol.line, symbol.lexical, symbol.name))
    product_symbols = {
        symbol
        for symbol in opaque_symbols
        if symbol.path.resolve() == type_locations[product_type][0]
        and symbol.line == type_locations[product_type][1]
    }
    product_edges = tuple(
        edge for edge in graph.calls if set(edge.targets) & product_symbols
    )
    canonical_owner_symbols = set(init_symbols)
    for edge in product_edges:
        if edge.caller not in canonical_owner_symbols:
            site = EvidenceSite(
                edge.path, edge.line, edge.caller.lexical, edge.caller.name
            )
            second_product_doors.append(site)
            wrappers.append(site)
    projection_alias_sites = tuple(
        EvidenceSite(binding.path, binding.line, binding.owner.lexical, binding.name)
        for binding in projection_bindings
        if binding.kind == "alias"
    )
    projection_reexport_sites = tuple(
        EvidenceSite(binding.path, binding.line, binding.owner.lexical, binding.name)
        for binding in projection_bindings
        if binding.kind == "reexport"
    )
    projection_wrapper_sites = []
    for edge in projection_edges:
        tree = parsed[edge.path]
        parents = _parents(tree)
        matching_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and node.lineno == edge.line
        ]
        if any(isinstance(parents.get(node), ast.Return) for node in matching_calls):
            projection_wrapper_sites.append(
                EvidenceSite(edge.path, edge.line, edge.caller.lexical, edge.caller.name)
            )
    non_product_projection_callers = tuple(
        EvidenceSite(edge.path, edge.line, edge.caller.lexical, edge.caller.name)
        for edge in projection_edges
        if len(edge.argument_producers) != 1
        or not (set(edge.argument_producers[0]) & product_symbols)
    )
    def pickle_round_trip(value: object) -> object:
        return pickle.loads(pickle.dumps(value))

    for operation in (copy.copy, copy.deepcopy, pickle_round_trip):
        try:
            copied = operation(product)
        except Exception:
            continue
        assert type(copied) is product_type
        serializers.append(
            EvidenceSite(Path(__file__).resolve(), inspect.currentframe().f_lineno, (), operation.__qualname__)
        )
    opaque_reads = tuple(
        read for read in graph.reads if set(read.producers) & opaque_symbols
    )

    def ordered_sites(sites: set[EvidenceSite]) -> tuple[EvidenceSite, ...]:
        return tuple(sorted(
            sites,
            key=lambda site: (
                str(site.path), site.line, site.lexical_owner, site.symbol
            ),
        ))

    producer_relation_roster = ordered_sites({
        EvidenceSite(symbol.path, symbol.line, symbol.lexical, symbol.name)
        for symbol in producer_roster
    })
    observed_relation_roster = ordered_sites({
        EvidenceSite(symbol.path, symbol.line, symbol.lexical, symbol.name)
        for symbol in producer_roster
        if any(
            symbol.path.resolve() == location[0]
            and symbol.line == location[1]
            for location in type_locations.values()
        )
    })
    unobserved_relation_roster = tuple(
        site for site in producer_relation_roster
        if site not in set(observed_relation_roster)
    )

    discovered_reference_sites = ordered_sites({
        *(EvidenceSite(symbol.path, symbol.line, symbol.lexical, symbol.name)
          for symbol in opaque_symbols),
        *(EvidenceSite(edge.path, edge.line, edge.caller.lexical, edge.expression)
          for edge in opaque_edges),
        *(EvidenceSite(binding.path, binding.line, binding.owner.lexical, binding.name)
          for binding in opaque_bindings),
        *(EvidenceSite(read.path, read.line, read.owner.lexical, read.name)
          for read in opaque_reads),
    })
    audited_closed_types = tuple(
        runtime_type
        for runtime_type in discovered_closed_types
        if len(
            {
                symbol
                for symbol in opaque_symbols
                if symbol.path.resolve() == type_locations[runtime_type][0]
                and symbol.line == type_locations[runtime_type][1]
            }
        ) == 1
        and any(
            target.path.resolve() == type_locations[runtime_type][0]
            and target.line == type_locations[runtime_type][1]
            for edge in opaque_edges
            for target in edge.targets
        )
    )
    unaudited_closed_types = tuple(
        runtime_type
        for runtime_type in discovered_closed_types
        if runtime_type not in audited_closed_types
    )
    errors.extend(
        "unresolved closed runtime type: "
        f"{runtime_type.__module__}.{runtime_type.__qualname__}"
        for runtime_type in unaudited_closed_types
    )
    audited_opaque_symbols = {
        symbol
        for symbol in opaque_symbols
        if any(
            symbol.path.resolve() == type_locations[runtime_type][0]
            and symbol.line == type_locations[runtime_type][1]
            for runtime_type in audited_closed_types
        )
    }
    audited_reference_sites = ordered_sites({
        *(EvidenceSite(symbol.path, symbol.line, symbol.lexical, symbol.name)
          for symbol in audited_opaque_symbols),
        *(EvidenceSite(edge.path, edge.line, edge.caller.lexical, edge.expression)
          for edge in opaque_edges
          if set(edge.targets) & audited_opaque_symbols),
        *(EvidenceSite(binding.path, binding.line, binding.owner.lexical, binding.name)
          for binding in opaque_bindings
          if set(binding.targets) & audited_opaque_symbols),
        *(EvidenceSite(read.path, read.line, read.owner.lexical, read.name)
          for read in opaque_reads
          if set(read.producers) & audited_opaque_symbols),
    })
    unaudited_reference_sites = tuple(
        site for site in discovered_reference_sites
        if site not in set(audited_reference_sites)
    )
    discovered_capabilities = ordered_sites({
        *(EvidenceSite(edge.path, edge.line, edge.caller.lexical, "construct")
          for edge in opaque_edges),
        *(EvidenceSite(binding.path, binding.line, binding.owner.lexical, binding.kind)
          for binding in opaque_bindings),
        *(EvidenceSite(read.path, read.line, read.owner.lexical, "read")
          for read in opaque_reads),
    })
    audited_capabilities = ordered_sites({
        *(EvidenceSite(edge.path, edge.line, edge.caller.lexical, "construct")
          for edge in opaque_edges
          if set(edge.targets) & audited_opaque_symbols),
        *(EvidenceSite(binding.path, binding.line, binding.owner.lexical, binding.kind)
          for binding in opaque_bindings
          if set(binding.targets) & audited_opaque_symbols),
        *(EvidenceSite(read.path, read.line, read.owner.lexical, "read")
          for read in opaque_reads
          if set(read.producers) & audited_opaque_symbols),
    })
    unaudited_capabilities = tuple(
        site for site in discovered_capabilities
        if site not in set(audited_capabilities)
    )
    errors.extend(
        f"unaudited closed reference: {site.path}:{site.line}:{site.symbol}"
        for site in unaudited_reference_sites
    )
    errors.extend(
        f"unaudited closed capability: {site.path}:{site.line}:{site.symbol}"
        for site in unaudited_capabilities
    )
    errors.extend(
        f"unobserved producer-owned relation: {site.path}:{site.line}:{site.symbol}"
        for site in unobserved_relation_roster
    )
    discovered_opaque_reference_count = len(discovered_reference_sites)
    audited_opaque_reference_count = len(audited_reference_sites)

    work.clear()
    before_events = tuple(reporter.events)
    before_work = tuple(sorted(work.items()))
    stored = product.reporting_projection
    results = tuple(project_constructed_module(product) for _ in range(3))
    foreign_projection = project_constructed_module(foreign_product)
    with pytest.raises(TypeError):
        project_constructed_module(product, foreign_product.closed_roll_call)
    after_events = tuple(reporter.events)
    after_work = tuple(sorted(work.items()))

    evidence = _mint_test_owned_evidence(
        discovered=discovered,
        audited=audited,
        unaudited=unaudited,
        discovery_errors=tuple(errors),
        duplicate_modules=duplicates,
        owner_path=OwnerCallPathEvidence(
            owner=owner,
            canonical_source_file_entry=source_entry,
            canonical_call=canonical_call,
            other_owner_definitions=tuple(owner_defs[1:]),
            constructor_calls=tuple(door_calls),
            dynamic_calls=tuple(
                EvidenceSite(edge.path, edge.line, edge.caller.lexical, edge.expression)
                for edge in relevant_dynamic
                if edge.caller in {from_path_symbol, *init_symbols}
            ),
            forwarders=tuple(forwarders),
            adapter_overrides=tuple(overrides),
            discovered_calls=len(door_edges),
            audited_calls=len(door_edges),
        ),
        source_file_surfaces=SourceFileSurfaceEvidence(
            oracle_intake=source_entry,
            work_entry=owner,
            intake_constructor_edges=(canonical_call,),
            forbidden_intake_work_edges=tuple(
                EvidenceSite(edge.path, edge.line, edge.caller.lexical, edge.expression)
                for edge in forbidden_from_path_edges
            ),
            discovered_surfaces=(
                len(from_path_construction_edges) + len(forbidden_from_path_edges)
            ),
            audited_surfaces=(
                sum(not edge.dynamic for edge in from_path_construction_edges)
                + sum(not edge.dynamic for edge in forbidden_from_path_edges)
            ),
        ),
        privacy=PrivacyLeakEvidence(
            product_type, relation_type, member_type, leaf_assertion_type,
            tuple(definitions),
            tuple(constructions), tuple(aliases), tuple(reexports),
            tuple(wrappers), tuple(caches), tuple(second_product_doors),
            tuple(public), tuple(serializers),
            discovered_opaque_reference_count, audited_opaque_reference_count,
            discovered_reference_sites, audited_reference_sites,
            unaudited_reference_sites,
            discovered_capabilities, audited_capabilities,
            unaudited_capabilities,
            producer_relation_roster, observed_relation_roster,
            unobserved_relation_roster,
            discovered_closed_types, audited_closed_types,
            unaudited_closed_types,
            product_relation_types, receipt_relation_types,
        ),
        projection=ProjectionClosureEvidence(
            definition=projection_def,
            callers=tuple(projection_calls),
            dynamic_edges=projection_dynamic,
            aliases=projection_alias_sites,
            reexports=projection_reexport_sites,
            wrappers=tuple(projection_wrapper_sites),
            non_product_callers=non_product_projection_callers,
            legacy_doors=tuple(
                EvidenceSite(path, 1, (), path.name) for path in legacy_paths
            ),
            discovered_edges=len(projection_edges) + len(projection_dynamic),
            audited_edges=len(projection_edges),
        ),
        zero_work=ProtocolZeroWorkEvidence(
            product, product.closed_roll_call, stored, truthful_constructor_events,
            foreign_constructor_events, truthful_protocol, foreign_protocol,
            before_events, after_events, before_work, after_work, results,
            results[0], foreign_product, foreign_projection,
        ),
    )
    assert projection_calls
    assert projection_def.path.resolve() == projection_file
    assert len(inspect.signature(project_constructed_module).parameters) == 1, (
        "projection accepts exactly one constructed product; a foreign "
        "roll-call/projection cross-product must be uncallable"
    )
    return evidence

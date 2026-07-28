"""Executable independent, test-owned LAW_OF_ONE auditor."""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
import inspect
from pathlib import Path

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
    *, repository_root: Path, temporary_root: Path, monkeypatch: pytest.MonkeyPatch
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
    law_symbols = {
        "materialize_module",
        "project_constructed_module",
        "constructed_module",
        "closed_roll_call",
        "reporting_projection",
    }
    relevant_dynamic = tuple(
        edge for edge in graph.calls
        if edge.dynamic and edge.expression.rsplit(".", 1)[-1] in law_symbols
    )
    errors.extend(
        f"{edge.path}:{edge.line}: unresolved LAW_OF_ONE edge "
        f"{edge.expression!r} in {edge.caller.qualified}"
        for edge in relevant_dynamic
    )

    contract_reds: list[str] = []
    door = getattr(Backend, "materialize_module", None)
    if door is None:
        contract_reds.append(
            "R_missing_owner_definition=1: Backend.materialize_module"
        )
    if "constructed_module" not in SourceFile.__dict__:
        contract_reds.append(
            "R_missing_sourcefile_projection_entry=1: SourceFile.constructed_module"
        )
    if "closed_roll_call" not in SourceFile.__dict__:
        contract_reds.append(
            "R_missing_sourcefile_roll_call_entry=1: SourceFile.closed_roll_call"
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
    if not projection_call_edges:
        contract_reds.append(
            "R_missing_projection_callers=1: no resolved caller routes through projection"
        )
    legacy_paths = tuple(sorted(repository_root.rglob(
        "test_roll_call_law_of_one_instrument.py"
    )))
    if legacy_paths:
        contract_reds.append(
            f"R_legacy_leaf_name_doors={len(legacy_paths)}: "
            + ", ".join(str(path) for path in legacy_paths)
        )
    if door is None:
        contract_reds.append(
            "R_unobserved_seal_protocol_closure=1: owner product is unavailable"
        )
        contract_reds.append(
            "R_unobserved_privacy_closure=1: opaque product types are unavailable"
        )
    if relevant_dynamic:
        contract_reds.append(
            f"R_dynamic_or_unresolved_edges={len(relevant_dynamic)}"
        )
        contract_reds.extend(errors[-len(relevant_dynamic):])
    if contract_reds:
        raise AssertionError("LAW_OF_ONE_REDS\n" + "\n".join(contract_reds))

    assert door is not None
    assert project_constructed_module is not None
    door_file = Path(inspect.getsourcefile(door) or "").resolve()
    door_line = inspect.getsourcelines(door)[1]
    projection_file = Path(inspect.getsourcefile(project_constructed_module) or "").resolve()
    projection_line = inspect.getsourcelines(project_constructed_module)[1]
    owner = EvidenceSite(door_file, door_line, (Backend.__name__,), door.__name__)
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
        if any(target.path.resolve() == door_file and target.line == door_line for target in edge.targets)
    ]
    projection_edges = [
        edge for edge in graph.calls
        if any(target.path.resolve() == projection_file and target.line == projection_line for target in edge.targets)
    ]
    door_calls = [EvidenceSite(edge.path, edge.line, edge.caller.lexical, edge.caller.name) for edge in door_edges]
    projection_calls = [EvidenceSite(edge.path, edge.line, edge.caller.lexical, edge.caller.name) for edge in projection_edges]
    projection_dynamic = tuple(
        EvidenceSite(edge.path, edge.line, edge.caller.lexical, edge.expression)
        for edge in relevant_dynamic
        if edge.expression.rsplit(".", 1)[-1] == project_constructed_module.__name__
    )
    overrides = []
    for backend_type in subclasses(Backend):
        override = backend_type.__dict__.get(door.__name__)
        if override is None:
            continue
        override_file = Path(inspect.getsourcefile(override) or "").resolve()
        override_line = inspect.getsourcelines(override)[1]
        overrides.append(
            EvidenceSite(
                override_file, override_line, (backend_type.__name__,), door.__name__
            )
        )
    forwarders = []
    source_methods: dict[object, tuple[EvidenceSite, set[object]]] = {}
    assert len(owner_defs) == 1
    assert len(door_calls) == 1
    assert len(projection_calls) > 0
    canonical_call = door_calls[0]
    source_entry = EvidenceSite(
        canonical_call.path,
        canonical_call.line,
        canonical_call.lexical_owner[:-1],
        canonical_call.lexical_owner[-1],
    )
    source_file_path = Path(inspect.getsourcefile(SourceFile) or "").resolve()
    for symbol in graph.definitions.values():
        if symbol.path.resolve() != source_file_path or SourceFile.__name__ not in symbol.lexical:
            continue
        targets = {
            target for edge in graph.calls if edge.caller == symbol for target in edge.targets
        }
        source_methods[symbol] = (
            EvidenceSite(symbol.path, symbol.line, symbol.lexical[:-1], symbol.name),
            targets,
        )
    # Any transitive caller of the door other than the canonical SourceFile
    # entry is a forwarder. Resolve over concrete symbol edges, not spellings.
    reverse: dict[object, set[object]] = defaultdict(set)
    for edge in graph.calls:
        for target in edge.targets:
            reverse[target].add(edge.caller)
    door_symbols = {
        target for edge in door_edges for target in edge.targets
    }
    frontier = set(door_symbols)
    seen = set(frontier)
    while frontier:
        target = frontier.pop()
        for caller in reverse.get(target, ()):
            if caller not in seen:
                seen.add(caller)
                frontier.add(caller)
    canonical_caller = door_edges[0].caller
    for symbol in seen:
        if symbol == canonical_caller:
            continue
        if symbol.path.resolve() == door_file and symbol.line == door_line:
            continue
        forwarders.append(EvidenceSite(symbol.path, symbol.line, symbol.lexical, symbol.name))

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
    monkeypatch.setattr(Backend, "materialize_module", counted_door)

    for cls in subclasses(Node) | {Node}:
        method = cls.__dict__.get("sugar")
        if not inspect.isfunction(method):
            continue
        def counted_sugar(self, *args, __method=method, **kwargs):
            work["sugar"] += 1
            return __method(self, *args, **kwargs)
        monkeypatch.setattr(cls, "sugar", counted_sugar)

    for cls in (SourceFile, Node):
        for name, method in tuple(cls.__dict__.items()):
            if not inspect.isfunction(method) or not inspect.isgeneratorfunction(method):
                continue
            def counted_enumeration(self, *args, __name=name, __method=method, **kwargs):
                work[f"enumeration:{__name}"] += 1
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
            work["protocol"] += 1
            return __method(self, *args, **kwargs)
        monkeypatch.setattr(Reporter, name, observed)

    def construct(text: str, filename: str):
        path = temporary_root / filename
        path.write_text(text, encoding="utf-8")
        reporter = Reporter()
        return SourceFile.from_path(path, backend=backend_instance, reporter=reporter), reporter

    first, reporter = construct(
        "VALUE = 1\ndef outer():\n    def child():\n        return VALUE\n    return child()\n",
        "first.py",
    )
    product = first.constructed_module
    receipt = product.construction_event_receipt
    assert sum(value is receipt for _, value in reporter.events) == 1
    truthful_constructor_events = work["constructor"]
    truthful_protocol = tuple(sorted(work.items()))
    work.clear()
    foreign, _ = construct(
        "VALUE = 2\ndef outer():\n    def child():\n        return VALUE\n    return child()\n",
        "foreign.py",
    )
    foreign_constructor_events = work["constructor"]
    foreign_product = foreign.constructed_module
    foreign_protocol = tuple(sorted(work.items()))
    relation_type = type(product.lexical_call_rows[0])
    member_type = type(product.provider_member_rows[0])
    product_type = type(product)
    assert dict(truthful_protocol)["backend_root"] == 1
    assert dict(foreign_protocol)["backend_root"] == 1
    assert work["internal_materialize"] > 0
    assert work["sugar"] > 0
    assert work["protocol"] > 0
    assert dict(truthful_protocol)["seal"] > 0
    assert dict(foreign_protocol)["seal"] > 0

    type_locations = {}
    for runtime_type in (product_type, relation_type, member_type):
        type_locations[runtime_type] = (
            Path(inspect.getsourcefile(runtime_type) or "").resolve(),
            inspect.getsourcelines(runtime_type)[1],
        )

    definitions = []
    constructions = []
    aliases = []
    reexports = []
    public = []
    serializers = []
    opaque_symbols = {
        symbol for symbol in graph.definitions.values()
        if any(symbol.path.resolve() == location[0] and symbol.line == location[1] for location in type_locations.values())
    }
    definitions.extend(EvidenceSite(s.path, s.line, s.lexical, s.name) for s in opaque_symbols)
    opaque_edges = [edge for edge in graph.calls if set(edge.targets) & opaque_symbols]
    constructions.extend(EvidenceSite(e.path, e.line, e.caller.lexical, e.caller.name) for e in opaque_edges)
    for binding in graph.bindings:
        if not (set(binding.targets) & opaque_symbols):
            continue
        site = EvidenceSite(
            binding.path, binding.line, binding.owner.lexical, binding.name
        )
        if binding.kind == "alias":
            aliases.append(site)
        elif binding.kind == "reexport":
            reexports.append(site)
    for symbol in opaque_symbols:
        if not symbol.name.startswith("_"):
            public.append(EvidenceSite(symbol.path, symbol.line, symbol.lexical, symbol.name))
    serializer_names = {
        "asdict", "dict", "json", "model_dump", "model_dump_json",
        "serialize", "to_dict", "to_json",
    }
    opaque_lexical_owners = {
        (*symbol.lexical, symbol.name) for symbol in opaque_symbols
    }
    for symbol in graph.definitions.values():
        if (
            symbol.name in serializer_names
            and any(
                symbol.lexical[: len(owner)] == owner
                for owner in opaque_lexical_owners
            )
        ):
            serializers.append(
                EvidenceSite(symbol.path, symbol.line, symbol.lexical, symbol.name)
            )
    audited_opaque_reference_count = (
        len(opaque_symbols) + len(opaque_edges) + len(aliases)
        + len(reexports) + len(serializers)
    )
    opaque_names = {symbol.name for symbol in opaque_symbols}
    discovered_opaque_reference_count = sum(
        1
        for tree in parsed.values()
        for node in ast.walk(tree)
        if isinstance(node, (ast.Name, ast.Attribute))
        and (
            (isinstance(node, ast.Name) and node.id in opaque_names)
            or (isinstance(node, ast.Attribute) and node.attr in opaque_names)
        )
    ) + len(opaque_symbols)

    door_symbol = next(iter(door_symbols))
    reaches = {symbol: door_symbol in calls for symbol, (_, calls) in source_methods.items()}
    changed = True
    while changed:
        changed = False
        for symbol, (_, calls) in source_methods.items():
            value = reaches[symbol] or any(reaches.get(callee, False) for callee in calls)
            if value != reaches[symbol]:
                reaches[symbol] = value
                changed = True
    constructing_surfaces = tuple(
        site for symbol, (site, _) in source_methods.items()
        if reaches[symbol] and site != source_entry
    )
    pure_surfaces = tuple(
        site for symbol, (site, _) in source_methods.items()
        if not reaches[symbol]
    )

    work.clear()
    before_events = tuple(reporter.events)
    before_work = tuple(sorted(work.items()))
    stored = product.reporting_projection
    results = tuple(project_constructed_module(product) for _ in range(3))
    foreign_projection = project_constructed_module(foreign_product)
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
            other_constructor_calls=tuple(door_calls[1:]),
            forwarders=tuple(forwarders),
            adapter_overrides=tuple(overrides),
            discovered_calls=len(graph.calls),
            audited_calls=sum(not edge.dynamic for edge in graph.calls),
        ),
        source_file_surfaces=SourceFileSurfaceEvidence(
            source_entry, pure_surfaces, constructing_surfaces,
            len(source_methods),
            sum(
                all(not edge.dynamic for edge in graph.calls if edge.caller == symbol)
                for symbol in source_methods
            ),
        ),
        privacy=PrivacyLeakEvidence(
            product_type, relation_type, member_type, tuple(definitions),
            tuple(constructions), tuple(aliases), tuple(reexports),
            tuple(public), tuple(serializers),
            discovered_opaque_reference_count, audited_opaque_reference_count,
        ),
        projection=ProjectionClosureEvidence(
            definition=projection_def,
            callers=tuple(projection_calls),
            dynamic_edges=projection_dynamic,
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
    assert len(projection_calls) == 1
    assert projection_calls[0].path.resolve() == projection_file
    assert projection_def.path.resolve() == projection_file
    assert len(inspect.signature(project_constructed_module).parameters) == 1, (
        "projection accepts exactly one constructed product; a foreign "
        "roll-call/projection cross-product must be uncallable"
    )
    return evidence

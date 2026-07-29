"""Exact-span, dual-door retirement instrument for FactoryBuildContext."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import importlib.util
from pathlib import Path
import re
import sys
import tokenize

import pytest


_PACKAGE_MARKER = Path(
    "implementations/python/sugar-lift-py-tests/src/"
    "sugar_lift_py_tests/context/reduce_context.py"
)


def _discover_repo() -> Path:
    candidates: set[Path] = set()
    artifact = Path(__file__).resolve()
    spec = importlib.util.find_spec("sugar_lift_py_tests")
    installed = None if spec is None or spec.origin is None else Path(spec.origin).resolve()
    if installed is not None:
        for candidate in installed.parents:
            package_root = candidate / "implementations/python/sugar-lift-py-tests/src"
            package_init = package_root / "sugar_lift_py_tests/__init__.py"
            if (
                (candidate / _PACKAGE_MARKER).is_file()
                and package_init.resolve() == installed
                and (candidate / "sugar-build.toml").is_file()
            ):
                candidates.add(candidate.resolve())
    assert len(candidates) == 1, (
        "ontology instrument requires exactly one git- and package-authenticated source root; "
        f"artifact={artifact} installed={installed} "
        f"candidates={sorted(map(str, candidates))!r}"
    )
    return next(iter(candidates))


REPO = _discover_repo()
PYTHON = REPO / "implementations/python"
PRODUCTION_ROOTS = tuple(sorted(PYTHON.glob("*/src")))
TARGET_MODULE = "sugar_lift_py_tests.context.factory_build_context"
TARGET_NAME = "FactoryBuildContext"

# Ratchet only: neither production discovery nor raw discovery consumes it.
EXPECTED_RAW_BY_FILE = {
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/callable_application.py": 2,
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/context/__init__.py": 2,
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/context/factory_build_context.py": 5,
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/context/reduce_context.py": 3,
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/context/sink_protocols.py": 1,
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/floor_dispatch_surface.py": 35,
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/floor_value.py": 35,
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/object_method_value.py": 1,
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/object_value.py": 25,
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/string_value.py": 2,
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/generator_construction.py": 1,
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/in_flight_effect.py": 1,
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/try_star_sugar.py": 1,
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar_body/sugar_body.py": 2,
}


@dataclass(frozen=True, order=True)
class Span:
    line: int
    column: int
    end_line: int
    end_column: int


@dataclass(frozen=True, order=True)
class RawRow:
    path: str
    span: Span
    token_kind: str
    detail: str


@dataclass(frozen=True, order=True)
class SemanticRow:
    raw: RawRow
    category: str
    authority: str


@dataclass(frozen=True, order=True)
class OntologyImpact:
    path: str
    span: Span
    kind: str
    authority: Symbol


@dataclass(frozen=True)
class Symbol:
    module: str
    name: str


@dataclass(frozen=True)
class ReachingDefinition:
    name: str
    node: ast.AST
    symbol: Symbol | None = None
    expression: ast.AST | None = None
    deleted: bool = False
    scope_owner: str = "local"


@dataclass(frozen=True)
class ModuleFacts:
    path: Path
    module: str
    package: str
    tree: ast.Module
    parents: dict[ast.AST, ast.AST]


Environment = dict[str, frozenset[ReachingDefinition]]


@dataclass(frozen=True)
class ReachingIndex:
    before: dict[tuple[str, tuple[tuple[str, str, int, int], ...], str, Span], Environment]
    module_exit: Environment


@dataclass(frozen=True)
class FlowFaces:
    normal: Environment | None
    returned: tuple[Environment, ...] = ()
    raised: tuple[Environment, ...] = ()
    broken: tuple[Environment, ...] = ()
    continued: tuple[Environment, ...] = ()


_REACHING_CACHE: dict[tuple[str, str, str], ReachingIndex] = {}


def _node_occurrence(
    facts: ModuleFacts, node: ast.AST
) -> tuple[str, tuple[tuple[str, str, int, int], ...], str, Span]:
    lexical: list[tuple[str, str, int, int]] = []
    parent = facts.parents.get(node)
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)) and _has_span(parent):
            lexical.append((type(parent).__name__, getattr(parent, "name", "<lambda>"), parent.lineno, parent.col_offset))
        parent = facts.parents.get(parent)
    return (facts.module, tuple(reversed(lexical)), type(node).__name__, _node_span(node))


def _before_environment(facts: ModuleFacts, node: ast.AST) -> Environment:
    index = _reaching_index(facts)
    if not _has_span(node):
        return index.module_exit
    return index.before.get(_node_occurrence(facts, node), index.module_exit)


def _production_files() -> tuple[Path, ...]:
    return tuple(sorted(
        path
        for root in PRODUCTION_ROOTS
        for path in root.rglob("*.py")
        if "tests" not in path.parts and not path.name.startswith("test_")
    ))


def _test_files() -> tuple[Path, ...]:
    return tuple(sorted(
        path
        for path in PYTHON.rglob("*.py")
        if "tests" in path.parts or path.name.startswith("test_")
    ))


def _production_module(path: Path) -> str:
    root = next(root for root in PRODUCTION_ROOTS if path.is_relative_to(root))
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _test_module(path: Path) -> str:
    # Tests never share identities with production or with another package's test.
    return "__test__." + ".".join(path.relative_to(PYTHON).with_suffix("").parts)


def _path_identity(path: Path) -> str:
    """Give repository files their checkout identity and fixtures a stable local identity."""
    if path.is_relative_to(REPO):
        return path.relative_to(REPO).as_posix()
    return f"__fixture__/{path.name}"


def _node_span(node: ast.AST) -> Span:
    return Span(node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


def _has_span(node: ast.AST) -> bool:
    return all(getattr(node, field, None) is not None for field in ("lineno", "col_offset", "end_lineno", "end_col_offset"))


def _contains(outer: Span, inner: Span) -> bool:
    return (outer.line, outer.column) <= (inner.line, inner.column) and (
        inner.end_line, inner.end_column
    ) <= (outer.end_line, outer.end_column)


def _relative_module(module: str, package: str, level: int) -> str:
    if level == 0:
        return module
    base = package.split(".") if package else []
    base = base[: len(base) - (level - 1)]
    return ".".join((*base, *module.split("."))) if module else ".".join(base)


def _facts(path: Path, *, module: str) -> ModuleFacts:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    return ModuleFacts(path, module, package, tree, parents)


def _merge_environments(*environments: Environment) -> Environment:
    names = set().union(*(environment for environment in environments))
    return {
        name: frozenset().union(*(environment.get(name, frozenset()) for environment in environments))
        for name in names
    }


def _with_definition(environment: Environment, definition: ReachingDefinition) -> Environment:
    updated = dict(environment)
    updated[definition.name] = frozenset((definition,))
    return updated


def _add_definition(environment: Environment, definition: ReachingDefinition) -> Environment:
    updated = dict(environment)
    updated[definition.name] = updated.get(definition.name, frozenset()) | frozenset((definition,))
    return updated


def _reaching_index(facts: ModuleFacts) -> ReachingIndex:
    cache_key = (
        facts.module,
        _path_identity(facts.path),
        hashlib.sha256(facts.path.read_bytes()).hexdigest(),
    )
    cached = _REACHING_CACHE.get(cache_key)
    if cached is not None:
        return cached
    before: dict[tuple[str, tuple[tuple[str, str, int, int], ...], str, Span], Environment] = {}

    def store_before(node: ast.AST, environment: Environment) -> None:
        if not _has_span(node):
            return
        key = _node_occurrence(facts, node)
        before[key] = _merge_environments(before[key], environment) if key in before else dict(environment)

    def target_names(target: ast.AST) -> tuple[str, ...]:
        if isinstance(target, ast.Name):
            return (target.id,)
        if isinstance(target, ast.Starred):
            return target_names(target.value)
        if isinstance(target, (ast.Tuple, ast.List)):
            return tuple(name for element in target.elts for name in target_names(element))
        return ()

    def pattern_names(pattern: ast.pattern) -> tuple[str, ...]:
        if isinstance(pattern, ast.MatchAs):
            return ((pattern.name,) if pattern.name else ()) + (
                pattern_names(pattern.pattern) if pattern.pattern is not None else ()
            )
        if isinstance(pattern, ast.MatchStar):
            return (pattern.name,) if pattern.name else ()
        if isinstance(pattern, ast.MatchMapping):
            return tuple(name for child in pattern.patterns for name in pattern_names(child)) + (
                (pattern.rest,) if pattern.rest else ()
            )
        if isinstance(pattern, ast.MatchSequence):
            return tuple(name for child in pattern.patterns for name in pattern_names(child))
        if isinstance(pattern, ast.MatchClass):
            return tuple(
                name for child in (*pattern.patterns, *pattern.kwd_patterns) for name in pattern_names(child)
            )
        if isinstance(pattern, ast.MatchOr):
            alternatives = tuple(frozenset(pattern_names(child)) for child in pattern.patterns)
            if alternatives and len(set(alternatives)) != 1:
                raise AssertionError(f"match alternatives bind different names at {facts.path}:{pattern.lineno}")
            return tuple(sorted(next(iter(alternatives), frozenset())))
        return ()

    def owned_nodes(node: ast.AST):
        """Walk one lexical scope, pruning nested definition-time scopes."""
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        for child in ast.iter_child_nodes(node):
            yield from owned_nodes(child)

    def declarations(statements: list[ast.stmt]) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
        globals_: set[str] = set()
        nonlocals: set[str] = set()
        locals_: set[str] = set()
        for statement in statements:
            for node in owned_nodes(statement):
                if isinstance(node, ast.Global):
                    globals_.update(node.names)
                elif isinstance(node, ast.Nonlocal):
                    nonlocals.update(node.names)
                elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
                    targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
                    locals_.update(name for target in targets for name in target_names(target))
                elif isinstance(node, (ast.For, ast.AsyncFor)):
                    locals_.update(target_names(node.target))
                elif isinstance(node, (ast.With, ast.AsyncWith)):
                    locals_.update(
                        name for item in node.items if item.optional_vars is not None
                        for name in target_names(item.optional_vars)
                    )
                elif isinstance(node, ast.ExceptHandler) and node.name:
                    locals_.add(node.name)
                elif isinstance(node, ast.match_case):
                    locals_.update(pattern_names(node.pattern))
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    locals_.update(
                        alias.asname or (alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name)
                        for alias in node.names if alias.name != "*"
                    )
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    locals_.add(node.name)
        overlap = globals_ & nonlocals
        if overlap:
            raise AssertionError(f"global/nonlocal overlap at {facts.path}: {sorted(overlap)!r}")
        return frozenset(globals_), frozenset(nonlocals), frozenset(locals_ - globals_ - nonlocals)

    def record(
        node: ast.AST | None,
        environment: Environment,
        *,
        walrus_exports: list[ReachingDefinition] | None = None,
    ) -> Environment:
        if node is None:
            return environment
        store_before(node, environment)
        if isinstance(node, ast.NamedExpr):
            environment = record(node.value, environment, walrus_exports=walrus_exports)
            environment = bind_target(node.target, node.value, environment)
            if walrus_exports is not None and isinstance(node.target, ast.Name):
                walrus_exports.append(ReachingDefinition(node.target.id, node.target, expression=node.value))
            store_before(node.target, environment)
            return environment
        if isinstance(node, ast.Lambda):
            for default in (*node.args.defaults, *node.args.kw_defaults):
                environment = record(default, environment)
            local = dict(environment)
            for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                local = _with_definition(local, ReachingDefinition(argument.arg, argument))
            record(node.body, local, walrus_exports=None)
            return environment
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            local = dict(environment)
            exports: list[ReachingDefinition] = []
            for generator in node.generators:
                local = record(generator.iter, local, walrus_exports=exports)
                local = bind_target(generator.target, None, local)
                for condition in generator.ifs:
                    local = record(condition, local, walrus_exports=exports)
            if isinstance(node, ast.DictComp):
                local = record(node.key, local, walrus_exports=exports)
                record(node.value, local, walrus_exports=exports)
            else:
                record(node.elt, local, walrus_exports=exports)
            for definition in exports:
                environment = _with_definition(environment, definition)
            return environment
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                continue
            environment = record(child, environment, walrus_exports=walrus_exports)
        return environment

    def bind_target(
        target: ast.AST,
        value: ast.AST | None,
        environment: Environment,
        global_names: frozenset[str] = frozenset(),
        nonlocal_names: frozenset[str] = frozenset(),
    ) -> Environment:
        if isinstance(target, ast.Name):
            owner = "module" if target.id in global_names else "nonlocal" if target.id in nonlocal_names else "local"
            return _with_definition(
                environment,
                ReachingDefinition(target.id, target, expression=value, scope_owner=owner),
            )
        if isinstance(target, (ast.Tuple, ast.List)):
            result = environment
            for element in target.elts:
                result = bind_target(element, None, result, global_names, nonlocal_names)
            return result
        if isinstance(target, ast.Starred):
            return bind_target(target.value, value, environment, global_names, nonlocal_names)
        if isinstance(target, ast.Attribute):
            return _add_definition(
                environment,
                ReachingDefinition(f"@attribute:{target.attr}", target, expression=value),
            )
        return environment

    def join_normal(*environments: Environment | None) -> Environment | None:
        present = tuple(environment for environment in environments if environment is not None)
        return _merge_environments(*present) if present else None

    def combine(*faces: FlowFaces) -> FlowFaces:
        return FlowFaces(
            join_normal(*(face.normal for face in faces)),
            tuple(environment for face in faces for environment in face.returned),
            tuple(environment for face in faces for environment in face.raised),
            tuple(environment for face in faces for environment in face.broken),
            tuple(environment for face in faces for environment in face.continued),
        )

    def flow_block(
        statements: list[ast.stmt],
        incoming: Environment,
        global_names: frozenset[str] = frozenset(),
        nonlocal_names: frozenset[str] = frozenset(),
    ) -> FlowFaces:
        environment: Environment | None = dict(incoming)
        returned: list[Environment] = []
        raised: list[Environment] = []
        broken: list[Environment] = []
        continued: list[Environment] = []
        for statement in statements:
            if environment is None:
                break
            store_before(statement, environment)
            if isinstance(statement, ast.ImportFrom):
                provider = _relative_module(statement.module or "", facts.package, statement.level)
                for imported in statement.names:
                    if imported.name == "*":
                        environment = _add_definition(
                            environment,
                            ReachingDefinition("@star", imported, symbol=Symbol(provider, "*")),
                        )
                    else:
                        environment = _with_definition(environment, ReachingDefinition(
                            imported.asname or imported.name,
                            imported,
                            symbol=Symbol(provider, imported.name),
                        ))
                record(statement, environment)
            elif isinstance(statement, ast.Import):
                for imported in statement.names:
                    local = imported.asname or imported.name.split(".")[0]
                    environment = _with_definition(environment, ReachingDefinition(local, imported, symbol=Symbol(imported.name, "")))
                record(statement, environment)
            elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                value = statement.value
                environment = record(value, environment)
                targets = statement.targets if isinstance(statement, ast.Assign) else (statement.target,)
                for target in targets:
                    environment = bind_target(target, value, environment, global_names, nonlocal_names)
                    record(target, environment)
            elif isinstance(statement, ast.AugAssign):
                environment = record(statement.target, environment)
                environment = record(statement.value, environment)
                environment = bind_target(
                    statement.target, None, environment, global_names, nonlocal_names
                )
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for expression in (*statement.decorator_list, *statement.args.defaults, *statement.args.kw_defaults, statement.returns):
                    environment = record(expression, environment)
                environment = _with_definition(environment, ReachingDefinition(statement.name, statement))
                local = dict(environment)
                for argument in (*statement.args.posonlyargs, *statement.args.args, *statement.args.kwonlyargs):
                    local = _with_definition(local, ReachingDefinition(argument.arg, argument))
                    record(argument.annotation, environment)
                if statement.args.vararg is not None:
                    local = _with_definition(local, ReachingDefinition(statement.args.vararg.arg, statement.args.vararg))
                if statement.args.kwarg is not None:
                    local = _with_definition(local, ReachingDefinition(statement.args.kwarg.arg, statement.args.kwarg))
                global_names, nonlocal_names, local_names = declarations(statement.body)
                # Python decides the whole function's locals at definition time.
                for name in local_names:
                    local = _with_definition(
                        local, ReachingDefinition(name, statement, scope_owner="predeclared")
                    )
                flow_block(statement.body, local, global_names, nonlocal_names)
            elif isinstance(statement, ast.ClassDef):
                for expression in (*statement.decorator_list, *statement.bases, *(keyword.value for keyword in statement.keywords)):
                    record(expression, environment)
                environment = _with_definition(environment, ReachingDefinition(statement.name, statement))
                flow_block(statement.body, dict(environment))
            elif isinstance(statement, ast.If):
                environment = record(statement.test, environment)
                branches = combine(
                    flow_block(statement.body, dict(environment), global_names, nonlocal_names),
                    flow_block(statement.orelse, dict(environment), global_names, nonlocal_names),
                )
                environment = branches.normal
                returned.extend(branches.returned); raised.extend(branches.raised)
                broken.extend(branches.broken); continued.extend(branches.continued)
            elif isinstance(statement, (ast.For, ast.AsyncFor)):
                environment = record(statement.iter, environment)
                loop_environment = bind_target(statement.target, None, environment, global_names, nonlocal_names)
                while True:
                    body = flow_block(statement.body, loop_environment, global_names, nonlocal_names)
                    recurrence = join_normal(body.normal, *body.continued)
                    next_environment = join_normal(environment, loop_environment, recurrence)
                    assert next_environment is not None
                    if next_environment == loop_environment:
                        break
                    loop_environment = next_environment
                else_in = join_normal(environment, body.normal)
                assert else_in is not None
                else_face = flow_block(statement.orelse, else_in, global_names, nonlocal_names)
                environment = join_normal(else_face.normal, *body.broken)
                returned.extend((*body.returned, *else_face.returned))
                raised.extend((*body.raised, *else_face.raised))
                continued.extend(else_face.continued); broken.extend(else_face.broken)
            elif isinstance(statement, ast.While):
                environment = record(statement.test, environment)
                loop_environment = dict(environment)
                while True:
                    body = flow_block(statement.body, loop_environment, global_names, nonlocal_names)
                    recurrence = join_normal(body.normal, *body.continued)
                    next_environment = join_normal(environment, recurrence)
                    assert next_environment is not None
                    next_environment = record(statement.test, next_environment)
                    if next_environment == loop_environment:
                        break
                    loop_environment = next_environment
                else_in = join_normal(environment, body.normal)
                assert else_in is not None
                else_face = flow_block(statement.orelse, else_in, global_names, nonlocal_names)
                environment = join_normal(else_face.normal, *body.broken)
                returned.extend((*body.returned, *else_face.returned))
                raised.extend((*body.raised, *else_face.raised))
                continued.extend(else_face.continued); broken.extend(else_face.broken)
            elif isinstance(statement, (ast.Try, ast.TryStar)):
                body_face = flow_block(statement.body, dict(environment), global_names, nonlocal_names)
                handler_faces = []
                for handler in statement.handlers:
                    raised_inputs = body_face.raised or (dict(environment),)
                    for raised_environment in raised_inputs:
                        handler_environment = dict(raised_environment)
                        record(handler.type, handler_environment)
                        if handler.name:
                            handler_environment = _with_definition(
                                handler_environment, ReachingDefinition(handler.name, handler)
                            )
                        handler_faces.append(
                            flow_block(handler.body, handler_environment, global_names, nonlocal_names)
                        )
                else_face = flow_block(statement.orelse, body_face.normal, global_names, nonlocal_names) if body_face.normal is not None else FlowFaces(None)
                pre_final = combine(else_face, *handler_faces, FlowFaces(
                    None, body_face.returned, (), body_face.broken, body_face.continued
                ))
                if statement.finalbody:
                    final_outputs: list[FlowFaces] = []
                    for face_name, inputs in (
                        ("normal", (() if pre_final.normal is None else (pre_final.normal,))),
                        ("returned", pre_final.returned), ("raised", pre_final.raised),
                        ("broken", pre_final.broken), ("continued", pre_final.continued),
                    ):
                        for input_environment in inputs:
                            final = flow_block(statement.finalbody, input_environment, global_names, nonlocal_names)
                            if final.normal is not None:
                                final = FlowFaces(
                                    final.normal if face_name == "normal" else None,
                                    final.returned + ((final.normal,) if face_name == "returned" else ()),
                                    final.raised + ((final.normal,) if face_name == "raised" else ()),
                                    final.broken + ((final.normal,) if face_name == "broken" else ()),
                                    final.continued + ((final.normal,) if face_name == "continued" else ()),
                                )
                            final_outputs.append(final)
                    pre_final = combine(*final_outputs)
                environment = pre_final.normal
                returned.extend(pre_final.returned); raised.extend(pre_final.raised)
                broken.extend(pre_final.broken); continued.extend(pre_final.continued)
            elif isinstance(statement, (ast.With, ast.AsyncWith)):
                local = dict(environment)
                for item in statement.items:
                    local = record(item.context_expr, local)
                    if item.optional_vars is not None:
                        local = bind_target(item.optional_vars, item.context_expr, local, global_names, nonlocal_names)
                face = flow_block(statement.body, local, global_names, nonlocal_names)
                environment = face.normal
                returned.extend(face.returned); raised.extend(face.raised)
                broken.extend(face.broken); continued.extend(face.continued)
            elif isinstance(statement, ast.Match):
                environment = record(statement.subject, environment)
                exits = []
                for case in statement.cases:
                    record(case.pattern, environment)
                    record(case.guard, environment)
                    case_environment = dict(environment)
                    for name in pattern_names(case.pattern):
                        owner = "module" if name in global_names else "nonlocal" if name in nonlocal_names else "local"
                        case_environment = _with_definition(
                            case_environment, ReachingDefinition(name, case.pattern, scope_owner=owner)
                        )
                    exits.append(flow_block(case.body, case_environment, global_names, nonlocal_names))
                matched = combine(*exits)
                environment = join_normal(environment, matched.normal)
                returned.extend(matched.returned); raised.extend(matched.raised)
                broken.extend(matched.broken); continued.extend(matched.continued)
            elif isinstance(statement, ast.Delete):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        environment = _with_definition(environment, ReachingDefinition(target.id, target, deleted=True))
                    elif isinstance(target, ast.Attribute):
                        environment = _add_definition(
                            environment,
                            ReachingDefinition(f"@attribute:{target.attr}", target, deleted=True),
                        )
                record(statement, environment)
            else:
                environment = record(statement, environment)
                if isinstance(statement, ast.Return):
                    returned.append(environment); environment = None
                elif isinstance(statement, ast.Raise):
                    raised.append(environment); environment = None
                elif isinstance(statement, ast.Break):
                    broken.append(environment); environment = None
                elif isinstance(statement, ast.Continue):
                    continued.append(environment); environment = None
        return FlowFaces(environment, tuple(returned), tuple(raised), tuple(broken), tuple(continued))

    module_face = flow_block(facts.tree.body, {})
    module_exit = module_face.normal or {}
    result = ReachingIndex(before, module_exit)
    _REACHING_CACHE[cache_key] = result
    return result


def _attribute_parts(node: ast.AST) -> tuple[str, ...] | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return tuple(reversed((*parts, node.id)))


def _declared_exports(facts: ModuleFacts) -> frozenset[str] | None:
    for statement in facts.tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else (statement.target,)
            if any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
                value = statement.value
                if isinstance(value, (ast.List, ast.Tuple, ast.Set)) and all(
                    isinstance(element, ast.Constant) and isinstance(element.value, str)
                    for element in value.elts
                ):
                    return frozenset(element.value for element in value.elts)
                raise AssertionError(f"dynamic __all__ is outside retirement resolver: {facts.path}:{statement.lineno}")
    return None


def _resolve_definition(
    definition: ReachingDefinition,
    facts: ModuleFacts,
    graph: dict[str, ModuleFacts],
    seen: frozenset[tuple[str, str, int, int, int, int]],
) -> Symbol | None:
    span = _node_span(definition.node)
    key = (facts.module, definition.name, span.line, span.column, span.end_line, span.end_column)
    if key in seen:
        if any(module == TARGET_MODULE or name == TARGET_NAME for module, name, *_ in seen | {key}):
            raise AssertionError(f"target resolved-definition cycle at {facts.path}:{getattr(definition.node, 'lineno', '?')}")
        return None
    if definition.deleted:
        return None
    if definition.scope_owner == "predeclared":
        return None
    if definition.symbol is not None:
        symbol = definition.symbol
        if symbol.name == "":
            return symbol
        provider = graph.get(symbol.module)
        if provider is None:
            return symbol
        return _resolve_export(symbol.name, provider, graph, seen | {key}, star=False)
    if definition.expression is not None:
        return _resolve(definition.expression, facts, graph, seen | {key})
    if isinstance(definition.node, ast.ClassDef):
        return Symbol(facts.module, definition.node.name)
    if isinstance(definition.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return Symbol(facts.module, definition.node.name)
    return None


def _resolve_export(
    name: str,
    provider: ModuleFacts,
    graph: dict[str, ModuleFacts],
    seen: frozenset[tuple[str, str, int, int, int, int]],
    *,
    star: bool,
) -> Symbol | None:
    exports = _declared_exports(provider)
    if star and ((exports is not None and name not in exports) or (exports is None and name.startswith("_"))):
        return None
    definitions = _reaching_index(provider).module_exit.get(name, frozenset())
    resolved = {
        symbol for definition in definitions
        if (symbol := _resolve_definition(definition, provider, graph, seen)) is not None
    }
    star_resolved = set()
    for definition in _reaching_index(provider).module_exit.get("@star", frozenset()):
        star_module = definition.symbol.module if definition.symbol is not None else ""
        upstream = graph.get(star_module)
        if upstream is not None:
            symbol = _resolve_export(name, upstream, graph, seen, star=True)
            if symbol is not None:
                star_resolved.add(symbol)
    resolved |= star_resolved
    if len(resolved) > 1 and Symbol(TARGET_MODULE, TARGET_NAME) in resolved:
        raise AssertionError(f"ambiguous export {provider.module}.{name}: {sorted(resolved, key=lambda item: (item.module, item.name))!r}")
    if len(resolved) > 1:
        return None
    return next(iter(resolved), None)


def _resolve(
    node: ast.AST,
    facts: ModuleFacts,
    graph: dict[str, ModuleFacts],
    seen: frozenset[tuple[str, str, int, int, int, int]] = frozenset(),
    environment_override: Environment | None = None,
) -> Symbol | None:
    if isinstance(node, ast.Name):
        environment = environment_override
        if environment is None:
            environment = _before_environment(facts, node)
        definitions = environment.get(node.id, frozenset())
        resolutions = tuple(
            _resolve_definition(definition, facts, graph, seen)
            for definition in definitions
        )
        resolved = {symbol for symbol in resolutions if symbol is not None}
        target_symbol = Symbol(TARGET_MODULE, TARGET_NAME)
        if target_symbol in resolved and (len(resolved) > 1 or any(symbol is None for symbol in resolutions)):
            raise AssertionError(f"ambiguous reaching definitions for {facts.path}:{node.lineno}:{node.col_offset} {node.id}: {definitions!r}")
        if len(resolved) > 1:
            return None
        if resolved:
            return next(iter(resolved))
        star_resolutions: list[Symbol | None] = []
        for definition in environment.get("@star", frozenset()):
            provider_name = definition.symbol.module if definition.symbol is not None else ""
            provider = graph.get(provider_name)
            if provider is not None:
                symbol = _resolve_export(node.id, provider, graph, seen, star=True)
                star_resolutions.append(symbol)
        star_resolved = {symbol for symbol in star_resolutions if symbol is not None}
        if len(star_resolved) > 1 and Symbol(TARGET_MODULE, TARGET_NAME) in star_resolved:
            raise AssertionError(f"ambiguous star binding {facts.path}:{node.lineno} {node.id}: {star_resolved!r}")
        if Symbol(TARGET_MODULE, TARGET_NAME) in star_resolved and any(
            symbol is None for symbol in star_resolutions
        ):
            raise AssertionError(f"target star binding has unresolved sibling {facts.path}:{node.lineno} {node.id}")
        if len(star_resolved) > 1:
            return None
        if star_resolved:
            return next(iter(star_resolved))
        if not definitions and not environment.get("@star") and node.id in {"isinstance", "issubclass", "getattr", "hasattr"}:
            return Symbol("builtins", node.id)
        return None
    parts = _attribute_parts(node)
    if parts is None:
        return None
    root_node = node
    while isinstance(root_node, ast.Attribute):
        root_node = root_node.value
    root_symbol = _resolve(root_node, facts, graph, seen, environment_override)
    if root_symbol is None:
        return None
    module = root_symbol.module if root_symbol.name == "" else ".".join((root_symbol.module, root_symbol.name))
    if len(parts) == 1:
        return root_symbol
    projected = Symbol(".".join((module, *parts[1:-1])), parts[-1])
    projected_provider = graph.get(projected.module)
    if projected_provider is not None:
        exported = _resolve_export(projected.name, projected_provider, graph, seen, star=False)
        if exported is not None:
            projected = exported
    # Attribute assignments are keyed by the resolved base symbol and field,
    # never by unparsed receiver spelling.
    resolutions: list[Symbol | None] = []
    environment = _before_environment(facts, node)
    for definition in environment.get(f"@attribute:{parts[-1]}", frozenset()):
        target = definition.node
        if not isinstance(target, ast.Attribute):
            continue
        if _resolve(target.value, facts, graph, seen) == root_symbol:
            resolutions.append(_resolve_definition(definition, facts, graph, seen))
    candidates = {symbol for symbol in resolutions if symbol is not None}
    if len(candidates) > 1 and Symbol(TARGET_MODULE, TARGET_NAME) in candidates:
        raise AssertionError(f"ambiguous attribute provenance {facts.path}:{node.lineno}: {candidates!r}")
    if len(candidates) > 1:
        return None
    if Symbol(TARGET_MODULE, TARGET_NAME) in candidates and any(symbol is None for symbol in resolutions):
        raise AssertionError(f"target attribute provenance has unresolved sibling {facts.path}:{node.lineno}")
    return next(iter(candidates), projected)


def _is_target(node: ast.AST, facts: ModuleFacts, graph: dict[str, ModuleFacts]) -> bool:
    return _resolve(node, facts, graph) == Symbol(TARGET_MODULE, TARGET_NAME)


def _raw_rows(files: tuple[Path, ...]) -> tuple[RawRow, ...]:
    pattern = re.compile(r"\bFactoryBuildContext\b")
    rows: list[RawRow] = []
    for path in files:
        relative = _path_identity(path)
        source = path.read_text(encoding="utf-8")
        token_kinds: dict[tuple[int, int], str] = {}
        with path.open("rb") as stream:
            for token in tokenize.tokenize(stream.readline):
                token_lines = token.string.splitlines() or [token.string]
                for offset, token_line in enumerate(token_lines):
                    for match in pattern.finditer(token_line):
                        position = (
                            token.start[0] + offset,
                            match.start() + (token.start[1] if offset == 0 else 0),
                        )
                        if position in token_kinds:
                            raise AssertionError(f"overlapping tokenizer ownership at {relative}:{position}")
                        token_kinds[position] = tokenize.tok_name[token.type]
        for line_number, line in enumerate(source.splitlines(), 1):
            for match in pattern.finditer(line):
                column = match.start()
                token_kind = token_kinds.get((line_number, column))
                rows.append(RawRow(
                    relative,
                    Span(line_number, column, line_number, match.end()),
                    token_kind or "UNMAPPED",
                    line.strip(),
                ))
    return tuple(sorted(rows))


def _annotation_roots(tree: ast.Module) -> tuple[tuple[ast.AST, str], ...]:
    roots: list[tuple[ast.AST, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            roots.append((node.annotation, "annotation_leaf"))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            roots.append((node.returns, "annotation_leaf"))
        elif isinstance(node, ast.AnnAssign):
            roots.append((node.annotation, "annotation_leaf"))
            if isinstance(node.annotation, ast.Name) and node.annotation.id == "TypeAlias" and node.value is not None:
                roots.append((node.value, "type_alias_site"))
    return tuple(roots)


def _annotation_resolves(root: ast.AST, facts: ModuleFacts, graph: dict[str, ModuleFacts]) -> bool:
    expression = root
    containing_environment = _before_environment(facts, root)
    if isinstance(root, ast.Constant) and isinstance(root.value, str):
        try:
            expression = ast.parse(root.value, mode="eval").body
        except SyntaxError:
            return False
    return any(
        isinstance(child, (ast.Name, ast.Attribute))
        and _resolve(child, facts, graph, environment_override=containing_environment)
        == Symbol(TARGET_MODULE, TARGET_NAME)
        for child in ast.walk(expression)
    )


def _inside_type_checking(
    raw: RawRow, facts: ModuleFacts, graph: dict[str, ModuleFacts]
) -> bool:
    return any(
        isinstance(node, ast.If)
        and _contains(_node_span(node), raw.span)
        and _resolve(node.test, facts, graph) == Symbol("typing", "TYPE_CHECKING")
        for node in ast.walk(facts.tree)
        if _has_span(node)
    )


def _classification_candidates(raw: RawRow, facts: ModuleFacts, graph: dict[str, ModuleFacts]) -> tuple[SemanticRow, ...]:
    candidates: list[SemanticRow] = []
    containing = [node for node in ast.walk(facts.tree) if _has_span(node) and _contains(_node_span(node), raw.span)]
    for node in containing:
        if (
            isinstance(node, ast.ClassDef)
            and facts.module == TARGET_MODULE
            and node.name == TARGET_NAME
            and raw.token_kind == "NAME"
            and raw.span.line == node.lineno
        ):
            candidates.append(SemanticRow(raw, "definition", f"{facts.module}:{node.lineno}"))
    for node in containing:
        if isinstance(node, ast.ImportFrom):
            for imported in node.names:
                if imported.name == TARGET_NAME and _contains(_node_span(imported), raw.span):
                    symbol = Symbol(_relative_module(node.module or "", facts.package, node.level), imported.name)
                    provider = graph.get(symbol.module)
                    resolved = provider is not None and _resolve_export(
                        symbol.name, provider, graph, frozenset(), star=False
                    ) == Symbol(TARGET_MODULE, TARGET_NAME)
                    if resolved:
                        category = "type_checking_import" if _inside_type_checking(raw, facts, graph) else (
                            "runtime_reexport" if facts.path.name == "__init__.py" else "runtime_import"
                        )
                        candidates.append(SemanticRow(raw, category, f"{symbol.module}.{symbol.name}"))
    for root, category in _annotation_roots(facts.tree):
        if _contains(_node_span(root), raw.span) and _annotation_resolves(root, facts, graph):
            candidates.append(SemanticRow(raw, category, ast.dump(root, include_attributes=False)))
    for node in containing:
        if isinstance(node, ast.Call) and _contains(_node_span(node.func), raw.span) and _is_target(node.func, facts, graph):
            candidates.append(SemanticRow(raw, "constructor", ast.dump(node.func, include_attributes=False)))
    for node in containing:
        if (
            isinstance(node, ast.Constant)
            and node.value == TARGET_NAME
            and isinstance(facts.parents.get(node), (ast.List, ast.Tuple, ast.Set))
            and any(
                isinstance(parent, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "__all__" for target in parent.targets)
                for parent in ast.walk(facts.tree)
                if hasattr(parent, "lineno") and _contains(_node_span(parent), _node_span(node))
            )
        ):
            candidates.append(SemanticRow(raw, "export_literal", "resolved __all__ export"))
    # Non-code occurrences are explicit terminal semantic categories. There is
    # deliberately no generic prose fallback.
    if raw.token_kind == "COMMENT":
        candidates.append(SemanticRow(raw, "source_comment", "tokenize.COMMENT"))
    string_nodes = [node for node in containing if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    if string_nodes and not any(row.category in {"annotation_leaf", "type_alias_site", "export_literal"} for row in candidates):
        calls = [node for node in containing if isinstance(node, ast.Call)]
        if calls:
            call = min(calls, key=lambda node: (node.end_lineno - node.lineno, node.end_col_offset - node.col_offset))
            candidates.append(SemanticRow(raw, "diagnostic_literal", ast.dump(call.func, include_attributes=False)))
        else:
            candidates.append(SemanticRow(raw, "documentation_literal", "AST string literal"))
    return tuple(candidates)


def _semantic_rows(raw: tuple[RawRow, ...], facts: dict[str, ModuleFacts]) -> tuple[SemanticRow, ...]:
    by_path = {_path_identity(module.path): module for module in facts.values()}
    unmapped = tuple(row for row in raw if row.token_kind == "UNMAPPED")
    assert not unmapped, f"unmapped tokenizer spans: {unmapped!r}"
    candidate_rows = tuple(
        (row, _classification_candidates(row, by_path[row.path], facts))
        for row in raw
    )
    wrong_cardinality = tuple((row, candidates) for row, candidates in candidate_rows if len(candidates) != 1)
    assert not wrong_cardinality, f"exact semantic ownership cardinality != 1: {wrong_cardinality!r}"
    rows = tuple(candidates[0] for _, candidates in candidate_rows)
    assert len(rows) == len(raw)
    assert {row.raw for row in rows} == set(raw)
    assert len({row.raw for row in rows}) == len(rows)
    return rows


def _semantic_ontology_impacts(facts: dict[str, ModuleFacts]) -> tuple[OntologyImpact, ...]:
    """Discover ontology reachability from resolved testimony, never token spelling."""
    target = Symbol(TARGET_MODULE, TARGET_NAME)
    impacts: list[OntologyImpact] = []
    for module in facts.values():
        relative = _path_identity(module.path)
        annotation_roots = tuple(root for root, _ in _annotation_roots(module.tree))
        for node in ast.walk(module.tree):
            if isinstance(node, ast.ClassDef) and Symbol(module.module, node.name) == target:
                impacts.append(OntologyImpact(relative, _node_span(node), "definition", target))
            elif isinstance(node, (ast.Name, ast.Attribute)) and isinstance(
                getattr(node, "ctx", ast.Load()), ast.Load
            ) and not (
                isinstance(module.parents.get(node), ast.Call)
                and module.parents[node].func is node
            ) and not any(
                _contains(_node_span(root), _node_span(node)) for root in annotation_roots
            ) and _resolve(node, module, facts) == target:
                impacts.append(OntologyImpact(relative, _node_span(node), "resolved_use", target))
            elif isinstance(node, ast.Call) and _resolve(node.func, module, facts) == target:
                impacts.append(OntologyImpact(relative, _node_span(node.func), "constructor", target))
            elif isinstance(node, ast.ImportFrom):
                provider_name = _relative_module(node.module or "", module.package, node.level)
                provider = facts.get(provider_name)
                if provider is not None:
                    for alias in node.names:
                        if alias.name != "*" and _resolve_export(
                            alias.name, provider, facts, frozenset(), star=False
                        ) == target:
                            impacts.append(OntologyImpact(relative, _node_span(alias), "resolved_import", target))
        for root in annotation_roots:
            if _annotation_resolves(root, module, facts):
                impacts.append(OntologyImpact(relative, _node_span(root), "annotation_contract", target))
        exports = _declared_exports(module)
        if exports is not None:
            for name in exports:
                if _resolve_export(name, module, facts, frozenset(), star=False) == target:
                    for node in ast.walk(module.tree):
                        if isinstance(node, ast.Constant) and node.value == name and _has_span(node):
                            impacts.append(OntologyImpact(relative, _node_span(node), "resolved_reexport", target))
    duplicates = tuple(row for row in impacts if impacts.count(row) > 1)
    assert not duplicates, f"duplicate semantic ontology impacts: {duplicates!r}"
    return tuple(sorted(impacts))


@dataclass(frozen=True, order=True)
class MigrationRow:
    source: RawRow | OntologyImpact
    caller_path: str
    caller_span: Span
    caller_contract: str
    replacement_path: str
    replacement_span: Span
    action: str
    consumers: tuple[tuple[str, Span, str], ...]


@dataclass(frozen=True, order=True)
class MigrationManifestRow:
    path: str
    span: Span
    site_kind: str
    owner: str
    action: str
    caller: str


def _reduce_context_sites(production: dict[str, ModuleFacts]) -> dict[str, tuple[str, Span]]:
    facts = production["sugar_lift_py_tests.context.reduce_context"]
    path = _path_identity(facts.path)
    sites: dict[str, tuple[str, Span]] = {}
    for node in ast.walk(facts.tree):
        if isinstance(node, ast.ClassDef) and node.name == "ReduceContext":
            sites["type"] = (path, _node_span(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {"root", "derived"}:
            sites[node.name] = (path, _node_span(node))
    assert set(sites) == {"type", "root", "derived"}, sites
    return sites


Origin = tuple[str, tuple[str, tuple[tuple[str, str, int, int], ...], str, Span]]


def _definition_origins(
    definition: ReachingDefinition,
    facts: ModuleFacts,
    graph: dict[str, ModuleFacts],
    seen: frozenset[Origin] = frozenset(),
) -> frozenset[Origin]:
    origin = (facts.module, _node_occurrence(facts, definition.node))
    if origin in seen:
        raise AssertionError(f"migration provenance cycle: {origin!r}")
    origins = {origin}
    if definition.symbol is not None and definition.symbol.name:
        provider = graph.get(definition.symbol.module)
        if provider is not None:
            for upstream in _reaching_index(provider).module_exit.get(definition.symbol.name, frozenset()):
                origins.update(_definition_origins(upstream, provider, graph, seen | {origin}))
    if definition.expression is not None:
        origins.update(_expression_origins(definition.expression, facts, graph, seen | {origin}))
    return frozenset(origins)


def _expression_origins(
    expression: ast.AST,
    facts: ModuleFacts,
    graph: dict[str, ModuleFacts],
    seen: frozenset[Origin] = frozenset(),
    environment_override: Environment | None = None,
) -> frozenset[Origin]:
    origins: set[Origin] = set()
    for node in ast.walk(expression):
        if isinstance(node, ast.Attribute) and _resolve(
            node, facts, graph, environment_override=environment_override
        ) == Symbol(TARGET_MODULE, TARGET_NAME):
            root = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                environment = environment_override or _before_environment(facts, root)
                for definition in environment.get(root.id, frozenset()):
                    origins.update(_definition_origins(definition, facts, graph, seen))
            provider = graph.get(TARGET_MODULE)
            if provider is not None:
                for definition in _reaching_index(provider).module_exit.get(TARGET_NAME, frozenset()):
                    origins.update(_definition_origins(definition, provider, graph, seen))
            continue
        if not isinstance(node, ast.Name):
            continue
        environment = environment_override or _before_environment(facts, node)
        for definition in environment.get(node.id, frozenset()):
            origins.update(_definition_origins(definition, facts, graph, seen))
    return frozenset(origins)


def _resolved_use_edges(
    graph: dict[str, ModuleFacts],
) -> tuple[tuple[Origin, tuple[str, Span, str]], ...]:
    target = Symbol(TARGET_MODULE, TARGET_NAME)
    edges: list[tuple[Origin, tuple[str, Span, str]]] = []
    for facts in graph.values():
        path = _path_identity(facts.path)
        candidates: list[tuple[ast.AST, Environment | None, Span, str]] = [
            (node, None, _node_span(node), type(node).__name__) for node in ast.walk(facts.tree)
            if isinstance(node, (ast.Name, ast.Attribute)) and _has_span(node)
            and _resolve(node, facts, graph) == target
        ]
        for root, _ in _annotation_roots(facts.tree):
            if isinstance(root, ast.Constant) and isinstance(root.value, str) and _annotation_resolves(root, facts, graph):
                parsed = ast.parse(root.value, mode="eval").body
                candidates.extend(
                    (
                        node,
                        _before_environment(facts, root),
                        _node_span(root),
                        f"forward:{_node_span(node)!r}:{ast.dump(node, include_attributes=False)}",
                    )
                    for node in ast.walk(parsed) if isinstance(node, ast.Name)
                )
        for node, environment, use_span, use_kind in candidates:
            origins = _expression_origins(node, facts, graph, environment_override=environment)
            use = (path, use_span, use_kind)
            edges.extend((origin, use) for origin in origins)
    duplicates = tuple(edge for edge in edges if edges.count(edge) > 1)
    assert not duplicates, f"duplicate migration dataflow edges: {duplicates!r}"
    return tuple(sorted(edges))


def _migration_rows(
    semantic: tuple[SemanticRow, ...],
    production: dict[str, ModuleFacts],
    impacts: tuple[OntologyImpact, ...] = (),
) -> tuple[MigrationRow, ...]:
    sites = _reduce_context_sites(production)
    facts_by_path = {
        _path_identity(facts.path): facts for facts in production.values()
    }
    dataflow_edges = _resolved_use_edges(production)
    rows: list[MigrationRow] = []
    for row in semantic:
        facts = facts_by_path[row.raw.path]
        containing = [
            node for node in ast.walk(facts.tree)
            if _has_span(node) and _contains(_node_span(node), row.raw.span)
        ]
        semantic_owners: list[ast.AST] = []
        semantic_owners.extend(
            alias for node in containing if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names if _has_span(alias) and _contains(_node_span(alias), row.raw.span)
        )
        semantic_owners.extend(
            root for root, _ in _annotation_roots(facts.tree) if _contains(_node_span(root), row.raw.span)
        )
        semantic_owners.extend(
            node for node in containing
            if isinstance(node, ast.Call) and _contains(_node_span(node.func), row.raw.span)
            and _is_target(node.func, facts, production)
        )
        semantic_owners.extend(
            node for node in containing if isinstance(node, ast.ClassDef)
            and facts.module == TARGET_MODULE and node.name == TARGET_NAME
            and row.raw.span.line == node.lineno and row.raw.token_kind == "NAME"
        )
        if not semantic_owners and row.category in {
            "export_literal", "documentation_literal", "diagnostic_literal"
        }:
            semantic_owners.extend(
                node for node in containing if isinstance(node, ast.Constant) and isinstance(node.value, str)
            )
        if row.category == "source_comment":
            semantic_owner = None
        else:
            assert len(semantic_owners) == 1, (
                f"semantic migration owner cardinality != 1: {row!r} "
                f"{tuple((type(node).__name__, _node_span(node)) for node in semantic_owners)!r}"
            )
            semantic_owner = semantic_owners[0]
        caller: ast.AST = semantic_owner or facts.tree
        while caller in facts.parents and not isinstance(
            caller, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            caller = facts.parents[caller]
        caller_span = (
            _node_span(caller)
            if _has_span(caller)
            else Span(1, 0, len(facts.path.read_text(encoding="utf-8").splitlines()), 0)
        )
        annotation_owner = semantic_owner if any(
            semantic_owner is root for root, _ in _annotation_roots(facts.tree)
        ) else None
        constructor_owner = semantic_owner if isinstance(semantic_owner, ast.Call) else None
        if annotation_owner is not None:
            replacement_path, replacement_span = sites["type"]
            action = "replace exact caller annotation contract with typed ReduceContext"
        elif constructor_owner is not None:
            replacement_path, replacement_span = sites["derived"]
            action = "replace self reconstruction with authenticated ReduceContext.derived"
        else:
            replacement_path, replacement_span = row.raw.path, row.raw.span
            action = "delete ontology definition/export/documentation occurrence"
        consumers: list[tuple[str, Span, str]] = []
        if semantic_owner is not None:
            owner_origin = (facts.module, _node_occurrence(facts, semantic_owner))
            consumers.extend(use for origin, use in dataflow_edges if origin == owner_origin)
            if annotation_owner is not None:
                consumers.append((row.raw.path, _node_span(annotation_owner), "annotation contract"))
            if constructor_owner is not None:
                consumers.append((row.raw.path, _node_span(constructor_owner), "constructor call"))
        terminal = row.category in {
            "source_comment", "documentation_literal", "diagnostic_literal", "export_literal"
        }
        if not consumers and terminal:
            consumers.append((row.raw.path, row.raw.span, "terminal deletion site"))
        assert consumers, f"executable semantic site has no resolved migration consumer: {row!r}"
        assert len(consumers) == len(set(consumers)), f"duplicate migration consumer edges: {row.raw!r} {consumers!r}"
        rows.append(MigrationRow(
            row.raw,
            row.raw.path,
            caller_span,
            f"{type(caller).__name__}:{getattr(caller, 'name', facts.module)}:{_node_span(semantic_owner) if semantic_owner is not None else row.raw.span}",
            replacement_path,
            replacement_span,
            action,
            tuple(sorted(consumers)),
        ))
    assert len(rows) == len(semantic)
    alias_only = tuple(
        impact for impact in impacts
        if not any(
            row.raw.path == impact.path
            and (_contains(impact.span, row.raw.span) or _contains(row.raw.span, impact.span))
            for row in semantic
        )
    )
    for impact in alias_only:
        facts = facts_by_path[impact.path]
        containing = [
            node for node in ast.walk(facts.tree)
            if _has_span(node) and _node_span(node) == impact.span
        ]
        if impact.kind == "annotation_contract":
            owner_candidates = [
                root for root, _ in _annotation_roots(facts.tree) if _node_span(root) == impact.span
            ]
        elif impact.kind == "constructor":
            owner_candidates = [
                node.func for node in ast.walk(facts.tree) if isinstance(node, ast.Call)
                and _has_span(node.func) and _node_span(node.func) == impact.span
            ]
        else:
            owner_candidates = [
                node for node in containing
                if isinstance(node, (ast.Name, ast.Attribute, ast.alias, ast.Constant))
            ]
        assert len(owner_candidates) == 1, (
            f"alias-only migration owner cardinality != 1: {impact!r} {owner_candidates!r}"
        )
        owner = owner_candidates[0]
        origin = (facts.module, _node_occurrence(facts, owner))
        consumers = tuple(use for edge_origin, use in dataflow_edges if edge_origin == origin)
        resolved_owner = (
            isinstance(owner, (ast.Name, ast.Attribute))
            and _resolve(owner, facts, production) == Symbol(TARGET_MODULE, TARGET_NAME)
        )
        parent = facts.parents.get(owner)
        if not consumers and resolved_owner and parent is not None and _has_span(parent):
            consumers = ((
                impact.path,
                _node_span(parent),
                f"resolved {type(parent).__name__} consumer",
            ),)
        if not consumers and impact.kind == "resolved_reexport":
            consumers = ((impact.path, impact.span, "authenticated export deletion"),)
        assert consumers, f"alias-only impact has no transitive consumer: {impact!r}"
        rows.append(MigrationRow(
            impact,
            impact.path,
            impact.span,
            f"{type(owner).__name__}:{impact.kind}",
            impact.path,
            impact.span,
            "migrate alias-only resolved capability to ReduceContext",
            tuple(sorted(consumers)),
        ))
    assert len({row.source for row in rows}) == len(rows)
    return tuple(sorted(rows, key=lambda row: (
        row.caller_path, row.caller_span, type(row.source).__name__, repr(row.source)
    )))


def _migration_manifest(
    semantic: tuple[SemanticRow, ...],
    impacts: tuple[OntologyImpact, ...],
    graph: dict[str, ModuleFacts],
) -> tuple[MigrationManifestRow, ...]:
    facts_by_path = {_path_identity(facts.path): facts for facts in graph.values()}
    rows: list[MigrationManifestRow] = []
    for impact in impacts:
        facts = facts_by_path[impact.path]
        if impact.kind == "constructor":
            owners = [
                node for node in ast.walk(facts.tree) if isinstance(node, ast.Call)
                and _has_span(node.func) and _node_span(node.func) == impact.span
            ]
            action = "replace construction capability with ReduceContext.root/derived"
        elif impact.kind == "resolved_import":
            owners = [
                node for node in ast.walk(facts.tree) if isinstance(node, ast.alias)
                and _has_span(node) and _node_span(node) == impact.span
            ]
            action = "delete import after all resolved consumers migrate"
        elif impact.kind == "annotation_contract":
            owners = [root for root, _ in _annotation_roots(facts.tree) if _node_span(root) == impact.span]
            action = "replace exact annotation capability with ReduceContext"
        elif impact.kind == "resolved_reexport":
            owners = [
                node for node in ast.walk(facts.tree) if isinstance(node, ast.Constant)
                and _has_span(node) and _node_span(node) == impact.span
            ]
            action = "delete authenticated export edge"
        elif impact.kind == "definition":
            owners = [
                node for node in ast.walk(facts.tree) if isinstance(node, ast.ClassDef)
                and _node_span(node) == impact.span
            ]
            action = "delete unowned ontology definition"
        else:
            owners = [
                node for node in ast.walk(facts.tree) if isinstance(node, (ast.Name, ast.Attribute))
                and _has_span(node) and _node_span(node) == impact.span
                and _resolve(node, facts, graph) == impact.authority
            ]
            action = "migrate resolved capability use to ReduceContext"
        assert len(owners) == 1, f"migration manifest owner cardinality != 1: {impact!r} {owners!r}"
        owner = owners[0]
        caller = owner
        while caller in facts.parents and not isinstance(caller, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            caller = facts.parents[caller]
        rows.append(MigrationManifestRow(
            impact.path,
            impact.span,
            impact.kind,
            f"{type(owner).__name__}:{_node_span(owner)}",
            action,
            f"{type(caller).__name__}:{getattr(caller, 'name', facts.module)}",
        ))
    for row in semantic:
        if row.category not in {"source_comment", "documentation_literal", "diagnostic_literal"}:
            continue
        rows.append(MigrationManifestRow(
            row.raw.path, row.raw.span, row.category, row.authority,
            "delete explicitly terminal prose testimony", f"token:{row.raw.token_kind}",
        ))
    ontology = graph[TARGET_MODULE]
    ontology_path = _path_identity(ontology.path)
    line_count = len(ontology.path.read_text(encoding="utf-8").splitlines())
    rows.append(MigrationManifestRow(
        ontology_path, Span(1, 0, line_count, 0), "ontology_file", ontology.module,
        "delete file after every semantic edge migrates", "module owner",
    ))
    assert len(rows) == len(set(rows)), "migration manifest contains duplicate site-owner-action rows"
    return tuple(sorted(rows))


def _bounded_runtime_discriminators(facts: dict[str, ModuleFacts]) -> tuple[tuple[str, Span, str], ...]:
    """Resolve the bounded admission grammar: semantic builtin calls,
    identity/equality comparisons, and match subject/class/pattern/guards.

    This deliberately does not claim arbitrary user-defined callable-object
    equivalence; the axis name and vector preserve that honest ceiling.
    """
    rows: list[tuple[str, Span, str]] = []
    discriminator_symbols = {
        Symbol("builtins", "isinstance"), Symbol("builtins", "issubclass"),
        Symbol("builtins", "getattr"), Symbol("builtins", "hasattr"),
    }

    def string_values(node: ast.AST, module: ModuleFacts) -> frozenset[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return frozenset((node.value,))
        if isinstance(node, ast.Name):
            environment = _before_environment(module, node)
            values = set()
            for definition in environment.get(node.id, frozenset()):
                if definition.expression is not None:
                    values.update(string_values(definition.expression, module))
            return frozenset(values)
        return frozenset()

    for module in facts.values():
        relative = _path_identity(module.path)
        for node in ast.walk(module.tree):
            candidates: tuple[ast.AST, ...] = ()
            if isinstance(node, ast.Call) and _resolve(node.func, module, facts) in discriminator_symbols:
                callee = _resolve(node.func, module, facts)
                if callee in {Symbol("builtins", "getattr"), Symbol("builtins", "hasattr")}:
                    if len(node.args) >= 2 and string_values(node.args[1], module):
                        candidates = (node.args[0],)
                else:
                    candidates = tuple(node.args[1:])
            elif isinstance(node, ast.Compare) and any(isinstance(op, (ast.Is, ast.IsNot, ast.Eq, ast.NotEq)) for op in node.ops):
                candidates = (node.left, *node.comparators)
            elif isinstance(node, ast.Match):
                candidates = (node.subject,)
            elif isinstance(node, ast.MatchClass):
                candidates = (node.cls,)
            elif isinstance(node, ast.match_case):
                candidates = tuple(candidate for candidate in (node.pattern, node.guard) if candidate is not None)
            if candidates and any(
                isinstance(ref, (ast.Name, ast.Attribute)) and _is_target(ref, module, facts)
                for candidate in candidates for ref in ast.walk(candidate)
            ):
                anchor = node if hasattr(node, "lineno") else candidates[0]
                rows.append((relative, _node_span(anchor), ast.dump(node, include_attributes=False)))
    return tuple(sorted(rows))


def _constructor_rows(facts: dict[str, ModuleFacts]) -> tuple[tuple[str, Span], ...]:
    return tuple(sorted(
        (_path_identity(module.path), _node_span(node.func))
        for module in facts.values()
        for node in ast.walk(module.tree)
        if isinstance(node, ast.Call) and _is_target(node.func, module, facts)
    ))


def _report():
    # Reaching definitions retain authenticated AST testimony. A new report
    # reparses the universe, so no node-bearing value crosses that boundary;
    # stable occurrence keys govern reuse only within this report.
    _REACHING_CACHE.clear()
    production_files = _production_files()
    production = {_production_module(path): _facts(path, module=_production_module(path)) for path in production_files}
    raw = _raw_rows(production_files)
    semantic = _semantic_rows(raw, production)
    test_facts = {_test_module(path): _facts(path, module=_test_module(path)) for path in _test_files()}
    # Tests resolve against production providers without sharing module identity.
    test_graph = {**production, **test_facts}
    impacts = _semantic_ontology_impacts(test_graph)
    return production_files, raw, semantic, impacts, production, test_facts, _constructor_rows(test_graph), _bounded_runtime_discriminators(production)


def _universe_identity() -> str:
    digest = hashlib.sha256()
    for path in (*_production_files(), *_test_files()):
        digest.update(_path_identity(path).encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


@dataclass(frozen=True)
class ReportSnapshot:
    source_sha256: str
    universe_sha256: str
    report: tuple


@pytest.fixture(scope="module")
def ontology_snapshot() -> ReportSnapshot:
    source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    universe_sha256 = _universe_identity()
    ontology_path = REPO / _PACKAGE_MARKER.parent / "factory_build_context.py"
    print(
        "ONTOLOGY_PRE_REPORT",
        f"source_sha256={source_sha256}",
        f"universe_sha256={universe_sha256}",
        f"ontology_file_exists={ontology_path.exists()}",
        f"repo={REPO}",
    )
    report = _report()
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == source_sha256
    assert _universe_identity() == universe_sha256
    return ReportSnapshot(source_sha256, universe_sha256, report)


def test_independent_exact_span_audits_reconcile_every_live_row(ontology_snapshot):
    print(
        "ONTOLOGY_IDENTITY",
        f"executable={sys.executable}",
        f"version={sys.version}",
        f"source_sha256={ontology_snapshot.source_sha256}",
        f"universe_sha256={ontology_snapshot.universe_sha256}",
    )
    _, raw, semantic, impacts, production, test_facts, constructors, discriminators = ontology_snapshot.report
    discovered_by_file = {path: sum(row.path == path for row in raw) for path in {row.path for row in raw}}
    annotations = tuple(row for row in semantic if row.category in {"annotation_leaf", "type_alias_site"})
    categories = {category: sum(row.category == category for row in semantic) for category in {row.category for row in semantic}}
    if not raw:
        assert semantic == ()
        assert impacts == ()
        assert constructors == ()
        assert discriminators == ()
        assert TARGET_MODULE not in production
        assert len(production) > len(EXPECTED_RAW_BY_FILE)
        return
    migrations = _migration_rows(semantic, {**production, **test_facts}, impacts)
    manifest = _migration_manifest(semantic, impacts, {**production, **test_facts})
    executable_semantic = tuple(
        row for row in semantic
        if row.category not in {"source_comment", "documentation_literal", "diagnostic_literal"}
    )
    missing_semantic_impacts = tuple(
        row for row in executable_semantic
        if not any(
            impact.path == row.raw.path
            and (_contains(impact.span, row.raw.span) or _contains(row.raw.span, impact.span))
            for impact in impacts
        )
    )
    assert not missing_semantic_impacts, missing_semantic_impacts
    assert all(impact.authority == Symbol(TARGET_MODULE, TARGET_NAME) for impact in impacts)
    assert any(
        not any(
            row.raw.path == impact.path
            and (_contains(impact.span, row.raw.span) or _contains(row.raw.span, impact.span))
            for row in semantic
        )
        for impact in impacts
    ), "semantic door must independently retain alias-only impact rows"
    manifest_sites = {(row.path, row.span) for row in manifest if row.site_kind != "ontology_file"}
    assert len(manifest_sites) == len(tuple(row for row in manifest if row.site_kind != "ontology_file"))
    assert sum(row.site_kind == "constructor" for row in manifest) == 9
    assert sum(row.site_kind == "ontology_file" for row in manifest) == 1
    assert all(
        any(
            manifest_row.path == row.raw.path
            and (_contains(manifest_row.span, row.raw.span) or _contains(row.raw.span, manifest_row.span))
            for manifest_row in manifest
        )
        for row in semantic
    )

    assert discovered_by_file == EXPECTED_RAW_BY_FILE
    assert len(raw) == 116 and len(discovered_by_file) == 14
    assert len(annotations) == 99 and len({row.raw.path for row in annotations}) == 8
    assert categories["annotation_leaf"] == 98
    assert categories["type_alias_site"] == 1
    assert categories["definition"] == 1
    assert categories["constructor"] == 1
    assert categories["runtime_import"] == 1
    assert categories["runtime_reexport"] == 1
    assert categories["export_literal"] == 1
    assert categories["type_checking_import"] == 6
    assert categories["source_comment"] == 3
    assert categories["documentation_literal"] == 2
    assert categories["diagnostic_literal"] == 1
    assert {row.source for row in migrations if isinstance(row.source, RawRow)} == set(raw)
    assert {
        row.source for row in migrations if isinstance(row.source, OntologyImpact)
    } == {
        impact for impact in impacts
        if not any(
            row.raw.path == impact.path
            and (_contains(impact.span, row.raw.span) or _contains(row.raw.span, impact.span))
            for row in semantic
        )
    }
    assert len(constructors) == 9  # one production self-reconstruction + eight tests
    assert sum(path in {_path_identity(facts.path) for facts in test_facts.values()} for path, _ in constructors) == 8
    assert discriminators == ()
    assert len(production) > len(EXPECTED_RAW_BY_FILE)  # repository-wide discovery denominator is non-empty and independent


def test_reaching_definition_authority_truthful_and_lying_twins(tmp_path):
    target_path = tmp_path / "factory_build_context.py"
    target_path.write_text(
        "class FactoryBuildContext:\n    pass\n"
        "before = FactoryBuildContext\n"
        "del FactoryBuildContext\n"
        "after = FactoryBuildContext\n"
        "FactoryBuildContext = before\n",
        encoding="utf-8",
    )
    consumer_path = tmp_path / "consumer.py"
    consumer_path.write_text(
        "from builtins import getattr as projected\n"
        "from typing import TYPE_CHECKING as CHECKING\n"
        f"from {TARGET_MODULE} import FactoryBuildContext as Alias\n"
        "field = 'token'\n"
        "truth = projected(Alias, field)\n"
        "lie = projected(object, field)\n"
        "if CHECKING:\n"
        f"    from {TARGET_MODULE} import FactoryBuildContext as TypedAlias\n"
        "if True:\n"
        f"    from {TARGET_MODULE} import FactoryBuildContext as RuntimeAlias\n",
        encoding="utf-8",
    )
    target = _facts(target_path, module=TARGET_MODULE)
    consumer = _facts(consumer_path, module="fixture.consumer")
    graph = {TARGET_MODULE: target, consumer.module: consumer}

    assignments = {
        node.targets[0].id: node.value
        for node in target.tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    }
    assert _resolve(assignments["before"], target, graph) == Symbol(TARGET_MODULE, TARGET_NAME)
    assert _resolve(assignments["after"], target, graph) is None

    discriminators = _bounded_runtime_discriminators(graph)
    assert len(discriminators) == 1
    assert discriminators[0][1].line == 5

    raw = _raw_rows((consumer_path,))
    semantic = _semantic_rows(raw, graph)
    import_categories = {
        row.raw.span.line: row.category
        for row in semantic
        if row.category in {"runtime_import", "type_checking_import"}
    }
    assert import_categories[8] == "type_checking_import"
    assert import_categories[10] == "runtime_import"


def test_immutable_artifact_discovers_authenticated_repo_without_caller_root(tmp_path):
    artifact = tmp_path / "immutable_ontology_instrument.py"
    artifact.write_bytes(Path(__file__).read_bytes())
    spec = importlib.util.spec_from_file_location("immutable_ontology_instrument", artifact)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        assert module.REPO == REPO
        assert module._production_files() == _production_files()
    finally:
        del sys.modules[spec.name]


def test_alias_only_impact_without_resolved_origin_edge_is_loud(tmp_path):
    reduce_path = tmp_path / "reduce_context.py"
    reduce_path.write_text(
        "class ReduceContext:\n"
        "    @classmethod\n"
        "    def root(cls): pass\n"
        "    @classmethod\n"
        "    def derived(cls): pass\n",
        encoding="utf-8",
    )
    orphan_path = tmp_path / "orphan.py"
    orphan_path.write_text("orphan = Hidden\n", encoding="utf-8")
    reduce_facts = _facts(
        reduce_path, module="sugar_lift_py_tests.context.reduce_context"
    )
    orphan_facts = _facts(orphan_path, module="fixture.orphan")
    hidden = next(
        node for node in ast.walk(orphan_facts.tree)
        if isinstance(node, ast.Name) and node.id == "Hidden"
    )
    impact = OntologyImpact(
        _path_identity(orphan_path),
        _node_span(hidden),
        "resolved_use",
        Symbol(TARGET_MODULE, TARGET_NAME),
    )

    with pytest.raises(AssertionError, match="has no transitive consumer"):
        _migration_rows(
            (),
            {
                reduce_facts.module: reduce_facts,
                orphan_facts.module: orphan_facts,
            },
            (impact,),
        )


def test_scope_control_flow_and_spelling_free_discovery_twins(tmp_path):
    target_path = tmp_path / "factory_build_context.py"
    target_path.write_text("class FactoryBuildContext:\n    pass\n", encoding="utf-8")
    scope_path = tmp_path / "scope_fixture.py"
    scope_path.write_text(
        f"from {TARGET_MODULE} import FactoryBuildContext as Authority\n"
        "def nested_scope():\n"
        "    before = Authority\n"
        "    def inner():\n"
        "        Authority = object\n"
        "    after = Authority\n"
        "def predeclared(seq, parameter, *, keyword):\n"
        "    before_tuple = tuple_bound\n"
        "    before_import = imported\n"
        "    before_with = entered\n"
        "    before_match = captured\n"
        "    (tuple_bound, *tail) = seq\n"
        f"    from {TARGET_MODULE} import FactoryBuildContext as imported\n"
        "    with parameter as entered:\n"
        "        pass\n"
        "    match seq:\n"
        "        case [captured, *_]:\n"
        "            pass\n"
        "def owners():\n"
        "    global global_slot\n"
        "    global_slot = Authority\n"
        "    global_use = global_slot\n"
        "    nonlocal_slot = Authority\n"
        "    def inner_owner():\n"
        "        nonlocal nonlocal_slot\n"
        "        nonlocal_slot = Authority\n"
        "        nonlocal_use = nonlocal_slot\n"
        "def flow(flag, seq):\n"
        "    value = Authority\n"
        "    if flag:\n"
        "        value = object\n"
        "        return\n"
        "    after_return = value\n"
        "    [exported := Authority for _ in seq]\n"
        "    after_walrus = exported\n"
        "def condition_truth():\n"
        "    probe = Authority\n"
        "    while (condition_truth_bound := probe):\n"
        "        break\n"
        "    condition_truth_after = condition_truth_bound\n"
        "def condition_lie(flag):\n"
        "    probe = Authority\n"
        "    while (condition_lie_bound := probe):\n"
        "        probe = object\n"
        "        if flag:\n"
        "            continue\n"
        "        break\n"
        "    condition_lie_after = condition_lie_bound\n",
        encoding="utf-8",
    )
    target = _facts(target_path, module=TARGET_MODULE)
    scope = _facts(scope_path, module="fixture.scope")
    graph = {target.module: target, scope.module: scope}
    assignments = {
        node.targets[0].id: node.value
        for node in ast.walk(scope.tree)
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    }
    target_symbol = Symbol(TARGET_MODULE, TARGET_NAME)
    assert _resolve(assignments["before"], scope, graph) == target_symbol
    assert _resolve(assignments["after"], scope, graph) == target_symbol
    for name in ("before_tuple", "before_import", "before_with", "before_match"):
        assert _resolve(assignments[name], scope, graph) is None
    assert _resolve(assignments["after_return"], scope, graph) == target_symbol
    assert _resolve(assignments["after_walrus"], scope, graph) == target_symbol
    assert _resolve(assignments["condition_truth_after"], scope, graph) == target_symbol
    with __import__("pytest").raises(AssertionError, match="ambiguous reaching definitions"):
        _resolve(assignments["condition_lie_after"], scope, graph)
    index = _reaching_index(scope)
    assert next(iter(index.before[_node_occurrence(scope, assignments["global_use"])].get("global_slot", ()))).scope_owner == "module"
    assert next(iter(index.before[_node_occurrence(scope, assignments["nonlocal_use"])].get("nonlocal_slot", ()))).scope_owner == "nonlocal"

    bridge_path = tmp_path / "bridge.py"
    bridge_path.write_text(
        f"from {TARGET_MODULE} import FactoryBuildContext as Hidden\n__all__ = ['Hidden']\n",
        encoding="utf-8",
    )
    consumer_path = tmp_path / "consumer_without_target_spelling.py"
    consumer_path.write_text("from fixture.bridge import *\nconstructed = Hidden()\n", encoding="utf-8")
    bridge = _facts(bridge_path, module="fixture.bridge")
    consumer = _facts(consumer_path, module="fixture.consumer_without_spelling")
    expanded_graph = {**graph, bridge.module: bridge, consumer.module: consumer}
    assert _constructor_rows(expanded_graph) == (("__fixture__/consumer_without_target_spelling.py", Span(2, 14, 2, 20)),)


def test_control_transfer_shadow_ambiguity_and_multiplicity_twins(tmp_path):
    target_path = tmp_path / "factory_build_context.py"
    target_path.write_text("class FactoryBuildContext:\n    pass\n", encoding="utf-8")
    flow_path = tmp_path / "flow_twins.py"
    flow_path.write_text(
        f"from {TARGET_MODULE} import FactoryBuildContext as Authority\n"
        "from builtins import getattr as projected\n"
        "truth_discriminator = projected(Authority, 'field')\n"
        "def shadowed(projected):\n"
        "    lie_discriminator = projected(Authority, 'field')\n"
        "truth_lambda = lambda: Authority\n"
        "lie_lambda = lambda Authority: Authority\n"
        "def raised_truth():\n"
        "    value = object\n"
        "    try:\n"
        "        value = Authority\n"
        "        raise RuntimeError()\n"
        "    except RuntimeError:\n"
        "        caught_truth = value\n"
        "    finally:\n"
        "        final_truth = value\n"
        "def raised_lie():\n"
        "    value = Authority\n"
        "    try:\n"
        "        value = object\n"
        "        raise ExceptionGroup('x', [RuntimeError()])\n"
        "    except* RuntimeError:\n"
        "        caught_lie = value\n"
        "    finally:\n"
        "        value = Authority\n"
        "        final_override = value\n"
        "def loop_faces(flag):\n"
        "    recurrent = Authority\n"
        "    while recurrent:\n"
        "        recurrent = object\n"
        "        if flag:\n"
        "            continue\n"
        "        break\n"
        "    after_loop = recurrent\n",
        encoding="utf-8",
    )
    target = _facts(target_path, module=TARGET_MODULE)
    flow = _facts(flow_path, module="fixture.flow_twins")
    graph = {target.module: target, flow.module: flow}
    assignments = {
        node.targets[0].id: node.value
        for node in ast.walk(flow.tree)
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    }
    target_symbol = Symbol(TARGET_MODULE, TARGET_NAME)
    assert _resolve(assignments["caught_truth"], flow, graph) == target_symbol
    assert _resolve(assignments["final_truth"], flow, graph) == target_symbol
    assert _resolve(assignments["caught_lie"], flow, graph) is None
    assert _resolve(assignments["final_override"], flow, graph) == target_symbol
    with __import__("pytest").raises(AssertionError, match="ambiguous reaching definitions"):
        _resolve(assignments["after_loop"], flow, graph)
    lambdas = [node for node in ast.walk(flow.tree) if isinstance(node, ast.Lambda)]
    assert _resolve(lambdas[0].body, flow, graph) == target_symbol
    assert _resolve(lambdas[1].body, flow, graph) is None
    assert len(_bounded_runtime_discriminators(graph)) == 1

    holder_path = tmp_path / "holder.py"
    holder_path.write_text("slot = object\n", encoding="utf-8")
    attribute_path = tmp_path / "attribute_ambiguity.py"
    attribute_path.write_text(
        f"from {TARGET_MODULE} import FactoryBuildContext as Authority\n"
        "import fixture.holder as holder\n"
        "holder.slot = Authority\n"
        "if flag:\n"
        "    holder.slot = object\n"
        "use = holder.slot\n",
        encoding="utf-8",
    )
    holder = _facts(holder_path, module="fixture.holder")
    attribute = _facts(attribute_path, module="fixture.attribute_ambiguity")
    attribute_graph = {target.module: target, holder.module: holder, attribute.module: attribute}
    use = next(
        node.value for node in attribute.tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "use"
    )
    with __import__("pytest").raises(AssertionError, match="attribute provenance"):
        _resolve(use, attribute, attribute_graph)

    bridge_path = tmp_path / "truth_bridge.py"
    bridge_path.write_text(
        f"from {TARGET_MODULE} import FactoryBuildContext as Hidden\n__all__ = ['Hidden']\n",
        encoding="utf-8",
    )
    lie_path = tmp_path / "lie_bridge.py"
    lie_path.write_text("Hidden = object\n__all__ = ['Hidden']\n", encoding="utf-8")
    star_path = tmp_path / "star_ambiguity.py"
    star_path.write_text(
        "from fixture.truth_bridge import *\nfrom fixture.lie_bridge import *\nuse = Hidden\n",
        encoding="utf-8",
    )
    bridge = _facts(bridge_path, module="fixture.truth_bridge")
    lie = _facts(lie_path, module="fixture.lie_bridge")
    star = _facts(star_path, module="fixture.star_ambiguity")
    star_graph = {target.module: target, bridge.module: bridge, lie.module: lie, star.module: star}
    star_use = next(node.value for node in star.tree.body if isinstance(node, ast.Assign))
    with __import__("pytest").raises(AssertionError, match="star binding"):
        _resolve(star_use, star, star_graph)

    prose_path = tmp_path / "prose_collision.py"
    prose_path.write_text('"FactoryBuildContext FactoryBuildContext"\n', encoding="utf-8")
    prose = _facts(prose_path, module="fixture.prose_collision")
    raw = _raw_rows((prose_path,))
    assert len(raw) == 2 and len({row.span for row in raw}) == 2
    semantic = _semantic_rows(raw, {prose.module: prose})
    assert [row.category for row in semantic] == ["documentation_literal", "documentation_literal"]


def test_measured_retirement_postcondition_has_no_surviving_ontology(ontology_snapshot):
    assert ontology_snapshot.source_sha256 == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    assert ontology_snapshot.universe_sha256 == _universe_identity()
    files, raw, semantic, _, _, test_facts, constructors, discriminators = ontology_snapshot.report
    exports = tuple(row for row in semantic if row.category in {"runtime_reexport", "export_literal"})
    ontology_files = tuple(path for path in files if path.name == "factory_build_context.py")
    test_paths = {_path_identity(facts.path) for facts in test_facts.values()}
    test_constructors = tuple(row for row in constructors if row[0] in test_paths)
    production_constructors = tuple(row for row in constructors if row[0] not in test_paths)

    vector = {
        "R_symbol": (len(raw), raw),
        "R_exports": (len(exports), exports),
        "R_files": (len(ontology_files), ontology_files),
        "R_constructors": (len(production_constructors), production_constructors),
        "R_bounded_runtime_discriminators": (len(discriminators), discriminators),
        "R_test_constructors": (len(test_constructors), test_constructors),
    }
    offenders = {axis: rows for axis, (count, rows) in vector.items() if count}
    assert not offenders, f"retirement_vector={{{', '.join(f'{axis}: {len(rows)}' for axis, rows in offenders.items())}}} rows={offenders!r}"

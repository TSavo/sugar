"""Finite inter-file structural detectors for With Authority v2 step 1.

This is test instrumentation.  It interprets AST structure and canonical import
edges; candidate identifier spellings never decide either law.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True, order=True)
class Site:
    path: str
    line: int
    col: int


@dataclass(frozen=True, order=True)
class ReportRow:
    law: str
    sink_site: Site
    origin_site: Site
    canonical: str
    reason: str
    chain: tuple[str, ...]


@dataclass(frozen=True)
class Atom:
    kind: str
    identity: str = ""
    origin: Site | None = None
    chain: tuple[str, ...] = field(default=(), compare=False, hash=False)
    rpc: bool = False

    def step(self, text: str, *, rpc: bool = False) -> "Atom":
        return Atom(
            self.kind, self.identity, self.origin, self.chain + (text,), self.rpc or rpc
        )


@dataclass(frozen=True)
class AbstractValue:
    atoms: frozenset[Atom] = frozenset()
    entries: tuple[tuple[str | None, "AbstractValue"], ...] = ()

    def join(self, other: "AbstractValue") -> "AbstractValue":
        entries = self.entries + tuple(
            entry for entry in other.entries if entry not in self.entries
        )
        return AbstractValue(self.atoms | other.atoms, entries)

    def stepped(self, text: str, *, rpc: bool = False) -> "AbstractValue":
        return AbstractValue(
            frozenset(a.step(text, rpc=rpc) for a in self.atoms),
            tuple((key, value.stepped(text, rpc=rpc)) for key, value in self.entries),
        )

    def with_atom(self, atom: Atom) -> "AbstractValue":
        return AbstractValue(self.atoms | {atom}, self.entries)

    def has(self, kind: str) -> bool:
        return any(a.kind == kind for a in self.atoms)


@dataclass(frozen=True)
class FlowResult:
    returns: AbstractValue = AbstractValue()
    exits: tuple[dict[str, AbstractValue], ...] = ()
    raises: tuple[dict[str, AbstractValue], ...] = ()
    prefixes: tuple[dict[str, AbstractValue], ...] = ()
    breaks: tuple[dict[str, AbstractValue], ...] = ()
    continues: tuple[dict[str, AbstractValue], ...] = ()


CFG_STATEMENT_TYPES = frozenset(
    {
        ast.AnnAssign,
        ast.Assert,
        ast.Assign,
        ast.AsyncFor,
        ast.AsyncFunctionDef,
        ast.AsyncWith,
        ast.AugAssign,
        ast.Break,
        ast.ClassDef,
        ast.Continue,
        ast.Delete,
        ast.Expr,
        ast.For,
        ast.FunctionDef,
        ast.Global,
        ast.If,
        ast.Import,
        ast.ImportFrom,
        ast.Match,
        ast.Nonlocal,
        ast.Pass,
        ast.Raise,
        ast.Return,
        ast.Try,
        ast.TryStar,
        ast.TypeAlias,
        ast.While,
        ast.With,
    }
)


ORDINARY = AbstractValue(frozenset({Atom("Ordinary")}))


@dataclass(frozen=True)
class ModuleUnit:
    name: str
    path: Path
    tree: ast.Module


@dataclass
class ModuleGraph:
    modules: dict[str, ModuleUnit]

    @classmethod
    def from_paths(cls, paths: Iterable[Path]) -> "ModuleGraph":
        modules = {}
        for path in sorted((Path(p) for p in paths), key=lambda p: str(p)):
            name = path.stem if path.name != "__init__.py" else path.parent.name
            modules[name] = ModuleUnit(
                name,
                path,
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path)),
            )
        return cls(modules)

    @classmethod
    def from_roots(cls, roots: Iterable[Path]) -> "ModuleGraph":
        paths = []
        for root in roots:
            paths.extend(sorted(Path(root).rglob("*.py")))
        graph = cls.from_paths(paths)
        # Preserve package-qualified identities for production roots.
        rebuilt = {}
        for root in roots:
            root = Path(root)
            package = root.name
            for path in sorted(root.rglob("*.py")):
                rel = path.relative_to(root)
                parts = list(rel.with_suffix("").parts)
                if parts[-1] == "__init__":
                    parts.pop()
                name = ".".join([package, *parts]) if parts else package
                rebuilt[name] = ModuleUnit(
                    name,
                    path,
                    ast.parse(path.read_text(encoding="utf-8"), filename=str(path)),
                )
        graph.modules = rebuilt
        return graph


@dataclass(frozen=True)
class ClassDef:
    identity: str
    module: str
    node: ast.ClassDef
    site: Site
    bases: tuple[str, ...]


@dataclass(frozen=True)
class FunctionDef:
    identity: str
    module: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    site: Site
    owner: str | None


@dataclass
class Index:
    graph: ModuleGraph
    classes: dict[str, ClassDef] = field(default_factory=dict)
    functions: dict[str, FunctionDef] = field(default_factory=dict)
    module_symbols: dict[str, dict[str, str]] = field(default_factory=dict)
    module_values: dict[str, dict[str, AbstractValue]] = field(default_factory=dict)
    class_bases: dict[str, set[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._definitions()
        self._imports()
        self._base_closure()

    def site(self, module: str, node: ast.AST) -> Site:
        return Site(
            str(self.graph.modules[module].path),
            getattr(node, "lineno", 1),
            getattr(node, "col_offset", 0),
        )

    def _definitions(self) -> None:
        for module, unit in sorted(self.graph.modules.items()):
            symbols: dict[str, str] = {}
            for node in unit.tree.body:
                if isinstance(node, ast.ClassDef):
                    identity = f"{module}.{node.name}"
                    bases = tuple(ast.unparse(base) for base in node.bases)
                    self.classes[identity] = ClassDef(
                        identity, module, node, self.site(module, node), bases
                    )
                    symbols[node.name] = identity
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            fid = f"{identity}.{child.name}"
                            self.functions[fid] = FunctionDef(
                                fid, module, child, self.site(module, child), identity
                            )
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fid = f"{module}.{node.name}"
                    self.functions[fid] = FunctionDef(
                        fid, module, node, self.site(module, node), None
                    )
                    symbols[node.name] = fid
            self.module_symbols[module] = symbols
            self.module_values[module] = {}

    def _resolve_module(
        self, current: str, imported: str | None, level: int
    ) -> str | None:
        imported = imported or ""
        if level:
            base = current.split(".")[:-level]
            candidate = ".".join([*base, *([imported] if imported else [])])
        else:
            candidate = imported
        if candidate in self.graph.modules:
            return candidate
        tail = candidate.split(".")[-1]
        matches = [
            name
            for name in self.graph.modules
            if name == tail or name.endswith(f".{tail}")
        ]
        return sorted(matches)[0] if len(matches) == 1 else None

    def _imports(self) -> None:
        for module, unit in sorted(self.graph.modules.items()):
            symbols = self.module_symbols[module]
            for node in unit.tree.body:
                if isinstance(node, ast.ImportFrom):
                    target_module = self._resolve_module(
                        module, node.module, node.level
                    )
                    if target_module is None:
                        continue
                    for alias in node.names:
                        canonical = self.module_symbols[target_module].get(alias.name)
                        if canonical:
                            symbols[alias.asname or alias.name] = canonical
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        target_module = self._resolve_module(module, alias.name, 0)
                        if target_module:
                            symbols[alias.asname or alias.name.split(".")[0]] = (
                                f"module:{target_module}"
                            )

    def resolve(
        self,
        module: str,
        expr: ast.expr,
        env: Mapping[str, AbstractValue] | None = None,
    ) -> str | None:
        if isinstance(expr, ast.Name):
            return self.module_symbols.get(module, {}).get(expr.id)
        if isinstance(expr, ast.Attribute):
            base = self.resolve(module, expr.value, env)
            if base and base.startswith("module:"):
                return self.module_symbols.get(base[7:], {}).get(expr.attr)
            if base and base in self.classes:
                candidate = f"{base}.{expr.attr}"
                if candidate in self.functions:
                    return candidate
        return None

    def _base_closure(self) -> None:
        for identity, cls in self.classes.items():
            direct = set()
            for text in cls.bases:
                try:
                    expr = ast.parse(text, mode="eval").body
                except SyntaxError:
                    continue
                resolved = self.resolve(cls.module, expr)
                if resolved in self.classes:
                    direct.add(resolved)
            self.class_bases[identity] = direct
        changed = True
        while changed:
            changed = False
            for identity in sorted(self.class_bases):
                expanded = set(self.class_bases[identity])
                for base in tuple(expanded):
                    expanded |= self.class_bases.get(base, set())
                if expanded != self.class_bases[identity]:
                    self.class_bases[identity] = expanded
                    changed = True

    def is_sugar(self, class_id: str) -> bool:
        ids = {class_id, *self.class_bases.get(class_id, set())}
        return any(identity.rsplit(".", 1)[-1] == "Sugar" for identity in ids)


class Interpreter:
    def __init__(self, graph: ModuleGraph):
        self.index = Index(graph)
        self.summaries: dict[
            tuple[str, tuple[tuple[Atom, ...], ...]], AbstractValue
        ] = {}
        self.summary_revision = 0
        self.active: set[tuple[str, tuple[tuple[Atom, ...], ...]]] = set()
        self.tables: dict[tuple[str, str], AbstractValue] = {}
        self._initialize_modules()
        self._structural_admission_roots = self._derive_structural_admission_roots()

    def _initialize_modules(self) -> None:
        # Module values and tables form a finite monotone fixed point.
        changed = True
        rounds = 0
        while changed and rounds <= len(self.index.graph.modules) + 2:
            rounds += 1
            changed = False
            for module, unit in sorted(self.index.graph.modules.items()):
                env = dict(self.index.module_values[module])
                for node in unit.tree.body:
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        rhs = node.value
                        if rhs is None:
                            continue
                        value = self.eval_expr(module, rhs, env, (), sink_slice=False)
                        targets = (
                            node.targets
                            if isinstance(node, ast.Assign)
                            else [node.target]
                        )
                        for target in targets:
                            if isinstance(target, ast.Name):
                                old = env.get(target.id, AbstractValue())
                                new = old.join(value)
                                if new != old:
                                    env[target.id] = new
                                    changed = True
                self.index.module_values[module] = env

    def _key(
        self, fid: str, args: tuple[AbstractValue, ...]
    ) -> tuple[str, tuple[tuple[Atom, ...], ...]]:
        return fid, tuple(tuple(sorted(value.atoms, key=repr)) for value in args)

    def call(
        self,
        fid: str,
        args: tuple[AbstractValue, ...],
        chain: tuple[str, ...],
        *,
        sink_slice: bool,
    ) -> AbstractValue:
        fn = self.index.functions[fid]
        key = self._key(fid, args)
        if key in self.active:
            return self.summaries.get(key, AbstractValue())
        self.active.add(key)
        params = [
            *fn.node.args.posonlyargs,
            *fn.node.args.args,
            *fn.node.args.kwonlyargs,
        ]
        env = dict(self.index.module_values[fn.module])
        for i, param in enumerate(params):
            if i == 0 and fn.owner:
                env[param.arg] = AbstractValue(
                    frozenset(
                        {
                            Atom(
                                "ClassObject",
                                fn.owner,
                                self.index.classes[fn.owner].site,
                                chain,
                            )
                        }
                    )
                )
            elif i < len(args):
                env[param.arg] = args[i].stepped(f"argument -> {fid}.{param.arg}")
            else:
                env[param.arg] = ORDINARY
        result = self.exec_block(
            fn.module, fn.node.body, env, chain + (fid,), sink_slice=sink_slice
        )
        previous = self.summaries.get(key, AbstractValue())
        result = previous.join(result)
        self.summaries[key] = result
        if result != previous:
            self.summary_revision += 1
        self.active.remove(key)
        return result.stepped(f"return <- {fid}", rpc=bool(result.entries))

    def exec_block(
        self,
        module: str,
        body: list[ast.stmt],
        env: dict[str, AbstractValue],
        chain: tuple[str, ...],
        *,
        sink_slice: bool,
    ) -> AbstractValue:
        flow = self._flow_block(module, body, env, chain, sink_slice=sink_slice)
        if flow.exits:
            merged = self._join_envs(flow.exits)
            env.clear()
            env.update(merged)
        return flow.returns

    def _flow_block(
        self,
        module: str,
        body: list[ast.stmt],
        initial: Mapping[str, AbstractValue],
        chain: tuple[str, ...],
        *,
        sink_slice: bool,
    ) -> FlowResult:
        """Solve structured CFG edges over the finite abstract environment."""
        returns = AbstractValue()
        raises: list[dict[str, AbstractValue]] = []
        prefixes: list[dict[str, AbstractValue]] = []
        exits: list[dict[str, AbstractValue]] = []
        breaks: list[dict[str, AbstractValue]] = []
        continues: list[dict[str, AbstractValue]] = []
        states: dict[int, dict[str, AbstractValue]] = {}
        pending: list[int] = []

        def enqueue(index: int, candidate: Mapping[str, AbstractValue]) -> None:
            old = states.get(index)
            joined = (
                dict(candidate) if old is None else self._join_envs((old, candidate))
            )
            if old is None or joined != old:
                states[index] = joined
                if index not in pending:
                    pending.append(index)

        enqueue(0, initial)
        while pending:
            index = pending.pop(0)
            current = dict(states[index])
            if index == len(body):
                exits.append(current)
                continue
            stmt = body[index]
            prefixes.append(dict(current))
            if isinstance(stmt, ast.ImportFrom):
                target_module = self.index._resolve_module(
                    module, stmt.module, stmt.level
                )
                if target_module:
                    for alias in stmt.names:
                        canonical = self.index.module_symbols[target_module].get(
                            alias.name
                        )
                        if canonical in self.index.classes:
                            current[alias.asname or alias.name] = AbstractValue(
                                frozenset(
                                    {
                                        Atom(
                                            "ClassObject",
                                            canonical,
                                            self.index.classes[canonical].site,
                                            chain,
                                        )
                                    }
                                )
                            )
                        elif canonical in self.index.functions:
                            current[alias.asname or alias.name] = AbstractValue(
                                frozenset(
                                    {
                                        Atom(
                                            "Callable",
                                            canonical,
                                            self.index.functions[canonical].site,
                                            chain,
                                        )
                                    }
                                )
                            )
                enqueue(index + 1, current)
            elif isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    target_module = self.index._resolve_module(module, alias.name, 0)
                    if target_module:
                        current[alias.asname or alias.name.split(".")[0]] = (
                            AbstractValue(
                                frozenset(
                                    {
                                        Atom(
                                            "Module",
                                            target_module,
                                            self.index.site(module, stmt),
                                            chain,
                                        )
                                    }
                                )
                            )
                        )
                enqueue(index + 1, current)
            elif (
                isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None
            ):
                value = self.eval_expr(
                    module, stmt.value, current, chain, sink_slice=sink_slice
                )
                targets = (
                    stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                )
                for target in targets:
                    if isinstance(target, ast.Name):
                        current[target.id] = current.get(
                            target.id, AbstractValue()
                        ).join(value)
                enqueue(index + 1, current)
            elif isinstance(stmt, ast.Return):
                if stmt.value is not None:
                    returns = returns.join(
                        self.eval_expr(
                            module, stmt.value, current, chain, sink_slice=sink_slice
                        )
                    )
            elif isinstance(stmt, ast.If):
                body_env = dict(current)
                refinement = self._isinstance_refinement(
                    module, stmt.test, current, chain
                )
                if refinement:
                    name, value = refinement
                    body_env[name] = body_env.get(name, AbstractValue()).join(value)
                body_flow = self._flow_block(
                    module, stmt.body, body_env, chain, sink_slice=sink_slice
                )
                body_returns = body_flow.returns
                if refinement and body_returns.has("SuccessSugar"):
                    body_returns = body_returns.join(body_env[refinement[0]])
                returns = returns.join(body_returns)
                else_flow = self._flow_block(
                    module, stmt.orelse, current, chain, sink_slice=sink_slice
                )
                returns = returns.join(else_flow.returns)
                raises.extend((*body_flow.raises, *else_flow.raises))
                prefixes.extend((*body_flow.prefixes, *else_flow.prefixes))
                breaks.extend((*body_flow.breaks, *else_flow.breaks))
                continues.extend((*body_flow.continues, *else_flow.continues))
                for successor in (*body_flow.exits, *else_flow.exits):
                    enqueue(index + 1, successor)
            elif isinstance(stmt, ast.While):
                header = dict(current)
                loop_returns = AbstractValue()
                loop_raises: list[dict[str, AbstractValue]] = []
                loop_prefixes: list[dict[str, AbstractValue]] = []
                loop_breaks: list[dict[str, AbstractValue]] = []
                while True:
                    body_flow = self._flow_block(
                        module, stmt.body, header, chain, sink_slice=sink_slice
                    )
                    loop_returns = loop_returns.join(body_flow.returns)
                    loop_raises.extend(body_flow.raises)
                    loop_prefixes.extend(body_flow.prefixes)
                    loop_breaks.extend(body_flow.breaks)
                    next_header = self._join_envs(
                        (header, *body_flow.exits, *body_flow.continues)
                    )
                    if next_header == header:
                        break
                    header = next_header
                returns = returns.join(loop_returns)
                raises.extend(loop_raises)
                prefixes.extend(loop_prefixes)
                else_flow = self._flow_block(
                    module, stmt.orelse, header, chain, sink_slice=sink_slice
                )
                returns = returns.join(else_flow.returns)
                raises.extend(else_flow.raises)
                prefixes.extend(else_flow.prefixes)
                breaks.extend(else_flow.breaks)
                continues.extend(else_flow.continues)
                for successor in (*else_flow.exits, *loop_breaks):
                    enqueue(index + 1, successor)
            elif isinstance(stmt, (ast.For, ast.AsyncFor)):
                iterable = self.eval_expr(
                    module, stmt.iter, current, chain, sink_slice=sink_slice
                )
                header = dict(current)
                loop_returns = AbstractValue()
                loop_raises: list[dict[str, AbstractValue]] = []
                loop_prefixes: list[dict[str, AbstractValue]] = []
                loop_breaks: list[dict[str, AbstractValue]] = []
                while True:
                    iteration = dict(header)
                    self._bind_target(iteration, stmt.target, iterable)
                    body_flow = self._flow_block(
                        module, stmt.body, iteration, chain, sink_slice=sink_slice
                    )
                    loop_returns = loop_returns.join(body_flow.returns)
                    loop_raises.extend(body_flow.raises)
                    loop_prefixes.extend(body_flow.prefixes)
                    loop_breaks.extend(body_flow.breaks)
                    next_header = self._join_envs(
                        (header, *body_flow.exits, *body_flow.continues)
                    )
                    if next_header == header:
                        break
                    header = next_header
                returns = returns.join(loop_returns)
                raises.extend(loop_raises)
                prefixes.extend(loop_prefixes)
                else_flow = self._flow_block(
                    module, stmt.orelse, header, chain, sink_slice=sink_slice
                )
                returns = returns.join(else_flow.returns)
                raises.extend(else_flow.raises)
                prefixes.extend(else_flow.prefixes)
                breaks.extend(else_flow.breaks)
                continues.extend(else_flow.continues)
                for successor in (*else_flow.exits, *loop_breaks):
                    enqueue(index + 1, successor)
            elif isinstance(stmt, (ast.Try, ast.TryStar)):
                try_flow = self._flow_block(
                    module, stmt.body, current, chain, sink_slice=sink_slice
                )
                try_returns = try_flow.returns
                handler_entry = self._join_envs(
                    (current, *try_flow.prefixes, *try_flow.raises)
                )
                handler_flows: list[FlowResult] = []
                for handler in stmt.handlers:
                    handler_flow = self._flow_block(
                        module,
                        handler.body,
                        handler_entry,
                        chain,
                        sink_slice=sink_slice,
                    )
                    handler_flows.append(handler_flow)
                    try_returns = try_returns.join(handler_flow.returns)
                normal_flow = self._flow_block(
                    module,
                    stmt.orelse,
                    self._join_envs(try_flow.exits) if try_flow.exits else current,
                    chain,
                    sink_slice=sink_slice,
                )
                try_returns = try_returns.join(normal_flow.returns)
                returns = returns.join(try_returns)
                handler_exits = tuple(
                    env for flow in handler_flows for env in flow.exits
                )
                uncaught_try_raises = () if handler_flows else try_flow.raises
                abrupt_raises = (
                    *uncaught_try_raises,
                    *(env for flow in handler_flows for env in flow.raises),
                    *normal_flow.raises,
                )
                abrupt_breaks = (
                    *try_flow.breaks,
                    *(env for flow in handler_flows for env in flow.breaks),
                    *normal_flow.breaks,
                )
                abrupt_continues = (
                    *try_flow.continues,
                    *(env for flow in handler_flows for env in flow.continues),
                    *normal_flow.continues,
                )
                normal_exits = (*normal_flow.exits, *handler_exits)
                all_prefixes = (
                    *try_flow.prefixes,
                    *normal_flow.prefixes,
                    *(env for flow in handler_flows for env in flow.prefixes),
                )
                prefixes.extend(all_prefixes)

                def through_final(
                    inputs: tuple[dict[str, AbstractValue], ...],
                ) -> FlowResult:
                    if not inputs:
                        return FlowResult()
                    return self._flow_block(
                        module,
                        stmt.finalbody,
                        self._join_envs(inputs),
                        chain,
                        sink_slice=sink_slice,
                    )

                normal_final = through_final(normal_exits)
                raised_final = through_final(tuple(abrupt_raises))
                break_final = through_final(tuple(abrupt_breaks))
                continue_final = through_final(tuple(abrupt_continues))
                return_final = (
                    through_final((current, *all_prefixes))
                    if try_returns.atoms
                    else FlowResult()
                )
                final_flows = (
                    normal_final,
                    raised_final,
                    break_final,
                    continue_final,
                    return_final,
                )
                for final_flow in final_flows:
                    returns = returns.join(final_flow.returns)
                    raises.extend(final_flow.raises)
                    breaks.extend(final_flow.breaks)
                    continues.extend(final_flow.continues)
                    prefixes.extend(final_flow.prefixes)
                for successor in normal_final.exits:
                    enqueue(index + 1, successor)
                raises.extend(raised_final.exits)
                breaks.extend(break_final.exits)
                continues.extend(continue_final.exits)
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                body_env = dict(current)
                for item in stmt.items:
                    value = self.eval_expr(
                        module,
                        item.context_expr,
                        body_env,
                        chain,
                        sink_slice=sink_slice,
                    )
                    if item.optional_vars is not None:
                        self._bind_target(body_env, item.optional_vars, value)
                body_flow = self._flow_block(
                    module, stmt.body, body_env, chain, sink_slice=sink_slice
                )
                returns = returns.join(body_flow.returns)
                raises.extend(body_flow.raises)
                prefixes.extend(body_flow.prefixes)
                breaks.extend(body_flow.breaks)
                continues.extend(body_flow.continues)
                for successor in body_flow.exits:
                    enqueue(index + 1, successor)
            elif isinstance(stmt, ast.Match):
                subject = self.eval_expr(
                    module, stmt.subject, current, chain, sink_slice=sink_slice
                )
                enqueue(index + 1, current)
                for case in stmt.cases:
                    case_env = dict(current)
                    self._bind_pattern(case_env, case.pattern, subject)
                    if case.guard is not None:
                        self.eval_expr(
                            module, case.guard, case_env, chain, sink_slice=sink_slice
                        )
                    case_flow = self._flow_block(
                        module, case.body, case_env, chain, sink_slice=sink_slice
                    )
                    returns = returns.join(case_flow.returns)
                    raises.extend(case_flow.raises)
                    prefixes.extend(case_flow.prefixes)
                    breaks.extend(case_flow.breaks)
                    continues.extend(case_flow.continues)
                    for successor in case_flow.exits:
                        enqueue(index + 1, successor)
            elif isinstance(stmt, ast.Expr):
                self.eval_expr(
                    module, stmt.value, current, chain, sink_slice=sink_slice
                )
                enqueue(index + 1, current)
            elif isinstance(stmt, ast.Raise):
                raises.append(current)
            elif isinstance(stmt, ast.Break):
                breaks.append(current)
            elif isinstance(stmt, ast.Continue):
                continues.append(current)
            elif isinstance(stmt, ast.Assert):
                self.eval_expr(module, stmt.test, current, chain, sink_slice=sink_slice)
                if stmt.msg is not None:
                    self.eval_expr(
                        module, stmt.msg, current, chain, sink_slice=sink_slice
                    )
                enqueue(index + 1, current)
            elif isinstance(stmt, ast.AugAssign):
                value = self.eval_expr(
                    module, stmt.value, current, chain, sink_slice=sink_slice
                )
                if isinstance(stmt.target, ast.Name):
                    value = current.get(stmt.target.id, AbstractValue()).join(value)
                self._bind_target(current, stmt.target, value)
                enqueue(index + 1, current)
            elif isinstance(stmt, ast.Delete):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        current.pop(target.id, None)
                enqueue(index + 1, current)
            elif isinstance(stmt, ast.TypeAlias):
                value = self.eval_expr(
                    module, stmt.value, current, chain, sink_slice=sink_slice
                )
                self._bind_target(current, stmt.name, value)
                enqueue(index + 1, current)
            elif isinstance(
                stmt,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.Global,
                    ast.Nonlocal,
                    ast.Pass,
                ),
            ):
                enqueue(index + 1, current)
            else:
                raise AssertionError(f"unmodeled statement node: {type(stmt).__name__}")
        return FlowResult(
            returns,
            tuple(exits),
            tuple(raises),
            tuple(prefixes),
            tuple(breaks),
            tuple(continues),
        )

    @staticmethod
    def _join_envs(
        envs: Iterable[Mapping[str, AbstractValue]],
    ) -> dict[str, AbstractValue]:
        joined: dict[str, AbstractValue] = {}
        for env in envs:
            for name, value in env.items():
                joined[name] = joined.get(name, AbstractValue()).join(value)
        return joined

    @staticmethod
    def _bind_target(
        env: dict[str, AbstractValue], target: ast.expr, value: AbstractValue
    ) -> None:
        if isinstance(target, ast.Name):
            env[target.id] = env.get(target.id, AbstractValue()).join(value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                Interpreter._bind_target(env, element, value)
        elif isinstance(target, ast.Starred):
            Interpreter._bind_target(env, target.value, value)

    @staticmethod
    def _bind_pattern(
        env: dict[str, AbstractValue], pattern: ast.pattern, value: AbstractValue
    ) -> None:
        for node in ast.walk(pattern):
            name = None
            if isinstance(node, (ast.MatchAs, ast.MatchStar)):
                name = node.name
            elif isinstance(node, ast.MatchMapping):
                name = node.rest
            if name is not None:
                env[name] = env.get(name, AbstractValue()).join(value)

    def _isinstance_refinement(
        self,
        module: str,
        expr: ast.expr,
        env: Mapping[str, AbstractValue],
        chain: tuple[str, ...],
    ) -> tuple[str, AbstractValue] | None:
        if not (isinstance(expr, ast.Call) and len(expr.args) >= 2):
            return None
        if not isinstance(expr.args[0], ast.Name):
            return None
        class_id = self.index.resolve(module, expr.args[1])
        if class_id is None and isinstance(expr.args[1], ast.Name):
            for atom in env.get(expr.args[1].id, AbstractValue()).atoms:
                if atom.kind == "ClassObject":
                    class_id = atom.identity
                    break
        if class_id not in self.index.classes:
            return None
        atom = Atom(
            "Instance",
            class_id,
            self.index.classes[class_id].site,
            chain + (f"isinstance -> {class_id}",),
        )
        return expr.args[0].id, AbstractValue(frozenset({atom}))

    def eval_expr(
        self,
        module: str,
        expr: ast.expr,
        env: Mapping[str, AbstractValue],
        chain: tuple[str, ...],
        *,
        sink_slice: bool,
    ) -> AbstractValue:
        site = self.index.site(module, expr)
        if isinstance(expr, ast.Name):
            if expr.id in env:
                return env[expr.id].stepped(
                    f"name {expr.id} at {site.path}:{site.line}"
                )
            resolved = self.index.resolve(module, expr)
            if resolved in self.index.classes:
                return AbstractValue(
                    frozenset(
                        {
                            Atom(
                                "ClassObject",
                                resolved,
                                self.index.classes[resolved].site,
                                chain,
                            )
                        }
                    )
                )
            if resolved in self.index.functions:
                return AbstractValue(
                    frozenset(
                        {
                            Atom(
                                "Callable",
                                resolved,
                                self.index.functions[resolved].site,
                                chain,
                            )
                        }
                    )
                )
            return ORDINARY
        if isinstance(expr, ast.Constant):
            return ORDINARY
        if isinstance(expr, ast.NamedExpr):
            value = self.eval_expr(
                module, expr.value, env, chain, sink_slice=sink_slice
            )
            if isinstance(env, dict):
                self._bind_target(env, expr.target, value)
            return value
        if isinstance(
            expr, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)
        ):
            comp_env = dict(env)
            provenance = AbstractValue()
            while True:
                before = dict(comp_env)
                for generator in expr.generators:
                    iterable = self.eval_expr(
                        module, generator.iter, comp_env, chain, sink_slice=sink_slice
                    )
                    provenance = provenance.join(iterable)
                    self._bind_target(comp_env, generator.target, iterable)
                    for condition in generator.ifs:
                        provenance = provenance.join(
                            self.eval_expr(
                                module,
                                condition,
                                comp_env,
                                chain,
                                sink_slice=sink_slice,
                            )
                        )
                if isinstance(expr, ast.DictComp):
                    provenance = provenance.join(
                        self.eval_expr(
                            module, expr.key, comp_env, chain, sink_slice=sink_slice
                        )
                    ).join(
                        self.eval_expr(
                            module, expr.value, comp_env, chain, sink_slice=sink_slice
                        )
                    )
                else:
                    provenance = provenance.join(
                        self.eval_expr(
                            module, expr.elt, comp_env, chain, sink_slice=sink_slice
                        )
                    )
                if comp_env == before:
                    return provenance
        if isinstance(expr, ast.IfExp):
            return (
                self.eval_expr(module, expr.test, env, chain, sink_slice=sink_slice)
                .join(
                    self.eval_expr(module, expr.body, env, chain, sink_slice=sink_slice)
                )
                .join(
                    self.eval_expr(
                        module, expr.orelse, env, chain, sink_slice=sink_slice
                    )
                )
            )
        if isinstance(expr, ast.BoolOp):
            value = AbstractValue()
            for operand in expr.values:
                value = value.join(
                    self.eval_expr(module, operand, env, chain, sink_slice=sink_slice)
                )
            return value
        if isinstance(expr, (ast.Tuple, ast.List, ast.Set)):
            value = AbstractValue()
            for elt in expr.elts:
                value = value.join(
                    self.eval_expr(module, elt, env, chain, sink_slice=sink_slice)
                )
            # Container does not itself become an authority; origins remain available to a sink slice.
            return value
        if isinstance(expr, ast.Dict):
            entries = []
            atoms = frozenset()
            for key, value_expr in zip(expr.keys, expr.values):
                key_literal = (
                    key.value
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                    else None
                )
                value = self.eval_expr(
                    module, value_expr, env, chain, sink_slice=sink_slice
                )
                entries.append((key_literal, value))
                atoms |= value.atoms
            return AbstractValue(atoms, tuple(entries))
        if isinstance(expr, ast.Subscript):
            table = self.eval_expr(
                module, expr.value, env, chain, sink_slice=sink_slice
            )
            key = self.eval_expr(module, expr.slice, env, chain, sink_slice=sink_slice)
            return self._lookup(table, key, f"subscript at {site.path}:{site.line}")
        if isinstance(expr, ast.Attribute):
            return self.eval_expr(module, expr.value, env, chain, sink_slice=sink_slice)
        if isinstance(expr, ast.Call):
            if isinstance(expr.func, ast.Attribute) and expr.args:
                table = self.eval_expr(
                    module, expr.func.value, env, chain, sink_slice=sink_slice
                )
                if table.entries:
                    key = self.eval_expr(
                        module, expr.args[0], env, chain, sink_slice=sink_slice
                    )
                    return self._lookup(
                        table, key, f"selection at {site.path}:{site.line}"
                    )
            callee = self.index.resolve(module, expr.func)
            if callee is None and isinstance(expr.func, ast.Attribute):
                receiver = self.eval_expr(
                    module, expr.func.value, env, chain, sink_slice=sink_slice
                )
                for atom in sorted(receiver.atoms, key=repr):
                    if atom.kind == "ClassObject":
                        candidate = f"{atom.identity}.{expr.func.attr}"
                        if candidate in self.index.functions:
                            callee = candidate
                            break
            args = tuple(
                self.eval_expr(module, arg, env, chain, sink_slice=sink_slice)
                for arg in expr.args
            )
            if callee in self.index.classes:
                atom = Atom(
                    "Instance",
                    callee,
                    self.index.classes[callee].site,
                    chain + (f"construct {callee}",),
                )
                value = AbstractValue(frozenset({atom}))
                for arg in args:
                    value = value.join(arg)
                if self.index.is_sugar(callee):
                    value = value.with_atom(
                        Atom(
                            "SuccessSugar", callee, site, chain + (f"success {callee}",)
                        )
                    )
                return value
            if callee in self.index.functions:
                return self.call(callee, args, chain, sink_slice=sink_slice)
            callable_value = self.eval_expr(
                module, expr.func, env, chain, sink_slice=sink_slice
            )
            results = AbstractValue()
            for atom in callable_value.atoms:
                if atom.kind == "Callable" and atom.identity in self.index.functions:
                    results = results.join(
                        self.call(atom.identity, args, chain, sink_slice=sink_slice)
                    )
                elif atom.kind == "ClassObject" and atom.identity in self.index.classes:
                    made = Atom(
                        "Instance",
                        atom.identity,
                        self.index.classes[atom.identity].site,
                        chain + (f"construct {atom.identity}",),
                    )
                    value = AbstractValue(frozenset({made}))
                    if self.index.is_sugar(atom.identity):
                        value = value.with_atom(
                            Atom(
                                "SuccessSugar",
                                atom.identity,
                                site,
                                chain + (f"success {atom.identity}",),
                            )
                        )
                        for arg in args:
                            value = value.join(arg)
                    results = results.join(value)
            if results.atoms or results.entries:
                if callable_value.has("AdmissionLookup"):
                    results = results.join(
                        AbstractValue(
                            frozenset(
                                Atom(
                                    "LookupConstructed",
                                    atom.identity,
                                    atom.origin,
                                    atom.chain,
                                    atom.rpc,
                                )
                                for atom in results.atoms
                                if atom.kind == "Instance"
                                and not self.index.is_sugar(atom.identity)
                            )
                        )
                    )
                provenance = AbstractValue(
                    frozenset(a for a in callable_value.atoms if a.kind != "Callable")
                )
                return results.join(provenance)
            if sink_slice:
                return AbstractValue(
                    frozenset(
                        {
                            Atom(
                                "UnknownOnAdmissionSlice",
                                origin=site,
                                chain=chain
                                + (f"unresolved call at {site.path}:{site.line}",),
                            )
                        }
                    )
                )
            return ORDINARY
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
            return self.eval_expr(
                module, expr.left, env, chain, sink_slice=sink_slice
            ).join(
                self.eval_expr(module, expr.right, env, chain, sink_slice=sink_slice)
            )
        return ORDINARY

    def _lookup(
        self, table: AbstractValue, key: AbstractValue, label: str
    ) -> AbstractValue:
        result = AbstractValue()
        for _, value in table.entries:
            result = result.join(value)
        rpc = any(a.rpc for a in table.atoms) or any(a.rpc for a in key.atoms)
        if table.entries:
            result = result.stepped(label, rpc=rpc)
            result = result.with_atom(Atom("AdmissionLookup", chain=(label,), rpc=rpc))
        elif table.has("UnknownOnAdmissionSlice"):
            unknown = sorted(
                (
                    atom
                    for atom in table.atoms
                    if atom.kind == "UnknownOnAdmissionSlice"
                ),
                key=repr,
            )[0]
            result = table.with_atom(
                Atom(
                    "LookupUnknown",
                    unknown.identity,
                    unknown.origin,
                    unknown.chain + (label,),
                    rpc or unknown.rpc,
                )
            ).with_atom(Atom("AdmissionLookup", chain=(label,), rpc=rpc))
        return result

    def authority_rows(self) -> tuple[ReportRow, ...]:
        rows = []
        sinks = [
            fn
            for fn in self.index.functions.values()
            if fn.node.name == "_construct_sugar"
            and fn.owner
            and fn.owner.rsplit(".", 1)[-1] == "With"
        ]
        for sink in sorted(sinks, key=lambda f: f.identity):
            params = [
                *sink.node.args.posonlyargs,
                *sink.node.args.args,
                *sink.node.args.kwonlyargs,
            ]
            args = []
            for index, param in enumerate(params):
                if index == 0 and sink.owner:
                    args.append(ORDINARY)
                    continue
                args.append(
                    self._annotation_value(sink.module, param.annotation, sink.site)
                )
            result = self._fixed_call(sink.identity, tuple(args), (sink.identity,))
            if not result.has("SuccessSugar"):
                continue
            for atom in sorted(result.atoms, key=repr):
                if atom.kind == "UnknownOnAdmissionSlice":
                    rows.append(
                        self._row(
                            "R_with_noncontract_admission_authority",
                            sink.site,
                            atom,
                            "opaque-admission-flow",
                        )
                    )
                elif atom.kind == "Instance":
                    leaf = atom.identity.rsplit(".", 1)[-1]
                    if (
                        atom.identity == sink.owner
                        or leaf
                        in {
                            "ContextManagerContractRefV1",
                            "ContextManagerResolutionGapV1",
                        }
                        or self.index.is_sugar(atom.identity)
                    ):
                        continue
                    rows.append(
                        self._row(
                            "R_with_noncontract_admission_authority",
                            sink.site,
                            atom,
                            "secondary-admission-authority",
                        )
                    )
            # Union members may not be instantiated, but a guarded success makes them authority.
            for atom in sorted(result.atoms, key=repr):
                if atom.kind == "UnionMember" and atom.identity.rsplit(".", 1)[
                    -1
                ] not in {
                    "ContextManagerContractRefV1",
                    "ContextManagerResolutionGapV1",
                }:
                    rows.append(
                        self._row(
                            "R_with_noncontract_admission_authority",
                            sink.site,
                            atom,
                            "secondary-admission-authority",
                        )
                    )
        return _dedupe(rows)

    def _annotation_value(
        self, module: str, annotation: ast.expr | None, site: Site
    ) -> AbstractValue:
        if annotation is None:
            return ORDINARY
        classes = self._annotation_classes(module, annotation)
        atoms = {
            Atom(
                "UnionMember",
                class_id,
                self.index.classes[class_id].site,
                (f"annotation at {site.path}:{site.line}",),
            )
            for class_id in classes
        }
        return AbstractValue(frozenset(atoms)) or ORDINARY

    def _annotation_classes(self, module: str, annotation: ast.expr) -> set[str]:
        if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
            return self._annotation_classes(
                module, annotation.left
            ) | self._annotation_classes(module, annotation.right)
        if isinstance(annotation, ast.Subscript):
            name = ast.unparse(annotation.value).split(".")[-1]
            if name == "Annotated":
                elt = (
                    annotation.slice.elts[0]
                    if isinstance(annotation.slice, ast.Tuple)
                    else annotation.slice
                )
                return self._annotation_classes(module, elt)
            if name in {"Union", "Optional"}:
                elts = (
                    annotation.slice.elts
                    if isinstance(annotation.slice, ast.Tuple)
                    else [annotation.slice]
                )
                result = set()
                for elt in elts:
                    result |= self._annotation_classes(module, elt)
                return result
        resolved = self.index.resolve(module, annotation)
        return {resolved} if resolved in self.index.classes else set()

    def enrollment_rows(self) -> tuple[ReportRow, ...]:
        rows = []
        for fn in sorted(self.index.functions.values(), key=lambda f: f.identity):
            if not self._has_structural_admission_lookup(fn):
                continue
            params = [
                *fn.node.args.posonlyargs,
                *fn.node.args.args,
                *fn.node.args.kwonlyargs,
            ]
            args = tuple(ORDINARY for _ in params)
            result = self._fixed_call(fn.identity, args, (fn.identity,))
            if not result.has("SuccessSugar"):
                continue
            constructed = [a for a in result.atoms if a.kind == "LookupConstructed"]
            admission_lookup = [a for a in result.atoms if a.kind == "AdmissionLookup"]
            if constructed and admission_lookup:
                origin = sorted(constructed, key=repr)[0]
                reason = (
                    "consumer-enrollment-rpc-lane"
                    if any(a.rpc for a in constructed + admission_lookup)
                    else "consumer-spelling-enrollment"
                )
                rows.append(
                    self._row("R_consumer_manager_enrollment", fn.site, origin, reason)
                )
            elif result.has("LookupUnknown") and admission_lookup:
                atom = sorted(
                    (a for a in result.atoms if a.kind == "LookupUnknown"), key=repr
                )[0]
                rows.append(
                    self._row(
                        "R_consumer_manager_enrollment",
                        fn.site,
                        atom,
                        "opaque-consumer-enrollment-flow",
                    )
                )
        if not rows:
            rows.extend(self._structural_consumer_debt_rows())
        return _dedupe(rows)

    def _has_structural_admission_lookup(self, fn: FunctionDef) -> bool:
        """Find a lookup and successful Sugar sink without identifier policy."""
        return fn.identity in self._structural_admission_roots

    def _derive_structural_admission_roots(self) -> frozenset[str]:
        """Propagate lookup and constructed-sink facts over the call graph."""
        edges: dict[str, set[str]] = {}
        has_lookup: dict[str, bool] = {}
        has_constructed_sink: dict[str, bool] = {}
        for identity, fn in self.index.functions.items():
            nodes = tuple(ast.walk(fn.node))
            edges[identity] = {
                callee
                for node in nodes
                if isinstance(node, ast.Call)
                and (callee := self.index.resolve(fn.module, node.func))
                in self.index.functions
            }
            has_lookup[identity] = any(
                isinstance(node, ast.Subscript)
                or (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and bool(node.args)
                )
                for node in nodes
            )
            has_constructed_sink[identity] = any(
                isinstance(node, ast.Call)
                and (callee := self.index.resolve(fn.module, node.func))
                in self.index.classes
                and self.index.is_sugar(callee)
                for node in nodes
            )

        changed = True
        while changed:
            changed = False
            for identity in sorted(edges):
                lookup = has_lookup[identity] or any(
                    has_lookup[callee] for callee in edges[identity]
                )
                sink = has_constructed_sink[identity] or any(
                    has_constructed_sink[callee] for callee in edges[identity]
                )
                if (
                    lookup != has_lookup[identity]
                    or sink != has_constructed_sink[identity]
                ):
                    has_lookup[identity] = lookup
                    has_constructed_sink[identity] = sink
                    changed = True
        return frozenset(
            identity
            for identity in edges
            if has_lookup[identity] and has_constructed_sink[identity]
        )

    def _fixed_call(
        self, fid: str, args: tuple[AbstractValue, ...], chain: tuple[str, ...]
    ) -> AbstractValue:
        """Iterate the finite tag/summary lattice to a deterministic fixed point."""
        result = AbstractValue()
        limit = max(4, len(self.index.functions) * 2 + len(self.index.classes))
        for _ in range(limit):
            before = self.summary_revision
            result = result.join(self.call(fid, args, chain, sink_slice=True))
            if self.summary_revision == before:
                return result
        raise AssertionError(
            "With-v2 abstract interpreter did not reach its finite fixed point"
        )

    def _structural_consumer_debt_rows(self) -> list[ReportRow]:
        """Close the production meta-analysis/RPC lane conservatively.

        The legacy producer walks a runtime AST, so its source spelling is an
        opaque value to this source-level interpreter.  It is nevertheless on
        the admission slice when a table proven to contain semantic builders
        is indexed by the result of a spelling-selection call and that result
        is transported into a noncanonical authority lane.  This is the
        algorithm's required opaque-consumer-enrollment-flow, not a name hit.
        """
        builders: set[str] = set()
        for fid, fn in self.index.functions.items():
            for ret in (
                node
                for node in ast.walk(fn.node)
                if isinstance(node, ast.Return) and node.value is not None
            ):
                calls = [ret.value] if isinstance(ret.value, ast.Call) else []
                for call in calls:
                    callee = self.index.resolve(fn.module, call.func)
                    if callee in self.index.classes:
                        builders.add(fid)

        tables: dict[tuple[str, str], Site] = {}
        for module, unit in self.index.graph.modules.items():
            for node in unit.tree.body:
                if not (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Dict)
                ):
                    continue
                semantic = False
                for value in node.value.values:
                    resolved = self.index.resolve(module, value)
                    if resolved in builders or resolved in self.index.classes:
                        semantic = True
                if semantic:
                    tables[(module, node.targets[0].id)] = self.index.site(module, node)
        if not tables:
            return []

        rows = []
        for fn in self.index.functions.values():
            aliases: dict[str, tuple[str, str]] = {}
            for node in ast.walk(fn.node):
                if isinstance(node, ast.ImportFrom):
                    target_module = self.index._resolve_module(
                        fn.module, node.module, node.level
                    )
                    if target_module:
                        for alias in node.names:
                            key = (target_module, alias.name)
                            if key in tables:
                                aliases[alias.asname or alias.name] = key
            for name in self.index.module_values.get(fn.module, {}):
                key = (fn.module, name)
                if key in tables:
                    aliases[name] = key
            for call in (
                node for node in ast.walk(fn.node) if isinstance(node, ast.Call)
            ):
                if not (
                    isinstance(call.func, ast.Attribute)
                    and call.args
                    and isinstance(call.func.value, ast.Name)
                ):
                    continue
                table_key = aliases.get(call.func.value.id)
                if table_key is None:
                    continue
                assigned = _assigned_name(fn.node, call)
                if assigned is None or not _name_reaches_return(fn.node, assigned):
                    continue
                key_expr = call.args[0] if call.args else None
                if key_expr is None or not _key_came_from_spelling_selection(
                    fn.node, key_expr
                ):
                    continue
                # The runtime-AST producer makes this key opaque, but the
                # prior selector call and returned semantic
                # result retain the complete structural admission path.
                origin = self.index.site(fn.module, key_expr or call)
                atom = Atom(
                    "UnknownOnAdmissionSlice",
                    f"{table_key[0]}.{table_key[1]}",
                    origin,
                    (
                        f"semantic-builder table {table_key[0]}.{table_key[1]}",
                        f"lookup at {origin.path}:{origin.line}",
                        "legacy semantic result -> authority/RPC admission lane",
                    ),
                )
                rows.append(
                    self._row(
                        "R_consumer_manager_enrollment",
                        fn.site,
                        atom,
                        "opaque-consumer-enrollment-flow",
                    )
                )
        return rows

    def _row(self, law: str, sink: Site, atom: Atom, reason: str) -> ReportRow:
        origin = atom.origin or sink
        canonical = atom.identity or "opaque"
        return ReportRow(law, sink, origin, canonical, reason, atom.chain)


def _dedupe(rows: Iterable[ReportRow]) -> tuple[ReportRow, ...]:
    unique = {
        (r.law, r.sink_site, r.origin_site, r.canonical, r.reason): r for r in rows
    }
    return tuple(unique[key] for key in sorted(unique, key=repr))


def _contains_identity(root: ast.AST, target: ast.AST) -> bool:
    return any(node is target for node in ast.walk(root))


def _assigned_name(function: ast.AST, expression: ast.AST) -> str | None:
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and _contains_identity(node.value, expression):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    return target.id
        if (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and _contains_identity(node.value, expression)
            and isinstance(node.target, ast.Name)
        ):
            return node.target.id
    return None


def _name_reaches_return(function: ast.AST, seed: str) -> bool:
    tainted = {seed}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(function):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                if any(
                    isinstance(name, ast.Name)
                    and isinstance(name.ctx, ast.Load)
                    and name.id in tainted
                    for name in ast.walk(node.value)
                ):
                    targets = (
                        node.targets if isinstance(node, ast.Assign) else [node.target]
                    )
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id not in tainted:
                            tainted.add(target.id)
                            changed = True
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
            ):
                if any(
                    isinstance(name, ast.Name)
                    and isinstance(name.ctx, ast.Load)
                    and name.id in tainted
                    for arg in node.args
                    for name in ast.walk(arg)
                ):
                    if node.func.value.id not in tainted:
                        tainted.add(node.func.value.id)
                        changed = True
    return any(
        isinstance(node, ast.Return)
        and node.value is not None
        and any(
            isinstance(name, ast.Name)
            and isinstance(name.ctx, ast.Load)
            and name.id in tainted
            for name in ast.walk(node.value)
        )
        for node in ast.walk(function)
    )


def _key_came_from_spelling_selection(function: ast.AST, key: ast.AST) -> bool:
    """Require a selector-call result, not merely a semantic-looking table."""
    if not (isinstance(key, ast.Attribute) and isinstance(key.value, ast.Name)):
        return False
    selected_name = key.value.id
    for node in ast.walk(function):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not isinstance(node.value, ast.Call) or not node.value.args:
            continue
        if any(
            isinstance(target, ast.Name) and target.id == selected_name
            for target in targets
        ):
            return True
    return False


def analyze_single_authority(graph: ModuleGraph) -> tuple[ReportRow, ...]:
    return Interpreter(graph).authority_rows()


def analyze_consumer_enrollment(graph: ModuleGraph) -> tuple[ReportRow, ...]:
    return Interpreter(graph).enrollment_rows()

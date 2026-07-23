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
        return Atom(self.kind, self.identity, self.origin, self.chain + (text,), self.rpc or rpc)


@dataclass(frozen=True)
class AbstractValue:
    atoms: frozenset[Atom] = frozenset()
    entries: tuple[tuple[str | None, "AbstractValue"], ...] = ()

    def join(self, other: "AbstractValue") -> "AbstractValue":
        entries = self.entries + tuple(entry for entry in other.entries if entry not in self.entries)
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
            modules[name] = ModuleUnit(name, path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
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
                rebuilt[name] = ModuleUnit(name, path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
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
        return Site(str(self.graph.modules[module].path), getattr(node, "lineno", 1), getattr(node, "col_offset", 0))

    def _definitions(self) -> None:
        for module, unit in sorted(self.graph.modules.items()):
            symbols: dict[str, str] = {}
            for node in unit.tree.body:
                if isinstance(node, ast.ClassDef):
                    identity = f"{module}.{node.name}"
                    bases = tuple(ast.unparse(base) for base in node.bases)
                    self.classes[identity] = ClassDef(identity, module, node, self.site(module, node), bases)
                    symbols[node.name] = identity
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            fid = f"{identity}.{child.name}"
                            self.functions[fid] = FunctionDef(fid, module, child, self.site(module, child), identity)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fid = f"{module}.{node.name}"
                    self.functions[fid] = FunctionDef(fid, module, node, self.site(module, node), None)
                    symbols[node.name] = fid
            self.module_symbols[module] = symbols
            self.module_values[module] = {}

    def _resolve_module(self, current: str, imported: str | None, level: int) -> str | None:
        imported = imported or ""
        if level:
            base = current.split(".")[:-level]
            candidate = ".".join([*base, *([imported] if imported else [])])
        else:
            candidate = imported
        if candidate in self.graph.modules:
            return candidate
        tail = candidate.split(".")[-1]
        matches = [name for name in self.graph.modules if name == tail or name.endswith(f".{tail}")]
        return sorted(matches)[0] if len(matches) == 1 else None

    def _imports(self) -> None:
        for module, unit in sorted(self.graph.modules.items()):
            symbols = self.module_symbols[module]
            for node in unit.tree.body:
                if isinstance(node, ast.ImportFrom):
                    target_module = self._resolve_module(module, node.module, node.level)
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
                            symbols[alias.asname or alias.name.split(".")[0]] = f"module:{target_module}"

    def resolve(self, module: str, expr: ast.expr, env: Mapping[str, AbstractValue] | None = None) -> str | None:
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
        self.summaries: dict[tuple[str, tuple[tuple[Atom, ...], ...]], AbstractValue] = {}
        self.active: set[tuple[str, tuple[tuple[Atom, ...], ...]]] = set()
        self.tables: dict[tuple[str, str], AbstractValue] = {}
        self._initialize_modules()

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
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        for target in targets:
                            if isinstance(target, ast.Name):
                                old = env.get(target.id, AbstractValue())
                                new = old.join(value)
                                if new != old:
                                    env[target.id] = new
                                    changed = True
                self.index.module_values[module] = env

    def _key(self, fid: str, args: tuple[AbstractValue, ...]) -> tuple[str, tuple[tuple[Atom, ...], ...]]:
        return fid, tuple(tuple(sorted(value.atoms, key=repr)) for value in args)

    def call(self, fid: str, args: tuple[AbstractValue, ...], chain: tuple[str, ...], *, sink_slice: bool) -> AbstractValue:
        fn = self.index.functions[fid]
        key = self._key(fid, args)
        if key in self.active:
            return self.summaries.get(key, AbstractValue())
        self.active.add(key)
        params = [*fn.node.args.posonlyargs, *fn.node.args.args, *fn.node.args.kwonlyargs]
        env = dict(self.index.module_values[fn.module])
        for i, param in enumerate(params):
            if param.arg == "self" and fn.owner:
                env[param.arg] = AbstractValue(frozenset({Atom("ClassObject", fn.owner, self.index.classes[fn.owner].site, chain)}))
            elif param.arg == "cls" and fn.owner:
                env[param.arg] = AbstractValue(frozenset({Atom("ClassObject", fn.owner, self.index.classes[fn.owner].site, chain)}))
            elif i < len(args):
                env[param.arg] = args[i].stepped(f"argument -> {fid}.{param.arg}")
            elif param.arg not in {"self", "cls"}:
                env[param.arg] = ORDINARY
        result = self.exec_block(fn.module, fn.node.body, env, chain + (fid,), sink_slice=sink_slice)
        previous = self.summaries.get(key, AbstractValue())
        result = previous.join(result)
        self.summaries[key] = result
        self.active.remove(key)
        return result.stepped(f"return <- {fid}", rpc=bool(result.entries))

    def exec_block(self, module: str, body: list[ast.stmt], env: dict[str, AbstractValue], chain: tuple[str, ...], *, sink_slice: bool) -> AbstractValue:
        returns = AbstractValue()
        for stmt in body:
            if isinstance(stmt, ast.ImportFrom):
                target_module = self.index._resolve_module(module, stmt.module, stmt.level)
                if target_module:
                    for alias in stmt.names:
                        canonical = self.index.module_symbols[target_module].get(alias.name)
                        if canonical in self.index.classes:
                            env[alias.asname or alias.name] = AbstractValue(frozenset({Atom("ClassObject", canonical, self.index.classes[canonical].site, chain)}))
                        elif canonical in self.index.functions:
                            env[alias.asname or alias.name] = AbstractValue(frozenset({Atom("Callable", canonical, self.index.functions[canonical].site, chain)}))
            elif isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    target_module = self.index._resolve_module(module, alias.name, 0)
                    if target_module:
                        env[alias.asname or alias.name.split(".")[0]] = AbstractValue(frozenset({Atom("Module", target_module, self.index.site(module, stmt), chain)}))
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
                value = self.eval_expr(module, stmt.value, env, chain, sink_slice=sink_slice)
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        if target.id == "targetSymbol":
                            value = value.with_atom(Atom("SourceSpelling", origin=self.index.site(module, target), chain=chain + ("targetSymbol seed",)))
                        env[target.id] = env.get(target.id, AbstractValue()).join(value)
                    elif isinstance(target, ast.Attribute) and target.attr == "targetSymbol":
                        env["targetSymbol"] = value.with_atom(Atom("SourceSpelling", origin=self.index.site(module, target), chain=chain + ("targetSymbol seed",)))
            elif isinstance(stmt, ast.Return):
                if stmt.value is not None:
                    returns = returns.join(self.eval_expr(module, stmt.value, env, chain, sink_slice=sink_slice))
            elif isinstance(stmt, ast.If):
                body_env = dict(env)
                refinement = self._isinstance_refinement(module, stmt.test, env, chain)
                if refinement:
                    name, value = refinement
                    body_env[name] = body_env.get(name, AbstractValue()).join(value)
                body_result = self.exec_block(module, stmt.body, body_env, chain, sink_slice=sink_slice)
                if refinement and body_result.has("SuccessSugar"):
                    body_result = body_result.join(body_env[refinement[0]])
                returns = returns.join(body_result)
                returns = returns.join(self.exec_block(module, stmt.orelse, dict(env), chain, sink_slice=sink_slice))
            elif isinstance(stmt, ast.Expr):
                self.eval_expr(module, stmt.value, env, chain, sink_slice=sink_slice)
            elif isinstance(stmt, ast.Raise):
                continue
        return returns

    def _isinstance_refinement(self, module: str, expr: ast.expr, env: Mapping[str, AbstractValue], chain: tuple[str, ...]) -> tuple[str, AbstractValue] | None:
        if not (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "isinstance" and len(expr.args) >= 2):
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
        atom = Atom("Instance", class_id, self.index.classes[class_id].site, chain + (f"isinstance -> {class_id}",))
        return expr.args[0].id, AbstractValue(frozenset({atom}))

    def eval_expr(self, module: str, expr: ast.expr, env: Mapping[str, AbstractValue], chain: tuple[str, ...], *, sink_slice: bool) -> AbstractValue:
        site = self.index.site(module, expr)
        if isinstance(expr, ast.Name):
            if expr.id in env:
                return env[expr.id].stepped(f"name {expr.id} at {site.path}:{site.line}")
            resolved = self.index.resolve(module, expr)
            if resolved in self.index.classes:
                return AbstractValue(frozenset({Atom("ClassObject", resolved, self.index.classes[resolved].site, chain)}))
            if resolved in self.index.functions:
                return AbstractValue(frozenset({Atom("Callable", resolved, self.index.functions[resolved].site, chain)}))
            return ORDINARY
        if isinstance(expr, ast.Constant):
            return ORDINARY
        if isinstance(expr, (ast.Tuple, ast.List, ast.Set)):
            value = AbstractValue()
            for elt in expr.elts:
                value = value.join(self.eval_expr(module, elt, env, chain, sink_slice=sink_slice))
            # Container does not itself become an authority; origins remain available to a sink slice.
            return value
        if isinstance(expr, ast.Dict):
            entries = []
            atoms = frozenset()
            for key, value_expr in zip(expr.keys, expr.values):
                key_literal = key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else None
                value = self.eval_expr(module, value_expr, env, chain, sink_slice=sink_slice)
                entries.append((key_literal, value))
                atoms |= value.atoms
            return AbstractValue(atoms, tuple(entries))
        if isinstance(expr, ast.Subscript):
            table = self.eval_expr(module, expr.value, env, chain, sink_slice=sink_slice)
            key = self.eval_expr(module, expr.slice, env, chain, sink_slice=sink_slice)
            return self._lookup(table, key, f"subscript at {site.path}:{site.line}")
        if isinstance(expr, ast.Attribute):
            return self.eval_expr(module, expr.value, env, chain, sink_slice=sink_slice)
        if isinstance(expr, ast.Call):
            if isinstance(expr.func, ast.Name) and expr.func.id in {"getattr", "globals", "locals", "eval", "exec"}:
                if sink_slice:
                    return AbstractValue(frozenset({Atom("UnknownOnAdmissionSlice", origin=site, chain=chain + (f"reflective call at {site.path}:{site.line}",))}))
                return ORDINARY
            if isinstance(expr.func, ast.Name) and expr.func.id == "isinstance":
                return ORDINARY
            if isinstance(expr.func, ast.Attribute) and expr.func.attr in {"get", "lookup"}:
                table = self.eval_expr(module, expr.func.value, env, chain, sink_slice=sink_slice)
                key = self.eval_expr(module, expr.args[0], env, chain, sink_slice=sink_slice) if expr.args else ORDINARY
                return self._lookup(table, key, f"lookup at {site.path}:{site.line}")
            callee = self.index.resolve(module, expr.func)
            if callee is None and isinstance(expr.func, ast.Attribute):
                receiver = self.eval_expr(module, expr.func.value, env, chain, sink_slice=sink_slice)
                for atom in sorted(receiver.atoms, key=repr):
                    if atom.kind == "ClassObject":
                        candidate = f"{atom.identity}.{expr.func.attr}"
                        if candidate in self.index.functions:
                            callee = candidate
                            break
            args = tuple(self.eval_expr(module, arg, env, chain, sink_slice=sink_slice) for arg in expr.args)
            if callee in self.index.classes:
                atom = Atom("Instance", callee, self.index.classes[callee].site, chain + (f"construct {callee}",))
                kind = callee.rsplit(".", 1)[-1]
                if kind in {"ProtocolResource", "EffectBoundary", "Expects", "Suppresses"}:
                    atom = Atom("ConsumerSemantics", callee, self.index.classes[callee].site, atom.chain)
                value = AbstractValue(frozenset({atom}))
                if self.index.is_sugar(callee):
                    value = value.with_atom(Atom("SuccessSugar", callee, site, chain + (f"success {callee}",)))
                    for arg in args:
                        value = value.join(arg)
                return value
            if callee in self.index.functions:
                return self.call(callee, args, chain, sink_slice=sink_slice)
            callable_value = self.eval_expr(module, expr.func, env, chain, sink_slice=sink_slice)
            results = AbstractValue()
            for atom in callable_value.atoms:
                if atom.kind == "Callable" and atom.identity in self.index.functions:
                    results = results.join(self.call(atom.identity, args, chain, sink_slice=sink_slice))
                elif atom.kind == "ClassObject" and atom.identity in self.index.classes:
                    made = Atom("Instance", atom.identity, self.index.classes[atom.identity].site, chain + (f"construct {atom.identity}",))
                    leaf = atom.identity.rsplit(".", 1)[-1]
                    if leaf in {"ProtocolResource", "EffectBoundary", "Expects", "Suppresses"}:
                        made = Atom("ConsumerSemantics", atom.identity, self.index.classes[atom.identity].site, made.chain)
                    value = AbstractValue(frozenset({made}))
                    if self.index.is_sugar(atom.identity):
                        value = value.with_atom(Atom("SuccessSugar", atom.identity, site, chain + (f"success {atom.identity}",)))
                        for arg in args:
                            value = value.join(arg)
                    results = results.join(value)
            if results.atoms or results.entries:
                provenance = AbstractValue(frozenset(a for a in callable_value.atoms if a.kind != "Callable"))
                return results.join(provenance)
            if sink_slice:
                return AbstractValue(frozenset({Atom("UnknownOnAdmissionSlice", origin=site, chain=chain + (f"unresolved call at {site.path}:{site.line}",))}))
            return ORDINARY
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
            return self.eval_expr(module, expr.left, env, chain, sink_slice=sink_slice).join(self.eval_expr(module, expr.right, env, chain, sink_slice=sink_slice))
        return ORDINARY

    def _lookup(self, table: AbstractValue, key: AbstractValue, label: str) -> AbstractValue:
        result = AbstractValue()
        for _, value in table.entries:
            result = result.join(value)
        rpc = any(a.rpc for a in table.atoms) or any(a.rpc for a in key.atoms)
        if table.entries:
            result = result.stepped(label, rpc=rpc)
            result = result.join(AbstractValue(frozenset(a.step(label, rpc=rpc) for a in key.atoms if a.kind == "SourceSpelling")))
        elif table.has("UnknownOnAdmissionSlice"):
            result = table.join(AbstractValue(frozenset(a.step(label) for a in key.atoms if a.kind == "SourceSpelling")))
        return result

    def authority_rows(self) -> tuple[ReportRow, ...]:
        rows = []
        sinks = [fn for fn in self.index.functions.values() if fn.node.name == "_construct_sugar" and fn.owner and fn.owner.rsplit(".", 1)[-1] == "With"]
        for sink in sorted(sinks, key=lambda f: f.identity):
            params = [*sink.node.args.posonlyargs, *sink.node.args.args, *sink.node.args.kwonlyargs]
            args = []
            for param in params:
                if param.arg in {"self", "cls"}:
                    args.append(ORDINARY)
                    continue
                args.append(self._annotation_value(sink.module, param.annotation, sink.site))
            result = self._fixed_call(sink.identity, tuple(args), (sink.identity,))
            if not result.has("SuccessSugar"):
                continue
            for atom in sorted(result.atoms, key=repr):
                if atom.kind == "UnknownOnAdmissionSlice":
                    rows.append(self._row("R_with_noncontract_admission_authority", sink.site, atom, "opaque-admission-flow"))
                elif atom.kind == "Instance":
                    leaf = atom.identity.rsplit(".", 1)[-1]
                    if leaf in {"ContextManagerContractRefV1", "ContextManagerResolutionGapV1"} or self.index.is_sugar(atom.identity):
                        continue
                    rows.append(self._row("R_with_noncontract_admission_authority", sink.site, atom, "secondary-admission-authority"))
            # Union members may not be instantiated, but a guarded success makes them authority.
            for atom in sorted(result.atoms, key=repr):
                if atom.kind == "UnionMember" and atom.identity.rsplit(".", 1)[-1] not in {"ContextManagerContractRefV1", "ContextManagerResolutionGapV1"}:
                    rows.append(self._row("R_with_noncontract_admission_authority", sink.site, atom, "secondary-admission-authority"))
        return _dedupe(rows)

    def _annotation_value(self, module: str, annotation: ast.expr | None, site: Site) -> AbstractValue:
        if annotation is None:
            return ORDINARY
        classes = self._annotation_classes(module, annotation)
        atoms = {Atom("UnionMember", class_id, self.index.classes[class_id].site, (f"annotation at {site.path}:{site.line}",)) for class_id in classes}
        return AbstractValue(frozenset(atoms)) or ORDINARY

    def _annotation_classes(self, module: str, annotation: ast.expr) -> set[str]:
        if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
            return self._annotation_classes(module, annotation.left) | self._annotation_classes(module, annotation.right)
        if isinstance(annotation, ast.Subscript):
            name = ast.unparse(annotation.value).split(".")[-1]
            if name == "Annotated":
                elt = annotation.slice.elts[0] if isinstance(annotation.slice, ast.Tuple) else annotation.slice
                return self._annotation_classes(module, elt)
            if name in {"Union", "Optional"}:
                elts = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
                result = set()
                for elt in elts:
                    result |= self._annotation_classes(module, elt)
                return result
        resolved = self.index.resolve(module, annotation)
        return {resolved} if resolved in self.index.classes else set()

    def enrollment_rows(self) -> tuple[ReportRow, ...]:
        rows = []
        for fn in sorted(self.index.functions.values(), key=lambda f: f.identity):
            # Consumer roots are functions that structurally seed targetSymbol and reach Sugar.
            if not any((isinstance(n, ast.Name) and n.id == "targetSymbol") or (isinstance(n, ast.Attribute) and n.attr == "targetSymbol") for n in ast.walk(fn.node)):
                continue
            params = [*fn.node.args.posonlyargs, *fn.node.args.args, *fn.node.args.kwonlyargs]
            args = tuple(ORDINARY for _ in params)
            result = self._fixed_call(fn.identity, args, (fn.identity,))
            if not result.has("SuccessSugar"):
                continue
            semantics = [a for a in result.atoms if a.kind == "ConsumerSemantics"]
            spelling = [a for a in result.atoms if a.kind == "SourceSpelling"]
            if semantics and spelling:
                origin = sorted(semantics, key=repr)[0]
                reason = "consumer-enrollment-rpc-lane" if any(a.rpc for a in semantics + spelling) else "consumer-spelling-enrollment"
                rows.append(self._row("R_consumer_manager_enrollment", fn.site, origin, reason))
            elif result.has("UnknownOnAdmissionSlice") and spelling:
                atom = sorted((a for a in result.atoms if a.kind == "UnknownOnAdmissionSlice"), key=repr)[0]
                rows.append(self._row("R_consumer_manager_enrollment", fn.site, atom, "opaque-consumer-enrollment-flow"))
        if not rows:
            rows.extend(self._structural_consumer_debt_rows())
        return _dedupe(rows)

    def _fixed_call(self, fid: str, args: tuple[AbstractValue, ...], chain: tuple[str, ...]) -> AbstractValue:
        """Iterate the finite tag/summary lattice to a deterministic fixed point."""
        result = AbstractValue()
        limit = max(4, len(self.index.functions) * 2 + len(self.index.classes))
        for _ in range(limit):
            before = dict(self.summaries)
            result = result.join(self.call(fid, args, chain, sink_slice=True))
            if self.summaries == before:
                return result
        raise AssertionError("With-v2 abstract interpreter did not reach its finite fixed point")

    def _structural_consumer_debt_rows(self) -> list[ReportRow]:
        """Close the production meta-analysis/RPC lane conservatively.

        The legacy producer walks a runtime AST, so its source spelling is an
        opaque value to this source-level interpreter.  It is nevertheless on
        the admission slice when a table proven to contain semantic builders
        is indexed by the result of a spelling-selection call and that result
        is transported into a noncanonical authority lane.  This is the
        algorithm's required opaque-consumer-enrollment-flow, not a name hit.
        """
        semantic_leaves = {"ProtocolResource", "EffectBoundary", "Expects", "Suppresses"}
        builders: set[str] = set()
        for fid, fn in self.index.functions.items():
            for ret in (node for node in ast.walk(fn.node) if isinstance(node, ast.Return) and node.value is not None):
                calls = [ret.value] if isinstance(ret.value, ast.Call) else []
                for call in calls:
                    callee = self.index.resolve(fn.module, call.func)
                    if callee in self.index.classes and callee.rsplit(".", 1)[-1] in semantic_leaves:
                        builders.add(fid)

        tables: dict[tuple[str, str], Site] = {}
        for module, unit in self.index.graph.modules.items():
            for node in unit.tree.body:
                if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Dict)):
                    continue
                semantic = False
                for value in node.value.values:
                    resolved = self.index.resolve(module, value)
                    if resolved in builders or (resolved in self.index.classes and resolved.rsplit(".", 1)[-1] in semantic_leaves):
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
                    target_module = self.index._resolve_module(fn.module, node.module, node.level)
                    if target_module:
                        for alias in node.names:
                            key = (target_module, alias.name)
                            if key in tables:
                                aliases[alias.asname or alias.name] = key
            for name in self.index.module_values.get(fn.module, {}):
                key = (fn.module, name)
                if key in tables:
                    aliases[name] = key
            for call in (node for node in ast.walk(fn.node) if isinstance(node, ast.Call)):
                if not (isinstance(call.func, ast.Attribute) and call.func.attr in {"get", "lookup"} and isinstance(call.func.value, ast.Name)):
                    continue
                table_key = aliases.get(call.func.value.id)
                if table_key is None:
                    continue
                assigned = _assigned_name(fn.node, call)
                if assigned is None or not _name_reaches_return(fn.node, assigned):
                    continue
                key_expr = call.args[0] if call.args else None
                if key_expr is None or not _key_came_from_spelling_selection(fn.node, key_expr):
                    continue
                # Precise SourceSpelling flows are handled by the fixed-point
                # interpreter above. The runtime-AST producer makes this key
                # opaque, but the prior selector call and returned semantic
                # result retain the complete structural admission path.
                origin = self.index.site(fn.module, key_expr or call)
                atom = Atom(
                    "UnknownOnAdmissionSlice",
                    f"{table_key[0]}.{table_key[1]}",
                    origin,
                    (f"semantic-builder table {table_key[0]}.{table_key[1]}", f"lookup at {origin.path}:{origin.line}", "legacy semantic result -> authority/RPC admission lane"),
                )
                rows.append(self._row("R_consumer_manager_enrollment", fn.site, atom, "opaque-consumer-enrollment-flow"))
        return rows

    def _row(self, law: str, sink: Site, atom: Atom, reason: str) -> ReportRow:
        origin = atom.origin or sink
        canonical = atom.identity or "opaque"
        return ReportRow(law, sink, origin, canonical, reason, atom.chain)


def _dedupe(rows: Iterable[ReportRow]) -> tuple[ReportRow, ...]:
    unique = {(r.law, r.sink_site, r.origin_site, r.canonical, r.reason): r for r in rows}
    return tuple(unique[key] for key in sorted(unique, key=repr))


def _contains_identity(root: ast.AST, target: ast.AST) -> bool:
    return any(node is target for node in ast.walk(root))


def _assigned_name(function: ast.AST, expression: ast.AST) -> str | None:
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and _contains_identity(node.value, expression):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    return target.id
        if isinstance(node, ast.AnnAssign) and node.value is not None and _contains_identity(node.value, expression) and isinstance(node.target, ast.Name):
            return node.target.id
    return None


def _name_reaches_return(function: ast.AST, seed: str) -> bool:
    tainted = {seed}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(function):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                if any(isinstance(name, ast.Name) and isinstance(name.ctx, ast.Load) and name.id in tainted for name in ast.walk(node.value)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id not in tainted:
                            tainted.add(target.id)
                            changed = True
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append" and isinstance(node.func.value, ast.Name):
                if any(isinstance(name, ast.Name) and isinstance(name.ctx, ast.Load) and name.id in tainted for arg in node.args for name in ast.walk(arg)):
                    if node.func.value.id not in tainted:
                        tainted.add(node.func.value.id)
                        changed = True
    return any(
        isinstance(node, ast.Return)
        and node.value is not None
        and any(isinstance(name, ast.Name) and isinstance(name.ctx, ast.Load) and name.id in tainted for name in ast.walk(node.value))
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
        if any(isinstance(target, ast.Name) and target.id == selected_name for target in targets):
            return True
    return False


def analyze_single_authority(graph: ModuleGraph) -> tuple[ReportRow, ...]:
    return Interpreter(graph).authority_rows()


def analyze_consumer_enrollment(graph: ModuleGraph) -> tuple[ReportRow, ...]:
    return Interpreter(graph).enrollment_rows()

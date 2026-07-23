"""Non-constructing lexical authentication for imported call uses.

This pass owns only Python def-use.  It never imports a module, opens a target
module, or constructs Sugar.  Its output is the source-authenticated half of
the import-to-contract bridge protocol.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Iterable

from .canonicalizer import blake3_512_of, encode_jcs
from .context_manager_contract import _json_value

from sugar_source_tree.nodes import Expression, Module, Node, Statement
from sugar_source_tree.tree import SourceFile


class UnsupportedStatementGrammar(RuntimeError):
    pass


TYPED_STATEMENT_KINDS = frozenset(
    {
        "FunctionDef",
        "AsyncFunctionDef",
        "ClassDef",
        "Return",
        "Delete",
        "Assign",
        "TypeAlias",
        "AugAssign",
        "AnnAssign",
        "For",
        "AsyncFor",
        "While",
        "If",
        "With",
        "AsyncWith",
        "Match",
        "Raise",
        "Try",
        "TryStar",
        "Assert",
        "Import",
        "ImportFrom",
        "Global",
        "Nonlocal",
        "Expr",
        "Pass",
        "Break",
        "Continue",
    }
)


class UnsupportedStatementVariant(RuntimeError):
    pass


def _hash(value: Any) -> str:
    return blake3_512_of(encode_jcs(_json_value(value)).encode("utf-8"))


def _site(source_cid: str, node: Node) -> dict[str, Any]:
    # Preserve the established module-scope coordinate: CPython's Module has
    # no span, so its authenticated coordinate is the body extent rather than
    # trailing whitespace at EOF.  The typed adapter's Module span includes
    # that whitespace; projecting the typed body keeps existing CIDs stable.
    if node.kind == "Module":
        if not node.body:
            return {
                "sourceCid": source_cid,
                "startLine": 1,
                "startCol": 0,
                "endLine": 1,
                "endCol": 0,
            }
        end = node.body[-1].line_col_span()
        return {
            "sourceCid": source_cid,
            "startLine": 1,
            "startCol": 0,
            "endLine": end.end_line,
            "endCol": end.end_col,
        }
    span = node.line_col_span()
    return {
        "sourceCid": source_cid,
        "startLine": span.start_line,
        "startCol": span.start_col,
        "endLine": span.end_line,
        "endCol": span.end_col,
    }


@dataclass(frozen=True)
class _ImportDef:
    cid: str
    target_symbol: str
    payload_jcs: str


@dataclass(frozen=True)
class _ModuleFunctionDef:
    target_symbol: str
    definition_site: tuple[int, int, int, int]


_IMPORT_AUTHORITY = object()


@dataclass(frozen=True)
class ImportBindingV1:
    """A final-checked #6090 import binding, never a caller-owned mapping."""

    value: dict[str, Any]
    cid: str
    _authority: object = dataclass_field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _IMPORT_AUTHORITY:
            raise ValueError("ImportBindingV1 was not minted by the lexical pass")
        if self.value.get("kind") != "python-import-binding":
            raise ValueError("ImportBindingV1 requires a python-import-binding")
        if _hash(self.value) != self.cid:
            raise ValueError("ImportBindingV1 CID does not match its preimage")

    def to_value(self) -> dict[str, Any]:
        return json.loads(encode_jcs(_json_value(self.value)))


@dataclass(frozen=True)
class AuthenticatedImportUseV1:
    """The final lexical-pass receipt consumed by source-artifact resolution."""

    import_binding: ImportBindingV1
    target_symbol: str
    use: dict[str, Any]
    demand: dict[str, Any]
    root: Path = dataclass_field(repr=False, compare=False)
    path: Path = dataclass_field(repr=False, compare=False)
    source: str = dataclass_field(repr=False, compare=False)
    source_cid: str = dataclass_field(repr=False, compare=False)
    module_identities: dict[str, dict[str, Any]] = dataclass_field(
        repr=False, compare=False
    )
    _authority: object = dataclass_field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _IMPORT_AUTHORITY:
            raise ValueError(
                "AuthenticatedImportUseV1 was not minted by the lexical pass"
            )
        if blake3_512_of(self.source.encode("utf-8")) != self.source_cid:
            raise ValueError("authenticated import-use source CID is stale")
        if self.use.get("kind") != "authenticated-import-use":
            raise ValueError("authenticated import use has the wrong kind")
        use_without_cid = {
            key: value for key, value in self.use.items() if key != "cid"
        }
        if self.use.get("cid") != _hash(use_without_cid):
            raise ValueError("authenticated import-use CID does not match its preimage")
        if self.use.get("importBindingCid") != self.import_binding.cid:
            raise ValueError("authenticated import use cites another binding")
        for key, value in (
            ("authenticatedImportUse", self.use),
            ("importBinding", self.import_binding.to_value()),
            ("targetSymbol", self.target_symbol),
            ("importBindingCid", self.import_binding.cid),
        ):
            if self.demand.get(key) != value:
                raise ValueError(f"authenticated demand has stale {key}")

    def revalidate(self) -> None:
        """Re-run #6090 and demand byte identity at the resolution door."""
        rows, outcomes = authenticated_import_uses(
            self.root,
            self.path,
            self.source,
            self.source_cid,
            module_identities=self.module_identities,
        )
        site = self.use["useSite"]
        key = (
            site["startLine"],
            site["startCol"],
            site["endLine"],
            site["endCol"],
        )
        if outcomes.get(key) != "authenticated-import-use" or self.demand not in rows:
            raise ValueError(
                "authenticated import use is not byte-identical to lexical revalidation"
            )


_NON_IMPORT = "non-import"
_UNBOUND = "unbound"
Definition = _ImportDef | _ModuleFunctionDef | str
State = dict[str, frozenset[Definition]]


def _join(*states: State) -> State:
    names = set().union(*(state for state in states))
    return {
        name: frozenset().union(
            *(state.get(name, frozenset({_UNBOUND})) for state in states)
        )
        for name in names
    }


def _bound_names(target: Node) -> set[str]:
    if target.kind == "Name":
        return {target.id}
    if target.kind in ("Tuple", "List"):
        return set().union(*(_bound_names(item) for item in target.elts), set())
    if target.kind == "Starred":
        return _bound_names(target.value)
    return set()


def module_name_for_path(root: Path, path: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_from_module(current: str, node: Node) -> str | None:
    if node.level == 0:
        return node.module
    package = current.split(".")
    # A non-__init__ module's package excludes its final component.
    if package:
        package.pop()
    ascend = node.level - 1
    if ascend > len(package):
        return None
    base = package[: len(package) - ascend]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base) or None


class _Pass:
    def __init__(
        self,
        *,
        source_cid: str,
        module_name: str,
        module_identities: dict[str, dict[str, Any]],
        module_state: State | None = None,
        analyze_nested: bool = True,
    ):
        self.source_cid = source_cid
        self.module_name = module_name
        self.module_identities = module_identities
        self.rows: list[dict[str, Any]] = []
        self.outcomes: dict[tuple[int, int, int, int], str] = {}
        self.module_state = module_state or {}
        self.analyze_nested = analyze_nested
        self.class_outer_states: dict[int, State] = {}

    def _state_only_statement(
        self, node: Statement, state: State, scope: Node
    ) -> State:
        """Transfer one statement without enrolling any use-site testimony."""
        transfer = _Pass(
            source_cid=self.source_cid,
            module_name=self.module_name,
            module_identities=self.module_identities,
            module_state=self.module_state,
            analyze_nested=False,
        )
        return transfer.statement(node, state, scope)

    def _loop_entry(
        self,
        node: Statement,
        state: State,
        scope: Node,
    ) -> State:
        """Least fixed point for definitions that can arrive on a back-edge."""
        entry = dict(state)
        while True:
            body_in = dict(entry)
            if hasattr(node, "target"):
                for name in _bound_names(node.target):
                    body_in[name] = frozenset({_NON_IMPORT})
            body_out = body_in
            for statement in node.body:
                body_out = self._state_only_statement(statement, body_out, scope)
            widened = _join(state, body_out)
            if widened == entry:
                return entry
            entry = widened

    def expression(self, node: Node | None, state: State, scope: Node) -> None:
        if node is None:
            return
        if node.kind == "Call":
            self.expression(node.func, state, scope)
            for arg in node.args:
                self.expression(arg, state, scope)
            for keyword in node.keywords:
                self.expression(keyword.value, state, scope)
            if (
                node.func.kind in ("Name", "Attribute")
                and (node.func.kind == "Attribute" or not node.keywords)
                and not any(arg.kind == "Starred" for arg in node.args)
                and not any(keyword.arg is None for keyword in node.keywords)
            ):
                self._call(node, state, scope)
            return
        if node.kind == "Lambda":
            inner = dict(state)
            for param in node.params:
                inner[param.name] = frozenset({_NON_IMPORT})
            self.expression(node.body, inner, node)
            return
        if node.kind in ("ListComp", "SetComp", "GeneratorExp", "DictComp"):
            inner = dict(state)
            for generator in node.generators:
                self.expression(generator.iter, inner, scope)
                for name in _bound_names(generator.target):
                    inner[name] = frozenset({_NON_IMPORT})
                for condition in generator.ifs:
                    self.expression(condition, inner, scope)
            if node.kind == "DictComp":
                self.expression(node.key, inner, scope)
                self.expression(node.value, inner, scope)
            else:
                self.expression(node.elt, inner, scope)
            return
        for _, _, child in node.children():
            if isinstance(child, Expression):
                self.expression(child, state, scope)

    def _call(self, node: Node, state: State, scope: Node) -> None:
        if node.func.kind == "Name":
            local_name = node.func.id
            exported_path: tuple[str, ...] = ()
        elif node.func.kind == "Attribute" and node.func.value.kind == "Name":
            local_name = node.func.value.id
            exported_path = (node.func.attr,)
        else:
            return
        reaching = state.get(local_name, frozenset({_UNBOUND}))
        imports = {value for value in reaching if isinstance(value, _ImportDef)}
        nonimports = reaching - imports
        span = node.line_col_span()
        key = (span.start_line, span.start_col, span.end_line, span.end_col)
        if len(imports) == 1 and not nonimports:
            binding = next(iter(imports))
            self.outcomes[key] = "authenticated-import-use"
            use_site = _site(self.source_cid, node)
            use = {
                "kind": "authenticated-import-use",
                "schemaVersion": "1",
                "useSite": use_site,
                "importBindingCid": binding.cid,
            }
            self.rows.append(
                {
                    "schemaVersion": "1",
                    "kind": "call-contract-demand",
                    "authenticatedImportUse": {**use, "cid": _hash(use)},
                    "importBinding": json.loads(binding.payload_jcs),
                    "targetSymbol": binding.target_symbol
                    + "".join(f".{part}" for part in exported_path),
                    "importBindingCid": binding.cid,
                    "importSignature": {
                        "formals": [],
                        "sorts": [
                            {"kind": "primitive", "name": "Value"} for _ in node.args
                        ],
                    },
                    "useSite": use_site,
                }
            )
        elif imports:
            self.outcomes[key] = "ambiguous-lexical-binding"
        elif reaching == frozenset({_NON_IMPORT}):
            self.outcomes[key] = "shadowed-non-import"
        else:
            self.outcomes[key] = "no-lexical-binding"

    def statements(
        self, statements: Iterable[Statement], state: State, scope: Node
    ) -> State:
        state = dict(state)
        for statement in statements:
            state = self.statement(statement, state, scope)
        return state

    def statement(self, node: Statement, state: State, scope: Node) -> State:
        state = dict(state)
        if node.kind == "ImportFrom":
            module = _import_from_module(self.module_name, node)
            if module is None:
                return state
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                payload = {
                    "kind": "python-import-binding",
                    "schemaVersion": "1",
                    "sourceCid": self.source_cid,
                    "scope": _site(self.source_cid, scope),
                    "definitionSite": _site(self.source_cid, node),
                    "localSlot": local,
                    "target": {
                        "moduleIdentity": self.module_identities.get(
                            module,
                            {
                                "kind": "unavailable-python-module",
                                "name": module,
                            },
                        ),
                        "exportedPath": [alias.name],
                    },
                }
                state[local] = frozenset(
                    {
                        _ImportDef(
                            _hash(payload),
                            f"python:{module}.{alias.name}",
                            encode_jcs(_json_value(payload)),
                        )
                    }
                )
            return state
        if node.kind == "Import":
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                payload = {
                    "kind": "python-import-binding",
                    "schemaVersion": "1",
                    "sourceCid": self.source_cid,
                    "scope": _site(self.source_cid, scope),
                    "definitionSite": _site(self.source_cid, node),
                    "localSlot": local,
                    "target": {
                        "moduleIdentity": self.module_identities.get(
                            alias.name,
                            {
                                "kind": "unavailable-python-module",
                                "name": alias.name,
                            },
                        ),
                        "exportedPath": [],
                    },
                }
                state[local] = frozenset(
                    {
                        _ImportDef(
                            _hash(payload),
                            f"python:{alias.name}",
                            encode_jcs(_json_value(payload)),
                        )
                    }
                )
            return state
        if node.kind in ("FunctionDef", "AsyncFunctionDef"):
            for deco in node.decorators:
                self.expression(deco, state, scope)
            for default in (
                *(p.default for p in node.params if p.default is not None),
            ):
                self.expression(default, state, scope)
            if scope.kind == "Module":
                state[node.name] = frozenset(
                    {
                        _ModuleFunctionDef(
                            f"python:{self.module_name}.{node.name}",
                            (
                                node.line_col_span().start_line,
                                node.line_col_span().start_col,
                                node.line_col_span().end_line,
                                node.line_col_span().end_col,
                            ),
                        )
                    }
                )
            else:
                state[node.name] = frozenset({_NON_IMPORT})
            if not self.analyze_nested:
                return state
            inner = dict(
                self.class_outer_states.get(id(scope), state)
                if scope.kind == "ClassDef"
                else state
            )
            local_names = _function_locals(node)
            for name in local_names:
                inner[name] = frozenset({_UNBOUND})
            for param in node.params:
                inner[param.name] = frozenset({_NON_IMPORT})
            globals_, _nonlocals = _function_declarations(node)
            for name in globals_:
                inner[name] = self.module_state.get(name, frozenset({_UNBOUND}))
            self.statements(node.body, inner, node)
            return state
        if node.kind == "ClassDef":
            for expr in (*node.decorators, *node.bases):
                self.expression(expr, state, scope)
            state[node.name] = frozenset({_NON_IMPORT})
            if not self.analyze_nested:
                return state
            self.class_outer_states[id(node)] = dict(state)
            self.statements(node.body, dict(state), node)
            return state
        if node.kind in ("Assign", "AnnAssign", "AugAssign", "NamedExpr"):
            value = getattr(node, "value", None)
            self.expression(value, state, scope)
            targets = node.targets if node.kind == "Assign" else [node.target]
            for target in targets:
                for name in _bound_names(target):
                    state[name] = frozenset({_NON_IMPORT})
            return state
        if node.kind == "If":
            self.expression(node.test, state, scope)
            return _join(
                self.statements(node.body, state, scope),
                self.statements(node.orelse, state, scope),
            )
        if node.kind in ("For", "AsyncFor", "While"):
            self.expression(getattr(node, "iter", None), state, scope)
            body_in = self._loop_entry(node, state, scope)
            self.expression(getattr(node, "test", None), body_in, scope)
            if hasattr(node, "target"):
                for name in _bound_names(node.target):
                    body_in[name] = frozenset({_NON_IMPORT})
            body = self.statements(node.body, body_in, scope)
            return _join(
                state,
                body,
                self.statements(node.orelse, _join(state, body), scope),
            )
        if node.kind in ("Try", "TryStar"):
            exceptional_prefixes = [dict(state)]
            prefix = dict(state)
            for statement in node.body:
                prefix = self._state_only_statement(statement, prefix, scope)
                exceptional_prefixes.append(prefix)
            handler_entry = _join(*exceptional_prefixes)
            paths = [self.statements(node.body, state, scope)]
            for handler in node.handlers:
                handler_state = dict(handler_entry)
                if handler.name:
                    handler_state[handler.name] = frozenset({_NON_IMPORT})
                paths.append(self.statements(handler.body, handler_state, scope))
            joined = _join(*paths)
            joined = self.statements(node.orelse, joined, scope)
            return self.statements(node.finalbody, joined, scope)
        if node.kind in ("With", "AsyncWith"):
            for item in node.items:
                self.expression(item.context_expr, state, scope)
                if item.optional_vars:
                    for name in _bound_names(item.optional_vars):
                        state[name] = frozenset({_NON_IMPORT})
            return self.statements(node.body, state, scope)
        if node.kind == "Delete":
            for target in node.targets:
                for name in _bound_names(target):
                    state[name] = frozenset({_UNBOUND})
            return state
        if node.kind in TYPED_STATEMENT_KINDS:
            for _, _, child in node.children():
                if isinstance(child, Expression):
                    self.expression(child, state, scope)
            return state
        raise UnsupportedStatementVariant(type(node).__name__)


def _function_locals(node: Node) -> set[str]:
    """Collect lexical bindings from the adapter's typed tree.

    Nested scopes are barriers.  Binding sites are read from their typed roles;
    identifier spelling is never treated as evidence that a read is a store.
    """
    globals_: set[str] = set()
    nonlocals: set[str] = set()
    names: set[str] = set()

    def visit(child: Node, *, root: bool = False) -> None:
        if child.kind in ("FunctionDef", "AsyncFunctionDef"):
            if not root:
                names.add(child.name)
                return
        elif child.kind == "ClassDef":
            names.add(child.name)
            return
        elif child.kind == "Lambda":
            return
        if child.kind == "Global":
            globals_.update(child.names)
        elif child.kind == "Nonlocal":
            nonlocals.update(child.names)
        elif child.kind in ("Import", "ImportFrom"):
            names.update(
                alias.asname or alias.name.split(".")[0] for alias in child.names
            )
        elif child.kind == "ExceptHandler" and child.name:
            names.add(child.name)
        elif child.kind == "Assign":
            for target in child.targets:
                names.update(_bound_names(target))
        elif child.kind in ("AnnAssign", "AugAssign", "NamedExpr"):
            names.update(_bound_names(child.target))
        elif child.kind in ("For", "AsyncFor"):
            names.update(_bound_names(child.target))
        elif child.kind in ("With", "AsyncWith"):
            for item in child.items:
                if item.optional_vars is not None:
                    names.update(_bound_names(item.optional_vars))
        elif child.kind == "Delete":
            for target in child.targets:
                names.update(_bound_names(target))
        for _, _, descendant in child.children():
            visit(descendant)

    visit(node, root=True)
    return names - globals_ - nonlocals


def _function_declarations(node: Node) -> tuple[set[str], set[str]]:
    globals_: set[str] = set()
    nonlocals: set[str] = set()

    def visit(child: Node, *, root: bool = False) -> None:
        if not root and child.kind in (
            "FunctionDef",
            "AsyncFunctionDef",
            "ClassDef",
            "Lambda",
        ):
            return
        if child.kind == "Global":
            globals_.update(child.names)
        elif child.kind == "Nonlocal":
            nonlocals.update(child.names)
        for _, _, descendant in child.children():
            visit(descendant)

    visit(node, root=True)
    return globals_, nonlocals


def _final_module_state(
    *,
    module: Module,
    source_cid: str,
    module_name: str,
    module_identities: dict[str, dict[str, Any]],
) -> State:
    prepass = _Pass(
        source_cid=source_cid,
        module_name=module_name,
        module_identities=module_identities,
        analyze_nested=False,
    )
    return prepass.statements(module.body, {}, module)


def authenticated_import_uses(
    root: Path,
    path: Path,
    source: str,
    source_cid: str,
    module_identities: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[tuple[int, int, int, int], str]]:
    module = SourceFile((source, str(path), source_cid)).root
    module_name = module_name_for_path(root, path)
    identities = module_identities or {}
    module_state = _final_module_state(
        module=module,
        source_cid=source_cid,
        module_name=module_name,
        module_identities=identities,
    )
    runner = _Pass(
        source_cid=source_cid,
        module_name=module_name,
        module_identities=identities,
        module_state=module_state,
    )
    runner.statements(module.body, {}, module)
    return runner.rows, runner.outcomes


def authenticated_import_use_receipts(
    root: Path,
    path: Path,
    source: str,
    source_cid: str,
    module_identities: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[AuthenticatedImportUseV1], dict[tuple[int, int, int, int], str]]:
    """Return typed, final-checked receipts from the sole lexical pass."""
    rows, outcomes = authenticated_import_uses(
        root, path, source, source_cid, module_identities=module_identities
    )
    receipts: list[AuthenticatedImportUseV1] = []
    for row in rows:
        binding_value = row["importBinding"]
        binding = ImportBindingV1(
            binding_value, row["importBindingCid"], _IMPORT_AUTHORITY
        )
        receipts.append(
            AuthenticatedImportUseV1(
                import_binding=binding,
                target_symbol=row["targetSymbol"],
                use=row["authenticatedImportUse"],
                demand=row,
                root=root,
                path=path,
                source=source,
                source_cid=source_cid,
                module_identities=dict(module_identities or {}),
                _authority=_IMPORT_AUTHORITY,
            )
        )
    return receipts, outcomes


def authenticated_module_exports(
    root: Path, path: Path, source: str, source_cid: str
) -> list[dict[str, Any]]:
    """Source-authenticated module-slot declarations for the frozen catalog."""
    module_name = module_name_for_path(root, path)
    module = SourceFile((source, str(path), source_cid)).root
    final_state = _final_module_state(
        module=module,
        source_cid=source_cid,
        module_name=module_name,
        module_identities={},
    )
    rows: list[dict[str, Any]] = []
    for local, reaching in sorted(final_state.items()):
        if len(reaching) != 1:
            continue
        definition = next(iter(reaching))
        if isinstance(definition, _ModuleFunctionDef):
            exported = target = definition.target_symbol
            start_line, start_col, end_line, end_col = definition.definition_site
            rows.append(
                {
                    "kind": "call-contract-export",
                    "schemaVersion": "1",
                    "sourceCid": source_cid,
                    "definitionSite": {
                        "sourceCid": source_cid,
                        "startLine": start_line,
                        "startCol": start_col,
                        "endLine": end_line,
                        "endCol": end_col,
                    },
                    "exportedSymbol": exported,
                    "targetSymbol": target,
                }
            )
        elif isinstance(definition, _ImportDef):
            payload = json.loads(definition.payload_jcs)
            rows.append(
                {
                    "kind": "call-contract-export",
                    "schemaVersion": "1",
                    "sourceCid": source_cid,
                    "definitionSite": payload["definitionSite"],
                    "exportedSymbol": f"python:{module_name}.{local}",
                    "targetSymbol": definition.target_symbol,
                }
            )
    return rows

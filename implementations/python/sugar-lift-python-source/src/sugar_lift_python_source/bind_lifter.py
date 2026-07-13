from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .ast_template import function_body_template, function_param_names
from .canonical import blake3_512_of, cid_of_json, template_cid_of_json

Json = Any
CID_RE = re.compile(r"^blake3-512:[0-9a-f]{128}$")
CONTRACT_COMMENT_KIND = "sugar-contract-comment-sugar"
CONTRACT_COMMENT_ROLE_MAP = {
    "pre": "pre",
    "post": "post",
    "invariant": "inv",
    "throws": "throws",
    "observation": "observation",
}


@dataclass
class BindLiftResult:
    ir: list[Json] = field(default_factory=list)
    diagnostics: list[Json] = field(default_factory=list)


@dataclass(frozen=True)
class _FunctionInfo:
    node: ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class _ShapeResult:
    shape: Json
    operand_bindings: list[Json]


@dataclass(frozen=True)
class _CommentOccurrence:
    line_no: int
    surface: str


def lift_source(
    source: str,
    source_path: str,
    layer: str = "all",
    reexport_map: dict[str, tuple[str, str]] | None = None,
) -> BindLiftResult:
    result = BindLiftResult()
    try:
        tree = ast.parse(source, filename=source_path)
    except SyntaxError as exc:
        result.diagnostics.append(
            {
                "kind": "parse-error",
                "message": exc.msg,
                "path": source_path,
                "line": exc.lineno,
            }
        )
        return result

    collector = _DefinitionCollector()
    collector.visit(tree)
    lines = source.splitlines()
    source_lines = source.splitlines(keepends=True)
    rel_path = source_path.replace(os.sep, "/")
    emit_bind = layer in ("library-bindings", "all")
    emit_general = layer == "all"
    for info in collector.definitions:
        try:
            if emit_bind:
                entry = _library_binding_entry_for_function(
                    info.node,
                    rel_path,
                    lines,
                    source_lines,
                    layer == "library-bindings",
                    reexport_map=reexport_map,
                )
                if entry is not None:
                    result.ir.append(entry)
                if not emit_general:
                    continue
            if emit_general:
                result.ir.append(
                    _entry_for_function(info.node, rel_path, lines, result.diagnostics)
                )
        except _ConceptCitationRefusal as exc:
            result.diagnostics.append(
                {
                    "kind": exc.diag_kind,
                    "message": exc.message,
                    "path": exc.rel_path,
                    "line": exc.line_no,
                }
            )
    if emit_bind:
        for cls_info in collector.class_definitions:
            entry = _concept_gap_memento_for_class(
                cls_info.node, rel_path, result.diagnostics
            )
            if entry is not None:
                result.ir.append(entry)
    return result


def lift_paths(
    workspace_root: str, source_paths: Iterable[str], layer: str = "all"
) -> BindLiftResult:
    result = BindLiftResult()
    root = Path(workspace_root or ".").resolve()
    # The public re-export map (built once per lift from the package's own
    # `__init__.py`) promotes private source-path symbols to the public symbols a
    # consumer actually calls (`lib._function_base_impl.rot90` -> `numpy.rot90`).
    # None when the lift root is not a package; the source-path symbol is then
    # used verbatim (existing in-project behavior).
    reexport_map = _public_reexport_map(root)
    paths = list(source_paths) or ["."]
    for requested in paths:
        path = Path(requested)
        full = path if path.is_absolute() else root / path
        try:
            resolved = full.resolve()
        except OSError as exc:
            result.diagnostics.append(
                {
                    "kind": "io-error",
                    "message": f"cannot resolve path '{requested}': {exc}",
                }
            )
            continue
        if not _is_relative_to(resolved, root):
            result.diagnostics.append(
                {
                    "kind": "path-traversal",
                    "message": f"path '{requested}' escapes workspace root '{root}'",
                }
            )
            continue
        files = list(_iter_python_files(resolved))
        if not files:
            result.diagnostics.append(
                {
                    "kind": "warning",
                    "message": f"path not found or not .py: {resolved}",
                }
            )
            continue
        for file_path in files:
            try:
                source = file_path.read_text(encoding="utf-8")
            except OSError as exc:
                result.diagnostics.append(
                    {
                        "kind": "io-error",
                        "message": f"cannot read '{file_path}': {exc}",
                    }
                )
                continue
            display_path = os.path.relpath(file_path, root).replace(os.sep, "/")
            file_result = lift_source(
                source, display_path, layer=layer, reexport_map=reexport_map
            )
            result.ir.extend(file_result.ir)
            result.diagnostics.extend(file_result.diagnostics)
    return result


@dataclass(frozen=True)
class _ClassInfo:
    node: ast.ClassDef


class _DefinitionCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.definitions: list[_FunctionInfo] = []
        self.class_definitions: list[_ClassInfo] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.definitions.append(_FunctionInfo(node=node))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.definitions.append(_FunctionInfo(node=node))
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_definitions.append(_ClassInfo(node=node))
        # still recurse so method definitions inside classes are visited for function lifting
        self.generic_visit(node)


def _entry_for_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    rel_path: str,
    lines: list[str],
    diagnostics: list[Json],
) -> Json:
    shape_result = _function_shape_with_bindings(node, lines)
    term_shape = shape_result.shape
    param_names = _signature_param_names(node.args)
    witnesses = []
    witnesses.extend(_contract_comment_witnesses(lines, node, rel_path, diagnostics))
    witnesses.extend(
        _decorator_contract_witnesses(node, param_names, rel_path, diagnostics)
    )

    # Source-language signature types are diagnostic sidecar metadata only; they
    # do not participate in the CID-bearing term shape.
    realize_param_types = [
        _annotation_surface(arg.annotation) or ""
        for arg in _ordered_signature_args(node.args)
    ]
    realize_return_type = _annotation_surface(node.returns) or ""

    return {
        "kind": "bind-lift-entry",
        "param_names": param_names,
        "term_shape": term_shape,
        "term_shape_cid": cid_of_json(term_shape),
        "operand_bindings": shape_result.operand_bindings,
        "realize_param_types": realize_param_types,
        "realize_return_type": realize_return_type,
        "source_function_name": node.name,
        "witnesses": witnesses,
    }


def _derive_symbol(rel_path: str, function_name: str) -> str | None:
    """Derive the fully-qualified symbol for an UNTAGGED function from its file
    position — the zero-code-changes path: `pkg/mod.py::f` -> `pkg.mod.f`,
    `pkg/__init__.py::f` -> `pkg.f`. The module path IS the qualifier, the
    package IS the library, the function name IS the symbol; nothing declared."""
    path = rel_path.replace("\\", "/")
    if not path.endswith(".py"):
        return None
    parts = [p for p in path[:-3].split("/") if p and p != "."]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    module = ".".join(parts)
    return f"{module}.{function_name}" if module else function_name


def _module_file(root: Path, module: str) -> Path | None:
    module_path = root.joinpath(*module.split("."))
    package_init = module_path / "__init__.py"
    if package_init.is_file():
        return package_init
    file_path = module_path.with_suffix(".py")
    if file_path.is_file():
        return file_path
    return None


def _literal_all_exports(root: Path, module: str) -> list[str]:
    file_path = _module_file(root, module)
    if file_path is None:
        return []
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (OSError, SyntaxError):
        return []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            return []
        if isinstance(value, (list, tuple)) and all(
            isinstance(item, str) for item in value
        ):
            return list(value)
        return []
    return []


def _relative_import_target(current_module: str, node: ast.ImportFrom) -> str | None:
    if node.level != 1 or not node.module:
        return None
    return f"{current_module}.{node.module}" if current_module else node.module


def _package_import_target(
    package: str, current_module: str, node: ast.ImportFrom
) -> str | None:
    if node.level:
        current_parts = [p for p in current_module.split(".") if p]
        parent_parts = current_parts[: max(0, len(current_parts) - node.level + 1)]
        if node.module:
            parent_parts.append(node.module)
        return ".".join(part for part in parent_parts if part)
    module = node.module or ""
    if module == package:
        return ""
    prefix = f"{package}."
    if module.startswith(prefix):
        return module[len(prefix) :]
    return None


def _join_symbol(prefix: str, name: str) -> str:
    return f"{prefix}.{name}" if prefix else name


def _module_name_for_package_file(root: Path, path: Path) -> str | None:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    rel_text = rel.as_posix()
    if rel_text == "__init__.py":
        return ""
    if rel_text.endswith("/__init__.py"):
        return rel_text[: -len("/__init__.py")].replace("/", ".")
    if rel_text.endswith(".py"):
        return rel_text[:-3].replace("/", ".")
    return None


def _is_private_public_symbol(symbol: str) -> bool:
    return any(part.startswith("_") for part in symbol.split(".") if part)


def _public_symbol_score(public_symbol: str, package: str) -> tuple[int, int, str]:
    suffix = (
        public_symbol[len(package) + 1 :]
        if public_symbol.startswith(f"{package}.")
        else public_symbol
    )
    parts = [part for part in suffix.split(".") if part]
    if any(part.startswith("_") for part in parts):
        family = 100
    elif len(parts) == 1:
        family = 0
    elif parts and parts[0] == "api":
        family = 1
    elif parts and parts[0] in {"arrays", "io", "tseries"}:
        family = 2
    elif parts and parts[0] == "core":
        family = 20
    else:
        family = 10
    return (family, len(parts), public_symbol)


def _record_public_mapping(
    mapping: dict[str, tuple[str, str]],
    source_symbol: str,
    package: str,
    public_symbol: str,
) -> None:
    existing = mapping.get(source_symbol)
    candidate = (package, public_symbol)
    if existing is None or _public_symbol_score(
        public_symbol, package
    ) < _public_symbol_score(existing[1], package):
        mapping[source_symbol] = candidate


def _alias_chain(
    aliases: dict[str, str],
    source_symbol: str,
) -> list[str]:
    chain = [source_symbol]
    seen = {source_symbol}
    cursor = source_symbol
    while cursor in aliases:
        cursor = aliases[cursor]
        if cursor in seen:
            break
        chain.append(cursor)
        seen.add(cursor)
    return chain


def _public_reexport_map(workspace_root: Path) -> dict[str, tuple[str, str]] | None:
    """Build the PUBLIC re-export map for a package being universal-lifted.

    When lifting an installed library (e.g. `--project <site-packages>/numpy`),
    a module-level function lives at a private source path
    (`lib/_function_base_impl.py::rot90`) whose DERIVED symbol is the
    source-path symbol (`lib._function_base_impl.rot90`). But materialize /
    recognize match on the PUBLIC symbol (`numpy.rot90`, the name a consumer
    actually calls). The public name is whatever the package's top-level
    `__init__.py` re-exports it as: `from .lib._function_base_impl import rot90`
    publishes `rot90` at `<package>.rot90`.

    This reads the package's declared `__init__.py` re-export chain and returns
    a map keyed by the SOURCE-PATH symbol the lifter derives, valued by the PUBLIC
    `(library_tag, public_symbol)` pair:

      `lib._function_base_impl.rot90` -> (`numpy`, `numpy.rot90`)

    Nothing is hard-coded: the package name is the root directory's name, and every
    name is DERIVED from package-authored imports. Public names come from package
    `__init__.py` files (`pandas`, `pandas.api.indexers`, ...). Their targets may
    pass through package-authored aggregator modules (`pandas.core.api`) before
    reaching the source definition. Both relative imports and absolute
    same-package imports are accepted; imports from other packages are ignored.
    Star imports are followed only when the target module has a literal
    string-list `__all__`. Returns None when the root is not a package (no
    `__init__.py`), leaving the source-path symbol untouched (the existing
    in-project behavior).
    """
    root = workspace_root
    init_path = root / "__init__.py"
    if not init_path.is_file():
        return None
    package = root.name
    if not package:
        return None
    mapping: dict[str, tuple[str, str]] = {}
    aliases: dict[str, str] = {}
    public_aliases: set[str] = set()
    for current_file in sorted(root.rglob("*.py")):
        current_module = _module_name_for_package_file(root, current_file)
        if current_module is None:
            continue
        try:
            current_src = current_file.read_text(encoding="utf-8")
            current_tree = ast.parse(current_src, filename=str(current_file))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(current_tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            target_module = _package_import_target(package, current_module, node)
            if target_module is None:
                continue
            for alias in node.names:
                export_names = (
                    _literal_all_exports(root, target_module)
                    if alias.name == "*"
                    else [alias.name]
                )
                for source_name in export_names:
                    public_name = (
                        source_name if alias.name == "*" else alias.asname or alias.name
                    )
                    source_symbol = _join_symbol(target_module, source_name)
                    alias_symbol = _join_symbol(current_module, public_name)
                    aliases.setdefault(alias_symbol, source_symbol)
                    if (
                        current_file.name == "__init__.py"
                        and not _is_private_public_symbol(alias_symbol)
                    ):
                        public_aliases.add(alias_symbol)

    for public_alias in sorted(public_aliases):
        public_symbol = f"{package}.{public_alias}" if public_alias else package
        for source_symbol in _alias_chain(aliases, public_alias):
            _record_public_mapping(mapping, source_symbol, package, public_symbol)
    return mapping or None


def _library_binding_entry_for_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    rel_path: str,
    lines: list[str],
    source_lines: list[str],
    allow_derived: bool = False,
    reexport_map: dict[str, tuple[str, str]] | None = None,
) -> Json | None:
    binding = _sugar_bind_decorator(node)
    if binding is None:
        # Every MODULE-LEVEL function IS sugar. No @sugar.bind required — the tag
        # is gone; the symbol is DERIVED from the qualified module path + function
        # name (`pkg/mod.py::f` -> `pkg.mod.f`). This is the zero-code-changes
        # product: write a function, it's sugar. Gated to the `library-bindings`
        # layer (where sugar lives) — the general `all` contract path is
        # unaffected. Methods/nested defs (col_offset != 0) skipped for now.
        if not allow_derived:
            return None
        if node.col_offset != 0:
            return None
        symbol = _derive_symbol(rel_path, node.name)
        if symbol is None:
            return None
        # Default: the source-path symbol IS the library symbol, the first
        # segment IS the library tag (in-project, zero-config behavior). When the
        # package re-exports this function publicly (`from .lib._function_base_impl
        # import rot90` in numpy's `__init__`), promote BOTH to the public form so
        # materialize/recognize match on the symbol a consumer actually calls
        # (`numpy.rot90`) and resolution keys the library by its real package
        # (`numpy`), not the private source segment (`lib`). The body still
        # resolves from the SourceMemento's real locus (unchanged below).
        library_tag = symbol.split(".", 1)[0]
        public = reexport_map.get(symbol) if reexport_map else None
        if public is not None:
            library_tag, symbol = public
        binding = {
            "op_cid": _local_op_cid(symbol),
            "symbol": symbol,
            "target_library_tag": library_tag,
            "binding_origin": "derived",
        }

    shape_result = _function_shape_with_bindings(node, lines)
    term_shape = shape_result.shape
    param_names = _signature_param_names(node.args)
    param_types = [
        _annotation_surface(arg.annotation)
        for arg in _ordered_signature_args(node.args)
    ]
    return_type = _annotation_surface(node.returns)
    signature_shape = {
        "param_names": param_names,
        "param_types": param_types,
        "return_type": return_type,
    }
    # The proof carries the SourceMemento ONLY (locus + cids). The body never
    # enters the `.proof`; the Source Oracle reconstructs it from disk on demand.
    body_source = source_memento_of(_body_source_locator(node, rel_path, source_lines))
    loss_entries = binding.get("loss") or []

    entry: Json = {
        "body_source": body_source,
        "kind": "library-sugar-binding-entry",
        "loss_record_contribution": {
            "form": "literal",
            "value": {"entries": loss_entries},
        },
        "param_names": param_names,
        "param_types": param_types,
        "return_type": return_type,
        "signature_shape_cid": cid_of_json(signature_shape),
        "source_function_name": node.name,
        "target_language": "python",
        "target_library_tag": binding["target_library_tag"],
        "term_shape": term_shape,
        "term_shape_cid": cid_of_json(term_shape),
    }
    # Symbol-keyed identity remains the public join key when a library symbol
    # exists. Operator identity travels as op_cid, derived from the declared
    # op shape when an authoring concept is the only local handle.
    symbol = binding.get("symbol")
    if symbol:
        entry["symbol"] = symbol
    op_cid = binding.get("op_cid")
    if op_cid:
        entry["op_cid"] = op_cid
    # Provenance: `derived` marks a zero-code universal-lift binding (no
    # @sugar.bind), distinct from a `declared` one. Emitted only when derived,
    # so tagged shims stay byte-identical. Lets recognize keep the project's own
    # functions out of the published match-template set.
    binding_origin = binding.get("binding_origin")
    if binding_origin:
        entry["binding_origin"] = binding_origin
    observed = binding.get("observed_dimension")
    if observed:
        entry["observed_dimension"] = observed
    # #1357 / #1355: surface optional family + library_version pins on the
    # binding entry. Absent on the @sugar.bind decorator → absent in the
    # emitted JSON (NOT empty strings — null/missing is the substrate
    # signal for "this axis floats"). Parallel to walk_rpc + TS lifter.
    family = binding.get("family")
    if family:
        entry["family"] = family
    library_version = binding.get("library_version")
    if library_version:
        entry["library_version"] = library_version
    return entry


def _sugar_bind_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict | None:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not _is_sugar_bind_func(
            decorator.func
        ):
            continue
        concept = _keyword_str(decorator, "concept")
        library = _keyword_str(decorator, "library")
        symbol = _keyword_str(decorator, "symbol")
        op_cid = _keyword_str(decorator, "op_cid")
        # Symbol-keyed identity is the public library path (e.g. `numpy.add`).
        # If an authoring concept is present, derive only the canonical op_cid;
        # the concept string is not transported as identity.
        if library and (symbol or op_cid or concept):
            result: dict = {"target_library_tag": library}
            if symbol:
                result["symbol"] = symbol
            result_op_cid = op_cid or (_local_op_cid(concept) if concept else None)
            if result_op_cid:
                result["op_cid"] = result_op_cid
            loss = _keyword_str_list(decorator, "loss")
            if loss is not None:
                result["loss"] = loss
            observed = _keyword_str(decorator, "observed_dimension")
            if observed:
                result["observed_dimension"] = observed
            # #1357 / #1355: optional family + version pins, parallel to
            # the rust (walk_rpc) and typescript (typescript-source) lifters.
            # Both float when absent; dispatch downstream narrows via these
            # when present.
            family = _keyword_str(decorator, "family")
            if family:
                result["family"] = family
            version = _keyword_str(decorator, "version")
            if version:
                result["library_version"] = version
            return result
    return None


def _is_sugar_bind_func(func: ast.expr) -> bool:
    if not isinstance(func, ast.Attribute) or func.attr != "bind":
        return False
    value = func.value
    if isinstance(value, ast.Name):
        return value.id == "sugar"
    if isinstance(value, ast.Attribute) and value.attr == "sugar":
        return isinstance(value.value, ast.Name) and value.value.id == "sugar"
    return False


def _keyword_str(call: ast.Call, name: str) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            if isinstance(keyword.value.value, str) and keyword.value.value:
                return keyword.value.value
    return None


def _keyword_str_list(call: ast.Call, name: str) -> list[str] | None:
    """Return a keyword argument whose value is a list of string literals, or None if absent."""
    for keyword in call.keywords:
        if keyword.arg != name:
            continue
        if not isinstance(keyword.value, ast.List):
            return None
        result: list[str] = []
        for elt in keyword.value.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                result.append(elt.value)
        return result
    return None


# #3632: the source-level decorator that marks "this concept surface is
# uncovered, here is why, and what closing it would unlock" is spelled
# `@concept_gap(...)`. REFUSE is the verifier's verb, not the lifter's.
_CONCEPT_GAP_DECORATOR_NAMES = ("concept_gap",)


def _is_concept_gap_func(func: ast.expr) -> bool:
    """Return True for @concept_gap(...) or its @sugar.* form."""
    if isinstance(func, ast.Name):
        return func.id in _CONCEPT_GAP_DECORATOR_NAMES
    if isinstance(func, ast.Attribute) and func.attr in _CONCEPT_GAP_DECORATOR_NAMES:
        value = func.value
        return isinstance(value, ast.Name) and value.id == "sugar"
    return False


def _concept_gap_memento_for_class(
    node: ast.ClassDef,
    rel_path: str,
    diagnostics: list[Json],
) -> Json | None:
    """Emit a concept-gap-memento IR record for an empty class decorated with
    @concept_gap(...)."""
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not _is_concept_gap_func(
            decorator.func
        ):
            continue
        surface = _keyword_str(decorator, "surface")
        concept = _keyword_str(decorator, "concept")
        reason = _keyword_str(decorator, "reason")
        would_close = _keyword_str(decorator, "would_close_with_cluster")
        if not (surface and concept and reason and would_close):
            diagnostics.append(
                {
                    "kind": "concept-gap-memento-invalid",
                    "message": "missing required field in @concept_gap (surface, concept, reason, would_close_with_cluster)",
                    "path": rel_path,
                    "line": node.lineno,
                }
            )
            return None
        # Validate body is trivial (only pass or docstring)
        body_stmts = [s for s in node.body if not _is_docstring_stmt(s)]
        if len(body_stmts) > 1 or (
            len(body_stmts) == 1 and not isinstance(body_stmts[0], ast.Pass)
        ):
            diagnostics.append(
                {
                    "kind": "concept-gap-memento-invalid",
                    "message": "@concept_gap class body must be empty (pass only)",
                    "path": rel_path,
                    "line": node.lineno,
                }
            )
            return None
        return {
            "kind": "concept-gap-memento",
            "target_language": "python",
            "surface": surface,
            "concept": concept,
            "reason": reason,
            "would_close_with_cluster": would_close,
        }
    return None


def _ordered_signature_args(args: ast.arguments) -> list[ast.arg]:
    ordered_args: list[ast.arg] = []
    ordered_args.extend(args.posonlyargs)
    ordered_args.extend(args.args)
    if args.vararg is not None:
        ordered_args.append(args.vararg)
    ordered_args.extend(args.kwonlyargs)
    if args.kwarg is not None:
        ordered_args.append(args.kwarg)
    return ordered_args


def _annotation_surface(annotation: ast.expr | None) -> str | None:
    if annotation is None:
        return None
    return ast.unparse(annotation)


def _body_source_locator(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    rel_path: str,
    source_lines: list[str],
) -> Json:
    start_line = node.lineno
    start_col = node.col_offset
    if node.decorator_list:
        first = min(node.decorator_list, key=lambda decorator: decorator.lineno)
        start_line = first.lineno
        start_col = 0
    end_line = node.end_lineno or node.lineno
    end_col = node.end_col_offset or 0
    body_text = _extract_body_text(node, source_lines)
    ast_template = function_body_template(node)
    result: Json = {
        "file": rel_path,
        "source_cid": blake3_512_of(body_text.encode("utf-8")),
        "span": {
            "start_line": start_line,
            "start_col": start_col,
            "end_line": end_line,
            "end_col": end_col,
        },
        "template_cid": template_cid_of_json(ast_template),
        "param_names": function_param_names(node),
    }
    # `_body_source_locator` is the FULL reconstruction (locus + cids + body +
    # ast_template) -- this is what the Source Oracle returns when it resolves a
    # SourceMemento from disk. The MINT path strips body_text/ast_template to the
    # SourceMemento before anything enters the `.proof` (see `source_memento_of`);
    # the body NEVER touches the proof. No flag: the lean SourceMemento is the
    # only thing a proof ever carries.
    result["ast_template"] = ast_template
    if body_text:
        result["body_text"] = body_text
    return result


# The fields a `.proof` carries: locus + CIDs, ZERO content. The Source Oracle
# resolves body_text + ast_template from disk on demand, CID-verified.
_SOURCE_MEMENTO_FIELDS = ("file", "source_cid", "span", "template_cid", "param_names")


def source_memento_of(full_body_source: Json) -> Json:
    """Strip a full `_body_source_locator` reconstruction down to the SourceMemento
    the proof carries -- locus + CIDs, no body_text, no ast_template."""
    return {
        k: full_body_source[k] for k in _SOURCE_MEMENTO_FIELDS if k in full_body_source
    }


def _extract_body_text(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    source_lines: list[str],
) -> str:
    """Extract the text of the function body (excluding decorators and def line).

    Returns the dedented body text for use in body-templates projection.
    The body starts at node.body[0].lineno and ends at node.end_lineno.
    """
    if not node.body:
        return ""
    body_start = node.body[0].lineno
    body_end = node.end_lineno or body_start
    if body_start > len(source_lines) or body_end < body_start:
        return ""
    raw_lines = source_lines[body_start - 1 : body_end]
    if not raw_lines:
        return ""
    # Determine indentation from the first non-docstring statement
    indent = 0
    for stmt in node.body:
        if not _is_docstring_stmt(stmt):
            line_idx = stmt.lineno - 1
            if line_idx < len(source_lines):
                line = "".join(source_lines[line_idx])
                stripped = line.lstrip()
                if stripped:
                    indent = len(line) - len(stripped)
            break
    dedented = []
    for raw_line in raw_lines:
        text = "".join([raw_line]) if isinstance(raw_line, str) else raw_line
        if text.startswith(" " * indent):
            dedented.append(text[indent:])
        else:
            dedented.append(text.lstrip())
    return "".join(dedented).rstrip()


def _signature_param_names(args: ast.arguments) -> list[str]:
    names: list[str] = []
    for arg in _ordered_signature_args(args):
        names.append(arg.arg)
    return names


def _function_shape(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Json:
    return _function_shape_with_bindings(node).shape


def _function_shape_with_bindings(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    lines: list[str] | None = None,
) -> _ShapeResult:
    statements = [stmt for stmt in node.body if not _is_docstring_stmt(stmt)]
    comments = _trivia_comment_occurrences(lines, node) if lines is not None else []
    return _shape_block_with_bindings(statements, comments)


def _shape_block(statements: list[ast.stmt]) -> Json:
    return _shape_block_with_bindings(statements).shape


def _shape_block_with_bindings(
    statements: list[ast.stmt],
    comments: list[_CommentOccurrence] | None = None,
) -> _ShapeResult:
    shapes: list[Json] = []
    binding_groups: list[list[Json]] = []
    leaf_only: _ShapeResult | None = None
    pending_comments = sorted(comments or [], key=lambda comment: comment.line_no)
    comment_index = 0
    for stmt in statements:
        if _is_docstring_stmt(stmt):
            continue
        stmt_line = getattr(stmt, "lineno", 0)
        while (
            comment_index < len(pending_comments)
            and pending_comments[comment_index].line_no < stmt_line
        ):
            comment = pending_comments[comment_index]
            shapes.append(_comment_shape(comment.surface))
            binding_groups.append([])
            comment_index += 1
        candidate = _shape_stmt_with_bindings(stmt, top_level=False)
        shape = candidate.shape
        if _shape_has_operator_identity(shape):
            shapes.append(shape)
            binding_groups.append(candidate.operand_bindings)
        elif leaf_only is None and candidate.operand_bindings:
            leaf_only = candidate
    while comment_index < len(pending_comments):
        comment = pending_comments[comment_index]
        shapes.append(_comment_shape(comment.surface))
        binding_groups.append([])
        comment_index += 1
    if not shapes and leaf_only is not None:
        return _ShapeResult({}, _sort_operand_bindings(leaf_only.operand_bindings))
    return _collapse_operation_shape_results(shapes, binding_groups)


def _shape_stmt(node: ast.stmt, *, top_level: bool) -> Json:
    return _shape_stmt_with_bindings(node, top_level=top_level).shape


def _shape_stmt_with_bindings(node: ast.stmt, *, top_level: bool) -> _ShapeResult:
    if isinstance(node, ast.If):
        test = _shape_expr_with_bindings(node.test)
        body = _shape_block_with_bindings(node.body)
        orelse = _shape_block_with_bindings(node.orelse)
        return _operator_shape_result(
            "concept:conditional",
            [test, body, orelse],
        )
    if isinstance(node, ast.While):
        return _operator_shape_result(
            "concept:while",
            [
                _shape_expr_with_bindings(node.test),
                _shape_block_with_bindings(node.body),
            ],
        )
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return _operator_shape_result(
            "concept:for", [_shape_block_with_bindings(node.body)]
        )
    if isinstance(node, ast.Return):
        if node.value is None:
            return _empty_shape_result()
        return _shape_expr_with_bindings(node.value)
    if isinstance(node, ast.Pass):
        return _operator_shape_result("concept:skip", [])
    if isinstance(node, ast.Break):
        return _operator_shape_result("concept:break", [])
    if isinstance(node, ast.Continue):
        return _operator_shape_result("concept:continue", [])
    if isinstance(node, ast.Assign):
        target = (
            _shape_expr_with_bindings(node.targets[0])
            if node.targets
            else _empty_shape_result()
        )
        return _operator_shape_result(
            "concept:assign", [target, _shape_expr_with_bindings(node.value)]
        )
    if isinstance(node, ast.AnnAssign):
        if node.value is not None:
            return _operator_shape_result(
                "concept:assign",
                [
                    _shape_expr_with_bindings(node.target),
                    _shape_expr_with_bindings(node.value),
                ],
            )
        return _empty_shape_result()
    if isinstance(node, ast.AugAssign):
        return _bin_operator_shape_result(
            node.op,
            [
                _shape_expr_with_bindings(node.target),
                _shape_expr_with_bindings(node.value),
            ],
        )
    if isinstance(node, ast.Expr):
        return _shape_expr_with_bindings(node.value)
    return _empty_shape_result()


def _shape_expr(node: ast.expr) -> Json:
    return _shape_expr_with_bindings(node).shape


def _shape_expr_with_bindings(node: ast.expr) -> _ShapeResult:
    if isinstance(node, ast.BinOp):
        return _bin_operator_shape_result(
            node.op,
            [
                _shape_expr_with_bindings(node.left),
                _shape_expr_with_bindings(node.right),
            ],
        )
    if isinstance(node, ast.BoolOp):
        op = _bool_op(node.op)
        values = [_shape_expr_with_bindings(value) for value in node.values]
        if op is None:
            return _empty_shape_result()
        return _operator_shape_result(op, values)
    if isinstance(node, ast.UnaryOp):
        op = _unary_op(node.op)
        if op is None:
            return _empty_shape_result()
        return _operator_shape_result(op, [_shape_expr_with_bindings(node.operand)])
    if isinstance(node, ast.IfExp):
        return _operator_shape_result(
            "concept:conditional",
            [
                _shape_expr_with_bindings(node.test),
                _shape_expr_with_bindings(node.body),
                _shape_expr_with_bindings(node.orelse),
            ],
        )
    if isinstance(node, ast.Compare):
        return _compare_shape_result(node)
    if isinstance(node, ast.Call):
        args = [_shape_expr_with_bindings(node.func)]
        args.extend(_shape_expr_with_bindings(arg) for arg in node.args)
        args.extend(
            _shape_expr_with_bindings(keyword.value) for keyword in node.keywords
        )
        return _operator_shape_result("concept:call", args)
    symbol = _operand_symbol(node)
    if symbol is not None:
        return _ShapeResult({}, [{"position": [], "symbol": symbol}])
    return _empty_shape_result()


def _shape_has_operator_identity(value: Json) -> bool:
    if isinstance(value, dict):
        if "op_cid" in value:
            return True
        return any(_shape_has_operator_identity(child) for child in value.values())
    if isinstance(value, list):
        return any(_shape_has_operator_identity(child) for child in value)
    return False


def _collapse_operation_shapes(shapes: list[Json]) -> Json:
    if not shapes:
        return {}
    if len(shapes) == 1:
        return shapes[0]
    return _operator_shape("concept:seq", shapes)


def _collapse_operation_shape_results(
    shapes: list[Json],
    binding_groups: list[list[Json]],
) -> _ShapeResult:
    if not shapes:
        return _empty_shape_result()
    if len(shapes) == 1:
        return _ShapeResult(shapes[0], _sort_operand_bindings(binding_groups[0]))
    bindings: list[Json] = []
    for index, group in enumerate(binding_groups):
        bindings.extend(_prefix_bindings(group, index))
    return _ShapeResult(
        _operator_shape("concept:seq", shapes),
        _sort_operand_bindings(bindings),
    )


def _bin_operator_shape(op: ast.operator, args: list[Json]) -> Json:
    atom = _bin_op(op)
    if atom is None:
        return {}
    return _operator_shape(atom, args)


def _bin_operator_shape_result(
    op: ast.operator, args: list[_ShapeResult]
) -> _ShapeResult:
    atom = _bin_op(op)
    if atom is None:
        return _empty_shape_result()
    return _operator_shape_result(atom, args)


def _compare_shape_result(node: ast.Compare) -> _ShapeResult:
    if not node.ops or len(node.ops) != len(node.comparators):
        return _empty_shape_result()
    operands: list[ast.expr] = [node.left, *node.comparators]
    comparisons: list[_ShapeResult] = []
    for index, raw_op in enumerate(node.ops):
        op = _rel_op(raw_op)
        if op is None:
            return _empty_shape_result()
        comparisons.append(
            _operator_shape_result(
                op,
                [
                    _shape_expr_with_bindings(operands[index]),
                    _shape_expr_with_bindings(operands[index + 1]),
                ],
            )
        )
    result = comparisons[0]
    for comparison in comparisons[1:]:
        result = _operator_shape_result(
            "concept:ite", [result, comparison, _bool_literal(False)]
        )
    return result


def _bool_literal(value: bool) -> _ShapeResult:
    return _ShapeResult({}, [{"position": [], "symbol": "True" if value else "False"}])


def _operator_shape(operator: str, args: list[Json]) -> Json:
    return {
        "args": [_operand_slot(arg) for arg in args],
        "op_cid": _local_op_cid(operator),
    }


def _comment_shape(surface: str) -> Json:
    return {
        "args": [{"kind": "literal", "value": surface}],
        "op_cid": _local_op_cid("concept:comment"),
    }


def _operator_shape_result(operator: str, args: list[_ShapeResult]) -> _ShapeResult:
    shape = _operator_shape(operator, [arg.shape for arg in args])
    if not shape:
        return _empty_shape_result()
    bindings: list[Json] = []
    for index, arg in enumerate(args):
        bindings.extend(_prefix_bindings(arg.operand_bindings, index))
    return _ShapeResult(shape, _sort_operand_bindings(bindings))


def _empty_shape_result() -> _ShapeResult:
    return _ShapeResult({}, [])


def _prefix_bindings(bindings: list[Json], prefix: int) -> list[Json]:
    return [
        {"position": [prefix, *binding["position"]], "symbol": binding["symbol"]}
        for binding in bindings
    ]


def _sort_operand_bindings(bindings: list[Json]) -> list[Json]:
    return sorted(bindings, key=lambda binding: binding["position"])


def _operand_symbol(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return repr(value)
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)
        if value is None:
            return "None"
    return None


def _operand_slot(value: Json) -> Json:
    if (
        isinstance(value, dict)
        and isinstance(value.get("op_cid"), str)
        and isinstance(value.get("args"), list)
    ):
        return value
    if isinstance(value, dict) and (
        value.get("kind") in {"literal", "const"} or "value" in value
    ):
        return value
    return {}


def _bin_op(op: ast.operator) -> str | None:
    table: tuple[tuple[type[ast.operator], str], ...] = (
        (ast.Add, "concept:add"),
        (ast.Sub, "concept:sub"),
        (ast.Mult, "concept:mul"),
        (ast.Div, "concept:div"),
        (ast.Mod, "concept:mod"),
        (ast.LShift, "concept:shl"),
        (ast.RShift, "concept:shr"),
        (ast.BitAnd, "concept:bitand"),
        (ast.BitOr, "concept:bitor"),
        (ast.BitXor, "concept:bitxor"),
    )
    for cls, operator in table:
        if isinstance(op, cls):
            return operator
    return None


def _bool_op(op: ast.boolop) -> str | None:
    if isinstance(op, ast.And):
        return "concept:and"
    if isinstance(op, ast.Or):
        return "concept:or"
    return None


def _unary_op(op: ast.unaryop) -> str | None:
    if isinstance(op, ast.Not):
        return "concept:not"
    if isinstance(op, ast.USub):
        return "concept:neg"
    if isinstance(op, ast.Invert):
        return "concept:bitnot"
    return None


def _rel_op(op: ast.cmpop) -> str | None:
    table: tuple[tuple[type[ast.cmpop], str], ...] = (
        (ast.Eq, "concept:eq"),
        (ast.NotEq, "concept:ne"),
        (ast.Lt, "concept:lt"),
        (ast.LtE, "concept:le"),
        (ast.Gt, "concept:gt"),
        (ast.GtE, "concept:ge"),
    )
    for cls, operator in table:
        if isinstance(op, cls):
            return operator
    return None


def _contract_comment_witnesses(
    lines: list[str],
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    rel_path: str,
    diagnostics: list[Json],
) -> list[Json]:
    witnesses: list[Json] = []
    witnesses.extend(
        _contract_comment_witnesses_from_surface_lines(
            _leading_contract_comment_surface(lines, node.lineno),
            rel_path,
            diagnostics,
        )
    )
    docstring = ast.get_docstring(node, clean=True)
    if docstring:
        doc_lines = [
            (getattr(node.body[0], "lineno", node.lineno), line.strip())
            for line in docstring.splitlines()
        ]
        witnesses.extend(
            _contract_comment_witnesses_from_surface_lines(
                doc_lines,
                rel_path,
                diagnostics,
            )
        )
    return witnesses


def _leading_contract_comment_surface(
    lines: list[str],
    fn_line: int,
) -> list[tuple[int, str]]:
    start = fn_line - 2
    while start >= 0:
        stripped = lines[start].strip()
        if stripped == "" or stripped.startswith("#") or stripped.startswith("@"):
            start -= 1
            continue
        break
    surface: list[tuple[int, str]] = []
    for idx in range(start + 1, fn_line - 1):
        stripped = lines[idx].strip()
        if stripped.startswith("#"):
            surface.append((idx + 1, stripped[1:].strip()))
    return surface


def _contract_comment_witnesses_from_surface_lines(
    surface_lines: list[tuple[int, str]],
    rel_path: str,
    diagnostics: list[Json],
) -> list[Json]:
    witnesses: list[Json] = []
    idx = 0
    while idx < len(surface_lines):
        line_no, content = surface_lines[idx]
        if not content.startswith("sugar-contract:"):
            idx += 1
            continue
        raw_payload = content[len("sugar-contract:") :].strip()
        payload_cid: str | None = None
        if idx + 1 < len(surface_lines):
            _, next_content = surface_lines[idx + 1]
            if next_content.startswith("sugar-contract-payload-cid:"):
                payload_cid = next_content[len("sugar-contract-payload-cid:") :].strip()
                idx += 1
        witness = _contract_comment_witness(
            raw_payload,
            payload_cid,
            rel_path,
            line_no,
            diagnostics,
        )
        if witness is not None:
            witnesses.append(witness)
        idx += 1
    return witnesses


def _contract_comment_witness(
    raw_payload: str,
    emitted_payload_cid: str | None,
    rel_path: str,
    line_no: int,
    diagnostics: list[Json],
) -> Json | None:
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        _contract_comment_diag(
            diagnostics,
            rel_path,
            line_no,
            f"malformed JSON: {exc.msg}",
        )
        return None
    if not isinstance(payload, dict):
        _contract_comment_diag(
            diagnostics, rel_path, line_no, "payload is not an object"
        )
        return None

    def require_str(key: str) -> str | None:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
        _contract_comment_diag(diagnostics, rel_path, line_no, f"missing {key}")
        return None

    if payload.get("artifact_kind") != CONTRACT_COMMENT_KIND:
        _contract_comment_diag(diagnostics, rel_path, line_no, "wrong artifact_kind")
        return None
    if payload.get("schema_version") != "1":
        _contract_comment_diag(diagnostics, rel_path, line_no, "unknown schema_version")
        return None

    fol_text = require_str("fol_text")
    if fol_text is None:
        return None

    emitted_by = payload.get("emitted_by")
    if not _valid_emitted_by(emitted_by):
        _contract_comment_diag(diagnostics, rel_path, line_no, "malformed emitted_by")
        return None

    role = require_str("role")
    if role not in CONTRACT_COMMENT_ROLE_MAP:
        _contract_comment_diag(diagnostics, rel_path, line_no, "unknown role")
        return None

    cid_fields = [
        "concept_site_cid",
        "contract_cid",
        "ir_formula_jcs_cid",
        "loss_record_cid",
        "policy_cid",
        "sugar_dict_cid",
    ]
    for key in cid_fields:
        value = require_str(key)
        if value is None or not CID_RE.fullmatch(value):
            _contract_comment_diag(diagnostics, rel_path, line_no, f"malformed {key}")
            return None
    local_contract_cid = payload.get("local_contract_cid")
    if local_contract_cid is not None and (
        not isinstance(local_contract_cid, str)
        or not CID_RE.fullmatch(local_contract_cid)
    ):
        _contract_comment_diag(
            diagnostics, rel_path, line_no, "malformed local_contract_cid"
        )
        return None

    predicate = payload.get("ir_formula_jcs")
    if not isinstance(predicate, dict):
        _contract_comment_diag(diagnostics, rel_path, line_no, "missing ir_formula_jcs")
        return None
    if not _valid_formula_shape(predicate):
        _contract_comment_diag(diagnostics, rel_path, line_no, "invalid formula shape")
        return None
    if cid_of_json(predicate) != payload["ir_formula_jcs_cid"]:
        _contract_comment_diag(diagnostics, rel_path, line_no, "formula CID mismatch")
        return None

    payload_cid = cid_of_json(payload)
    if emitted_payload_cid is not None and not CID_RE.fullmatch(emitted_payload_cid):
        _contract_comment_diag(diagnostics, rel_path, line_no, "malformed payload CID")
        return None
    if emitted_payload_cid is not None and emitted_payload_cid != payload_cid:
        _contract_comment_diag(diagnostics, rel_path, line_no, "payload CID mismatch")
        return None

    extension_fields = {
        "concept_site_cid": payload["concept_site_cid"],
        "contract_cid": payload["contract_cid"],
        "ir_formula_jcs_cid": payload["ir_formula_jcs_cid"],
        "loss_record_cid": payload["loss_record_cid"],
        "payload_cid": payload_cid,
        "policy_cid": payload["policy_cid"],
        "sugar_dict_cid": payload["sugar_dict_cid"],
        "surface": "contract-comment-sugar",
    }
    if isinstance(local_contract_cid, str):
        extension_fields["local_contract_cid"] = local_contract_cid
    return {
        "confidence_basis_points": 10000,
        "extension_fields": extension_fields,
        "predicate": predicate,
        "predicate_text": fol_text,
        "role": CONTRACT_COMMENT_ROLE_MAP[role],
        "source_kind": "native-surface",
    }


def _function_body_comment_surface(
    lines: list[str],
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[int, str]]:
    end_lineno = getattr(node, "end_lineno", node.lineno)
    surface: list[tuple[int, str]] = []
    for idx in range(node.lineno, min(end_lineno, len(lines))):
        stripped = lines[idx].strip()
        if stripped.startswith("#"):
            surface.append((idx + 1, stripped[1:].strip()))
    return surface


def _trivia_comment_occurrences(
    lines: list[str],
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[_CommentOccurrence]:
    end_lineno = getattr(node, "end_lineno", node.lineno)
    occurrences: list[_CommentOccurrence] = []
    for idx in range(node.lineno, min(end_lineno, len(lines))):
        stripped = lines[idx].strip()
        if not stripped.startswith("#"):
            continue
        surface = stripped[1:].strip()
        if _is_sugar_comment_carrier(surface):
            continue
        occurrences.append(_CommentOccurrence(line_no=idx + 1, surface=surface))
    return occurrences


def _is_sugar_comment_carrier(surface: str) -> bool:
    normalized = surface.strip()
    carrier_prefixes = (
        "sugar:concept:",
        "sugar:concept-payload-cid:",
        "sugar-concept:",
        "sugar-concept-payload-cid:",
        "sugar-contract:",
        "sugar-contract-payload-cid:",
    )
    return any(normalized.startswith(prefix) for prefix in carrier_prefixes)


def _local_op_cid(name: str) -> str:
    return cid_of_json(
        {"kind": "local-operator", "name": name.removeprefix("concept:")}
    )


def _valid_emitted_by(value: Json) -> bool:
    if not isinstance(value, dict):
        return False
    kit_cid = value.get("kit_cid")
    kit_kind = value.get("kit_kind")
    target_language = value.get("target_language")
    return (
        isinstance(kit_cid, str)
        and CID_RE.fullmatch(kit_cid) is not None
        and isinstance(kit_kind, str)
        and bool(kit_kind)
        and isinstance(target_language, str)
        and bool(target_language)
    )


def _valid_formula_shape(formula: Json) -> bool:
    if not isinstance(formula, dict):
        return False
    kind = formula.get("kind")
    if kind == "atomic":
        return isinstance(formula.get("name"), str) and isinstance(
            formula.get("args"),
            list,
        )
    if kind in {"and", "or", "not", "implies"}:
        operands = formula.get("operands")
        return isinstance(operands, list) and all(
            _valid_formula_shape(operand) for operand in operands
        )
    if kind in {"forall", "exists"}:
        return (
            isinstance(formula.get("name"), str)
            and isinstance(formula.get("sort"), dict)
            and _valid_formula_shape(formula.get("body"))
        )
    return False


def _contract_comment_diag(
    diagnostics: list[Json],
    rel_path: str,
    line_no: int,
    message: str,
) -> None:
    diagnostics.append(
        {
            "kind": "contract-comment-invalid",
            "message": message,
            "path": rel_path,
            "line": line_no,
        }
    )


def _decorator_contract_witnesses(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    param_names: list[str],
    rel_path: str,
    diagnostics: list[Json],
) -> list[Json]:
    witnesses: list[Json] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if _decorator_name(decorator.func) not in {"contract", "sugar_contract"}:
            continue
        for keyword in decorator.keywords:
            role = {"pre": "pre", "post": "post", "inv": "inv"}.get(keyword.arg or "")
            if role is None or not isinstance(keyword.value, ast.Constant):
                continue
            if not isinstance(keyword.value.value, str):
                continue
            text = keyword.value.value
            try:
                from sugar_lift_py_tests.canonicalizer import encode_jcs
                from sugar_lift_py_tests.contract_expression import (
                    parse_contract_expression,
                )
                from sugar_lift_py_tests.ir import formula_to_value

                names = [*param_names, "out"] if role == "post" else param_names
                formula = parse_contract_expression(text, names)
                predicate = json.loads(encode_jcs(formula_to_value(formula)))
            except Exception as exc:
                diagnostics.append(
                    {
                        "kind": "decorator-contract-invalid",
                        "message": str(exc),
                        "path": rel_path,
                        "line": getattr(decorator, "lineno", node.lineno),
                    }
                )
                continue
            witnesses.append(
                {
                    "confidence_basis_points": 10000,
                    "extension_fields": {
                        "decorator": _decorator_name(decorator.func),
                        "surface": "python-decorator-contract",
                    },
                    "predicate": predicate,
                    "predicate_text": text,
                    "role": role,
                    "source_kind": "native-surface",
                }
            )
    return witnesses


def _decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _iter_python_files(path: Path) -> Iterable[Path]:
    if path.is_dir():
        yield from sorted(p for p in path.rglob("*.py") if p.is_file())
    elif path.is_file() and path.suffix == ".py":
        yield path


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_docstring_stmt(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )

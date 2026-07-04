from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys
import traceback
from typing import Any

from .ast_template import expr_to_template, function_body_template, function_param_names
from .bind_effects import (
    BoundaryBodyShapeEffect,
    MissingBindingEffect,
    bind_effect_result,
)
from .bind_lifter import lift_paths
from .canonical import template_cid_of_json

VERSION = "0.1.0"
SURFACE = "python-bind"
KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"


def initialize_result() -> dict[str, Any]:
    return {
        "name": "sugar-lift-python-bind",
        "version": VERSION,
        "protocol_version": "pep/1.7.0",
        "capabilities": {
            "authoring_surfaces": ["python", "python-bind"],
            "ir_version": "bind-ir/1.0.0",
            "emits_signed_mementos": False,
        },
    }


def kit_declaration_result() -> dict[str, Any]:
    return {
        "kit": {
            "id": SURFACE,
            "language": "python",
            "version": VERSION,
        },
        "rpc": {
            "methods": [
                {"name": "initialize", "required": True},
                {"name": KIT_DECLARATION_RPC_METHOD, "required": True},
                {"name": "lift", "required": True},
                {"name": "sugar.plugin.recognize", "required": True},
                {"name": "shutdown", "required": False},
            ]
        },
        "proofResolution": {"strategy": "pip"},
        "effectKinds": [],
        "effectLeaves": [],
        "guardPredicates": [],
        "controlCarriers": [],
        "residueCategories": [],
    }


def run_rpc() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = dispatch(request)
        except json.JSONDecodeError as exc:
            response = _error(None, -32700, f"PARSE_ERROR: {exc}")
        except Exception as exc:
            response = _error(None, -32603, f"{exc}\n{traceback.format_exc()}")
        _send(response)


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    msg_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params") or {}

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": initialize_result()}
    if method == KIT_DECLARATION_RPC_METHOD:
        return {"jsonrpc": "2.0", "id": msg_id, "result": kit_declaration_result()}
    if method == "lift":
        return _lift(msg_id, params)
    if method == "sugar.plugin.recognize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": recognize_impl(params),
        }
    if method == "sugar.plugin.materialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": materialize_impl(params),
        }
    if method == "shutdown":
        return {"jsonrpc": "2.0", "id": msg_id, "result": None}
    return _error(msg_id, -32601, f"METHOD_NOT_FOUND: {method}")


def _lift(msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    source_paths = params.get("source_paths")
    paths: list[str]
    if isinstance(source_paths, list):
        paths = [str(path) for path in source_paths if str(path)]
    else:
        paths = ["."]
    if not paths:
        paths = ["."]

    options_value = params.get("options")
    options = options_value if isinstance(options_value, dict) else {}
    # This kit IS the library-bindings (sugar) surface, so default to that layer
    # — which enables zero-code-changes universal lift (every module-level
    # function is sugar). The direct `lift_source(layer="all")` unit tests are
    # unaffected (they don't go through this RPC).
    layer = str(options.get("layer") or "library-bindings")
    result = lift_paths(str(params.get("workspace_root", ".")), paths, layer=layer)
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "kind": "ir-document",
            "ir": result.ir,
            "diagnostics": result.diagnostics,
        },
    }


def recognize_impl(params: dict[str, Any]) -> dict[str, Any]:
    project_root = params.get("project_root")
    if not isinstance(project_root, str) or not project_root:
        raise ValueError("missing `project_root`")
    source_paths = params.get("source_paths")
    if not isinstance(source_paths, list):
        raise ValueError("missing `source_paths` array")
    root = Path(project_root).resolve()

    binding_templates, sugar_template_files = _self_resolved_binding_templates(
        root, source_paths
    )

    bindings_by_cid: dict[str, dict[str, Any]] = {}
    for binding in binding_templates:
        if not isinstance(binding, dict):
            continue
        cid = binding.get("template_cid")
        if isinstance(cid, str) and cid:
            bindings_by_cid[cid] = binding

    tags: list[dict[str, Any]] = []
    for rel_path, full_path in _iter_requested_python_files(root, source_paths):
        if rel_path in sugar_template_files:
            continue
        try:
            source = full_path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError:
            continue
        file_exact_tags: list[dict[str, Any]] = []
        for node in _iter_candidate_functions(tree):
            tag = _recognize_function(rel_path, node, bindings_by_cid)
            if tag is not None:
                tags.append(tag)
                file_exact_tags.append(tag)
        # The body template matches anywhere: walk every call site and unify the
        # published sugar body pattern against it (param holes are wildcards),
        # not just whole top-level functions identical to the shim wrapper.
        # Skip call sites already covered by an exact whole-function match (same
        # recognition; the exact tag is richer), so we don't double-emit.
        tags.extend(
            _recognize_calls_anywhere(
                rel_path, tree, binding_templates, file_exact_tags
            )
        )
    return {"tags": tags}


def materialize_impl(params: dict[str, Any]) -> dict[str, Any]:
    """The Python materializer (lower-sugar). Finds functions tagged
    `@boundary(library="numpy", call="add")` and replaces their entire body with
    the matching sugar `body_text` resolved from the vendor `.proof` in scope
    (kit-side; rust stays proof-blind). The mirror of recognize: recognize reads
    the body shape, materialize writes the body."""
    project_root = params.get("project_root")
    if not isinstance(project_root, str) or not project_root:
        raise ValueError("missing `project_root`")
    source_paths = params.get("source_paths")
    if not isinstance(source_paths, list):
        raise ValueError("missing `source_paths` array")
    write = bool(params.get("write"))
    root = Path(project_root).resolve()

    binding_templates, _ = _self_resolved_binding_templates(root, source_paths)
    by_symbol: dict[str, dict[str, Any]] = {}
    for binding in binding_templates:
        symbol = binding.get("symbol") if isinstance(binding, dict) else None
        if not (isinstance(symbol, str) and symbol):
            continue
        # A lean binding carries only the SourceMemento (locus + cids), no inline
        # body. Materialize needs the body to fill the @boundary stub, so it asks
        # the SOURCE ORACLE to resolve it from disk -- the same resolution recognize
        # uses. The proof never carries the body; the oracle reconstructs it.
        if not binding.get("body_text"):
            resolved = _resolve_via_source_oracle(str(root), binding)
            if resolved and resolved.get("body_text"):
                binding = {**binding, "body_text": resolved["body_text"]}
        if binding.get("body_text"):
            by_symbol.setdefault(symbol, binding)

    results: list[dict[str, Any]] = []
    for rel_path, full_path in _iter_requested_python_files(root, source_paths):
        try:
            source = full_path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError:
            continue
        edits: list[tuple[ast.AST, str, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            boundary = _boundary_decorator(node)
            if boundary is None:
                continue
            library, call = boundary
            symbol = f"{library}.{call}"
            binding = by_symbol.get(symbol)
            if binding is None:
                results.append(
                    bind_effect_result(
                        MissingBindingEffect(symbol=symbol),
                        file=rel_path,
                        function=node.name,
                    )
                )
                continue
            if not node.body or node.body[0].lineno <= node.lineno:
                results.append(
                    bind_effect_result(
                        BoundaryBodyShapeEffect(symbol=symbol),
                        file=rel_path,
                        function=node.name,
                    )
                )
                continue
            edits.append((node, binding["body_text"], symbol))
        if not edits:
            continue
        new_source = _apply_body_replacements(source, edits)
        results.append(
            {
                "file": rel_path,
                "outcome": "materialized",
                "materialized": [
                    {"function": n.name, "symbol": s} for (n, _b, s) in edits
                ],
                "new_source": new_source,
            }
        )
        if write:
            try:
                full_path.write_text(new_source, encoding="utf-8")
            except OSError as exc:
                results[-1]["write_error"] = str(exc)
    return {"results": results}


def _boundary_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, str] | None:
    """Return (library, call) for a `@boundary(library=..., call=...)` decorator
    (bare or `@sugar.boundary(...)`), else None."""
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        name = (
            func.attr
            if isinstance(func, ast.Attribute)
            else func.id if isinstance(func, ast.Name) else None
        )
        if name != "boundary":
            continue
        library: str | None = None
        call: str | None = None
        for keyword in decorator.keywords:
            if not isinstance(keyword.value, ast.Constant) or not isinstance(
                keyword.value.value, str
            ):
                continue
            if keyword.arg == "library":
                library = keyword.value.value
            elif keyword.arg == "call":
                call = keyword.value.value
        if library and call:
            return library, call
    return None


def _apply_body_replacements(
    source: str,
    edits: list[tuple[ast.AST, str, str]],
) -> str:
    """Replace each tagged function's body lines with the (re-indented) sugar
    `body_text`. Applied bottom-up so earlier edits don't shift later spans."""
    lines = source.splitlines(keepends=True)
    for node, body_text, _symbol in sorted(
        edits, key=lambda edit: edit[0].body[0].lineno, reverse=True
    ):
        body_start = node.body[0].lineno  # 1-based
        body_end = node.end_lineno or body_start
        indent = " " * node.body[0].col_offset
        replacement = [
            (indent + line if line.strip() else "") + "\n"
            for line in body_text.splitlines()
        ]
        lines[body_start - 1 : body_end] = replacement
    return "".join(lines)


def _published_call_pattern(ast_template: Any) -> dict[str, Any] | None:
    """Extract the matchable call/method-call pattern from a published sugar
    body template. A body like `return numpy.add(x, y)` carries
    block -> expr_stmt -> return -> method_call(param holes); return that inner
    call template (the shape to match anywhere), or None if not a single call."""
    node = ast_template
    if isinstance(node, dict) and node.get("kind") == "block":
        stmts = node.get("stmts") or []
        if len(stmts) != 1:
            return None
        node = stmts[0]
    if isinstance(node, dict) and node.get("kind") == "expr_stmt":
        node = node.get("expr")
    if isinstance(node, dict) and node.get("kind") == "return":
        node = node.get("expr")
    if isinstance(node, dict) and node.get("kind") in ("call", "method_call"):
        return node
    return None


def _unify_template(pattern: Any, candidate: Any, holes: dict[int, Any]) -> bool:
    """Structurally match a published `pattern` against a `candidate` template.
    `param_ref` in the pattern is a wildcard that binds the candidate subtree by
    index; every other node must match exactly. Mutates `holes` on success."""
    if isinstance(pattern, dict) and pattern.get("kind") == "param_ref":
        index = pattern.get("index")
        if index in holes:
            return holes[index] == candidate
        holes[index] = candidate
        return True
    if isinstance(pattern, dict):
        if not isinstance(candidate, dict) or pattern.keys() != candidate.keys():
            return False
        return all(_unify_template(pattern[k], candidate[k], holes) for k in pattern)
    if isinstance(pattern, list):
        if not isinstance(candidate, list) or len(pattern) != len(candidate):
            return False
        return all(_unify_template(p, c, holes) for p, c in zip(pattern, candidate))
    return pattern == candidate


def _import_alias_maps(
    tree: ast.AST,
) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """Build import maps so the ast_walk canonicalizes aliases — the reason a
    sugar `.proof` recognizes `numpy.add` no matter how the consumer spelled the
    import. `module_aliases`: local name -> canonical dotted module
    (`np`->`numpy`). `from_imports`: local name -> (module, original) for
    `from numpy import add [as plus]` (`plus`->(`numpy`,`add`))."""
    module_aliases: dict[str, str] = {}
    from_imports: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    module_aliases[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    module_aliases[head] = head
        elif isinstance(node, ast.ImportFrom):
            if node.module is None or node.level:
                continue
            for alias in node.names:
                local = alias.asname or alias.name
                from_imports[local] = (node.module, alias.name)
    return module_aliases, from_imports


def _module_to_receiver_template(module: str) -> dict[str, Any]:
    segments = module.split(".")
    if len(segments) == 1:
        return {"kind": "ident", "name": segments[0]}
    return {"kind": "path", "segments": segments}


def _canonicalize_template(
    template: Any,
    module_aliases: dict[str, str],
    from_imports: dict[str, tuple[str, str]],
) -> Any:
    """Rewrite a candidate template so aliased references canonicalize to the
    vendor symbol's form: `np.add(...)` -> receiver `numpy`; `add(...)` (from
    `from numpy import add`) -> `numpy.add(...)`."""
    if isinstance(template, list):
        return [
            _canonicalize_template(x, module_aliases, from_imports) for x in template
        ]
    if not isinstance(template, dict):
        return template
    kind = template.get("kind")
    if kind == "method_call":
        receiver = template.get("receiver")
        if (
            isinstance(receiver, dict)
            and receiver.get("kind") == "ident"
            and receiver.get("name") in module_aliases
        ):
            receiver = _module_to_receiver_template(module_aliases[receiver["name"]])
        return {
            "kind": "method_call",
            "receiver": _canonicalize_template(receiver, module_aliases, from_imports),
            "method": template.get("method"),
            "args": [
                _canonicalize_template(a, module_aliases, from_imports)
                for a in template.get("args", [])
            ],
        }
    if kind == "call":
        func = template.get("func")
        if (
            isinstance(func, dict)
            and func.get("kind") == "ident"
            and func.get("name") in from_imports
        ):
            module, original = from_imports[func["name"]]
            return {
                "kind": "method_call",
                "receiver": _module_to_receiver_template(module),
                "method": original,
                "args": [
                    _canonicalize_template(a, module_aliases, from_imports)
                    for a in template.get("args", [])
                ],
            }
    return {
        key: _canonicalize_template(value, module_aliases, from_imports)
        for key, value in template.items()
    }


def _canonical_call_symbol(template: Any) -> str | None:
    """Return the fully-qualified dotted symbol a canonicalized call template
    invokes (`numpy.rot90` for `numpy.rot90(...)`), or None when the template is
    not a direct dotted call. `_canonicalize_template` has already rewritten
    aliases to the vendor form (`np`->`numpy`, `from numpy import rot90`->
    `numpy.rot90`), so the receiver path + method spell the public symbol."""
    if not isinstance(template, dict):
        return None
    if template.get("kind") == "method_call":
        receiver = template.get("receiver")
        method = template.get("method")
        if not isinstance(method, str):
            return None
        if isinstance(receiver, dict) and receiver.get("kind") == "ident":
            name = receiver.get("name")
            return f"{name}.{method}" if isinstance(name, str) else None
        if isinstance(receiver, dict) and receiver.get("kind") == "path":
            segments = receiver.get("segments")
            if isinstance(segments, list) and all(isinstance(s, str) for s in segments):
                return ".".join([*segments, method])
        return None
    if template.get("kind") == "call":
        # `from numpy import rot90; rot90(...)` canonicalizes the callee to the
        # vendor path; a bare ident callee carries no library qualifier and is
        # not a vendor symbol match.
        callee = template.get("callee")
        if isinstance(callee, dict) and callee.get("kind") == "path":
            segments = callee.get("segments")
            if isinstance(segments, list) and all(isinstance(s, str) for s in segments):
                return ".".join(segments)
    return None


def _recognize_calls_anywhere(
    rel_path: str,
    tree: ast.AST,
    binding_templates: list[dict[str, Any]],
    exclude_tags: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Walk every call expression and match published sugar bindings anywhere
    they appear (the recognizer's real job — matched against real code at any
    position, not just identical wrapper functions). Two match faces:

      - BODY-PATTERN: a declared shim publishes a thin wrapper body
        (`return numpy.add(x, y)`); its template IS a call pattern, matched
        structurally with `param_ref` holes (`np.add(_, _)` anywhere).
      - SYMBOL: a universal-lifted vendor function publishes its PUBLIC symbol
        (`numpy.rot90`) but its body is the real implementation, NOT a self-call
        — so there is no wrapper pattern. The recognizer matches any call whose
        canonicalized dotted symbol equals the binding's `symbol`. This is the
        path the lean source oracle requires; without it a vendored symbol whose
        body is not a one-line call could never be recognized.

    Call sites whose line falls within an `exclude_tags` span (an exact
    whole-function match) are skipped to avoid double-emitting."""
    patterns: list[tuple[dict[str, Any], dict[str, Any]]] = []
    symbol_bindings: dict[str, dict[str, Any]] = {}
    for binding in binding_templates:
        if not isinstance(binding, dict):
            continue
        pattern = _published_call_pattern(binding.get("ast_template"))
        if pattern is not None:
            patterns.append((pattern, binding))
            continue
        # No wrapper body pattern: fall back to public-symbol matching. Only
        # bindings carrying an explicit `symbol` (the vendor public name) qualify;
        # the body-pattern path above keeps declared shims byte-identical.
        symbol = binding.get("symbol")
        if isinstance(symbol, str) and symbol:
            symbol_bindings.setdefault(symbol, binding)
    if not patterns and not symbol_bindings:
        return []

    exclude_ranges: list[tuple[int, int]] = []
    for tag in exclude_tags or ():
        span = tag.get("span") if isinstance(tag, dict) else None
        if isinstance(span, dict):
            start = span.get("start_line")
            end = span.get("end_line")
            if isinstance(start, int) and isinstance(end, int):
                exclude_ranges.append((start, end))

    module_aliases, from_imports = _import_alias_maps(tree)

    tags: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if any(lo <= node.lineno <= hi for lo, hi in exclude_ranges):
            continue
        candidate = expr_to_template(node, [])
        candidate = _canonicalize_template(candidate, module_aliases, from_imports)
        matched = False
        for pattern, binding in patterns:
            holes: dict[int, Any] = {}
            if not _unify_template(pattern, candidate, holes):
                continue
            tags.append(
                {
                    "file": rel_path,
                    "span": {
                        "start_line": node.lineno,
                        "start_col": node.col_offset,
                        "end_line": node.end_lineno or node.lineno,
                        "end_col": node.end_col_offset or 0,
                    },
                    "symbol": binding.get("symbol"),
                    "op_cid": binding.get("op_cid"),
                    "library_tag": binding.get("library_tag"),
                    "family": binding.get("family"),
                    "template_cid": binding.get("template_cid"),
                    "contract_cid": binding.get("contract_cid"),
                    "match_tier": "body-anywhere",
                    "param_bindings": [
                        {"index": index, "template": holes[index]}
                        for index in sorted(holes)
                    ],
                }
            )
            matched = True
            break
        if matched:
            continue
        # SYMBOL face: a universal-lifted vendor binding has no wrapper pattern;
        # match by the call's canonicalized public symbol (`numpy.rot90`). The
        # call args are the published-symbol's argument bindings (index-keyed),
        # so a downstream consumer can recover them the same way body-pattern
        # holes are recovered.
        if symbol_bindings:
            call_symbol = _canonical_call_symbol(candidate)
            binding = symbol_bindings.get(call_symbol) if call_symbol else None
            if binding is not None:
                args = candidate.get("args") if isinstance(candidate, dict) else None
                param_bindings = (
                    [{"index": i, "template": a} for i, a in enumerate(args)]
                    if isinstance(args, list)
                    else []
                )
                tags.append(
                    {
                        "file": rel_path,
                        "span": {
                            "start_line": node.lineno,
                            "start_col": node.col_offset,
                            "end_line": node.end_lineno or node.lineno,
                            "end_col": node.end_col_offset or 0,
                        },
                        "symbol": binding.get("symbol"),
                        "op_cid": binding.get("op_cid"),
                        "library_tag": binding.get("library_tag"),
                        "family": binding.get("family"),
                        "template_cid": binding.get("template_cid"),
                        "contract_cid": binding.get("contract_cid"),
                        "match_tier": "symbol",
                        "param_bindings": param_bindings,
                    }
                )
    return tags


def _self_resolved_binding_templates(
    root: Path,
    source_paths: list[Any],
) -> tuple[list[dict[str, Any]], set[str]]:
    result = lift_paths(
        str(root),
        [str(path) for path in source_paths],
        layer="library-bindings",
    )
    templates: list[dict[str, Any]] = []
    sugar_template_files: set[str] = set()
    for entry in result.ir:
        if (
            not isinstance(entry, dict)
            or entry.get("kind") != "library-sugar-binding-entry"
        ):
            continue
        # A `derived` binding is the project's OWN universal-lifted function (no
        # @sugar.bind). It belongs in the project's `.proof`, but it is NOT a
        # published match-template — otherwise recognize matches a project's
        # functions against themselves. Published templates are declared shims +
        # resolved vendor `.proof`s (below). This is the coherence rule that lets
        # "every function is sugar" and recognize co-exist.
        if entry.get("binding_origin") == "derived":
            continue
        template = _binding_template_from_sugar_entry(entry)
        if template is not None:
            templates.append(template)
        body_source = entry.get("body_source")
        file = body_source.get("file") if isinstance(body_source, dict) else None
        if isinstance(file, str) and file:
            sugar_template_files.add(file)
    # The `.proof` is the transport: also load published binding templates from
    # the vendor `.proof`s the kit resolves itself (`.sugar/imports/`). The
    # kit owns `.proof` resolution and decode; the substrate (rust) stays
    # proof-blind. Without this, a real consumer (no co-located `@sugar.bind`)
    # resolves zero templates and recognize finds nothing.
    templates.extend(_vendor_proof_binding_templates(root))
    return templates, sugar_template_files


def _vendor_proof_binding_templates(root: Path) -> list[dict[str, Any]]:
    """Resolve published sugar binding templates from vendor `.proof`s under
    `.sugar/imports/`. Decodes each envelope with the kit's own cbor2 (same
    decoder as proof_envelope) and lifts every `library-sugar-binding-entry`'s
    `{ast_template, template_cid, symbol}`. Rust never reads the `.proof`."""
    import json as _json

    try:
        import cbor2
    except ImportError:
        return []
    proof_paths: set[Path] = set()
    # 1. The package manager's dependency tree — the real "all `.proof`s in
    #    scope". Every pip-installed distribution that ships a `.proof` (e.g.
    #    the sugar-shim-numpy wheel) contributes it, exactly like
    #    DefinitelyTyped `@types/*` resolve through node_modules. The kit owns
    #    this ecosystem-native resolution; rust stays proof-blind.
    try:
        from importlib import metadata as importlib_metadata
        from fnmatch import fnmatch

        for dist in importlib_metadata.distributions():
            for file in dist.files or ():
                if not fnmatch(Path(str(file)).name, "blake3-512_*.proof"):
                    continue
                try:
                    located = Path(dist.locate_file(file)).resolve()
                except Exception:
                    continue
                if located.is_file():
                    proof_paths.add(located)
    except Exception:
        pass
    # 2. Locally-staged proofs the project resolved into `.sugar/imports/`.
    imports_dir = root / ".sugar" / "imports"
    if imports_dir.is_dir():
        proof_paths.update(
            p for p in imports_dir.glob("blake3-512_*.proof") if p.is_file()
        )
    templates: list[dict[str, Any]] = []
    for proof_path in sorted(proof_paths):
        try:
            catalog = cbor2.loads(proof_path.read_bytes())
        except Exception:
            continue
        members = catalog.get("members") if isinstance(catalog, dict) else None
        if not isinstance(members, dict):
            continue
        for member_bytes in members.values():
            if not isinstance(member_bytes, (bytes, bytearray)):
                continue
            try:
                member = _json.loads(member_bytes)
            except Exception:
                try:
                    member = cbor2.loads(member_bytes)
                except Exception:
                    continue
            if not isinstance(member, dict):
                continue
            header = member.get("header")
            if (
                not isinstance(header, dict)
                or header.get("kind") != "library-sugar-binding-entry"
            ):
                continue
            body = member.get("body")
            if not isinstance(body, dict):
                continue
            body_source = body.get("body_source")
            if not isinstance(body_source, dict):
                continue
            ast_template = body_source.get("ast_template")
            template_cid = body_source.get("template_cid")
            body_text = body_source.get("body_text")
            # SourceMemento: when the `.proof` carries no inline source (just the
            # locus + CIDs), ask the SOURCE ORACLE to resolve body_text +
            # ast_template from the on-disk source at the locus (CID-verified,
            # refuse on drift). ONE resolution feeds BOTH recognize (ast_template)
            # and materialize (body_text). Inline content (legacy .proof) wins.
            if ast_template is None or body_text is None:
                resolved = _resolve_via_source_oracle(str(root), body)
                if resolved is not None:
                    if ast_template is None:
                        ast_template = resolved.get("ast_template")
                    if body_text is None:
                        body_text = resolved.get("body_text")
            if (
                ast_template is None
                or not isinstance(template_cid, str)
                or not template_cid
            ):
                continue
            templates.append(
                {
                    "symbol": body.get("symbol"),
                    "op_cid": body.get("op_cid"),
                    "library_tag": body.get("target_library_tag"),
                    "ast_template": ast_template,
                    "template_cid": template_cid,
                    "param_names": body_source.get("param_names"),
                    "body_text": body_text,
                    "contract_cid": body.get("contract_cid"),
                }
            )
    return templates


def _resolve_via_source_oracle(
    project_root: str, body: dict[str, Any]
) -> dict[str, Any] | None:
    """Resolve a SourceMemento (the `.proof`'s locus + CIDs) to body_text +
    ast_template via the Source Oracle, trying the consumer project root and the
    vendor's installed-package root. None on a loud refusal (source drift)."""
    from .source_oracle import (
        SourceOracleRefusal,
        importlib_library_dir,
        importlib_package_root,
        resolve_from_roots,
    )

    body_source = body.get("body_source")
    if not isinstance(body_source, dict):
        return None
    memento = {
        "source_function_name": body.get("source_function_name"),
        "file": body_source.get("file"),
        "span": body_source.get("span"),
        "source_cid": body_source.get("source_cid"),
        "template_cid": body_source.get("template_cid"),
    }
    roots = [project_root]
    # 1. `file` is `pkg/mod.py` -> the package's PARENT resolves it
    #    (`numpy/lib/...` against site-packages).
    pkg_root = importlib_package_root(body_source.get("file") or "")
    if pkg_root:
        roots.append(pkg_root)
    # 2. `file` is RELATIVE TO THE PACKAGE (`lib/_function_base_impl.py`, minted
    #    with `--project <site-packages>/numpy`) -> the package DIR ITSELF
    #    resolves it. Keyed by the binding's authoritative `target_library_tag`
    #    (`numpy`), not the file's private first segment (`lib`). Additive: tried
    #    only after the project root, so in-project resolutions are unaffected.
    library_tag = body.get("target_library_tag") or body.get("library_tag") or ""
    lib_dir = importlib_library_dir(library_tag)
    if lib_dir:
        roots.append(lib_dir)
    try:
        return resolve_from_roots(memento, roots)
    except SourceOracleRefusal:
        return None


def _binding_template_from_sugar_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    body_source = entry.get("body_source")
    if not isinstance(body_source, dict):
        return None
    template_cid = body_source.get("template_cid")
    # `template_cid` is the recognize key (recognize matches by cid, not by the
    # inline template) and is ALWAYS present -- even in a lean SourceMemento. The
    # inline `ast_template`/`body_text` are absent in a lean binding; the consumer
    # (recognize match / materialize fill) resolves them through the Source Oracle.
    # Carry `body_source` + `source_function_name` so the oracle can resolve.
    if not isinstance(template_cid, str) or not template_cid:
        return None
    return {
        "symbol": entry.get("symbol"),
        "op_cid": entry.get("op_cid"),
        "library_tag": entry.get("target_library_tag"),
        "family": entry.get("family"),
        "ast_template": body_source.get("ast_template"),
        "template_cid": template_cid,
        "param_names": body_source.get("param_names"),
        "body_text": body_source.get("body_text"),
        "contract_cid": entry.get("contract_cid"),
        "body_source": body_source,
        "source_function_name": entry.get("source_function_name"),
    }


def _recognize_function(
    rel_path: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    bindings_by_cid: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    candidate_template = function_body_template(node)
    candidate_cid = template_cid_of_json(candidate_template)
    binding = bindings_by_cid.get(candidate_cid)
    if binding is None:
        return None

    param_names = function_param_names(node)
    return {
        "file": rel_path,
        "span": {
            "start_line": node.lineno,
            "start_col": node.col_offset,
            "end_line": node.end_lineno or node.lineno,
            "end_col": node.end_col_offset or 0,
        },
        "function_name": node.name,
        "symbol": binding.get("symbol"),
        "op_cid": binding.get("op_cid"),
        "library_tag": binding.get("library_tag"),
        "family": binding.get("family"),
        "template_cid": candidate_cid,
        "contract_cid": binding.get("contract_cid"),
        "match_tier": "exact",
        "param_bindings": [
            {"index": index + 1, "source_text": name}
            for index, name in enumerate(param_names)
        ],
    }


def _iter_candidate_functions(
    tree: ast.AST,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    candidates: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            candidates.append(node)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            candidates.append(node)
            self.generic_visit(node)

    Visitor().visit(tree)
    return candidates


def _iter_requested_python_files(
    root: Path,
    source_paths: list[Any],
) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for item in source_paths:
        rel = str(item)
        if not rel:
            continue
        matches = _expand_source_path(root, rel)
        for full_path in matches:
            try:
                resolved = full_path.resolve()
            except OSError:
                continue
            if resolved in seen or not _is_relative_to(resolved, root):
                continue
            if not resolved.is_file() or resolved.suffix != ".py":
                continue
            seen.add(resolved)
            display = resolved.relative_to(root).as_posix()
            files.append((display, resolved))
    return files


def _expand_source_path(root: Path, rel: str) -> list[Path]:
    if any(ch in rel for ch in "*?[]"):
        return sorted(root.glob(rel))
    full = Path(rel)
    if not full.is_absolute():
        full = root / full
    if full.is_dir():
        return sorted(full.rglob("*.py"))
    return [full]


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _send(obj: dict[str, Any]) -> None:
    # Write bytes with errors="replace": a single pathological source character
    # (e.g. an astral emoji whose surrogate pair got split during source slicing)
    # would otherwise raise UnicodeEncodeError ("surrogates not allowed") and
    # kill the ENTIRE response. A lifter must be robust to one bad byte in one
    # function out of thousands, so unencodable chars become U+FFFD rather than
    # aborting the run.
    line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(line.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message},
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rpc", action="store_true", help="run bind JSON-RPC over stdio"
    )
    parser.add_argument("--bind-rpc", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.rpc or args.bind_rpc:
        run_rpc()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

"""Install-source body dig: resolve vendor/same-module callees for CallSiteValue.body.

Membrane: fleet/CallSugar emits call:f(...) coordinates. This module resolves
f to a FunctionDef (same module, from_import, or importable module.attr), tags
install-source provenance, and builds a diggable body via build_bridge_body.

Bridge/dig doctrine:
- Resolve first; None means body stays None (coordinate only / dig opaque).
- Prefer real source file (Download Sources / site-packages) over invention.
- nested_external_bridge stays default False — not flipped here.
- Failures are None (opaque) or leave force_floor to panic — never silent invent.
"""

from __future__ import annotations

import importlib
import inspect
import textwrap
from pathlib import Path
from typing import Any


def module_sibling_function_nodes(module_name: str) -> dict:
    """AST FunctionDef nodes for every def in ``module_name``, bare + qualified keys.

    Enables open dig of ``base64.urlsafe_b64encode`` to resolve same-module
    ``b64encode`` (and itsdangerous ``want_bytes`` when digging encoding bodies).
    """
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    try:
        module = importlib.import_module(module_name)
        sourcefile = inspect.getsourcefile(module)
        if not sourcefile:
            return {}
        source = Path(sourcefile).read_text(encoding="utf-8")
    except (ImportError, OSError, TypeError, UnicodeError):
        return {}
    try:
        parsed = SourceFragment.from_source(source, sourcefile)
    except SyntaxError:
        return {}
    nodes: dict = {}
    for child in parsed.walk():
        if child.observed != "FunctionDef":
            continue
        name = child.function_name()
        child.node.decorator_list = []  # type: ignore[attr-defined]
        child.node._sugar_source = source  # type: ignore[attr-defined]
        child.node._sugar_file = sourcefile  # type: ignore[attr-defined]
        child.node._sugar_bridge_name = f"{module_name}.{name}"  # type: ignore[attr-defined]
        nodes[name] = child.node
        nodes[f"{module_name}.{name}"] = child.node
    return nodes


def resolve_install_source_funcdef(import_target: str):
    """Resolve ``module.attr`` to an installed FunctionDef SourceFragment, or None."""
    if "." not in import_target:
        return None
    module_name, attr = import_target.rsplit(".", 1)
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    try:
        module = importlib.import_module(module_name)
        obj = getattr(module, attr)
        if not callable(obj) or inspect.isclass(obj):
            # Classes are not free-function dig targets in this PR.
            return None
        source = textwrap.dedent(inspect.getsource(obj))
    except (ImportError, AttributeError, OSError, TypeError):
        return None
    try:
        sourcefile = inspect.getsourcefile(obj) or f"<{module_name}>"
    except TypeError:
        sourcefile = f"<{module_name}>"
    try:
        parsed = SourceFragment.from_source(source, sourcefile)
    except SyntaxError:
        return None
    for child in parsed.walk():
        if child.observed == "FunctionDef" and child.function_name() == attr:
            child.node.decorator_list = []  # type: ignore[attr-defined]
            child.node._sugar_source = source  # type: ignore[attr-defined]
            child.node._sugar_file = sourcefile  # type: ignore[attr-defined]
            child.node._sugar_bridge_name = import_target  # type: ignore[attr-defined]
            return child
    return None


def resolve_call_funcdef(target_name: str, ctx: Any):
    """Resolve a plain-name call target to a FunctionDef SourceFragment, or None.

    Order:
    1. ``ctx.name_resolver`` (same-module defs seeded by audit_lift_file)
    2. ``ctx.from_imports`` → ``module.attr`` install-source
    3. ``ctx.import_aliases`` not used for bare names (attr path is MethodCall)
    """
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    if not target_name or ctx is None:
        return None

    resolver = getattr(ctx, "name_resolver", None) or {}
    node = resolver.get(target_name)
    if node is not None:
        filename = getattr(ctx, "filename", "<module>")
        site = SourceFragment.from_node(node, filename)
        if site.observed == "FunctionDef":
            # Tag with module file when available so global binds seed.
            sugar_file = getattr(node, "_sugar_file", None) or filename
            sugar_source = getattr(node, "_sugar_source", None)
            if sugar_source is None and sugar_file and Path(sugar_file).is_file():
                try:
                    sugar_source = Path(sugar_file).read_text(encoding="utf-8")
                except OSError:
                    sugar_source = None
            if sugar_source is not None:
                node._sugar_source = sugar_source  # type: ignore[attr-defined]
                node._sugar_file = sugar_file  # type: ignore[attr-defined]
            return site

    from_imports = getattr(ctx, "from_imports", None) or {}
    if target_name in from_imports:
        mod, attr = from_imports[target_name]
        qualified = f"{mod}.{attr}" if mod else attr
        # Prefer full-module sibling node (real file + globals).
        if mod:
            siblings = module_sibling_function_nodes(mod)
            n = siblings.get(qualified) or siblings.get(attr)
            if n is not None:
                return SourceFragment.from_node(
                    n, getattr(n, "_sugar_file", f"<{mod}>")
                )
        return resolve_install_source_funcdef(qualified)

    return None


def build_dig_body(fn_site, ctx: Any):
    """Build diggable body for ``fn_site`` FunctionDef, or None on failure."""
    if fn_site is None or fn_site.observed != "FunctionDef":
        return None
    from sugar_lift_py_tests.factory.sugar_constructors import build_bridge_body

    # Recursion / re-entrancy: skip if already building this callee.
    building = getattr(ctx, "building", frozenset()) or frozenset()
    name = fn_site.function_name()
    bridge = getattr(fn_site.node, "_sugar_bridge_name", None) or name
    if name in building or bridge in building:
        return None
    try:
        from dataclasses import replace

        body_ctx = replace(ctx, building=building | {name, bridge})
        # Seed siblings into name_resolver for same-module nested calls.
        mod = getattr(fn_site.node, "_sugar_bridge_name", "") or ""
        if "." in str(mod):
            module_name = str(mod).rsplit(".", 1)[0]
            siblings = module_sibling_function_nodes(module_name)
            if siblings:
                merged = dict(getattr(body_ctx, "name_resolver", None) or {})
                merged.update(siblings)
                body_ctx = replace(body_ctx, name_resolver=merged)
        return build_bridge_body(fn_site, body_ctx)
    except Exception:
        # IncompleteFunctionBody is Exception; Incomplete is not BaseException.
        # Any build failure → coordinate only (body=None). Never invent.
        return None


def dig_parameters_for_body(fn_site, arg_count: int, keyword_names: tuple[str, ...]):
    """Formal names for CallSiteValue.parameters when body dig can run.

    Dig requires ``len(parameters) == len(arg_values)``. Prefer function formals
    when arity matches positional-only calls; keyword-only uses keyword_names.
    """
    if fn_site is None:
        return keyword_names
    formals = tuple(fn_site.function_params())
    if keyword_names:
        # Keyword values are trailing; parameters are keyword names in order.
        if len(keyword_names) == arg_count:
            return keyword_names
        # Mixed pos+kw: need full formal list of same length — else dig stays opaque.
        if len(formals) == arg_count:
            return formals
        return keyword_names
    if len(formals) == arg_count:
        return formals
    return ()


# Aliases matching historical test imports from call_sugar
_resolve_install_source_funcdef = resolve_install_source_funcdef
_module_sibling_function_nodes = module_sibling_function_nodes

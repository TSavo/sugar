# SPDX-License-Identifier: MIT OR Apache-2.0
#
# The Source Oracle.
#
# The `.proof` does not carry source. A SourceMemento is a pointer + two hashes:
#   { source_function_name, file, span, source_cid, template_cid }
# zero content. The source already lives on disk (pip/npm/cargo shipped it); the
# `.proof` only LOCATES it (file, span) and PINS it (source_cid, template_cid).
#
# You do not ask the `.proof` for `body_text`/`ast_template` -- you ask the Source
# Oracle. Its contract is one line:
#
#   given a locus + CID, return the source IFF it recomputes to the CID;
#   else REFUSE, loudly.
#
# That refusal is the BINARY axis of the three-axis pin made operational, checked
# at every resolution: a tampered or wrong-version package -> CID mismatch ->
# refuse -> the sugar cannot resolve -> you KNOW the on-disk source is not what was
# proven. exact-or-refuse, no silent loss (supra omnia, rectum).

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any

from .ast_template import (
    expr_to_template,
    function_param_names,
    stmt_to_template,
)
from .bind_lifter import _body_source_locator
from .canonical import blake3_512_of, template_cid_of_json
from .source_tables import parsed_tree, source_segment, source_splitlines


class SourceOracleRefusal(Exception):
    """Raised LOUDLY when on-disk source does not recompute to the pinned CID:
    the source has drifted from what the `.proof` pins. Never a silent fallback."""


def resolve_source_memento(
    project_root: str, memento: dict[str, Any]
) -> dict[str, Any]:
    """Resolve a SourceMemento to its `{body_text, ast_template}` by RECOMPUTE.

    Reads the on-disk source at the memento's locus, re-derives the pinned
    function body or source node with the same machinery that minted it, and
    returns the source/AST IFF the recomputed `source_cid`/`template_cid` equal
    the pinned ones. Otherwise raises `SourceOracleRefusal`.
    """
    file = memento.get("file")
    if not isinstance(file, str) or not file:
        raise SourceOracleRefusal("source memento missing `file`")
    function_name = memento.get("source_function_name")
    pinned_source_cid = memento.get("source_cid")
    pinned_template_cid = memento.get("template_cid")
    span = memento.get("span") if isinstance(memento.get("span"), dict) else {}

    path = Path(project_root) / file
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SourceOracleRefusal(f"cannot read source `{path}`: {exc}") from exc
    try:
        tree = parsed_tree(source, filename=str(path))
    except SyntaxError as exc:
        raise SourceOracleRefusal(f"cannot parse source `{path}`: {exc}") from exc

    node = _locate_function(tree, function_name, span)
    if node is None:
        raise SourceOracleRefusal(
            f"source function `{function_name}` not found in `{file}` near line "
            f"{span.get('start_line')}"
        )

    rel = file.replace(os.sep, "/")
    if memento.get("source_kind") in {"python.ast-stmt", "python.ast-expr"}:
        recomputed = _node_source_locator(
            node,
            rel,
            source,
            span,
            str(memento.get("source_kind")),
        )
    else:
        recomputed = _body_source_locator(node, rel, list(source_splitlines(source)))
    # The Source Oracle's whole job is to RECONSTRUCT source + ast_template from
    # disk. Function mementos resolve to whole bodies; statement/expression
    # mementos resolve to the exact node that warranted the proof row.

    if (
        pinned_source_cid is not None
        and recomputed.get("source_cid") != pinned_source_cid
    ):
        raise SourceOracleRefusal(
            f"source CID misaligned for `{function_name}` in `{file}`: "
            f"pinned {pinned_source_cid}, on-disk {recomputed.get('source_cid')} "
            "-- the source drifted from the proof"
        )
    if (
        pinned_template_cid is not None
        and recomputed.get("template_cid") != pinned_template_cid
    ):
        raise SourceOracleRefusal(
            f"template CID misaligned for `{function_name}` in `{file}`: "
            f"pinned {pinned_template_cid}, on-disk {recomputed.get('template_cid')} "
            "-- the AST drifted from the proof"
        )

    return {
        "body_text": recomputed.get("body_text"),
        "ast_template": recomputed.get("ast_template"),
        "source_cid": recomputed.get("source_cid"),
        "template_cid": recomputed.get("template_cid"),
        "param_names": recomputed.get("param_names"),
    }


def _node_source_locator(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    rel_path: str,
    source: str,
    span: dict[str, Any],
    source_kind: str,
) -> dict[str, Any]:
    node = _locate_spanned_node(fn, span, source_kind)
    if node is None:
        raise SourceOracleRefusal(
            f"{source_kind} source node not found in `{rel_path}` near line "
            f"{span.get('start_line')}"
        )
    body_text = source_segment(source, node)
    if body_text is None:
        raise SourceOracleRefusal(
            f"{source_kind} source node in `{rel_path}` had no source segment"
        )
    params = function_param_names(fn)
    if isinstance(node, ast.stmt):
        ast_template = stmt_to_template(node, params)
    elif isinstance(node, ast.expr):
        ast_template = expr_to_template(node, params)
    else:
        raise SourceOracleRefusal(
            f"unsupported source node kind `{type(node).__name__}`"
        )
    return {
        "file": rel_path,
        "source_cid": blake3_512_of(body_text.encode("utf-8")),
        "span": _span_of(node),
        "template_cid": template_cid_of_json(ast_template),
        "param_names": params,
        "ast_template": ast_template,
        "body_text": body_text,
    }


def _locate_spanned_node(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    span: dict[str, Any],
    source_kind: str,
) -> ast.AST | None:
    node_type: type[ast.AST]
    if source_kind == "python.ast-stmt":
        node_type = ast.stmt
    elif source_kind == "python.ast-expr":
        node_type = ast.expr
    else:
        return None
    for node in ast.walk(fn):
        if not isinstance(node, node_type):
            continue
        if _span_of(node) == {
            "start_line": span.get("start_line"),
            "start_col": span.get("start_col"),
            "end_line": span.get("end_line"),
            "end_col": span.get("end_col"),
        }:
            return node
    return None


def _span_of(node: ast.AST) -> dict[str, int]:
    return {
        "start_line": getattr(node, "lineno"),
        "start_col": getattr(node, "col_offset"),
        "end_line": getattr(node, "end_lineno"),
        "end_col": getattr(node, "end_col_offset"),
    }


def resolve_from_roots(memento: dict[str, Any], roots: list[str]) -> dict[str, Any]:
    """Resolve a SourceMemento against the first root whose on-disk source aligns
    to the pinned CIDs. The source already lives SOMEWHERE on disk (the consumer's
    project, or the vendor's installed package); try each candidate root, refuse
    loudly only if none aligns."""
    last: SourceOracleRefusal | None = None
    for root in roots:
        if not root:
            continue
        try:
            return resolve_source_memento(root, memento)
        except SourceOracleRefusal as exc:
            last = exc
    raise last or SourceOracleRefusal("no root resolved the source memento")


def importlib_package_root(file: str) -> str | None:
    """Root R such that R/<file> is the installed source for a vendor `.proof`
    whose `file` is `pkg/mod.py` — found via the package manager (pip/importlib),
    the same ecosystem-native resolution the kit uses for `.proof`s themselves."""
    if not isinstance(file, str) or not file:
        return None
    package = file.replace("\\", "/").split("/", 1)[0]
    try:
        from importlib.util import find_spec

        spec = find_spec(package)
    except Exception:
        return None
    if spec is None:
        return None
    locations = getattr(spec, "submodule_search_locations", None)
    if locations:
        return str(Path(next(iter(locations))).parent)
    origin = getattr(spec, "origin", None)
    return str(Path(origin).parent) if origin else None


def importlib_library_dir(library_tag: str) -> str | None:
    """Directory D such that D/<file> is the installed source when a `.proof`'s
    `file` is RELATIVE TO THE PACKAGE ITSELF (e.g. `lib/_function_base_impl.py`
    for a binding minted with `--project <site-packages>/numpy`).

    `importlib_package_root` returns the package's PARENT (good for `numpy/...`
    file paths). This returns the package DIR ITSELF, keyed by the binding's
    authoritative `target_library_tag` (`numpy`) rather than the file's first
    path segment (`lib`, a private submodule that is not an importable package).
    Found ecosystem-natively via importlib — pip already shipped the source."""
    if not isinstance(library_tag, str) or not library_tag:
        return None
    try:
        from importlib.util import find_spec

        spec = find_spec(library_tag)
    except Exception:
        return None
    if spec is None:
        return None
    locations = getattr(spec, "submodule_search_locations", None)
    if locations:
        return str(Path(next(iter(locations))))
    origin = getattr(spec, "origin", None)
    return str(Path(origin).parent) if origin else None


def _locate_function(
    tree: ast.AST,
    function_name: Any,
    span: dict[str, Any],
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find the FunctionDef matching the memento's name (and span when ambiguous)."""
    start = span.get("start_line")
    function_leaf = (
        function_name.rsplit(".", 1)[-1] if isinstance(function_name, str) else None
    )
    matches = [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and (
            function_name is None or n.name == function_name or n.name == function_leaf
        )
    ]
    if not matches:
        return None
    if isinstance(start, int) and len(matches) > 1:
        for n in matches:
            n_start = min((d.lineno for d in n.decorator_list), default=n.lineno)
            if n_start <= start <= (n.end_lineno or n.lineno):
                return n
    return matches[0]

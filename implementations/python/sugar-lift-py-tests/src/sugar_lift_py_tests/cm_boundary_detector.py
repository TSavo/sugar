"""Construction-boundary detector over production sugar / source-tree roots.

Source text is the authority: import and call shapes are matched as text so
this instrument is not itself an ``ast``-semantic side door above adapters.
Adapters may parse; construction meaning does not re-open raw AST here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BoundaryReport:
    files_scanned: int
    offenders: tuple[str, ...]

    @property
    def r(self) -> int:
        return len(self.offenders)

    def render(self) -> str:
        return "\n".join(self.offenders)


def scan_construction_boundary(
    *, sugar_root: Path, source_tree_root: Path
) -> BoundaryReport:
    files = tuple(sorted(sugar_root.rglob("*.py"))) + tuple(
        sorted(source_tree_root.rglob("*.py"))
    )
    offenders: list[str] = []
    for path in files:
        offenders.extend(_scan_file(path))
    return BoundaryReport(
        files_scanned=len(files), offenders=tuple(sorted(set(offenders)))
    )


_HARD_MODULES = (
    "sugar_linker",
    "sugar.linker",
    "sugar_proof_catalog",
    "sugar_proof_envelope",
)
_SOURCE_ORACLE = "sugar_lift_python_source.source_oracle"
_SOURCE_ORACLE_BOUNDARIES = frozenset(
    {
        "tree.py",
        "corpus.py",
        "bench_backends.py",
        "fragment.py",
    }
)
_FORBIDDEN_CALLS = frozenset(
    {
        "resolve_context_manager_demand",
        "resolve_context_manager_import",
        "decode_context_manager_contract",
        "member_field",
        "member_kind",
        "read_proof_catalog",
    }
)
_SOURCE_CALLS = frozenset({"path_source", "installed_module_source"})

# import sugar_linker as hidden
# import sugar_linker, other as o
_IMPORT_LINE = re.compile(r"^\s*import\s+(.+?)(?:\s*#.*)?$")
# from sugar_linker import resolve_context_manager_demand as lookup
# from sugar_linker import (
_FROM_IMPORT_LINE = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+(.+?)(?:\s*#.*)?$")
# hidden.resolve_context_manager_demand(  /  resolve_context_manager_demand(
_CALL_SITE = re.compile(r"(?<![\w.])([\w]+(?:\.[\w]+)*)\s*\(")
_NAME_AS = re.compile(r"^([\w.]+)(?:\s+as\s+(\w+))?$")


def _strip_hash_comment(line: str) -> str:
    """Drop trailing ``#`` comments when the hash is outside simple quotes."""
    in_single = False
    in_double = False
    escape = False
    for index, char in enumerate(line):
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            return line[:index]
    return line


def _split_import_clause(clause: str) -> list[tuple[str, str | None]]:
    """Parse ``a as b, c`` into ``[(a, b), (c, None)]`` (parens already stripped)."""
    cleaned = clause.strip().rstrip("\\").strip()
    if not cleaned or cleaned == "*":
        return []
    parts: list[tuple[str, str | None]] = []
    for raw in cleaned.split(","):
        piece = raw.strip()
        if not piece or piece == "*":
            continue
        match = _NAME_AS.match(piece)
        if match is None:
            continue
        parts.append((match.group(1), match.group(2)))
    return parts


def _module_is_hard(module: str) -> bool:
    return module.startswith(_HARD_MODULES)


def _scan_file(path: Path) -> list[str]:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [f"{path}:0:auditor-read-error"]

    aliases: dict[str, str] = {}
    offenders: list[str] = []
    allow_source_oracle = path.name in _SOURCE_ORACLE_BOUNDARIES

    # Multi-line ``from X import ( ... )`` continuation buffer.
    pending_from_module: str | None = None
    pending_from_start_line = 0
    pending_from_chunks: list[str] = []

    def record(line_no: int, reason: str) -> None:
        offenders.append(f"{path}:{line_no}:{reason}")

    def ingest_import(
        module_name: str, line_no: int, asname: str | None = None
    ) -> None:
        local = asname or module_name.split(".", 1)[0]
        aliases[local] = module_name
        if _module_is_hard(module_name):
            record(line_no, f"forbidden import {module_name}")
        if module_name == _SOURCE_ORACLE and not allow_source_oracle:
            record(
                line_no,
                f"source-oracle import outside setup boundary {module_name}",
            )

    def ingest_from_import(
        module: str, imported: str, line_no: int, asname: str | None = None
    ) -> None:
        local = asname or imported
        target = f"{module}.{imported}" if module else imported
        aliases[local] = target
        if _module_is_hard(module) or imported in _FORBIDDEN_CALLS:
            record(line_no, f"forbidden import {target}")
        if module == _SOURCE_ORACLE and not allow_source_oracle:
            record(
                line_no,
                f"source-oracle import outside setup boundary {target}",
            )

    def flush_from_import() -> None:
        nonlocal pending_from_module, pending_from_start_line, pending_from_chunks
        if pending_from_module is None:
            return
        body = " ".join(pending_from_chunks)
        # Drop surrounding parentheses if present.
        body = body.strip()
        if body.startswith("("):
            body = body[1:]
        if body.endswith(")"):
            body = body[:-1]
        for name, asname in _split_import_clause(body):
            ingest_from_import(
                pending_from_module, name, pending_from_start_line, asname
            )
        pending_from_module = None
        pending_from_start_line = 0
        pending_from_chunks = []

    for line_no, raw_line in enumerate(source.splitlines(), start=1):
        line = _strip_hash_comment(raw_line).rstrip()
        if not line.strip():
            if pending_from_module is not None:
                pending_from_chunks.append("")
            continue

        if pending_from_module is not None:
            pending_from_chunks.append(line)
            # Close when this chunk balances the open paren from the start.
            joined = " ".join(pending_from_chunks)
            if joined.count("(") > 0 and joined.count("(") <= joined.count(")"):
                flush_from_import()
            continue

        from_match = _FROM_IMPORT_LINE.match(line)
        if from_match is not None:
            module = from_match.group(1)
            clause = from_match.group(2).strip()
            if clause.startswith("(") and clause.count("(") > clause.count(")"):
                pending_from_module = module
                pending_from_start_line = line_no
                pending_from_chunks = [clause]
                continue
            # Single-line from-import (possibly with balanced parens).
            if clause.startswith("(") and clause.endswith(")"):
                clause = clause[1:-1]
            for name, asname in _split_import_clause(clause):
                ingest_from_import(module, name, line_no, asname)
            continue

        import_match = _IMPORT_LINE.match(line)
        if import_match is not None:
            clause = import_match.group(1).strip()
            for name, asname in _split_import_clause(clause):
                ingest_import(name, line_no, asname)
            continue

        for call_match in _CALL_SITE.finditer(line):
            dotted = call_match.group(1)
            # Skip attribute/method definitions and obvious non-calls left of =
            head, _, tail = dotted.partition(".")
            resolved = aliases.get(head, head)
            if tail:
                resolved = f"{resolved}.{tail}"
            call_name = resolved.rsplit(".", 1)[-1]
            if call_name in _FORBIDDEN_CALLS:
                record(line_no, f"forbidden call {resolved}")
            if call_name in _SOURCE_CALLS and not allow_source_oracle:
                record(
                    line_no,
                    f"source-oracle call outside setup boundary {resolved}",
                )

    # Unclosed multi-line import: still ingest what we have so planted twins
    # cannot hide behind a missing paren.
    if pending_from_module is not None:
        flush_from_import()

    return offenders

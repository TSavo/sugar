import ast
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
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _BoundaryVisitor(path)
        visitor.visit(tree)
        offenders.extend(visitor.offenders)
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


def _dotted(node: ast.expr) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


class _BoundaryVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.aliases: dict[str, str] = {}
        self.offenders: list[str] = []

    def _record(self, node: ast.AST, reason: str) -> None:
        self.offenders.append(f"{self.path}:{getattr(node, 'lineno', 0)}:{reason}")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            self.aliases[local] = alias.name
            if alias.name.startswith(_HARD_MODULES):
                self._record(node, f"forbidden import {alias.name}")
            if (
                alias.name == _SOURCE_ORACLE
                and self.path.name not in _SOURCE_ORACLE_BOUNDARIES
            ):
                self._record(
                    node, f"source-oracle import outside setup boundary {alias.name}"
                )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            local = alias.asname or alias.name
            target = f"{module}.{alias.name}" if module else alias.name
            self.aliases[local] = target
            if module.startswith(_HARD_MODULES) or alias.name in _FORBIDDEN_CALLS:
                self._record(node, f"forbidden import {target}")
            if (
                module == _SOURCE_ORACLE
                and self.path.name not in _SOURCE_ORACLE_BOUNDARIES
            ):
                self._record(
                    node, f"source-oracle import outside setup boundary {target}"
                )

    def visit_Call(self, node: ast.Call) -> None:
        dotted = _dotted(node.func)
        if dotted:
            head, _, tail = dotted.partition(".")
            resolved = self.aliases.get(head, head)
            if tail:
                resolved = f"{resolved}.{tail}"
            call_name = resolved.rsplit(".", 1)[-1]
            if call_name in _FORBIDDEN_CALLS:
                self._record(node, f"forbidden call {resolved}")
            if (
                call_name in _SOURCE_CALLS
                and self.path.name not in _SOURCE_ORACLE_BOUNDARIES
            ):
                self._record(
                    node, f"source-oracle call outside setup boundary {resolved}"
                )
        self.generic_visit(node)

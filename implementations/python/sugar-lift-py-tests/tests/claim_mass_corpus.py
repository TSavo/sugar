from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ClaimMassPin:
    name: str
    relative_path: str
    sha256: str
    assertion_count: int
    lifted_loci: tuple[int | tuple[str, int], ...]


@dataclass(frozen=True)
class AssertionClaim:
    cid: str
    owner: str
    line: int


class _AssertionClaims(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope = ["<module>"]
        self.claims: list[AssertionClaim] = []
        self.occurrences: dict[tuple[str, str], int] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scope(node.name, node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scope(node.name, node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scope(node.name, node)

    def visit_Assert(self, node: ast.Assert) -> None:
        owner = ".".join(self.scope)
        predicate = ast.dump(node.test, annotate_fields=True, include_attributes=False)
        occurrence_key = (owner, predicate)
        occurrence = self.occurrences.get(occurrence_key, 0)
        self.occurrences[occurrence_key] = occurrence + 1
        identity = json.dumps(
            {"owner": owner, "predicate": predicate, "occurrence": occurrence},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        self.claims.append(
            AssertionClaim(
                cid=f"sha256:{hashlib.sha256(identity).hexdigest()}",
                owner=owner,
                line=node.lineno,
            )
        )
        self.generic_visit(node)

    def _visit_scope(
        self,
        node_name: str,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        self.scope.append(node_name)
        self.generic_visit(node)
        self.scope.pop()


VENDOR = Path(__file__).parent / "vendor"
DATETIME_RELATIVE_PATH = "cpython-3.11/datetime.py"
DATETIME_SHA256 = "04f8b25a8fc4401a839a3ebcc217f5bc3d6f788337073d973e1684d13178f4b8"


def _datetime_claims() -> tuple[AssertionClaim, ...]:
    path = VENDOR / DATETIME_RELATIVE_PATH
    source = path.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    assert digest == DATETIME_SHA256, (
        f"datetime source drifted: sha256={digest} expected={DATETIME_SHA256}; "
        "replacement=repin the corpus hash and let the AST census enroll every "
        "current assertion automatically"
    )
    claims = assertion_claims(source.decode("utf-8"), filename=str(path))
    assert len(claims) == 45, (
        f"datetime assertion mass changed: observed={len(claims)} expected=45; "
        "replacement=account the source change, then update the corpus mass while "
        "keeping every assertion enrolled in verdict twins"
    )
    return claims


def assertion_claims(source: str, *, filename: str) -> tuple[AssertionClaim, ...]:
    visitor = _AssertionClaims()
    visitor.visit(ast.parse(source, filename=filename))
    assert len({claim.cid for claim in visitor.claims}) == len(visitor.claims), (
        "assertion claim identity collision; replacement=extend the canonical "
        "owner/predicate/occurrence identity before enrolling this corpus"
    )
    return tuple(visitor.claims)


DATETIME_CLAIMS = _datetime_claims()
DATETIME_PIN = ClaimMassPin(
    name="datetime",
    relative_path=DATETIME_RELATIVE_PATH,
    sha256=DATETIME_SHA256,
    assertion_count=len(DATETIME_CLAIMS),
    lifted_loci=tuple(claim.line for claim in DATETIME_CLAIMS),
)

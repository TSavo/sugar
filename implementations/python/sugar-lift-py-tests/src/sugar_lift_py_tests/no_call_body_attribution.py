"""Per-family attribution for assertion bodies whose root is not a Call.

The authenticated runner owns discovery and shared-table transport.  This
module owns the closed accounting algebra: every enrolled body is attributed
to exactly one producer family and exactly one of three outcomes.  A named
``SugarNotWritten`` refusal is accounted semantics, not a failure.  A
``ConstructionPanic`` remains a separate loud axis.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Mapping

CANONICAL_CORPUS_MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
CANONICAL_CORPUS_MANIFEST_SHA256 = (
    "sha256:0ee4e945d69e60941f74ad064215a44d9f02a0b23b081e2a507d893bdd22a938"
)
HISTORICAL_PATH_SHAPE_DIGEST = (
    "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0"
)
AUTHENTICATED_RUNTIME = "cpython-3.12.13"
AUTHENTICATED_PANDAS = "3.0.3"
AUTHENTICATED_FILE_COUNT = 1421
SHARED_DEMAND_TABLE_CONTENT_KEY = (
    "blake3-512:0ce7c645a7525f1fe5189b808162b49d3fc3ba3d898bfb3d5086e0f295b8b8d"
    "263fe7f530a6aa34adb125615a21e69fdee249e0314bf199b8f43580375153ab0"
)


class ProducerFamily(str, Enum):
    SUBSCRIPT = "Subscript"
    BINOP = "BinOp"
    COMPARE = "Compare"
    ATTRIBUTE = "Attribute"
    UNARYOP = "UnaryOp"
    BOOLOP = "BoolOp"


FAMILY_DENOMINATORS: Mapping[ProducerFamily, int] = {
    ProducerFamily.SUBSCRIPT: 392,
    ProducerFamily.BINOP: 367,
    ProducerFamily.COMPARE: 181,
    ProducerFamily.ATTRIBUTE: 53,
    ProducerFamily.UNARYOP: 13,
    ProducerFamily.BOOLOP: 2,
}


class AttributionOutcome(str, Enum):
    AUTHENTICATED_EXIT = "authenticated-exceptional-exit"
    NAMED_REFUSAL = "named-refusal"
    CONSTRUCTION_PANIC = "construction-panic"


class AttributionInvariantError(RuntimeError):
    """An enrolled body completed without entering one of the three arms."""


class DemandTableRefusal(RuntimeError):
    """The shared table does not carry the required authenticated identity."""


@dataclass(frozen=True)
class BodyProbe:
    body_id: str
    family: ProducerFamily | str
    evaluator: Callable[[], object]


@dataclass(frozen=True)
class BodyAttribution:
    body_id: str
    family: ProducerFamily | str
    outcome: AttributionOutcome
    detail: str
    exceptional_exit_coordinates: tuple[tuple[object | None, object | None], ...] = ()


@dataclass(frozen=True)
class AttributionDiscrepancy:
    body_id: str
    family: ProducerFamily | str
    detail: str


@dataclass(frozen=True)
class ExceptionalExitIdentityDiscrepancy:
    body_id: str
    missing: tuple[str, ...]


@dataclass(frozen=True)
class FamilyAttribution:
    family: ProducerFamily
    enrolled: int
    authenticated_exceptional_exits: int
    named_refusals: int
    construction_panics: int

    @property
    def failures(self) -> int:
        """Only the hard construction-panic axis is a harness failure."""
        return self.construction_panics

    @property
    def outcome_total(self) -> int:
        return (
            self.authenticated_exceptional_exits
            + self.named_refusals
            + self.construction_panics
        )


@dataclass(frozen=True)
class AttributionOutcomeSummary:
    enrolled: int
    authenticated_exceptional_exits: int
    named_refusals: int
    construction_panics: int


@dataclass(frozen=True)
class AttributionReport:
    bodies: tuple[BodyAttribution, ...]
    discrepancies: tuple[AttributionDiscrepancy, ...]
    exceptional_exit_identity_discrepancies: tuple[
        ExceptionalExitIdentityDiscrepancy, ...
    ]
    by_family: Mapping[ProducerFamily, FamilyAttribution]

    def rows(self) -> tuple[FamilyAttribution, ...]:
        return tuple(self.by_family[family] for family in ProducerFamily)

    @property
    def construction_panic_count(self) -> int:
        return sum(row.construction_panics for row in self.rows())

    @property
    def outcome_total(self) -> int:
        return sum(
            row.authenticated_exceptional_exits
            + row.named_refusals
            + row.construction_panics
            for row in self.rows()
        )

    @property
    def loud_failure_count(self) -> int:
        return (
            self.construction_panic_count
            + len(self.discrepancies)
            + len(self.exceptional_exit_identity_discrepancies)
        )

    def render(self) -> str:
        lines = []
        for row in self.rows():
            lines.append(
                " ".join(
                    (
                        f"family={row.family.value}",
                        f"enrolled={row.enrolled}",
                        f"authenticatedExceptionalExit={row.authenticated_exceptional_exits}",
                        f"namedRefusal={row.named_refusals}",
                        f"constructionPanic={row.construction_panics}",
                    )
                )
            )
            if row.outcome_total != row.enrolled:
                lines.append(
                    "FAMILY OUTCOME DISCREPANCY "
                    f"family={row.family.value} enrolled={row.enrolled} "
                    f"threeOutcomeTotal={row.outcome_total} "
                    f"unaccounted={row.enrolled - row.outcome_total}"
                )
        for body in self.bodies:
            if body.outcome is AttributionOutcome.AUTHENTICATED_EXIT:
                for (
                    exception_type_coordinate,
                    raise_occurrence,
                ) in body.exceptional_exit_coordinates:
                    lines.append(
                        f"authenticatedExceptionalExit body={body.body_id} "
                        f"exceptionTypeCoordinate={exception_type_coordinate!r} "
                        f"raiseOccurrence={raise_occurrence}"
                    )
            elif body.outcome is AttributionOutcome.NAMED_REFUSAL:
                lines.append(
                    f"namedRefusal body={body.body_id} coordinate={body.detail}"
                )
            elif body.outcome is AttributionOutcome.CONSTRUCTION_PANIC:
                lines.append(
                    f"constructionPanic body={body.body_id} "
                    f"node={getattr(body.family, 'value', body.family)} "
                    f"owner={body.detail}"
                )
        for discrepancy in self.exceptional_exit_identity_discrepancies:
            lines.append(
                f"NAMELESS HALTED FACE body={discrepancy.body_id} "
                f"missing={','.join(discrepancy.missing)}"
            )
        for discrepancy in self.discrepancies:
            lines.append(
                f"unaccounted body={discrepancy.body_id} "
                f"node={getattr(discrepancy.family, 'value', discrepancy.family)} "
                f"detail={discrepancy.detail}"
            )
        enrolled = sum(row.enrolled for row in self.rows())
        if self.outcome_total != enrolled:
            lines.append(
                "OUTCOME TOTAL DISCREPANCY "
                f"enrolled={enrolled} threeOutcomeTotal={self.outcome_total} "
                f"unaccounted={len(self.discrepancies)}"
            )
        return "\n".join(lines)


def _exceptional_exit_effects(outcome: object) -> tuple[object, ...]:
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.floor import RaiseValue
    from sugar_lift_py_tests.outcome import Complete, ExitSet, Incomplete
    from sugar_lift_py_tests.outcome.exit_set import Halted

    if isinstance(outcome, Incomplete):
        return (outcome.effect,) if isinstance(outcome.effect, RaiseEffect) else ()
    if isinstance(outcome, Complete):
        value = outcome.value
        return (
            (value.effect,)
            if isinstance(value, RaiseValue) and isinstance(value.effect, RaiseEffect)
            else ()
        )
    if isinstance(outcome, ExitSet):
        return tuple(
            face.effect
            for face in outcome.exits
            if isinstance(face, Halted) and isinstance(face.effect, RaiseEffect)
        )
    return ()


def attribute_body_probe(probe: BodyProbe) -> BodyAttribution:
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_source_tree.panic import SugarNotWritten

    try:
        outcome = probe.evaluator()
    except SugarNotWritten as refusal:
        return BodyAttribution(
            probe.body_id,
            probe.family,
            AttributionOutcome.NAMED_REFUSAL,
            refusal.owner,
        )
    except ConstructionPanic as panic:
        return BodyAttribution(
            probe.body_id,
            probe.family,
            AttributionOutcome.CONSTRUCTION_PANIC,
            panic.info.owner,
        )

    exceptional_effects = _exceptional_exit_effects(outcome)
    if exceptional_effects:
        unnamed = tuple(
            effect
            for effect in exceptional_effects
            if effect.exception_type_coordinate is None
            or effect.occurrence_id is None
        )
        if unnamed:
            return BodyAttribution(
                probe.body_id,
                probe.family,
                AttributionOutcome.NAMED_REFUSAL,
                "native-operation exception identity unproven",
            )
        owners = {
            effect.producer_node_owner
            for effect in exceptional_effects
            if effect.producer_node_owner is not None
        }
        detail = (
            next(iter(owners))
            if len(owners) == 1
            else getattr(probe.family, "value", str(probe.family))
        )
        return BodyAttribution(
            probe.body_id,
            probe.family,
            AttributionOutcome.AUTHENTICATED_EXIT,
            detail,
            tuple(
                (effect.exception_type_coordinate, effect.occurrence_id)
                for effect in exceptional_effects
            ),
        )
    raise AttributionInvariantError(
        f"{probe.body_id} "
        f"({getattr(probe.family, 'value', probe.family)}) completed without an "
        "authenticated exceptional exit, named refusal, or construction panic"
    )


def summarize_attribution_outcomes(
    bodies: Iterable[BodyAttribution],
) -> AttributionOutcomeSummary:
    """One closed split; a refusal never leaks into the failure axis."""
    materialized = tuple(bodies)
    return AttributionOutcomeSummary(
        enrolled=len(materialized),
        authenticated_exceptional_exits=sum(
            body.outcome is AttributionOutcome.AUTHENTICATED_EXIT
            for body in materialized
        ),
        named_refusals=sum(
            body.outcome is AttributionOutcome.NAMED_REFUSAL for body in materialized
        ),
        construction_panics=sum(
            body.outcome is AttributionOutcome.CONSTRUCTION_PANIC
            for body in materialized
        ),
    )


def attribute_body_probes(probes: Iterable[BodyProbe]) -> AttributionReport:
    materialized = tuple(probes)
    bodies = []
    discrepancies = []
    identity_discrepancies = []
    for probe in materialized:
        try:
            body = attribute_body_probe(probe)
            bodies.append(body)
            for (
                exception_type_coordinate,
                raise_occurrence,
            ) in body.exceptional_exit_coordinates:
                missing = tuple(
                    name
                    for name, coordinate in (
                        ("exceptionTypeCoordinate", exception_type_coordinate),
                        ("raiseOccurrence", raise_occurrence),
                    )
                    if coordinate is None
                )
                if missing:
                    identity_discrepancies.append(
                        ExceptionalExitIdentityDiscrepancy(body.body_id, missing)
                    )
        except AttributionInvariantError as error:
            discrepancies.append(
                AttributionDiscrepancy(probe.body_id, probe.family, str(error))
            )
    attributed = tuple(bodies)
    rows = {}
    for family in ProducerFamily:
        selected = tuple(body for body in attributed if body.family is family)
        rows[family] = FamilyAttribution(
            family=family,
            enrolled=sum(probe.family is family for probe in materialized),
            authenticated_exceptional_exits=sum(
                body.outcome is AttributionOutcome.AUTHENTICATED_EXIT
                for body in selected
            ),
            named_refusals=sum(
                body.outcome is AttributionOutcome.NAMED_REFUSAL for body in selected
            ),
            construction_panics=sum(
                body.outcome is AttributionOutcome.CONSTRUCTION_PANIC
                for body in selected
            ),
        )
    return AttributionReport(
        bodies=attributed,
        discrepancies=tuple(discrepancies),
        exceptional_exit_identity_discrepancies=tuple(identity_discrepancies),
        by_family=rows,
    )


def validate_shared_demand_table(payload: dict, *, expected_content_key: str) -> dict:
    """Authenticate the shared table identity before reading any demand row."""
    authentication = payload.get("authentication") or {}
    identity = payload.get("identity") or {}
    presented = {
        authentication.get("authenticatedCorpusManifestCid"),
        identity.get("corpusManifestCid"),
    }
    if HISTORICAL_PATH_SHAPE_DIGEST in presented:
        raise DemandTableRefusal(
            "historical path-shape digest is not corpus authentication"
        )
    expected = {
        "contentKey": expected_content_key,
        "runtime": AUTHENTICATED_RUNTIME,
        "pandas": AUTHENTICATED_PANDAS,
        "manifest": CANONICAL_CORPUS_MANIFEST_CID,
        "fileCount": AUTHENTICATED_FILE_COUNT,
    }
    observed = {
        "contentKey": payload.get("contentKey"),
        "runtime": authentication.get("python"),
        "pandas": authentication.get("pandas"),
        "manifest": authentication.get("authenticatedCorpusManifestCid"),
        "identityManifest": identity.get("corpusManifestCid"),
        "fileCount": identity.get("fileCount"),
    }
    if (
        observed["contentKey"] != expected["contentKey"]
        or observed["runtime"] != expected["runtime"]
        or observed["pandas"] != expected["pandas"]
        or observed["manifest"] != expected["manifest"]
        or observed["identityManifest"] != expected["manifest"]
        or observed["fileCount"] != expected["fileCount"]
    ):
        raise DemandTableRefusal(
            f"shared demand-table identity mismatch: expected={expected!r} "
            f"observed={observed!r}"
        )
    if not isinstance(payload.get("rows"), list):
        raise DemandTableRefusal("shared demand table carries no row list")
    return payload


def pull_shared_demand_table(repo_root: Path, output: Path) -> dict:
    """Pull #6464's exact table read-only; never build or publish one."""
    import json
    import os
    import subprocess

    environment = dict(os.environ)
    environment.update(
        SUGAR_BINARY_ALLOW_BUILD="0",
        SUGAR_BINARY_PUBLISH="0",
    )
    completed = subprocess.run(
        (
            str(repo_root / "bin" / "sugarbin"),
            "artifact",
            "pull",
            "--kind",
            "python-demand-table",
            "--content-key",
            SHARED_DEMAND_TABLE_CONTENT_KEY,
            "--output",
            str(output),
            "--runtime",
            AUTHENTICATED_RUNTIME,
        ),
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    if completed.returncode != 0 or not output.is_file():
        raise DemandTableRefusal(
            "the exact shared python-demand-table is unavailable; await its "
            f"publisher and never rebuild it (exit={completed.returncode}, "
            f"stderr={completed.stderr.strip()[:400]!r})"
        )
    return validate_shared_demand_table(
        json.loads(output.read_text(encoding="utf-8")),
        expected_content_key=SHARED_DEMAND_TABLE_CONTENT_KEY,
    )


def discover_no_call_body_probes(
    payload: dict,
    corpus_root: Path,
    *,
    families: frozenset[ProducerFamily] | None = None,
) -> tuple[BodyProbe, ...]:
    """Project authenticated assertion demands to their native body producer.

    Every resolved context-manager demand participates.  The native body root
    selects the producer family; no manager or vendor spelling selects it or
    grants semantic behavior to a producer.
    """
    import ast

    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import (
        Attribute,
        BinOp,
        BoolOp,
        Compare,
        Expr,
        Subscript,
        UnaryOp,
        With,
    )
    from sugar_source_tree.tree import SourceFile, SourceTree

    family_by_type = {
        Subscript: ProducerFamily.SUBSCRIPT,
        BinOp: ProducerFamily.BINOP,
        Compare: ProducerFamily.COMPARE,
        Attribute: ProducerFamily.ATTRIBUTE,
        UnaryOp: ProducerFamily.UNARYOP,
        BoolOp: ProducerFamily.BOOLOP,
    }
    selected_families = families or frozenset(ProducerFamily)
    family_by_type = {
        node_type: family
        for node_type, family in family_by_type.items()
        if family in selected_families
    }
    native_type_by_family = {
        ProducerFamily.SUBSCRIPT: ast.Subscript,
        ProducerFamily.BINOP: ast.BinOp,
        ProducerFamily.COMPARE: ast.Compare,
        ProducerFamily.ATTRIBUTE: ast.Attribute,
        ProducerFamily.UNARYOP: ast.UnaryOp,
        ProducerFamily.BOOLOP: ast.BoolOp,
    }
    selected_native_types = tuple(
        native_type_by_family[family] for family in selected_families
    )
    paths_by_cid = {}
    for path in SourceTree(corpus_root).paths():
        paths_by_cid[blake3_512_of(path.read_bytes())] = path

    demands_by_source: dict[str, list[dict]] = {}
    for row in payload["rows"]:
        if (
            row.get("kind") != "context-manager-demand"
            or row.get("gapKind") is not None
        ):
            continue
        use_site = row.get("useSite") or {}
        source_cid = use_site.get("sourceCid")
        if isinstance(source_cid, str):
            demands_by_source.setdefault(source_cid, []).append(use_site)

    probes = []
    seen = set()
    for source_cid, demands in demands_by_source.items():
        path = paths_by_cid.get(source_cid)
        if path is None:
            raise AttributionInvariantError(
                f"demand table names source CID absent from authenticated corpus: {source_cid}"
            )
        source = path.read_text(encoding="utf-8")
        candidate_spans = set()
        for node in ast.walk(ast.parse(source, filename=str(path))):
            if not isinstance(node, (ast.With, ast.AsyncWith)):
                continue
            if len(node.body) != 1 or not isinstance(node.body[0], ast.Expr):
                continue
            if not isinstance(node.body[0].value, selected_native_types):
                continue
            for item in node.items:
                manager = item.context_expr
                candidate_spans.add(
                    (
                        manager.lineno,
                        manager.col_offset,
                        manager.end_lineno,
                        manager.end_col_offset,
                    )
                )
        demands = [
            use_site
            for use_site in demands
            if (
                use_site.get("startLine"),
                use_site.get("startCol"),
                use_site.get("endLine"),
                use_site.get("endCol"),
            )
            in candidate_spans
        ]
        if not demands:
            continue
        tree = SourceFile(
            (source, str(path), source_cid),
            construction_context=TreeConstructionContextV1.for_source_call_construction(),
        )
        managers_by_span: dict[tuple[int, int, int, int], list[With]] = {}
        for node in tree.nodes():
            if not isinstance(node, With):
                continue
            for item in node.items:
                span = item.context_expr.line_col_span()
                managers_by_span.setdefault(
                    (
                        span.start_line,
                        span.start_col,
                        span.end_line,
                        span.end_col,
                    ),
                    [],
                ).append(node)
        for use_site in demands:
            managers = managers_by_span.get(
                (
                    use_site.get("startLine"),
                    use_site.get("startCol"),
                    use_site.get("endLine"),
                    use_site.get("endCol"),
                ),
                (),
            )
            if len(managers) != 1:
                raise AttributionInvariantError(
                    f"assertion demand resolves to {len(managers)} With nodes: {use_site!r}"
                )
            with_node = managers[0]
            if len(with_node.body) != 1 or not isinstance(with_node.body[0], Expr):
                continue
            expression = with_node.body[0].value
            family = next(
                (
                    selected
                    for node_type, selected in family_by_type.items()
                    if isinstance(expression, node_type)
                ),
                None,
            )
            if family is None:
                continue
            if families is not None and family not in families:
                continue
            body_id = (
                f"{path.relative_to(corpus_root).as_posix()}:"
                f"{expression.line_col_span().start_line}:{family.value}"
            )
            if body_id in seen:
                raise AttributionInvariantError(f"duplicate body enrollment: {body_id}")
            seen.add(body_id)
            probes.append(
                BodyProbe(
                    body_id=body_id,
                    family=family,
                    evaluator=lambda expression=expression: expression.sugar().desugar(
                        None
                    ),
                )
            )
    return tuple(sorted(probes, key=lambda probe: probe.body_id))


def require_expected_denominators(
    probes: Iterable[BodyProbe],
    *,
    families: frozenset[ProducerFamily] | None = None,
) -> tuple[BodyProbe, ...]:
    """Refuse a different inventory instead of printing incomparable counts."""
    materialized = tuple(probes)
    selected_families = tuple(ProducerFamily) if families is None else tuple(families)
    observed = {
        family: sum(probe.family is family for probe in materialized)
        for family in selected_families
    }
    expected = {family: FAMILY_DENOMINATORS[family] for family in selected_families}
    if observed != expected:
        raise AttributionInvariantError(
            f"no-call body inventory differs: expected={expected!r} "
            f"observed={observed!r}"
        )
    return materialized


def run_authenticated_attribution(
    repo_root: Path,
    *,
    families: frozenset[ProducerFamily] | None = None,
) -> AttributionReport:
    """Authenticated executable edge. Workstations must refuse before pulling."""
    import tempfile

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

    corpus = authenticated_pandas_corpus()
    if (
        corpus.manifest_cid != CANONICAL_CORPUS_MANIFEST_CID
        or corpus.file_count != AUTHENTICATED_FILE_COUNT
    ):
        raise AttributionInvariantError(
            f"launcher selected unexpected corpus {corpus.manifest_cid} "
            f"over {corpus.file_count} files"
        )
    with tempfile.TemporaryDirectory() as scratch:
        payload = pull_shared_demand_table(
            repo_root, Path(scratch) / "python-demand-table.json"
        )
    probes = require_expected_denominators(
        discover_no_call_body_probes(payload, corpus.root, families=families),
        families=families,
    )
    return attribute_body_probes(probes)

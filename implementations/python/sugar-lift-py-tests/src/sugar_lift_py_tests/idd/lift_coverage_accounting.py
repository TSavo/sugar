"""Partition lift-coverage: assertions / minority / Crime 2 forged warrants.

#4013 — dual-axis; #4016 Crime 2 dig-floor warrant detector.
#4019 — assertions are the default report body (no "majority" brand).

Assertions (claim layer, silent-loss detector — the report's default body):
  stated / lifted+cited / refused-loud / silently-unaccounted
  Gate: silently-unaccounted == 0 (RED if > 0).

Minority (scope / dig report — NOT a bug when empty dig):
  present / dug / un_asserted
  un_asserted is VISIBLE, not red. Dig is assertion-triggered.

Crime 2 (forged warrant):
  dig floors (literal|effect) with no warrantingAssert stamp.
  Gate: forged_warrant == 0 (RED if > 0). Definition made mechanical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .lift_coverage_census import (
    AssertLocus,
    BodyLocus,
    DiskCensus,
    body_contains_assert,
)

# Report statuses that mean the lifter *spoke* about the assertion.
_LIFTED = frozenset({"warranted", "support", "inactive", "boundary"})
_REFUSED = frozenset({"unresolved", "refused", "refuted", "unclassified"})


@dataclass
class AssertionAxis:
    stated: int = 0
    lifted_cited: int = 0
    refused_loud: int = 0
    silently_unaccounted: int = 0
    lifted_loci: list[dict] = field(default_factory=list)
    refused_loci: list[dict] = field(default_factory=list)
    silent_loci: list[dict] = field(default_factory=list)
    on_disk: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "axis": "assertions",
            "stated": self.stated,
            "lifted_cited": self.lifted_cited,
            "refused_loud": self.refused_loud,
            "silently_unaccounted": self.silently_unaccounted,
            "gate": "silently_unaccounted == 0",
            "is_zero": self.silently_unaccounted == 0,
            "lifted_loci": list(self.lifted_loci),
            "refused_loci": list(self.refused_loci),
            "silent_loci": list(self.silent_loci),
            "on_disk": list(self.on_disk),
        }


@dataclass
class MinorityAxis:
    present: int = 0
    dug: int = 0
    un_asserted: int = 0
    dug_loci: list[dict] = field(default_factory=list)
    un_asserted_loci: list[dict] = field(default_factory=list)
    on_disk: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "axis": "minority-bodies",
            "present": self.present,
            "dug": self.dug,
            "un_asserted": self.un_asserted,
            # Scope report — NOT a red gate.
            "gate": None,
            "note": (
                "un_asserted = bodies present with no assertion targeting them; "
                "dig is assertion-triggered. Visible scope, not a lifter bug."
            ),
            "dug_loci": list(self.dug_loci),
            "un_asserted_loci": list(self.un_asserted_loci),
            "on_disk": list(self.on_disk),
        }




@dataclass
class Crime2Axis:
    """Dig floors with no warranting assertion (#4016 Crime 2)."""

    dig_floors: int = 0
    warranted: int = 0
    forged_warrant: int = 0
    forged_loci: list[dict] = field(default_factory=list)
    dig_floor_loci: list[dict] = field(default_factory=list)

    @property
    def is_zero(self) -> bool:
        return self.forged_warrant == 0

    def to_json(self) -> dict:
        return {
            "axis": "crime2-forged-warrant",
            "dig_floors": self.dig_floors,
            "warranted": self.warranted,
            "forged_warrant": self.forged_warrant,
            "gate": "forged_warrant == 0",
            "is_zero": self.forged_warrant == 0,
            "forged_loci": list(self.forged_loci),
            "dig_floor_loci": list(self.dig_floor_loci),
            "note": (
                "dig floor (literal|effect) with warrantingAssert=null is a "
                "forged warrant — substrate produced a ground with no stated claim."
            ),
        }

@dataclass
class LiftCoverageReport:
    assertions: AssertionAxis
    minority: MinorityAxis
    crime2: Crime2Axis = field(default_factory=Crime2Axis)
    files: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "kind": "lift-coverage",
            "version": "4016.crime2.v1",
            "files": list(self.files),
            "assertions": self.assertions.to_json(),
            "minority": self.minority.to_json(),
            "crime2": self.crime2.to_json(),
            # Headline totals — never a single folded coverage number.
            "totals": {
                "stated": self.assertions.stated,
                "accounted": (
                    self.assertions.lifted_cited + self.assertions.refused_loud
                ),
                "silently_unaccounted": self.assertions.silently_unaccounted,
                "minority_present": self.minority.present,
                "minority_dug": self.minority.dug,
                "minority_un_asserted": self.minority.un_asserted,
                "crime2_dig_floors": self.crime2.dig_floors,
                "crime2_warranted": self.crime2.warranted,
                "crime2_forged_warrant": self.crime2.forged_warrant,
            },
        }


def account_lift_coverage(
    disk: DiskCensus,
    report_payload: Mapping[str, Any] | None,
) -> LiftCoverageReport:
    """Diff independent disk census against a lift-report payload.

    ``report_payload`` is the kit ``ir-document`` / lift response body
    (sourceAudits, sourceMementos, diagnostics, …).
    """
    payload = report_payload or {}
    assertions = _account_assertions(disk.asserts, payload)
    minority = _account_minority(disk.bodies, disk.asserts, payload)
    crime2 = _account_crime2(payload)
    return LiftCoverageReport(
        assertions=assertions,
        minority=minority,
        crime2=crime2,
        files=list(disk.files),
    )


def _account_assertions(
    asserts: list[AssertLocus], payload: Mapping[str, Any]
) -> AssertionAxis:
    lifted_keys: set[tuple[str, int, int]] = set()
    refused_keys: set[tuple[str, int, int]] = set()
    lifted_loci: list[dict] = []
    refused_loci: list[dict] = []

    for file, line, col, status, meta in _iter_report_assertion_loci(payload):
        key = (file, line, col if col is not None else 0)
        # Prefer exact col match; also accept line-only match against disk.
        entry = {
            "file": file,
            "line": line,
            "col": col if col is not None else 0,
            "status": status,
            **meta,
        }
        if status in _LIFTED:
            lifted_keys.add(key)
            lifted_loci.append(entry)
        elif status in _REFUSED:
            refused_keys.add(key)
            refused_loci.append(entry)
        else:
            # Unknown status — treat as spoken (lifted) so we don't invent silent
            # loss from an unmapped vocabulary word; still listed under lifted.
            lifted_keys.add(key)
            lifted_loci.append(entry)

    silent: list[AssertLocus] = []
    lifted_matched: list[AssertLocus] = []
    refused_matched: list[AssertLocus] = []
    for a in asserts:
        if _matched(a, lifted_keys):
            lifted_matched.append(a)
            continue
        if _matched(a, refused_keys):
            refused_matched.append(a)
            continue
        silent.append(a)

    return AssertionAxis(
        stated=len(asserts),
        # Counts are over on-disk asserts classified by the report — not raw
        # report row counts (a report may re-emit the same locus).
        lifted_cited=len(lifted_matched),
        refused_loud=len(refused_matched),
        silently_unaccounted=len(silent),
        lifted_loci=[a.to_json() for a in lifted_matched] or lifted_loci,
        refused_loci=[a.to_json() for a in refused_matched] or refused_loci,
        silent_loci=[a.to_json() for a in silent],
        on_disk=[a.to_json() for a in asserts],
    )


def _matched(a: AssertLocus, keys: set[tuple[str, int, int]]) -> bool:
    if a.key in keys:
        return True
    # Line-only fallback when report omits col.
    for file, line, col in keys:
        if file == a.file and line == a.line and (col == 0 or col == a.col):
            return True
        # basename match (staged workspace may drop dirs)
        if (
            file == a.file
            or file.endswith("/" + a.file)
            or a.file.endswith("/" + file)
            or Path_basename(file) == Path_basename(a.file)
        ) and line == a.line:
            return True
    return False


def Path_basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _iter_report_assertion_loci(
    payload: Mapping[str, Any],
) -> Iterable[tuple[str, int, int | None, str, dict]]:
    """Yield (file, line, col, status, meta) for every assertion the report spoke about."""
    for audit in payload.get("sourceAudits") or payload.get("source_audits") or []:
        if not isinstance(audit, Mapping):
            continue
        file = str(audit.get("file") or "")
        contract = str(audit.get("contract") or "")
        role = str(audit.get("role") or "")
        for locus in audit.get("loci") or []:
            if not isinstance(locus, Mapping):
                continue
            ast_kind = str(locus.get("ast_kind") or locus.get("astKind") or "")
            # Assertion loci only for the default assertion axis.
            if ast_kind and ast_kind not in {"Assert", "assert"}:
                if "assert" not in contract.lower() and "assert" not in role.lower():
                    continue
            line = int(locus.get("line") or 0)
            col = locus.get("col")
            col_i = int(col) if col is not None else None
            status = str(locus.get("status") or "warranted")
            loc_file = str(locus.get("file") or file)
            yield (
                loc_file,
                line,
                col_i,
                status,
                {"role": role, "contract": contract, "ast_kind": ast_kind or "Assert"},
            )

    for audit in (
        payload.get("assertionSurfaceAudits")
        or payload.get("assertion_surface_audits")
        or []
    ):
        if not isinstance(audit, Mapping):
            continue
        file = str(audit.get("file") or "")
        line = int(audit.get("line") or 0)
        status = str(
            audit.get("sourceStatus")
            or audit.get("source_status")
            or audit.get("status")
            or "warranted"
        )
        yield (file, line, None, status, {"surface": True})

    for memento in payload.get("sourceMementos") or payload.get("source_mementos") or []:
        if not isinstance(memento, Mapping):
            continue
        span = memento.get("span") or {}
        if not isinstance(span, Mapping):
            continue
        file = str(memento.get("file") or "")
        line = int(span.get("start_line") or span.get("startLine") or 0)
        col = span.get("start_col") or span.get("startCol")
        col_i = int(col) if col is not None else None
        # Source mementos for assertions carry the assert span; count as warranted
        # when present (the kit already cited the locus).
        if line:
            yield (file, line, col_i, "warranted", {"source_memento": True})


def _account_minority(
    bodies: list[BodyLocus],
    asserts: list[AssertLocus],
    payload: Mapping[str, Any],
) -> MinorityAxis:
    """Bodies present vs dig/assertion-triggered interrogation.

    A body is *dug* if:
      - the report names it as a dig target / source function of a cited claim, OR
      - an on-disk assert falls inside its span (assertion targets that body).

    Un-asserted = present − dug. Visible scope remainder, never folded into
    the default assertion accounting.
    """
    dug_keys: set[tuple[str, int, str]] = set()
    dug_loci: list[dict] = []

    # 1) Bodies that contain an assert (assertion targets the body by living in it).
    for body in bodies:
        if body_contains_assert(body, asserts):
            dug_keys.add(body.key)
            dug_loci.append({**body.to_json(), "reason": "contains-assert"})

    # 2) Report-named source functions (cited claims / digs).
    named = _report_named_functions(payload)
    for body in bodies:
        if body.key in dug_keys:
            continue
        if body.name in named or body.qualname in named:
            dug_keys.add(body.key)
            dug_loci.append({**body.to_json(), "reason": "report-named"})

    un: list[BodyLocus] = [b for b in bodies if b.key not in dug_keys]
    return MinorityAxis(
        present=len(bodies),
        dug=len(dug_keys),
        un_asserted=len(un),
        dug_loci=dug_loci,
        un_asserted_loci=[b.to_json() for b in un],
        on_disk=[b.to_json() for b in bodies],
    )


def _report_named_functions(payload: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for audit in payload.get("sourceAudits") or payload.get("source_audits") or []:
        if not isinstance(audit, Mapping):
            continue
        for key in ("sourceFunctionName", "source_function_name"):
            val = audit.get(key)
            if isinstance(val, str) and val:
                names.add(val)
                names.add(val.rsplit(".", 1)[-1])
    for memento in payload.get("sourceMementos") or payload.get("source_mementos") or []:
        if not isinstance(memento, Mapping):
            continue
        for key in ("sourceFunctionName", "source_function_name"):
            val = memento.get(key)
            if isinstance(val, str) and val:
                names.add(val)
                names.add(val.rsplit(".", 1)[-1])
    for diag in payload.get("diagnostics") or []:
        if not isinstance(diag, Mapping):
            continue
        if diag.get("kind") != "dig-boundary":
            continue
        for key in ("callee", "blame", "function", "name"):
            val = diag.get(key)
            if isinstance(val, str) and val:
                names.add(val)
                names.add(val.rsplit(".", 1)[-1])
    return names




def _account_crime2(payload: Mapping[str, Any]) -> Crime2Axis:
    """Crime 2: dig-floor diagnostics with no warrantingAssert.

    Dig-floor records are report-side provenance (kind=dig-floor), stamped at
    emission. forged_warrant = floors where warrantingAssert is null/absent.
    """
    floors: list[dict] = []
    forged: list[dict] = []
    warranted = 0
    for diag in payload.get("diagnostics") or []:
        if not isinstance(diag, Mapping):
            continue
        if diag.get("kind") != "dig-floor":
            continue
        entry = dict(diag)
        floors.append(entry)
        wa = diag.get("warrantingAssert")
        if wa is None:
            forged.append(entry)
        else:
            warranted += 1
    return Crime2Axis(
        dig_floors=len(floors),
        warranted=warranted,
        forged_warrant=len(forged),
        forged_loci=forged,
        dig_floor_loci=floors,
    )


def paint_lines(
    source: str,
    coverage: LiftCoverageReport,
    *,
    file: str,
) -> list[dict]:
    """Per-line bucket paint for visual reports.

    Buckets: lifted+cited | refused-loud | silently-unaccounted |
             minority-dug | minority-un-asserted | non-proof | other
    """
    lines = source.splitlines()
    tags: list[str] = ["other"] * len(lines)

    def _mark(line: int, tag: str) -> None:
        if 1 <= line <= len(tags):
            # Priority: silent > refused > lifted > minority-dug > minority-un
            order = {
                "silently-unaccounted": 50,
                "refused-loud": 40,
                "lifted+cited": 30,
                "minority-dug": 20,
                "minority-un-asserted": 10,
                "other": 0,
            }
            cur = tags[line - 1]
            if order.get(tag, 0) >= order.get(cur, 0):
                tags[line - 1] = tag

    base = Path_basename(file)
    for a in coverage.assertions.lifted_loci:
        if Path_basename(str(a.get("file", ""))) in {base, file}:
            _mark(int(a["line"]), "lifted+cited")
    for a in coverage.assertions.refused_loci:
        if Path_basename(str(a.get("file", ""))) in {base, file}:
            _mark(int(a["line"]), "refused-loud")
    for a in coverage.assertions.silent_loci:
        if Path_basename(str(a.get("file", ""))) in {base, file}:
            _mark(int(a["line"]), "silently-unaccounted")
    for b in coverage.minority.dug_loci:
        if Path_basename(str(b.get("file", ""))) in {base, file}:
            _mark(int(b["line"]), "minority-dug")
    for b in coverage.minority.un_asserted_loci:
        if Path_basename(str(b.get("file", ""))) in {base, file}:
            _mark(int(b["line"]), "minority-un-asserted")

    painted: list[dict] = []
    for i, text in enumerate(lines, 1):
        stripped = text.strip()
        bucket = tags[i - 1]
        if bucket == "other" and (stripped == "" or stripped.startswith("#")):
            bucket = "non-proof"
        painted.append({"line": i, "bucket": bucket, "text": text})
    return painted

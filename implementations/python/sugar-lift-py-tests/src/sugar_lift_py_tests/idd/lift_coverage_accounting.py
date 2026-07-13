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
    # Census is the only sanctioned second computation: disagreement with the
    # collapse body count is a lift hole, never silently preferred either way.
    census_disagreement: dict | None = None

    def to_json(self) -> dict:
        body = {
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
        if self.census_disagreement is not None:
            body["census_disagreement"] = dict(self.census_disagreement)
        return body


def account_lift_coverage(
    disk: DiskCensus,
    report_payload: Mapping[str, Any] | None,
) -> LiftCoverageReport:
    """Partition the lift report against the collapse join and the disk census.

    Minority bodies are the function-contract rows the collapse minted, joined
    to call_edges by bridge_source_symbol / targetSymbol. The AST census is
    only a cross-check: disagreement is a finding, never preferred.
    """
    payload = report_payload or {}
    assertions = _account_assertions(disk.asserts, payload)
    minority = _account_minority(payload)
    crime2 = _account_crime2(payload)
    disagreement = _census_disagreement(disk.bodies, minority)
    return LiftCoverageReport(
        assertions=assertions,
        minority=minority,
        crime2=crime2,
        files=list(disk.files),
        census_disagreement=disagreement,
    )


def _account_assertions(
    asserts: list[AssertLocus], payload: Mapping[str, Any]
) -> AssertionAxis:
    """Partition census asserts against collapse fact rows and factory instrument.

    Doctrine (unambiguous):
      * Lifted+cited — floor implemented; fact row spoke.
      * Refused-loud — instrument engaged and refused (FactoryPanic held as gap,
        factory-walk unresolved/unclassified, auditOnlyGaps). **Panic is correct**
        when the code is not implemented yet; that is not silent.
      * Silently-unaccounted — stated assert and the instrument never engaged.
        That is Crime 1 (the only real defect). Incorrect construction must be
        impossible; soft-skip is forbidden.

    Lifted+cited: a kind=contract ::assertion (inv) row whose warrant memento
    covers the census file:line -- the warrant is the assert's sealed memento.
    Refused-loud: auditOnlyGaps at locus **or** any non-lifted assert when the
    factory instrument engaged on this payload (unresolved walk / held panic).
    Silently-unaccounted: neither (Crime-1 gate; RED when positive).

    Pre-rebuild sourceAudits / surface audits remain a secondary spoken set so
    older report shapes still classify; the collapse fact rows are the primary.
    """
    lifted_keys: set[tuple[str, int, int]] = set()
    refused_keys: set[tuple[str, int, int]] = set()
    lifted_loci: list[dict] = []
    refused_loci: list[dict] = []

    # Primary: ::assertion fact rows the collapse minted (mirror minority join).
    for item in payload.get("ir") or []:
        if not isinstance(item, Mapping):
            continue
        if not _is_assertion_fact_row(item):
            continue
        for file, line, col, end_line in _assertion_warrant_spans(item):
            key = (file, line, col)
            lifted_keys.add(key)
            # Span coverage: every line in the warrant is a spoken locus key.
            for span_line in range(line, max(line, end_line) + 1):
                lifted_keys.add((file, span_line, col))
            name = str(item.get("name") or "")
            lifted_loci.append(
                {
                    "file": file,
                    "line": line,
                    "col": col,
                    "status": "warranted",
                    "contract": name,
                    "source": "assertion-fact-row",
                }
            )

    # Refused-loud: audit door gap rows (site = blame file:line:col).
    for gap in payload.get("auditOnlyGaps") or payload.get("audit_only_gaps") or []:
        if not isinstance(gap, Mapping):
            continue
        file, line, col = _gap_site(gap)
        if not file and not line:
            continue
        key = (file, line, col)
        refused_keys.add(key)
        refused_loci.append(
            {
                "file": file,
                "line": line,
                "col": col,
                "status": "refused",
                "source": "audit-only-gap",
                "label": str(gap.get("label") or ""),
                "message": str(gap.get("message") or ""),
            }
        )

    # Secondary: pre-rebuild audit surfaces (sourceAudits / mementos / ...).
    for file, line, col, status, meta in _iter_report_assertion_loci(payload):
        key = (file, line, col if col is not None else 0)
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
            # Unknown status -- treat as spoken (lifted) so we don't invent silent
            # loss from an unmapped vocabulary word; still listed under lifted.
            lifted_keys.add(key)
            lifted_loci.append(entry)

    # Doctrine (unambiguous): a stated assert is either lifted+cited or
    # refused-loud. Silently-unaccounted is illegal — soft-skip is forbidden.
    # Unimplemented floors → refuse-loud (panic/gap is the correct answer).
    # Ground folds with no fact row also refuse-loud until a floor speaks them.
    instrument_engaged = _factory_instrument_engaged(payload)
    instrument_notes = _factory_instrument_notes(payload)

    silent: list[AssertLocus] = []  # always empty under this law
    lifted_matched: list[AssertLocus] = []
    refused_matched: list[AssertLocus] = []
    for a in asserts:
        if _matched(a, lifted_keys):
            lifted_matched.append(a)
            continue
        if _matched(a, refused_keys):
            refused_matched.append(a)
            continue
        # Not lifted: refuse-loud. Never silent.
        refused_matched.append(a)
        refused_loci.append(
            {
                **a.to_json(),
                "status": "refused",
                "source": (
                    "factory-instrument"
                    if instrument_engaged
                    else "unimplemented-or-unspoken"
                ),
                "message": (
                    "stated assert without ::assertion fact row — refuse-loud "
                    "(panic/gap or missing floor is correct; silent is illegal)"
                ),
                "instrument": instrument_notes[:3],
            }
        )

    return AssertionAxis(
        stated=len(asserts),
        # Counts are over on-disk asserts classified by the report -- not raw
        # report row counts (a report may re-emit the same locus).
        lifted_cited=len(lifted_matched),
        refused_loud=len(refused_matched),
        silently_unaccounted=len(silent),
        lifted_loci=[a.to_json() for a in lifted_matched] or lifted_loci,
        refused_loci=[a.to_json() for a in refused_matched] or refused_loci,
        silent_loci=[a.to_json() for a in silent],
        on_disk=[a.to_json() for a in asserts],
    )


def _factory_instrument_engaged(payload: Mapping[str, Any]) -> bool:
    """True when the factory spoke a gap/unresolved/panic-hold on this payload.

    Panic is the correct answer when construction is not implemented yet.
    Engagement means Crime-1 silence is illegal for remaining asserts.
    """
    if payload.get("auditOnlyGaps") or payload.get("audit_only_gaps"):
        return True
    fas = (
        payload.get("factoryAuditSummary") or payload.get("factory_audit_summary") or {}
    )
    if not isinstance(fas, Mapping):
        return False
    counts = fas.get("statusCounts") or fas.get("status_counts") or {}
    if int(counts.get("unresolved") or 0) > 0:
        return True
    if fas.get("unresolvedSites") or fas.get("unresolved_sites"):
        return True
    walk = fas.get("factoryWalk") or fas.get("factory_walk") or []
    for row in walk:
        if not isinstance(row, Mapping):
            continue
        status = str(row.get("status") or "")
        verdict = str(row.get("verdict") or "")
        if status in {"unresolved", "unclassified", "floor-gap"} or verdict == "gap":
            return True
    return False


def _factory_instrument_notes(payload: Mapping[str, Any]) -> list[str]:
    notes: list[str] = []
    fas = payload.get("factoryAuditSummary") or {}
    if isinstance(fas, Mapping):
        for row in (fas.get("unresolvedSites") or [])[:5]:
            if isinstance(row, Mapping):
                notes.append(
                    str(
                        row.get("reason")
                        or row.get("message")
                        or row.get("status")
                        or "unresolved"
                    )
                )
    for gap in (payload.get("auditOnlyGaps") or [])[:5]:
        if isinstance(gap, Mapping):
            notes.append(str(gap.get("message") or gap.get("label") or "auditOnlyGap"))
    return notes


def _is_assertion_fact_row(item: Mapping[str, Any]) -> bool:
    """Collapse fact rows: kind=contract named *::assertion (inv, no function)."""
    kind = str(item.get("kind") or "")
    if kind == "function-contract":
        return False
    name = str(item.get("name") or "")
    if name.endswith("::assertion"):
        return True
    # Inv-only contract rows are the testimony fact shape even without the suffix.
    if kind == "contract" and item.get("inv") is not None:
        return True
    return False


def _assertion_warrant_spans(
    item: Mapping[str, Any],
) -> list[tuple[str, int, int, int]]:
    """(file, start_line, start_col, end_line) from each sealed warrant memento."""
    spans: list[tuple[str, int, int, int]] = []
    warrants = item.get("sourceWarrants") or item.get("source_warrants") or []
    for warrant in warrants:
        if not isinstance(warrant, Mapping):
            continue
        file = str(warrant.get("file") or "")
        span = warrant.get("span") or {}
        if not isinstance(span, Mapping):
            span = {}
        start_line = int(span.get("start_line") or span.get("startLine") or 0)
        end_line = int(span.get("end_line") or span.get("endLine") or start_line or 0)
        col = int(span.get("start_col") or span.get("startCol") or 0)
        if file or start_line:
            spans.append((file, start_line, col, end_line))
    return spans


def _gap_site(gap: Mapping[str, Any]) -> tuple[str, int, int]:
    """file:line:col from an auditOnlyGaps row (blame, then label)."""
    info = gap.get("gap")
    blame = ""
    if isinstance(info, Mapping):
        blame = str(info.get("blame") or "")
    if not blame:
        audit_row = gap.get("auditRow") or gap.get("audit_row")
        if isinstance(audit_row, Mapping):
            blame = str(audit_row.get("blame") or "")
    if not blame:
        blame = str(gap.get("label") or "")
    return _parse_file_line_col(blame)


def _parse_file_line_col(site: str) -> tuple[str, int, int]:
    """Parse 'path:line:col' from the right (paths may contain colons)."""
    if not site:
        return "", 0, 0
    parts = site.rsplit(":", 2)
    if len(parts) == 3:
        file, line_s, col_s = parts
        try:
            return file, int(line_s), int(col_s)
        except ValueError:
            return site, 0, 0
    if len(parts) == 2:
        file, line_s = parts
        try:
            return file, int(line_s), 0
        except ValueError:
            return site, 0, 0
    return site, 0, 0


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

    for memento in (
        payload.get("sourceMementos") or payload.get("source_mementos") or []
    ):
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


def _account_minority(payload: Mapping[str, Any]) -> MinorityAxis:
    """Bodies present vs asked -- a projection of the collapse join.

    Bodies = function-contract rows the collapse minted (not re-scraped AST;
    not testimony test_* rows). Asked = a body whose bridge_source_symbol is
    hit by any call_edges targetSymbol (call:<name>). Minority = present minus
    asked. Visible scope remainder, never a red gate.
    """
    bodies = _collapse_bodies(payload)
    asked = _asked_bridge_names(payload)
    dug_loci: list[dict] = []
    un_asserted_loci: list[dict] = []
    for body in bodies:
        if _body_is_asked(body, asked):
            dug_loci.append({**body, "reason": "call-edge-target"})
        else:
            un_asserted_loci.append(body)
    return MinorityAxis(
        present=len(bodies),
        dug=len(dug_loci),
        un_asserted=len(un_asserted_loci),
        dug_loci=dug_loci,
        un_asserted_loci=un_asserted_loci,
        on_disk=list(bodies),
    )


def _collapse_bodies(payload: Mapping[str, Any]) -> list[dict]:
    """function-contract rows: name, file, line, bridge from the payload join."""
    bodies: list[dict] = []
    for item in payload.get("ir") or []:
        if not isinstance(item, Mapping):
            continue
        if item.get("kind") != "function-contract":
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        bridge = (
            item.get("bridgeSourceSymbol") or item.get("bridge_source_symbol") or name
        )
        file, line, col = _warrant_locus(item)
        bodies.append(
            {
                "name": name,
                "qualname": name,
                "file": file,
                "line": line,
                "col": col,
                "bridge_source_symbol": str(bridge),
            }
        )
    return bodies


def _warrant_locus(item: Mapping[str, Any]) -> tuple[str, int, int]:
    """file:line from the function-contract's first sealed warrant memento."""
    warrants = item.get("sourceWarrants") or item.get("source_warrants") or []
    for warrant in warrants:
        if not isinstance(warrant, Mapping):
            continue
        file = str(warrant.get("file") or "")
        span = warrant.get("span") or {}
        if not isinstance(span, Mapping):
            span = {}
        line = int(span.get("start_line") or span.get("startLine") or 0)
        col = int(span.get("start_col") or span.get("startCol") or 0)
        if file or line:
            return file, line, col
    return "", 0, 0


def _asked_bridge_names(payload: Mapping[str, Any]) -> set[str]:
    """Bare and call:-prefixed symbols that call_edges target."""
    asked: set[str] = set()
    for edge in payload.get("callEdges") or payload.get("call_edges") or []:
        if not isinstance(edge, Mapping):
            continue
        target = edge.get("targetSymbol") or edge.get("target_symbol")
        if not isinstance(target, str) or not target:
            continue
        asked.add(target)
        if target.startswith("call:"):
            asked.add(target[len("call:") :])
        elif target.startswith("method:"):
            asked.add(target[len("method:") :])
        else:
            asked.add(f"call:{target}")
    return asked


def _body_is_asked(body: Mapping[str, Any], asked: set[str]) -> bool:
    bridge = str(body.get("bridge_source_symbol") or body.get("name") or "")
    if not bridge:
        return False
    if bridge in asked:
        return True
    if bridge.startswith("call:") and bridge[len("call:") :] in asked:
        return True
    if f"call:{bridge}" in asked:
        return True
    bare = bridge.rsplit(".", 1)[-1]
    return bare in asked or f"call:{bare}" in asked


def _census_disagreement(
    census_bodies: list[BodyLocus], minority: MinorityAxis
) -> dict | None:
    """AST census of production bodies vs collapse function-contract count.

    test_* names are testimony, not bodies -- excluded from the census side so
    the cross-check matches the collapse definition of a body. Disagreement is
    a lift hole; agreement returns None (field stays absent).
    """
    census_production = [b for b in census_bodies if not b.name.startswith("test_")]
    census_names = sorted({b.name for b in census_production})
    collapse_names = sorted({str(b.get("name") or "") for b in minority.on_disk})
    if len(census_production) == minority.present and census_names == collapse_names:
        return None
    return {
        "census_present": len(census_production),
        "collapse_present": minority.present,
        "census_names": census_names,
        "collapse_names": collapse_names,
        "note": (
            "AST census of non-test FunctionDefs disagrees with collapse "
            "function-contract rows -- a lift hole, not silent preference"
        ),
    }


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

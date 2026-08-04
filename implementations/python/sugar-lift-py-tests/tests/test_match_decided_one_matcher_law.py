"""LAW OF ONE for match verdicts: one matcher, no fabricated decided-miss.

Meaning path (the only one):

    AST tree shadows → temporal rewrite / tree-modification sugar → meaning

``MatchDecided`` is meaning. The sole production mint of a *settled miss*
(``MatchDecided(False)``) lives in ``authenticated_exception_matching`` —
``matches_raise_effect`` / ``*_message_verdict`` — after authenticated
operands have been produced by sugar. Anywhere else that mints
``MatchDecided(False)`` is a second mechanism: ad-hoc Python deciding miss
outside the tree→sugar path (cardinality, isinstance kind gates, spelling).

Throwing ``SugarNotWritten`` is honorable: sugar is not written yet. Fabricating
a decided miss is the sin even when the runtime answer would have been miss.

BLIND SPOT (loud): ``tests/sourcefile_construction_door_auditor.py`` / ``sourcefile_construction_door_evidence.py`` /
``sourcefile_construction_door_symbol_graph.py`` audit SourceFile construction, privacy, and
projection closure. They do **not** scan sugar for fabricated ``MatchDecided``
mints. This file is the instrument that can see this sin class. If it is
deleted or skipped, the cluster is unguarded again.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


from sugar_lift_py_tests.repo_root import resolve_repo_root, sugar_lift_py_tests_package_root

_PKG_SRC = sugar_lift_py_tests_package_root() / "src" / "sugar_lift_py_tests"

# Sole owner of MatchDecided(False) meaning. Every other production mint is a
# second mechanism.
_ONE_MATCHER = _PKG_SRC / "authenticated_exception_matching.py"

# Production roots under this package. Tests and scripts are not meaning owners.
_PRODUCTION_ROOTS = (
    _PKG_SRC / "sugar",
    _PKG_SRC / "effect",
    _PKG_SRC / "floor",
    _PKG_SRC / "outcome",
    _PKG_SRC / "temporal",
    _PKG_SRC / "operations",
)


def _production_py_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for root in _PRODUCTION_ROOTS:
        if not root.is_dir():
            continue
        files.extend(
            path
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts and path.name != "__init__.py"
        )
    # Package-root modules that own routing/matching.
    for name in (
        "authenticated_exception_matching.py",
        "caller_parameter_contract.py",
        "effect_router.py",
        "in_flight_effect.py",
    ):
        path = _PKG_SRC / name
        if path.is_file():
            files.append(path)
    return tuple(sorted(set(files)))


def _is_match_decided_false(node: ast.AST) -> bool:
    """True when ``node`` is a Call that constructs ``MatchDecided(False)``."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        name = func.id
    elif isinstance(func, ast.Attribute):
        name = func.attr
    else:
        return False
    if name != "MatchDecided":
        return False
    if not node.args:
        return False
    arg0 = node.args[0]
    return isinstance(arg0, ast.Constant) and arg0.value is False


def _fabricated_decided_miss_sites(path: Path) -> list[tuple[Path, int, str]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    sites: list[tuple[Path, int, str]] = []
    for node in ast.walk(tree):
        if _is_match_decided_false(node):
            line = getattr(node, "lineno", 0)
            sites.append(
                (
                    path,
                    line,
                    ast.get_source_segment(source, node) or "MatchDecided(False)",
                )
            )
    return sites


def test_one_matcher_is_the_sole_match_decided_false_owner() -> None:
    """``MatchDecided(False)`` only from authenticated_exception_matching.

    Truthful: the one matcher may settle miss after authenticated operands.
    Lying: any other production module minting MatchDecided(False) is a
    fabricated decided-miss (SIN CLUSTER 1).
    """
    assert _ONE_MATCHER.is_file(), f"missing one matcher: {_ONE_MATCHER}"

    offenders: list[str] = []
    matcher_hits = 0
    for path in _production_py_files():
        sites = _fabricated_decided_miss_sites(path)
        if path.resolve() == _ONE_MATCHER.resolve():
            matcher_hits += len(sites)
            continue
        for site_path, line, snippet in sites:
            rel = site_path.relative_to(_PKG_SRC)
            offenders.append(f"{rel}:{line}: {snippet}")

    assert matcher_hits >= 1, (
        "one matcher must still mint MatchDecided(False) for real identity/message "
        "misses; instrument found zero hits in authenticated_exception_matching.py"
    )
    assert not offenders, (
        "LAW OF ONE / fabricated decided-miss: MatchDecided(False) outside the one "
        "matcher (authenticated_exception_matching). That is a second mechanism — "
        "ad-hoc Python deciding miss without tree→sugar meaning. Throw SugarNotWritten "
        "until the sugar is written; never fabricate MatchDecided.\n"
        + "\n".join(offenders)
    )


def test_sourcefile_construction_door_auditor_is_blind_to_fabricated_match_decided() -> (
    None
):
    """LOUD: repository SOURCEFILE_CONSTRUCTION_DOOR auditor does not cover this sin class.

    ``tests/sourcefile_construction_door_auditor.py`` closes SourceFile construction, privacy, and
    projection. It never walks sugar for MatchDecided mints. This assertion pins
    that gap so nobody confuses a green SOURCEFILE_CONSTRUCTION_DOOR receipt with coverage of
    fabricated decided-miss.
    """
    repo_tests = resolve_repo_root() / "tests"
    auditor = repo_tests / "sourcefile_construction_door_auditor.py"
    evidence = repo_tests / "sourcefile_construction_door_evidence.py"
    assert auditor.is_file(), auditor
    assert evidence.is_file(), evidence
    auditor_src = auditor.read_text(encoding="utf-8")
    # Positive pin: the auditor's documented axes.
    assert "SourceFile" in auditor_src
    assert "materialize_module" in auditor_src or "constructed_module" in auditor_src
    # Negative pin: it does not name this sin class.
    assert "MatchDecided" not in auditor_src, (
        "sourcefile_construction_door_auditor now mentions MatchDecided — either wire fabricated "
        "decided-miss into its receipt, or update this blindness pin"
    )
    assert "fabricated decided" not in auditor_src.lower()


def test_planted_fabricated_miss_is_detected() -> None:
    """Lying twin of the instrument: a foreign MatchDecided(False) is red."""
    planted = ast.parse(
        "def route(effect):\n"
        "    if not isinstance(effect, RaiseEffect):\n"
        "        return MatchDecided(False)\n"
        "    return MatchDecided(True)\n"
    )
    hits = [node for node in ast.walk(planted) if _is_match_decided_false(node)]
    assert len(hits) == 1

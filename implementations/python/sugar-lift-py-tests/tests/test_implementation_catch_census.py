"""Authenticated census for implementation-owned construction panic catches."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root


_KIT = sugar_lift_py_tests_package_root()
_SCRIPT = _KIT / "scripts" / "implementation_catch_census.py"
_SPEC = importlib.util.spec_from_file_location("implementation_catch_census", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_CENSUS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CENSUS)


def _write(root: Path, relative: str, source: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _measure(root: Path) -> dict[str, object]:
    return _CENSUS.measure_declared_roots(
        declared_roots=(("fixture", root),),
        measured_commit="f" * 40,
    )


def _candidate_rows(receipt: dict[str, object], hierarchy: str) -> list[dict]:
    return receipt["candidates"][hierarchy]["manifest"]


def test_exception_catches_sugar_not_written_but_not_construction_panic(
    tmp_path: Path,
) -> None:
    root = tmp_path / "src"
    _write(
        root,
        "sample.py",
        """
def sugar_gap():
    raise SugarNotWritten(blame="x", owner="o", observed="v", requested="s", fix="f")

def cp_gap():
    raise ConstructionPanic(None)

def sugar_consumer():
    try:
        sugar_gap()
    except Exception:
        return None

def cp_consumer():
    try:
        cp_gap()
    except Exception:
        return None
""",
    )

    receipt = _measure(root)

    assert receipt["status"] == "measured"
    assert _candidate_rows(receipt, "constructionPanic") == []
    snw = _candidate_rows(receipt, "sugarNotWritten")
    assert [(row["qualname"], row["reachability"], row["classification"]) for row in snw] == [
        ("sugar_consumer", "transitive", "suppression"),
        ("cp_consumer", "outside-construction", None),
    ]


def test_construction_panic_soft_catch_wraps_existing_classifier(
    tmp_path: Path,
) -> None:
    root = tmp_path / "src"
    _write(
        root,
        "bad.py",
        """
def bad():
    try:
        raise ConstructionPanic(None)
    except BaseException:
        return None
""",
    )

    receipt = _measure(root)
    row = _candidate_rows(receipt, "constructionPanic")[0]

    assert row["reachability"] == "direct"
    assert row["classification"] == "suppression"
    assert row["classifierAuthority"].endswith("construction_panic_catch_law.py")


def test_pure_reraise_is_lawful_for_both_hierarchies(tmp_path: Path) -> None:
    root = tmp_path / "src"
    _write(
        root,
        "ok.py",
        """
def cp():
    try:
        raise ConstructionPanic(None)
    except BaseException:
        raise

def snw():
    try:
        raise SugarNotWritten(blame="x", owner="o", observed="v", requested="s", fix="f")
    except Exception:
        raise
""",
    )

    receipt = _measure(root)

    assert [row["classification"] for row in _candidate_rows(receipt, "constructionPanic")] == ["lawful"]
    assert [
        (row["qualname"], row["reachability"], row["classification"])
        for row in _candidate_rows(receipt, "sugarNotWritten")
    ] == [
        ("cp", "outside-construction", None),
        ("snw", "direct", "lawful"),
    ]


def test_named_typed_conversions_are_lawful_primary_testimony(
    tmp_path: Path,
) -> None:
    root = tmp_path / "src"
    _write(
        root,
        "typed.py",
        """
def gap():
    raise SugarNotWritten(blame="x", owner="o", observed="v", requested="s", fix="f")

def typed_return():
    try:
        gap()
    except SugarNotWritten:
        return ManagerConstructionGapV1("source-body-gap")

def typed_raise():
    try:
        gap()
    except SourceTreePanic as cause:
        raise BindingStateWireGap("construction refused") from cause
""",
    )

    rows = _candidate_rows(_measure(root), "sugarNotWritten")

    assert [
        (row["qualname"], row["classification"], row["typedConversionKind"])
        for row in rows
    ] == [
        ("typed_return", "lawful", "typed-gap-return"),
        ("typed_raise", "lawful", "typed-refusal-raise"),
    ]


def test_typed_loud_transport_and_attested_obligation_are_lawful(
    tmp_path: Path,
) -> None:
    root = tmp_path / "src"
    _write(
        root,
        "transport.py",
        """
def gap():
    raise SugarNotWritten(blame="x", owner="o", observed="v", requested="s", fix="f")

def serve_forever():
    while True:
        try:
            gap()
        except SourceTreePanic as panic:
            _send({"error": {"data": {"kind": "typed-loud", "diagnostic": panic.info}}})
            continue

def enumerate_calls():
    for call in calls:
        try:
            gap()
        except (SugarNotWritten, TypeError):
            _install_opaque_call_obligation(context, call, obligation("typed-gap"))
            continue
""",
    )

    rows = _candidate_rows(_measure(root), "sugarNotWritten")

    assert [
        (row["qualname"], row["classification"], row["typedConversionKind"])
        for row in rows
    ] == [
        ("serve_forever", "lawful", "typed-loud-refusal"),
        ("enumerate_calls", "lawful", "attested-gap-obligation"),
    ]


def test_inner_bare_reraise_does_not_invent_construction_reachability(
    tmp_path: Path,
) -> None:
    root = tmp_path / "src"
    _write(
        root,
        "cache.py",
        """
def best_effort_cache():
    try:
        try:
            write_bytes()
        except Exception:
            cleanup()
            raise
    except Exception:
        return None
""",
    )

    rows = _candidate_rows(_measure(root), "sugarNotWritten")

    assert [
        (row["coordinate"]["startLine"], row["reachability"], row["classification"])
        for row in rows
    ] == [
        # The inner handler is lawful if SNW ever reaches it; its bare re-raise
        # still must not mint SNW reachability for the outer handler.
        (6, "unresolved", "lawful"),
        (9, "unresolved", None),
    ]


def test_sibling_exact_reraise_intercepts_later_broad_catch(tmp_path: Path) -> None:
    root = tmp_path / "src"
    _write(
        root,
        "precedence.py",
        """
def cp():
    try:
        raise ConstructionPanic(None)
    except ConstructionPanic:
        raise
    except BaseException:
        return None
""",
    )

    receipt = _measure(root)
    rows = _candidate_rows(receipt, "constructionPanic")

    assert len(rows) == 1
    assert rows[0]["caughtTypes"] == ["ConstructionPanic"]
    assert rows[0]["classification"] == "lawful"


def test_unrelated_broad_catch_is_outside_construction_not_suppression(
    tmp_path: Path,
) -> None:
    root = tmp_path / "src"
    _write(
        root,
        "outside.py",
        """
def parse():
    try:
        int("1")
    except Exception:
        return None
""",
    )

    row = _candidate_rows(_measure(root), "sugarNotWritten")[0]

    assert row["reachability"] == "outside-construction"
    assert row["classification"] is None


def test_dynamic_call_is_unresolved_and_not_fabricated_as_suppression(
    tmp_path: Path,
) -> None:
    root = tmp_path / "src"
    _write(
        root,
        "dynamic.py",
        """
def invoke(plugin):
    try:
        plugin.build()
    except Exception:
        return None
""",
    )

    receipt = _measure(root)
    row = _candidate_rows(receipt, "sugarNotWritten")[0]

    assert row["reachability"] == "unresolved"
    assert row["classification"] is None
    assert receipt["result"]["unresolvedCount"] == 1


def test_manifest_members_are_carried_and_equal_count_substitution_refuses(
    tmp_path: Path,
) -> None:
    root = tmp_path / "src"
    _write(root, "one.py", "try:\n    pass\nexcept Exception:\n    pass\n")
    _write(root, "two.py", "try:\n    pass\nexcept BaseException:\n    raise\n")

    receipt = _measure(root)

    assert receipt["status"] == "measured"
    assert receipt["files"]["count"] == 2
    assert len(receipt["files"]["manifest"]) == 2
    assert receipt["sites"]["count"] == 2
    assert len(receipt["sites"]["manifest"]) == 2
    assert receipt["files"]["cid"].startswith("blake3-512:")
    assert receipt["sites"]["cid"].startswith("blake3-512:")

    lying = copy.deepcopy(receipt)
    lying["sites"]["manifest"][0]["coordinate"]["startLine"] += 1
    failures = _CENSUS.validate_measured_receipt(lying)
    assert any(row["reason"] == "site manifest CID mismatch" for row in failures)


def test_missing_or_malformed_source_is_unmeasured_without_totals(
    tmp_path: Path,
) -> None:
    missing = _CENSUS.measure_declared_roots(
        declared_roots=(("missing", tmp_path / "missing"),),
        measured_commit="f" * 40,
    )
    assert missing["status"] == "unmeasured"
    assert missing["measured"] is False
    assert "result" not in missing
    assert missing["instrumentFailures"][0]["kind"] == "missing-root"

    root = tmp_path / "src"
    _write(root, "broken.py", "def broken(:\n")
    malformed = _measure(root)
    assert malformed["status"] == "unmeasured"
    assert malformed["measured"] is False
    assert "result" not in malformed
    assert malformed["instrumentFailures"][0]["kind"] == "parse-error"


def test_current_construction_panic_classifier_stays_authoritative() -> None:
    receipt = _CENSUS.measure_declared_roots(
        declared_roots=(
            ("sugar-lift-py-tests/src", _KIT / "src" / "sugar_lift_py_tests"),
            ("sugar-lift-py-tests/scripts", _KIT / "scripts"),
        ),
        measured_commit="f" * 40,
    )

    assert receipt["status"] == "measured"
    assert receipt["stageMap"]["constructionPanicClassifier"]["module"].endswith(
        "construction_panic_catch_law.py"
    )
    assert all(
        row["classification"] != "suppression"
        for row in _candidate_rows(receipt, "constructionPanic")
        if row["reachability"] in {"direct", "transitive"}
    )

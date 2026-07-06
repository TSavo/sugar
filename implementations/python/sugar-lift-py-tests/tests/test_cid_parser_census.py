# SPDX-License-Identifier: MIT OR Apache-2.0
#
# IDD instrument: hand-rolled CID/filename parsers are ILLEGAL in the Python
# kit, same doctrine as the Rust `hand_rolled_cid_parsers_are_zero_or_pinned`
# audit in implementations/rust/sugar-cli/tests/proof_api_audit.rs. CID
# format knowledge has exactly two owners in this kit:
#
#   sugar_lift_py_tests.canonicalizer.cid_hex        -- in-memory colon-form
#   sugar_lift_py_tests.filename.{cid_filename_stem,  -- on-disk filename
#                                  proof_filename,        stems
#                                  cid_filename,
#                                  cid_from_proof_stem}
#
# Every other site reimplementing the colon<->underscore transform or the
# stem-parse by hand is a side door. This census greps the whole Python
# tree for those hand-rolled shapes and pins R == 0. It is content-anchored
# (per #3492): identity is the offending line's own text, not a line number,
# so a pure reflow/reformat of an unrelated line never reddens this test --
# only a REAL new offending line does.

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # implementations/python

# Modules allowed to own CID/filename format knowledge. Everything else is a
# consumer and must route through them.
OWNER_MODULES = {
    "sugar-lift-py-tests/src/sugar_lift_py_tests/canonicalizer.py",
    "sugar-lift-py-tests/src/sugar_lift_py_tests/filename.py",
    "sugar-lift-py-tests/tests/test_cid_parser_census.py",
}


def _offending_axis(line: str) -> str | None:
    t = line.strip()
    if t.startswith("#"):
        return None
    # In-memory colon-prefix stripping by hand instead of cid_hex().
    if (
        'removeprefix("blake3-512:")' in t
        or '.lstrip("blake3-512:")' in t
        or '[len("blake3-512:") :]' in t
        or '[len("blake3-512:"):]' in t
    ):
        return "colon-prefix-strip"
    # On-disk colon-to-underscore filename transform by hand instead of
    # cid_filename_stem() / proof_filename() / cid_filename().
    if '.replace(":", "_")' in t or ".replace(':', '_')" in t:
        return "colon-to-underscore-filename-transform"
    # Stem -> CID reconstruction by hand instead of cid_from_proof_stem().
    if 'replace("blake3-512_", "blake3-512:"' in t:
        return "filename-stem-reconstruct"
    return None


def _python_sources() -> list[Path]:
    out = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if "/target/" in f"/{rel}" or rel.startswith("target/"):
            continue
        if any(part in {".venv", "venv", "__pycache__", ".git"} for part in path.parts):
            continue
        out.append(path)
    return out


def _scan() -> list[tuple[str, int, str, str]]:
    offenders = []
    for path in _python_sources():
        rel = path.relative_to(ROOT).as_posix()
        if rel in OWNER_MODULES:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(src.splitlines(), start=1):
            axis = _offending_axis(line)
            if axis is not None:
                offenders.append((rel, i, axis, line.strip()))
    offenders.sort()
    return offenders


def test_hand_rolled_cid_parsers_are_zero() -> None:
    offenders = _scan()
    assert offenders == [], (
        f"\nR(hand-rolled-cid-parsers-py) = {len(offenders)}; expected 0.\n"
        "CID format knowledge has two owners only: "
        "sugar_lift_py_tests.canonicalizer.cid_hex for in-memory colon-form CIDs, "
        "sugar_lift_py_tests.filename.{cid_filename_stem,proof_filename,cid_filename,"
        "cid_from_proof_stem} for on-disk filename stems.\n"
        f"Offenders:\n"
        + "\n".join(f"  {p}:{ln} [{ax}] {txt}" for p, ln, ax, txt in offenders)
    )


def test_census_recognizes_a_planted_offender() -> None:
    """Red-first check: the axis classifier itself must fire on each of the
    three hand-rolled shapes it claims to police, else the census above is
    silently toothless."""
    assert _offending_axis('cid.removeprefix("blake3-512:")') == "colon-prefix-strip"
    assert (
        _offending_axis('fname = cid.replace(":", "_") + ".proof"')
        == "colon-to-underscore-filename-transform"
    )
    assert (
        _offending_axis('cid = stem.replace("blake3-512_", "blake3-512:", 1)')
        == "filename-stem-reconstruct"
    )
    assert _offending_axis("x = 1  # nothing to see here") is None

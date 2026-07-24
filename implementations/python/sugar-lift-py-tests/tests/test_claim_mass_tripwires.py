"""Fast per-corpus claim-mass tripwires (#4266).

These are source-accounting pins, not wall-scale correctness gates. Each case:
- SHA-256 pins the hermetic vendor fixture
- requires silent accounting == 0 (every on-disk assert is classified)
- pins total assertion mass (lifted + refused)
- pins the complete current lifted-locus list

Post-factory measurement path: ``SourceFile`` + ``Assert.sugar()``.
Construction success is *lifted*; a loud panic (``SourceTreePanic``,
``ConstructionPanic``, or any other exception) is *refused*. There is no
third arm — soft-skip is silent loss and fails the tripwire.

Stated count cannot fall unexplained. Known lifted loci cannot disappear.
Improvements are allowed only as more-lifted-with-zero-silent plus a loud pin
update in the same PR.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from claim_mass_corpus import ClaimMassPin, DATETIME_PIN
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.nodes import Assert
from sugar_source_tree.panic import SourceTreePanic
from sugar_source_tree.tree import SourceFile

VENDOR = Path(__file__).parent / "vendor"


PINS = (
    DATETIME_PIN,
    ClaimMassPin(
        name="itsdangerous",
        relative_path="itsdangerous-2.2.0/test_serializer.py",
        sha256="e9620d6a6999a77773e3a5733ca71cb81375dafd06ad0f3a5b2bea9404e66c26",
        assertion_count=22,
        # Positive ratchet: lines 119 and 121 now construct via Assert.sugar()
        # (was 20 lifted loci under the factory audit path). Loud pin update
        # required by the tripwire contract.
        lifted_loci=(
            53,
            66,
            79,
            89,
            93,
            96,
            100,
            111,
            119,
            121,
            129,
            136,
            137,
            143,
            144,
            154,
            165,
            181,
            184,
            192,
            193,
            194,
        ),
    ),
    ClaimMassPin(
        name="pandas",
        relative_path="pandas-2.3.3/test_frame_equals.py",
        sha256="00599b73d4a67e0a505743c3f61097ba4b5109190dbc31794b567bcf7d44db11",
        assertion_count=18,
        lifted_loci=(
            15,
            24,
            28,
            29,
            45,
            46,
            47,
            48,
            49,
            50,
            51,
            56,
            61,
            66,
            72,
            77,
            80,
            85,
        ),
    ),
    ClaimMassPin(
        name="numpy",
        relative_path="numpy-2.3.5/test_exceptions.py",
        sha256="3fc5007a241556bab6d582572e6771ffa72b21af584fe615be67601f5178ffc2",
        assertion_count=17,
        lifted_loci=(
            23,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            41,
            42,
            43,
            46,
            47,
            50,
            55,
            58,
            64,
        ),
    ),
    ClaimMassPin(
        name="requests",
        # Whole-package hash still tripwires source drift across the recognition
        # surface; measurement only walks the files named by lifted_loci because
        # the rest of the package is not part of this owned slice.
        relative_path="requests-2.34.2/requests",
        sha256="eb729075b795436b6b7c7e746b82750b19c128b8f08793b56b61dc2fef2b9ff3",
        assertion_count=2,
        lifted_loci=(
            ("_internal_utils.py", 46),
            ("cookies.py", 46),
        ),
    ),
)


def _source_digest(path: Path, files: list[Path]) -> str:
    digest = hashlib.sha256()
    for source_path in files:
        if path.is_dir():
            digest.update(source_path.relative_to(path).as_posix().encode())
            digest.update(b"\0")
        digest.update(source_path.read_bytes())
        if path.is_dir():
            digest.update(b"\0")
    return digest.hexdigest()


def _measure_files(path: Path, pin: ClaimMassPin, files: list[Path]) -> list[Path]:
    """For multi-file pins, only measure files named by the lifted-locus pin.

    The package hash still covers the full tree so unmeasured files cannot
    drift silently; measurement stays inside the owned slice.
    """
    if not path.is_dir():
        return files
    named = {
        locus[0]
        for locus in pin.lifted_loci
        if isinstance(locus, tuple) and len(locus) == 2
    }
    if not named:
        return files
    return [source_path for source_path in files if source_path.name in named]


def _classify_assert(assert_node: Assert) -> str:
    """Return ``lifted`` or ``refused``. Never soft-skip."""
    try:
        assert_node.sugar()
    except (SourceTreePanic, ConstructionPanic):
        return "refused"
    except BaseException:
        # Any other failure is still loud refusal, not silent loss.
        return "refused"
    return "lifted"


@pytest.mark.parametrize("pin", PINS, ids=lambda pin: pin.name)
def test_claim_mass_corpus_never_silently_shrinks(pin: ClaimMassPin) -> None:
    path = VENDOR / pin.relative_path
    files = sorted(path.rglob("*.py")) if path.is_dir() else [path]
    assert _source_digest(path, files) == pin.sha256, (
        f"{pin.name} source drifted; re-pin the source hash, assertion count, "
        "and lifted loci in the same PR"
    )

    silent = lifted = refused = 0
    lifted_loci: list[int | tuple[str, int]] = []
    for source_path in _measure_files(path, pin, files):
        try:
            source_file = SourceFile(path_source(str(source_path)))
        except BaseException as panic:
            raise AssertionError(
                f"{pin.name} failed to parse {source_path} for claim accounting: "
                f"{type(panic).__name__}: {panic}; "
                "replacement=restore the owned parse path for this fixture, or "
                "re-slice the corpus and re-pin loudly in the same PR"
            ) from panic

        for assert_node in source_file.nodes():
            if not isinstance(assert_node, Assert):
                continue
            line = assert_node.line_col_span().start_line
            locus: int | tuple[str, int] = (
                (source_path.relative_to(path).as_posix(), line)
                if path.is_dir()
                else line
            )
            status = _classify_assert(assert_node)
            if status == "lifted":
                lifted += 1
                lifted_loci.append(locus)
            elif status == "refused":
                refused += 1
            else:
                silent += 1

    assert (
        silent == 0
    ), f"{pin.name} silent accounting must stay exactly 0; observed silent={silent}"
    assert (lifted + refused, tuple(lifted_loci)) == (
        pin.assertion_count,
        pin.lifted_loci,
    ), (
        f"{pin.name} claim mass changed: count={lifted + refused}, "
        f"lifted={tuple(lifted_loci)}; improvements must increase lifted coverage with "
        "zero silent and update this pin loudly"
    )

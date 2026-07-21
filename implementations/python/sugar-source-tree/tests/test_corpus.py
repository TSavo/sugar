"""Golden corpus: deterministic addressing, pinned quirk-shape artifact.

The pinned corpus for ``goldens/quirks.py`` is a record of what WE produce.
Regenerating it here and comparing proves the emission is a pure function of
the source — no object identity, no iteration-order dependence — and that
today's build still produces the pinned spans and CIDs. It is NOT a
cross-backend check: different parsers build different trees, and the memento
is a location hash, so addresses differ by backend by construction.

Each backend is its own identity, and they can and SHOULD produce different
trees — cpython-ast, libcst, parso and tree-sitter genuinely parse the same
source into different node streams, and CPython's ``ast`` produces different
streams across interpreter releases (e.g. 3.12 staples a spurious empty
``Constant("")`` into a nested f-string format spec; 3.14 does not). We do NOT
normalize any of that away — normalizing would erase a real difference, and the
tree is a FAITHFUL mirror of the backend, not a corrector of it. That difference
is reality, not a fact we are here to change.

So the golden is pinned PER backend fingerprint (``backend.fingerprint()`` —
name plus its version-of-record: the interpreter for cpython-ast, the library
release for a library backend). Each pin records precisely what that backend
parsed; a CID differing across fingerprints is the honest report that the parse
differed. A backend with no matching pin is a LOUD "mint me", never a silent
pass and never a fall-back to another fingerprint's tree.
"""

import json
from pathlib import Path

import pytest

from sugar_source_tree import SourceFile
from sugar_source_tree.corpus import records_for_file
from sugar_source_tree.tree import _default_backend

GOLDENS = Path(__file__).resolve().parents[1] / "goldens"


def _backend_fingerprint() -> str:
    """The identity of the backend the corpus actually parses through — the
    same default backend ``records_for_file`` uses. Identity comes FROM the
    backend, not a tag the test invents."""
    return _default_backend().fingerprint()


def _pinned_golden() -> Path:
    return GOLDENS / f"quirks.{_backend_fingerprint()}.jsonl"


def _generate() -> list[str]:
    records = records_for_file(
        SourceFile.from_path(GOLDENS / "quirks.py"), display="quirks.py"
    )
    return [json.dumps(r, sort_keys=True, ensure_ascii=True) for r in records]


def test_emission_is_deterministic():
    assert _generate() == _generate()


def test_addresses_are_unique():
    lines = _generate()
    keys = [(json.loads(l)["file"], json.loads(l)["path"]) for l in lines]
    assert len(set(keys)) == len(keys)


def test_cid_is_a_pure_function_of_source_and_span():
    source = (GOLDENS / "quirks.py").read_text(encoding="utf-8")
    import hashlib

    for line in _generate():
        rec = json.loads(line)
        segment = source[rec["start"] : rec["end"]]
        expected = "sha256:" + hashlib.sha256(segment.encode("utf-8")).hexdigest()
        assert rec["cid"] == expected


def test_pinned_golden_corpus_reproduces_byte_identically():
    golden = _pinned_golden()
    if not golden.exists():
        # A backend at a new fingerprint is a new backend. We do NOT fall back
        # to another fingerprint's pin (that would silently compare against a
        # different backend's tree) and we do NOT normalize this one to match.
        # Mint its faithful golden, once, and it becomes supported.
        available = sorted(p.name for p in GOLDENS.glob("quirks.*.jsonl"))
        pytest.fail(
            f"no pinned golden for backend {_backend_fingerprint()!r} "
            f"(expected {golden.name}). This backend parses quirks.py into its "
            f"own faithful node stream; mint its pin with:\n"
            f"    python -m sugar_source_tree.corpus goldens/quirks.py "
            f"> {golden}\n"
            f"Existing pins: {available}"
        )
    pinned = golden.read_text(encoding="utf-8").splitlines()
    assert _generate() == pinned

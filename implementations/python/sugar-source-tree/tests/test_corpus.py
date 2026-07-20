"""Golden corpus: deterministic addressing, pinned quirk-shape artifact.

``goldens/quirks.jsonl`` is the pinned corpus for ``goldens/quirks.py``.
It is a pinned record of what WE produce. Regenerating it here and
comparing proves the emission is a pure function of the source — no object
identity, no iteration-order dependence — and that today's build still
produces the pinned spans and CIDs. It is NOT a cross-backend check:
different parsers build different trees, and the memento is a location
hash, so addresses differ by backend by construction.
"""

import json
from pathlib import Path

from sugar_source_tree import SourceFile
from sugar_source_tree.corpus import records_for_file

GOLDENS = Path(__file__).resolve().parents[1] / "goldens"


def _generate() -> list[str]:
    source = (GOLDENS / "quirks.py").read_text(encoding="utf-8")
    records = records_for_file(SourceFile(filename="quirks.py", source=source))
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
    pinned = (GOLDENS / "quirks.jsonl").read_text(encoding="utf-8").splitlines()
    assert _generate() == pinned

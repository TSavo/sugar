"""A shared demand table is addressed by its preimage, not by where it lives.

THE DISCRIMINATING FACE, and the reason this file exists: moving a corpus to
another directory must produce the SAME key. A fixture keyed on a path is a
per-checkout cache wearing a CID, and it would silently stop being shared the
moment two workers had different checkouts -- which is thirteen environments
on this box today.

Every other input must move it: a source byte, path membership, the schema,
the producer's own source, the resolution configuration. Each pinned
separately, because a key that changed on all-or-nothing would hide which
input actually broke.

Mirrors `bin/sugarbin`'s `build_identity()` for the Rust binary -- authenticated
source matter in the content key, situational things in the cell path, "so a
docs-only commit cannot bust the shelf".
"""

from __future__ import annotations

import pathlib
import shutil

import pytest

from sugar_lift_py_tests.demand_table_identity import (
    DEMAND_TABLE_SCHEMA_VERSION,
    demand_table_identity,
)

_SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"


_PRODUCER_FUNCTIONS = (
    "_context_manager_demand_rows",
    "_call_contract_demand_rows",
    "_preconstruction_demand_rows",
    "provisional_contract_refs_from_demands",
)


def _producer_bodies() -> dict[str, str]:
    """The source of each function that actually builds the demand table."""
    import ast

    module = (_SOURCE_ROOT / "sugar_lift_py_tests" / "lift_rpc.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(module)
    lines = module.splitlines()
    bodies = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in _PRODUCER_FUNCTIONS:
            bodies[node.name] = "\n".join(lines[node.lineno - 1 : node.end_lineno])
    assert set(bodies) == set(_PRODUCER_FUNCTIONS), (
        f"producer functions missing from lift_rpc.py: "
        f"{set(_PRODUCER_FUNCTIONS) - set(bodies)}"
    )
    return bodies


def _corpus(root: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


_FILES = {
    "pkg/__init__.py": "",
    "pkg/mod.py": "def f(p):\n    with open(p) as handle:\n        return handle.read()\n",
}


def _identity(root: pathlib.Path, **kwargs):
    return demand_table_identity(
        root,
        sorted(root.rglob("*.py")),
        source_root=_SOURCE_ROOT,
        **kwargs,
    )


# -- the discriminating face: location is not identity ------------------------


def test_the_same_corpus_at_another_location_has_the_same_key(tmp_path) -> None:
    """THE face that proves the key was taken over the preimage.

    If this fails, the artifact is a per-checkout cache and cannot be shared --
    which defeats the entire reason for publishing it.
    """
    here = _corpus(tmp_path / "one" / "corpus", _FILES)
    there = tmp_path / "two" / "corpus"
    there.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(here, there)

    assert _identity(here).content_key == _identity(there).content_key


def test_a_deeper_relocation_still_has_the_same_key(tmp_path) -> None:
    """Depth is not identity either -- only the relative shape is."""
    here = _corpus(tmp_path / "a" / "corpus", _FILES)
    there = tmp_path / "x" / "y" / "z" / "corpus"
    there.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(here, there)

    assert _identity(here).content_key == _identity(there).content_key


# -- everything in the preimage must move the key -----------------------------


def test_a_changed_source_byte_changes_the_key(tmp_path) -> None:
    root = _corpus(tmp_path / "corpus", _FILES)
    before = _identity(root).content_key

    (root / "pkg" / "mod.py").write_text(
        _FILES["pkg/mod.py"].replace("handle.read()", "handle.readlines()"),
        encoding="utf-8",
    )

    assert _identity(root).content_key != before


def test_adding_a_file_changes_the_key(tmp_path) -> None:
    """Path MEMBERSHIP is part of the corpus, not just the bytes present."""
    root = _corpus(tmp_path / "corpus", _FILES)
    before = _identity(root).content_key

    (root / "pkg" / "extra.py").write_text("x = 1\n", encoding="utf-8")

    assert _identity(root).content_key != before


def test_renaming_a_file_changes_the_key(tmp_path) -> None:
    """Same bytes at a different RELATIVE path is a different corpus."""
    root = _corpus(tmp_path / "corpus", _FILES)
    before = _identity(root).content_key

    (root / "pkg" / "mod.py").rename(root / "pkg" / "renamed.py")

    assert _identity(root).content_key != before


def test_a_changed_resolution_config_changes_the_key(tmp_path) -> None:
    root = _corpus(tmp_path / "corpus", _FILES)

    assert _identity(root).content_key != _identity(root, config={"k": "v"}).content_key


def test_the_schema_version_is_in_the_preimage(tmp_path) -> None:
    """A consumer holding an older-schema artifact must MISS, not decode it."""
    root = _corpus(tmp_path / "corpus", _FILES)

    assert _identity(root).preimage()["schemaVersion"] == DEMAND_TABLE_SCHEMA_VERSION


def test_the_producer_source_is_in_the_preimage(tmp_path) -> None:
    """A change to the code that builds the table changes the table."""
    root = _corpus(tmp_path / "corpus", _FILES)

    assert _identity(root).preimage()["producerSourceCid"]


# -- the key is reproducible from its preimage alone --------------------------


def test_the_key_is_recomputable_from_the_preimage(tmp_path) -> None:
    """An identity whose preimage cannot re-derive it is an assertion, not an
    address. Any machine must reach the same key without this process."""
    from sugar_lift_python_source.canonical import cid_of_json

    identity = _identity(_corpus(tmp_path / "corpus", _FILES))

    assert cid_of_json(dict(identity.preimage())) == identity.content_key


# -- the measured law the key depends on --------------------------------------


def test_the_producers_perform_no_runtime_observation() -> None:
    """THE law that keeps runtime out of the content key.

    The table is a pure function of source bytes, which is why one artifact
    serves a 3.12 offload host and a 3.14 workstation. If a producer ever
    starts importing, executing, or interrogating the interpreter, the key
    becomes wrong -- and this must fail LOUDLY rather than let incompatible
    machines share a table.

    SCOPED TO THE PRODUCERS, AND HERE IS WHY. An earlier draft scanned the
    whole of `lift_rpc.py` and failed on `_cache_cardinalities`, which reads
    `sys.modules` to report cache sizes. That is telemetry about OUR OWN
    installation, it is not called by any producer, and it does not touch the
    corpus -- so scanning it tested a different claim than the one the key
    depends on. The narrowing is recorded rather than quietly applied, because
    narrowing a failing law to reach green is the exact move this suite exists
    to prevent. `test_the_named_exception_is_not_a_producer` below is what
    keeps the narrowing honest.
    """
    import re

    forbidden = re.compile(
        r"\bimportlib\b|\b__import__\b|\bexec\(|\beval\(|\bsys\.modules\b|\bpkgutil\b"
    )
    offenders = []
    for name, body in _producer_bodies().items():
        for line in body.splitlines():
            if forbidden.search(line) and not line.strip().startswith("#"):
                offenders.append(f"{name}: {line.strip()}")

    assert offenders == [], (
        "a demand-table producer now observes the runtime, so the content key "
        "must include runtime identity or the artifact cannot be shared across "
        f"interpreters: {offenders}"
    )


def test_the_named_exception_is_not_a_producer() -> None:
    """Keeps the scoping above honest.

    `_cache_cardinalities` is excluded because it is not on the production
    path. If a producer ever calls it, the exclusion becomes a hole and this
    fails -- so the narrowing cannot rot into a blind spot.
    """
    for name, body in _producer_bodies().items():
        assert "_cache_cardinalities" not in body, (
            f"{name} now calls _cache_cardinalities, which reads sys.modules; "
            "the runtime-observation law's scoping is no longer sound"
        )


# -- the correction: runtime IS in the key, until measured otherwise ----------


def test_the_parser_identity_is_in_the_preimage(tmp_path) -> None:
    """THE correction.

    An earlier version excluded runtime on two independently-traced verdicts
    that production never CALLS anything observing the interpreter. Both were
    correct and both answered the wrong question: production's OUTPUT can
    differ across interpreters with no such call, because the parse itself is
    version-dependent. `CPythonAstBackend.fingerprint` documents it and names
    3.12 versus 3.14 -- the offload host versus the workstations.
    """
    import sys

    identity = _identity(_corpus(tmp_path / "corpus", _FILES))

    assert identity.preimage()["parserIdentity"] == (
        f"{sys.implementation.name}-{sys.version_info.major}."
        f"{sys.version_info.minor}"
    )


def test_a_different_parser_identity_changes_the_key(tmp_path) -> None:
    """The tooth. Two interpreters must not share one key while it is unproven
    that they produce the same table.

    Asymmetric on purpose: a too-specific key costs a rebuild and announces
    itself as a miss; a too-loose key silently shares a table built under a
    different parser behind a valid-looking CID. Loudly-lossy over
    silently-wrong.
    """
    import sugar_lift_py_tests.demand_table_identity as module

    root = _corpus(tmp_path / "corpus", _FILES)
    here = _identity(root).content_key

    original = module.parser_identity
    module.parser_identity = lambda: "cpython-3.12"
    try:
        elsewhere = _identity(root).content_key
    finally:
        module.parser_identity = original

    assert elsewhere != here


def test_the_relaxing_condition_is_a_measurement_not_an_argument() -> None:
    """Records what would let runtime leave the key, so the next reader does
    not remove it on the strength of the two traces that were already wrong.

    The gate is: build the table for one corpus on 3.12 and on 3.14 and
    compare CIDs. Matching CIDs plus a test pinning the match is the only
    thing that earns the removal.
    """
    from sugar_lift_py_tests import demand_table_identity as module

    doc = " ".join((module.__doc__ or "").split())

    assert "RELAXING IS A MEASUREMENT, NOT AN ARGUMENT" in doc
    assert "3.12" in doc and "3.14" in doc


def test_the_reason_the_first_answer_was_wrong_is_recorded() -> None:
    """A key that mysteriously grew a field invites its own removal. The
    evidence travels with the correction."""
    from sugar_lift_py_tests import demand_table_identity as module

    # Normalized: the docstring wraps, and a phrase split across lines is
    # still the phrase. Asserting the wrapped form would pin the formatting
    # rather than the claim.
    doc = " ".join((module.__doc__ or "").split())

    assert "version-dependent node stream" in doc
    assert "answered the wrong question" in doc

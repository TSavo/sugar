# SPDX-License-Identifier: MIT OR Apache-2.0

"""A proof states every term inline (#7843).

A function that enrolls a parameter-contract link unit gets its contract from
the resume answer. That answer stated its terms by reference into a term table
it never sent, so the minted post was ``=(term-ref, term-ref)``: a post nothing
could read. The resume answer now closes over its own table, the one decoder
resolves it, mint refuses a term-ref it cannot resolve, and the verifier
refuses a proof that holds one.
"""

from __future__ import annotations

import json
from pathlib import Path

import cbor2

from sugar_lift_py_tests.witness_harness import (
    TERM_REF_BYTES,
    _stage_cli_project,
    mint_project,
)


def _contract_posts(project: Path) -> dict[str, dict]:
    (proof,) = sorted(project.glob("blake3-512_*.proof"))
    raw = proof.read_bytes()
    assert TERM_REF_BYTES not in raw
    doc = cbor2.loads(raw)

    def decode(value):
        return json.loads(value) if isinstance(value, (bytes, bytearray)) else value

    atoms = {cid: decode(value) for cid, value in doc["atoms"].items()}
    bodies = {cid: decode(value) for cid, value in doc["body"].items()}
    posts = {}
    for member in doc["members"].values():
        header = decode(member).get("header", {})
        if header.get("kind") != "contract":
            continue
        slots = bodies[header["bodyCid"]]["body"]
        if "post" in slots:
            posts[header["name"]] = atoms[slots["post"]["atomCid"]]
    return posts


def _var(name: str) -> dict:
    return {"kind": "var", "name": name}


def test_the_identity_post_is_stated_inline(tmp_path: Path) -> None:
    vendor = tmp_path / "vendor"
    _stage_cli_project(vendor, "def ident(x):\n    return x\n")
    (vendor / "test_witness.py").rename(vendor / "idn.py")
    mint = mint_project(vendor)
    assert mint.returncode == 0, mint.stderr

    post = _contract_posts(vendor)["ident"]
    assert post == {"kind": "atomic", "name": "=", "args": [_var("out"), _var("x")]}


def test_an_indexing_post_is_stated_inline(tmp_path: Path) -> None:
    # The receiver is not a formal: a formal's own subscript (``xs[0]``) is
    # decided by its caller's actual (the ``subscript`` carrier) and states
    # no post of its own.
    project = tmp_path / "linkunit"
    _stage_cli_project(
        project,
        "def consume(i):\n    return [1, 2][i]\n\n\n"
        "def test_consume():\n    assert consume(0) == 1\n",
    )
    mint = mint_project(project)
    assert mint.returncode == 0, mint.stderr

    post = _contract_posts(project)["consume"]
    assert TERM_REF_BYTES not in json.dumps(post, separators=(",", ":")).encode()
    assert post["args"][0] == _var("out")

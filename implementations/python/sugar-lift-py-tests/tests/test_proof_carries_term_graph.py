# SPDX-License-Identifier: MIT OR Apache-2.0

"""A proof carries the term graph it states (#7757).

A formula atom states each term by ``{kind: term-ref, cid}``, naming a term
row that is an atom of the same proof (a row's atom CID is its term CID), so
a term shared by both arms of a conditional is stated once, never written out
per arm. Mint refuses a term-ref whose row the ir-document lacks, the verifier
refuses a proof holding one that names no term row of its own, and every mint
through the harness is checked (``assert_proofs_carry_their_terms``). The posts
below are read written out from the proof's own rows.
"""

from __future__ import annotations

import json
from pathlib import Path

import cbor2

from sugar_lift_py_tests.witness_harness import (
    TERM_REF_BYTES,
    _stage_cli_project,
    mint_project,
    write_out_terms,
)


def _stated_contract_posts(project: Path) -> dict[str, dict]:
    """Each contract's post as its proof states it: terms by reference."""
    (proof,) = sorted(project.glob("blake3-512_*.proof"))
    raw = proof.read_bytes()
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
            posts[header["name"]] = (atoms[slots["post"]["atomCid"]], atoms)
    return posts


def _contract_posts(project: Path) -> dict[str, dict]:
    """Each contract's post written out from its proof's own term rows."""
    return {
        name: write_out_terms(post, atoms)
        for name, (post, atoms) in _stated_contract_posts(project).items()
    }


def _var(name: str) -> dict:
    return {"kind": "var", "name": name}


def _leaves(parameter: str) -> dict:
    """``python:leaves("<parameter>")``: the function never changes the
    object its parameter binds nor rebinds it, stated beside its post
    (``universe_value.LEAVES``, ``tree_enumerate.parameters_left_unchanged``)
    and read by prove's dispatch."""
    return {
        "kind": "atomic",
        "name": "python:leaves",
        "args": [
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "String"},
                "value": parameter,
            }
        ],
    }


def _out_equation(post: dict) -> dict:
    """The one ``=`` the post states of ``out``: the post itself, or one
    conjunct of it (beside ``python:leaves``)."""
    conjuncts = post["operands"] if post.get("kind") == "and" else [post]
    (equation,) = [
        conjunct
        for conjunct in conjuncts
        if conjunct.get("kind") == "atomic"
        and conjunct.get("name") == "="
        and conjunct["args"][0] == _var("out")
    ]
    return equation


def test_the_identity_post_reads_from_its_term_rows(tmp_path: Path) -> None:
    vendor = tmp_path / "vendor"
    _stage_cli_project(vendor, "def ident(x):\n    return x\n")
    (vendor / "test_witness.py").rename(vendor / "idn.py")
    mint = mint_project(vendor)
    assert mint.returncode == 0, mint.stderr

    post = _contract_posts(vendor)["python:idn.ident"]
    # ``out = x``, and ``ident`` leaves the object ``x`` binds as it was.
    assert post == {
        "kind": "and",
        "operands": [
            {"kind": "atomic", "name": "=", "args": [_var("out"), _var("x")]},
            _leaves("x"),
        ],
    }


def test_a_compound_post_is_stated_by_reference_to_its_rows(tmp_path: Path) -> None:
    # No operation on a formal: a parameter in any operand of a subscript
    # (``xs[0]``, ``[1, 2][i]``) is the undecided read, owed, and states no
    # value of its own.  A container
    # built from the formal states a compound term.
    project = tmp_path / "linkunit"
    _stage_cli_project(
        project,
        "def consume(x):\n    return [x, 2]\n\n\n"
        "def test_consume():\n    assert consume(1) == [1, 2]\n",
    )
    mint = mint_project(project)
    assert mint.returncode == 0, mint.stderr

    stated, _atoms = _stated_contract_posts(project)["python:test_witness.consume"]
    # The proof states the post's terms by reference to its own rows.
    assert TERM_REF_BYTES in json.dumps(stated, separators=(",", ":")).encode()
    post = _contract_posts(project)["python:test_witness.consume"]
    assert TERM_REF_BYTES not in json.dumps(post, separators=(",", ":")).encode()
    # Written out, ``out`` is a compound term over the formal.
    assert _out_equation(post)["args"][1] != _var("x")

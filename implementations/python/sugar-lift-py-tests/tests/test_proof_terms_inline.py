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


def test_the_identity_post_is_stated_inline(tmp_path: Path) -> None:
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


def test_a_compound_post_is_stated_inline(tmp_path: Path) -> None:
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

    post = _contract_posts(project)["python:test_witness.consume"]
    assert TERM_REF_BYTES not in json.dumps(post, separators=(",", ":")).encode()
    # The post states ``out`` inline, as a compound term over the formal.
    assert _out_equation(post)["args"][1] != _var("x")

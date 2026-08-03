"""`sugar.enumerate` is the ONE construction door for the `python-source` seat.

There is no `lift` kit method: full-tree construction is `sugar.enumerate` over
the SourceTree (#6222). These pin the two levels this kit serves, and the two
laws that make the census honest -- identity is minted through the oracle, and
a file that cannot be sealed is a first-class gap rather than a node carrying a
made-up identity.
"""

from __future__ import annotations

import json

import pytest

from sugar_lift_python_source.rpc import (
    ENUMERATE_RPC_METHOD,
    dispatch,
    kit_declaration_result,
)
from sugar_lift_python_source.source_oracle import path_source


def _enumerate(root, level, at=None, seek=False):
    params = {"level": level, "workspace_root": str(root)}
    if at is not None:
        params["at"] = at
    if seek:
        params["seek"] = True
    return dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": ENUMERATE_RPC_METHOD, "params": params}
    )


def _files(tmp_path, **sources):
    for name, body in sources.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


# ------- THE RETIRED DOOR -------


def test_lift_is_no_longer_advertised_as_a_kit_method():
    methods = {m["name"] for m in kit_declaration_result()["rpc"]["methods"]}
    assert (
        "lift" not in methods
    ), "`lift` is retired: full-tree construction is sugar.enumerate only"
    assert ENUMERATE_RPC_METHOD in methods


# ------- source_files -------


def test_source_files_censuses_every_python_file_with_oracle_identity(tmp_path):
    _files(
        tmp_path,
        **{
            "alpha.py": "def a():\n    return 1\n",
            "beta.py": "def b():\n    return 2\n",
        },
    )
    (tmp_path / "notes.txt").write_text("not python", encoding="utf-8")

    result = _enumerate(tmp_path, "source_files")["result"]

    assert [n["memento"]["file"] for n in result["nodes"]] == ["alpha.py", "beta.py"]
    assert result["gaps"] == []
    # Identity comes from the oracle door, not from hashing here.
    _source, _filename, expected_cid = path_source(str(tmp_path / "alpha.py"))
    assert result["nodes"][0]["memento"]["source_cid"] == expected_cid
    assert result["nodes"][0]["memento"]["span"] is None


def test_undecodable_file_is_a_gap_not_a_node_with_a_made_up_identity(tmp_path):
    (tmp_path / "good.py").write_text("def g():\n    return 1\n", encoding="utf-8")
    # Lone 0x80 continuation byte: readable, but not decodable as utf-8.
    (tmp_path / "bad.py").write_bytes(b"\x80")

    result = _enumerate(tmp_path, "source_files")["result"]

    assert [n["memento"]["file"] for n in result["nodes"]] == ["good.py"]
    assert len(result["gaps"]) == 1
    gap = result["gaps"][0]
    assert gap["memento"]["file"] == "bad.py"
    assert gap["memento"]["source_cid"] is None, "a gap never carries an identity"
    assert "bad.py" in gap["reason"]


def test_seek_returns_only_the_named_file(tmp_path):
    _files(
        tmp_path,
        **{
            "alpha.py": "def a():\n    return 1\n",
            "beta.py": "def b():\n    return 2\n",
        },
    )

    result = _enumerate(tmp_path, "source_files", at={"file": "beta.py"}, seek=True)[
        "result"
    ]

    assert [n["memento"]["file"] for n in result["nodes"]] == ["beta.py"]


# ------- universe -------


def test_universe_constructs_the_demanded_file(tmp_path):
    _files(
        tmp_path,
        **{
            "alpha.py": "def a(x):\n    assert x == 1\n",
            "beta.py": "def b(y):\n    assert y == 2\n",
        },
    )
    census = _enumerate(tmp_path, "source_files")["result"]
    alpha = next(
        n["memento"] for n in census["nodes"] if n["memento"]["file"] == "alpha.py"
    )

    result = _enumerate(tmp_path, "universe", at=alpha)["result"]

    assert result["nodes"], "the demanded file constructs its own rows"
    # Every row is addressed to the file that was demanded -- never a sibling.
    assert {n["memento"]["file"] for n in result["nodes"]} == {"alpha.py"}


def test_universe_rows_match_what_the_retired_lift_produced(tmp_path):
    """The one door reproduces the retired method's construction exactly."""
    _files(tmp_path, **{"alpha.py": "def a(x):\n    assert x == 1\n"})
    census = _enumerate(tmp_path, "source_files")["result"]
    alpha = census["nodes"][0]["memento"]

    through_enumerate = [
        n["audit"]
        for n in _enumerate(tmp_path, "universe", at=alpha)["result"]["nodes"]
    ]
    through_lift = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "lift",
            "params": {"workspace_root": str(tmp_path), "source_paths": ["alpha.py"]},
        }
    )["result"]["ir"]

    assert through_enumerate == through_lift


def test_universe_without_a_file_is_a_named_gap_not_an_empty_success(tmp_path):
    result = _enumerate(tmp_path, "universe", at={})["result"]

    assert result["nodes"] == []
    assert len(result["gaps"]) == 1
    assert "requires `at.file`" in result["gaps"][0]["reason"]


def test_universe_refuses_a_forged_memento_that_escapes_the_workspace(tmp_path):
    (tmp_path / "inside.py").write_text("def i():\n    return 1\n", encoding="utf-8")
    outside = tmp_path.parent / "outside_secret.py"
    outside.write_text("def secret():\n    return 1\n", encoding="utf-8")

    result = _enumerate(tmp_path, "universe", at={"file": "../outside_secret.py"})[
        "result"
    ]

    assert result["nodes"] == [], "a traversal must never enumerate outside the root"
    assert len(result["gaps"]) == 1
    assert "escapes workspace root" in result["gaps"][0]["reason"]


def test_universe_reports_a_syntax_refusal_as_a_gap(tmp_path):
    _files(tmp_path, **{"broken.py": "def a(:\n"})
    census = _enumerate(tmp_path, "source_files")["result"]
    broken = census["nodes"][0]["memento"]

    result = _enumerate(tmp_path, "universe", at=broken)["result"]

    assert result["gaps"], "a refusal is a first-class gap, not a shorter node list"
    assert "syntax-error" in json.dumps(result["gaps"])


# ------- unserved levels are LOUD -------


@pytest.mark.parametrize(
    "level", ["functions", "call_sites", "assertions", "facts", "implications"]
)
def test_an_unserved_level_is_a_loud_refusal_not_a_false_empty_census(tmp_path, level):
    response = _enumerate(tmp_path, level)

    assert (
        "result" not in response
    ), f"level {level!r} must not answer an empty census it cannot back"
    assert response["error"]["code"] == -32602
    assert level in response["error"]["message"]

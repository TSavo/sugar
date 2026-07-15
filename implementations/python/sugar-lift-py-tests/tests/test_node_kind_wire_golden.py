"""Golden byte-identity: the NodeKind flip must not move a single wire byte.

`observed` now returns NodeKind (StrEnum) instead of a bare str. The string
projection ("Name", "PrimitiveLiteral", ...) IS the wire format across
factory_gap_info, build.py, and lift_rpc DTOs. These hashes were generated
under the pre-flip baseline (origin/main d203da11f) and MUST match post-flip;
the flip was verified both ways (baseline and NodeKind builds produce the
same digests).
"""

from __future__ import annotations

import hashlib
import json

from sugar_lift_py_tests.factory.node_kind import NodeKind
from sugar_lift_py_tests.lift_rpc import audit_lift_file

_SOURCE = """\
def golden(xs, y):
    total = 0
    for x in xs:
        total = total + x * 2
    if total != y:
        return None
    name = "ok"
    return (name, total, -y)
"""

_BROKEN = """\
def broken(xs):
    match xs:
        case 0:
            return xs
    return None
"""

_PAYLOAD_SHA256 = "d3d2e1553f4b02c86ae5581443d1e1e190bb7bcd2125685820fe466cd4fff9af"
_RECOVERED_SHA256 = "ff6d1f9b937a6ca428e1a03788980ad0904e1d32cfa90b82c91ac1c77f761463"


def test_lift_report_payload_bytes_unchanged_by_nodekind_flip() -> None:
    payload, _gaps = audit_lift_file(_SOURCE, "golden.py")
    wire = json.dumps(payload.to_rpc(), sort_keys=True).encode("utf-8")
    assert hashlib.sha256(wire).hexdigest() == _PAYLOAD_SHA256


def test_recovered_audit_dto_bytes_unchanged_by_nodekind_flip() -> None:
    recovered = audit_lift_file(_BROKEN, "golden_broken.py", recover_panics=True)
    wire = json.dumps(recovered.to_rpc(), sort_keys=True).encode("utf-8")
    assert hashlib.sha256(wire).hexdigest() == _RECOVERED_SHA256


def test_nodekind_json_and_format_projection_is_the_bare_string() -> None:
    # StrEnum guarantees the wire projection: json, str(), and f-strings all
    # emit the historical string, never "NodeKind.NAME".
    assert json.dumps({"observed": NodeKind.NAME}) == '{"observed": "Name"}'
    assert f"{NodeKind.PRIMITIVE_LITERAL}" == "PrimitiveLiteral"
    assert str(NodeKind.BLOCK) == "Block"

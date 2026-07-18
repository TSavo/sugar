"""Golden wire projection for structural NodeKind observations.

The string projection ("Name", "Constant", ...) is the wire format across
factory_gap_info, build.py, and lift_rpc DTOs. Semantic literal ownership is
carried by the selected Sugar, not by a fabricated factory node kind.
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

_PAYLOAD_SHA256 = "84779f488c3b5e9649f61352853bbf66c343bd0dd76d5e2599b533be90a125f4"
_RECOVERED_SHA256 = "fbb0b7662e8045d0f0804f60bd4f094f56c1951626bb0c2913ff52c71a39240c"


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

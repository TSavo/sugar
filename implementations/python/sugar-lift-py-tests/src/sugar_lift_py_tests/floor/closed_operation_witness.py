from __future__ import annotations

import sys
from dataclasses import dataclass

from sugar_lift_py_tests.canonicalizer import (
    blake3_512_of,
    encode_jcs,
    varr,
    vint,
    vobj,
    vstr,
)
from sugar_lift_py_tests.ir import Term, _term_content_cid

_CLOSED_OPERATIONS = frozenset(
    {
        "python.issubclass",
        "python.isinstance",
        "python.len",
        "python.set.contains",
        "python.set.union",
        "python.set.intersection",
        "python.set.difference",
        "python.set.construct",
        "python.tuple.construct",
    }
)


@dataclass(frozen=True)
class PythonRuntimeIdentity:
    implementation: str
    major: int
    minor: int

    @classmethod
    def current(cls) -> "PythonRuntimeIdentity":
        return cls(
            sys.implementation.name, sys.version_info.major, sys.version_info.minor
        )


@dataclass(frozen=True)
class ClosedSemanticOperationWitness:
    runtime: PythonRuntimeIdentity
    operation: str
    operand_cids: tuple[str, ...]
    result_cid: str
    witness_cid: str

    @classmethod
    def mint(
        cls,
        runtime: PythonRuntimeIdentity,
        operation: str,
        operands: tuple[Term, ...],
        result: Term,
    ) -> "ClosedSemanticOperationWitness":
        if operation not in _CLOSED_OPERATIONS:
            raise ValueError(f"unsupported closed semantic operation: {operation}")
        operand_cids = tuple(_term_content_cid(term) for term in operands)
        result_cid = _term_content_cid(result)
        witness_cid = _witness_cid(runtime, operation, operand_cids, result_cid)
        return cls(runtime, operation, operand_cids, result_cid, witness_cid)

    def verify(
        self,
        runtime: PythonRuntimeIdentity,
        operation: str,
        operands: tuple[Term, ...],
        result: Term,
    ) -> None:
        expected = ClosedSemanticOperationWitness.mint(
            runtime, operation, operands, result
        )
        if self != expected:
            raise ValueError(
                "closed semantic operation witness does not authenticate operands, result, runtime identity, and operation"
            )


def _witness_cid(
    runtime: PythonRuntimeIdentity,
    operation: str,
    operand_cids: tuple[str, ...],
    result_cid: str,
) -> str:
    body = vobj(
        [
            ("operation", vstr(operation)),
            ("operands", varr([vstr(cid) for cid in operand_cids])),
            ("result", vstr(result_cid)),
            (
                "runtime",
                vobj(
                    [
                        ("implementation", vstr(runtime.implementation)),
                        ("major", vint(runtime.major)),
                        ("minor", vint(runtime.minor)),
                    ]
                ),
            ),
        ]
    )
    return blake3_512_of(encode_jcs(body).encode("utf-8"))

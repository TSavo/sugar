"""Mint a language-owned ``_io`` resource contract from an export gap."""

from __future__ import annotations

import json

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.context_manager_contract import (
    EnterResultContractV1,
    ExitContractV1,
    ImportSignatureV2,
    NeverSuppressesDispositionV1,
    ProtocolResourceSemanticsV1,
    import_signature_to_value,
    semantics_to_value,
)
from sugar_lift_py_tests.context_manager_resolution import (
    LanguageOwnedContextManagerRefV1,
)
from sugar_lift_py_tests.floor.closed_operation_witness import PythonRuntimeIdentity
from sugar_lift_py_tests.floor.language_owned_io_resource import (
    LanguageOwnedIoResourceProtocol,
    is_language_owned_io_resource_gap,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_python_source.canonical import cid_of_json


def mint_language_owned_io_resource_ref(coordinate, receipt, resolved):
    """Publish the IOBase protocol when export resolution names ``_io``.

    Returns ``None`` when the gap is not a language-owned ``_io`` resource, so
    the caller can keep the ordinary derivation gap.
    """
    if not is_language_owned_io_resource_gap(resolved):
        return None
    exported_name = resolved.exported_name
    runtime = PythonRuntimeIdentity.current()
    protocol = LanguageOwnedIoResourceProtocol(
        exported_name=exported_name,
        runtime=runtime,
    )
    semantics = ProtocolResourceSemanticsV1(
        EnterResultContractV1(PrimitiveSort("Value")),
        ExitContractV1(NeverSuppressesDispositionV1()),
    )
    signature = ImportSignatureV2(())
    preimage = {
        "kind": "language-owned-io-resource-summary",
        "schemaVersion": "1",
        "moduleName": "_io",
        "exportedName": exported_name,
        "runtime": {
            "implementation": runtime.implementation,
            "major": runtime.major,
            "minor": runtime.minor,
        },
        "semantics": json.loads(encode_jcs(semantics_to_value(semantics))),
        "importSignature": json.loads(encode_jcs(import_signature_to_value(signature))),
        "targetSymbol": receipt.target_symbol,
        "useSite": coordinate.wire(),
    }
    return LanguageOwnedContextManagerRefV1(
        use_site=coordinate,
        summary_cid=cid_of_json(preimage),
        semantics=semantics,
        import_signature=signature,
        protocol=protocol,
        target_symbol=receipt.target_symbol,
        exported_name=exported_name,
    )

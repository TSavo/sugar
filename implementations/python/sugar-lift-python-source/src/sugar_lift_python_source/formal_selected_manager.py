"""Seat the formal-selected manager law at ``with p.m():`` / ``with self.x:``.

See ``sugar_lift_py_tests.floor.formal_selected_manager`` for the law.
"""

from __future__ import annotations

import json

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.context_manager_contract import (
    EnterResultContractV1,
    ExitContractV1,
    FormalManagerCallFacesCompletionV1,
    ImportSignatureV2,
    ProtocolResourceSemanticsV1,
    ReturnTruthinessDispositionV1,
    import_signature_to_value,
    semantics_to_value,
)
from sugar_lift_py_tests.context_manager_resolution import (
    FormalManagerRefV1,
)
from sugar_lift_py_tests.floor.formal_selected_manager import (
    FormalSelectedManagerProtocol,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_python_source.canonical import cid_of_json


def mint_formal_selected_manager_ref(coordinate, head: str):
    """The opaque two-faced manager ref for one formal-rooted With head."""
    site = coordinate.wire()
    site_key = json.dumps(site, sort_keys=True) if not isinstance(site, str) else site
    protocol = FormalSelectedManagerProtocol(
        head=head, site=site_key, coordinate=coordinate
    )
    # Each step completes with an opaque result or halts with an
    # UndeterminedRaiseEffect.
    semantics = ProtocolResourceSemanticsV1(
        EnterResultContractV1(
            PrimitiveSort("Value"), FormalManagerCallFacesCompletionV1()
        ),
        ExitContractV1(
            ReturnTruthinessDispositionV1(), FormalManagerCallFacesCompletionV1()
        ),
    )
    signature = ImportSignatureV2(())
    target_symbol = f"python:formal:{head}"
    preimage = {
        "kind": "formal-selected-manager-summary",
        "schemaVersion": "1",
        "head": head,
        "semantics": json.loads(encode_jcs(semantics_to_value(semantics))),
        "importSignature": json.loads(encode_jcs(import_signature_to_value(signature))),
        "targetSymbol": target_symbol,
        "useSite": site,
    }
    return FormalManagerRefV1(
        use_site=coordinate,
        summary_cid=cid_of_json(preimage),
        semantics=semantics,
        import_signature=signature,
        protocol=protocol,
        target_symbol=target_symbol,
        exported_name=head,
    )

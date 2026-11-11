"""Mint a C-owned context-manager contract from an ``artifact-module-absent`` gap.

``with decimal.localcontext() as ctx:`` resolves to ``_decimal.localcontext``,
a builtin function of an interpreter C module with no source in any artifact.
The contract is keyed on runtime identity, never on a name table or a use-site
spelling: the export must be a ``builtin_function_or_method`` bound to the very
module object it resolved to, and that module must be interpreter-owned
(``sys.builtin_module_names`` or a stdlib ``lib-dynload`` extension).

The published law is ``LanguageOwnedCManagerProtocol``: ``__enter__`` and
``__exit__`` are two-faced C calls (opaque result, or an
``UndeterminedRaiseEffect`` halt), and suppression is ``py.truthy`` of the
opaque exit result. ``_pydecimal`` is never read as the semantics of
``_decimal``.
"""

from __future__ import annotations

import importlib
import json
import sys
import types

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.context_manager_contract import (
    EnterResultContractV1,
    ExitContractV1,
    ImportSignatureV2,
    LanguageOwnedCCallFacesCompletionV1,
    ProtocolResourceSemanticsV1,
    ReturnTruthinessDispositionV1,
    import_signature_to_value,
    semantics_to_value,
)
from sugar_lift_py_tests.context_manager_resolution import (
    LanguageOwnedContextManagerRefV1,
)
from sugar_lift_py_tests.floor.closed_operation_witness import PythonRuntimeIdentity
from sugar_lift_py_tests.floor.language_owned_c_manager import (
    LanguageOwnedCManagerProtocol,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_python_source.canonical import cid_of_json


def _interpreter_owned_c_function(module_name, exported_name):
    """Return the runtime C function, or ``None`` when identity does not hold."""
    from .dependency_export_adapter import _is_stdlib_extension_module

    if not isinstance(module_name, str) or not isinstance(exported_name, str):
        return None
    if module_name not in sys.builtin_module_names and not _is_stdlib_extension_module(
        module_name
    ):
        return None
    try:
        module = importlib.import_module(module_name)
        obj = getattr(module, exported_name)
    except (ImportError, AttributeError, TypeError, ValueError):
        return None
    if type(obj) is not types.BuiltinFunctionType or obj.__self__ is not module:
        return None
    return obj


def mint_language_owned_c_manager_ref(coordinate, receipt, resolved):
    """Publish the C-owned protocol, or ``None`` to keep the derivation gap."""
    if getattr(resolved, "kind", None) != "artifact-module-absent":
        return None
    module_name = getattr(resolved, "module_name", None)
    exported_name = getattr(resolved, "exported_name", None)
    if _interpreter_owned_c_function(module_name, exported_name) is None:
        return None
    return _c_manager_ref(coordinate, module_name, exported_name, receipt.target_symbol)


def mint_builtin_c_manager_ref(coordinate, name, source):
    """``with open(...)``: the head calls a builtin that is a C function.

    The name must read the builtin at every load in ``source`` (the module
    binds it nowhere), and ``builtins.<name>`` must be the very C function that
    its own interpreter-owned module exports (``builtins.open`` is
    ``_io.open``).  Returns ``None`` otherwise, keeping the require door.
    """
    import builtins

    from sugar_source_tree.builtin_reference import module_reads_builtin

    if not module_reads_builtin(source, name):
        return None
    obj = getattr(builtins, name)
    if type(obj) is not types.BuiltinFunctionType or not isinstance(
        obj.__self__, types.ModuleType
    ):
        return None
    module_name = obj.__self__.__name__
    exported_name = obj.__name__
    if _interpreter_owned_c_function(module_name, exported_name) is not obj:
        return None
    return _c_manager_ref(coordinate, module_name, exported_name, f"python:builtins.{name}")


def _c_manager_ref(coordinate, module_name, exported_name, target_symbol):
    runtime = PythonRuntimeIdentity.current()
    protocol = LanguageOwnedCManagerProtocol(
        module_name=module_name,
        exported_name=exported_name,
        runtime=runtime,
    )
    semantics = ProtocolResourceSemanticsV1(
        EnterResultContractV1(
            PrimitiveSort("Value"), LanguageOwnedCCallFacesCompletionV1()
        ),
        ExitContractV1(
            ReturnTruthinessDispositionV1(), LanguageOwnedCCallFacesCompletionV1()
        ),
    )
    signature = ImportSignatureV2(())
    preimage = {
        "kind": "language-owned-c-manager-summary",
        "schemaVersion": "1",
        "moduleName": module_name,
        "exportedName": exported_name,
        "runtime": {
            "implementation": runtime.implementation,
            "major": runtime.major,
            "minor": runtime.minor,
        },
        "semantics": json.loads(encode_jcs(semantics_to_value(semantics))),
        "importSignature": json.loads(encode_jcs(import_signature_to_value(signature))),
        "targetSymbol": target_symbol,
        "useSite": coordinate.wire(),
    }
    return LanguageOwnedContextManagerRefV1(
        use_site=coordinate,
        summary_cid=cid_of_json(preimage),
        semantics=semantics,
        import_signature=signature,
        protocol=protocol,
        target_symbol=target_symbol,
        exported_name=exported_name,
    )

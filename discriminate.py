import sys

sys.path.insert(0, "implementations/python/sugar-lift-py-tests/src")

from sugar_lift_py_tests.floor.import_alias_value import (
    _resolve_static_module_attribute_chain,
)
from sugar_lift_py_tests.sugar.install_source_dig import native_extension_class_origin

arm = sys.argv[1]

if arm == "import_alias_cycle":
    # Force the guard: pre-seed `resolving` with the cycle_key this exact
    # call will compute (module_name.name), so the guard fires immediately.
    _resolve_static_module_attribute_chain(
        "os", ["path"], resolving=frozenset({"os.path"})
    )
elif arm == "import_alias_normal":
    receiver = _resolve_static_module_attribute_chain("json", ["JSONDecoder"])
    assert receiver is not None and receiver.kind == "class", receiver
    print("OK", receiver)
elif arm == "native_origin_cycle":
    native_extension_class_origin("io.BytesIO", frozenset({"io.BytesIO"}))
elif arm == "native_origin_normal":
    origin = native_extension_class_origin("io.BytesIO")
    assert origin is not None, origin
    print("OK", origin)
else:
    raise SystemExit(f"unknown arm {arm}")

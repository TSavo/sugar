from __future__ import annotations

from sugar_lift_py_tests.recognition.native_shape import (
    NativeShape,
    recognize_native_class_import,
)


def class_value_supports_generic_subscription(value) -> bool:
    """Recognize inherited generic subscription from carried floor evidence."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.class_value import ClassValue
    from sugar_lift_py_tests.floor.import_alias_value import ImportAliasValue

    worklist = [value]
    visited: set[int] = set()
    while worklist:
        current = worklist.pop()
        identity = id(current)
        if identity in visited:
            continue
        visited.add(identity)
        for base in current.bases:
            if type(base) is ClassValue:
                worklist.append(base)
                continue
            if (
                type(base) is not CallSiteValue
                or base.target_name != "py.subscript"
                or len(base.arg_values) != 2
            ):
                continue
            receiver = base.arg_values[0]
            if type(receiver) is ClassValue:
                worklist.append(receiver)
                continue
            if type(receiver) is not ImportAliasValue:
                continue
            coordinate = receiver.import_target or receiver.name
            module, separator, name = coordinate.rpartition(".")
            if (
                separator
                and recognize_native_class_import(module, name)
                is NativeShape.GENERIC_CLASS
            ):
                return True
    return False

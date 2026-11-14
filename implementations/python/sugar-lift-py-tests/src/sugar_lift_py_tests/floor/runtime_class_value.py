from __future__ import annotations

from dataclasses import dataclass

from .class_value import ClassValue


@dataclass(frozen=True)
class RuntimeClassValue(ClassValue):
    """Class object minted by authenticated ``type.__new__`` arguments."""

    namespace: object = None

    def _namespace_entries(self):
        if hasattr(self.namespace, "mapping_entries"):
            return self.namespace.mapping_entries()
        return self.namespace.entries

    def attribute(self, name, site, ctx):
        from sugar_lift_py_tests.floor.dict_value import DictValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.outcome import ExitSet

        if name == "__dict__":
            return ExitSet.completed(DictValue(self._namespace_entries()))
        if name == "__mro__":
            return ExitSet.completed(TupleValue((self, *self.bases)))
        for key, value in reversed(self._namespace_entries()):
            if getattr(key, "value", object()) == name:
                return ExitSet.completed(value)
        return super().attribute(name, site, ctx)

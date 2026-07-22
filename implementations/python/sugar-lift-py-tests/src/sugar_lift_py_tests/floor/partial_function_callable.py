from __future__ import annotations

from dataclasses import dataclass

from .function_callable import FunctionCallable


@dataclass(frozen=True)
class PartialFunctionCallable(FunctionCallable):
    """A construction-closed ``functools.partial`` of a source callable.

    The target callable remains the sole owner of its body.  This floor only
    carries Python's pre-bound positional/keyword arguments into that existing
    callsite; it never invents a replacement body.
    """

    target: FunctionCallable | None = None
    bound_positional: tuple = ()
    bound_keyword_names: tuple[str, ...] = ()
    bound_keyword_values: tuple = ()

    def callsite(
        self,
        arg_values,
        keyword_names,
        site,
        *,
        source_arg_values=None,
        term=None,
        native_shape=None,
    ):
        from sugar_lift_py_tests.gap.panic import factory_panic_gap

        if self.target is None:
            factory_panic_gap(
                owner=type(self).__name__,
                blame=str(site),
                observed="missing partial target",
                requested="factory-constructed callable target",
                fix="construct functools.partial from a resolved FunctionCallable",
            )

        call_keyword_count = len(keyword_names)
        call_positional = (
            tuple(arg_values[:-call_keyword_count])
            if call_keyword_count
            else tuple(arg_values)
        )
        call_keyword_values = (
            tuple(arg_values[-call_keyword_count:]) if call_keyword_count else ()
        )
        merged_names = list(self.bound_keyword_names)
        merged_values = list(self.bound_keyword_values)
        for name, value in zip(keyword_names, call_keyword_values, strict=True):
            if name in merged_names:
                merged_values[merged_names.index(name)] = value
            else:
                merged_names.append(name)
                merged_values.append(value)

        assert self.target is not None
        # Forward the authenticated recognition coordinate — never drop
        # native_shape (signature drift leaked bare TypeError on vendor walls).
        return self.target.callsite(
            (
                *self.bound_positional,
                *call_positional,
                *merged_values,
            ),
            tuple(merged_names),
            site,
            source_arg_values=source_arg_values,
            term=term,
            native_shape=native_shape,
        )

from __future__ import annotations

from dataclasses import dataclass, replace

from .function_callable import FunctionCallable


@dataclass(frozen=True)
class AsyncFunctionCallable(FunctionCallable):
    """An async function coordinate whose bare call cannot replay its body."""

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
        from sugar_lift_py_tests.outcome import Complete

        # Match FunctionCallable's proof-bearing callsite protocol so an
        # authenticated native_shape coordinate is never a bare TypeError.
        return (
            super()
            .callsite(
                arg_values,
                keyword_names,
                site,
                source_arg_values=source_arg_values,
                term=term,
                native_shape=native_shape,
            )
            .and_then(lambda call: Complete(replace(call, body=None)))
        )

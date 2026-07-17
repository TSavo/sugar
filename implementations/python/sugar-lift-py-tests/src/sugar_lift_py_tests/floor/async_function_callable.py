from __future__ import annotations

from dataclasses import dataclass, replace

from .function_callable import FunctionCallable


@dataclass(frozen=True)
class AsyncFunctionCallable(FunctionCallable):
    """An async function coordinate whose bare call cannot replay its body."""

    def callsite(self, arg_values, keyword_names, site, *, source_arg_values=None):
        from sugar_lift_py_tests.outcome import Complete

        return (
            super()
            .callsite(
                arg_values,
                keyword_names,
                site,
                source_arg_values=source_arg_values,
            )
            .and_then(lambda call: Complete(replace(call, body=None)))
        )

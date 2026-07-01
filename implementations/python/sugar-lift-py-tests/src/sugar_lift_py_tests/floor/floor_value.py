from __future__ import annotations


class FloorValue:
    def inplace_binary_operator_with(self, operation, ctx):
        return operation.inplace_default(self, ctx)

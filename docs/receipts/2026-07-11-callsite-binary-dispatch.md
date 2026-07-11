# CallSiteValue binary dispatch

## Law
AddOpSugar calls `left.add(right)` — floor surface, not walk if-tree.
CallSiteValue must totalize `add` (and friends): dig body then redispatch, else
EUF `+(left, right)` via SymbolicValue. Never invent a concrete sum.

## Shipped
1. **CallSiteValue.add / subtract / multiply** → dig-or-symbolic binop
2. **SymbolicValue.add / subtract** → EUF join (mirror multiply)
3. **Attachable** widened: Assign* + Return; BinOp/Call return exprs
4. **SequentialDigBody** for multi-stmt method dig under formals

## Tests
`test_callsite_binary_dispatch` + method dig → 11 passed

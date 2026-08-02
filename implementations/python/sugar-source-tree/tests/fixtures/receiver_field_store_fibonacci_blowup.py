# Permanent regression seed: combinatorial ReceiverFieldStoreState blowup.
#
# Source: pandas/tests/test_nanops.py TestnanopsDataFrame.setup_method
# (seal stuck 35+ min @ 99.8% CPU after #7099 removed TypeError abort).
#
# Mechanism: each `self.aN = …` becomes ReceiverFieldStoreStatement binding
# `self` to ReceiverFieldStoreState(receiver=<prior self state>, value=RHS).
# RHS reads of self.* share the prior state (DAG). walk() without a seen-set
# treated that DAG as a tree → ~3× node visits per sequential store.
#
# Twelve fib-shaped self-field stores: no numpy, no complex, no *args.
# With DAG-correct walk (visit-once), construct is linear in statement count.

class C:
    def setup_method(self):
        self.a0 = 1
        self.a1 = self.a0
        self.a2 = self.a1 + self.a0
        self.a3 = self.a2 + self.a1
        self.a4 = self.a3 + self.a2
        self.a5 = self.a4 + self.a3
        self.a6 = self.a5 + self.a4
        self.a7 = self.a6 + self.a5
        self.a8 = self.a7 + self.a6
        self.a9 = self.a8 + self.a7
        self.a10 = self.a9 + self.a8
        self.a11 = self.a10 + self.a9

"""Known-constructed with-item plant (mr_blue conservation tooth).

The smoke harness injects SourceDerivedContextManagerRef at the live use-site
after open — same type With construction consumes — so constructed>0 is a real
tally, not a hardcoded scoreboard number.
"""


def consume(mgr):
    with mgr:
        pass

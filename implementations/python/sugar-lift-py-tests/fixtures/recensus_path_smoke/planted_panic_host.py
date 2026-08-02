"""Host file for the known-panic plant.

The smoke harness measures this file under a ConstructionPanic inject at
SourceFile construction so cpanic=1 is projected through the production
_measure_file door (not invented at board compose).
"""


def a():
    return 1

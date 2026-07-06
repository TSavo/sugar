# The bad twin: a pandas consumer whose Series.sum assertion contradicts the
# imported vendor universe.

import pandas as pd


def test_sum_contradictory():
    df = pd.DataFrame({"a": [1, 2, 3]})
    total = df["a"].sum()
    assert total == 7

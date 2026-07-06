# The consistent companion: a pandas consumer whose Series.sum assertion agrees
# with the imported vendor universe.

import pandas as pd


def test_sum_consistent():
    df = pd.DataFrame({"a": [1, 2, 3]})
    total = df["a"].sum()
    assert total == 6

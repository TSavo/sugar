def A():
    ((q_raw, tau), r, *rest) = ((2, 3), 4, 5, 6)
    return q_raw + tau + r + rest[0] + rest[1]


def test_a():
    assert A() == 19

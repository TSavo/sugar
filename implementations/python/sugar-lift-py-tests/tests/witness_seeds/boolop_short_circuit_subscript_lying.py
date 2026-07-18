def A():
    values = []
    if values and values[-1] != ":":
        return 1
    return 0


def test_short_circuit_subscript():
    assert A() == 1

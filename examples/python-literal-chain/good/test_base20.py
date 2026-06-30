def h(x):
    return x + 1


def g(x):
    return h(x)


def test_base20():
    assert g(5) == 6

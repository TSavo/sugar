def A():
    if {1: 2}:
        return 7
    return 9


def test_dict_truth():
    assert A() == 7

def encode20(value):
    alphabet = "ABCDEFGHIJKLMNOPQRST"
    b0 = ord(value[0])
    return alphabet[b0 & 15] + alphabet[(b0 >> 4) & 15]


def test_encode20():
    assert encode20("A") == "AA"

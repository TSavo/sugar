import struct

def test_true():
    assert struct.calcsize("!I") == 4

def test_lie():
    assert struct.calcsize("!I") == 8

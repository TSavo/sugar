import binascii

def test_true():
    assert binascii.hexlify(b"x") == b"78"

def test_lie():
    assert binascii.hexlify(b"x") == b"00"

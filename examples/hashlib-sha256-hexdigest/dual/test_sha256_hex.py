import hashlib

def test_true():
    assert hashlib.sha256(b"x").hexdigest() == "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"

def test_lie():
    assert hashlib.sha256(b"x").hexdigest() == "00"

import hashlib

def test_true():
    assert len(hashlib.sha256(b"x").digest()) == 32

def test_lie():
    assert len(hashlib.sha256(b"x").digest()) == 16

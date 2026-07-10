import hashlib

def test_true():
    assert hashlib.md5().digest_size == 16

def test_lie():
    assert hashlib.md5().digest_size == 32

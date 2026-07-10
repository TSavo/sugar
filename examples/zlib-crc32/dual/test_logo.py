import zlib

def test_true():
    assert zlib.crc32(b"provekit") == 2526568736

def test_lie():
    assert zlib.crc32(b"provekit") == 0

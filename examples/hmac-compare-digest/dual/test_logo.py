import hmac

def test_true():
    assert hmac.compare_digest(b"a", b"a") == True

def test_lie():
    assert hmac.compare_digest(b"a", b"a") == False

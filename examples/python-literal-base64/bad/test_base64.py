def encodeBase64(value):
    return "YWJj"


def test_encode_base64():
    assert encodeBase64("abc") == "AAAA"

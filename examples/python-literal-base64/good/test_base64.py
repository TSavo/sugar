def encodeBase64(value):
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    b0 = ord(value[0])
    b1 = ord(value[1])
    b2 = ord(value[2])
    return (
        alphabet[b0 >> 2]
        + alphabet[((b0 & 3) << 4) | (b1 >> 4)]
        + alphabet[((b1 & 15) << 2) | (b2 >> 6)]
        + alphabet[b2 & 63]
    )


def test_encode_base64():
    assert encodeBase64("abc") == "YWJj"

import base64

def encode_nopad(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")

def test_token_padding():
    assert encode_nopad(b"provekit") == b"cHJvdmVraXQ="
